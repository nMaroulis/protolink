from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from protolink.llms._deps import require_openai
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.types import LLMProvider
from protolink.utils.id_generator import IDGenerator
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OpenAILLM(APILLM):
    """OpenAI API implementation of the LLM API interface."""

    provider: ClassVar[LLMProvider] = "openai"
    DEFAULT_MODEL: ClassVar[str] = "gpt-4o-mini"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,  # Sampling randomness (0-2)
        "top_p": 1.0,  # Nucleus sampling
        "top_logprobs": None,  # Number of logprobs to return (optional)
        "truncation": "disabled",  # How to handle inputs exceeding model context; "disabled" or "auto"
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {
            **self.DEFAULT_MODEL_PARAMS,
            **(model_params or {}),
        }
        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=base_url,
        )

        # Set OpenAI API Client
        openai, _, _ = require_openai()
        self._client = openai.OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url,
        )
        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response from the model."""

        response = self._client.responses.create(model=self.model, input=history.messages, **self._model_params)
        return self._parse_output(response)

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response using OpenAI Responses API."""

        stream = self._client.responses.create(
            model=self.model,
            input=history.messages,
            stream=True,
            **self._model_params,
        )

        for event in stream:
            # We only care about output text deltas
            if event.type != "response.output_text.delta":
                continue

            # event.delta is a string chunk - yield only the new chunk
            yield event.delta

    # ----------------------------------------------------------------------
    # Agent-LLM Interface - A2A Operations
    # ----------------------------------------------------------------------

    def _inject_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], tool_result: Any):
        """
        Inject a completed tool invocation into the conversation history using OpenAI's Responses API tool-calling
        protocol.

        This implementation adapts a completed tool execution into the exact message sequence required by the OpenAI
        Responses API, which differs from the legacy Chat Completions interface.

        The Responses API represents tool usage as a correlated pair of messages:

        1. An ``assistant`` message declaring the tool invocation via a ``tool_calls`` field, including:
        - A generated ``tool_call_id`` used to correlate the call and its result
        - The tool (function) name
        - The serialized tool arguments

        2. A subsequent ``user`` message containing a ``tool_result`` content block, which supplies:
        - The same ``tool_call_id`` to associate the result with the originating assistant tool call
        - The serialized tool execution result

        The Responses API explicitly forbids a dedicated ``tool`` role. Tool outputs must instead be provided as
        structured content blocks within a ``user`` message. Failure to follow this schema results in request
        validation errors.

        This method encapsulates all OpenAI-specific protocol requirements, including role constraints and tool-call
        correlation identifiers, allowing the base ``LLM`` inference loop to remain provider-agnostic and free of
        API-specific branching.

        Official documentation:
            - OpenAI Responses API - Tool calling
            https://platform.openai.com/docs/guides/tools
            - OpenAI Responses API - Message schema
            https://platform.openai.com/docs/api-reference/responses

        Args:
            tool_name (str):
                The registered name of the tool invoked by the model.

            tool_args (dict[str, Any]):
                The arguments supplied by the model for the tool invocation.
                These are serialized and embedded in the assistant's ``tool_calls`` declaration.

            tool_result (Any):
                The result returned by the executed tool. The value must be JSON-serializable, as it is injected into
                a ``tool_result`` content block within a ``user`` message.

        Returns:
            None

        Notes:
            - A unique ``tool_call_id`` is generated per invocation to satisfy the Responses API's strict tool-call
            correlation requirements.
            - Tool execution and side effects are performed exclusively by the runtime; this method is responsible only
            for adapting completed tool results into the provider-specific conversation format.
            - This implementation is intentionally incompatible with the legacy Chat Completions API, which uses a
            different role model and message schema.
        """
        tool_call_id = IDGenerator.generate_openai_tool_call_id()

        # Assistant declares the tool call
        self.history.add_raw(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args),
                        },
                    }
                ],
            }
        )

        # User provides the tool result (Responses API requirement)
        self.history.add_raw(
            {
                "role": "user",
                "content": f"""[
                    {{
                        "type": "tool_result",
                        "tool_call_id": {tool_call_id},
                        "content": {tool_result},
                    }}
                ]""",
            }
        )

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def _parse_output(self, response: Any) -> str:
        """Convert OpenAI completion to internal Message format."""

        output_text: str = ""
        for item in response.output or []:
            # item: ResponseOutputMessage
            if item.type != "message":
                continue
            if item.role != "assistant":
                continue

            for content in item.content:
                # content: ResponseOutputText (or other types later)
                if content.type == "output_text":
                    output_text += content.text

        return output_text

    def validate_connection(self) -> bool:
        try:
            # Check that the configured model is available / accessible
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"OpenAI connection validation failed for model {self.model}: {e}")
            return False
