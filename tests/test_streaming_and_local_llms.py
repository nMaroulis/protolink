import json

import pytest

from protolink.agents import Agent
from protolink.client import AgentClient
from protolink.core.events import TaskLLMStreamEvent
from protolink.core.part import ToolOutput
from protolink.core.task import Task
from protolink.llms import create_llm
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport import Transport
from protolink.transport.backends import FastAPIBackend, StarletteBackend
from protolink.transport.sse_jsonrpc_transport import SSEJSONRPCTransport
from protolink.transport.websocket_transport import WebSocketTransport


class _FakeStreamingTransport(Transport):
    transport_type = "sse"
    supports_streaming = True

    async def send(self, request_spec, base_url, data=None, params=None):
        return data

    async def subscribe(self, agent_url, task):
        yield {"type": "task_status_update", "final": False}
        yield {"type": "task_status_update", "final": True}

    def setup_routes(self, endpoints):
        return None

    async def start(self):
        return None

    async def stop(self):
        return None

    def validate_url(self):
        return True

    @property
    def url(self):
        return "memory://client"


class _FakeNonStreamingTransport(_FakeStreamingTransport):
    supports_streaming = False


def test_create_mock_llm_without_optional_provider_imports():
    llm = create_llm("mock", default_response="hello")

    assert llm.provider == "mock"


def test_sse_jsonrpc_parse_event():
    transport = SSEJSONRPCTransport(url="http://localhost:9999")

    result, final = transport._parse_event(
        ['{"jsonrpc":"2.0","id":"abc","ok":true,"result":{"type":"event"},"final":true}'],
        "http://localhost:9999",
        "abc",
    )

    assert result == {"type": "event"}
    assert final is True


@pytest.mark.parametrize("backend_type", [StarletteBackend, FastAPIBackend])
@pytest.mark.asyncio
async def test_sse_backend_serializes_nested_tool_output(backend_type):
    tool_output = ToolOutput(call_id="call-1", result={"path": ".", "entries": ["README.md"]})

    async def stream_handler(_task):
        yield TaskLLMStreamEvent(
            task_id="task-1",
            agent_name="coder",
            llm_event_type="tool_result",
            metadata={"action": {"output": tool_output}},
        )

    endpoint = EndpointSpec(
        name="task_stream",
        path="/tasks/stream",
        method="POST",
        handler=stream_handler,
        streaming=True,
        mode="stream",
        request_source="body",
    )
    backend = backend_type()

    frames = [
        frame
        async for frame in backend._stream_sse(
            ep=endpoint,
            handler_input={"task_id": "task-1"},
            payload={"task_id": "task-1"},
            request_id="request-1",
        )
    ]

    event_envelope = json.loads(frames[0].removeprefix("data: "))
    assert event_envelope["ok"] is True
    assert event_envelope["result"]["metadata"]["action"]["output"] == {
        "call_id": "call-1",
        "result": {"path": ".", "entries": ["README.md"]},
        "error": None,
    }
    assert json.loads(frames[-1].removeprefix("data: "))["final"] is True


def test_websocket_transport_serializes_nested_tool_output():
    transport = WebSocketTransport(url="ws://localhost:9999")
    event = TaskLLMStreamEvent(
        task_id="task-1",
        llm_event_type="tool_result",
        metadata={"output": ToolOutput(call_id="call-1", result="done")},
    )

    payload = transport._serialize_result(event)

    assert payload["metadata"]["output"] == {
        "call_id": "call-1",
        "result": "done",
        "error": None,
    }


@pytest.mark.asyncio
async def test_agent_client_streaming_requires_streaming_transport():
    client = AgentClient(transport=_FakeNonStreamingTransport())
    task = Task.create_infer(prompt="hello")

    with pytest.raises(NotImplementedError, match="does not support streaming"):
        async for _event in client.send_task_streaming("memory://agent", task):
            pass


@pytest.mark.asyncio
async def test_agent_client_streaming_uses_transport_subscribe():
    client = AgentClient(transport=_FakeStreamingTransport())
    task = Task.create_infer(prompt="hello")

    events = []
    async for event in client.send_task_streaming("memory://agent", task):
        events.append(event)

    assert events[-1]["final"] is True


def test_sync_agent_client_streaming_yields_events():
    client = AgentClient(transport=_FakeStreamingTransport())
    task = Task.create_infer(prompt="hello")

    events = list(client.sync.send_task_streaming("memory://agent", task))

    assert events == [
        {"type": "task_status_update", "final": False},
        {"type": "task_status_update", "final": True},
    ]


def test_agent_transport_updates_streaming_capability():
    agent = Agent(
        {
            "name": "streamer",
            "description": "Streaming test agent",
            "url": "http://localhost:8001",
        },
        transport=_FakeStreamingTransport(),
    )

    assert agent.card.capabilities.streaming is True
    assert agent.card.transport == "sse"


@pytest.mark.asyncio
async def test_agent_streams_llm_events_and_attaches_final_artifact():
    llm = create_llm("mock", default_response="streamed hello")
    agent = Agent(
        {
            "name": "streamer",
            "description": "Streaming test agent",
            "url": "runtime://streamer",
            "capabilities": {"streaming": True},
        },
        llm=llm,
        verbosity=0,
    )
    task = Task.create_infer(prompt="hello")

    events = []
    async for event in agent.handle_task_streaming(task):
        events.append(event.to_dict() if hasattr(event, "to_dict") else event)

    event_types = [event["type"] for event in events]
    assert "task_llm_stream" in event_types
    assert "task_artifact_update" in event_types
    assert event_types[-1] == "task_status_update"
    assert events[-1]["final"] is True
    assert task.get_last_part_content() == "streamed hello"
