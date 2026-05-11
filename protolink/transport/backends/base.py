from abc import ABC, abstractmethod

from protolink.server.endpoint_handler import EndpointSpec


class BackendInterface(ABC):
    @abstractmethod
    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register all abstract endpoints onto the physical ASGI routing table.

        Subclasses must implement this to iterate over the provided `EndpointSpec` models
        and mount them as concrete HTTP routes within their specific web framework
        (e.g., Starlette or FastAPI).
        """
        raise NotImplementedError()

    @abstractmethod
    async def start(self, url: str) -> None:
        """Initialize and spin up the underlying ASGI HTTP server daemon.

        Implementations should bind to the parsed host/port from the provided `url`
        and execute the server loop inside an isolated `asyncio.Task`.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully terminate the ASGI HTTP server daemon.

        Implementations must signal the server to exit, gracefully complete any
        in-flight connections, and safely `await` the background server task until closure.
        """
        ...

    def _get_host_port(self, url: str) -> tuple[str | None, int | None]:
        """Extract host and port integers from an absolute URI string."""
        from urllib.parse import urlparse

        parsed = urlparse(url.rstrip("/"))
        return parsed.hostname, parsed.port
