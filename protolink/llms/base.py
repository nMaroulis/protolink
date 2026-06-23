"""LLM Base - Abstract base class for all LLM implementations.

This module provides the `LLM` abstract base class that defines the interface for all language model implementations in
Protolink. Whether using API-based providers (OpenAI, Anthropic, Gemini), server-based solutions (Ollama), or local
models (LLaMA.cpp, MPT), all implementations inherit from this class.

Creating a Custom LLM Wrapper
-----------------------------
To add support for a new LLM provider, create a subclass that implements
the required abstract methods:

Required Methods:
    - `call(history: ConversationHistory) -> str`: Single response generation
    - `call_stream(history: ConversationHistory) -> AsyncIterator[str]`: Streaming response

Optional Override:
    - `_inject_tool_call(...)`: Customize how tool results are injected into history.
      Override this if your provider has specific tool-calling protocols (e.g., OpenAI
      requires tool_call_id correlation).
    - `validate_connection() -> bool`: Verify API connectivity or model availability.

Example: Minimal Custom LLM
    ```python
    from collections.abc import AsyncIterator
    from typing import Any, ClassVar
    from protolink.llms.base import LLM
    from protolink.llms.history import ConversationHistory

    class MyCustomLLM(LLM):
        model_type: ClassVar[str] = "api"
        provider: ClassVar[str] = "my_provider"

        def __init__(self, api_key: str, model: str = "default-model"):
            super().__init__(model=model, model_params={"temperature": 0.7})
            self._client = MyProviderClient(api_key)

        def call(self, history: ConversationHistory) -> str:
            # Convert history to provider's format and call API
            messages = [{"role": m["role"], "content": m["content"]} for m in history.messages]
            response = self._client.complete(model=self.model, messages=messages)
            return response.text

        async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
            messages = [{"role": m["role"], "content": m["content"]} for m in history.messages]
            stream = self._client.complete_stream(model=self.model, messages=messages)
            for chunk in stream:
                yield chunk.text

        def validate_connection(self) -> bool:
            try:
                self._client.ping()
                return True
            except Exception:
                return False

        # Optional: Override if provider has native tool-calling protocol
        def _inject_tool_call(self, *, tool_name: str, tool_args: dict, tool_result: Any):
            # Provider-specific tool result injection
            # Default uses system message; override for native tool protocols
            self.history.add_raw({
                "role": "tool",
                "tool_call_id": "...",
                "content": str(tool_result)
            })
    ```

See Also:
    - `protolink.llms.api.openai_client.OpenAILLM`: Example of native tool-calling override
    - `protolink.llms.api.base.APILLM`: Base class for API-based LLMs
    - `protolink.llms.local.base.LocalLLM`: Base class for local models
"""

import ast
import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from protolink.tools import BaseTool

from protolink.core.actions import RunAction
from protolink.core.cancellation import CancellationToken
from protolink.core.part import Part
from protolink.core.policy import (
    ActionAuthorization,
    ActionDeniedError,
    ActionPolicyError,
    ApprovalRequiredError,
)
from protolink.llms.actions import (
    AgentCallAction,
    FinalAction,
    LLMAction,
    LLMActionResult,
    ToolCallAction,
    prompt_action_schema,
    validate_action_payload,
)
from protolink.llms.compaction import (
    HISTORY_COMPACTION_TOOL_NAME,
    HistoryCompactionResult,
    HistoryCompactionStrategy,
    HistoryCompactor,
)
from protolink.llms.history import ConversationHistory
from protolink.llms.metrics import (
    LLMCallMetrics,
    LLMContextUsage,
    LLMModelProfile,
    build_call_metrics,
    context_usage_from_tokens,
    estimate_token_count,
    profile_from_value,
)
from protolink.llms.prompts import (
    AGENT_LIST_PROMPT,
    BASE_INSTRUCTIONS,
    BASE_SYSTEM_PROMPT,
    NATIVE_AGENT_LIST_PROMPT,
    NATIVE_BASE_INSTRUCTIONS,
    NATIVE_NO_TOOL_PROMPT,
    NATIVE_SYSTEM_PROMPT,
    NATIVE_SYSTEM_REASONING_MAP,
    NATIVE_TOOL_PROMPT,
    SYSTEM_REASONING_MAP,
    TOOL_CALL_PROMPT,
)
from protolink.llms.serialization import json_history_default
from protolink.tools import BaseTool
from protolink.types import LLMProvider, LLMType, ReasoningLevel

MAX_INFER_STEPS: int = 10  # safety against infinite loops


