"""Public Agent class for the Protolink framework.

The :class:`Agent` type is intentionally kept as the stable public façade. Its
constructor owns identity and dependency wiring; reusable runtime behavior lives
in mixins and the task execution engine lives in :mod:`protolink.agents.engine`.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Literal

from protolink.client import RegistryClient
from protolink.core.cancellation import TaskExecutionRegistry
from protolink.core.policy import ActionAuthorizer, ApprovalHandlerLike, CapabilityPolicy, Policy
from protolink.discovery.registry import Registry
from protolink.llms.base import LLM
from protolink.logging import BaseLogger, ConsoleLogger
from protolink.models import AgentCard
from protolink.security.auth import Authenticator
from protolink.state import State
from protolink.storage import InMemoryStorage, Storage
from protolink.telemetry.base import Telemetry
from protolink.tools import BaseTool
from protolink.transport import Transport
from protolink.types import StateMode, TransportType

from .engine import AgentExecutionMixin
from .helpers import _coerce_state_operation_request
from .mixins import (
    AgentCommunicationMixin,
    AgentConfigurationMixin,
    AgentControlPlaneMixin,
    AgentLifecycleMixin,
    AgentSerializationMixin,
    AgentToolMixin,
)
from .sync import SyncAgent

__all__ = ["Agent", "SyncAgent", "_coerce_state_operation_request"]


class Agent(
    AgentLifecycleMixin,
    AgentControlPlaneMixin,
    AgentCommunicationMixin,
    AgentToolMixin,
    AgentExecutionMixin,
    AgentConfigurationMixin,
    AgentSerializationMixin,
):
    """Base class for creating A2A-compatible agents.

    Users should subclass this and implement the handle_task method only when
    they need custom orchestration. The default implementation executes explicit
    tool and inference parts, supports streaming, cancellation, persistent state,
    delegation, policy checks, telemetry, and serialization.
    """

    def __init__(
        self,
        card: AgentCard | dict[str, Any],
        transport: TransportType | Transport | None = None,
        registry: TransportType | Registry | RegistryClient | None = None,
        registry_url: str | None = None,
        llm: LLM | None = None,
        system_prompt: str | None = None,
        storage: Storage | None = None,
        state: list[StateMode] | State | None = None,
        telemetry: Telemetry | None = None,
        skills: Literal["auto", "fixed"] = "auto",
        logger: BaseLogger | None = None,
        discovery_ttl: int = 0,
        *,
        override_system_prompt: bool = False,
        verbosity: Literal[0, 1, 2] = 1,
        expose_chat: bool = True,
        authenticator: Authenticator | None = None,
        credentials: str | None = None,
        policy: Policy | None = None,
        approval_handler: ApprovalHandlerLike | None = None,
        run_store: Any | None = None,
        registry_heartbeat_interval: float | None = None,
    ):
        """Initialize agent with its identity card and transport layer.

        Args:
            card: AgentCard or dict describing this agent's identity and capabilities.
            transport: Transport instance or transport type string. If a Transport object is provided, it's used
                directly. If a string is provided (e.g., "http", "websocket"), a new Transport instance is created
                (transport factory) using the agent's card URL.
            registry: Registry instance, RegistryClient, or transport type string. If a Registry object is provided,
                its RegistryClient is extracted. If a RegistryClient is provided, it's used directly.
                If a string is provided, a new RegistryClient is created using the transport factory with registry_url.
            registry_url: URL of registry when using string transport type for registry creation.
            llm: Optional LLM instance for agent reasoning and inference.
            system_prompt: This is used as complementary text in the system prompt, which is responsible for explaining
                the agent logic and role. The agent calling, tool calling and other A2A functionalities are already
                predefined, so the LLM already has the knowledge on how to interact with its environment.
                If you wish to override the system prompt completely, set override_system_prompt to True.
            storage: Optional Storage instance for agent data persistence. It's also used for State persistence.
            state: Agent state. Choose for which modules state should be persistent.
                - ``None`` (default): Stateless. State is wiped on every task.
                - ``["conversation"]``: Persistent conversation history per session. Conversation Session State is
                preserved across tasks with the same ``session_id``.
                Example: ``state=["conversation"]``
            telemetry: Optional Telemetry instance for agent observability and tracing.
            skills: Skills mode - "auto" to detect from tools, "fixed" to use only card-defined skills.
            logger: Custom logger instance. If not provided, a ConsoleLogger will be used.
            discovery_ttl: Time to live in seconds for caching Agent information discovered from the Registry.
            override_system_prompt: If True, overrides system_prompt completely with the system_prompt provided.
            verbosity: Verbosity level - 0 for silent standard Agent logs, 1 for normal, 2 for verbose (debug mode).
            expose_chat: Whether the Agent will expose a chat endpoint for interaction with a UI.
            authenticator: Optional Authenticator instance for verifying incoming requests to this agent.
            credentials: Optional credentials string used for authenticating outgoing requests.
            policy: Optional runtime policy evaluated before concrete actions execute.
                Defaults to a backward-compatible ``CapabilityPolicy`` that
                allows actions unless a tool or ``RunContext`` rule restricts
                one of their declared capabilities.
            approval_handler: Optional synchronous or asynchronous application
                callback that resolves typed approval checkpoints. Protolink
                owns the safety contract; the application owns the user
                experience used to obtain the decision.
            run_store: Optional persistent task/run store. When provided, the
                agent records task snapshots after direct, server, and streaming
                execution paths.
            registry_heartbeat_interval: Optional seconds between registry
                heartbeat requests after successful registration. Leave ``None``
                to disable automatic heartbeats.
        """

        # Field Validation is handled by the AgentCard dataclass.
        self.card: AgentCard = AgentCard.from_dict(card) if isinstance(card, dict) else card
        # LLM validation is handled by the @llm.setter property.
        self._llm: LLM | None = None
        self.llm = llm
        # Storage
        self._storage: Storage
        self.storage = storage if storage is not None else InMemoryStorage(namespace=self.card.name)
        # Telemetry
        self._telemetry: Telemetry | None = None
        self.telemetry = telemetry
        # Tools & skills
        self.tools: dict[str, BaseTool] = {}
        self.skills: Literal["auto", "fixed"] = skills
        # Runtime action authorization
        self.action_authorizer = ActionAuthorizer(
            policy=policy or CapabilityPolicy(),
            approval_handler=approval_handler,
        )
        # Live task control is intentionally separate from serialized Task state.
        self._task_executions = TaskExecutionRegistry()
        self._control_tasks: set[asyncio.Task[Any]] = set()
        self.run_store = run_store
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._registry_heartbeat_interval = registry_heartbeat_interval
        self._registry_heartbeat_task: asyncio.Task[Any] | None = None
        # Logger - Maps verbosity to silent, INFO, DEBUG for default console logger.
        self._logger = (
            ConsoleLogger(name=f"protolink.agents.{self.card.name}", level={0: 50, 1: 20, 2: 10}.get(verbosity, 20))
            if logger is None
            else logger
        )
        # Agent State Persistence
        if isinstance(state, State):
            self._state: State = state
        else:
            if state is None:
                self._logger.debug(f"State not provided, agent {self.card.name} will be stateless.")
                self._state: State = State(storage=self.storage, enabled=[])
            else:
                self._state: State = State(storage=self.storage, enabled=state)
                self._logger.debug(f"Agent {self.card.name} state set to {self._state.to_dict()}")
        # LLM prompt
        self._system_prompt: str | None = system_prompt
        self.override_system_prompt: bool = override_system_prompt
        self._verbosity: Literal[0, 1, 2] = verbosity
        # Store authentication configuration
        self.authenticator: Authenticator | None = authenticator
        self.credentials: str | None = credentials
        # Initialize client and server components
        if transport is None:
            self._transport, self._client, self._server = None, None, None
            self._logger.warning(
                "No transport provided, agent will not be able to receive tasks. Set agent.transport property"
                " (e.g. agent.transport = 'http') to configure."
            )
        else:
            self.transport = transport  # init _transport, _client, _server properties
        # Initialize Registry Client
        if not registry:
            self.registry_client = None
            self._logger.warning(
                "No registry provided, agent will not be able to register to the registry or fetch agents.\n"
                "Call set_registry() to configure."
            )
        else:
            self.set_registry(registry, registry_url)
        # Runtime Lifecycle State
        self._background_task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Resolve and add necessary skills
        self._resolve_skills(skills)
        # Uptime
        self.start_time: float | None = None
        # Discovery TTL Cache
        self._discovery_ttl = discovery_ttl
        self._discovery_cache: dict[str, tuple[float, list[AgentCard]]] = {}
        # Expose Chat
        self._expose_chat = expose_chat
        # Sync API
        self.sync = SyncAgent(self)
