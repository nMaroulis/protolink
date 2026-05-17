import asyncio
from abc import ABC, abstractmethod

from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task
from protolink.types import FlowTarget
from protolink.utils.logging import get_logger


class Flow(ABC):
    """Abstract base class for all structured flows in Protolink.

    Flows provide deterministic orchestration of Tasks between agents.
    Unlike standard Agents that may rely on LLMs for dynamic routing, flows mandate strict execution paths
    (Sequential, Parallel, Graph, etc.).

    Key features:
    - **Composability**: Flows can be nested within each other (e.g., a Parallel block inside a Pipeline).
    - **Centralized Dispatch**: Execution logic is handled by `_execute_target`, supporting local Agents, remote agent
      URLs/names, and nested Flow instances.
    - **Resource Propagation**: Parent flows automatically propagate their `AgentClient` and `RegistryClient` to
      nested flows if they are unconfigured.

    All flows accept an `AgentClient` for execution and optionally a `Registry` for discovering agents by name.
    """

    def __init__(
        self,
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize the Flow.

        Args:
            client: The `AgentClient` instance required to send tasks to remote agents.
                If not provided, the flow will attempt to instantiate one from the registry.
            registry: A `Registry` or `RegistryClient` used to discover agents by their name instead of requiring
                      absolute URLs.
        """
        self.client = client
        self.registry_client: RegistryClient | None = None

        if registry:
            if isinstance(registry, Registry):
                self.registry_client = registry.client
            elif isinstance(registry, RegistryClient):
                self.registry_client = registry

        self._logger = get_logger("protolink.flows")
        self.sync = SyncFlow(self)

    @abstractmethod
    async def execute(self, task: Task) -> Task:
        """Execute the flow on a given task.

        Args:
            task: The `Task` to be processed through the flow.

        Returns:
            The resulting `Task` after all flow steps have been executed.
            The Task will contain appended Messages and Artifacts from the journey.
        """
        pass

    async def _resolve_agent_url(self, agent_name_or_url: str) -> str:
        """Resolve a string to a valid agent URL.

        If the string is already a valid URL (http, ws, runtime), it is returned.
        Otherwise, a registry lookup is performed to find the matching agent.

        Args:
            agent_name_or_url: The URL or registry name of the target agent.

        Returns:
            str: The fully qualified URL of the agent.

        Raises:
            ValueError: If the agent name cannot be resolved or if no registry is provided.
        """
        if (
            agent_name_or_url.startswith("http://")
            or agent_name_or_url.startswith("https://")
            or agent_name_or_url.startswith("ws://")
            or agent_name_or_url.startswith("wss://")
            or agent_name_or_url.startswith("runtime://")
        ):
            return agent_name_or_url

        if not self.registry_client:
            raise ValueError(
                f"Cannot resolve agent name '{agent_name_or_url}' without a registry configured in the flow definition."
            )

        discovered = await self.registry_client.discover()
        for agent in discovered:
            if agent.name == agent_name_or_url:
                return agent.url

        raise ValueError(
            f"Agent '{agent_name_or_url}' not found in registry. Available agents: {[a.name for a in discovered]}"
        )

    def _ensure_client(self) -> None:
        """Ensure an AgentClient is available for remote task dispatching.

        Attempts to configure the client from the passed registry if missing.

        Raises:
            RuntimeError: If there is no client and no registry from which to infer the transport.
        """
        if not self.client:
            if self.registry_client and hasattr(self.registry_client, "transport"):
                self.client = AgentClient(transport=self.registry_client.transport)
            else:
                raise RuntimeError(
                    "Flow requires an AgentClient to call remote agents. "
                    "Please provide an AgentClient during initialization."
                )

    async def _execute_target(self, target: FlowTarget, task: Task) -> Task:
        """Centralized dispatcher for executing a flow step target.

        This method handles the polymorphic nature of flow steps by delegating execution based on the target type:
        - **Flow**: Recursively executes the nested flow, propagating client and registry.
        - **Agent**: Executes a local agent instance by calling its `handle_task` method.
        - **str**: Resolves the agent URL (via Registry if needed) and sends the task remotely.

        Args:
            target: The execution unit (Agent instance, URL string, or nested Flow).
            task: The current Task state to process.

        Returns:
            The Task state after execution.

        Raises:
            ValueError: If the target type is not supported.
            RuntimeError: If remote execution is requested but no client/registry is available.
        """
        from protolink.agents.base import Agent

        if isinstance(target, Flow):
            # Propagate client/registry if missing in the nested flow
            if target.client is None:
                target.client = self.client
            if target.registry_client is None:
                target.registry_client = self.registry_client
            return await target.execute(task)
        elif isinstance(target, Agent):
            return await target.handle_task(task)
        elif isinstance(target, str):
            self._ensure_client()
            url = await self._resolve_agent_url(target)
            assert self.client is not None
            return await self.client.send_task(url, task)
        else:
            raise ValueError(f"Invalid execution target type: {type(target)}")


class SyncFlow:
    """Synchronous wrapper around Flow.

    This class provides blocking equivalents of async methods for use in:
        - scripts
        - CLI tools
        - notebooks without async support

    Internally uses `asyncio.run()` to execute async operations.

    Warning:
        This API should NOT be used inside an active event loop (e.g., FastAPI, Jupyter async cells).
    """

    def __init__(self, flow: Flow):
        self._flow = flow

    def execute(self, task: Task) -> Task:
        """Synchronously execute the flow on a given task.

        This is a blocking version of `execute()`.

        Internally runs the async implementation in a new event loop.

        Example:
            >>> flow = Pipeline([...])
            >>> result = flow.sync.execute(task)
        """
        return asyncio.run(self._flow.execute(task))