class LLM(ABC):
    """
    Abstract base class for all Large Language Model (LLM) implementations.

    This class defines the core interface and shared functionality for any LLM,
    whether it is API-based (OpenAI, Anthropic, Gemini), server-based (Ollama) or local (LLaMA, MPT, etc.).

    Subclasses are expected to define:

    - `model_type` (ClassVar[LLMType]): Type of the LLM (i.e., "api", "server", "local").
    - `provider` (ClassVar[LLMProvider]): Name of the model provider (e.g., "openai").

    Instance variables:

    - `model` (str): The identifier of the model to use (e.g., "gpt-4o-mini").
    - `_model_params` (dict[str, Any]): Model-specific generation parameters. These
      vary depending on the provider. Examples include:
        - OpenAI: temperature, top_p, stop, max_tokens
        - Anthropic: temperature, top_p, max_tokens
        - Gemini: temperature, top_p, max_output_tokens
    - `history` (ConversationHistory): Tracks conversation messages for multi-turn
      interactions.
    - `compactor` (HistoryCompactor): Owns provider-neutral history compaction,
      summary generation, and the agent-facing compaction tool.
    - `system_prompt` (str): Optional system instructions used as context for the
      model when generating responses. Uses default prompts for agent, tool and llm calling.
    - `_reasoning` (ReasoningLevel): Whether to use chain of thought (CoT) for the model, adds reasoning steps to the
      response.

    Usage:

        Subclasses should implement at least:
        - `call(history: ConversationHistory) -> str`: Blocking single-response generation.
        - `call_stream(history: ConversationHistory) -> AsyncIterator[str]`: Streaming response generation.
        - `validate_connection() -> bool`: Optional, to verify API connectivity or model availability.

    Example:

        class OpenAILLM(APILLM):
            provider = "openai"
            model_type = "api"

            def call(self, history):
                ...
    """

    # Class-level metadata (set by subclasses)
    model_type: ClassVar[LLMType]
    provider: ClassVar[LLMProvider]

    def __init__(
        self,
        model: str,
        model_params: dict[str, Any],
        *,
        reasoning: ReasoningLevel = "none",
    ) -> None:
        # ---- Instance state ----
        self.model: str = model
        self._model_params: dict[str, Any] = model_params
        self._reasoning: ReasoningLevel = reasoning

        self.history: ConversationHistory = ConversationHistory()
        self.compactor: HistoryCompactor = HistoryCompactor(self)
        self.system_prompt: str = self.build_system_prompt(action_mode="json")
        self.metrics_enabled: bool = True
        self._metrics_profile: LLMModelProfile | None = None
        self.sync = SyncLLM(self)

    def configure_metrics(
        self,
        profile: LLMModelProfile | dict[str, Any] | None = None,
        *,
        context_window: int | None = None,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
        currency: str = "USD",
        enabled: bool = True,
    ) -> "LLM":
        """Configure optional LLM budget metrics for this model.

        Metrics are purely observational. They do not change prompt generation,
        provider request payloads, retry behavior, or model responses. When an
        ``event_callback`` or telemetry backend is attached, Protolink emits
        per-call latency, usage, context-pressure, and cost events. Provider
        token usage is preferred when available; otherwise Protolink uses local
        estimates.

        Args:
            profile: Optional ``LLMModelProfile`` or dictionary. Pass this when
                you already have model budget metadata.
            context_window: Total context-window size in tokens. Used to
                compute ``context.used_percent``.
            input_cost_per_million: Input-token price per one million tokens.
                Used only for estimated cost metadata.
            output_cost_per_million: Output-token price per one million tokens.
                Used only for estimated cost metadata.
            currency: Currency code for cost estimates. Defaults to ``"USD"``.
            enabled: Whether to emit metrics when an observer is attached.

        Returns:
            The LLM instance, so callers can configure fluently.
        """
        self.metrics_enabled = enabled
        if profile is not None:
            self._metrics_profile = profile_from_value(profile, provider=self.provider, model=self.model)
            return self

        if context_window is None and input_cost_per_million is None and output_cost_per_million is None:
            return self

        self._metrics_profile = LLMModelProfile(
            context_window=context_window,
            input_cost_per_million=input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
            currency=currency,
            provider=self.provider,
            model=self.model,
        )
        return self

    @property
    def metrics_profile(self) -> LLMModelProfile | None:
        """Return the optional model profile used for context/cost metrics."""
        return self._metrics_profile

    def compact_history(
        self,
        strategy: HistoryCompactionStrategy = "recent",
        *,
        max_messages: int = 20,
        max_tokens: int = 4_000,
        preserve_recent: int = 6,
        summary_max_tokens: int = 512,
    ) -> HistoryCompactionResult:
        """Compact live history through this LLM's ``HistoryCompactor``.

        This convenience facade preserves the direct LLM API. Applications
        that need the component itself can call ``llm.compactor.compact()``.

        Args:
            strategy: ``"recent"``, ``"tokens"``, or ``"summary"``.
            max_messages: Retained-message limit for ``"recent"``.
            max_tokens: Estimated token ceiling for ``"tokens"``.
            preserve_recent: Newest messages protected by smart strategies.
            summary_max_tokens: Requested maximum summary length.

        Returns:
            Structured before/after message and estimated-token counts.
        """
        return self.compactor.compact(
            strategy=strategy,
            max_messages=max_messages,
            max_tokens=max_tokens,
            preserve_recent=preserve_recent,
            summary_max_tokens=summary_max_tokens,
        )

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    @abstractmethod
    def call(self, history: ConversationHistory) -> str:
        """Generate a response from the LLM.

        This is the core method that subclasses must implement to call their specific LLM (OpenAI, Anthropic, etc.).

        Args:
            history: Conversation history containing system, user, assistant, and tool messages

        Returns:
            str: Raw text response from the LLM
        """
        raise NotImplementedError

    @abstractmethod
    def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response from the LLM.

        This method is defined as a standard function (non-async) that returns an AsyncIterator to ensure strict
        adherence to the Liskov Substitution Principle. Subclasses should implement this as an 'async def' generator
        using 'yield'.

        Note on Implementation:
            In Python, calling an 'async def' function that contains 'yield' returns an AsyncIterator immediately and
            synchronously. Defining this as 'def' in the base class allows subclasses to be used interchangeably
            without requiring an inconsistent 'await' on the initial call, maintaining type-system integrity.

        Args:
            history: Conversation history containing system, user, assistant, and tool messages

        Returns:
            AsyncIterator[str]: An asynchronous iterator yielding response chunks.
        """
        raise NotImplementedError

    def chat(self, user_query: str, *, streaming: bool = False) -> str | AsyncIterator[str]:
        """
        High-level convenience method for standard chat usage.

        Args:
            user_query: The user's query/message
            streaming: If True, returns an iterator of response chunks

        Returns:
            str: Complete response if streaming=False
            AsyncIterator[str]: Iterator of response chunks if streaming=True
        """
        self.history.add_user(user_query)
        if streaming:
            return self.call_stream(self.history)
        return self.call(self.history)

    @property
    def uses_native_action_prompt(self) -> bool:
        """Whether this LLM should receive provider-native tool instructions.

        The default is ``False`` because the portable Protolink protocol is a
        simple JSON action contract. Providers that actually send native tool
        declarations override this so the system prompt does not ask the model
        to emit JSON while the provider API is asking it to call tools.
        """
        return False

    @property
    def supports_native_action_stream(self) -> bool:
        """Whether ``streaming=True`` can acquire actions from native events.

        Providers that override ``call_action_stream()`` to consume structured
        streaming tool-call events should return ``True`` here. Providers that
        stream plain text should keep the default ``False`` so the agent builds
        the JSON action prompt for streaming inference.
        """
        return False

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, "BaseTool"],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one validated runtime action for the current conversation.

        Subclasses with native tool/function-calling support should override
        this method and normalize provider-native results into
        :class:`~protolink.llms.actions.LLMActionResult`. The base
        implementation is the compatibility path: call the model for text,
        parse the prompt-defined JSON action, validate it with Pydantic, and
        return the same typed result shape as native adapters.

        Args:
            history: Conversation history for this inference step.
            tools: Local tools available to this agent. Fallback adapters rely
                on the system prompt for tool descriptions; native adapters use
                this mapping to build provider tool declarations.
            agent_callback_available: Whether agent delegation can be
                dispatched by the runtime for this step.
            agent_cards: Optional discovered agent cards. The fallback parser
                uses this context only to repair unambiguous legacy shorthand
                such as ``{"type":"agent_call","prompt":"list_directory(path='.')"}`
                into a fully typed ``AgentCallAction``.

        Returns:
            A normalized and validated action result. The runtime dispatches
            only this object, never raw provider payloads.
        """
        _ = agent_callback_available
        raw_response = self.call(history)
        action = self._parse_infer_response(raw_response, tools=tools, agent_cards=agent_cards)
        return LLMActionResult(action=action, raw_response=raw_response, native=False)

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, "BaseTool"],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        """Return one action from a streaming model call.

        The base implementation is intentionally simple and local-model
        friendly: stream text chunks, emit them to the optional callback, join
        the chunks, and parse the final text as one Protolink JSON action. API
        providers with native streaming tool-call events override this method
        and normalize those events into the same ``LLMActionResult`` contract.
        """
        _ = agent_callback_available
        chunks: list[str] = []
        async for chunk in self.call_stream(history):
            chunks.append(chunk)
            if chunk_callback is not None:
                await chunk_callback(chunk)
        raw_response = "".join(chunks)
        action = self._parse_infer_response(raw_response, tools=tools, agent_cards=agent_cards)
        return LLMActionResult(action=action, raw_response=raw_response, native=False)

    # ----------------------------------------------------------------------
    # Agent-LLM Interface - A2A Operations
    #
    # This is the interface that the Agent class will use to interact with the LLM. It is a controlled, multi-step
    # inference loop that allows the LLM to invoke tools, delegate tasks to other Agents, and finally produce an
    # ``infer_output`` Part.
    #
    # LLMs know how to produce these outputs for these actions (tool_calling, delegate_task, final_output) using
    # Protolink's predefined prompts.
    #
    # What's interesting is how Protolink handles tool_calling and how this tool call is appended to the message
    # history. Each class implements its own way of handling tool_calling in order to comply with the LLM's API and
    # internal logic. This implementation should be implemented in `_inject_tool_call`
    # ----------------------------------------------------------------------

    async def infer(
        self,
        *,
        query: str,
        tools: dict[str, "BaseTool"],
        agent_callback: Callable[[str, str, dict[str, Any]], Awaitable[Any]] | None = None,
        agent_cards: list[Any] | None = None,
        streaming: bool = False,
        event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        action_authorizer: Callable[[RunAction], Awaitable[ActionAuthorization]] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> "Part":
        """
        Execute a controlled, multi-step inference loop against the configured LLM.

        This method implements a deterministic agent runtime over a stateless language model. The LLM is invoked
        iteratively to *declare intent only* using a strict typed action protocol. All side effects (tool execution,
        agent dispatch) are performed by the runtime, never by the LLM itself.

        Workflow Overview
        -----------------
        The inference loop follows a ReAct-style (Reasoning + Acting) pattern:

        1. **Query Injection**: The user query is added to the conversation history.

        2. **LLM Invocation**: The provider adapter returns one normalized ``LLMActionResult``. Native-capable adapters
           use provider tool/function calling and convert returned tool calls into Protolink actions. Fallback adapters
           call the model for JSON text and parse that JSON into the same action models. Raw client API calls are
           wrapped in a transient error handler with exponential backoff and random jitter.

        3. **Action Validation**: The action is validated against the type-safe ``LLMAction`` union. If validation
           fails, recursive field-level diagnostics (detailing the exact error location and type) are extracted from the
           Pydantic validation error and injected back into history for self-correction.

        4. **Action Dispatch**: Based on the validated action type:

           - ``final``: The loop terminates and returns the response content.
           - ``tool_call``: The specified tool is executed, and its result is injected back into the conversation
             history for the LLM to observe.
           - ``agent_call``: The request is delegated to another agent via the callback, and the result is similarly
             injected into history.

        5. **Iteration**: Steps 2-4 repeat until the LLM produces a ``final`` action or safety limits are exceeded.

        This design ensures the LLM remains stateless and purely declarative. The runtime maintains full control over
        execution, enabling observability, rate limiting, and consistent error handling across providers.

        Execution Model
        ---------------
        The LLM operates in a "thought → action → observation" cycle:

        - **Thought**: The LLM reasons about the task (internal, not exposed).
        - **Action**: The LLM outputs a JSON action declaring what it wants to do.
        - **Observation**: The runtime executes the action and injects the result as a new message, which the LLM
          observes on the next iteration.

        This continues until the LLM determines it has enough information to produce a final response to the user.

        Parameters
        ----------
        query : str
            The user-provided task or instruction to be processed by the agent.
        tools : dict[str, BaseTool]
            A mapping of tool names to executable tool instances available for invocation.
            Each tool must be callable with keyword arguments matching its schema.
        agent_callback : Callable[[str, str, dict[str, Any]], Awaitable[Any]], optional
            Async callback for handling ``agent_call`` actions. Signature::

                async def callback(agent_name: str, action_type: str, payload: dict) -> Any

            The callback receives the target agent's name, the action type (``tool_call`` or ``infer``), and the full
            payload. It should return the result from the delegated agent. If None, agent_call actions trigger
            self-correction guidance.
        agent_cards : list[Any], optional
            Discovered agent cards available for delegation. Provider-native adapters can use these to expose agent
            delegation tools; prompt-fallback parsing uses them to repair unambiguous legacy shorthand emitted by
            smaller local models.
        streaming : bool, default False
            Whether to invoke the underlying LLM in streaming mode. When True, the response is collected from an async
            generator before parsing.
        event_callback : Callable[[dict[str, Any]], Awaitable[None]], optional
            Async observer called with normalized inference events. Events include
            LLM chunks, parsed actions, tool execution results, delegated agent
            calls, final output, and recoverable errors. The callback is for
            observability only; the inference loop still returns a final ``Part``.
        action_authorizer : Callable[[RunAction], Awaitable[ActionAuthorization]], optional
            Runtime callback invoked after a model action has been validated but
            before a tool or delegated agent operation executes. The callback
            may enrich the action, enforce capability policy, and obtain an
            application-owned approval decision. Direct LLM usage may omit it;
            the ``Agent`` runtime supplies its configured authorizer.
        cancellation_token : CancellationToken, optional
            Live process-local token checked before model calls and action
            dispatch. The owning Agent also cancels this coroutine directly so
            awaited provider, tool, and delegation operations stop promptly.

        Returns
        -------
        Part
            A Part instance of type ``infer_output`` containing the final user-facing response produced by the agent.

        Raises
        ------
        RuntimeError
            Raised in the following scenarios:

            - **LLM call failure**: Network error, API error, or provider-specific issue that persists after retries.
            - **Unrecoverable tool error**: Tool execution raises an exception other than ``TypeError`` (which triggers
              self-correction).
            - **Parse circuit breaker**: 3 consecutive JSON parse or validation failures.
            - **Step limit exceeded**: ``MAX_INFER_STEPS`` reached without ``final``.

        Notes
        -----
        **Action Protocol**

        The runtime dispatches only validated ``LLMAction`` instances. Provider-native adapters expose Protolink tools
        as native functions/tools, then normalize returned provider calls into ``ToolCallAction`` or
        ``AgentCallAction``. Providers without reliable native tool support use the prompt JSON fallback, which must
        return a JSON object containing a ``type`` field matching the discriminated ``LLMAction`` union.

        Supported actions:

        - ``final``: Produce the final response. Requires ``content`` field.
        - ``tool_call``: Execute a local tool. Requires ``tool`` and ``args`` fields.
        - ``agent_call``: Delegate to another agent. Requires ``agent``, ``action``, and action-specific fields
          (``tool``/``args`` or ``prompt``).

        Example valid responses::

            {"type": "final", "content": "The weather in Athens is sunny, 28°C."}

            {"type": "tool_call", "tool": "get_weather", "args": {"location": "Athens"}}

            {"type": "agent_call", "action": "tool_call", "agent": "weather_agent",
             "tool": "get_weather", "args": {"location": "Athens"}}

        **Safety Guardrails**

        1. *Deduplication Detection*: Tracks recent actions in a sliding window of 5. If the LLM produces an identical
           action (same signature), the runtime injects corrective guidance rather than re-executing, preventing
           infinite loops.

        2. *Transient Error Resiliency*: API requests are protected by an exponential backoff handler with random
           jitter. It retries on rate limits (429), server overloads (529), 5xx response codes, timeouts, and network
           disconnects.

        3. *Granular Field-Level Self-Correction*: When Pydantic validation fails, the
           error message returned to the model includes the exact Pydantic validation trace
           (location, message, error type) rather than a generic parsing error, facilitating
           precise correction of schema violations.

        4. *Parse Failure Circuit Breaker*: After 3 consecutive JSON parse or schema validation failures, raises
           ``RuntimeError`` early rather than consuming the full step budget. Each failure injects corrective feedback.

        5. *Bounded Execution*: Hard limit of ``MAX_INFER_STEPS`` (default: 10) prevents runaway execution. If exceeded,
           raises ``RuntimeError``.

        See Also
        --------
        _inject_tool_call : Provider-specific hook for tool result injection.
        _inject_agent_call : Hook for agent delegation result injection.
        _compute_action_signature : Computes action fingerprints for deduplication.
        _call_with_retry : Wrapped executor for LLM API calls with backoff.
        _parse_infer_response : Validator for LLM responses using Pydantic action models.
        build_system_prompt : Constructs the system prompt with tools and agents.
        """

        if HISTORY_COMPACTION_TOOL_NAME in tools:
            raise ValueError(f"{HISTORY_COMPACTION_TOOL_NAME!r} is reserved by the LLM runtime")
        tools = dict(tools)
        tools[HISTORY_COMPACTION_TOOL_NAME] = self.compactor.tool

        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        self.history.add_user(query)

        steps: int = 0
        parse_failures: int = 0
        max_parse_failures: int = 3  # Circuit breaker for consecutive parse failures
        recent_actions: list[str] = []  # Track recent actions for dedup detection
        max_recent_actions: int = 5  # Window for detecting repeated actions

        async def emit(event: dict[str, Any]) -> None:
            if event_callback is not None:
                await event_callback(event)

        async def authorize_action(action: RunAction) -> ActionAuthorization | None:
            """Authorize one concrete action and emit its structured lifecycle."""
            if action_authorizer is None:
                return None

            try:
                authorization = await action_authorizer(action)
            except ApprovalRequiredError as exc:
                await emit({"type": "action_requested", "action": exc.action.to_dict()})
                await emit({"type": "policy_decision", "decision": exc.decision.to_dict()})
                await emit({"type": "approval_required", "request": exc.request.to_dict()})
                raise
            except ActionDeniedError as exc:
                await emit({"type": "action_requested", "action": exc.action.to_dict()})
                await emit({"type": "policy_decision", "decision": exc.decision.to_dict()})
                if exc.approval_request is not None:
                    await emit({"type": "approval_required", "request": exc.approval_request.to_dict()})
                if exc.approval_decision is not None:
                    await emit({"type": "approval_decision", "decision": exc.approval_decision.to_dict()})
                await emit({"type": "action_denied", "action": exc.action.to_dict(), "message": str(exc)})
                raise

            await emit({"type": "action_requested", "action": authorization.action.to_dict()})
            await emit({"type": "policy_decision", "decision": authorization.policy_decision.to_dict()})
            if authorization.approval_request is not None:
                await emit({"type": "approval_required", "request": authorization.approval_request.to_dict()})
            if authorization.approval_decision is not None:
                await emit({"type": "approval_decision", "decision": authorization.approval_decision.to_dict()})
            return authorization

        metrics_active = self.metrics_enabled and event_callback is not None

        while steps < MAX_INFER_STEPS:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            steps += 1
            await emit({"type": "llm_step", "step": steps})
            action_error: ValueError | None = None
            action_result: LLMActionResult | None = None
            call_metrics: LLMCallMetrics | None = None

            if metrics_active:
                context_tokens = estimate_token_count(self.history.messages, model=self.model)
                context_usage: LLMContextUsage = context_usage_from_tokens(
                    context_tokens,
                    self.metrics_profile,
                    estimated=True,
                )
                await emit(
                    {
                        "type": "llm_context",
                        "step": steps,
                        "provider": self.provider,
                        "model": self.model,
                        "context": context_usage.to_dict(),
                    }
                )

            # ─────────────────────────────────────────────────────────────────
            # Step 1: Ask the LLM adapter for one typed action
            # ─────────────────────────────────────────────────────────────────
            try:
                import time

                call_started_at = time.perf_counter()
                if streaming:

                    async def stream_action(current_step=steps):
                        async def emit_chunk(chunk: str) -> None:
                            await emit({"type": "llm_chunk", "step": current_step, "content": chunk})

                        return await self.call_action_stream(
                            self.history,
                            tools=tools,
                            agent_callback_available=agent_callback is not None,
                            agent_cards=agent_cards,
                            chunk_callback=emit_chunk,
                        )

                    action_result = await self._call_with_retry(stream_action)
                    raw_response = action_result.raw_response
                else:
                    action_result = await self._call_with_retry(
                        self.call_action,
                        self.history,
                        tools=tools,
                        agent_callback_available=agent_callback is not None,
                        agent_cards=agent_cards,
                    )
                    raw_response = action_result.raw_response
                    action_obj = action_result.action
                latency_ms = round((time.perf_counter() - call_started_at) * 1000, 3)
                response_metadata = dict(action_result.metadata if action_result is not None else {})
                if metrics_active and action_result is not None:
                    call_metrics = build_call_metrics(
                        step=steps,
                        provider=str(getattr(self, "provider", "")) or None,
                        model=self.model,
                        latency_ms=latency_ms,
                        input_value=self.history.messages,
                        output_value=action_result.raw_response,
                        profile=self.metrics_profile,
                        provider_usage=response_metadata.get("usage"),
                        streaming=streaming,
                        native=action_result.native,
                    )
                    metrics_payload = call_metrics.to_dict()
                    response_metadata["metrics"] = metrics_payload
                    await emit({"type": "llm_call_metrics", **metrics_payload})
                await emit(
                    {
                        "type": "llm_response",
                        "step": steps,
                        "streaming": streaming,
                        "native": action_result.native if action_result is not None else False,
                        "metadata": response_metadata,
                        "metrics": call_metrics.to_dict() if call_metrics else None,
                    }
                )
            except ValueError as e:
                action_error = e
            except Exception as e:
                await emit({"type": "llm_error", "step": steps, "message": str(e), "recoverable": False})
                raise RuntimeError(f"LLM call failed at step {steps}: {e}") from e

            # ─────────────────────────────────────────────────────────────────
            # Step 2: Normalize parsed action fields
            # ─────────────────────────────────────────────────────────────────
            try:
                if action_error is not None:
                    raise action_error
                if action_result is None:
                    raise ValueError("LLM adapter did not return an action result")
                action_obj = action_result.action
                raw_response = action_result.raw_response
                action = action_obj.type
                payload = action_obj.model_dump(exclude_none=True)
                parse_failures = 0  # Reset on success
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
            except ValueError as e:
                parse_failures += 1
                await emit(
                    {
                        "type": "llm_parse_error",
                        "step": steps,
                        "message": str(e),
                        "parse_failures": parse_failures,
                        "retry_count": parse_failures,
                        "recoverable": parse_failures < max_parse_failures,
                    }
                )
                if parse_failures >= max_parse_failures:
                    raise RuntimeError(
                        f"Failed to parse LLM output after {parse_failures} consecutive attempts. Last error: {e}"
                    ) from e
                # Inject error feedback to help LLM self-correct
                self.history.add_system(
                    f"Your previous response could not be parsed or validated. Error:\n{e}\n"
                    f"Return exactly one JSON action object, for example:\n"
                    f'{{"type":"final","content":"..."}}\n'
                    f'{{"type":"tool_call","tool":"tool_name","args":{{}}}}\n'
                    f'{{"type":"agent_call","agent":"agent_name","action":"infer","prompt":"..."}}\n'
                    f'{{"type":"agent_call","agent":"agent_name","action":"tool_call","tool":"tool_name","args":{{}}}}'
                )
                continue

            # ─────────────────────────────────────────────────────────────────
            # Step 3: Deduplication detection for repeated actions
            # ─────────────────────────────────────────────────────────────────
            await emit({"type": "llm_action", "step": steps, "action": action, "payload": payload})
            action_signature = self._compute_action_signature(action_obj)
            if action_signature in recent_actions:
                # Detected repeated action - inject guidance to prevent infinite loop
                await emit(
                    {
                        "type": "llm_retry",
                        "step": steps,
                        "reason": "duplicate_action",
                        "action": action,
                        "payload": payload,
                    }
                )
                self.history.add_system(
                    f"You have already performed this action: {action}. "
                    f"The result is in your context. Please proceed with your task - "
                    f"either produce a 'final' response or take a different action."
                )
                continue

            # Track recent actions (sliding window)
            recent_actions.append(action_signature)
            if len(recent_actions) > max_recent_actions:
                recent_actions.pop(0)

            # ─────────────────────────────────────────────────────────────────
            # Step 4: Handle action types
            # ─────────────────────────────────────────────────────────────────
            if isinstance(action_obj, FinalAction):
                content = action_obj.content
                # Add final response to history
                self.history.add_assistant(raw_response)
                await emit({"type": "llm_final", "step": steps, "content": content, "final": True})
                return Part("infer_output", content)

            elif isinstance(action_obj, ToolCallAction):
                # Add assistant call to history before result
                self.history.add_assistant(raw_response)

                # Validate tool_call payload
                tool_name = action_obj.tool
                tool_args = action_obj.args

                if tool_name not in tools:
                    available = list(tools.keys())
                    self.history.add_system(f"Unknown tool: '{tool_name}'. Available tools: {available}")
                    continue

                tool = tools[tool_name]

                try:
                    if cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
                    runtime_action = RunAction(
                        kind=("llm.history.compact" if tool_name == HISTORY_COMPACTION_TOOL_NAME else "tool.call"),
                        name=tool_name,
                        payload={"arguments": tool_args},
                        capabilities=frozenset(getattr(tool, "capabilities", None) or ()),
                        description=getattr(tool, "description", None) or None,
                    )
                    authorization = await authorize_action(runtime_action)
                    if authorization is not None:
                        authorized_arguments = authorization.action.payload.get("arguments", tool_args)
                        if not isinstance(authorized_arguments, dict):
                            raise TypeError("Authorized tool action payload.arguments must be a dictionary")
                        tool_args = authorized_arguments
                        action_id = authorization.action.action_id
                    else:
                        action_id = runtime_action.action_id
                    await emit(
                        {
                            "type": "tool_start",
                            "step": steps,
                            "tool": tool_name,
                            "args": tool_args,
                            "action_id": action_id,
                        }
                    )
                    tool_result = await tool(**tool_args)
                    if cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
                except ActionPolicyError:
                    raise
                except TypeError as e:
                    # Likely wrong arguments - help LLM correct
                    self.history.add_system(
                        f"Tool '{tool_name}' call failed due to argument error: {e}. "
                        f"Please check the tool's input_schema and try again."
                    )
                    continue
                except Exception as e:
                    await emit(
                        {
                            "type": "tool_error",
                            "step": steps,
                            "tool": tool_name,
                            "message": str(e),
                            "recoverable": False,
                        }
                    )
                    raise RuntimeError(f"Tool '{tool_name}' execution failed: {e}") from e

                await emit(
                    {
                        "type": "tool_result",
                        "step": steps,
                        "tool": tool_name,
                        "result": tool_result,
                        "action_id": action_id,
                    }
                )
                self._inject_tool_call(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                )
                continue

            elif isinstance(action_obj, AgentCallAction):
                if not agent_callback:
                    self.history.add_system(
                        "agent_call is not available in this context. "
                        "Please use 'tool_call' for local tools or produce a 'final' response."
                    )
                    continue

                # Add assistant call to history before result
                self.history.add_assistant(raw_response)

                # Validate agent_call payload
                agent_name = action_obj.agent
                agent_action = action_obj.action

                try:
                    if cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
                    runtime_action = RunAction(
                        kind="agent.call",
                        name=agent_name,
                        payload=payload,
                        capabilities=frozenset({"agent.delegate"}),
                        description=f"Delegate {agent_action} action to agent '{agent_name}'",
                    )
                    authorization = await authorize_action(runtime_action)
                    action_id = (
                        authorization.action.action_id if authorization is not None else runtime_action.action_id
                    )
                    await emit(
                        {
                            "type": "agent_call_start",
                            "step": steps,
                            "agent": agent_name,
                            "action": agent_action,
                            "payload": payload,
                            "action_id": action_id,
                        }
                    )
                    agent_result = await agent_callback(agent_name, agent_action, payload)
                    if cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
                except ActionPolicyError:
                    raise
                except ValueError as e:
                    # Agent not found or validation error - help LLM correct
                    self.history.add_system(f"Agent call failed: {e}")
                    continue
                except Exception as e:
                    await emit(
                        {
                            "type": "agent_call_error",
                            "step": steps,
                            "agent": agent_name,
                            "action": agent_action,
                            "message": str(e),
                            "recoverable": False,
                        }
                    )
                    raise RuntimeError(f"Agent call to '{agent_name}' failed: {e}") from e

                await emit(
                    {
                        "type": "agent_call_result",
                        "step": steps,
                        "agent": agent_name,
                        "action": agent_action,
                        "result": agent_result,
                        "action_id": action_id,
                    }
                )
                self._inject_agent_call(
                    agent_name=agent_name,
                    agent_action=agent_action,
                    agent_result=agent_result,
                )
                continue

            else:
                # Unknown action type - guide LLM to valid actions
                self.history.add_system(
                    f"Unknown action type: '{action}'. Valid actions are:\n"
                    f"- 'final': Produce final response\n"
                    f"- 'tool_call': Execute a tool\n"
                    f"- 'agent_call': Delegate to another agent"
                )
                continue

        raise RuntimeError(
            f"Maximum inference steps ({MAX_INFER_STEPS}) exceeded without producing final response. "
            f"The LLM may be stuck in a loop. Consider simplifying the task or checking prompts."
        )

    def _compute_action_signature(self, action: LLMAction) -> str:
        """
        Compute a unique signature for an action to detect duplicates.

        This enables deduplication detection to prevent infinite loops where the LLM repeatedly produces the same
        action with identical parameters.

        Parameters
        ----------
        action : LLMAction
            The action model instance.

        Returns
        -------
        str
            A deterministic string signature uniquely identifying this action.
        """
        import hashlib

        def canonical(value: Any) -> str:
            return json.dumps(value, sort_keys=True, default=json_history_default)

        if isinstance(action, ToolCallAction):
            key = f"tool_call:{action.tool}:{canonical(action.args or {})}"
        elif isinstance(action, AgentCallAction):
            if action.action == "tool_call":
                key = f"agent_call:{action.agent}:tool_call:{action.tool}:{canonical(action.args or {})}"
            else:
                key = f"agent_call:{action.agent}:infer:{action.prompt[:50] if action.prompt else ''}"
        else:
            # For final or other actions, use content hash
            content = getattr(action, "content", "")
            key = f"final:{hashlib.md5(content.encode()).hexdigest()[:8]}"

        return key

    def _parse_infer_response(
        self,
        response: str,
        *,
        tools: dict[str, "BaseTool"] | None = None,
        agent_cards: list[Any] | None = None,
    ) -> LLMAction:
        """
        Parse, validate, and normalize a raw LLM response using Pydantic action models.

        This method enforces a hard contract between the LLM and the runtime. The response must be a single,
        well-formed JSON object declaring exactly one supported action. Validation is performed by Pydantic's
        ``TypeAdapter`` against the discriminated ``LLMAction`` union.

        On validation failure, field-level diagnostics are extracted from Pydantic's ``ValidationError`` and
        formatted into a precise, human-readable error message to maximize the LLM's ability to self-correct
        on the next iteration.

        Args:
            response: The raw string output returned by the language model.
            tools: Local tools available to the current agent, used only for
                unambiguous fallback-shorthand repair.
            agent_cards: Discovered agents available for delegation, used only
                for unambiguous fallback-shorthand repair.

        Returns:
            The parsed and validated action model (FinalAction, ToolCallAction, or AgentCallAction).

        Raises:
            ValueError: If the response is not valid JSON or fails Pydantic validation.
        """
        try:
            data = json.loads(response, strict=False)
        except json.JSONDecodeError as e:
            # Try to find JSON within the text (e.g. if wrapped in code blocks or mixed with text)
            try:
                start = response.find("{")
                end = response.rfind("}")

                if start != -1 and end != -1 and start < end:
                    json_str = response[start : end + 1]
                    data = json.loads(json_str, strict=False)
                else:
                    raise e
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON: {e}\nRaw response: {response}") from e

        from pydantic import ValidationError

        data = self._repair_fallback_action_payload(data, tools=tools or {}, agent_cards=agent_cards or [])

        try:
            return validate_action_payload(data)
        except ValidationError as e:
            diagnostics = self._format_validation_errors(e)
            raise ValueError(
                f"Action validation failed. Field-level errors:\n{diagnostics}\nParsed data: {data}"
            ) from e
        except Exception as e:
            raise ValueError(f"Action validation failed: {e}\nParsed data: {data}") from e

    @staticmethod
    def _repair_fallback_action_payload(
        data: Any,
        *,
        tools: dict[str, "BaseTool"],
        agent_cards: list[Any],
    ) -> Any:
        """Repair narrow, legacy prompt-fallback action shorthands.

        The runtime still dispatches only strict ``LLMAction`` models. This
        helper runs before validation and converts a few historical or
        small-model-friendly forms into the canonical shape when the repair is
        deterministic. It is intentionally conservative:

        - ``payload`` dictionaries are flattened for older examples.
        - ``prompt: "tool_name(arg=value)"`` is parsed as a function-call
          shorthand for tool calls.
        - A missing delegated-agent name is inferred only when exactly one
          discovered agent advertises the requested tool.

        If the target tool or agent cannot be inferred safely, the original data
        is returned and normal Pydantic diagnostics drive self-correction.
        """
        if not isinstance(data, dict):
            return data

        repaired = dict(data)
        payload = repaired.get("payload")
        if isinstance(payload, dict):
            for key in ("agent", "action", "tool", "args", "prompt", "content"):
                if key not in repaired and key in payload:
                    repaired[key] = payload[key]
            repaired.pop("payload", None)

        if repaired.get("type") == "tool_call" and "args" not in repaired:
            prompt = repaired.get("prompt")
            parsed_call = LLM._parse_function_call_shorthand(prompt) if isinstance(prompt, str) else None
            if parsed_call is not None:
                tool_name, call_args, _agent_name = parsed_call
                repaired.setdefault("tool", tool_name)
                repaired["args"] = call_args
                repaired.pop("prompt", None)

        if repaired.get("type") != "agent_call":
            return repaired

        if repaired.get("action") not in {"tool_call", None}:
            return repaired

        prompt = repaired.get("prompt")
        parsed_call = LLM._parse_function_call_shorthand(prompt) if isinstance(prompt, str) else None
        if parsed_call is not None:
            tool_name, call_args, agent_from_prompt = parsed_call
            repaired.setdefault("action", "tool_call")
            repaired.setdefault("tool", tool_name)
            repaired.setdefault("args", call_args)
            if agent_from_prompt and "agent" not in repaired:
                repaired["agent"] = agent_from_prompt
            repaired.pop("prompt", None)

        tool_name = repaired.get("tool")
        if isinstance(tool_name, str) and "agent" not in repaired:
            agent_name = LLM._infer_unique_agent_for_tool(tool_name, agent_cards)
            if agent_name:
                repaired["agent"] = agent_name
            elif tool_name in tools:
                return {"type": "tool_call", "tool": tool_name, "args": repaired.get("args") or {}}

        return repaired

    @staticmethod
    def _parse_function_call_shorthand(value: str | None) -> tuple[str, dict[str, Any], str | None] | None:
        """Parse ``tool(arg=value)`` or ``agent.tool(arg=value)`` fallback text.

        This is not a general expression evaluator; it accepts only Python AST
        function-call syntax with literal arguments. Positional arguments are
        supported only when they are a single dictionary literal, because there
        is no reliable way to map arbitrary positional values to tool parameter
        names without the target schema.
        """
        if not value:
            return None
        text = value.strip().strip("`")
        try:
            expr = ast.parse(text, mode="eval").body
        except SyntaxError:
            return None
        if not isinstance(expr, ast.Call):
            return None

        agent_name: str | None = None
        if isinstance(expr.func, ast.Name):
            tool_name = expr.func.id
        elif isinstance(expr.func, ast.Attribute):
            tool_name = expr.func.attr
            if isinstance(expr.func.value, ast.Name):
                agent_name = expr.func.value.id
        else:
            return None

        args: dict[str, Any] = {}
        if len(expr.args) == 1 and not expr.keywords:
            try:
                literal = ast.literal_eval(expr.args[0])
            except (ValueError, TypeError):
                return None
            if not isinstance(literal, dict):
                return None
            args = literal
        elif expr.args:
            return None

        for keyword in expr.keywords:
            if keyword.arg is None:
                return None
            try:
                args[keyword.arg] = ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                return None

        return tool_name, args, agent_name

    @staticmethod
    def _infer_unique_agent_for_tool(tool_name: str, agent_cards: list[Any]) -> str | None:
        """Return the only discovered agent advertising ``tool_name``, if any."""
        candidates: list[str] = []
        for card in agent_cards:
            agent_name = getattr(card, "name", None)
            for skill in getattr(card, "skills", []) or []:
                if getattr(skill, "id", None) == tool_name and agent_name:
                    candidates.append(str(agent_name))
        unique = sorted(set(candidates))
        return unique[0] if len(unique) == 1 else None

    @staticmethod
    def _format_validation_errors(exc: Any) -> str:
        """
        Extract precise, field-level diagnostics from a Pydantic ``ValidationError``.

        Produces a human-readable bullet list of every field error, including the full
        location path (e.g. ``agent_call -> prompt``) and the Pydantic error message.
        This feedback is injected into the conversation history so the LLM can self-correct
        with maximum precision on the next turn.

        Args:
            exc: A Pydantic ``ValidationError`` instance.

        Returns:
            A multi-line string with one bullet per validation error.
        """
        lines: list[str] = []
        try:
            for error in exc.errors():
                loc = " -> ".join(str(part) for part in error.get("loc", []))
                msg = error.get("msg", "unknown error")
                err_type = error.get("type", "")
                if loc:
                    lines.append(f"  - Field '{loc}': {msg} (type: {err_type})")
                else:
                    lines.append(f"  - {msg} (type: {err_type})")
        except Exception:
            lines.append(f"  - {exc}")
        return "\n".join(lines) if lines else str(exc)

    async def _call_with_retry(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a callable with exponential backoff and jitter on transient failures.

        This method wraps LLM API calls to handle transient errors gracefully:
        - HTTP 429 (rate limit) / 529 (overloaded)
        - HTTP 5xx (server errors)
        - Connection timeouts and network errors

        Non-transient errors (e.g. authentication failures, invalid requests) are raised
        immediately without consuming the retry budget.

        The backoff schedule uses exponential delay with random jitter to prevent the
        "thundering herd" problem when multiple agents hit rate limits simultaneously.

        Parameters
        ----------
        fn : Callable
            The function to execute. May be sync or async.
        *args : Any
            Positional arguments forwarded to ``fn``.
        **kwargs : Any
            Keyword arguments forwarded to ``fn``. The retry controls
            ``max_retries``, ``base_delay``, and ``max_delay`` may be provided
            as keyword-only values and are consumed before calling ``fn``.
        max_retries : int
            Maximum number of retry attempts. Defaults to 3.
        base_delay : float
            Initial delay in seconds before the first retry. Defaults to 1.0.
        max_delay : float
            Maximum delay cap in seconds. Defaults to 30.0.

        Returns
        -------
        Any
            The return value of ``fn``.

        Raises
        ------
        Exception
            The last exception encountered if all retries are exhausted, or immediately
            for non-transient errors.
        """
        import asyncio
        import random

        max_retries = int(kwargs.pop("max_retries", 3))
        base_delay = float(kwargs.pop("base_delay", 1.0))
        max_delay = float(kwargs.pop("max_delay", 30.0))
        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                # If the callable returned a coroutine, await it
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except Exception as e:
                last_exception = e

                # Determine if this is a retryable (transient) error
                if not self._is_transient_error(e):
                    raise

                if attempt >= max_retries:
                    raise

                # Exponential backoff with jitter
                delay = min(base_delay * (2**attempt), max_delay)
                jitter = random.uniform(0, delay * 0.5)
                await asyncio.sleep(delay + jitter)

        # Should never reach here, but satisfy the type checker
        if last_exception is None:
            raise RuntimeError("retry loop exited without returning a result or capturing an exception")
        raise last_exception

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        """
        Determine whether an exception represents a transient failure worth retrying.

        Checks for:
        - HTTP status codes 429 (rate limit), 529 (overloaded), and 5xx (server errors)
        - Connection-related errors (timeout, refused, reset)
        - Provider-specific rate limit / overloaded exception types

        Args:
            exc: The exception to classify.

        Returns:
            True if the error is transient and the call should be retried.
        """
        # Check for HTTP status code on the exception object (common across providers)
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status, int):
            if status == 429 or status == 529 or 500 <= status < 600:
                return True

        # Check exception class name for provider-specific rate limit types
        exc_name = type(exc).__name__.lower()
        transient_names = {"ratelimiterror", "ratelimit", "overloaded", "overloadederror", "apitimeouterror"}
        if exc_name in transient_names:
            return True

        # Check for connection-level errors
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True

        # Check the string representation as a last resort
        msg = str(exc).lower()
        if any(keyword in msg for keyword in ("rate limit", "429", "overloaded", "timeout", "timed out", "connection")):
            return True

        return False

    def get_action_schema(self) -> dict[str, Any]:
        """Get the exact Pydantic JSON schema for the runtime action union."""
        from protolink.llms.actions import ACTION_ADAPTER

        return ACTION_ADAPTER.json_schema()

    def get_prompt_action_schema(self) -> dict[str, Any]:
        """Get the root-object JSON schema used by prompt fallback adapters.

        Native tool-capable providers should expose each real tool as a native
        function/tool declaration instead of using this schema for every action.
        The schema exists for JSON-mode fallbacks that can constrain a single
        response object but cannot represent provider-native tool calls.
        """
        return prompt_action_schema()

    def get_openai_action_schema(self) -> dict[str, Any]:
        """Compatibility alias for the prompt fallback action schema.

        OpenAI-native action acquisition no longer uses this method because a
        generic action schema cannot safely express dynamic tool arguments under
        strict structured outputs. Use provider tools instead.
        """
        return self.get_prompt_action_schema()

    def get_inlined_action_schema(self) -> dict[str, Any]:
        """Get the JSON schema for LLMAction with all reference definitions inlined."""
        from protolink.llms.actions import inline_refs

        return inline_refs(self.get_action_schema())

    def _inject_tool_call(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Any,
    ) -> None:
        """
        Handle the completion of a tool invocation and inject its result into the conversation history in a
        provider-agnostic way.

        This default implementation serializes the tool execution result into a system message, allowing the model to
        observe the outcome of the tool call without relying on provider-specific message roles (e.g. `role="tool"`).

        The message is intentionally added as a system message to:
        - Maintain compatibility across LLM providers (OpenAI, Anthropic, Ollama, etc.)
        - Avoid strict role validation errors imposed by some APIs
        - Preserve a single, unified inference loop in the base `LLM` class

        Subclasses representing providers with native tool-calling semantics SHOULD override this method.

        Such providers typically require:
        - A dedicated message role (e.g. `role="tool"`)
        - A correlation identifier linking the tool result to the originating assistant tool call (e.g. `tool_call_id`)
        - The tool result in a user or assistant message

        In these cases, the subclass implementation should translate the completed tool execution into the exact message
        structure expected by the provider's API and append it to the conversation history accordingly.

        This design allows provider-specific protocol requirements to be encapsulated entirely within the subclass,
        while preserving a single, shared inference loop in the base `LLM` class. The base loop remains unaware of
        message role constraints, correlation identifiers, or transport-level validation rules.

        Parameters
        ----------
        tool_name : str
            The name of the tool that was invoked by the model.

        tool_args : dict[str, Any]
            The arguments that were passed to the tool by the model.
            This is provided for observability and debugging purposes and is not used directly in the default
            implementation.

        tool_result : Any
            The result returned by the tool execution. This value must be JSON-serializable or convertible to a string
            representation.

        Returns
        -------
        None
            This method mutates the internal conversation history in-place and does not return a value.
        """
        self.history.add_system(
            json.dumps(
                {
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": tool_result,
                },
                default=json_history_default,
            )
        )

    def _inject_agent_call(
        self,
        *,
        agent_name: str,
        agent_action: str,
        agent_result: Any,
    ) -> None:
        """
        Inject the result of an agent delegation into the conversation history.

        This method records the outcome of an agent_call action, allowing the LLM to observe the result of delegating
        work to another agent. The default implementation uses a system message with structured JSON, maintaining
        compatibility across LLM providers.

        Subclasses may override this method if they require provider-specific message formats for agent delegation
        results, though this is less common than tool-call customization.

        Parameters
        ----------
        agent_name : str
            The name of the agent that was invoked.

        agent_action : str
            The action type performed by the agent (\"tool_call\" or \"infer\").

        agent_result : Any
            The result returned by the delegated agent. Must be JSON-serializable.

        Returns
        -------
        None
            Mutates the internal conversation history in-place.
        """
        self.history.add_system(
            json.dumps(
                {
                    "type": "agent_result",
                    "agent": agent_name,
                    "action": agent_action,
                    "result": agent_result,
                },
                default=json_history_default,
            )
        )

    # ----------------------------------------------------------------------
    # Prompt management
    # ----------------------------------------------------------------------

    def build_system_prompt(
        self,
        user_instructions: str | None = None,
        agent_cards: str | None = None,
        tools: str | None = None,
        *,
        action_mode: Literal["json", "native"] | None = None,
        flow_instructions: str | None = None,
        override_system_prompt: bool = False,
        persist: bool = False,
        agent_name: str | None = None,
    ) -> str:
        """
        Build the final system prompt for the LLM.

        This function combines:
        - Base agent instructions
        - Chain of thought instructions (if enabled)
        - Tool calling prompt
        - Agent delegation prompt
        - User-provided instructions

        If any of the optional parameters are not provided, they will be omitted from the final prompt.

        Args:
            user_instructions: Optional instructions from the user to customize behavior.
            agent_cards: JSON/text describing available agents for delegation.
            tools: JSON/text describing available tools for this agent.
            action_mode: Explicit prompt protocol. ``"json"`` uses the simple
                Protolink JSON action contract. ``"native"`` uses provider tool
                instructions and leaves tool-call syntax to the backend. When
                omitted, the LLM's ``uses_native_action_prompt`` property is
                used.
            flow_instructions: Optional flow context instructions (e.g. pipeline step awareness).
            override_system_prompt: Whether to override completely the system prompt with the user defined prompt.
            persist: If True, updates the system prompt in history without wiping conversation turns.
                If False (default), resets history to only include the new system prompt.
            agent_name: The registered name of the current agent to prevent self-delegation.

        Returns:
            A fully assembled, machine-readable prompt string suitable for sending to the LLM.
        """

        if override_system_prompt:
            self.system_prompt = user_instructions or ""
        else:
            tools = self.compactor.append_tool_prompt(tools)
            # Guardrail: Prevent agent from delegating to itself and provide ID
            agent_identity_prompt = ""
            if agent_name:
                agent_identity_prompt = (
                    f"Your registered name in the system is '{agent_name}'. "
                    f"You are executing as '{agent_name}'. Do NOT attempt to delegate tasks to yourself."
                )
            resolved_action_mode = action_mode or ("native" if self.uses_native_action_prompt else "json")
            if resolved_action_mode == "native":
                self.system_prompt = NATIVE_SYSTEM_PROMPT.format(
                    native_base_instructions=NATIVE_BASE_INSTRUCTIONS,
                    native_reasoning_instructions=NATIVE_SYSTEM_REASONING_MAP.get(self._reasoning, ""),
                    agent_identity_prompt=agent_identity_prompt,
                    native_tool_prompt=NATIVE_TOOL_PROMPT if tools else NATIVE_NO_TOOL_PROMPT,
                    native_agent_prompt=NATIVE_AGENT_LIST_PROMPT.replace("{{agent_cards_from_registry}}", agent_cards)
                    if agent_cards
                    else "",
                    user_instructions=user_instructions or "",
                    flow_instructions=flow_instructions or "",
                )
            else:
                self.system_prompt = BASE_SYSTEM_PROMPT.format(
                    base_instructions=BASE_INSTRUCTIONS,
                    reasoning_instructions=SYSTEM_REASONING_MAP.get(self._reasoning, ""),
                    agent_identity_prompt=agent_identity_prompt,
                    tool_call_prompt=TOOL_CALL_PROMPT.replace("{{tools}}", tools)
                    if tools
                    else "No tools are available for you to call. You cannot return a tool call response.",
                    agent_call_prompt=AGENT_LIST_PROMPT.replace("{{agent_cards_from_registry}}", agent_cards)
                    if agent_cards
                    else "",
                    user_instructions=user_instructions or "",
                    flow_instructions=flow_instructions or "",
                )

        if persist:
            self.history.set_system(self.system_prompt)
        else:
            self.history.reset_to_system(self.system_prompt)

        return self.system_prompt

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    @abstractmethod
    def validate_connection(self) -> bool:
        """Validate the connection to the LLM API, server, or local model. Should handle the logging."""
        raise NotImplementedError

    # ----------------------------------------------------------------------
    # Setter methods
    # ----------------------------------------------------------------------

    @property
    def model_params(self) -> dict[str, Any]:
        """
        Model/provider-specific generation parameters.
        """
        return self._model_params

    @model_params.setter
    def model_params(self, value: dict[str, Any]) -> None:
        """Model Params Setter method.
        Correct Usage Examples:
            llm.model_params["temperature"] = 0.2  # allowed
            llm.model_params = {"temperature": 0.3}  # validated
        """
        if not isinstance(value, dict):
            raise TypeError("model_params must be a dict")
        self._model_params = value

    def set_system_prompt(self, system_prompt: str) -> None:
        """Set the system prompt for the LLM.

        Overrides the default system prompt with a custom one.

        Args:
            system_prompt: New system prompt to use
        """
        self.system_prompt = system_prompt

    # ----------------------------------------------------------------------
    # Callable interface
    # ----------------------------------------------------------------------

    def __call__(self, history: ConversationHistory) -> str:
        """Make the LLM instance callable.

        Allows using the LLM as a function: llm(history) -> str

        Args:
            history: Conversation history to use

        Returns:
            str: Response from the LLM
        """
        return self.call(history)

    def __str__(self) -> str:
        """String representation of the LLM instance."""
        return f"{self.provider} {self.model_type}"

    def __repr__(self) -> str:
        """Detailed string representation of the LLM instance."""
        return self.__str__()


class SyncLLM:
    """Synchronous wrapper around LLM.

    This class provides blocking equivalents of async methods
    for use in:
    - scripts
    - CLI tools
    - notebooks without async support

    Internally uses `asyncio.run()` to execute async operations.

    Warning:
        This API should NOT be used inside an active event loop
        (e.g., FastAPI, Jupyter async cells).
    """

    def __init__(self, llm: "LLM"):
        self._llm = llm

    def infer(
        self,
        *,
        query: str,
        tools: dict[str, "BaseTool"],
        agent_callback: Callable[[str, str, dict[str, Any]], Awaitable[Any]] | None = None,
        agent_cards: list[Any] | None = None,
        streaming: bool = False,
        event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> "Part":
        """Synchronously execute the inference loop.

        This is a blocking version of `infer()`.

        Internally runs the async implementation in a new event loop.
        """
        return asyncio.run(
            self._llm.infer(
                query=query,
                tools=tools,
                agent_callback=agent_callback,
                agent_cards=agent_cards,
                streaming=streaming,
                event_callback=event_callback,
            )
        )
