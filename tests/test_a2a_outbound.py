"""Outbound A2A 1.0 discovery, translation, and protocol selection tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar

import pytest

from protolink.a2a.v1 import A2A_PROTOCOL_VERSION, A2AClientError, A2AJSONRPCClientAdapter
from protolink.client import AgentClient
from protolink.client.request_spec import ClientRequestSpec
from protolink.core.agent_card import AgentCard
from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.core.task import Task, TaskState
from protolink.transport.base import Transport
from protolink.transport.config import TransportCapabilities
from protolink.transport.errors import TransportRemoteError


class _FakeHTTPTransport(Transport):
    transport_type: ClassVar[str] = "http"
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(networked=True)

    def __init__(self, handler: Callable[[ClientRequestSpec, str, Any], Any]) -> None:
        super().__init__()
        self._handler = handler

    async def send(
        self,
        request_spec: ClientRequestSpec,
        base_url: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        del params
        result = self._handler(request_spec, base_url, data)
        if isinstance(result, BaseException):
            raise result
        return result

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        del agent_url, task
        if False:  # pragma: no cover
            yield None

    def setup_routes(self, endpoints: list[Any]) -> None:
        del endpoints

    async def start(self) -> None:
        self._transport_running = True

    async def stop(self) -> None:
        self._transport_running = False

    def validate_url(self) -> bool:
        return True

    @property
    def url(self) -> str:
        return "http://caller.test"


def _a2a_card(interface_url: str = "https://remote.test/rpc/a2a") -> dict[str, Any]:
    return {
        "name": "remote",
        "description": "A2A-only test agent",
        "version": "1.2.3",
        "supportedInterfaces": [
            {
                "url": interface_url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [],
    }


def _wire_task(
    request_message: dict[str, Any],
    *,
    state: str = "TASK_STATE_COMPLETED",
    task_id: str = "remote-task-1",
    context_id: str = "remote-context-1",
) -> dict[str, Any]:
    agent_message = {
        "messageId": "remote-message-1",
        "role": "ROLE_AGENT",
        "parts": [{"text": "remote answer"}],
        "taskId": task_id,
        "contextId": context_id,
    }
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": state,
            "timestamp": "2026-07-14T10:00:00Z",
            "message": agent_message,
        },
        "history": [request_message, agent_message],
    }


@pytest.mark.asyncio
async def test_auto_discovers_a2a_only_peer_and_translates_infer_text() -> None:
    calls: list[tuple[ClientRequestSpec, str, Any]] = []

    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        calls.append((spec, base_url, data))
        if spec.name == "get_agent_card":
            return TransportRemoteError("missing", status_code=404)
        if spec.name == "get_a2a_agent_card":
            return _a2a_card("https://remote.test/rpc/a2a/")
        assert spec.name == "a2a_jsonrpc"
        request_message = data["params"]["message"]
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {"task": _wire_task(request_message)},
        }

    task = Task.create_infer(prompt="Explain the mesh")
    result = await AgentClient(_FakeHTTPTransport(handler), a2a=True).send_task(
        "https://remote.test",
        task,
    )

    jsonrpc_spec, interface_url, payload = calls[-1]
    assert interface_url == "https://remote.test/rpc/a2a/"
    assert jsonrpc_spec.headers == {"A2A-Version": A2A_PROTOCOL_VERSION}
    assert jsonrpc_spec.content_type == "application/json"
    assert jsonrpc_spec.accept == "application/json"
    assert jsonrpc_spec.idempotent is False
    assert payload["method"] == "SendMessage"
    assert payload["params"]["message"]["role"] == "ROLE_USER"
    assert payload["params"]["message"]["parts"] == [{"text": "Explain the mesh"}]
    assert "taskId" not in payload["params"]["message"]
    assert result.id == task.id
    assert result.state is TaskState.COMPLETED
    assert result.metadata["a2a_remote_task_id"] == "remote-task-1"
    assert result.metadata["a2a_remote_context_id"] == "remote-context-1"
    assert result.get_last_part_content() == "remote answer"
    assert task.state is TaskState.SUBMITTED
    assert "a2a_remote_task_id" not in task.metadata


@pytest.mark.asyncio
async def test_auto_prefers_native_protolink_peer_without_a2a_translation() -> None:
    calls: list[str] = []

    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        calls.append(spec.name)
        if spec.name == "get_agent_card":
            return AgentCard(name="native", description="native", url="http://native.test")
        if spec.name == "send_task":
            return Task.from_dict(data.to_dict()).complete("native answer")
        raise AssertionError(f"unexpected request: {spec.name}")

    client = AgentClient(_FakeHTTPTransport(handler), a2a=True)
    result = await client.send_task("http://native.test", Task.create_infer(prompt="hello"))

    assert calls == ["get_agent_card", "send_task"]
    assert result.get_last_part_content() == "native answer"
    assert "a2a_remote_task_id" not in result.metadata


@pytest.mark.asyncio
async def test_explicit_a2a_continuation_uses_remote_ids_and_can_cancel() -> None:
    send_count = 0
    sent_messages: list[dict[str, Any]] = []

    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        nonlocal send_count
        del base_url
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        if data["method"] == "CancelTask":
            assert data["params"] == {
                "id": "remote-task-1",
                "metadata": {"source": "test", "reason": "no longer needed"},
            }
            request_message = sent_messages[0]
            return {
                "jsonrpc": "2.0",
                "id": data["id"],
                "result": _wire_task(request_message, state="TASK_STATE_CANCELED"),
            }
        send_count += 1
        message = data["params"]["message"]
        sent_messages.append(message)
        state = "TASK_STATE_INPUT_REQUIRED" if send_count == 1 else "TASK_STATE_COMPLETED"
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {"task": _wire_task(message, state=state)},
        }

    client = AgentClient(_FakeHTTPTransport(handler), a2a=True)
    waiting = await client.send_task(
        "https://remote.test",
        Task.create_infer(prompt="start"),
        protocol="a2a",
    )
    assert waiting.state is TaskState.INPUT_REQUIRED

    waiting.add_message(Message.user("continue"))
    completed = await client.send_task("https://remote.test", waiting, protocol="a2a")
    assert sent_messages[1]["taskId"] == "remote-task-1"
    assert sent_messages[1]["contextId"] == "remote-context-1"
    assert completed.state is TaskState.COMPLETED

    canceled = await client.cancel_task(
        "https://remote.test",
        waiting.id,
        reason="no longer needed",
        metadata={"source": "test"},
    )
    assert canceled.id == waiting.id
    assert canceled.state is TaskState.CANCELED


@pytest.mark.asyncio
async def test_direct_message_result_completes_the_local_task() -> None:
    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {
                "message": {
                    "messageId": "direct-1",
                    "role": "ROLE_AGENT",
                    "parts": [{"text": "direct answer"}],
                    "contextId": "context-direct",
                }
            },
        }

    task = Task.create_infer(prompt="hello")
    result = await AgentClient(_FakeHTTPTransport(handler), a2a=True).send_task(
        "https://remote.test",
        task,
        protocol="a2a",
    )

    assert result.id == task.id
    assert result.state is TaskState.COMPLETED
    assert result.metadata["a2a_remote_context_id"] == "context-direct"
    assert result.get_last_part_content() == "direct answer"


@pytest.mark.asyncio
async def test_jsonrpc_error_is_raised_as_typed_a2a_error() -> None:
    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "error": {
                "code": -32005,
                "message": "unsupported content",
                "data": {"reason": "CONTENT_TYPE_NOT_SUPPORTED"},
            },
        }

    client = AgentClient(_FakeHTTPTransport(handler), a2a=True)
    with pytest.raises(A2AClientError) as caught:
        await client.send_task(
            "https://remote.test",
            Task.create_infer(prompt="hello"),
            protocol="a2a",
        )

    assert caught.value.code == -32005
    assert caught.value.data == {"reason": "CONTENT_TYPE_NOT_SUPPORTED"}


@pytest.mark.asyncio
async def test_send_message_never_returns_the_original_request_for_artifact_only_result() -> None:
    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {
                "task": {
                    "id": "remote-artifact-task",
                    "contextId": "remote-artifact-context",
                    "status": {
                        "state": "TASK_STATE_COMPLETED",
                        "timestamp": "2026-07-14T10:00:00Z",
                    },
                    "artifacts": [
                        {
                            "artifactId": "answer",
                            "parts": [{"text": "artifact answer"}],
                        }
                    ],
                }
            },
        }

    client = AgentClient(_FakeHTTPTransport(handler), a2a=True)
    with pytest.raises(RuntimeError, match="returned artifacts but no response message"):
        await client.send_message(
            "https://remote.test",
            Message.user("artifact request"),
            protocol="a2a",
        )


@pytest.mark.asyncio
async def test_continuation_replaces_an_updated_artifact_with_the_same_id() -> None:
    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        wire_task = _wire_task(data["params"]["message"])
        wire_task["artifacts"] = [
            {
                "artifactId": "answer",
                "parts": [{"text": "complete output"}],
            }
        ]
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {"task": wire_task},
        }

    task = Task.create_infer(prompt="finish")
    task.add_artifact(Artifact(id="answer", parts=[Part.text("partial output")]))
    result = await AgentClient(_FakeHTTPTransport(handler), a2a=True).send_task(
        "https://remote.test",
        task,
        protocol="a2a",
    )

    assert len(result.artifacts) == 1
    assert result.artifacts[0].parts[0].content == "complete output"


@pytest.mark.asyncio
async def test_cross_origin_interface_requires_explicit_trust() -> None:
    jsonrpc_calls = 0

    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        nonlocal jsonrpc_calls
        if spec.name == "get_a2a_agent_card":
            return _a2a_card("https://rpc.remote-cdn.test/a2a")
        jsonrpc_calls += 1
        request_message = data["params"]["message"]
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {"task": _wire_task(request_message)},
        }

    transport = _FakeHTTPTransport(handler)
    default_client = AgentClient(transport, a2a=True)
    with pytest.raises(A2AClientError, match="cross-origin interface"):
        await default_client.send_task(
            "https://remote.test",
            Task.create_infer(prompt="safe by default"),
            protocol="a2a",
        )
    assert jsonrpc_calls == 0

    trusted_client = AgentClient(
        transport,
        a2a=True,
        a2a_allow_cross_origin=True,
    )
    result = await trusted_client.send_task(
        "https://remote.test",
        Task.create_infer(prompt="trusted endpoint"),
        protocol="a2a",
    )
    assert result.state is TaskState.COMPLETED
    assert jsonrpc_calls == 1


@pytest.mark.asyncio
async def test_auto_cancel_never_falls_through_to_native_for_an_a2a_peer() -> None:
    calls: list[str] = []

    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        calls.append(spec.name)
        if spec.name == "get_agent_card":
            return TransportRemoteError("missing", status_code=404)
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        if spec.name == "a2a_jsonrpc":
            return {
                "jsonrpc": "2.0",
                "id": data["id"],
                "result": {
                    "message": {
                        "messageId": "direct-without-task-id",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": "accepted without a task"}],
                        "contextId": "direct-context",
                    }
                },
            }
        raise AssertionError("A2A cancellation must not use the native task route")

    client = AgentClient(_FakeHTTPTransport(handler), a2a=True)
    task = Task.create_infer(prompt="start")
    await client.send_task("https://remote.test", task)

    with pytest.raises(A2AClientError, match="No A2A remote task ID"):
        await client.cancel_task("https://remote.test", task.id)
    assert "cancel_task" not in calls


@pytest.mark.asyncio
async def test_outbound_remote_task_index_is_bounded() -> None:
    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        request_message = data["params"]["message"]
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {"task": _wire_task(request_message, task_id=f"remote-{request_message['messageId']}")},
        }

    adapter = A2AJSONRPCClientAdapter(
        _FakeHTTPTransport(handler),
        _max_remote_tasks=1,
    )
    first = Task.create_infer(prompt="first")
    second = Task.create_infer(prompt="second")

    await adapter.send_task("https://remote.test", first)
    await adapter.send_task("https://remote.test", second)

    assert adapter.has_task("https://remote.test", first.id) is False
    assert adapter.has_task("https://remote.test", second.id) is True


@pytest.mark.asyncio
async def test_a2a_task_result_may_omit_optional_context_id() -> None:
    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        del base_url
        if spec.name == "get_a2a_agent_card":
            return _a2a_card()
        return {
            "jsonrpc": "2.0",
            "id": data["id"],
            "result": {
                "task": {
                    "id": "remote-without-context",
                    "status": {
                        "state": "TASK_STATE_COMPLETED",
                        "timestamp": "2026-07-14T10:00:00Z",
                    },
                }
            },
        }

    result = await AgentClient(_FakeHTTPTransport(handler), a2a=True).send_task(
        "https://remote.test",
        Task.create_infer(prompt="context is optional"),
        protocol="a2a",
    )

    assert result.state is TaskState.COMPLETED
    assert result.metadata["a2a_remote_task_id"] == "remote-without-context"
    assert "a2a_remote_context_id" not in result.metadata


@pytest.mark.asyncio
async def test_auto_protocol_cache_is_bounded() -> None:
    def handler(spec: ClientRequestSpec, base_url: str, data: Any) -> Any:
        if spec.name == "get_agent_card":
            return AgentCard(name=base_url, description="native", url=base_url)
        if spec.name == "send_task":
            return Task.from_dict(data.to_dict()).complete("native")
        raise AssertionError(f"unexpected request: {spec.name}")

    client = AgentClient(_FakeHTTPTransport(handler), a2a=True)
    client._PROTOCOL_CACHE_MAX = 1

    await client.send_task("https://native-one.test", Task.create_infer(prompt="one"))
    await client.send_task("https://native-two.test", Task.create_infer(prompt="two"))

    assert list(client._protocol_cache) == ["https://native-two.test"]
