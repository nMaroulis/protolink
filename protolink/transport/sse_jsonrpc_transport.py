"""SSE JSON-RPC transport for streaming agent events over HTTP."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx

from protolink.client.request_spec import ClientRequestSpec
from protolink.transport.config import TransportCapabilities
from protolink.transport.errors import (
    TransportConnectionError,
    TransportProtocolError,
    TransportRemoteError,
    TransportTimeoutError,
)
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
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(
        streaming=True,
        tls=True,
        persistent_connections=True,
    )

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

        request_spec = ClientRequestSpec(
            name="task_stream",
            path="/tasks/stream",
            method="POST",
            request_source="body",
            idempotent=False,
        )
        context = self.new_request_context(request_spec, task)
        client = await self._ensure_client()
        request_id = context.request_id
        headers = {
            **self._build_headers(),
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "X-Protolink-Request-ID": request_id,
        }
        payload = self._serialize_payload(task)
        url = f"{agent_url.rstrip('/')}/tasks/stream"
        request_size = self.check_payload_limit(payload, kind="request", url=url)

        async with self.stream_slot():
            try:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                ) as response:
                    response.raise_for_status()
                    self._metrics.add(bytes_sent=request_size)
                    event_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if line == "":
                            result, final = self._parse_event(event_lines, agent_url, request_id)
                            event_lines = []
                            if result is not None:
                                event_size = self.check_payload_limit(result, kind="event", url=url)
                                self._metrics.add(bytes_received=event_size)
                                yield result
                            if final:
                                break
                            continue
                        if line.startswith("data:"):
                            event_lines.append(line[5:].strip())

                    result, _final = self._parse_event(event_lines, agent_url, request_id)
                    if result is not None:
                        event_size = self.check_payload_limit(result, kind="event", url=url)
                        self._metrics.add(bytes_received=event_size)
                        yield result
            except httpx.TimeoutException as exc:
                raise TransportTimeoutError(
                    f"SSE stream from {agent_url} timed out",
                    url=url,
                    request_id=request_id,
                    retryable=True,
                ) from exc
            except httpx.ConnectError as exc:
                raise TransportConnectionError(
                    f"Failed to connect to agent at {agent_url}. Make sure the agent is running and accessible.",
                    url=url,
                    request_id=request_id,
                    retryable=True,
                ) from exc
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                raise TransportRemoteError(
                    f"Agent at {agent_url} returned HTTP {status_code}: {exc.response.text}",
                    url=url,
                    request_id=request_id,
                    status_code=status_code,
                ) from exc

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
            raise TransportProtocolError(
                f"Invalid SSE JSON-RPC event from {agent_url}: {raw!r}",
                url=agent_url,
                request_id=request_id,
            ) from exc

        message_id = message.get("id")
        if message_id not in {None, request_id}:
            raise TransportProtocolError(
                f"Mismatched SSE JSON-RPC event id from {agent_url}: {message_id}",
                url=agent_url,
                request_id=request_id,
            )

        if not message.get("ok", False):
            error = message.get("error") or {}
            raise TransportRemoteError(
                f"SSE JSON-RPC stream failed at {agent_url}: {error}",
                url=agent_url,
                request_id=request_id,
            )

        return message.get("result"), bool(message.get("final", False))

    @staticmethod
    def _serialize_payload(data: Any) -> Any:
        """Convert Protolink domain objects into JSON-serializable payloads."""
        if hasattr(data, "to_json"):
            return data.to_json()
        if hasattr(data, "to_dict"):
            return data.to_dict()
        if hasattr(data, "model_dump"):
            return data.model_dump()
        return data
