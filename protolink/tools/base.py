from collections.abc import Collection
from typing import Any, Protocol


class BaseTool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: Any | None
    tags: list[str] | None
    examples: list[Any] | None
    capabilities: Collection[str] | None

    async def __call__(self, **kwargs) -> Any: ...
