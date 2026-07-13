"""Focused contract tests for the optional A2A 1.0 JSON-RPC boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest

from protolink.a2a.v1 import (
    A2A_AGENT_CARD_PATH,
    A2A_PROTOCOL_VERSION,
    A2AJSONRPCAdapter,
    agent_card_to_a2a,
    message_from_a2a,
    message_to_a2a,
    task_to_a2a,
)
from protolink.a2a.v1.serialization import part_from_a2a, part_to_a2a
from protolink.client.request_spec import ClientRequestSpec
from protolink.core.agent_card import AgentCard, AgentSkill
from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.core.task import Task, TaskState
from protolink.server.agent import AgentServer
from protolink.server.endpoint_handler import EndpointRequest, EndpointSpec
from protolink.transport.base import Transport
from protolink.transport.config import TransportCapabilities


def _card() -> AgentCard:
    return AgentCard(
        name="wire-test-agent",
        description="Deterministic A2A adapter test agent",
        url="http://agent.test",
        version="2.4.0",
        protocol_version="9.9",
        skills=[
            AgentSkill(
                id="summarize_text",
                description="Summarize supplied text",
                tags=["summary"],
                examples=["Summarize this", {"ignored": "non-string example"}],
            )
        ],
    )


class _HarnessAgent:
    """Small deterministic agent used to exercise the adapter without sockets."""

    def __init__(self) -> None:
        self.card = _card()
        self.llm = None

    async def run_task(self, task: Task) -> Task:
        message_id = task.messages[-1].id
        if message_id.startswith("needs-input"):
            return task.require_input(Message.agent("More input required"))
        if message_id.startswith("direct-message"):
            task.metadata["a2a_response_kind"] = "message"
            return task.complete("Direct message response")
        return task.complete("Adapter response")

    async def cancel_task(self, request: Any) -> Any:
        return request

    async def compact_history(self, request: Any) -> Any:
        return request

    async def describe_state(self, request: Any) -> Any:
        return request

    async def reset_state(self, request: Any) -> Any:
        return request

    async def compact_state(self, request: Any) -> Any:
        return request

    def get_agent_card(self, *, as_json: bool = True) -> AgentCard | dict[str, Any]:
        return self.card.to_dict() if as_json else self.card

    def get_status(self, output_format: str = "html") -> str:
        return output_format

    def get_chat(self) -> str:
        return "chat"

    async def handle_chat_message(self, data: dict[str, Any]) -> dict[str, str]:
        return {"response": str(data)}


class _BlockingAgent(_HarnessAgent):
    """Agent whose completion is controlled by the test event loop."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_task(self, task: Task) -> Task:
        self.started.set()
        await self.release.wait()
        return task.complete("Released response")


