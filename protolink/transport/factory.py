from protolink.transport.agent.base import AgentTransport
from protolink.transport.agent.http_transport import HTTPAgentTransport
from protolink.transport.agent.websocket_transport import WebSocketAgentTransport

_TRANSPORT_REGISTRY: dict[str, type[AgentTransport]] = {
    "http": HTTPAgentTransport,
    "websocket": WebSocketAgentTransport,
}


def get_agent_transport(transport: str, **kwargs) -> AgentTransport:
    try:
        transport_class = _TRANSPORT_REGISTRY[transport.lower()]
    except KeyError:
        raise ValueError(f"Unknown agent transport name: {transport}") from None

    return transport_class(**kwargs)


def register_agent_transport(name: str, cls: type[AgentTransport]) -> None:
    _TRANSPORT_REGISTRY[name] = cls
