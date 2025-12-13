# protolink/transport/registry/backends/base.py

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protolink.transport.registry.http import HTTPRegistryTransport


class RegistryBackendInterface(ABC):
    @abstractmethod
    def setup_routes(self, transport: "HTTPRegistryTransport") -> None: ...

    @abstractmethod
    async def start(self, host: str, port: int) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
