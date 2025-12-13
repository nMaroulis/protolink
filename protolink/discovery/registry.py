"""
ProtoLink - Agent Registry

Registry for agent discovery and catalog management.
"""

from typing import Any

from protolink.core.agent_card import AgentCard


class Registry:
    """Registry for managing and discovering agents.

    Provides a central catalog of available agents with discovery capabilities.
    Can be used for both local and remote agent registries.

    Example:
        registry = Registry("http://localhost:8000")

        # Register agents
        registry.register(agent1.get_agent_card())
        registry.register(agent2.get_agent_card())

        # Discover agents
        all_agents = registry.discover()
        specific_agent = registry.get("agent-name")
    """

    def __init__(self, url: str):
        """Initialize empty registry."""
        self._agents: dict[str, AgentCard] = {}
        self.url: str = url

    # ----------------------------------------------------------------------
    # Registration
    # ----------------------------------------------------------------------

    def register(self, card: AgentCard) -> None:
        """Register an agent in the registry.

        Args:
            card: AgentCard to register
        """
        # Register by URL
        self._agents[card.url] = card

    def unregister(self, agent_url: str) -> None:
        """Remove an agent from the registry.

        Args:
            agent_url: Agent URL
        """
        if agent_url in self._agents:
            self._agents.pop(agent_url, None)

    # ----------------------------------------------------------------------
    # Lookup
    # ----------------------------------------------------------------------

    def get(self, agent_url: str) -> AgentCard | None:
        """Get an agent card by URL or name.

        Args:
            agent_url: Agent URL

        Returns:
            AgentCard if found, None otherwise
        """
        return self._agents.get(agent_url)

    # ----------------------------------------------------------------------
    # Discovery
    # ----------------------------------------------------------------------

    def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Discover all agents or filter by criteria.

        Args:
            filter_by: Optional filter criteria (e.g., {"capabilities.streaming": True})

        Returns:
            List of matching AgentCards
        """
        # Get unique agents (avoid duplicates from name/url entries)
        agents = list(self._agents.values())

        # Apply filters if provided
        if filter_by:
            pass

        return agents

    # ----------------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------------

    def list_urls(self) -> list[str]:
        """List all registered agent URLs.

        Returns:
            List of agent URLs
        """
        return list(self._agents.keys())

    def count(self) -> int:
        """Get the number of registered agents.

        Returns:
            Number of unique agents
        """
        return len(self._agents)

    def clear(self) -> None:
        """Remove all agents from the registry."""
        self._agents.clear()

    def __repr__(self) -> str:
        return f"Registry(agents={self.count()})"
