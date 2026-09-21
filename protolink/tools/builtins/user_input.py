"""Await application-owned user feedback inside an active agent tool call."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal

from pydantic import Field

from protolink.core.actions import RunAction
from protolink.core.execution import ToolExecution
from protolink.core.run_context import RunContext
from protolink.tools.prepared import PreparedTool
from protolink.utils.id_generator import IDGenerator

_Question = Annotated[str, Field(min_length=1, max_length=8000, description="A clear question for the user.")]
_Option = Annotated[str, Field(min_length=1, max_length=500)]
_Options = Annotated[
    list[_Option] | None,
    Field(max_length=10, description="Optional suggested answers (up to 10). The user may always enter free text."),
]


@dataclass(frozen=True)
class UserInputRequest:
    """One immutable question for an application callback.

    ``request_id`` uniquely correlates this question, including concurrent calls.
    ``run_id``, ``task_id``, and ``action_id`` associate it with runtime events;
    ``task_id`` is absent for standalone ``Agent.call_tool`` calls. Options are
    suggestions, never a restriction on free-text answers. IDs are correlation
    values, not credentials: UI adapters must authenticate and scope responders.
    """

    request_id: str
    question: str
    options: tuple[str, ...]
    run_id: str
    task_id: str | None
    action_id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-compatible question for an application UI."""
        return {**asdict(self), "options": list(self.options)}


@dataclass(frozen=True)
class UserInputResult:
    """Feedback returned to the model, with no invented answer on decline/timeout."""

    request_id: str
    status: Literal["answered", "declined", "timed_out"]
    answer: str | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize feedback for application rendering and diagnostics."""
        return asdict(self)


UserInputHandler = Callable[[UserInputRequest], Awaitable[str | None]]
"""Async callback returning a free-text answer, or ``None`` when the user declines."""


def ask_user_tool(
    handler: UserInputHandler,
    *,
    timeout_seconds: float = 300.0,
    max_answer_chars: int = 16384,
) -> PreparedTool:
    """Create ``ask_user(question, options=None)`` and continue with user feedback.

    Register on an Agent. The model's tool call awaits ``handler(request)`` and
    receives a ``UserInputResult`` in its ordinary tool history before the next
    inference step. The callback owns the terminal, web UI, or messaging adapter;
    this library never reads stdin or picks a default answer. Requires
    ``user.interact``. Feedback does not grant permission for other tool calls.

    Args:
        handler: Async callable accepting a ``UserInputRequest`` and returning
            nonblank text or ``None`` to decline. Options are suggestions and
            free text is always accepted. Exceptions propagate to tool execution.
            Release pending UI state in ``finally`` on cancellation or timeout.
        timeout_seconds: Positive finite wait limit in seconds. The run's
            remaining runtime budget may end the wait earlier.
        max_answer_chars: Positive maximum answer length; oversized answers are
            rejected, never silently truncated or coerced from other types.

    Returns:
        A fresh prepared tool with typed results and ``user_input.*`` events.
        Factory and callback must be reattached after loading Agent dict/YAML.

    Raises:
        TypeError: ``handler`` is not callable or does not return an awaitable.
        ValueError: Configuration, question/options, or returned answer is invalid.

    A question timeout returns ``status='timed_out'``; declining returns
    ``status='declined'``. Native cancellation propagates and run-budget expiry
    raises the existing budget exception. The task remains working while it
    waits: this is a live coroutine, not a durable suspended/restartable task.
    Questions and answers enter model history and runtime events; do not use
    this tool for password collection. Concurrent calls invoke independent
    callbacks, so terminal adapters should serialize their own prompts.
    """
    if not callable(handler):
        raise TypeError("handler must be an async callable")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if isinstance(max_answer_chars, bool) or not isinstance(max_answer_chars, int) or max_answer_chars <= 0:
        raise ValueError("max_answer_chars must be a positive integer")

    def ask_user(question: _Question, options: _Options = None) -> UserInputResult:
        """Ask the user a question and wait for feedback before continuing.

        Supply optional suggested answers; free text is always allowed. Use this
        for clarification or preferences. A declined or timed_out result contains
        no answer: do not treat it as consent or choose an option for the user.
        """
        raise AssertionError("Signature only")

    def prepare(arguments: dict[str, Any], context: RunContext) -> RunAction:
        question = arguments["question"].strip()
        options = [option.strip() for option in arguments.get("options") or []]
        if not question or "\x00" in question:
            raise ValueError("question must be nonblank and contain no NUL bytes")
        if any(not option or "\x00" in option for option in options) or len(options) != len(set(options)):
            raise ValueError("options must be distinct, nonblank strings without NUL bytes")
        return RunAction(
            kind="tool.call",
            name="ask_user",
            capabilities=frozenset({"user.interact"}),
            payload={"arguments": {"question": question, "options": options}},
        )

    async def execute(execution: ToolExecution) -> UserInputResult:
        execution.check()
        action = execution.authorization.action
        arguments = action.payload["arguments"]
        request = UserInputRequest(
            request_id=IDGenerator.generate_context_id(prefix="input_"),
            question=arguments["question"],
            options=tuple(arguments["options"]),
            run_id=execution.context.run_id,
            task_id=execution.task_id,
            action_id=action.action_id,
        )
        await execution.emit("user_input.requested", request=request.to_dict())
        remaining = execution.remaining_seconds
        timeout = min(timeout_seconds, remaining) if remaining is not None else timeout_seconds
        timer = asyncio.timeout(timeout)
        try:
            async with timer:
                execution.check()
                pending = handler(request)
                if not inspect.isawaitable(pending):
                    raise TypeError("user input handler must return an awaitable")
                answer = await pending
                execution.check()
                if answer is not None and (
                    not isinstance(answer, str) or not answer.strip() or len(answer) > max_answer_chars
                ):
                    raise ValueError("user answer must be nonblank text within max_answer_chars, or None to decline")
                result = UserInputResult(request.request_id, "declined" if answer is None else "answered", answer)
        except TimeoutError:
            # A callback's own TimeoutError is a failure, not our wait deadline.
            if not timer.expired():
                await execution.emit("user_input.failed", request_id=request.request_id)
                raise
            await execution.emit("user_input.timed_out", request_id=request.request_id)
            execution.check()  # Preserve native budget errors when the run expired first.
            return UserInputResult(request.request_id, "timed_out", None)
        except asyncio.CancelledError:
            await execution.emit("user_input.canceled", request_id=request.request_id)
            raise
        except Exception:
            await execution.emit("user_input.failed", request_id=request.request_id)
            raise
        await execution.emit(f"user_input.{result.status}", result=result.to_dict())
        return result

    tool = PreparedTool(ask_user, prepare=prepare, execute=execute, capabilities=("user.interact",))
    tool.tags = ["builtin", "user", "interaction"]
    tool.examples = [{"question": "Which output format do you prefer?", "options": ["JSON", "CSV"]}]
    return tool
