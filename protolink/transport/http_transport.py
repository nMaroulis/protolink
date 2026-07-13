"""HTTP Transport Implementation - Distributed Agent Communication.

This module provides the :class:`HTTPTransport`, which serves as the primary physical
network boundary for Protolink agents. It facilitates the bidirectional transmission of
``Task`` and ``Message`` structures over standard HTTP protocols.

**Architecture:**
- **Server Role**: Dynamically mounts an ASGI application (using either the ``Starlette``
  or ``FastAPI`` backend) to listen for incoming JSON payloads from external networks.
- **Client Role**: Leverages ``httpx.AsyncClient`` to serialize local domain objects and
  dispatch them as outbound HTTP requests.
- **Event Loop Isolation**: Implements strict loop-aware connection pooling, allowing a single
  transport instance to act as a background server on one thread while concurrently acting
  as an outbound client on the main thread without triggering `asyncio` loop contamination.
"""

import asyncio
import json
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from protolink.client.request_spec import ClientRequestSpec
from protolink.security.auth import Authenticator
from protolink.security.tls import TLSConfig
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport.backends import BackendInterface, FastAPIBackend, StarletteBackend
from protolink.transport.base import Transport, TransportRequestContext
from protolink.transport.config import TransportCapabilities, TransportConfig
from protolink.transport.errors import (
    TransportConnectionError,
    TransportProtocolError,
    TransportRemoteError,
    TransportTimeoutError,
)
from protolink.types import BackendType, TransportType


