"""Transport-neutral client operations for the ProtoLink Agent Registry."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from protolink.client.request_spec import ClientRequestSpec
from protolink.models import AgentCard
from protolink.transport import Transport

# ----------------------------------------------------------------------
# Agent-to-Registry Communication
# ----------------------------------------------------------------------


class RegistryClient:
    """Call Registry endpoints through an already configured transport.

    The transport owns its URL, TLS, authentication, limits, and retry policy. Registry operations declare idempotency
    individually so transports can retry only those calls whose semantics are safe to repeat.

    Args:
        transport: Concrete transport used for every Registry request.
    """

    REGISTER_REQUEST = ClientRequestSpec(
        name="register",
        path="/agents/",
        method="POST",
        request_source="body",
    )

    UNREGISTER_REQUEST = ClientRequestSpec(
        name="unregister",
        path="/agents/",
        method="DELETE",
        request_source="body",
        idempotent=True,
    )

    HEARTBEAT_REQUEST = ClientRequestSpec(
        name="heartbeat",
        path="/agents/heartbeat",
        method="POST",
        request_source="body",
        idempotent=True,
    )

    DISCOVER_REQUEST = ClientRequestSpec(
        name="discover",
        path="/agents/",
        method="GET",
        request_source="query_params",
        idempotent=True,
    )

    def __init__(self, transport: Transport):
        """Store the concrete Registry transport without modifying it."""
        self.transport = transport

    async def register(self, card: AgentCard) -> dict[str, str]:
        """Register an agent to the registry.

        Args:
            card: AgentCard to register

        Raises:
            ConnectionError: If registry is not reachable
            RuntimeError: If registration fails for other reasons
        """
        response = await self.transport.send(
            request_spec=self.REGISTER_REQUEST, base_url=self.transport.url, data=card.to_dict()
        )
        return response

    async def unregister(self, agent_url: str) -> dict[str, str]:
        """Remove an agent registration by its stable URL.

        Args:
            agent_url: URL that identifies the registered agent.

        Returns:
            Registry status payload.
        """
        response = await self.transport.send(
            request_spec=self.UNREGISTER_REQUEST, base_url=self.transport.url, data={"agent_url": agent_url}
        )
        return response

    async def heartbeat(self, agent_url: str) -> dict[str, str]:
        """Refresh the registry liveness timestamp for a registered agent.

        Args:
            agent_url: Stable URL of the registered agent.

        Returns:
            Registry status payload.
        """
        response = await self.transport.send(
            request_spec=self.HEARTBEAT_REQUEST,
            base_url=self.transport.url,
            data={"agent_url": agent_url},
        )
        return response

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Discover Agent cards matching optional Registry filters.

        Args:
            filter_by: Optional name, role, tag, or other supported filters.

        Returns:
            Agent cards reconstructed from the Registry response.
        """
        response = await self.transport.send(
            request_spec=self.DISCOVER_REQUEST, base_url=self.transport.url, data=filter_by
        )
        # Serialized transports return mappings, while in-process transports
        # may preserve the already-materialized endpoint result. Normalize
        # both representations at this transport-neutral boundary.
        cards: list[AgentCard] = []
        for index, card in enumerate(response):
            if isinstance(card, AgentCard):
                # Keep the in-process path consistent with network transports:
                # callers receive a detached, validated card rather than a
                # mutable object owned by the Registry.
                cards.append(AgentCard.from_dict(deepcopy(card.to_dict())))
            elif isinstance(card, Mapping):
                cards.append(AgentCard.from_dict(deepcopy(dict(card))))
            else:
                raise TypeError(
                    f"Registry discovery item {index} must be an AgentCard or mapping, got {type(card).__name__}"
                )
        return cards

    @property
    def url(self) -> str:
        """Return the Registry URL owned by the configured transport."""
        return self.transport.url
