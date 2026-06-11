import json
from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar

from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory


class MockLLM(LLM):
    """
    A premium, fully customizable Mock LLM provider for testing and debugging.

    Features:
    1. Offline & Dependency-Free: Works without any API keys or local servers.
    2. Overridable Method: Simply subclass and override `mock_call(last_user_msg, system_prompt)`
       for dynamic Python logic without dealing with message extraction or JSON formatting.
    3. Declarative Nested Mappings: Provide a nested dict like `{"writer": {"draft": "...", "*": "..."}}`
       to match system prompts and conditional user keywords declaratively with no code.
    4. Sequential Responses: Provide a `sequential_responses` list to mock sequential conversational turns.
    5. Action Protocol Compliance: Automatically wraps raw strings/dicts into Protolink's JSON Action
       Protocol ({"type": "final", "content": ...}) so you don't have to write JSON syntax manually.

    Usage Examples:

    Option A: Simple Static Response (Basic Generic Mock)
    ----------------------------------------------------
    ```python
    from protolink.llms import MockLLM

    # Returns a static generic response for any query (perfect for fast testing)
    llm = MockLLM(default_response="Mocked response content")
    ```

    Option B: Declarative Mappings (Pure Configuration for Multi-Agent & A2A Routing)
    --------------------------------------------------------------------------------
    ```python
    from protolink.llms import MockLLM

    llm = MockLLM(
        mock_responses={
            # Matches keyword in the agent's system prompt:
            "writer": {
                # Conditional matching based on keywords in the last user message:
                "bad": "Draft: This needs editing. [ROUTE: editor]",
                "draft": "Draft: This is a draft. [ROUTE: editor]",
                # Fallback if no user keywords match:
                "*": "Perfect output! [ROUTE: qa]",
            },
            "editor": "[EDITED] Polished the content beautifully.",
            "qa": "[APPROVED] QA verified successfully.",
        }
    )
    ```

    Option C: Subclass and Override (Dynamic Python Logic)
    -----------------------------------------------------
    ```python
    from protolink.llms import MockLLM

    class CustomMockLLM(MockLLM):
        def mock_call(self, last_user_msg: str, system_prompt: str) -> str:
            if "researcher" in system_prompt.lower():
                return f"[RESEARCH] Gathered details on: {last_user_msg}"
            elif "summarizer" in system_prompt.lower():
                return f"[SUMMARY] Distilled key points for: {last_user_msg}"
            return "Default generic fallback response"
    ```
    """

    model_type: ClassVar[str] = "api"
    provider: ClassVar[str] = "mock"

    def __init__(
        self,
        model: str = "mock-gpt",
        model_params: dict[str, Any] | None = None,
        *,
        mock_responses: dict[str, Any] | None = None,
        sequential_responses: list[Any] | None = None,
        response_callback: Callable[[ConversationHistory, str], Any] | None = None,
        default_response: str = "Unprocessed generic mock response",
    ) -> None:
        super().__init__(model=model, model_params=model_params or {})
        self.mock_responses: dict[str, Any] = mock_responses or {}
        self.sequential_responses: list[Any] = sequential_responses or []
        self.response_callback: Callable[[ConversationHistory, str], Any] | None = response_callback
        self.default_response: str = default_response
        self._current_seq_idx: int = 0

    def mock_call(self, last_user_msg: str, system_prompt: str) -> Any:
        """
        High-level overridable method for subclassing.

        Override this method in a subclass to return custom mock responses based on the last user message
        and active system prompt, without having to extract history or deal with JSON action serialization.

        Args:
            last_user_msg (str): The last user message in the conversation.
            system_prompt (str): The active system prompt compiled for the agent.

        Returns:
            Any: A string, dict, or JSON-conforming response.
        """
        # 1. Check Dictionary Mapping
        if self.mock_responses:
            # First match system prompt keywords
            for key, val in self.mock_responses.items():
                if key.lower() in system_prompt.lower():
                    if isinstance(val, dict):
                        # Nested dictionary for conditional matching based on user query
                        matched_val = None
                        for subkey, subval in val.items():
                            if subkey != "*" and subkey.lower() in last_user_msg.lower():
                                matched_val = subval
                                break
                        if matched_val is None and "*" in val:
                            matched_val = val["*"]
                        return matched_val
                    return val

            # If not matched, try matching last user message keywords
            for key, val in self.mock_responses.items():
                if key.lower() in last_user_msg.lower():
                    return val

        # 2. Fallback to default
        return self.default_response

    def call(self, history: ConversationHistory) -> str:
        # Extract the last user message
        last_user_msg = ""
        for m in reversed(history.messages):
            if m.get("role") == "user":
                last_user_msg = str(m.get("content", ""))
                break

        system_prompt = self.system_prompt or ""

        # Determine the response source
        response_val = None

        # 1. Check Callback
        if self.response_callback:
            try:
                response_val = self.response_callback(history, system_prompt)
            except Exception as e:
                response_val = f"[MOCK ERROR] Callback raised exception: {e}"

        # 2. Check Sequential Responses
        if response_val is None and self.sequential_responses:
            if self._current_seq_idx < len(self.sequential_responses):
                response_val = self.sequential_responses[self._current_seq_idx]
                self._current_seq_idx += 1
            else:
                response_val = self.sequential_responses[-1]  # Repeat the last one

        # 3. Check overridable mock_call (which also handles self.mock_responses and default)
        if response_val is None:
            response_val = self.mock_call(last_user_msg, system_prompt)

        # Format output into JSON Action Protocol if it's not already a valid JSON Action dict/string
        if isinstance(response_val, dict):
            # If it's a dict, check if it fits the action protocol
            if "type" in response_val:
                return json.dumps(response_val)
            # Otherwise, treat it as a final content dict
            return json.dumps({"type": "final", "content": json.dumps(response_val)})

        # If it's a string, see if it is a JSON string already
        if isinstance(response_val, str):
            try:
                parsed = json.loads(response_val)
                if isinstance(parsed, dict) and "type" in parsed:
                    return response_val
            except json.JSONDecodeError:
                pass

            # Wrap standard raw text in the action protocol
            return json.dumps({"type": "final", "content": response_val})

        return json.dumps({"type": "final", "content": str(response_val)})

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True