class _CapturingHTTPTransport(Transport):
    """HTTP-identified transport that records route declarations without I/O."""

    transport_type: ClassVar[str] = "http"
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(networked=True)

    def __init__(self) -> None:
        super().__init__()
        self.endpoints: list[EndpointSpec] = []
        self._url = "http://agent.test"

    async def send(
        self,
        request_spec: ClientRequestSpec,
        base_url: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        del request_spec, base_url, data, params
        return None

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        del agent_url, task
        if False:  # pragma: no cover - preserve async-iterator shape
            yield None

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        self.endpoints.extend(endpoints)

    async def start(self) -> None:
        self._transport_running = True

    async def stop(self) -> None:
        self._transport_running = False

    def validate_url(self) -> bool:
        return True

    @property
    def url(self) -> str:
        return self._url


def _wire_message(
    message_id: str,
    text: str = "hello",
    *,
    task_id: str | None = None,
    context_id: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "messageId": message_id,
        "role": "ROLE_USER",
        "parts": [{"text": text}],
    }
    if task_id:
        message["taskId"] = task_id
    if context_id:
        message["contextId"] = context_id
    return message


def _request(
    method: str,
    params: dict[str, Any],
    *,
    request_id: int = 1,
    version: str = A2A_PROTOCOL_VERSION,
    content_type: str = "application/json",
    principal_id: str | None = None,
) -> EndpointRequest:
    return EndpointRequest(
        body={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        },
        headers={
            "A2A-Version": version,
            "Content-Type": content_type,
        },
        method="POST",
        url="http://agent.test/",
        principal_id=principal_id,
    )


def _assert_a2a_error(response: dict[str, Any], code: int, reason: str) -> None:
    assert response["error"]["code"] == code
    assert response["error"]["data"] == [
        {
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": reason,
            "domain": "a2a-protocol.org",
        }
    ]


def _indexed_task(
    task_id: str,
    *,
    context_id: str,
    state: TaskState,
    status_timestamp: str,
) -> Task:
    return Task(
        id=task_id,
        state=state,
        messages=[Message.user(f"request for {task_id}")],
        artifacts=[Artifact(name=f"{task_id}.txt", parts=[Part.text(task_id)])],
        metadata={
            "a2a_context_id": context_id,
            "state_history": [
                {
                    "previous_state": TaskState.WORKING.value,
                    "new_state": state.value,
                    "timestamp": status_timestamp,
                }
            ],
        },
    )


def test_agent_card_uses_a2a_1_0_fields_and_keeps_agent_version_distinct() -> None:
    card = agent_card_to_a2a(_card())

    assert card["version"] == "2.4.0"
    assert card["supportedInterfaces"] == [
        {
            "url": "http://agent.test",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert card["defaultInputModes"] == ["text/plain"]
    assert card["defaultOutputModes"] == ["text/plain"]
    assert card["capabilities"] == {
        "streaming": False,
        "pushNotifications": False,
        "extendedAgentCard": False,
    }
    assert card["skills"] == [
        {
            "id": "summarize_text",
            "name": "Summarize Text",
            "description": "Summarize supplied text",
            "tags": ["summary"],
            "examples": ["Summarize this"],
        }
    ]
    assert not {"url", "transport", "protocolVersion", "inputFormats", "outputFormats"}.intersection(card)


def test_agent_card_translates_native_security_schemes_to_a2a_unions() -> None:
    source = _card()
    source.security_schemes = {
        "http": {
            "type": "http",
            "scheme": "bearer",
            "description": "Signed access token",
        },
        "apiKey": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Agent-Key",
        },
    }

    card = agent_card_to_a2a(source)

    assert card["securitySchemes"] == {
        "http": {
            "httpAuthSecurityScheme": {
                "scheme": "bearer",
                "description": "Signed access token",
            }
        },
        "apiKey": {
            "apiKeySecurityScheme": {
                "location": "header",
                "name": "X-Agent-Key",
            }
        },
    }
    assert card["securityRequirements"] == [
        {"schemes": {"http": {"list": []}}},
        {"schemes": {"apiKey": {"list": []}}},
    ]


@pytest.mark.parametrize(
    ("wire_part", "internal_type", "wire_key"),
    [
        ({"text": "hello"}, "text", "text"),
        ({"data": {"count": 2}}, "json", "data"),
        (
            {
                "raw": "aGVsbG8=",
                "filename": "hello.txt",
                "mediaType": "text/plain",
            },
            "bytes",
            "raw",
        ),
        (
            {
                "url": "https://example.test/hello.txt",
                "filename": "hello.txt",
                "mediaType": "text/plain",
            },
            "uri",
            "url",
        ),
    ],
)
def test_part_round_trip_uses_a2a_member_discrimination(
    wire_part: dict[str, Any],
    internal_type: str,
    wire_key: str,
) -> None:
    part = part_from_a2a(wire_part)
    serialized = part_to_a2a(part)

    assert part.type == internal_type
    assert wire_key in serialized
    assert len({"text", "data", "raw", "url"}.intersection(serialized)) == 1


def test_message_and_task_mapping_use_camel_case_enums_and_utc_timestamps() -> None:
    message = message_from_a2a(_wire_message("message-1"))
    task = Task.create(message)
    task.metadata["a2a_context_id"] = "context-1"
    task.complete("done")
    task.add_artifact(Artifact(name="answer.txt", parts=[Part.text("artifact output")]))

    wire_message = message_to_a2a(message, context_id="context-1", task_id=task.id)
    wire_task = task_to_a2a(task, history_length=1)

    assert wire_message == {
        "messageId": "message-1",
        "role": "ROLE_USER",
        "parts": [{"text": "hello"}],
        "contextId": "context-1",
        "taskId": task.id,
    }
    assert wire_task["contextId"] == "context-1"
    assert wire_task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert wire_task["status"]["timestamp"].endswith("Z")
    assert wire_task["status"]["message"]["role"] == "ROLE_AGENT"
    assert len(wire_task["history"]) == 1
    assert wire_task["artifacts"][0]["artifactId"] == task.artifacts[0].id
    assert "history" not in task_to_a2a(task, history_length=0)


@pytest.mark.asyncio
async def test_jsonrpc_send_get_list_and_cancel_task_lifecycle() -> None:
    adapter = A2AJSONRPCAdapter(_HarnessAgent())

    sent = await adapter.handle(_request("SendMessage", {"message": _wire_message("needs-input-1")}))
    task = sent["result"]["task"]
    task_id = task["id"]
    context_id = task["contextId"]
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"

    fetched = await adapter.handle(_request("GetTask", {"id": task_id}, request_id=2))
    assert fetched["result"]["id"] == task_id

    listed = await adapter.handle(
        _request(
            "ListTasks",
            {"contextId": context_id, "pageSize": 10, "historyLength": 0},
            request_id=3,
        )
    )
    assert listed["result"]["totalSize"] == 1
    assert listed["result"]["tasks"][0]["id"] == task_id
    assert "history" not in listed["result"]["tasks"][0]

    canceled = await adapter.handle(_request("CancelTask", {"id": task_id}, request_id=4))
    assert canceled["result"]["id"] == task_id
    assert canceled["result"]["status"]["state"] == "TASK_STATE_CANCELED"


@pytest.mark.asyncio
async def test_return_immediately_runs_in_background_while_default_mode_blocks() -> None:
    nonblocking_agent = _BlockingAgent()
    nonblocking = A2AJSONRPCAdapter(nonblocking_agent)

    immediate = await nonblocking.handle(
        _request(
            "SendMessage",
            {
                "message": _wire_message("nonblocking-1"),
                "configuration": {"returnImmediately": True},
            },
        )
    )
    task_id = immediate["result"]["task"]["id"]
    assert immediate["result"]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    await asyncio.wait_for(nonblocking_agent.started.wait(), timeout=1)

    background_execution = nonblocking._executions[task_id]
    nonblocking_agent.release.set()
    await asyncio.wait_for(background_execution, timeout=1)
    completed = await nonblocking.handle(_request("GetTask", {"id": task_id}, request_id=2))
    assert completed["result"]["status"]["state"] == "TASK_STATE_COMPLETED"

    blocking_agent = _BlockingAgent()
    blocking = A2AJSONRPCAdapter(blocking_agent)
    request_task = asyncio.create_task(
        blocking.handle(
            _request(
                "SendMessage",
                {
                    "message": _wire_message("blocking-1"),
                    "configuration": {"returnImmediately": False},
                },
            )
        )
    )
    await asyncio.wait_for(blocking_agent.started.wait(), timeout=1)
    assert not request_task.done()
    blocking_agent.release.set()
    blocked_result = await asyncio.wait_for(request_task, timeout=1)
    assert blocked_result["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.asyncio
async def test_cancel_task_stops_a_nonblocking_adapter_execution() -> None:
    agent = _BlockingAgent()
    adapter = A2AJSONRPCAdapter(agent)

    sent = await adapter.handle(
        _request(
            "SendMessage",
            {
                "message": _wire_message("cancel-background-1"),
                "configuration": {"returnImmediately": True},
            },
        )
    )
    task_id = sent["result"]["task"]["id"]
    await asyncio.wait_for(agent.started.wait(), timeout=1)

    canceled = await adapter.handle(_request("CancelTask", {"id": task_id}, request_id=2))
    assert canceled["result"]["status"]["state"] == "TASK_STATE_CANCELED"
    execution = adapter._executions.get(task_id)
    if execution is not None:
        await asyncio.wait_for(execution, timeout=1)


@pytest.mark.asyncio
async def test_list_tasks_applies_filters_order_pagination_and_artifact_policy() -> None:
    adapter = A2AJSONRPCAdapter(_HarnessAgent())
    adapter._tasks.update(
        {
            "older": _indexed_task(
                "older",
                context_id="context-1",
                state=TaskState.COMPLETED,
                status_timestamp="2026-07-13T10:00:00Z",
            ),
            "newer": _indexed_task(
                "newer",
                context_id="context-1",
                state=TaskState.COMPLETED,
                status_timestamp="2026-07-13T12:00:00Z",
            ),
            "waiting": _indexed_task(
                "waiting",
                context_id="context-1",
                state=TaskState.INPUT_REQUIRED,
                status_timestamp="2026-07-13T13:00:00Z",
            ),
            "other-context": _indexed_task(
                "other-context",
                context_id="context-2",
                state=TaskState.COMPLETED,
                status_timestamp="2026-07-13T14:00:00Z",
            ),
        }
    )

    first_page = await adapter.handle(
        _request(
            "ListTasks",
            {
                "contextId": "context-1",
                "status": "TASK_STATE_COMPLETED",
                "pageSize": 1,
            },
        )
    )
    first_result = first_page["result"]
    assert first_result["totalSize"] == 2
    assert [task["id"] for task in first_result["tasks"]] == ["newer"]
    assert "artifacts" not in first_result["tasks"][0]
    assert first_result["nextPageToken"] == "1"

    second_page = await adapter.handle(
        _request(
            "ListTasks",
            {
                "context_id": "context-1",
                "status": "TASK_STATE_COMPLETED",
                "page_size": 1,
                "page_token": first_result["nextPageToken"],
                "include_artifacts": True,
            },
            request_id=2,
        )
    )
    second_result = second_page["result"]
    assert [task["id"] for task in second_result["tasks"]] == ["older"]
    assert second_result["tasks"][0]["artifacts"][0]["name"] == "older.txt"
    assert second_result["nextPageToken"] == ""

    after_cutoff = await adapter.handle(
        _request(
            "ListTasks",
            {
                "contextId": "context-1",
                "statusTimestampAfter": "2026-07-13T11:00:00Z",
            },
            request_id=3,
        )
    )
    assert [task["id"] for task in after_cutoff["result"]["tasks"]] == ["waiting", "newer"]

    all_contexts = await adapter.handle(_request("ListTasks", {}, request_id=4))
    assert all_contexts["result"]["totalSize"] == 4


@pytest.mark.asyncio
async def test_task_operations_are_scoped_to_the_authenticated_principal() -> None:
    adapter = A2AJSONRPCAdapter(_HarnessAgent())

    sent = await adapter.handle(
        _request(
            "SendMessage",
            {"message": _wire_message("needs-input-private-1")},
            principal_id="alice",
        )
    )
    task_id = sent["result"]["task"]["id"]
    context_id = sent["result"]["task"]["contextId"]

    hidden_get = await adapter.handle(_request("GetTask", {"id": task_id}, request_id=2, principal_id="bob"))
    _assert_a2a_error(hidden_get, -32001, "TASK_NOT_FOUND")

    hidden_cancel = await adapter.handle(_request("CancelTask", {"id": task_id}, request_id=3, principal_id="bob"))
    _assert_a2a_error(hidden_cancel, -32001, "TASK_NOT_FOUND")

    hidden_list = await adapter.handle(
        _request("ListTasks", {"contextId": context_id}, request_id=4, principal_id="bob")
    )
    assert hidden_list["result"]["tasks"] == []

    owner_list = await adapter.handle(
        _request("ListTasks", {"contextId": context_id}, request_id=5, principal_id="alice")
    )
    assert [task["id"] for task in owner_list["result"]["tasks"]] == [task_id]


@pytest.mark.asyncio
async def test_jsonrpc_send_message_can_return_direct_message_variant() -> None:
    adapter = A2AJSONRPCAdapter(_HarnessAgent())

    response = await adapter.handle(_request("SendMessage", {"message": _wire_message("direct-message-1")}))

    assert "task" not in response["result"]
    assert response["result"]["message"]["role"] == "ROLE_AGENT"
    assert response["result"]["message"]["parts"] == [{"text": "Direct message response"}]


@pytest.mark.asyncio
async def test_jsonrpc_errors_include_standard_code_and_error_info() -> None:
    adapter = A2AJSONRPCAdapter(_HarnessAgent())

    missing = await adapter.handle(_request("GetTask", {"id": "missing"}))
    _assert_a2a_error(missing, -32001, "TASK_NOT_FOUND")

    unsupported = await adapter.handle(
        _request("SendStreamingMessage", {"message": _wire_message("stream-1")}, request_id=2)
    )
    _assert_a2a_error(unsupported, -32004, "UNSUPPORTED_OPERATION")

    unsupported_media = _wire_message("unsupported-media-1")
    unsupported_media["parts"] = [
        {
            "raw": "dGNr",
            "mediaType": "application/x-unsupported-test-type",
        }
    ]
    content_error = await adapter.handle(_request("SendMessage", {"message": unsupported_media}, request_id=3))
    _assert_a2a_error(content_error, -32005, "CONTENT_TYPE_NOT_SUPPORTED")


@pytest.mark.asyncio
async def test_jsonrpc_rejects_unsupported_http_content_type() -> None:
    adapter = A2AJSONRPCAdapter(_HarnessAgent())

    response = await adapter.handle(
        _request(
            "SendMessage",
            {"message": _wire_message("wrong-http-content-type-1")},
            content_type="text/plain",
        )
    )

    _assert_a2a_error(response, -32005, "CONTENT_TYPE_NOT_SUPPORTED")


@pytest.mark.asyncio
async def test_jsonrpc_version_handling_accepts_patch_and_rejects_unsupported_versions() -> None:
    adapter = A2AJSONRPCAdapter(_HarnessAgent())

    accepted = await adapter.handle(
        _request(
            "SendMessage",
            {"message": _wire_message("patch-version-1")},
            version="1.0.7",
        )
    )
    assert "result" in accepted

    empty = await adapter.handle(
        _request(
            "SendMessage",
            {"message": _wire_message("empty-version-1")},
            request_id=2,
            version="",
        )
    )
    _assert_a2a_error(empty, -32009, "VERSION_NOT_SUPPORTED")

    rejected = await adapter.handle(
        _request(
            "SendMessage",
            {"message": _wire_message("wrong-version-1")},
            request_id=3,
            version="1.1",
        )
    )
    _assert_a2a_error(rejected, -32009, "VERSION_NOT_SUPPORTED")


def test_agent_server_mounts_a2a_card_and_jsonrpc_without_removing_native_card() -> None:
    transport = _CapturingHTTPTransport()
    server = AgentServer(transport, _HarnessAgent())

    server._build_endpoints()
    routes = {(endpoint.method, endpoint.path): endpoint for endpoint in transport.endpoints}

    assert ("GET", "/.well-known/agent.json") in routes
    assert ("GET", A2A_AGENT_CARD_PATH) in routes
    assert routes[("GET", A2A_AGENT_CARD_PATH)].request_source == "none"
    assert ("POST", "/") in routes
    assert routes[("POST", "/")].request_source == "request"
    assert isinstance(routes[("POST", "/")].handler.__self__, A2AJSONRPCAdapter)
