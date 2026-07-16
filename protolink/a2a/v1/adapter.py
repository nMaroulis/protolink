"""A2A 1.0 JSON-RPC adapter for a ProtoLink Agent.

The adapter owns protocol validation, wire translation, and the minimal task
index required by A2A task operations.  Agent authors still implement the same
``handle_task(Task)`` method and do not need A2A-specific business logic.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from protolink.a2a.v1.serialization import (
    A2A_PROTOCOL_VERSION,
    agent_card_to_a2a,
    message_from_a2a,
    message_to_a2a,
    task_state_to_a2a,
    task_status_timestamp,
    task_to_a2a,
)
from protolink.core.agent_card import AgentCard
from protolink.core.cancellation import (
    TaskCancellationRequest,
    TaskNotCancelableError,
    TaskNotFoundError,
)
from protolink.core.task import Task
from protolink.server.endpoint_handler import EndpointRequest


class _Agent(Protocol):
    card: AgentCard

    async def run_task(self, task: Task) -> Task: ...

    async def cancel_task(self, request: TaskCancellationRequest) -> Task: ...


class _A2AError(Exception):
    def __init__(self, code: int, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason


class A2AJSONRPCAdapter:
    """Expose one ProtoLink agent through the standard A2A 1.0 JSON-RPC binding."""

    def __init__(
        self,
        agent: _Agent,
        *,
        _max_tasks: int = 1024,
        _task_ttl: float = 3600.0,
        _clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if _max_tasks <= 0:
            raise ValueError("_max_tasks must be greater than zero")
        if _task_ttl <= 0:
            raise ValueError("_task_ttl must be greater than zero")
        self._agent = agent
        self._tasks: dict[str, Task] = {}
        self._task_updated_at: dict[str, float] = {}
        self._active_tasks: dict[str, int] = {}
        self._executions: dict[str, asyncio.Task[Task]] = {}
        self._max_tasks = _max_tasks
        self._task_ttl = _task_ttl
        self._clock = _clock
        self._lock = asyncio.Lock()

    def get_agent_card(self) -> dict[str, Any]:
        """Return the public A2A 1.0 Agent Card for this adapter."""

        return agent_card_to_a2a(self._agent.card)

    def _activate_task_locked(self, task_id: str) -> None:
        """Protect one task from retention pruning while an operation runs."""

        self._active_tasks[task_id] = self._active_tasks.get(task_id, 0) + 1

    def _deactivate_task_locked(self, task_id: str) -> None:
        """Release one active-operation reference for a retained task."""

        remaining = self._active_tasks.get(task_id, 0) - 1
        if remaining > 0:
            self._active_tasks[task_id] = remaining
        else:
            self._active_tasks.pop(task_id, None)

    def _touch_task_locked(self, task_id: str) -> None:
        """Record a task mutation without treating reads as retention activity."""

        self._task_updated_at[task_id] = self._clock()

    def _remove_task_locked(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)
        self._task_updated_at.pop(task_id, None)

    def _prune_tasks_locked(self, *, reserve: int = 0) -> bool:
        """Expire and size-bound inactive tasks while preserving live work.

        ``reserve`` requests free slots for an imminent insertion.  ``False``
        means every remaining slot is protected by an active operation.
        """

        now = self._clock()
        expired = [
            task_id
            for task_id, updated_at in self._task_updated_at.items()
            if task_id not in self._active_tasks and now - updated_at >= self._task_ttl
        ]
        for task_id in expired:
            self._remove_task_locked(task_id)

        target_size = self._max_tasks - reserve
        while len(self._tasks) > target_size:
            candidates = [
                (self._task_updated_at.get(task_id, float("-inf")), task_id)
                for task_id in self._tasks
                if task_id not in self._active_tasks
            ]
            if not candidates:
                return False
            _, oldest_task_id = min(candidates)
            self._remove_task_locked(oldest_task_id)
        return True

    async def close(self) -> None:
        """Cancel and drain non-blocking executions owned by this adapter."""

        executions = list(self._executions.items())
        for task_id, execution in executions:
            task = self._tasks.get(task_id)
            if task is not None and not task.is_terminal:
                task.cancel("A2A adapter stopped")
            if not execution.done():
                execution.cancel("A2A adapter stopped")
        if executions:
            await asyncio.gather(
                *(execution for _, execution in executions),
                return_exceptions=True,
            )

    async def handle(self, request: EndpointRequest) -> dict[str, Any]:
        """Handle one A2A JSON-RPC 2.0 request."""

        payload = request.body
        request_id = payload.get("id") if isinstance(payload, Mapping) else None
        try:
            self._validate_content_type(request.headers)
            self._validate_version(request.headers)
            method, params = self._validate_request(payload)
            result = await self._dispatch(
                method,
                params,
                principal_id=request.principal_id,
            )
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except _A2AError as exc:
            return self._error_response(request_id, exc)
        except Exception as exc:  # keep protocol errors on the wire, never an HTML 500
            return self._error_response(
                request_id,
                _A2AError(-32603, f"Internal error: {exc}"),
            )

    def _validate_version(self, headers: Mapping[str, str]) -> None:
        version = _header(headers, "a2a-version")
        if version == A2A_PROTOCOL_VERSION:
            return
        if version is None or version == "":
            raise _A2AError(
                -32009,
                "A2A protocol version 0.3 is not supported by this interface",
                "VERSION_NOT_SUPPORTED",
            )
        major_minor = ".".join(version.split(".")[:2])
        if major_minor != A2A_PROTOCOL_VERSION:
            raise _A2AError(
                -32009,
                f"A2A protocol version {version!r} is not supported",
                "VERSION_NOT_SUPPORTED",
            )

    @staticmethod
    def _validate_content_type(headers: Mapping[str, str]) -> None:
        content_type = (_header(headers, "content-type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise _A2AError(
                -32005,
                f"Content type {content_type or '<missing>'!r} is not supported",
                "CONTENT_TYPE_NOT_SUPPORTED",
            )

    @staticmethod
    def _validate_request(payload: Any) -> tuple[str, Mapping[str, Any]]:
        if not isinstance(payload, Mapping):
            raise _A2AError(-32700, "Parse error")
        if payload.get("jsonrpc") != "2.0" or "method" not in payload:
            raise _A2AError(-32600, "Invalid JSON-RPC request")
        method = payload.get("method")
        params = payload.get("params", {})
        if not isinstance(method, str):
            raise _A2AError(-32600, "JSON-RPC method must be a string")
        if not isinstance(params, Mapping):
            raise _A2AError(-32602, "JSON-RPC params must be an object")
        return method, params

    async def _dispatch(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        principal_id: str | None,
    ) -> Any:
        if method == "SendMessage":
            return await self._send_message(params, principal_id=principal_id)
        if method == "GetTask":
            return await self._get_task(params, principal_id=principal_id)
        if method == "ListTasks":
            return await self._list_tasks(params, principal_id=principal_id)
        if method == "CancelTask":
            return await self._cancel_task(params, principal_id=principal_id)
        if method == "SendStreamingMessage" or method == "SubscribeToTask":
            raise _A2AError(-32004, f"{method} is not enabled", "UNSUPPORTED_OPERATION")
        if method.startswith(("CreateTaskPush", "GetTaskPush", "ListTaskPush", "DeleteTaskPush")):
            raise _A2AError(
                -32003,
                "Push notifications are not enabled",
                "PUSH_NOTIFICATION_NOT_SUPPORTED",
            )
        if method == "GetExtendedAgentCard":
            raise _A2AError(-32004, "Extended Agent Card is not enabled", "UNSUPPORTED_OPERATION")
        raise _A2AError(-32601, f"Method not found: {method}")

    async def _send_message(
        self,
        params: Mapping[str, Any],
        *,
        principal_id: str | None,
    ) -> dict[str, Any]:
        wire_message = params.get("message")
        self._validate_message(wire_message)
        assert isinstance(wire_message, Mapping)

        configuration = self._validate_send_configuration(params.get("configuration"))
        request_metadata = params.get("metadata")
        if request_metadata is not None and not isinstance(request_metadata, Mapping):
            raise _A2AError(-32602, "metadata must be an object")
        tenant = _optional_string(params.get("tenant"))
        task_id = _optional_string(wire_message.get("taskId"))
        requested_context_id = _optional_string(wire_message.get("contextId"))
        history_length = _history_length(_value(configuration, "historyLength", "history_length"))
        return_immediately = _optional_bool(
            _value(configuration, "returnImmediately", "return_immediately"),
            default=False,
        )

        async with self._lock:
            self._prune_tasks_locked()
            if task_id:
                task = self._tasks.get(task_id)
                if task is None or not _is_visible(task, principal_id, tenant):
                    raise _A2AError(-32001, f"Task {task_id!r} was not found", "TASK_NOT_FOUND")
                context_id = str(task.metadata["a2a_context_id"])
                if requested_context_id and requested_context_id != context_id:
                    raise _A2AError(-32602, "Message contextId does not match the task")
                if task.is_terminal:
                    raise _A2AError(
                        -32004,
                        f"Task {task_id!r} is terminal and cannot accept messages",
                        "UNSUPPORTED_OPERATION",
                    )
                # Both blocking and returnImmediately executions hold an
                # active-operation reference.  `_executions` contains only
                # background jobs, so consulting it alone would allow a
                # continuation to mutate a blocking task concurrently.
                if self._active_tasks.get(task_id, 0) > 0:
                    raise _A2AError(
                        -32004,
                        f"Task {task_id!r} is already being processed",
                        "UNSUPPORTED_OPERATION",
                    )
                task.add_message(message_from_a2a(wire_message))
                task.metadata["a2a_message_id"] = str(wire_message["messageId"])
                task.metadata["a2a_inbound"] = True
                self._touch_task_locked(task.id)
            else:
                if not self._prune_tasks_locked(reserve=1):
                    raise _A2AError(-32603, "A2A task capacity is exhausted; retry later")
                context_id = requested_context_id or f"ctx-{uuid.uuid4()}"
                task = Task.create(message_from_a2a(wire_message))
                task.metadata["a2a_context_id"] = context_id
                task.metadata["a2a_message_id"] = str(wire_message["messageId"])
                task.metadata["a2a_inbound"] = True
                task.metadata["a2a_principal_id"] = principal_id
                task.metadata["a2a_tenant"] = tenant
                self._tasks[task.id] = task
                self._touch_task_locked(task.id)
            self._activate_task_locked(task.id)

        if return_immediately:
            self._start_execution(task)
            return {
                "task": task_to_a2a(
                    task,
                    history_length=history_length,
                )
            }

        completed = await self._run_and_store(task)
        if completed.metadata.get("a2a_response_kind") == "message":
            response = next(
                (message for message in reversed(completed.messages) if message.role != "user"),
                None,
            )
            if response is None:
                raise _A2AError(-32006, "Agent requested a direct response without a message", "INVALID_AGENT_RESPONSE")
            return {
                "message": message_to_a2a(
                    response,
                    context_id=context_id,
                )
            }
        return {"task": task_to_a2a(completed, history_length=history_length)}

    def _start_execution(self, task: Task) -> None:
        """Start one retained background execution for non-blocking mode."""

        execution = asyncio.create_task(
            self._run_and_store(task, suppress_cancellation=True),
            name=f"protolink-a2a-{task.id}",
        )
        self._executions[task.id] = execution
        execution.add_done_callback(lambda completed, task_id=task.id: self._forget_execution(task_id, completed))

    def _forget_execution(self, task_id: str, execution: asyncio.Task[Task]) -> None:
        if self._executions.get(task_id) is execution:
            self._executions.pop(task_id, None)

    async def _run_and_store(
        self,
        task: Task,
        *,
        suppress_cancellation: bool = False,
    ) -> Task:
        """Run an agent task and keep the adapter's process-local index current."""

        completed = task
        try:
            try:
                completed = await self._agent.run_task(task)
            except asyncio.CancelledError:
                if not task.is_terminal:
                    task.cancel("Canceled through A2A")
                completed = task
                if not suppress_cancellation:
                    raise
            except Exception as exc:
                if not task.is_terminal:
                    task.fail(str(exc))
                completed = task

            if completed.id != task.id:
                if not suppress_cancellation:
                    raise _A2AError(
                        -32006,
                        "Agent returned a task with a different id",
                        "INVALID_AGENT_RESPONSE",
                    )
                if not task.is_terminal:
                    task.fail("Agent returned a task with a different id")
                completed = task
            completed.metadata.setdefault("a2a_context_id", task.metadata["a2a_context_id"])
            return completed
        finally:
            retained = completed if completed.id == task.id else task
            async with self._lock:
                self._tasks[task.id] = retained
                self._touch_task_locked(task.id)
                self._deactivate_task_locked(task.id)
                self._prune_tasks_locked()

    def _validate_send_configuration(self, value: Any) -> Mapping[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise _A2AError(-32602, "configuration must be an object")

        accepted_modes = _value(value, "acceptedOutputModes", "accepted_output_modes")
        if accepted_modes is not None and (
            not isinstance(accepted_modes, list)
            or any(not isinstance(mode, str) or not mode for mode in accepted_modes)
        ):
            raise _A2AError(-32602, "configuration.acceptedOutputModes must be a list of media types")

        push_config = _value(
            value,
            "taskPushNotificationConfig",
            "task_push_notification_config",
        )
        if push_config is not None:
            raise _A2AError(
                -32003,
                "Push notifications are not enabled",
                "PUSH_NOTIFICATION_NOT_SUPPORTED",
            )

        _history_length(_value(value, "historyLength", "history_length"))
        _optional_bool(
            _value(value, "returnImmediately", "return_immediately"),
            default=False,
        )
        return value

    async def _get_task(
        self,
        params: Mapping[str, Any],
        *,
        principal_id: str | None,
    ) -> dict[str, Any]:
        task_id = _required_string(params, "id")
        tenant = _optional_string(params.get("tenant"))
        history_length = _history_length(_value(params, "historyLength", "history_length"))
        async with self._lock:
            self._prune_tasks_locked()
            task = self._tasks.get(task_id)
        if task is None or not _is_visible(task, principal_id, tenant):
            raise _A2AError(-32001, f"Task {task_id!r} was not found", "TASK_NOT_FOUND")
        return task_to_a2a(task, history_length=history_length)

    async def _list_tasks(
        self,
        params: Mapping[str, Any],
        *,
        principal_id: str | None,
    ) -> dict[str, Any]:
        tenant = _optional_string(params.get("tenant"))
        context_id = _optional_string(_value(params, "contextId", "context_id"))
        history_length = _history_length(_value(params, "historyLength", "history_length"))
        page_size = _page_size(_value(params, "pageSize", "page_size"))
        offset = _page_offset(_value(params, "pageToken", "page_token"))
        include_artifacts = _optional_bool(
            _value(params, "includeArtifacts", "include_artifacts"),
            default=False,
        )
        requested_status = _optional_string(params.get("status"))
        valid_statuses = {
            "TASK_STATE_UNSPECIFIED",
            "TASK_STATE_SUBMITTED",
            "TASK_STATE_WORKING",
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_REJECTED",
            "TASK_STATE_AUTH_REQUIRED",
        }
        if requested_status is not None and requested_status not in valid_statuses:
            raise _A2AError(-32602, f"Unsupported task status {requested_status!r}")

        status_after_value = _value(
            params,
            "statusTimestampAfter",
            "status_timestamp_after",
        )
        status_after = _timestamp(status_after_value) if status_after_value is not None else None

        async with self._lock:
            self._prune_tasks_locked()
            tasks = [task for task in self._tasks.values() if _is_visible(task, principal_id, tenant)]
        if context_id:
            tasks = [task for task in tasks if task.metadata.get("a2a_context_id") == context_id]
        if requested_status and requested_status != "TASK_STATE_UNSPECIFIED":
            tasks = [task for task in tasks if task_state_to_a2a(task) == requested_status]
        if status_after is not None:
            tasks = [task for task in tasks if _timestamp(task_status_timestamp(task), internal=True) >= status_after]
        tasks.sort(
            key=lambda task: (
                _timestamp(task_status_timestamp(task), internal=True),
                task.id,
            ),
            reverse=True,
        )
        selected = tasks[offset : offset + page_size]
        next_offset = offset + len(selected)
        return {
            "tasks": [
                task_to_a2a(
                    task,
                    history_length=history_length,
                    include_artifacts=include_artifacts,
                )
                for task in selected
            ],
            "totalSize": len(tasks),
            "pageSize": page_size,
            "nextPageToken": str(next_offset) if next_offset < len(tasks) else "",
        }

    async def _cancel_task(
        self,
        params: Mapping[str, Any],
        *,
        principal_id: str | None,
    ) -> dict[str, Any]:
        task_id = _required_string(params, "id")
        tenant = _optional_string(params.get("tenant"))
        wire_metadata = params.get("metadata")
        if wire_metadata is not None and not isinstance(wire_metadata, Mapping):
            raise _A2AError(-32602, "metadata must be an object")
        cancellation_metadata = dict(wire_metadata or {})
        requested_reason = cancellation_metadata.get("reason")
        reason = requested_reason if isinstance(requested_reason, str) and requested_reason else "Canceled through A2A"
        async with self._lock:
            self._prune_tasks_locked()
            task = self._tasks.get(task_id)
            if task is None or not _is_visible(task, principal_id, tenant):
                raise _A2AError(-32001, f"Task {task_id!r} was not found", "TASK_NOT_FOUND")
            if task.is_terminal:
                raise _A2AError(
                    -32002,
                    f"Task {task_id!r} is not cancelable",
                    "TASK_NOT_CANCELABLE",
                )
            self._activate_task_locked(task_id)

        canceled: Task | None = None
        try:
            try:
                result = await self._agent.cancel_task(
                    TaskCancellationRequest(
                        id=task_id,
                        reason=reason,
                        metadata=cancellation_metadata,
                    )
                )
            except TaskNotCancelableError as exc:
                raise _A2AError(-32002, str(exc), "TASK_NOT_CANCELABLE") from exc
            except TaskNotFoundError:
                result = task

            canceled = result if isinstance(result, Task) else task
            if not canceled.is_terminal:
                canceled.cancel(reason)

            execution = self._executions.get(task_id)
            if execution is not None and not execution.done():
                execution.cancel(reason)
            return task_to_a2a(canceled)
        finally:
            async with self._lock:
                if canceled is not None:
                    self._tasks[task_id] = canceled
                    self._touch_task_locked(task_id)
                self._deactivate_task_locked(task_id)
                self._prune_tasks_locked()

    def _validate_message(self, value: Any) -> None:
        if not isinstance(value, Mapping):
            raise _A2AError(-32602, "SendMessage requires a message object")
        if not isinstance(value.get("messageId"), str) or not value["messageId"].strip():
            raise _A2AError(-32602, "message.messageId is required")
        if value.get("role") not in {"ROLE_USER", "ROLE_AGENT"}:
            raise _A2AError(-32602, "message.role must be ROLE_USER or ROLE_AGENT")
        _optional_string(value.get("taskId"))
        _optional_string(value.get("contextId"))
        metadata = value.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise _A2AError(-32602, "message.metadata must be an object")
        _optional_string_list(value.get("extensions"), "message.extensions")
        _optional_string_list(value.get("referenceTaskIds"), "message.referenceTaskIds")
        parts = value.get("parts")
        if not isinstance(parts, list) or not parts:
            raise _A2AError(-32602, "message.parts must contain at least one part")
        supported_modes = set(self._agent.card.input_formats)
        for part in parts:
            if not isinstance(part, Mapping):
                raise _A2AError(-32602, "Each message part must be an object")
            content_fields = {"text", "data", "raw", "url"}.intersection(part)
            if len(content_fields) != 1:
                raise _A2AError(-32602, "Each message part must contain exactly one content field")
            content_field = next(iter(content_fields))
            if content_field in {"text", "raw", "url"} and not isinstance(part[content_field], str):
                raise _A2AError(-32602, f"part.{content_field} must be a string")
            if part.get("filename") is not None and not isinstance(part["filename"], str):
                raise _A2AError(-32602, "part.filename must be a string")
            if part.get("metadata") is not None and not isinstance(part["metadata"], Mapping):
                raise _A2AError(-32602, "part.metadata must be an object")
            media_type = part.get("mediaType", _default_media_type(content_fields))
            if media_type is not None and not isinstance(media_type, str):
                raise _A2AError(-32602, "part.mediaType must be a string")
            if media_type and media_type not in supported_modes:
                raise _A2AError(
                    -32005,
                    f"Content type {media_type!r} is not supported",
                    "CONTENT_TYPE_NOT_SUPPORTED",
                )

    @staticmethod
    def _error_response(request_id: Any, exc: _A2AError) -> dict[str, Any]:
        error: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.reason:
            error["data"] = [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": exc.reason,
                    "domain": "a2a-protocol.org",
                }
            ]
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    return next((value for key, value in headers.items() if key.lower() == lowered), None)


