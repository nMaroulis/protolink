from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from protolink.tools.base import BaseTool


@dataclass
class Tool(BaseTool):
    """Native Protolink Tool implementation."""

    name: str
    description: str
    tags: list[str] | None

    func: Callable[..., Any]
    args: dict[str, Any] | None = None

    async def __call__(self, **kwargs):
        # call the underlying function
        return await self.func(**kwargs)
