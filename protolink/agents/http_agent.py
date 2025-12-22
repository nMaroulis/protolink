from typing import Literal, Unpack

from protolink.agents.base import Agent
from protolink.client import RegistryClient
from protolink.core.agent_card import AgentCardArgs
from protolink.discovery.registry import Registry
from protolink.llms.base import LLM
from protolink.models import AgentCard
from protolink.transport import HTTPAgentTransport


class HTTPAgent(Agent):
    """
    HTTP-based Agent with implicit AgentCard construction.

    This class is a convenience wrapper around :class:`Agent` that allows users
    to define an agent by passing ``AgentCard`` fields directly as keyword
    arguments, without explicitly instantiating an ``AgentCard`` or transport.

    All keyword arguments not explicitly consumed by ``HTTPAgent`` are forwarded
    to ``AgentCard`` and validated there. This makes ``AgentCard`` the single
    source of truth for agent metadata and capabilities.

    Parameters
    ----------
    registry:
        Optional registry (or registry URL) where the agent should be registered.
    llm:
        Optional LLM instance used by the agent.
    skills:
        Skill handling mode:
        - ``"auto"``: infer skills from the agent card and tools (default)
        - ``"fixed"``: use only explicitly declared skills
    **kwargs:
        Keyword arguments corresponding to ``AgentCard`` fields, such as
        ``name``, ``description``, ``url``, ``version``, ``capabilities``,
        ``skills``, ``input_formats``, ``output_formats``, and
        ``security_schemes``.

    Raises
    ------
    TypeError
        If invalid or unknown ``AgentCard`` fields are provided.
    ValueError
        If required ``AgentCard`` fields are missing.

    Examples
    --------
    Basic usage:

    >>> agent = HTTPAgent(
    ...     name="WeatherAgent",
    ...     description="Produces weather data",
    ...     url="http://localhost:8010",
    ... )

    With additional AgentCard fields:

    >>> agent = HTTPAgent(
    ...     name="WeatherAgent",
    ...     description="Produces weather data",
    ...     url="http://localhost:8010",
    ...     version="1.1.0",
    ...     input_formats=["text/plain", "application/json"],
    ... )

    Advanced usage with registry and LLM:

    >>> agent = HTTPAgent(
    ...     name="WeatherAgent",
    ...     description="Produces weather data",
    ...     url="http://localhost:8010",
    ...     registry="http://localhost:9000",
    ...     llm=my_llm,
    ... )
    """

    def __init__(
        self,
        *,
        registry: Registry | RegistryClient | str | None = None,
        llm: LLM | None = None,
        skills_mode: Literal["auto", "fixed"] = "auto",
        **kwargs: Unpack[AgentCardArgs],
    ):
        agent_card = AgentCard(**kwargs)
        transport = HTTPAgentTransport(url=agent_card.url)
        super().__init__(card=agent_card, transport=transport, registry=registry, llm=llm, skills=skills_mode)
