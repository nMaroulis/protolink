from typing import Any, ClassVar

from protolink.llms.base import LLM, ToolCallingMode
from protolink.types import LLMType


class APILLM(LLM):
    """Base class for API-based LLM implementations."""

    model_type: ClassVar[LLMType] = "api"

    def __init__(
        self,
        *,
        model: str,
        model_params: dict[str, Any],
        base_url: str | None = None,
        tool_calling: ToolCallingMode | None = None,
    ) -> None:
        """Create the adapter with an optional runtime tool-calling policy.

        ``tool_calling`` accepts ``auto``, ``native`` or ``json``. Omit it
        to preserve the adapter default; the option is never forwarded as
        a provider generation setting. See ``LLM.resolve_tool_calling``.
        """
        self.base_url = base_url
        super().__init__(
            model=model,
            model_params=model_params,
            tool_calling=tool_calling,
        )

    def validate_connection(self) -> bool:
        """Validate API connection - to be implemented by subclasses."""
        raise NotImplementedError
