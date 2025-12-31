"""HTTP transport implementation for talking to remote Protolink agents.

This module exposes :class:`HTTPTransport`, which sends and receives
``Task`` and ``Message`` objects over plain HTTP using either a Starlette
or FastAPI backend for the server side.
"""

from typing import Any, ClassVar
from urllib.parse import urlparse

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

    Parameters
    ----------
    host:
        Host interface for the HTTP server to bind to when running as a
        server (e.g. ``"0.0.0.0"``).
    port:
        Port the HTTP server listens on.
    timeout:
        Request timeout (in seconds) for the internal HTTP client.
    authenticator:
        Optional authentication provider used to obtain auth context.
    backend:
        Name of the HTTP backend implementation to use. Currently
        ``"starlette"`` (default) and ``"fastapi"`` are supported.
    validate_schema:
        When using the FastAPI backend, controls whether incoming
        requests are validated with Pydantic models.
    """

    def __init__(
        self,
        url: str,
        timeout: float = 30.0,
        authenticator: Authenticator | None = None,
        backend: BackendType = "starlette",
        *,
        validate_schema: bool = False,
    ) -> None:
        self.transport_type: ClassVar[TransportType] = "http"
        self.url = url
        self._set_from_url(url)
        self.timeout: float = timeout
        self.authenticator: Authenticator | None = authenticator
        self.security_context: object | None = None
        # Handlers that are called for different Server Requests
        self._client: httpx.AsyncClient | None = None

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
        """Send a request to an agent endpoint."""
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
            response = await client.request(request_spec.method, url, **kwargs)
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
        """Return an initialized :class:`httpx.AsyncClient` instance."""

        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    # ------------------------------------------------------------------
    # Server Routing
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Setup the routes for the HTTP server."""
        self.backend.setup_routes(endpoints)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the HTTP server and initialize the HTTP client."""

        # Start the HTTP server
        await self.backend.start(self.host, self.port)

        # Initialize HTTP client
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def stop(self) -> None:
        """Stop the HTTP server and close the underlying HTTP client."""

        await self.backend.stop()
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Authentication & Security
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: str) -> None:
        """Authenticate using the configured :class:`Authenticator`.

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
        """Build HTTP headers for an outgoing request.

        Includes authentication headers when an auth context is present.
        """

        headers: dict[str, str] = {}

        if self.authenticator and self.security_context:
            headers["Authorization"] = f"Bearer {self.security_context.token}"

        return headers

    def validate_agent_url(self, agent_url: str) -> bool:
        """Validate an agent URL.

        Parameters
        ----------
        agent_url:
            Agent URL to validate.

        Returns
        -------
        bool
            ``True`` if the URL is allowed, ``False`` otherwise.
        """

        allowed = {
            f"http://{self.host}:{self.port}",
            f"https://{self.host}:{self.port}",
        }

        return agent_url in allowed

    # TODO(): Do this in the backend
    def _set_from_url(self, url: str) -> None:
        """Populate host, port, and canonical url from a full URL."""
        parsed = urlparse(url.rstrip("/"))
        self.host = parsed.hostname
        self.port = parsed.port
