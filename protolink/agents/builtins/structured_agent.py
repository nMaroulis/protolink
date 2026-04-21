from typing import Any, Literal, cast

from protolink.agents.base import Agent
from protolink.client import RegistryClient
from protolink.discovery import Registry
from protolink.flows import Flow, Pipeline
from protolink.models import AgentCard, Task
from protolink.storage import Storage
from protolink.transport import Transport
from protolink.types import TransportType


class StructuredAgent(Agent):
    """
    An agent that routes a Task deterministically through a predefined sequence of other agents,
    unlike a standard agent which relies on an LLM to decide routing dynamically.

    This essentially acts as a structured flow pipeline, packaged as an A2A-compliant agent.
    """

    def __init__(
        self,
        card: dict[str, Any] | AgentCard,
        flow: Flow | list[str],
        transport: TransportType | Transport | None = None,
        registry: TransportType | Registry | RegistryClient | None = None,
        registry_url: str | None = None,
        storage: Storage | None = None,
        verbosity: Literal[0, 1, 2] = 1,
    ) -> None:
        """Initialize the structured agent.

        Args:
            card: AgentCard or dict describing this agent's identity.
            flow: The underlying `Flow` to execute (e.g., `Pipeline`, `Graph`).
                For backwards compatibility and convenience, passing a `list[str]` automatically mounts
                a `Pipeline`.
            transport: Transport layer definition.
            registry: Registry definition.
            registry_url: Registry URL.
            storage: Storage layer.
            verbosity: Logging verbosity.
        """
        super().__init__(
            card=card,
            transport=transport,
            registry=registry,
            registry_url=registry_url,
            storage=storage,
            verbosity=verbosity,
        )

        # Transparent conversion if a simple list sequence is passed
        if isinstance(flow, list):
            self._logger.warning(
                "Initializing StructuredAgent with a list of steps is legacy behavior. Creating Pipeline automagically."
            )
            self.flow: Flow = Pipeline(steps=cast(list[Agent | str], flow))
        else:
            self.flow = flow

        # Hook agent's internal dispatchers onto the flow
        self.flow.client = self.client
        self.flow.registry_client = self.registry_client

    async def handle_task(self, task: Task) -> Task:
        """
        Execute the task deterministically through the agent's encapsulated flow logic.
        Overrides the default Base Agent behavior which relies on explicit Parts or the LLM.
        """
        self._logger.debug(f"StructuredAgent '{self.card.name}' starting execution of task: {task.id}")

        current_task = await self.flow.execute(task)

        self._logger.debug(f"StructuredAgent '{self.card.name}' completed task: {task.id}")
        return current_task
