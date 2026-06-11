from dataclasses import dataclass

from .agent_card import AgentCard


@dataclass
class RegistryEntry:
    card: AgentCard
    last_seen: float
