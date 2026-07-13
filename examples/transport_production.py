"""Configure production transport behavior on a concrete transport.

This provider-free example uses RuntimeTransport so it can run without opening
a network port. The same ``TransportConfig`` works unchanged with HTTP, SSE
JSON-RPC, WebSocket, and gRPC transports.
"""

from protolink import (
    Agent,
    AgentCard,
    AgentInterface,
    RetryPolicy,
    TransportConfig,
    TransportLimits,
)
from protolink.transport import RuntimeTransport


def main() -> None:
    """Start a bounded local agent and inspect transport health and metrics."""
    transport_config = TransportConfig(
        limits=TransportLimits(
            max_request_bytes=8 * 1024 * 1024,
            max_response_bytes=8 * 1024 * 1024,
            max_event_bytes=1024 * 1024,
            max_concurrent_requests=100,
            max_concurrent_streams=25,
        ),
        retry=RetryPolicy(max_attempts=3),
        keepalive_interval=20,
        keepalive_timeout=10,
        shutdown_timeout=10,
    )
    card = AgentCard(
        name="production-worker",
        description="Provider-free transport configuration example",
        url="runtime://production-worker",
        interfaces=[
            AgentInterface(
                url="grpcs://worker.internal:9443",
                transport="grpc",
            )
        ],
    )
    transport = RuntimeTransport(card.url, config=transport_config)
    agent = Agent(
        card=card,
        transport=transport,
        verbosity=0,
    )

    agent.start(register=False, background=True)
    try:
        health = agent.transport.health() if agent.transport is not None else {}
        print(health["status"])
        print(health["metrics"])
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
