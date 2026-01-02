from abc import ABC, abstractmethod

from protolink.server.endpoint_handler import EndpointSpec


class BackendInterface(ABC):
    @abstractmethod
    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register all HTTP routes for the given transport instance."""

        raise NotImplementedError()

    @abstractmethod
    async def start(self, url: str) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    def _get_host_port(self, url: str) -> tuple[str | None, int | None]:
        """Extract host and port from a full URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url.rstrip("/"))
        return parsed.hostname, parsed.port
