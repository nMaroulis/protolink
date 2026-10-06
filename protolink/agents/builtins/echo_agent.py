"""Deterministic echo utility for transport, streaming and delegation checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

from protolink.agents.base import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.cancellation import CancellationToken
from protolink.core.events import TaskStatusUpdateEvent
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.core.task import Task, TaskState


class EchoAgent(Agent):
    """Echo the latest task item without model inference or tool execution.

    ``invoke(text)`` returns text verbatim, including whitespace and empty strings.
    Inference parts become infer_output containing their prompt (or user text);
    other parts are copied into a new agent message. Executable parts are echoed,
    never dispatched. Inherited lifecycle, transport and cancellation still apply.
    Streams emit working/completed status events with the echoed task attached.
    This utility has no conversation reasoning and requires no LLM.
    """

    def __init__(self, card: AgentCard | dict[str, Any] | None = None, **agent_options: Any) -> None:
        if card is None:
            agent_options.setdefault("name", "echo")
            agent_options.setdefault("description", "Deterministic echo agent")
        super().__init__(card=card, **agent_options)

    async def _execute_task_impl(self, task: Task, cancellation_token: CancellationToken) -> Task:
        self._raise_if_execution_canceled(task, cancellation_token)
        if self._begin_task_if_needed(task) is None:
            return task
        item = task.get_last_item()
        if item is not None:
            parts = []
            for part in item.parts:
                if part.type == "infer":
                    payload = part.content
                    text = payload.get("prompt", payload.get("user", "")) if isinstance(payload, dict) else payload
                    parts.append(Part.infer_output(content=deepcopy(text)))
                else:
                    parts.append(Part.from_dict(deepcopy(part.to_dict())))
            task.add_message(Message(role="agent", parts=parts))
        task.update_state(TaskState.COMPLETED)
        self._persist_task_snapshot(task)
        return task

    async def _handle_task_streaming_impl(
        self, task: Task, cancellation_token: CancellationToken
    ) -> AsyncIterator[TaskStatusUpdateEvent]:
        self._raise_if_execution_canceled(task, cancellation_token)
        previous = task.state.value
        if not task.is_terminal:
            task.begin()
            yield TaskStatusUpdateEvent(task_id=task.id, previous_state=previous, new_state=task.state.value)
            previous = task.state.value
            await self._execute_task_impl(task, cancellation_token)
        yield TaskStatusUpdateEvent(
            task_id=task.id,
            previous_state=previous,
            new_state=task.state.value,
            final=True,
            metadata={"task": task.to_dict()},
        )
