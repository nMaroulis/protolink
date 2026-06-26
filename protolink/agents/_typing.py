"""Internal typing support for Agent mixins."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from protolink.client import AgentClient, RegistryClient
    from protolink.core.actions import RunAction
    from protolink.core.cancellation import CancellationToken, TaskCancellationRequest, TaskExecutionRegistry
    from protolink.core.policy import ActionAuthorization, ActionAuthorizer
    from protolink.core.run_context import RunContext
    from protolink.llms.base import LLM
    from protolink.llms.compaction import HistoryCompactionRequest, HistoryCompactionResult
    from protolink.logging import BaseLogger
    from protolink.models import AgentCard, AgentSkill, Part, Task
    from protolink.server import AgentServer
    from protolink.state import State
    from protolink.state.operations import StateOperationRequest, StateOperationResult
    from protolink.storage import Storage
    from protolink.telemetry.base import Telemetry
    from protolink.tools import BaseTool
    from protolink.transport import Transport


class _AgentMixinBase(Protocol):
    """Structural base declaring attributes supplied by ``Agent.__init__``."""

    card: AgentCard
    tools: dict[str, BaseTool]
    skills: Literal["auto", "fixed"]
    action_authorizer: ActionAuthorizer
    registry_client: RegistryClient | None
    authenticator: Any
    credentials: str | None
    override_system_prompt: bool
    start_time: float | None

    _transport: Transport | None
    _client: AgentClient | None
    _server: AgentServer | None
    _llm: LLM | None
    _storage: Storage
    _state: State
    _telemetry: Telemetry | None
    _logger: BaseLogger
    _task_executions: TaskExecutionRegistry
    _control_tasks: set[asyncio.Task[Any]]
    _system_prompt: str | None
    _verbosity: Literal[0, 1, 2]
    _background_task: asyncio.Task[Any] | None
    _thread: Any
    _loop: asyncio.AbstractEventLoop | None
    _startup_exception: BaseException | None
    _ready_event: Any
    _discovery_ttl: int
    _discovery_cache: dict[str, tuple[float, list[AgentCard]]]
    _expose_chat: bool

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    @property
    def llm(self) -> LLM | None: ...

    @llm.setter
    def llm(self, llm: LLM | None) -> None: ...

    @property
    def telemetry(self) -> Telemetry | None: ...

    @telemetry.setter
    def telemetry(self, telemetry: Telemetry | None) -> None: ...

    @property
    def storage(self) -> Storage: ...

    @storage.setter
    def storage(self, storage: Storage) -> None: ...

    def get_cancellation_token(self, task_id: str) -> CancellationToken | None: ...

    async def authorize_action(
        self,
        action: RunAction,
        context: RunContext | None = None,
    ) -> ActionAuthorization: ...

    async def _authorize_tool_action(
        self,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: RunContext,
    ) -> tuple[ActionAuthorization, dict[str, Any]]: ...

    async def discover_agents(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]: ...

    async def call_agent(self, agent_url: str, task: Task) -> Task: ...

    async def run_task(self, task: Task) -> Task: ...

    def run_task_streaming(self, task: Task) -> AsyncIterator[Any]: ...

    async def handle_task(self, task: Task) -> Task: ...

    def handle_task_streaming(self, task: Task) -> AsyncIterator[Any]: ...

    async def cancel_task(self, request: TaskCancellationRequest) -> Task: ...

    async def compact_history(self, request: HistoryCompactionRequest) -> HistoryCompactionResult: ...

    async def describe_state(self, request: StateOperationRequest) -> StateOperationResult: ...

    async def reset_state(self, request: StateOperationRequest) -> StateOperationResult: ...

    async def compact_state(self, request: StateOperationRequest) -> StateOperationResult: ...

    def get_agent_card(self, *, as_json: bool = True) -> AgentCard | dict[str, Any]: ...

    def get_status(self, output_format: Literal["html", "json"] = "html") -> str: ...

    def get_chat(self) -> str: ...

    async def handle_chat_message(self, data: dict[str, Any]) -> dict[str, str]: ...

    async def invoke(
        self,
        message: str,
        part_type: Literal["tool_call", "infer"] = "infer",
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        session_id: str = "invocation_session_id",
    ) -> str: ...

    def add_tool(self, tool: BaseTool) -> None: ...

    def _add_skill_to_agent_card(self, skill: AgentSkill) -> None: ...

    def _resolve_skills(self, skills_mode: Literal["auto", "fixed"]) -> None: ...

    def _build_tools_prompt(self) -> str | None: ...

    async def execute_tool(
        self,
        part: Part,
        *,
        task: Task | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> Part: ...

    async def call_llm(
        self,
        infer_part: Part,
        task: Task | None = None,
        *,
        streaming: bool = False,
        event_callback: Any = None,
        cancellation_token: CancellationToken | None = None,
    ) -> Part: ...

    def call_llm_stream(
        self,
        infer_part: Part,
        task: Task | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterator[Any]: ...
