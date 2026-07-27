"""Outbound A2A 1.0 JSON-RPC translation for ProtoLink clients."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import urlsplit

from protolink.a2a.v1.serialization import (
    A2A_AGENT_CARD_PATH,
    A2A_JSONRPC_BINDING,
    A2A_PROTOCOL_VERSION,
    message_from_a2a,
    message_to_a2a,
    task_from_a2a,
)
from protolink.client.request_spec import ClientRequestSpec
from protolink.core.task import Task, TaskState
from protolink.transport import Transport


class A2AClientError(RuntimeError):
    """A typed error returned by, or detected at, an A2A boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass(frozen=True, slots=True)
class A2AInterface:
    """One discovered A2A JSON-RPC 1.0 interface."""

    url: str
    tenant: str | None = None


@dataclass(slots=True)
class _RemoteTask:
    interface: A2AInterface
    remote_id: str
    task: Task
    updated_at: float


class A2AJSONRPCClientAdapter:
    """Use an existing HTTP transport to call A2A 1.0 JSON-RPC agents.

    The adapter deliberately has no dependency on the official SDK. It reuses the configured ProtoLink transport so TLS,
    authentication, connection pooling, limits, and telemetry keep working exactly as they do for native requests.
    """

    _HEADERS: ClassVar[dict[str, str]] = {"A2A-Version": A2A_PROTOCOL_VERSION}
    _CARD_REQUEST = ClientRequestSpec(
        name="get_a2a_agent_card",
        path=A2A_AGENT_CARD_PATH,
        method="GET",
        request_source="none",
        accept="application/json",
        headers=_HEADERS,
        idempotent=True,
    )
    _JSONRPC_REQUEST = ClientRequestSpec(
        name="a2a_jsonrpc",
        path="",
        method="POST",
        request_source="body",
        content_type="application/json",
        accept="application/json",
        headers=_HEADERS,
        # A2A servers assign task IDs. Retrying SendMessage can therefore
        # create duplicate remote work and is intentionally forbidden.
        idempotent=False,
    )

    def __init__(
        self,
        transport: Transport,
        *,
        allow_cross_origin_interfaces: bool = False,
        _max_remote_tasks: int = 1024,
        _remote_task_ttl: float = 3600.0,
    ) -> None:
        if getattr(transport, "transport_type", None) != "http":
            raise ValueError("Outbound A2A 1.0 requires an HTTP transport")
        if _max_remote_tasks <= 0:
            raise ValueError("_max_remote_tasks must be greater than zero")
        if _remote_task_ttl <= 0:
            raise ValueError("_remote_task_ttl must be greater than zero")
        self._transport = transport
        self._allow_cross_origin_interfaces = bool(allow_cross_origin_interfaces)
        self._remote_tasks: dict[tuple[str, str], _RemoteTask] = {}
        self._max_remote_tasks = _max_remote_tasks
        self._remote_task_ttl = _remote_task_ttl

    async def discover(self, agent_url: str) -> tuple[Mapping[str, Any], A2AInterface]:
        """Fetch and validate the standard card, then select JSON-RPC 1.0."""

        payload = await self._transport.send(self._CARD_REQUEST, agent_url)
        if not isinstance(payload, Mapping):
            raise A2AClientError("A2A Agent Card response must be a JSON object")

        interfaces = payload.get("supportedInterfaces")
        if not isinstance(interfaces, list):
            raise A2AClientError("A2A Agent Card does not declare supportedInterfaces")

        for candidate in interfaces:
            if not isinstance(candidate, Mapping):
                continue
            binding = candidate.get("protocolBinding")
            version = candidate.get("protocolVersion")
            url = candidate.get("url")
            if binding == A2A_JSONRPC_BINDING and _is_v1(version) and isinstance(url, str) and url.strip():
                tenant_value = candidate.get("tenant")
                tenant = tenant_value if isinstance(tenant_value, str) and tenant_value else None
                interface_url = _validate_interface_url(
                    url,
                    discovery_url=agent_url,
                    allow_cross_origin=self._allow_cross_origin_interfaces,
                )
                return payload, A2AInterface(url=interface_url, tenant=tenant)

        raise A2AClientError("A2A Agent Card has no compatible JSONRPC 1.0 interface")

    async def send_task(
        self,
        agent_url: str,
        task: Task,
        *,
        interface: A2AInterface | None = None,
    ) -> Task:
        """Translate and send one ProtoLink task through A2A ``SendMessage``."""

        if interface is None:
            _, interface = await self.discover(agent_url)

        message = next((item for item in reversed(task.messages) if item.role == "user"), None)
        if message is None and task.messages:
            message = task.messages[-1]
        if message is None:
            raise ValueError("An A2A SendMessage task must contain at least one message")

        normalized_url = _normalize_url(agent_url)
        continuation = task.metadata.get("a2a_remote_agent_url") == normalized_url
        remote_task_id = task.metadata.get("a2a_remote_task_id") if continuation else None
        remote_context_id = task.metadata.get("a2a_remote_context_id") if continuation else None

        wire_message = message_to_a2a(
            message,
            context_id=str(remote_context_id) if remote_context_id else None,
            task_id=str(remote_task_id) if remote_task_id else None,
        )
        # Delegation is always a user request at the remote boundary, even when
        # a local orchestration message happened to use another role.
        wire_message["role"] = "ROLE_USER"

        params: dict[str, Any] = {
            "message": wire_message,
            "configuration": {"returnImmediately": False},
        }
        if interface.tenant:
            params["tenant"] = interface.tenant

        request_id = uuid.uuid4().hex
        result = await self._request(interface, "SendMessage", params, request_id=request_id)
        translated = self._translate_send_result(result, original=task, remote_url=normalized_url)
        remote_id = translated.metadata.get("a2a_remote_task_id")
        if remote_id:
            self._remote_tasks[(normalized_url, task.id)] = _RemoteTask(
                interface=interface,
                remote_id=str(remote_id),
                task=translated,
                updated_at=time.monotonic(),
            )
            self._prune_remote_tasks()
        return translated

    def has_task(self, agent_url: str, local_task_id: str) -> bool:
        """Return whether this client knows the remote ID for a local task."""

        self._prune_remote_tasks()
        return (_normalize_url(agent_url), local_task_id) in self._remote_tasks

    async def cancel_task(
        self,
        agent_url: str,
        local_task_id: str,
        *,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Task:
        """Cancel a previously returned A2A task using its remote task ID."""

        self._prune_remote_tasks()
        key = (_normalize_url(agent_url), local_task_id)
        remote = self._remote_tasks.get(key)
        if remote is None:
            raise A2AClientError(f"No A2A remote task ID is known for local task {local_task_id!r}")
        params: dict[str, Any] = {"id": remote.remote_id}
        if remote.interface.tenant:
            params["tenant"] = remote.interface.tenant
        wire_metadata = dict(metadata or {})
        if reason:
            wire_metadata.setdefault("reason", reason)
        if wire_metadata:
            params["metadata"] = wire_metadata
        result = await self._request(
            remote.interface,
            "CancelTask",
            params,
            request_id=uuid.uuid4().hex,
        )
        if not isinstance(result, Mapping) or not _looks_like_task(result):
            raise A2AClientError("A2A CancelTask result must be a Task")
        try:
            translated = task_from_a2a(
                result,
                original=remote.task,
                remote_url=key[0],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise A2AClientError("A2A CancelTask result is malformed") from exc
        remote.task = translated
        remote.updated_at = time.monotonic()
        self._prune_remote_tasks()
        return translated

    def _prune_remote_tasks(self) -> None:
        """Bound process-local task-ID mappings used for continuation/cancel."""

        now = time.monotonic()
        expired = [
            key for key, remote in self._remote_tasks.items() if now - remote.updated_at >= self._remote_task_ttl
        ]
        for key in expired:
            self._remote_tasks.pop(key, None)
        while len(self._remote_tasks) > self._max_remote_tasks:
            oldest = min(self._remote_tasks, key=lambda key: self._remote_tasks[key].updated_at)
            self._remote_tasks.pop(oldest, None)

    async def _request(
        self,
        interface: A2AInterface,
        method: str,
        params: Mapping[str, Any],
        *,
        request_id: str,
    ) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        response = await self._transport.send(
            self._JSONRPC_REQUEST,
            interface.url,
            data=payload,
        )
        if not isinstance(response, Mapping):
            raise A2AClientError("A2A JSON-RPC response must be a JSON object")
        if response.get("jsonrpc") != "2.0":
            raise A2AClientError("A2A response has an invalid JSON-RPC version")
        if response.get("id") != request_id:
            raise A2AClientError("A2A response ID does not match the request")

        has_result = "result" in response
        has_error = "error" in response
        if has_result == has_error:
            raise A2AClientError("A2A response must contain exactly one of result or error")
        if has_error:
            error = response["error"]
            if not isinstance(error, Mapping):
                raise A2AClientError("A2A JSON-RPC error must be an object")
            code_value = error.get("code")
            code = code_value if isinstance(code_value, int) and not isinstance(code_value, bool) else None
            message = str(error.get("message") or "A2A request failed")
            raise A2AClientError(message, code=code, data=error.get("data"))
        return response["result"]

    @staticmethod
    def _translate_send_result(
        result: Any,
        *,
        original: Task,
        remote_url: str,
    ) -> Task:
        if not isinstance(result, Mapping):
            raise A2AClientError("A2A SendMessage result must be an object")
        has_task = "task" in result
        has_message = "message" in result
        if has_task == has_message:
            raise A2AClientError("A2A SendMessage result must contain exactly one of task or message")

        if has_task:
            wire_task = result["task"]
            if not isinstance(wire_task, Mapping) or not _looks_like_task(wire_task):
                raise A2AClientError("A2A SendMessage task result is malformed")
            try:
                return task_from_a2a(wire_task, original=original, remote_url=remote_url)
            except (KeyError, TypeError, ValueError) as exc:
                raise A2AClientError("A2A SendMessage task result is malformed") from exc

        wire_message = result["message"]
        if not isinstance(wire_message, Mapping) or not _looks_like_message(wire_message):
            raise A2AClientError("A2A SendMessage message result is malformed")
        task = Task.from_dict(copy.deepcopy(original.to_dict()))
        try:
            message = message_from_a2a(wire_message)
        except (KeyError, TypeError, ValueError) as exc:
            raise A2AClientError("A2A SendMessage message result is malformed") from exc
        if all(existing.id != message.id for existing in task.messages):
            task.add_message(message)
        task.state = TaskState.COMPLETED
        task.metadata["a2a_remote_agent_url"] = remote_url
        task.metadata["a2a_remote_state"] = "TASK_STATE_COMPLETED"
        if wire_message.get("taskId") is not None:
            task.metadata["a2a_remote_task_id"] = str(wire_message["taskId"])
        if wire_message.get("contextId") is not None:
            task.metadata["a2a_remote_context_id"] = str(wire_message["contextId"])
        return task


def _is_v1(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return ".".join(value.split(".")[:2]) == A2A_PROTOCOL_VERSION


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _validate_interface_url(
    url: str,
    *,
    discovery_url: str,
    allow_cross_origin: bool,
) -> str:
    """Validate an advertised endpoint before the transport sends credentials."""

    interface_url = url.strip()
    interface_origin = _http_origin(interface_url, label="A2A interface URL")
    discovery_origin = _http_origin(discovery_url.strip(), label="A2A discovery URL")
    if not allow_cross_origin and interface_origin != discovery_origin:
        raise A2AClientError(
            "A2A Agent Card advertised a cross-origin interface; construct "
            "AgentClient(..., a2a_allow_cross_origin=True) only when that endpoint is trusted"
        )
    return interface_url


def _http_origin(url: str, *, label: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise A2AClientError(f"{label} is not a valid URL") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise A2AClientError(f"{label} must be an absolute HTTP(S) URL without user information")
    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    return scheme, parsed.hostname.lower(), effective_port


def _looks_like_message(value: Mapping[str, Any]) -> bool:
    return (
        isinstance(value.get("messageId"), str)
        and value.get("role") in {"ROLE_USER", "ROLE_AGENT"}
        and isinstance(value.get("parts"), list)
    )


def _looks_like_task(value: Mapping[str, Any]) -> bool:
    status = value.get("status")
    context_id = value.get("contextId")
    return (
        isinstance(value.get("id"), str)
        and ("contextId" not in value or isinstance(context_id, str))
        and isinstance(status, Mapping)
        and isinstance(status.get("state"), str)
    )
