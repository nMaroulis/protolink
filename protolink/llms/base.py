import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from protolink.tools import BaseTool

from protolink.core.part import Part
from protolink.llms.history import ConversationHistory
from protolink.llms.prompts import AGENT_LIST_PROMPT, BASE_INSTRUCTIONS, BASE_SYSTEM_PROMPT, TOOL_CALL_PROMPT
from protolink.tools import BaseTool
from protolink.types import LLMProvider, LLMType

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
    - `system_prompt` (str): Optional system instructions used as context for the
      model when generating responses. Uses default prompts for agent, tool and llm calling.

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
    ) -> None:
        # ---- Instance state ----
        self.model: str = model
        self._model_params: dict[str, Any] = model_params

        self.history: ConversationHistory = ConversationHistory()
        self.system_prompt: str = self.build_system_prompt()

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
        streaming: bool = False,
    ) -> "Part":
        """
        Execute a controlled, multi-step inference loop against the configured LLM.

        This method implements a deterministic agent runtime over a stateless language model. The LLM is invoked
        iteratively to *declare intent only* using a strict JSON action protocol. All side effects (tool execution,
        agent dispatch) are performed by the runtime, never by the LLM itself.

        Workflow Overview
        -----------------
        The inference loop follows a ReAct-style (Reasoning + Acting) pattern:

        1. **Query Injection**: The user query is added to the conversation history.

        2. **LLM Invocation**: The LLM generates a JSON response declaring its next action.

        3. **Response Parsing**: The runtime parses and validates the JSON response.
           If parsing fails, corrective feedback is injected and the loop retries.

        4. **Action Dispatch**: Based on the action type:

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
        streaming : bool, default False
            Whether to invoke the underlying LLM in streaming mode. When True, the response is collected from an async
            generator before parsing.

        Returns
        -------
        Part
            A Part instance of type ``infer_output`` containing the final user-facing response produced by the agent.

        Raises
        ------
        RuntimeError
            Raised in the following scenarios:

            - **LLM call failure**: Network error, API error, or provider-specific issue.
            - **Unrecoverable tool error**: Tool execution raises an exception other than ``TypeError`` (which triggers
            self-correction).
            - **Parse circuit breaker**: 3 consecutive JSON parse failures.
            - **Step limit exceeded**: ``MAX_INFER_STEPS`` reached without ``final``.

        Notes
        -----
        **Action Protocol**

        The LLM must respond with JSON containing a ``type`` field. Supported actions:

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

        2. *Parse Failure Circuit Breaker*: After 3 consecutive JSON parse failures, raises ``RuntimeError`` early
           rather than consuming the full step budget. Each failure injects corrective feedback to help the LLM
           self-correct.

        3. *Self-Correcting Recovery*: Instead of failing immediately on validation errors, the runtime injects
           helpful context back into the conversation:

           - Unknown tool → lists available tools
           - Missing required fields → shows expected JSON format
           - Type errors (wrong args) → prompts to check input_schema
           - Agent not found → provides error details

        4. *Bounded Execution*: Hard limit of ``MAX_INFER_STEPS`` (default: 10) prevents runaway execution. If exceeded,
           raises ``RuntimeError``.

        See Also
        --------
        _inject_tool_call : Provider-specific hook for tool result injection.
        _inject_agent_call : Hook for agent delegation result injection.
        _compute_action_signature : Computes action fingerprints for deduplication.
        build_system_prompt : Constructs the system prompt with tools and agents.
        """

        self.history.add_user(query)

        steps: int = 0
        parse_failures: int = 0
        max_parse_failures: int = 3  # Circuit breaker for consecutive parse failures
        recent_actions: list[str] = []  # Track recent actions for dedup detection
        max_recent_actions: int = 5  # Window for detecting repeated actions

        while steps < MAX_INFER_STEPS:
            steps += 1

            # ─────────────────────────────────────────────────────────────────
            # Step 1: Call the LLM
            # ─────────────────────────────────────────────────────────────────
            try:
                if streaming:
                    chunks = []
                    async for chunk in self.call_stream(self.history):
                        chunks.append(chunk)
                    raw_response = "".join(chunks)
                else:
                    raw_response = self.call(self.history)
            except Exception as e:
                raise RuntimeError(f"LLM call failed at step {steps}: {e}") from e

            # ─────────────────────────────────────────────────────────────────
            # Step 2: Parse the response with retry budget
            # ─────────────────────────────────────────────────────────────────
            try:
                action, payload = self._parse_infer_response(raw_response)
                parse_failures = 0  # Reset on success
            except ValueError as e:
                parse_failures += 1
                if parse_failures >= max_parse_failures:
                    raise RuntimeError(
                        f"Failed to parse LLM output after {parse_failures} consecutive attempts. Last error: {e}"
                    ) from e
                # Inject error feedback to help LLM self-correct
                self.history.add_system(
                    f"Your previous response could not be parsed as valid JSON. Error: {e}\n"
                    f"Please respond with a valid JSON object containing 'type' and required fields."
                )
                continue

            # ─────────────────────────────────────────────────────────────────
            # Step 3: Deduplication detection for repeated actions
            # ─────────────────────────────────────────────────────────────────
            action_signature = self._compute_action_signature(action, payload)
            if action_signature in recent_actions:
                # Detected repeated action - inject guidance to prevent infinite loop
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
            if action == "final":
                content = payload.get("content")
                if content is None:
                    self.history.add_system(
                        "Your 'final' response is missing 'content'. Please provide: "
                        '{"type": "final", "content": "<your response>"}'
                    )
                    continue
                return Part("infer_output", content)

            elif action == "tool_call":
                # Validate tool_call payload
                tool_name = payload.get("tool")
                tool_args = payload.get("args", {})

                if not tool_name:
                    self.history.add_system(
                        "Your 'tool_call' is missing 'tool' field. Please specify which tool to call."
                    )
                    continue

                if tool_name not in tools:
                    available = list(tools.keys())
                    self.history.add_system(f"Unknown tool: '{tool_name}'. Available tools: {available}")
                    continue

                tool = tools[tool_name]

                try:
                    tool_result = await tool(**tool_args)
                except TypeError as e:
                    # Likely wrong arguments - help LLM correct
                    self.history.add_system(
                        f"Tool '{tool_name}' call failed due to argument error: {e}. "
                        f"Please check the tool's input_schema and try again."
                    )
                    continue
                except Exception as e:
                    raise RuntimeError(f"Tool '{tool_name}' execution failed: {e}") from e

                self._inject_tool_call(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                )
                continue

            elif action == "agent_call":
                if not agent_callback:
                    self.history.add_system(
                        "agent_call is not available in this context. "
                        "Please use 'tool_call' for local tools or produce a 'final' response."
                    )
                    continue

                # Validate agent_call payload
                agent_name = payload.get("agent")
                agent_action = payload.get("action")

                if not agent_name:
                    self.history.add_system(
                        "Your 'agent_call' is missing 'agent' field. Please specify which agent to call."
                    )
                    continue

                if agent_action not in {"tool_call", "infer"}:
                    self.history.add_system(
                        f"Invalid agent_call action: '{agent_action}'. Must be 'tool_call' or 'infer'."
                    )
                    continue

                try:
                    agent_result = await agent_callback(agent_name, agent_action, payload)
                except ValueError as e:
                    # Agent not found or validation error - help LLM correct
                    self.history.add_system(f"Agent call failed: {e}")
                    continue
                except Exception as e:
                    raise RuntimeError(f"Agent call to '{agent_name}' failed: {e}") from e

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

    def _compute_action_signature(self, action: str, payload: dict[str, Any]) -> str:
        """
        Compute a unique signature for an action to detect duplicates.

        This enables deduplication detection to prevent infinite loops where the LLM repeatedly produces the same
        action with identical parameters.

        Parameters
        ----------
        action : str
            The action type (``final``, ``tool_call``, or ``agent_call``).
        payload : dict[str, Any]
            The action payload containing action-specific fields.

        Returns
        -------
        str
            A deterministic string signature uniquely identifying this action.
            For ``tool_call``: includes tool name and sorted args.
            For ``agent_call``: includes agent, action type, and relevant params.
            For other actions: includes MD5 hash of payload.
        """
        import hashlib

        if action == "tool_call":
            key = f"tool_call:{payload.get('tool')}:{sorted(payload.get('args', {}).items())}"
        elif action == "agent_call":
            agent = payload.get("agent")
            agent_action = payload.get("action")
            if agent_action == "tool_call":
                key = f"agent_call:{agent}:tool_call:{payload.get('tool')}:{sorted(payload.get('args', {}).items())}"
            else:
                key = f"agent_call:{agent}:infer:{payload.get('prompt', '')[:50]}"
        else:
            # For final or other actions, use content hash
            key = f"{action}:{hashlib.md5(str(payload).encode()).hexdigest()[:8]}"

        return key

    def _parse_infer_response(self, response: str) -> tuple[str, dict[str, Any]]:
        """
        Parse, validate, and normalize a raw LLM response for agent execution.

        Args:
            response (str):
                The raw string output returned by the language model.

        Returns:
            tuple[str, dict[str, Any]]:
                A tuple containing:
                - The declared action type (e.g. ``final``, ``tool_call``, ``agent_call``)
                - A normalized payload dictionary for downstream execution

        Raises:
            ValueError:
                If the response is not valid JSON, does not declare a supported action, or is missing required fields
                for the declared action type.

        Notes:
        This function enforces a hard contract between the LLM and the runtime by requiring the response to be a single,
        well-formed JSON object declaring exactly one supported action. It validates both the structural integrity of
        the JSON payload and the semantic correctness of required fields for each action type.

        Unsupported actions, missing fields, or malformed JSON are rejected immediately with explicit errors, enabling
        robust retry, logging, or failure handling at the orchestration layer.

        The output of this function is guaranteed to be safe for downstream execution logic and free of implicit
        assumptions or provider-specific artifacts.
        """
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}\nRaw response: {response}") from e

        action = data.get("type")
        if action not in {"final", "tool_call", "agent_call"}:
            raise ValueError(f"Unsupported action type: {action}\nRaw response: {response}")

        if action == "final":
            content = data.get("content")
            if not isinstance(content, str):
                raise ValueError(f"Final response must have a 'content' string.\nRaw response: {response}")
            return action, {"content": content}

        # tool_call or agent_call
        if action in {"tool_call", "agent_call"} and not isinstance(data, dict):
            raise ValueError(f"{action} response must be a JSON object.\nRaw response: {response}")

        return action, data

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
                }
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
                }
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
        override_system_prompt: bool = False,
    ) -> str:
        """
        Build the final system prompt for the LLM.

        This function combines:
        - Base agent instructions
        - Tool calling prompt
        - Agent delegation prompt
        - User-provided instructions

        If any of the optional parameters are not provided, they will be omitted from the final prompt.

        Args:
            user_instructions: Optional instructions from the user to customize behavior.
            agent_cards: JSON/text describing available agents for delegation.
            tools: JSON/text describing available tools for this agent.
            override_system_prompt: Whether to override comletely the system prompt with the user defined prompt.

        Returns:
            A fully assembled, machine-readable prompt string suitable for sending to the LLM.

        Example:
            >>> user_instructions = "Always use the weather tool first if the user asks about weather."
            >>> agent_cards = '[{"name": "weather_forecaster", "tools": ["get_weather"]}]'
            >>> tools = '[{"name": "get_weather", "args": ["location"]}]'
            >>> prompt = build_system_prompt(user_instructions, agent_cards, tools)
            >>> print(prompt[:500])  # preview the first 500 characters
        """

        if override_system_prompt:
            self.system_prompt = user_instructions or ""
        else:
            self.system_prompt = BASE_SYSTEM_PROMPT.format(
                base_instructions=BASE_INSTRUCTIONS,
                tool_call_prompt=TOOL_CALL_PROMPT.replace("{{tools}}", tools)
                if tools
                else "No tools are available for you to call. You cannot return a tool call response.",
                agent_call_prompt=AGENT_LIST_PROMPT.replace("{{agent_cards_from_registry}}", agent_cards)
                if agent_cards
                else "",
                user_instructions=user_instructions or "",
            )
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
