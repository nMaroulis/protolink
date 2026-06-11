"""Streaming agent example.

This example demonstrates the full streaming path added to Protolink:

1. An Agent with a streaming-capable transport exposes ``/tasks/stream``.
2. ``AgentClient.send_task_streaming()`` subscribes to that task stream.
3. ``Agent.handle_task_streaming()`` calls ``LLM.infer(streaming=True)``.
4. The client receives task status, LLM stream, artifact, and final events.

The default mode uses ``RuntimeTransport`` and ``MockLLM`` so the example can
run without API keys or a local model server.

Run:
    python examples/streaming_agent.py

Try the synchronous CLI-style iterator:
    python examples/streaming_agent.py --sync

Try SSE JSON-RPC if you installed the HTTP extras:
    python examples/streaming_agent.py --transport sse

Try a real local model:
    python examples/streaming_agent.py --provider ollama --model qwen2.5-coder:7b
    python examples/streaming_agent.py --provider lmstudio --model local-model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

# PROJECT_ROOT = Path(__file__).resolve().parents[1]
# if str(PROJECT_ROOT) not in sys.path:
#     sys.path.insert(0, str(PROJECT_ROOT))
from protolink.agents import Agent
from protolink.client import AgentClient
from protolink.llms import MockLLM, create_llm
from protolink.llms.history import ConversationHistory
from protolink.models import AgentCard, Task

DEFAULT_PROMPT = "Say hello and briefly explain what just streamed."


class ChunkedMockLLM(MockLLM):
    """Mock LLM that streams its JSON action response in small chunks."""

    def __init__(self, *, chunk_size: int = 16, delay: float = 0.04) -> None:
        super().__init__(
            default_response=(
                "Hello from a streaming MockLLM. You are seeing task status, "
                "LLM chunks, the final artifact, and the closing event flow "
                "through AgentClient."
            )
        )
        self.chunk_size = chunk_size
        self.delay = delay

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Yield the normal mock response in small pieces."""
        response = self.call(history)
        for start in range(0, len(response), self.chunk_size):
            await asyncio.sleep(self.delay)
            yield response[start : start + self.chunk_size]


def make_llm(args: argparse.Namespace):
    """Create the LLM for the example from CLI arguments."""
    if args.provider == "mock":
        return ChunkedMockLLM(chunk_size=args.chunk_size, delay=args.delay)

    kwargs: dict[str, Any] = {}
    if args.model:
        kwargs["model"] = args.model
    if args.base_url:
        kwargs["base_url"] = args.base_url
    return create_llm(args.provider, **kwargs)


def make_agent(args: argparse.Namespace) -> Agent:
    """Create a streaming-capable agent for the selected transport."""
    agent_url = "runtime://streaming-agent"
    transport: Any = "runtime"
    if args.transport == "sse":
        agent_url = f"http://{args.host}:{args.port}"
        transport = "sse"
    elif args.transport == "runtime":
        transport = make_runtime_transport(agent_url)
    else:
        raise ValueError(f"Unsupported transport for this example: {args.transport}")

    card = AgentCard(
        name="streaming-agent",
        description="Streams LLM inference events through Protolink transports",
        url=agent_url,
    )
    return Agent(card=card, transport=transport, llm=make_llm(args), verbosity=args.verbosity)


def make_client(args: argparse.Namespace) -> tuple[AgentClient, str]:
    """Create a client and return it with the target agent URL."""
    if args.transport == "runtime":
        client_transport = make_runtime_transport("runtime://streaming-client")
        return AgentClient(transport=client_transport), "runtime://streaming-agent"

    client_url = f"http://{args.host}:{args.port + 1}"
    target_url = f"http://{args.host}:{args.port}"
    return AgentClient(transport="sse", url=client_url), target_url


def make_runtime_transport(url: str):
    """Create RuntimeTransport lazily so missing extras produce a clear error."""
    try:
        from protolink.transport import RuntimeTransport
    except ImportError as exc:
        raise RuntimeError(
            "RuntimeTransport requires the HTTP/test extras in this version "
            "(notably pydantic). Install development dependencies with "
            "`pip install -e .[dev]` or `uv pip install -e .[dev]`."
        ) from exc
    return RuntimeTransport(url=url)


