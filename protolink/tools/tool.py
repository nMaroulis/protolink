from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from protolink.tools.base import BaseTool


@dataclass
class Tool(BaseTool):
    name: str
    description: str
    func: Callable[..., Any]
    args: dict[str, Any] | None = None

    async def __call__(self, **kwargs):
        # call the underlying function
        return await self.func(**kwargs)
