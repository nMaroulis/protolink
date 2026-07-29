"""Runtime agent mesh used by the infer-loop benchmark."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Literal

from protolink import Agent, AgentCard, Task
from protolink.client import AgentClient
from protolink.core.agent_card import AgentCapabilities
from protolink.discovery import Registry
from protolink.llms.base import LLM
from protolink.telemetry import LocalTraceRecorder, LocalTraceTelemetry

from .catalog import (
    _HOTEL_BASE_PRICE,
    _ORACLE_VERDICTS,
    _SOURCE_FILES,
    _WEATHER,
    _hotel_result,
    _join_result,
    _multiply_result,
    _oracle_result,
    _read_file_result,
    _search_symbol_result,
    _weather_result,
)
from .models import DEFAULT_SYSTEM_PROMPT, ActionLedger, LedgerEntry


class _OracleAgent(Agent):
    """Deterministic infer worker whose receipts are not present in user prompts."""

    def __init__(
        self,
        *,
        card: AgentCard,
        registry: Registry,
        ledger: ActionLedger,
        verbosity: Literal[0, 1, 2],
    ) -> None:
        self._benchmark_ledger = ledger
        super().__init__(
            card=card,
            transport="runtime",
            registry=registry,
            verbosity=verbosity,
        )
        # This worker implements infer deterministically rather than through an
        # LLM, but must advertise infer capability to the coordinator.
        self.card.capabilities.has_llm = True
        self.card.capabilities.delegation = False

    async def handle_task(self, task: Task) -> Task:
        """Resolve the strict reference fields carried in an infer prompt."""
        raw_content = task.get_last_part_content()
        prompt = str(raw_content.get("prompt", "")) if isinstance(raw_content, dict) else str(raw_content or "")
        reference_match = re.search(r"\bREFERENCE=([A-Z0-9-]+)", prompt)
        request_match = re.search(r"\bREQUEST_ID=([A-Z0-9-]+)", prompt)
        evidence_match = re.search(r"\bEVIDENCE=([A-Z0-9-]+)", prompt)
        if not reference_match or not request_match or not evidence_match:
            return task.fail("Oracle infer prompt must include REFERENCE, REQUEST_ID, and EVIDENCE")

        reference = reference_match.group(1)
        if reference not in _ORACLE_VERDICTS:
            return task.fail(f"Unknown oracle reference: {reference}")

        result = _oracle_result(
            reference=reference,
            request_id=request_match.group(1),
            evidence_receipt=evidence_match.group(1),
        )
        self._benchmark_ledger.record(
            LedgerEntry(
                kind="agent_infer",
                agent=self.card.name,
                tool=None,
                args={
                    "reference": reference,
                    "request_id": request_match.group(1),
                    "evidence_receipt": evidence_match.group(1),
                },
                result=result,
                prompt=prompt,
            )
        )
        return task.complete(json.dumps(result, ensure_ascii=False, sort_keys=True))


class BenchmarkMesh:
    """A real RuntimeTransport mesh used by every scored attempt."""

    def __init__(
        self,
        *,
        llm: LLM,
        recorder: LocalTraceRecorder,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        verbosity: Literal[0, 1, 2] = 0,
        namespace: str | None = None,
    ) -> None:
        nonce = namespace or hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:12]
        prefix = f"runtime://infer-benchmark-{nonce}"
        self.ledger = ActionLedger()
        self.registry = Registry(
            transport="runtime",
            url=f"{prefix}/registry",
            verbosity=verbosity,
        )
        self.workspace_agent = self._build_workspace_agent(
            url=f"{prefix}/workspace",
            verbosity=verbosity,
        )
        self.travel_agent = self._build_travel_agent(
            url=f"{prefix}/travel",
            verbosity=verbosity,
        )
        self.workspace_archive_agent = self._build_workspace_archive_agent(
            url=f"{prefix}/workspace-archive",
            verbosity=verbosity,
        )
        self.travel_planning_agent = self._build_travel_planning_agent(
            url=f"{prefix}/travel-planning",
            verbosity=verbosity,
        )
        self.oracle_agent = _OracleAgent(
            card=AgentCard(
                name="oracle_agent",
                description=(
                    "Deterministic reference analyst. Use agent_call action=infer with a prompt containing "
                    "REFERENCE, REQUEST_ID, and EVIDENCE fields."
                ),
                url=f"{prefix}/oracle",
                capabilities=AgentCapabilities(delegation=False, has_llm=True),
            ),
            registry=self.registry,
            ledger=self.ledger,
            verbosity=verbosity,
        )
        self.coordinator = Agent(
            card=AgentCard(
                name="benchmark_coordinator",
                description="Coordinates deterministic benchmark specialists.",
                url=f"{prefix}/coordinator",
                capabilities=AgentCapabilities(delegation=True, has_llm=True),
            ),
            transport="runtime",
            registry=self.registry,
            llm=llm,
            system_prompt=system_prompt,
            telemetry=LocalTraceTelemetry(recorder=recorder),
            verbosity=verbosity,
        )
        self._add_coordinator_tools()
        self.client = AgentClient("runtime", url=f"{prefix}/client")
        self._started: list[Any] = []

    def _build_workspace_agent(self, *, url: str, verbosity: Literal[0, 1, 2]) -> Agent:
        agent = Agent(
            card=AgentCard(
                name="workspace_agent",
                description="Authoritative source-code workspace reader and symbol index.",
                url=url,
                capabilities=AgentCapabilities(delegation=False, tool_calling=True),
            ),
            transport="runtime",
            registry=self.registry,
            verbosity=verbosity,
        )

        @agent.tool(
            name="read_file",
            description="Read authoritative metadata for one known source file.",
        )
        def read_file(path: str, request_id: str) -> dict[str, Any]:
            if path not in _SOURCE_FILES:
                raise ValueError(f"Unknown benchmark source path: {path}")
            args = {"path": path, "request_id": request_id}
            result = _read_file_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "read_file", args, result))
            return result

        @agent.tool(
            name="search_symbol",
            description="Search the authoritative source index; source_receipt links a prior read_file observation.",
        )
        def search_symbol(query: str, request_id: str, source_receipt: str) -> dict[str, Any]:
            args = {
                "query": query,
                "request_id": request_id,
                "source_receipt": source_receipt,
            }
            result = _search_symbol_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "search_symbol", args, result))
            return result

        return agent

    def _build_travel_agent(self, *, url: str, verbosity: Literal[0, 1, 2]) -> Agent:
        agent = Agent(
            card=AgentCard(
                name="travel_agent",
                description="Authoritative synthetic weather and hotel data for benchmark trips.",
                url=url,
                capabilities=AgentCapabilities(delegation=False, tool_calling=True),
            ),
            transport="runtime",
            registry=self.registry,
            verbosity=verbosity,
        )

        @agent.tool(
            name="get_weather",
            description="Return deterministic weather and an opaque receipt for a supported location and date.",
        )
        def get_weather(location: str, travel_date: str, request_id: str) -> dict[str, Any]:
            if location not in _WEATHER:
                raise ValueError(f"Unknown benchmark location: {location}")
            args = {
                "location": location,
                "travel_date": travel_date,
                "request_id": request_id,
            }
            result = _weather_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "get_weather", args, result))
            return result

        @agent.tool(
            name="quote_hotel",
            description=(
                "Return a deterministic hotel total and receipt. weather_receipt must be NONE or a prior weather "
                "receipt when the request requires a dependency."
            ),
        )
        def quote_hotel(
            location: str,
            nights: int,
            guests: int,
            tier: str,
            request_id: str,
            weather_receipt: str,
        ) -> dict[str, Any]:
            if location not in _WEATHER:
                raise ValueError(f"Unknown benchmark location: {location}")
            if tier not in _HOTEL_BASE_PRICE:
                raise ValueError(f"Unknown benchmark hotel tier: {tier}")
            args = {
                "location": location,
                "nights": nights,
                "guests": guests,
                "tier": tier,
                "request_id": request_id,
                "weather_receipt": weather_receipt,
            }
            result = _hotel_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "quote_hotel", args, result))
            return result

        return agent

    def _build_workspace_archive_agent(self, *, url: str, verbosity: Literal[0, 1, 2]) -> Agent:
        agent = Agent(
            card=AgentCard(
                name="workspace_archive_agent",
                description=(
                    "Historical source snapshot reader and index. Its data is archived and non-authoritative; "
                    "use only when a request explicitly asks for historical workspace information."
                ),
                url=url,
                capabilities=AgentCapabilities(delegation=False, tool_calling=True),
            ),
            transport="runtime",
            registry=self.registry,
            verbosity=verbosity,
        )

        @agent.tool(
            name="read_file",
            description="Read stale archived source metadata, never the authoritative current workspace.",
        )
        def read_file(path: str, request_id: str) -> dict[str, Any]:
            if path not in _SOURCE_FILES:
                raise ValueError(f"Unknown benchmark source path: {path}")
            args = {"path": path, "request_id": request_id}
            result = _read_file_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "read_file", args, result))
            return result

        @agent.tool(
            name="search_symbol",
            description="Search the archived source index, never the authoritative current workspace index.",
        )
        def search_symbol(query: str, request_id: str, source_receipt: str) -> dict[str, Any]:
            args = {
                "query": query,
                "request_id": request_id,
                "source_receipt": source_receipt,
            }
            result = _search_symbol_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "search_symbol", args, result))
            return result

        return agent

    def _build_travel_planning_agent(self, *, url: str, verbosity: Literal[0, 1, 2]) -> Agent:
        agent = Agent(
            card=AgentCard(
                name="travel_planning_agent",
                description=(
                    "Generic travel scenario planner that offers non-authoritative estimates. "
                    "Do not use when a request requires authoritative benchmark travel data."
                ),
                url=url,
                capabilities=AgentCapabilities(delegation=False, tool_calling=True),
            ),
            transport="runtime",
            registry=self.registry,
            verbosity=verbosity,
        )

        @agent.tool(
            name="get_weather",
            description="Return a generic planning estimate, not authoritative benchmark weather.",
        )
        def get_weather(location: str, travel_date: str, request_id: str) -> dict[str, Any]:
            if location not in _WEATHER:
                raise ValueError(f"Unknown benchmark location: {location}")
            args = {
                "location": location,
                "travel_date": travel_date,
                "request_id": request_id,
            }
            result = _weather_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "get_weather", args, result))
            return result

        @agent.tool(
            name="quote_hotel",
            description="Return a generic planning estimate, not an authoritative benchmark hotel quote.",
        )
        def quote_hotel(
            location: str,
            nights: int,
            guests: int,
            tier: str,
            request_id: str,
            weather_receipt: str,
        ) -> dict[str, Any]:
            if location not in _WEATHER:
                raise ValueError(f"Unknown benchmark location: {location}")
            if tier not in _HOTEL_BASE_PRICE:
                raise ValueError(f"Unknown benchmark hotel tier: {tier}")
            args = {
                "location": location,
                "nights": nights,
                "guests": guests,
                "tier": tier,
                "request_id": request_id,
                "weather_receipt": weather_receipt,
            }
            result = _hotel_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "quote_hotel", args, result))
            return result

        return agent

    def _add_coordinator_tools(self) -> None:
        agent = self.coordinator

        @agent.tool(
            name="multiply_numbers",
            description="Multiply two integers and return the product with an opaque benchmark receipt.",
        )
        def multiply_numbers(a: int, b: int, request_id: str) -> dict[str, Any]:
            args = {"a": a, "b": b, "request_id": request_id}
            result = _multiply_result(**args)
            self.ledger.record(LedgerEntry("local_tool", agent.card.name, "multiply_numbers", args, result))
            return result

        @agent.tool(
            name="join_tokens",
            description="Join two strings exactly and return the joined value with an opaque benchmark receipt.",
        )
        def join_tokens(left: str, right: str, separator: str, request_id: str) -> dict[str, Any]:
            args = {
                "left": left,
                "right": right,
                "separator": separator,
                "request_id": request_id,
            }
            result = _join_result(**args)
            self.ledger.record(LedgerEntry("local_tool", agent.card.name, "join_tokens", args, result))
            return result

    async def start(self) -> None:
        """Start the registry and all agents, then verify discovery."""
        try:
            self.registry.start(background=True)
            self._started.append(self.registry)
            for agent in (
                self.workspace_agent,
                self.travel_agent,
                self.workspace_archive_agent,
                self.travel_planning_agent,
                self.oracle_agent,
                self.coordinator,
            ):
                agent.start(background=True)
                self._started.append(agent)
            discovered = await self.coordinator.discover_agents()
            names = {card.name for card in discovered}
            required = {
                "workspace_agent",
                "travel_agent",
                "workspace_archive_agent",
                "travel_planning_agent",
                "oracle_agent",
            }
            missing = sorted(required - names)
            if missing:
                raise RuntimeError(f"Benchmark discovery preflight failed; missing agents: {missing}")
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """Stop every started component in reverse order."""
        while self._started:
            component = self._started.pop()
            component.stop()
