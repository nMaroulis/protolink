"""Bounded retention tests for the inbound A2A 1.0 task index."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from protolink.a2a.v1 import A2A_PROTOCOL_VERSION, A2AJSONRPCAdapter
from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.server.endpoint_handler import EndpointRequest


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _RetentionAgent:
    def __init__(self) -> None:
        self.card = AgentCard(
            name="retention-agent",
            description="Deterministic A2A retention test agent",
            url="http://agent.test",
        )
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_task(self, task: Task) -> Task:
        message_id = task.messages[-1].id
        if message_id.startswith("block"):
            self.started.set()
            await self.release.wait()
            return task.complete("released")
        if message_id.startswith("wait"):
            return task.require_input(Message.agent("more input required"))
        return task.complete("done")

    async def cancel_task(self, request: Any) -> Any:
        return request


def _message(message_id: str, *, task_id: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {
        "messageId": message_id,
        "role": "ROLE_USER",
        "parts": [{"text": message_id}],
    }
    if task_id is not None:
        message["taskId"] = task_id
    return message


def _request(method: str, params: dict[str, Any], *, request_id: int = 1) -> EndpointRequest:
    return EndpointRequest(
        body={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        },
        headers={
            "A2A-Version": A2A_PROTOCOL_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
        url="http://agent.test/",
    )


async def _send(
    adapter: A2AJSONRPCAdapter,
    message_id: str,
    *,
    task_id: str | None = None,
    return_immediately: bool = False,
) -> dict[str, Any]:
    configuration = {"returnImmediately": True} if return_immediately else {}
    return await adapter.handle(
        _request(
            "SendMessage",
            {
                "message": _message(message_id, task_id=task_id),
                "configuration": configuration,
            },
        )
    )


@pytest.mark.asyncio
async def test_size_limit_evicts_the_oldest_inactive_task() -> None:
    clock = _Clock()
    adapter = A2AJSONRPCAdapter(_RetentionAgent(), _max_tasks=2, _clock=clock)

    first = await _send(adapter, "complete-1")
    first_id = first["result"]["task"]["id"]
    clock.advance(1)
    second = await _send(adapter, "complete-2")
    second_id = second["result"]["task"]["id"]
    clock.advance(1)
    third = await _send(adapter, "complete-3")
    third_id = third["result"]["task"]["id"]

    missing = await adapter.handle(_request("GetTask", {"id": first_id}))
    assert missing["error"]["code"] == -32001

    listed = await adapter.handle(_request("ListTasks", {}))
    assert listed["result"]["totalSize"] == 2
    assert {task["id"] for task in listed["result"]["tasks"]} == {second_id, third_id}


@pytest.mark.asyncio
async def test_ttl_prunes_on_read_and_reads_do_not_refresh_retention() -> None:
    clock = _Clock()
    adapter = A2AJSONRPCAdapter(_RetentionAgent(), _task_ttl=10, _clock=clock)

    sent = await _send(adapter, "wait-ttl")
    task_id = sent["result"]["task"]["id"]
    clock.advance(9)

    visible = await adapter.handle(_request("GetTask", {"id": task_id}))
    assert visible["result"]["id"] == task_id

    clock.advance(1)
    expired = await adapter.handle(_request("GetTask", {"id": task_id}))
    assert expired["error"]["code"] == -32001


@pytest.mark.asyncio
async def test_continuation_refreshes_retention_order() -> None:
    clock = _Clock()
    adapter = A2AJSONRPCAdapter(_RetentionAgent(), _max_tasks=2, _clock=clock)

    first = await _send(adapter, "wait-first")
    first_id = first["result"]["task"]["id"]
    clock.advance(1)
    second = await _send(adapter, "wait-second")
    second_id = second["result"]["task"]["id"]
    clock.advance(1)

    continued = await _send(adapter, "wait-first-follow-up", task_id=first_id)
    assert continued["result"]["task"]["id"] == first_id
    clock.advance(1)
    await _send(adapter, "wait-third")

    retained = await adapter.handle(_request("GetTask", {"id": first_id}))
    evicted = await adapter.handle(_request("GetTask", {"id": second_id}))
    assert retained["result"]["id"] == first_id
    assert evicted["error"]["code"] == -32001


@pytest.mark.asyncio
async def test_completion_refreshes_retention_order() -> None:
    clock = _Clock()
    agent = _RetentionAgent()
    adapter = A2AJSONRPCAdapter(agent, _max_tasks=2, _clock=clock)

    pending = asyncio.create_task(_send(adapter, "block-completion"))
    await asyncio.wait_for(agent.started.wait(), timeout=1)
    blocking_id = next(iter(adapter._tasks))
    clock.advance(1)
    waiting = await _send(adapter, "wait-older")
    waiting_id = waiting["result"]["task"]["id"]
    clock.advance(1)

    agent.release.set()
    completed = await asyncio.wait_for(pending, timeout=1)
    assert completed["result"]["task"]["id"] == blocking_id
    clock.advance(1)
    await _send(adapter, "wait-new")

    retained = await adapter.handle(_request("GetTask", {"id": blocking_id}))
    evicted = await adapter.handle(_request("GetTask", {"id": waiting_id}))
    assert retained["result"]["id"] == blocking_id
    assert evicted["error"]["code"] == -32001


@pytest.mark.asyncio
async def test_cancel_refreshes_retention_order() -> None:
    clock = _Clock()
    adapter = A2AJSONRPCAdapter(_RetentionAgent(), _max_tasks=2, _clock=clock)

    first = await _send(adapter, "wait-cancel")
    first_id = first["result"]["task"]["id"]
    clock.advance(1)
    second = await _send(adapter, "wait-older")
    second_id = second["result"]["task"]["id"]
    clock.advance(1)

    canceled = await adapter.handle(_request("CancelTask", {"id": first_id}))
    assert canceled["result"]["status"]["state"] == "TASK_STATE_CANCELED"
    clock.advance(1)
    await _send(adapter, "wait-new")

    retained = await adapter.handle(_request("GetTask", {"id": first_id}))
    evicted = await adapter.handle(_request("GetTask", {"id": second_id}))
    assert retained["result"]["id"] == first_id
    assert evicted["error"]["code"] == -32001


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_mode", ["blocking", "background"])
async def test_all_active_capacity_returns_protocol_error(execution_mode: str) -> None:
    agent = _RetentionAgent()
    adapter = A2AJSONRPCAdapter(agent, _max_tasks=1)

    if execution_mode == "background":
        first = await _send(adapter, "block-active", return_immediately=True)
        task_id = first["result"]["task"]["id"]
        await asyncio.wait_for(agent.started.wait(), timeout=1)
        execution = adapter._executions[task_id]
    else:
        pending = asyncio.create_task(_send(adapter, "block-active"))
        await asyncio.wait_for(agent.started.wait(), timeout=1)
        task_id = next(iter(adapter._tasks))
        execution = pending

    rejected = await _send(adapter, "wait-rejected")
    assert rejected["error"] == {
        "code": -32603,
        "message": "A2A task capacity is exhausted; retry later",
    }
    assert task_id in adapter._tasks

    agent.release.set()
    await asyncio.wait_for(execution, timeout=1)


@pytest.mark.asyncio
async def test_blocking_execution_rejects_concurrent_continuation() -> None:
    agent = _RetentionAgent()
    adapter = A2AJSONRPCAdapter(agent)

    pending = asyncio.create_task(_send(adapter, "block-active"))
    await asyncio.wait_for(agent.started.wait(), timeout=1)
    task_id = next(iter(adapter._tasks))

    rejected = await _send(adapter, "wait-concurrent", task_id=task_id)
    assert rejected["error"]["code"] == -32004
    assert "already being processed" in rejected["error"]["message"]

    agent.release.set()
    completed = await asyncio.wait_for(pending, timeout=1)
    assert completed["result"]["task"]["id"] == task_id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"_max_tasks": 0},
        {"_task_ttl": 0},
    ],
)
def test_retention_settings_must_be_positive(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="must be greater than zero"):
        A2AJSONRPCAdapter(_RetentionAgent(), **kwargs)