def render_event(event: Any) -> None:
    """Print streamed task events in a compact, readable format."""
    data = event.to_dict() if hasattr(event, "to_dict") else event
    if not isinstance(data, dict):
        print(f"[event] {data}")
        return

    event_type = data.get("type", "event")

    if event_type == "task_status_update":
        state = data.get("new_state", "")
        final = " final" if data.get("final") else ""
        print(f"[status{final}] {state}")
        return

    if event_type == "task_llm_stream":
        llm_type = data.get("llm_event_type", "")
        if llm_type == "llm_chunk":
            print(data.get("content", ""), end="", flush=True)
        elif llm_type == "llm_final":
            print(f"\n[llm final] {data.get('content')}")
        else:
            details = _compact_json(data.get("metadata", {}))
            print(f"\n[llm {llm_type}] step={data.get('step')} {details}".rstrip())
        return

    if event_type == "task_artifact_update":
        print(f"[artifact] {_extract_artifact_text(data.get('artifact'))}")
        return

    if event_type == "task_error":
        print(f"[error] {data.get('error_code')}: {data.get('error_message')}")
        return

    print(f"[{event_type}] {_compact_json(data)}")


def _extract_artifact_text(artifact: Any) -> str:
    if not isinstance(artifact, dict):
        return str(artifact)
    parts = artifact.get("parts") or []
    if not parts:
        return _compact_json(artifact)
    return " ".join(str(part.get("content", "")) for part in parts if isinstance(part, dict))


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except TypeError:
        return str(value)


async def run_async(args: argparse.Namespace) -> None:
    """Run the async streaming client path."""
    agent = make_agent(args)
    agent.start(background=True)
    await asyncio.sleep(args.startup_delay)

    client, target_url = make_client(args)
    task = Task.create_infer(prompt=args.prompt)

    try:
        print_header(agent, target_url)
        async for event in client.send_task_streaming(target_url, task):
            render_event(event)
    finally:
        agent.stop()


def run_sync(args: argparse.Namespace) -> None:
    """Run the blocking ``client.sync.send_task_streaming()`` path."""
    agent = make_agent(args)
    agent.start(background=True)
    time.sleep(args.startup_delay)

    client, target_url = make_client(args)
    task = Task.create_infer(prompt=args.prompt)

    try:
        print_header(agent, target_url)
        for event in client.sync.send_task_streaming(target_url, task):
            render_event(event)
    finally:
        agent.stop()


def print_header(agent: Agent, target_url: str) -> None:
    """Print the demo setup before events start streaming."""
    print("=" * 72)
    print("Protolink streaming agent demo")
    print("=" * 72)
    print(f"Agent        : {agent.card.name}")
    print(f"Target URL   : {target_url}")
    print(f"Transport    : {agent.card.transport}")
    print(f"Can stream   : {agent.card.capabilities.streaming}")
    print(f"LLM provider : {agent.llm.provider if agent.llm else 'none'}")
    print("-" * 72)


def parse_args() -> argparse.Namespace:
    """Parse CLI options for the example."""
    parser = argparse.ArgumentParser(description="Run a Protolink streaming agent example.")
    parser.add_argument("--transport", choices=["runtime", "sse"], default="runtime")
    parser.add_argument("--provider", default="mock", help="LLM provider passed to create_llm().")
    parser.add_argument("--model", default=None, help="Optional model name for real providers.")
    parser.add_argument("--base-url", default=None, help="Optional provider base URL.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--sync", action="store_true", help="Use client.sync.send_task_streaming().")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8015)
    parser.add_argument("--startup-delay", type=float, default=0.25)
    parser.add_argument("--chunk-size", type=int, default=16)
    parser.add_argument("--delay", type=float, default=0.04, help="Mock chunk delay in seconds.")
    parser.add_argument("--verbosity", type=int, choices=[0, 1, 2], default=0)
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    if cli_args.sync:
        run_sync(cli_args)
    else:
        asyncio.run(run_async(cli_args))