def _is_visible(
    task: Task,
    principal_id: str | None,
    tenant: str | None,
) -> bool:
    return task.metadata.get("a2a_principal_id") == principal_id and task.metadata.get("a2a_tenant") == tenant


def _required_string(params: Mapping[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _A2AError(-32602, f"{name} must be a non-empty string")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _A2AError(-32602, "Expected a string")
    return value


def _optional_string_list(value: Any, name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _A2AError(-32602, f"{name} must be a list of strings")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _A2AError(-32602, "Expected an integer")
    return value


def _history_length(value: Any) -> int | None:
    length = _optional_int(value)
    if length is not None and length < 0:
        raise _A2AError(-32602, "historyLength must be zero or greater")
    return length


def _page_size(value: Any) -> int:
    size = _optional_int(value)
    if size is None:
        return 50
    if not 1 <= size <= 100:
        raise _A2AError(-32602, "pageSize must be between 1 and 100")
    return size


def _page_offset(value: Any) -> int:
    if value is None or value == "":
        return 0
    if not isinstance(value, str):
        raise _A2AError(-32602, "pageToken must be a string")
    try:
        offset = int(value)
    except ValueError as exc:
        raise _A2AError(-32602, "pageToken is not valid") from exc
    if offset < 0:
        raise _A2AError(-32602, "pageToken is not valid")
    return offset


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _A2AError(-32602, "Expected a boolean")
    return value


def _value(values: Mapping[str, Any], camel: str, snake: str) -> Any:
    if camel in values:
        return values[camel]
    if snake in values:
        return values[snake]
    return None


def _timestamp(value: Any, *, internal: bool = False) -> datetime:
    if not isinstance(value, str) or not value:
        raise _A2AError(-32602, "statusTimestampAfter must be an ISO 8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _A2AError(-32602, "statusTimestampAfter must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        if not internal:
            raise _A2AError(-32602, "statusTimestampAfter must include a timezone")
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_media_type(content_fields: set[str]) -> str | None:
    if "text" in content_fields:
        return "text/plain"
    if "data" in content_fields:
        return "application/json"
    return None
