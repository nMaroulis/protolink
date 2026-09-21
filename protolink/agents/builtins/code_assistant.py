"""A small Agent preset for bounded shell execution and structured Git work."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from protolink.agents.base import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.policy import CapabilityPolicy
from protolink.llms.base import LLM
from protolink.tools.builtins import ask_user_tool, calculator, git_tool, shell_tool
from protolink.tools.builtins.user_input import UserInputHandler


class CodeAssistant(Agent):
    """An ordinary Agent with shell, Git, calculator, and optional user questions.

    The default policy allows Git reads and feedback, requires approval for shell
    execution/Git writes, and denies undeclared capabilities. Git writes also need
    ``allow_git_write=True``. Shell execution can change any host resource accessible
    to the process: ``cwd`` is a working directory, not a sandbox or write restriction.

    Example::

        coder = CodeAssistant(cwd="/workspace", llm=model, approval_handler=approve)
        answer = await coder.invoke("Inspect this repository and explain its tests.")

    This preset adds no execution loop; all normal Agent methods remain available.
    Customize tool settings by replacing a registered tool with a configured factory.
    Restore configurations through ``Agent.from_dict/from_yaml`` and reattach tools.
    """

    def __init__(
        self,
        llm: LLM | None = None,
        *,
        cwd: str | Path,
        env: Mapping[str, str] | None = None,
        ask_user: UserInputHandler | None = None,
        allow_git_write: bool = False,
        card: AgentCard | dict[str, Any] | None = None,
        **agent_options: Any,
    ) -> None:
        """Register workspace tools; additional options pass directly to Agent.

        Args:
            llm: Caller-selected model; optional for direct tool calls.
            cwd: Existing working directory for shell and Git tools.
            env: Complete child environment; ``None`` uses only a system PATH.
            ask_user: Optional async user-feedback callback.
            allow_git_write: Expose staging and committing behind Agent policy.
            card: Optional custom identity and transport URL.
            **agent_options: Normal Agent settings, including policy, approval_handler,
                system_prompt, state, storage, transport, and run_store.
        """
        if agent_options.get("policy") is None:
            agent_options["policy"] = CapabilityPolicy(
                {
                    "process.execute": "allow",
                    "git.read": "allow",
                    "user.interact": "allow",
                    "shell.execute": "require_approval",
                    "git.write": "require_approval",
                },
                default_effect="deny",
            )
        agent_options.setdefault(
            "system_prompt",
            (
                "Help the user inspect, change, and test code in the configured working directory. "
                "Inspect existing changes before editing. Preserve unrelated work. Use structured Git "
                "tools where possible. "
                "Check command exit codes, timeouts, and truncation; report evidence from tests before "
                "claiming success. "
                "Use ask_user when available for missing requirements. Never infer consent from a "
                "declined or timed-out "
                "question. Each shell call starts fresh. Do not retry uncertain mutations without "
                "inspecting their effects."
            ),
        )
        super().__init__(
            card
            or AgentCard(
                name="code-assistant", description="Shell and Git coding assistant", url="runtime://code-assistant"
            ),
            llm=llm,
            **agent_options,
        )
        self.add_tool(shell_tool(cwd=cwd, env=env))
        self.add_tool(git_tool(cwd=cwd, env=env, allow_write=allow_git_write))
        self.add_tool(calculator())
        if ask_user is not None:
            self.add_tool(ask_user_tool(ask_user))
