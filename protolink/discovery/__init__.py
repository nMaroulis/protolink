"""Agent discovery and registration for the A2A protocol.

This module provides functionality for agents to discover and register with
a central registry, enabling them to find and communicate with each other.
"""

from .registry import Registry, RegistryClient
from .service import DiscoveryService, DiscoveryClient

__all__ = ["Registry", "RegistryClient", "DiscoveryService", "DiscoveryClient"]
