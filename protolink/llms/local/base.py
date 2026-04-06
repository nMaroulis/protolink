from typing import Any, ClassVar

from protolink.llms.base import LLM, LLMType


class LocalLLM(LLM):
    """
    Base class for local-backed LLM implementations.

    This class represents language models that are executed entirely within the local Python process, running directly
    on the host machine's hardware using local bindings instead of communicating over a network.

    Typical examples include python bindings such as:
    - llama-cpp-python
    - MLX
    - Transformers pipelines

    The class stores common configuration required to load and serve local formats (such as .gguf paths).
    """

    model_type: ClassVar[LLMType] = "local"

    def __init__(
        self,
        *,
        model: str,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        merged_params = model_params or {}
        super().__init__(model=model, model_params=merged_params)

    def validate_connection(self) -> bool:
        """Validate Local LLM file path and loading availability."""
        raise NotImplementedError
