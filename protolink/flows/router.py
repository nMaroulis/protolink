import json
import re
from dataclasses import asdict
from typing import Any

from protolink.client import AgentClient, RegistryClient
from protolink.core.part import Part, RouteDecision
from protolink.discovery import Registry
from protolink.models import Task
from protolink.types import FlowTarget

from .base import Flow


class Router(Flow):
    """A flow step that enforces conditional branching based on LLM decision making.

    Instead of relying on a hardcoded Python condition function, the Router relies on Semantic Context Injection.
    When a Router is placed in a Pipeline, the Pipeline extracts the Router's `routing_prompt` and target options,
    injecting them into the preceding agent's system prompt. The preceding agent evaluates its own task context
    and emits a structured ``Part.route("key")`` decision. The Router also accepts the historical `[ROUTE: key]`
    text tag as a compatibility fallback.

    Routing destinations can be:
    - **Agent instances**: Local execution.
    - **URL strings**: Remote A2A execution.
    - **Nested Flows**: Sub-orchestration logic.
    """

    def __init__(
        self,
        routes: dict[str, FlowTarget],
        routing_prompt: str,
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize the dynamic LLM router.

        Args:
            routes: A dictionary mapping potential string conditions to their respective Agent, URLs, or nested Flows.
            routing_prompt: The instruction prompt that will be passed to the preceding agent to explain the criteria
                for selecting each route.
            client: Optional `AgentClient` for executing remote paths.
            registry: Optional registry configuration for discovery.
        """
        super().__init__(client=client, registry=registry)
        self.routes = routes
        self.routing_prompt = routing_prompt

    @staticmethod
    def _decision_from_mapping(content: dict[str, Any]) -> RouteDecision | None:
        """Extract a route decision from a JSON-like mapping."""
        if (
            "content" in content
            and content.get("type") in {"route", "decision"}
            and isinstance(content["content"], dict)
        ):
            content = content["content"]

        route_key = content.get("route_key", content.get("route", content.get("key")))
        if route_key is None:
            return None
        return RouteDecision(
            route_key=str(route_key),
            reason=content.get("reason"),
            confidence=content.get("confidence"),
            metadata=content.get("metadata") or {},
        )

    @classmethod
    def _decision_from_part(cls, part: Part) -> RouteDecision | None:
        """Extract a structured route decision from one part, if present."""
        if part.type in {"route", "decision"}:
            return part.as_route_decision()

        if isinstance(part.content, dict):
            return cls._decision_from_mapping(part.content)

        if isinstance(part.content, str):
            stripped = part.content.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    return None
                if isinstance(data, dict):
                    return cls._decision_from_mapping(data)

        return None

    @staticmethod
    def _record_decision(task: Task, decision: RouteDecision) -> None:
        """Record routing decisions in task metadata for tracing and replay."""
        decisions = task.metadata.setdefault("route_decisions", [])
        if isinstance(decisions, list):
            decisions.append(asdict(decision))

    @staticmethod
    def _clean_legacy_tag(task: Task, tag: str) -> None:
        """Remove a legacy route tag from user-visible text while preserving the route as a part."""
        last_item = task.get_last_item()
        if last_item and last_item.parts:
            for part in last_item.parts:
                if part.type in ("text", "infer_output") and isinstance(part.content, str):
                    part.content = part.content.replace(tag, "").strip()
                    break

    def _extract_decision(self, task: Task) -> tuple[RouteDecision, str | None]:
        """Find a structured route decision, falling back to legacy route tags."""
        last_item = task.get_last_item()
        if last_item:
            for part in reversed(last_item.parts):
                decision = self._decision_from_part(part)
                if decision is not None:
                    return decision, None

        last_content = str(task.get_last_part_content())
        match = re.search(r"\[ROUTE:\s*([a-zA-Z0-9_-]+)\]", last_content)
        if not match:
            raise ValueError(
                "Router could not find a structured route decision or valid [ROUTE: key] tag in the previous output.\n"
                "Ensure the preceding agent follows the routing instructions.\n"
                f"Output was: {last_content}"
            )

        return RouteDecision(route_key=match.group(1), metadata={"source": "legacy_text_tag"}), match.group(0)

    async def execute(self, task: Task) -> Task:
        """Execute the conditionally chosen branch.

        Reads a structured route decision generated by the preceding agent and forwards the task.
        Legacy `[ROUTE: key]` tags are still accepted for compatibility.

        Args:
            task: The active `Task` state containing the preceding agent's output.

        Returns:
            The resulting `Task` object post-execution on the chosen route.

        Raises:
            ValueError: If the route decision is missing or maps to an undefined route.
        """
        decision, legacy_tag = self._extract_decision(task)
        next_route_key = decision.route_key

        self._logger.info(f"Router evaluated route decision: routing to '{next_route_key}'")

        if next_route_key not in self.routes:
            raise ValueError(
                f"The preceding agent produced a route key '{next_route_key}' "
                f"which does not exist in mapped routes: {list(self.routes.keys())}"
            )

        if legacy_tag:
            self._clean_legacy_tag(task, legacy_tag)
            last_item = task.get_last_item()
            if last_item and last_item.parts:
                last_item.parts.append(Part.route(next_route_key, metadata=decision.metadata))

        self._record_decision(task, decision)

        route_destination = self.routes[next_route_key]
        return await self._execute_target(route_destination, task)
