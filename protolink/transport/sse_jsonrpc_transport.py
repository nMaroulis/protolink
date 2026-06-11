"""SSE JSON-RPC transport for streaming agent events over HTTP."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx

from protolink.transport.http_transport import HTTPTransport
from protolink.types import TransportType


class SSEJSONRPCTransport(HTTPTransport):
    """HTTP-compatible transport with Server-Sent Event streaming.

    Standard request/response calls use the same JSON HTTP behavior as
    :class:`HTTPTransport`. Streaming calls POST to ``/tasks/stream`` and
    consume ``text/event-stream`` frames where each ``data:`` payload is a
    JSON-RPC-style envelope.
    """

    transport_type: ClassVar[TransportType] = "sse"
    supports_streaming: ClassVar[bool] = True

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        """Stream events from a remote agent's ``/tasks/stream`` endpoint.

        The client sends a normal task payload with ``Accept: text/event-stream``
        and a request id header. The server replies with SSE ``data:`` frames
        containing JSON-RPC-style envelopes. This method validates the envelope,
        unwraps the ``result`` payload, and stops when an envelope is marked
        ``final``.
        """
        if self.authenticator and self.credentials and not self.security_context:
            await self.authenticate(self.credentials)

        client = await self._ensure_client()
        request_id = uuid.uuid4().hex
        headers = {
            **self._build_headers(),
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "X-Protolink-Request-ID": request_id,
        }
        payload = self._serialize_payload(task)
        url = f"{agent_url.rstrip('/')}/tasks/stream"

        try:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                event_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        result, final = self._parse_event(event_lines, agent_url, request_id)
                        if result is not None:
                            yield result
                        if final:
                            break
                        event_lines = []
                        continue
                    if line.startswith("data:"):
                        event_lines.append(line[5:].strip())

                result, _final = self._parse_event(event_lines, agent_url, request_id)
                if result is not None:
                    yield result
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"Failed to connect to agent at {agent_url}. Make sure the agent is running and accessible."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise RuntimeError(f"Agent at {agent_url} returned HTTP {status_code}: {exc.response.text}") from exc

    def _parse_event(self, event_lines: list[str], agent_url: str, request_id: str) -> tuple[Any | None, bool]:
        """Parse one SSE event block into ``(result, final)``.

        Empty event blocks are ignored. Non-empty blocks must contain JSON with
        the current request id, an ``ok`` flag, and either a ``result`` payload
        or an ``error`` object.
        """
        if not event_lines:
            return None, False

        raw = "\n".join(event_lines)
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid SSE JSON-RPC event from {agent_url}: {raw!r}") from exc

        message_id = message.get("id")
        if message_id not in {None, request_id}:
            raise RuntimeError(f"Mismatched SSE JSON-RPC event id from {agent_url}: {message_id}")

        if not message.get("ok", False):
            error = message.get("error") or {}
            raise RuntimeError(f"SSE JSON-RPC stream failed at {agent_url}: {error}")

        return message.get("result"), bool(message.get("final", False))

    def _serialize_payload(self, payload: Any) -> Any:
        """Convert Protolink domain objects into JSON-serializable payloads."""
        if hasattr(payload, "to_json"):
            return payload.to_json()
        if hasattr(payload, "to_dict"):
            return payload.to_dict()
        if hasattr(payload, "model_dump"):
            return payload.model_dump()
        return payload
