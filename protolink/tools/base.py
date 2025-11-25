from typing import Any, Protocol


class BaseTool(Protocol):
    name: str
    description: str

    async def __call__(self, **kwargs) -> Any: ...
