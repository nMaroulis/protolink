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

from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from protolink.client.request_spec import ClientRequestSpec
from protolink.security.auth import Authenticator
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport.backends import BackendInterface, FastAPIBackend, StarletteBackend
from protolink.transport.base import Transport
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
    """

    transport_type: ClassVar[TransportType] = "http"
    supports_streaming: ClassVar[bool] = False

    def __init__(
        self,
        url: str,
        timeout: float = 60.0,
        authenticator: Authenticator | None = None,
        backend: BackendType = "starlette",
        *,
        validate_schema: bool = False,
    ) -> None:
        """Initialize the HTTP transport and underlying ASGI server framework.

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
        """
        self._url: str = url
        self._timeout: float = timeout
        self.authenticator: Authenticator | None = authenticator
        self.security_context: object | None = None
        # Handlers that are called for different Server Requests

        # Loop-aware client connection pool: dict[id(event_loop), httpx.AsyncClient]
        # This prevents cross-loop contamination when the transport is used as both a
        # server (in a background thread) and a client (in the main thread).
        self._clients: dict[int, httpx.AsyncClient] = {}

        # Select backend implementation.
        if backend.lower() == "fastapi":
            self.backend: BackendInterface = FastAPIBackend(validate_schema=validate_schema)
        else:
            self.backend = StarletteBackend()

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
        client = await self._ensure_client()
        headers = self._build_headers()

        # Build URL
        url = f"{base_url.rstrip('/')}{request_spec.path}"

        # Prepare request arguments
        kwargs: dict[str, Any] = {"headers": headers}
        if params:
            kwargs["params"] = params

        if request_spec.request_source == "body" and data is not None:
            # Handle Pydantic models automatically
            if hasattr(data, "to_json"):
                kwargs["json"] = data.to_json()
            elif hasattr(data, "to_dict"):
                kwargs["json"] = data.to_dict()
            elif isinstance(data, BaseModel):
                kwargs["json"] = data.model_dump()
            elif isinstance(data, dict):
                kwargs["json"] = data
            else:
                # TODO: Fallback/Error? Assuming dict or compatible
                kwargs["json"] = data
        elif request_spec.request_source == "query_params" and data is not None:
            # Send data as query parameters
            if isinstance(data, dict):
                kwargs["params"] = data
            else:
                # For single values, wrap in dict
                kwargs["params"] = {"data": str(data)}

        try:
            response = await client.request(request_spec.method, url, timeout=self._timeout, **kwargs)
            response.raise_for_status()

            # Parse response
            if request_spec.response_parser:
                return request_spec.response_parser(response.json())
            return response.json()

        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Failed to connect to agent at {base_url}. Make sure the agent is running and accessible."
            ) from e
        except httpx.RemoteProtocolError as e:
            raise ConnectionError(
                f"Protocol error when communicating with agent at {base_url}. "
                f"The target may not be a proper HTTP server or may be misconfigured."
            ) from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Agent at {base_url} returned HTTP {e.response.status_code}: {e.response.text}") from e

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Return an initialized :class:`httpx.AsyncClient` instance for the current loop.

        Dynamically isolates and caches connection pools keyed by the ID of the currently
        running ``asyncio`` event loop. This ensures that concurrent requests made from
        the main thread and the isolated background server thread do not attempt to share
        the same underlying sockets or locks, avoiding `Future attached to a different loop`
        exceptions.
        """
        import asyncio

        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if not client or client.is_closed:
            client = httpx.AsyncClient(timeout=self._timeout)
            self._clients[loop_id] = client
        return client

    # ------------------------------------------------------------------
    # Server Routing
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Mount the configured Protolink endpoints onto the underlying ASGI framework.

        This method delegates to the selected web framework abstraction (e.g., ``StarletteBackend``
        or ``FastAPIBackend``) which binds the abstract ``EndpointSpec`` models into tangible
        RESTful routes on the underlying server application.
        """
        self.backend.setup_routes(endpoints)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot the background ASGI server and prime the client connection pool.

        When invoked, this kicks off the ``uvicorn`` or alternative ASGI server lifecycle configured
        by the active backend. Immediately afterward, it eagerly provisions an ``httpx.AsyncClient``
        pool dedicated strictly to the caller's event loop to guarantee safe outbound communications.
        """

        # Start the HTTP server
        await self.backend.start(self._url)

        # Initialize HTTP client for the current loop
        import asyncio

        loop_id = id(asyncio.get_running_loop())
        self._clients[loop_id] = httpx.AsyncClient(timeout=self._timeout)

    async def stop(self) -> None:
        """Stop the HTTP server and gracefully close all isolated HTTP client pools."""

        await self.backend.stop()
        for client in self._clients.values():
            if not client.is_closed:
                await client.aclose()
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
            if hasattr(context, "token"):
                headers["Authorization"] = f"Bearer {context.token}"
        return headers

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
