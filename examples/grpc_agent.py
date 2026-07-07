"""Minimal gRPC transport example.

Run:
    python examples/grpc_agent.py

This script starts one mock-LLM agent on a free local ``grpc://`` port, fetches
its public agent card, sends a unary task, and then consumes the same task over
the streaming API. It is provider-free and only requires the ``grpc`` extra.
"""

from __future__ import annotations

import importlib.util
import socket

from protolink import Agent, AgentCard, Task, create_llm
from protolink.client import AgentClient


def find_free_port() -> int:
    """Ask the OS for an available localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    """Run a request/response and streaming round trip over gRPC."""
    if importlib.util.find_spec("grpc") is None:
        print("Install the gRPC extra to run this example: pip install 'protolink[grpc]'")
        return

    port = find_free_port()
    agent_url = f"grpc://127.0.0.1:{port}"
    agent = Agent(
        AgentCard(
            name="grpc-echo-agent",
            description="Provider-free agent served over the gRPC transport",
            url=agent_url,
        ),
        transport="grpc",
        llm=create_llm("mock", default_response="hello from grpc"),
        verbosity=0,
    )
    client = AgentClient(transport="grpc", url="grpc://127.0.0.1:0")

    try:
        agent.start(register=False, background=True)

        card = client.sync.get_agent_card(agent_url)
        print(f"Connected to {card.name} at {card.url}")

        result = client.sync.send_task(agent_url, Task.create_infer(prompt="Say hello over gRPC"))
        print(f"Unary result: {result.get_last_part_content()}")

        print("Stream events:")
        for event in client.sync.send_task_streaming(agent_url, Task.create_infer(prompt="Stream hello over gRPC")):
            event_type = event.get("type") if isinstance(event, dict) else type(event).__name__
            print(f"- {event_type}")
            if isinstance(event, dict) and event.get("final"):
                break
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
