from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import AgentCard, Task
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
    - **Semantic Context Injection**: Flows dynamically build instruction prompts based on their downstream topology
      and inject them into `task.flow_state["prompt"]` for executing agents to utilize seamlessly.

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

        self._logger = get_logger(f"protolink.flows.{type(self).__name__}")
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

    async def _build_flow_prompt(self, next_target: FlowTarget | None = None, *, is_final: bool = False) -> str:
        """Build the semantic context instructions for the LLM based on the next target.

        Args:
            next_target: The next step in the flow.
            is_final: Whether the current step is the last step.

        Returns:
            A string containing the flow instructions to inject into the LLM system prompt.
        """
        from protolink.agents.base import Agent
        from protolink.flows.parallel import Parallel
        from protolink.flows.router import Router
        from protolink.llms.prompts import (
            FLOW_PARALLEL_PROMPT,
            FLOW_ROUTER_PROMPT,
            FLOW_TARGET_PROMPT,
            FLOW_TERMINAL_PROMPT,
        )

        if is_final:
            return FLOW_TERMINAL_PROMPT

        if not next_target:
            return ""

        discovered = []
        if self.registry_client:
            try:
                discovered = await self.registry_client.discover()
            except Exception:
                pass

        flow_instructions = ""
        if isinstance(next_target, Router):
            routes_info = []
            for route_key, route_dest in next_target.routes.items():
                route_card: AgentCard | None = None
                if isinstance(route_dest, str):
                    for card in discovered:
                        if card.name == route_dest or card.url == route_dest:
                            route_card = card
                            break
                elif isinstance(route_dest, Agent):
                    route_card = route_dest.card

                if route_card:
                    routes_info.append(f"Route Key: '{route_key}'\nAgent Profile:\n{route_card.get_prompt_format()}\n")
                else:
                    routes_info.append(f"Route Key: '{route_key}'\nTarget: {route_dest}\n")

            flow_instructions = FLOW_ROUTER_PROMPT.format(
                routing_prompt=next_target.routing_prompt, routes_info="\n".join(routes_info)
            )
        elif isinstance(next_target, Parallel):
            parallel_info = []
            for branch_idx, branch_dest in enumerate(next_target.branches):
                branch_card: AgentCard | None = None
                if isinstance(branch_dest, str):
                    for card in discovered:
                        if card.name == branch_dest or card.url == branch_dest:
                            branch_card = card
                            break
                elif isinstance(branch_dest, Agent):
                    branch_card = branch_dest.card

                if branch_card:
                    parallel_info.append(f"Agent {branch_idx + 1} Profile:\n{branch_card.get_prompt_format()}\n")
                else:
                    parallel_info.append(f"Agent {branch_idx + 1} Target: {branch_dest}\n")

            flow_instructions = FLOW_PARALLEL_PROMPT.format(parallel_info="\n".join(parallel_info))
        else:
            next_card = None
            if isinstance(next_target, str):
                for card in discovered:
                    if card.name == next_target or card.url == next_target:
                        next_card = card
                        break
            elif isinstance(next_target, Agent):
                next_card = next_target.card
            elif isinstance(next_target, Flow):
                return f"\n\n--- FLOW PIPELINE CONTEXT ---\nYour output will be passed to a nested {next_target.__class__.__name__} flow structure."  # noqa: E501

            if next_card:
                flow_instructions = FLOW_TARGET_PROMPT.format(
                    next_agent_name=next_card.name,
                    next_agent_card=next_card.get_prompt_format(),
                )

        return flow_instructions

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
        from protolink.models import Message

        # --- Flow Transition Bridge ---
        # When a flow step completes, its output is a Part of type "infer_output" (or "text", etc.).
        # Protolink agents are strictly deterministic: they only execute when they find an active
        # executable instruction (Part.infer or Part.tool_call) in the task's last item.
        # Without this bridge, downstream agents would receive "infer_output" and no-op.
        #
        # The bridge checks: does the task's last item contain an executable instruction?
        # If not, it wraps the previous output content into a new Part.infer() user message,
        # giving the downstream agent a clear "run your LLM on this" instruction.
        #
        # This only applies to Agent targets (local or remote). Nested Flows handle their own
        # internal dispatch and don't need wrapping.
        if isinstance(target, (Agent, str)):
            last_item = task.get_last_item()
            if last_item:
                has_executable = any(p.type in ("infer", "tool_call") for p in last_item.parts)
                is_plain_user_message = isinstance(last_item, Message) and last_item.role == "user"
                if not has_executable and not is_plain_user_message:
                    content = task.get_last_part_content()
                    if content is not None:
                        task.add_message(Message.infer(prompt=str(content)))

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
