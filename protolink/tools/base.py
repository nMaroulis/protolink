from typing import Any, Protocol


class BaseTool(Protocol):
    name: str
    description: str
    tags: list[str] | None

    async def __call__(self, **kwargs) -> Any: ...
