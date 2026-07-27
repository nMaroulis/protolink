from dataclasses import asdict, dataclass, field
from typing import Any

from protolink.types import PartType
from protolink.utils.id_generator import IDGenerator


@dataclass
class ToolCall:
    """
    Standardized tool/capability invocation.

    This mirrors A2A semantics where an agent requests another agent to execute a specific capability.

    Attributes:
        tool_name: Canonical name of the tool or capability to invoke.
                   Example: "weather.get_temperature"
        args: Arguments passed to the tool.
        call_id: Optional correlation ID used to match tool_call with the corresponding tool_output.
    """

    tool_name: str
    args: dict[str, Any]
    call_id: str = field(default_factory=lambda: IDGenerator.generate_tool_call_id())


@dataclass
class ToolOutput:
    """
    Output result of a previously issued tool_call.

    Attributes:
        call_id: Correlation ID matching the originating tool_call.
        result: Successful result payload (if any).
        error: Error payload if the tool execution failed.
    """

    call_id: str = field(default_factory=lambda: IDGenerator.generate_tool_output_id())
    result: Any | None = None
    error: dict | None = None


@dataclass
class RouteDecision:
    """
    Structured flow routing decision.

    Attributes:
        route_key: Key in the receiving Router's route map.
        reason: Optional human-readable reason for the decision.
        confidence: Optional confidence score from 0.0 to 1.0.
        metadata: Additional serializable decision context.
    """

    route_key: str
    reason: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Part:
    """Atomic content unit within a message.

    Attributes:
        type: Content type (e.g., 'text', 'image', 'file')
        content: The actual content data
    """

    type: PartType
    content: Any

    @staticmethod
    def _hydrate_content(part_type: PartType, content: Any) -> Any:
        if content is None:
            return content

        if part_type == "tool_call":
            if isinstance(content, ToolCall):
                return content
            if isinstance(content, dict):
                return ToolCall(
                    tool_name=content["tool_name"],
                    args=content.get("args", {}),
                    call_id=content.get("call_id", IDGenerator.generate_tool_call_id()),
                )

        if part_type == "tool_output":
            if isinstance(content, ToolOutput):
                return content
            if isinstance(content, dict):
                return ToolOutput(
                    call_id=content.get("call_id", IDGenerator.generate_tool_output_id()),
                    result=content.get("result"),
                    error=content.get("error"),
                )

        if part_type in {"route", "decision"}:
            if isinstance(content, RouteDecision):
                return content
            if isinstance(content, dict):
                route_key = content.get("route_key", content.get("route", content.get("key")))
                if route_key is None:
                    raise ValueError("route decision content must include 'route_key'")
                return RouteDecision(
                    route_key=str(route_key),
                    reason=content.get("reason"),
                    confidence=content.get("confidence"),
                    metadata=content.get("metadata") or {},
                )

        return content

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        content = asdict(self.content) if hasattr(self.content, "__dataclass_fields__") else self.content
        return {
            "type": self.type,
            "content": content,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Part":
        """Create from dictionary."""
        part_type = data["type"]
        content = cls._hydrate_content(part_type, data.get("content"))
        return cls(type=part_type, content=content)

    def as_tool_call(self) -> ToolCall:
        if self.type != "tool_call":
            raise ValueError(f"Expected part type 'tool_call', got '{self.type}'")
        if isinstance(self.content, ToolCall):
            return self.content
        if isinstance(self.content, dict):
            return self._hydrate_content("tool_call", self.content)
        raise TypeError(f"Unexpected tool_call content type: {type(self.content)}")

    def as_tool_output(self) -> ToolOutput:
        if self.type != "tool_output":
            raise ValueError(f"Expected part type 'tool_output', got '{self.type}'")
        if isinstance(self.content, ToolOutput):
            return self.content
        if isinstance(self.content, dict):
            return self._hydrate_content("tool_output", self.content)
        raise TypeError(f"Unexpected tool_output content type: {type(self.content)}")

    def as_route_decision(self) -> RouteDecision:
        if self.type not in {"route", "decision"}:
            raise ValueError(f"Expected part type 'route' or 'decision', got '{self.type}'")
        if isinstance(self.content, RouteDecision):
            return self.content
        if isinstance(self.content, dict):
            return self._hydrate_content(self.type, self.content)
        raise TypeError(f"Unexpected route decision content type: {type(self.content)}")

    @classmethod
    def text(cls, content: str) -> "Part":
        """Create a text part (convenience method)."""
        return cls(type="text", content=content)

    @classmethod
    def json(cls, content: dict) -> "Part":
        return cls(type="json", content=content)

    @classmethod
    def error(cls, code: str, message: str, *, retryable: bool = False) -> "Part":
        return cls(
            type="error",
            content={
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        )

    @classmethod
    def status(cls, state: str, message: str | None = None) -> "Part":
        return cls(
            type="status",
            content={"state": state, "message": message},
        )

    @classmethod
    def route(
        cls,
        route_key: str,
        *,
        reason: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Part":
        """Create a structured route decision part."""
        return cls(
            type="route",
            content=RouteDecision(
                route_key=route_key,
                reason=reason,
                confidence=confidence,
                metadata=metadata or {},
            ),
        )

    @classmethod
    def decision(
        cls,
        route_key: str,
        *,
        reason: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Part":
        """Create a structured decision part suitable for Router branching."""
        return cls(
            type="decision",
            content=RouteDecision(
                route_key=route_key,
                reason=reason,
                confidence=confidence,
                metadata=metadata or {},
            ),
        )

    # ------------------------------------------------------------------
    # Tool interaction
    # ------------------------------------------------------------------

    @classmethod
    def tool_call(
        cls,
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> "Part":
        """
        Create a tool invocation part.

        In A2A terms, this represents a request to execute a specific agent capability (tool) along with its arguments.

        This part is sent inside a Message and is interpreted by the receiving agent, which routes the call to the
        appropriate internal handler.

        Args:
            tool_name: Canonical name of the tool or capability to invoke.
            args: Arguments for the tool.
            call_id: Optional correlation ID to match with tool_output.

        Returns:
            Part: A Part of type "tool_call".
        """
        tool_call = ToolCall(
            tool_name=tool_name,
            args=args or {},
        )
        if call_id is not None:
            tool_call.call_id = call_id

        return cls(
            type="tool_call",
            content=tool_call,
        )

    @classmethod
    def tool_output(
        cls,
        *,
        call_id: str | None = None,
        result: Any | None = None,
        error: dict | None = None,
    ) -> "Part":
        """
        Create a tool result part.

        This part is used to return the outcome of a previously issued tool_call. It completes the tool invocation
        lifecycle.

        In A2A, this corresponds to emitting the execution result of a capability back to the requesting agent.

        Args:
            call_id: Correlation ID matching the original tool_call.
            result: Successful result payload.
            error: Error information if the tool execution failed.

        Returns:
            Part: A Part of type "tool_output".
        """
        tool_output = ToolOutput(result=result, error=error)
        if call_id is not None:
            tool_output.call_id = call_id

        return cls(
            type="tool_output",
            content=tool_output,
        )

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    @classmethod
    def infer(
        cls,
        *,
        prompt: str | None = None,
        user: str | None = None,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Part":
        """
        Create a infer part.

        This part is used to instruct the agent to invoke its LLM.

        Args:
            prompt: The prompt to send to the LLM.
            user: The user to send to the LLM.
            output_schema: The output schema to use for the LLM.
            metadata: Additional metadata to include with the infer.

        Returns:
            Part: A Part of type "infer".
        """
        content = {
            "prompt": prompt,
            "user": user,
            "output_schema": output_schema,
            "metadata": metadata,
        }

        # Remove None values
        content = {k: v for k, v in content.items() if v is not None}

        return cls(
            type="infer",
            content=content,
        )

    @classmethod
    def infer_output(cls, *, content: str | dict[str, Any]) -> "Part":
        """
        Create an infer_output part.

        The content contains the output from an LLM inference operation.

        Args:
            content: The output content, either as a string or dict.

        Returns:
            Part: A Part of type "infer_output".
        """

        return cls(
            type="infer_output",
            content=content,
        )
