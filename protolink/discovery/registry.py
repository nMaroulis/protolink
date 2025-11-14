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
        registry = Registry()

        # Register agents
        registry.register_agent(agent1.get_agent_card())
        registry.register_agent(agent2.get_agent_card())

        # Discover agents
        all_agents = registry.discover_agents()
        specific_agent = registry.get_agent("agent-name")
    """

    def __init__(self):
        """Initialize empty registry."""
        self.agents: dict[str, AgentCard] = {}

    def register_agent(self, agent_card: AgentCard) -> None:
        """Register an agent in the registry.

        Args:
            agent_card: AgentCard to register
        """
        # Register by both URL and name for flexible lookup
        self.agents[agent_card.url] = agent_card
        self.agents[agent_card.name] = agent_card

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the registry.

        Args:
            agent_id: Agent URL or name
        """
        if agent_id in self.agents:
            agent_card = self.agents[agent_id]
            # Remove both URL and name entries
            self.agents.pop(agent_card.url, None)
            self.agents.pop(agent_card.name, None)

    def get_agent(self, agent_id: str) -> AgentCard | None:
        """Get an agent card by URL or name.

        Args:
            agent_id: Agent URL or name

        Returns:
            AgentCard if found, None otherwise
        """
        return self.agents.get(agent_id)

    def discover_agents(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Discover all agents or filter by criteria.

        Args:
            filter_by: Optional filter criteria (e.g., {"capabilities.streaming": True})

        Returns:
            List of matching AgentCards
        """
        # Get unique agents (avoid duplicates from name/url entries)
        unique_agents = {}
        for card in self.agents.values():
            unique_agents[card.url] = card

        agents = list(unique_agents.values())

        # Apply filters if provided
        if filter_by:
            filtered = []
            for agent in agents:
                match = True
                for key, value in filter_by.items():
                    # Support nested keys like "capabilities.streaming"
                    if "." in key:
                        parts = key.split(".")
                        obj = agent
                        for part in parts[:-1]:
                            obj = getattr(obj, part, {})
                        actual_value = obj.get(parts[-1]) if isinstance(obj, dict) else getattr(obj, parts[-1], None)
                    else:
                        actual_value = getattr(agent, key, None)

                    if actual_value != value:
                        match = False
                        break

                if match:
                    filtered.append(agent)

            return filtered

        return agents

    def list_agents(self) -> list[str]:
        """List all registered agent URLs.

        Returns:
            List of agent URLs
        """
        unique_agents = {}
        for card in self.agents.values():
            unique_agents[card.url] = card

        return list(unique_agents.keys())

    def count(self) -> int:
        """Get the number of registered agents.

        Returns:
            Number of unique agents
        """
        unique_agents = {}
        for card in self.agents.values():
            unique_agents[card.url] = card

        return len(unique_agents)

    def clear(self) -> None:
        """Remove all agents from the registry."""
        self.agents.clear()

    def __repr__(self) -> str:
        return f"Registry(agents={self.count()})"
