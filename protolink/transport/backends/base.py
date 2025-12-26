from abc import ABC, abstractmethod

from protolink.models import EndpointSpec


class BackendInterface(ABC):
    @abstractmethod
    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register all HTTP routes for the given transport instance."""

        raise NotImplementedError()

    @abstractmethod
    async def start(self, host: str, port: int) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
