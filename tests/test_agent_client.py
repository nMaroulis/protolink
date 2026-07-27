"""Tests for AgentClient convenience methods."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from protolink.client import AgentClient
from protolink.core.task import Task
from protolink.transport import Transport


class _StubTransport(Transport):
    """Minimal transport used to construct an AgentClient."""

    @property
    def url(self) -> str:
        return "stub://client"

    async def send(self, request_spec: Any, base_url: str, data: Any = None, params: dict | None = None) -> Any:
        raise AssertionError("send_infer_task should delegate through AgentClient.send_task")

    def setup_routes(self, endpoints: list) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def validate_url(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_send_infer_task_creates_task_and_calls_send_task() -> None:
    client = AgentClient(_StubTransport())
    result = Task()
    client.send_task = AsyncMock(return_value=result)

    returned = await client.send_infer_task(
        "Summarize this report",
        "stub://agent",
        user="reader-42",
        output_schema={"type": "string"},
        metadata={"source": "report"},
        protocol="protolink",
    )

    assert returned is result
    client.send_task.assert_awaited_once()
    args, kwargs = client.send_task.await_args
    assert args[0] == "stub://agent"
    assert kwargs == {"protocol": "protolink"}

    task = args[1]
    assert isinstance(task, Task)
    assert len(task.messages) == 1
    assert task.messages[0].role == "user"
    assert len(task.messages[0].parts) == 1
    assert task.messages[0].parts[0].type == "infer"
    assert task.messages[0].parts[0].content == {
        "prompt": "Summarize this report",
        "user": "reader-42",
        "output_schema": {"type": "string"},
        "metadata": {"source": "report"},
    }


def test_sync_send_infer_task_uses_required_arguments() -> None:
    client = AgentClient(_StubTransport())
    result = Task()
    client.send_task = AsyncMock(return_value=result)

    returned = client.sync.send_infer_task("Explain ProtoLink", "stub://agent")

    assert returned is result
    client.send_task.assert_awaited_once()
    args, kwargs = client.send_task.await_args
    assert args[0] == "stub://agent"
    assert args[1].messages[0].parts[0].content == {"prompt": "Explain ProtoLink"}
    assert kwargs == {"protocol": "auto"}
