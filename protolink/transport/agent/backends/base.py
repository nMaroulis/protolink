from __future__ import annotations

from typing import Any

"""Common interface for HTTP transport backends.

This small protocol-like base class is implemented by concrete backends such
as :class:`StarletteBackend` and :class:`FastAPIBackend`. It defines the
minimal surface area required by :class:`HTTPTransport` to:

* register HTTP routes on the underlying ASGI application
* start and stop the HTTP server
"""


class BackendInterface:
    """Abstract interface for HTTP server backends used by ``HTTPTransport``."""

    app: Any  # Underlying ASGI application instance (Starlette or FastAPI)

    def setup_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821, UP037
        """Register all HTTP routes for the given transport instance."""

        raise NotImplementedError()

    async def start(self, host: str, port: int) -> None:
        """Start the backend HTTP server bound to ``host:port``."""

        raise NotImplementedError()

    async def stop(self) -> None:
        """Stop the backend HTTP server and release any resources."""

        raise NotImplementedError()
