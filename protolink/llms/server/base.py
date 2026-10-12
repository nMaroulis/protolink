from typing import Any, ClassVar

from protolink.llms.base import LLM, LLMType, ToolCallingMode


class ServerLLM(LLM):
    """
    Base class for server-backed LLM implementations.

    This class represents language models that are accessed via an HTTP-based inference server (local or remote), rather
    than through a provider-specific Python SDK (e.g. OpenAI or Anthropic clients).

    Typical examples include self-hosted or managed inference servers such as:
    - Ollama
    - vLLM
    - Text Generation Inference (TGI)
    - Custom FastAPI / HTTP model servers

    The class stores common configuration required to communicate with such servers (e.g. base URL, model identifier,
    and model parameters), while delegating all request/response logic to concrete subclasses.

    ``tool_calling`` selects automatic capability discovery, native tools or JSON actions through the shared engine.
    The legacy ``supports_tool_calling`` flag retains its behavior when the new policy is omitted. Subclasses supply
    metadata through ``discover_tool_calling`` where their server has a reliable capability contract. Native support
    and model reliability depend on the exact model, chat template and server configuration, not a family-name list.

    This design keeps the core inference loop in ``LLM`` provider-agnostic, while allowing server-specific subclasses
    to:
    - Define their own request payload schema
    - Handle streaming or non-streaming responses
    - Implement custom tool-calling behavior when supported by the backend

    Args:
        base_url (str):
            Base URL of the inference server (e.g. ``http://localhost:11434``).

        model (str):
            Model identifier understood by the server (e.g. ``llama3.1``).

        model_params (dict[str, Any] | None):
            Optional dictionary of model-specific parameters (e.g. temperature, max tokens). These are merged and passed
            to the underlying server request as-is.

        supports_tool_calling (bool):
            Whether this server/model combination supports tool calling.
            Defaults to ``False`` and must be explicitly enabled by subclasses that implement tool-calling semantics.
        tool_calling (ToolCallingMode | None):
            ``auto``, ``native`` or ``json``; overrides the legacy flag when supplied.

    Notes:
        - This class does not assume any particular server API shape.
        - Subclasses must implement the actual inference logic.
        - Declaring tool support does not guarantee correct
    """

    model_type: ClassVar[LLMType] = "server"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        model_params: dict[str, Any] | None = None,
        supports_tool_calling: bool = False,
        tool_calling: ToolCallingMode | None = None,
    ) -> None:
        """Create the adapter with an optional runtime tool-calling policy.

        ``tool_calling`` accepts ``auto``, ``native`` or ``json``. Omit it
        to preserve the adapter default; the option is never forwarded as
        a provider generation setting. See ``LLM.resolve_tool_calling``.
        """
        self.base_url = base_url
        merged_params = model_params or {}
        super().__init__(model=model, model_params=merged_params, tool_calling=tool_calling)
        self._supports_tool_calling = supports_tool_calling

    def validate_connection(self) -> bool:
        """Validate LLM Server connection - to be implemented by subclasses."""
        raise NotImplementedError

    # ----------------------------------------------------------------------
    # Properties
    # ----------------------------------------------------------------------

    @property
    def supports_tool_calling(self) -> bool:
        """Return whether this LLM supports tool calling."""
        return self.resolve_tool_calling() == "native"

    @supports_tool_calling.setter
    def supports_tool_calling(self, value: bool) -> None:
        """Set whether this LLM supports tool calling."""
        self._supports_tool_calling = value
