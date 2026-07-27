"""Translate between ProtoLink runtime objects and canonical A2A 1.0 JSON.

The conversion deliberately lives outside the core models.  ProtoLink's local runtime can evolve independently while
this module keeps the public A2A wire contract precise and testable.
"""

from __future__ import annotations

import base64
import copy
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from protolink.core.agent_card import AgentCard, AgentSkill
from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.core.task import Task, TaskState

A2A_PROTOCOL_VERSION = "1.0"
A2A_AGENT_CARD_PATH = "/.well-known/agent-card.json"
A2A_JSONRPC_BINDING = "JSONRPC"

_STATE_TO_A2A: dict[TaskState, str] = {
    TaskState.SUBMITTED: "TASK_STATE_SUBMITTED",
    TaskState.WORKING: "TASK_STATE_WORKING",
    TaskState.INPUT_REQUIRED: "TASK_STATE_INPUT_REQUIRED",
    TaskState.COMPLETED: "TASK_STATE_COMPLETED",
    TaskState.CANCELED: "TASK_STATE_CANCELED",
    TaskState.FAILED: "TASK_STATE_FAILED",
    TaskState.UNKNOWN: "TASK_STATE_UNSPECIFIED",
}

_STATE_FROM_A2A: dict[str, TaskState] = {
    "TASK_STATE_SUBMITTED": TaskState.SUBMITTED,
    "TASK_STATE_WORKING": TaskState.WORKING,
    "TASK_STATE_INPUT_REQUIRED": TaskState.INPUT_REQUIRED,
    "TASK_STATE_COMPLETED": TaskState.COMPLETED,
    "TASK_STATE_CANCELED": TaskState.CANCELED,
    "TASK_STATE_FAILED": TaskState.FAILED,
    # ProtoLink has no distinct rejected/auth-required states. Keep the exact
    # wire state in metadata while mapping to the closest local lifecycle state.
    "TASK_STATE_REJECTED": TaskState.FAILED,
    "TASK_STATE_AUTH_REQUIRED": TaskState.INPUT_REQUIRED,
    "TASK_STATE_UNSPECIFIED": TaskState.UNKNOWN,
}


def agent_card_to_a2a(
    card: AgentCard,
    *,
    interface_url: str | None = None,
    protocol_binding: str = A2A_JSONRPC_BINDING,
) -> dict[str, Any]:
    """Serialize an AgentCard using the A2A 1.0 Agent Card shape.

    Only interfaces implemented by this adapter are advertised.  ProtoLink's native ``card.interfaces`` remain part of
    its own discovery contract and must not be mistaken for standard A2A bindings.
    """

    capabilities: dict[str, Any] = {
        "streaming": False,
        "pushNotifications": False,
        "extendedAgentCard": False,
    }
    result: dict[str, Any] = {
        "name": card.name,
        "description": card.description,
        "supportedInterfaces": [
            {
                "url": (interface_url or card.url).strip(),
                "protocolBinding": protocol_binding,
                "protocolVersion": A2A_PROTOCOL_VERSION,
            }
        ],
        "version": card.version,
        "capabilities": capabilities,
        "defaultInputModes": list(card.input_formats),
        "defaultOutputModes": list(card.output_formats),
        "skills": [_skill_to_a2a(skill) for skill in card.skills],
    }
    if card.security_schemes:
        security_schemes, security_requirements = _security_to_a2a(card.security_schemes)
        if security_schemes:
            result["securitySchemes"] = security_schemes
            result["securityRequirements"] = security_requirements
    return result


