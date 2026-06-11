import pytest

from protolink.agents import Agent
from protolink.client import AgentClient
from protolink.core.task import Task
from protolink.llms import create_llm
from protolink.transport import Transport
from protolink.transport.sse_jsonrpc_transport import SSEJSONRPCTransport


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
