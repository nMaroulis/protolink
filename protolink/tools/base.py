from typing import Any, Protocol


class BaseTool(Protocol):
    name: str
    description: str
    input_schema: dict[str, type] | None
    output_schema: dict[str, type] | None
    tags: list[str] | None

    async def __call__(self, **kwargs) -> Any: ...
