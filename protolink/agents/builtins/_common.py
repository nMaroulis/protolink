"""Shared defaults for Agent presets; execution remains owned by Agent."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from protolink.agents.base import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.policy import CapabilityPolicy
from protolink.tools.base import BaseTool
from protolink.tools.builtins.user_input import UserInputHandler, ask_user_tool


def configure_preset(
    options: dict[str, Any],
    card: AgentCard | dict[str, Any] | None,
    *,
    name: str,
    description: str,
    prompt: str,
    rules: Mapping[str, str],
) -> None:
    """Apply defaults without displacing normal Agent identity or custom policies."""
    if card is None:
        options.setdefault("name", name)
        options.setdefault("description", description)
    options.setdefault("system_prompt", prompt)
    if options.get("policy") is None:
        options["policy"] = CapabilityPolicy(rules, default_effect="deny")


def add_preset_tools(agent: Agent, tools: Iterable[BaseTool], ask_user: UserInputHandler | None) -> None:
    """Keep caller-supplied tools and install durable questions without a live UI."""
    for tool in tools:
        if tool.name not in agent.tools:
            agent.add_tool(tool)
    if (ask_user is not None or agent.durability is not None) and "ask_user" not in agent.tools:
        agent.add_tool(ask_user_tool(ask_user))