class HTTPTransport(Transport):
    """HTTP-based transport for Protolink agents.

    This transport supports dual-role execution (Server and Client). Because Protolink
    executes agents using isolated background threads when ``background=True``, a single
    ``HTTPTransport`` instance may be accessed by multiple ``asyncio`` event loops concurrently.
    For example, the background thread's loop handles server endpoints and registry registration,
    while the main thread's loop handles client requests (e.g., ``call_agent``).

    To prevent `asyncio` cross-loop contamination, this transport utilizes loop-aware
    connection pooling. HTTP client connection pools (via ``httpx.AsyncClient``) are lazily
    instantiated and strictly isolated per event loop.

    Parameters
    ----------
    url:
        URL for the HTTP server (e.g. ``"http://localhost:8000"``).
    timeout:
        Request timeout (in seconds) for the internal HTTP client.
    authenticator:
        Optional authenticator for securing requests.
    backend:
        Backend implementation to use (``"starlette"`` or ``"fastapi"``).
    validate_schema:
        Whether to validate request/response schemas.
    tls:
        Optional TLS certificate and trust configuration. Use an ``https://``
        server URL to enable TLS.
    config:
        Shared limits, retry, keepalive, shutdown, idempotency, and metrics settings.
    """

    transport_type: ClassVar[TransportType] = "http"
    supports_streaming: ClassVar[bool] = False
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(
        tls=True,
        persistent_connections=True,
    )

    def __init__(
        self,
        url: str,
        timeout: float = 360.0,
        authenticator: Authenticator | None = None,
        backend: BackendType = "starlette",
        *,
        validate_schema: bool = False,
        credentials: str | None = None,
        tls: TLSConfig | None = None,
        config: TransportConfig | None = None,
        log_level: str = "info",
        access_log: bool = True,
    ) -> None:
        """Initialize the HTTP client/server transport and ASGI backend.

        Args:
            url: The absolute URL (e.g., ``"http://localhost:8000"``) dictating both the
                 server's binding interface and its advertised identity in the registry.
            timeout: The maximum duration (in seconds) to await outbound HTTP requests
                     before raising a timeout exception.
            authenticator: An optional cryptographic provider for validating inbound
                           requests and signing outbound headers.
            backend: The specific ASGI abstraction layer (``"starlette"`` or ``"fastapi"``)
                     used to construct the physical server routing table.
            validate_schema: If true, instructs the selected backend (such as FastAPI)
                             to enforce strict Pydantic model validation on inbound payloads.
            tls: Optional transport-security configuration for HTTPS and mutual TLS.
            config: Shared production transport behavior.
            log_level: Uvicorn log level.
            access_log: Whether Uvicorn emits request access logs.
        """
        super().__init__(config=config)
        self._url: str = url
        self._timeout: float = timeout
        self.authenticator: Authenticator | None = authenticator
        self.credentials: str | None = credentials
        self.tls = tls
        self.security_context: object | None = None
        # Handlers that are called for different Server Requests

        # Loop-aware client connection pool: dict[id(event_loop), httpx.AsyncClient]
        # This prevents cross-loop contamination when the transport is used as both a
        # server (in a background thread) and a client (in the main thread).
        self._clients: dict[int, httpx.AsyncClient] = {}

        # Select backend implementation.
        if backend.lower() == "fastapi":
            self.backend: BackendInterface = FastAPIBackend(
                validate_schema=validate_schema,
                log_level=log_level,
                access_log=access_log,
                keepalive_timeout=self.config.keepalive_timeout,
                limit_concurrency=self.config.limits.max_concurrent_requests,
            )
        else:
            self.backend = StarletteBackend(
                log_level=log_level,
                access_log=access_log,
                keepalive_timeout=self.config.keepalive_timeout,
                limit_concurrency=self.config.limits.max_concurrent_requests,
            )

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    async def send(
        self, request_spec: ClientRequestSpec, base_url: str, data: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        """Dispatch an outbound HTTP request to a remote agent endpoint.

        This method marshals a high-level ``ClientRequestSpec`` (which encapsulates HTTP verb,
        path, and expected payload schemas) into a physical HTTP request. It utilizes the loop-isolated
        connection pool (via ``_ensure_client()``) to safely execute the request without event loop
        contamination.

        It automatically normalizes complex data models (like Pydantic's ``BaseModel`` or Protolink
        DataClasses) into JSON-compatible dictionaries depending on whether the target endpoint
        expects a JSON body (``request_source="body"``) or query parameters (``request_source="query_params"``).

        Raises
        ------
        ConnectionError
            If the remote agent is unreachable or the protocol is invalid.
        RuntimeError
            If the remote endpoint returns a non-200 HTTP status code.
        """
        url = f"{base_url.rstrip('/')}{request_spec.path}"
        request_size = self.check_payload_limit({"data": data, "params": params}, kind="request", url=url)
        context = self.new_request_context(request_spec, data)

        async def operation(attempt: TransportRequestContext) -> Any:
            if self.authenticator and self.credentials and not self.security_context:
                await self.authenticate(self.credentials)

            client = await self._ensure_client()
            headers = {
                **self._build_headers(),
                "X-Protolink-Request-ID": attempt.request_id,
            }
            if attempt.idempotency_key:
                headers["Idempotency-Key"] = attempt.idempotency_key

            kwargs: dict[str, Any] = {"headers": headers}
            if params:
                kwargs["params"] = params
            if request_spec.request_source == "body" and data is not None:
                kwargs["json"] = self._serialize_payload(data)
            elif request_spec.request_source == "query_params" and data is not None:
                kwargs["params"] = data if isinstance(data, dict) else {"data": str(data)}

            try:
                self._metrics.add(bytes_sent=request_size)
                response = await client.request(request_spec.method, url, timeout=self._timeout, **kwargs)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise TransportTimeoutError(
                    f"HTTP request to {base_url} timed out",
                    url=url,
                    request_id=attempt.request_id,
                    retryable=True,
                ) from exc
            except httpx.ConnectError as exc:
                raise TransportConnectionError(
                    f"Failed to connect to agent at {base_url}. Make sure the agent is running and accessible.",
                    url=url,
                    request_id=attempt.request_id,
                    retryable=True,
                ) from exc
            except httpx.RemoteProtocolError as exc:
                raise TransportProtocolError(
                    f"Protocol error when communicating with agent at {base_url}",
                    url=url,
                    request_id=attempt.request_id,
                    retryable=True,
                ) from exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                raise TransportRemoteError(
                    f"Agent at {base_url} returned HTTP {status}: {exc.response.text}",
                    url=url,
                    request_id=attempt.request_id,
                    retryable=status == 429 or status >= 500,
                    status_code=status,
                ) from exc

            response_size = len(response.content)
            if response_size > self.config.limits.max_response_bytes:
                self.check_payload_limit(response.text, kind="response", url=url)
            self._metrics.add(bytes_received=response_size)
            try:
                payload = response.json()
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise TransportProtocolError(
                    f"Agent at {base_url} returned invalid JSON",
                    url=url,
                    request_id=attempt.request_id,
                ) from exc
            return request_spec.response_parser(payload) if request_spec.response_parser else payload

        async with self.request_slot():
            return await self.run_with_retries(request_spec, context, operation)

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Return an initialized :class:`httpx.AsyncClient` instance for the current loop.

        Dynamically isolates and caches connection pools keyed by the ID of the currently
        running ``asyncio`` event loop. This ensures that concurrent requests made from
        the main thread and the isolated background server thread do not attempt to share
        the same underlying sockets or locks, avoiding `Future attached to a different loop`
        exceptions.
        """
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if not client or client.is_closed:
            client = self._create_client()
            self._clients[loop_id] = client
            self.register_loop_resource(
                ("http", loop_id),
                client.aclose,
            )
        return client

    def _create_client(self) -> httpx.AsyncClient:
        """Create an HTTP client using configured TLS trust and identity."""
        limits = httpx.Limits(
            max_connections=self.config.limits.max_concurrent_requests,
            max_keepalive_connections=self.config.limits.max_concurrent_requests,
            keepalive_expiry=self.config.keepalive_interval,
        )
        if self.tls is None:
            return httpx.AsyncClient(timeout=self._timeout, limits=limits)
        return httpx.AsyncClient(timeout=self._timeout, limits=limits, verify=self.tls.create_client_context())

    # ------------------------------------------------------------------
    # Server Routing
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Mount the configured Protolink endpoints onto the underlying ASGI framework.

        This method delegates to the selected web framework abstraction (e.g., ``StarletteBackend``
        or ``FastAPIBackend``) which binds the abstract ``EndpointSpec`` models into tangible
        RESTful routes on the underlying server application.
        """
        self.backend.setup_routes(endpoints, authenticator=self.authenticator, transport=self)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot the background ASGI server and eagerly prime the loop-isolated client pool.

        This method initializes the dual-role nature of the transport. It first kicks off the configured ASGI server
        (e.g., Uvicorn) to handle inbound traffic. Immediately following, it provisions an ``httpx.AsyncClient``
        dedicated to the caller's current event loop.

        **Technical Note on Eager Provisioning:**
        By instantiating the client pool during ``start()``, we guarantee that the transport is fully warmed for
        outbound communication before the method returns. This is critical in multi-threaded Protolink environments
        (like background agents) where the server-side loop must be able to immediately dispatch registry registration
        requests or delegation calls without the overhead or potential race conditions of lazy initialization.

        The use of an ID-keyed pool (``self._clients``) ensures that this eagerly created client is strictly bound to
        the current thread's loop selector, preventing cross-loop boundary violations.
        """

        if self._transport_running:
            return
        await self.backend.start(self._url, tls=self.tls)
        self._transport_running = True

        await self._ensure_client()

    async def stop(self) -> None:
        """Stop the HTTP server and gracefully close the loop-isolated HTTP client pool.

        This method orchestrates a multi-layered shutdown. First, it terminates the ASGI server backend.
        Second, it performs a loop-safe cleanup of outbound connection pools.

        **Technical Note on Loop Isolation:**
        In Protolink's multi-threaded architecture, a single ``HTTPTransport`` instance is frequently shared across
        multiple ``asyncio`` event loops (e.g., a background server thread and the main execution thread).
        Because ``asyncio`` primitives, including the sockets and selectors within ``httpx.AsyncClient``, are strictly
        bound to the loop that instantiated them, attempting to close a client from a different loop triggers
        a ``RuntimeError`` ("Event loop is closed" or "Future attached to a different loop").

        To resolve this, we utilize an ID-keyed connection pool. This method only ``aclose()``'s the client associated
        with the *caller's* current event loop, ensuring that shutdown logic never violates loop boundaries or attempts
        to interact with a potentially defunct selector from another thread.
        """

        if self._transport_running:
            await self.backend.stop()
            self._transport_running = False
        await self.close_loop_resources()
        self._clients.clear()

    # ------------------------------------------------------------------
    # Authentication & Security
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: str) -> None:
        """Validate and construct an authentication security context.

        Delegates the raw credentials payload to the injected ``Authenticator`` strategy. If successful,
        stores the resulting security context (e.g., Bearer tokens) in memory. This context is subsequently
        injected into the HTTP headers of all outbound client requests handled by ``_build_headers()``.

        Raises
        ------
        RuntimeError
            If no authentication provider has been configured.
        """

        if not self.authenticator:
            raise RuntimeError("No Authenticator configured")

        self.security_context = await self.authenticator.authenticate(credentials)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Construct the baseline HTTP headers for outbound requests.

        Automatically interrogates the active ``security_context``. If a Bearer token is present,
        it seamlessly applies the ``Authorization`` header to ensure zero-trust compliance on
        remote endpoints.
        """
        headers: dict[str, str] = {}
        if self.authenticator and self.security_context:
            # Type guard: we know security_context is not None here
            context = self.security_context
            token = getattr(context, "token", None)
            if token:
                scheme = getattr(self.authenticator, "security_scheme", None)
                if scheme:
                    if scheme.auth_type == "http":
                        if scheme.auth_scheme == "basic":
                            headers["Authorization"] = f"Basic {token}"
                        elif scheme.auth_scheme == "bearer":
                            headers["Authorization"] = f"Bearer {token}"
                        else:
                            headers["Authorization"] = f"{scheme.auth_scheme.capitalize()} {token}"
                    elif scheme.auth_type == "apiKey":
                        headers["X-API-Key"] = token
                        headers["Authorization"] = f"ApiKey {token}"
                    else:
                        headers["Authorization"] = f"Bearer {token}"
                else:
                    headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _serialize_payload(data: Any) -> Any:
        """Normalize a request body into JSON-compatible data."""
        if hasattr(data, "to_json"):
            return data.to_json()
        if hasattr(data, "to_dict"):
            return data.to_dict()
        if isinstance(data, BaseModel):
            return data.model_dump()
        return data

    def validate_url(self) -> bool:
        """Ensure the target endpoint utilizes standard web protocols (http/https)."""
        if self._url.startswith("http://") or self._url.startswith("https://"):
            return True
        return False

    @property
    def url(self) -> str:
        """Retrieve the canonical network address assigned to this transport endpoint."""
        return self._url

    @property
    def timeout(self) -> float:
        """Retrieve the configured maximum duration (in seconds) for outbound network operations."""
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        """Dynamically reconfigure the maximum duration for outbound network operations.

        Note: Currently, mutating this property will only affect newly instantiated connection
        pools. Existing, active ``httpx.AsyncClient`` instances tied to active event loops
        will retain their original configuration.
        """
        self._timeout = value
