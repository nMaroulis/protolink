"""Opt-in typed answers and bounded validation repair using ordinary task execution."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from pydantic import TypeAdapter, ValidationError

from protolink.core.execution import emit_runtime_event, execution_scope
from protolink.core.invocation import prepare_task, response_content
from protolink.core.run_context import RunBudget, RunContext
from protolink.core.task import Task, TaskState
from protolink.models import Message

from .base import Flow
from .limits import merge_node_result, workflow_execution

ResponseT = TypeVar("ResponseT")


class StructuredResponseError(ValueError):
    """An answer was incomplete or invalid after the configured attempt limit.

    ``task`` retains execution evidence, ``attempts`` counts submissions, and
    ``validation_error`` holds Pydantic's final error (None for an incomplete task).
    """

    def __init__(self, task: Task, attempts: int, validation_error: ValidationError | None = None) -> None:
        self.task, self.attempts, self.validation_error = task, attempts, validation_error
        reason = str(validation_error) if validation_error is not None else f"Task is {task.state.value}"
        super().__init__(f"No valid structured response after {attempts} attempt(s): {reason}")


class _Submission(Flow):
    """Preserve the exact returned status; a submission is not a completed workflow step."""

    def __init__(self, submit: Callable[[Task], Awaitable[Task]]) -> None:
        super().__init__()
        self.submit = submit

    async def execute(self, task: Task) -> Task:
        return await self.submit(task)


class _TypedResponseFlow(Flow, Generic[ResponseT]):
    def __init__(
        self,
        submit: Callable[[Task], Awaitable[Task]],
        message: str,
        response_model: type[ResponseT],
        max_attempts: int,
    ) -> None:
        super().__init__()
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self.step = _Submission(submit)
        self.adapter: TypeAdapter[ResponseT] = TypeAdapter(response_model)
        self.prompt = message + "\n\nReturn only JSON matching this schema:\n" + json.dumps(self.adapter.json_schema())
        self.max_attempts = max_attempts
        self.value: ResponseT

    @workflow_execution
    async def execute(self, task: Task) -> Task:
        current = task
        for attempt in range(1, self.max_attempts + 1):
            request_ids = {item.id for item in (*current.messages, *current.artifacts)}
            current = (await self._execute_target(self.step, current)).raise_for_status()
            if current.state is not TaskState.COMPLETED:
                raise StructuredResponseError(current, attempt)
            item = current.get_last_item()
            if item is None or item.id in request_ids or not item.parts:
                raise StructuredResponseError(current, attempt)
            content = response_content(current, request_ids)
            try:
                if isinstance(content, str):
                    text = content.strip()
                    if text.startswith("```json\n") and text.endswith("```"):
                        text = text[8:-3].strip()
                    self.value = self.adapter.validate_json(text)
                else:
                    self.value = self.adapter.validate_python(content)
            except ValidationError as exc:
                with execution_scope(current):
                    await emit_runtime_event(
                        "response.validation",
                        RunContext.from_task(current),
                        attempt=attempt,
                        valid=False,
                    )
                merge_node_result(task, current)
                if attempt == self.max_attempts:
                    raise StructuredResponseError(current, attempt, exc) from exc
                current.add_message(
                    Message.infer(
                        prompt=self.prompt
                        + "\n\nCorrect your previous answer:\n"
                        + json.dumps(content, default=str)
                        + "\nValidation errors: "
                        + exc.json(include_input=False, include_url=False),
                        output_schema=self.adapter.json_schema(),
                    )
                )
            else:
                with execution_scope(current):
                    await emit_runtime_event(
                        "response.validation",
                        RunContext.from_task(current),
                        attempt=attempt,
                        valid=True,
                    )
                return current
        raise AssertionError("Unreachable: positive attempt limit always returns or raises")


async def invoke_typed(
    submit: Callable[[Task], Awaitable[Task]],
    message: str,
    response_model: type[ResponseT],
    *,
    max_attempts: int = 1,
    session_id: str | None = None,
    budget: RunBudget | None = None,
    context: RunContext | None = None,
) -> ResponseT:
    """Run typed-response validation under one bounded local workflow scope."""
    flow = _TypedResponseFlow(submit, message, response_model, max_attempts)
    schema = flow.adapter.json_schema()
    task = prepare_task(
        Task.create_infer(prompt=flow.prompt, output_schema=schema),
        session_id=session_id,
        budget=budget,
        context=context,
        default_session_id="invocation_session_id",
    )
    await flow.execute(task)
    return flow.value
