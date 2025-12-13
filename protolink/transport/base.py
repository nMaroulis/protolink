"""
ProtoLink - Transport Layer

Transport layer for Agent-to-Agent (A2A), Agent-to-Registry (A2R), and Registry-to-Agent (R2A) communication.
"""

from abc import ABC, abstractmethod


class Transport(ABC):
    """Abstract base class for transport implementations."""

    @abstractmethod
    async def start(self) -> None:
        """Start the transport server.

        For server-side transports, this should start listening for incoming requests.
        For client-only transports, this can be a no-op.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport server.

        For server-side transports, this should stop listening and clean up resources.
        For client-only transports, this can be a no-op.
        """
        pass