def _security_to_a2a(
    schemes: Mapping[Any, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Translate ProtoLink/OpenAPI-style schemes to A2A 1.0 unions."""

    converted: dict[str, Any] = {}
    requirements: list[dict[str, Any]] = []
    canonical_members = {
        "apiKeySecurityScheme",
        "httpAuthSecurityScheme",
        "mtlsSecurityScheme",
        "oauth2SecurityScheme",
        "openIdConnectSecurityScheme",
    }

    for name, scheme in schemes.items():
        if not isinstance(scheme, Mapping):
            continue
        existing_member = canonical_members.intersection(scheme)
        if len(existing_member) == 1:
            wire_scheme = _json_value(scheme)
        else:
            scheme_type = scheme.get("type", name)
            description = _optional_text(scheme.get("description"))
            raw_metadata = scheme.get("metadata")
            metadata: Mapping[str, Any]
            if isinstance(raw_metadata, Mapping):
                metadata = raw_metadata
            else:
                metadata = {}

            if scheme_type in {"apiKey", "api_key"}:
                detail = {
                    "location": str(scheme.get("in") or scheme.get("location") or "header"),
                    "name": str(scheme.get("name") or "X-API-Key"),
                }
                if description:
                    detail["description"] = description
                wire_scheme = {"apiKeySecurityScheme": detail}
            elif scheme_type == "http":
                auth_scheme = _optional_text(scheme.get("scheme"))
                if not auth_scheme:
                    continue
                detail = {"scheme": auth_scheme}
                if description:
                    detail["description"] = description
                bearer_format = _optional_text(scheme.get("bearerFormat") or metadata.get("bearer_format"))
                if bearer_format:
                    detail["bearerFormat"] = bearer_format
                wire_scheme = {"httpAuthSecurityScheme": detail}
            elif scheme_type == "mutualTLS":
                detail = {"description": description} if description else {}
                wire_scheme = {"mtlsSecurityScheme": detail}
            elif scheme_type == "openIdConnect":
                discovery_url = _optional_text(
                    scheme.get("openIdConnectUrl")
                    or scheme.get("open_id_connect_url")
                    or metadata.get("open_id_connect_url")
                    or metadata.get("url")
                )
                if not discovery_url:
                    continue
                detail = {"openIdConnectUrl": discovery_url}
                if description:
                    detail["description"] = description
                wire_scheme = {"openIdConnectSecurityScheme": detail}
            elif scheme_type == "oauth2":
                flows = scheme.get("flows")
                if not isinstance(flows, Mapping):
                    exchange_endpoint = _optional_text(metadata.get("exchange_endpoint"))
                    if not exchange_endpoint:
                        continue
                    flows = {
                        "clientCredentials": {
                            "tokenUrl": exchange_endpoint,
                            "scopes": {},
                        }
                    }
                detail = {"flows": _json_value(flows)}
                if description:
                    detail["description"] = description
                metadata_url = _optional_text(scheme.get("oauth2MetadataUrl") or metadata.get("oauth2_metadata_url"))
                if metadata_url:
                    detail["oauth2MetadataUrl"] = metadata_url
                wire_scheme = {"oauth2SecurityScheme": detail}
            else:
                continue

        converted[str(name)] = wire_scheme
        requirements.append({"schemes": {str(name): {"list": []}}})

    return converted, requirements


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _skill_to_a2a(skill: AgentSkill) -> dict[str, Any]:
    """Convert ProtoLink's compact skill declaration to A2A 1.0."""

    tags = list(skill.tags) or [skill.id]
    result: dict[str, Any] = {
        "id": skill.id,
        "name": skill.id.replace("_", " ").replace("-", " ").title(),
        "description": skill.description or skill.id,
        # A2A requires at least one tag; the stable skill ID is the least
        # surprising fallback for ProtoLink's optional local tag list.
        "tags": tags,
    }
    string_examples = [example for example in skill.examples if isinstance(example, str)]
    if string_examples:
        result["examples"] = string_examples
    return result


def message_from_a2a(data: Mapping[str, Any]) -> Message:
    """Create an internal Message from an A2A 1.0 Message object.

    Validation of required fields is handled by the adapter before conversion. Unknown structured content remains
    available as a JSON part rather than being discarded.
    """

    role = "user" if data.get("role") == "ROLE_USER" else "agent"
    parts = [part_from_a2a(part) for part in data.get("parts", [])]
    return Message(id=str(data["messageId"]), role=role, parts=parts)


def message_to_a2a(
    message: Message,
    *,
    context_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Serialize an internal Message as an A2A 1.0 Message."""

    result: dict[str, Any] = {
        "messageId": message.id,
        "role": "ROLE_USER" if message.role == "user" else "ROLE_AGENT",
        "parts": [part_to_a2a(part) for part in message.parts],
    }
    if context_id:
        result["contextId"] = context_id
    if task_id:
        result["taskId"] = task_id
    return result


def part_from_a2a(data: Mapping[str, Any]) -> Part:
    """Translate a canonical A2A Part into a ProtoLink Part."""

    metadata = dict(data.get("metadata") or {})
    media_type = data.get("mediaType")
    filename = data.get("filename")
    if "text" in data:
        return Part.text(str(data["text"]))
    if "data" in data:
        return Part(type="json", content=data["data"])
    if "raw" in data:
        return Part(
            type="bytes",
            content={
                "raw": data["raw"],
                "filename": filename,
                "mediaType": media_type,
                "metadata": metadata,
            },
        )
    if "url" in data:
        return Part(
            type="uri",
            content={
                "url": data["url"],
                "filename": filename,
                "mediaType": media_type,
                "metadata": metadata,
            },
        )
    return Part(type="json", content=dict(data))


def part_to_a2a(part: Part) -> dict[str, Any]:
    """Translate a ProtoLink Part into one canonical A2A content member."""

    if part.type in {"text", "infer_output"}:
        return {"text": str(part.content)}
    if part.type == "infer":
        if isinstance(part.content, Mapping):
            prompt = part.content.get("prompt", part.content.get("user", ""))
        else:
            prompt = part.content
        return {"text": str(prompt or "")}
    if part.type == "json":
        return {"data": _json_value(part.content)}
    if part.type in {"bytes", "file"}:
        return _file_part_to_a2a(part.content, prefer_url=False)
    if part.type == "uri":
        return _file_part_to_a2a(part.content, prefer_url=True)
    return {
        "data": _json_value(part.content),
        "metadata": {"protolinkPartType": part.type},
    }


def _file_part_to_a2a(content: Any, *, prefer_url: bool) -> dict[str, Any]:
    if isinstance(content, Mapping):
        raw = content.get("raw")
        url = content.get("url") or content.get("uri")
        result: dict[str, Any]
        if prefer_url and url is not None:
            result = {"url": str(url)}
        elif raw is not None:
            result = {"raw": _base64_value(raw)}
        elif url is not None:
            result = {"url": str(url)}
        else:
            result = {"data": _json_value(content)}
        if content.get("filename"):
            result["filename"] = str(content["filename"])
        media_type = content.get("mediaType", content.get("media_type"))
        if media_type:
            result["mediaType"] = str(media_type)
        metadata = content.get("metadata")
        if isinstance(metadata, Mapping) and metadata:
            result["metadata"] = _json_value(metadata)
        return result
    if isinstance(content, bytes):
        return {"raw": base64.b64encode(content).decode("ascii")}
    if prefer_url:
        return {"url": str(content)}
    return {"raw": _base64_value(content)}


def artifact_to_a2a(artifact: Artifact) -> dict[str, Any]:
    """Serialize an internal Artifact as A2A 1.0."""

    result: dict[str, Any] = {
        "artifactId": artifact.id,
        "parts": [part_to_a2a(part) for part in artifact.parts],
    }
    if artifact.name:
        result["name"] = artifact.name
    if artifact.metadata:
        result["metadata"] = _json_value(artifact.metadata)
    return result


def artifact_from_a2a(data: Mapping[str, Any]) -> Artifact:
    """Deserialize one canonical A2A artifact into ProtoLink's runtime form."""

    return Artifact(
        id=str(data["artifactId"]),
        name=_optional_text(data.get("name")),
        parts=[part_from_a2a(part) for part in data.get("parts", [])],
        metadata=dict(data.get("metadata") or {}),
    )


def task_from_a2a(
    data: Mapping[str, Any],
    *,
    original: Task | None = None,
    remote_url: str | None = None,
) -> Task:
    """Translate an A2A task result while preserving a caller's local task ID.

    A2A servers assign their own task IDs. When ``original`` is supplied, the returned ProtoLink task keeps that local
    ID and records the remote ID and context in metadata for continuation and cancellation.
    """

    status = data.get("status")
    if not isinstance(status, Mapping):
        status = {}
    wire_state = str(status.get("state") or "TASK_STATE_UNSPECIFIED")
    state = _STATE_FROM_A2A.get(wire_state, TaskState.UNKNOWN)

    if original is None:
        task = Task(state=state)
    else:
        task = Task.from_dict(copy.deepcopy(original.to_dict()))
        task.state = state

    seen_message_ids = {message.id for message in task.messages}
    wire_messages: list[Mapping[str, Any]] = []
    history = data.get("history")
    if isinstance(history, list):
        wire_messages.extend(message for message in history if isinstance(message, Mapping))
    status_message = status.get("message")
    if isinstance(status_message, Mapping):
        wire_messages.append(status_message)
    for wire_message in wire_messages:
        message = message_from_a2a(wire_message)
        if message.id not in seen_message_ids:
            task.add_message(message)
            seen_message_ids.add(message.id)

    artifacts = data.get("artifacts")
    if isinstance(artifacts, list):
        artifact_indexes = {artifact.id: index for index, artifact in enumerate(task.artifacts)}
        for wire_artifact in artifacts:
            if not isinstance(wire_artifact, Mapping):
                continue
            artifact = artifact_from_a2a(wire_artifact)
            existing_index = artifact_indexes.get(artifact.id)
            if existing_index is None:
                task.add_artifact(artifact)
                artifact_indexes[artifact.id] = len(task.artifacts) - 1
            else:
                # A2A artifacts can be updated across task continuations. The
                # ID is stable, so replace stale partial output in place.
                task.artifacts[existing_index] = artifact

    task.metadata["a2a_remote_task_id"] = str(data["id"])
    if data.get("contextId") is not None:
        task.metadata["a2a_remote_context_id"] = str(data["contextId"])
    if remote_url:
        task.metadata["a2a_remote_agent_url"] = remote_url.rstrip("/")
    task.metadata["a2a_remote_state"] = wire_state
    if status.get("timestamp") is not None:
        task.metadata["a2a_remote_status_timestamp"] = str(status["timestamp"])
    if isinstance(data.get("metadata"), Mapping):
        task.metadata["a2a_remote_metadata"] = _json_value(data["metadata"])
    return task


def task_to_a2a(
    task: Task,
    *,
    history_length: int | None = None,
    include_artifacts: bool = True,
) -> dict[str, Any]:
    """Serialize a Task as the canonical A2A 1.0 Task object.

    ``ListTasks`` defaults ``includeArtifacts`` to false, while direct task operations return artifacts normally.
    Keeping that choice explicit here prevents the list adapter from constructing a second task serializer.
    """

    context_id = str(task.metadata.get("a2a_context_id") or task.id)
    history = task.messages
    if history_length is not None:
        history = [] if history_length <= 0 else history[-history_length:]

    status: dict[str, Any] = {
        "state": task_state_to_a2a(task),
        "timestamp": _utc_z(task_status_timestamp(task)),
    }
    latest_agent_message = next((message for message in reversed(task.messages) if message.role != "user"), None)
    if latest_agent_message is not None:
        status["message"] = message_to_a2a(
            latest_agent_message,
            context_id=context_id,
            task_id=task.id,
        )

    result: dict[str, Any] = {
        "id": task.id,
        "contextId": context_id,
        "status": status,
    }
    if history_length != 0 and history:
        result["history"] = [message_to_a2a(message, context_id=context_id, task_id=task.id) for message in history]
    if include_artifacts and task.artifacts:
        result["artifacts"] = [artifact_to_a2a(artifact) for artifact in task.artifacts]
    return result


def task_state_to_a2a(task: Task) -> str:
    """Return the canonical A2A enum name for a task's current state."""

    return _STATE_TO_A2A.get(task.state, "TASK_STATE_UNSPECIFIED")


def task_status_timestamp(task: Task) -> str:
    """Return the timestamp associated with a task's latest status."""

    history = task.metadata.get("state_history")
    if isinstance(history, list) and history:
        latest = history[-1]
        if isinstance(latest, Mapping) and latest.get("timestamp"):
            return str(latest["timestamp"])
    if task.messages:
        return task.messages[-1].timestamp
    return task.created_at


def _utc_z(value: str) -> str:
    if value.endswith("+00:00"):
        return value[:-6] + "Z"
    return value


def _base64_value(value: Any) -> str:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    text = str(value)
    try:
        base64.b64decode(text, validate=True)
    except Exception:
        return base64.b64encode(text.encode()).decode("ascii")
    return text


def _json_value(value: Any) -> Any:
    """Convert common runtime values to deterministic JSON-compatible data."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict"):
        return _json_value(value.to_dict())
    return str(value)
