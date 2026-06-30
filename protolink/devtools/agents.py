"""Agent inspection actions used by the local dashboard.

These helpers keep network-facing dashboard actions separate from HTML
rendering. They intentionally use the Python standard library so the devtools
surface remains available without adding a frontend or HTTP-client dependency.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def ping_agent(agent_url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    """Probe an HTTP agent's status endpoint.

    Args:
        agent_url: Base URL from an ``AgentCard``.
        timeout: HTTP timeout in seconds.

    Returns:
        JSON-compatible probe details including success state, status code,
        measured latency, and the status URL that was called.

    Raises:
        ValueError: If ``agent_url`` is not an HTTP(S) URL.
        URLError: If the probe cannot connect before the timeout.
    """
    status_url = _join_url(_require_http_url(agent_url), "/status")
    started = time.perf_counter()
    request = Request(status_url, headers={"Accept": "text/html, application/json, */*"})
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read(512)
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "status": exc.code,
            "latency_ms": latency_ms,
            "url": status_url,
            "error": exc.reason,
        }

    latency_ms = round((time.perf_counter() - started) * 1000)
    return {
        "ok": 200 <= int(status) < 400,
        "status": int(status),
        "latency_ms": latency_ms,
        "url": status_url,
        "error": None,
    }


def chat_with_agent(
    agent_url: str,
    message: str,
    *,
    session_id: str = "dashboard",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Send one chat message to an HTTP agent.

    Args:
        agent_url: Base URL from an ``AgentCard``.
        message: User message to send to the agent's ``POST /chat`` endpoint.
        session_id: Conversation session identifier forwarded to the agent.
        timeout: HTTP timeout in seconds.

    Returns:
        JSON-compatible chat response. Successful Protolink chat endpoints
        return ``{"response": "..."}``; error responses are normalized into
        ``{"error": "..."}``.

    Raises:
        ValueError: If ``agent_url`` is not HTTP(S) or ``message`` is empty.
        URLError: If the request cannot connect before the timeout.
    """
    clean_message = message.strip()
    if not clean_message:
        raise ValueError("message cannot be empty")

    chat_url = _join_url(_require_http_url(agent_url), "/chat")
    payload = json.dumps({"message": clean_message, "session_id": session_id}).encode("utf-8")
    request = Request(
        chat_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {"response": raw, "url": chat_url}

    if not isinstance(decoded, dict):
        return {"response": str(decoded), "url": chat_url}
    decoded.setdefault("url", chat_url)
    return decoded


def _require_http_url(agent_url: str) -> str:
    """Return a normalized HTTP(S) base URL or raise ``ValueError``."""
    parsed = urlparse(agent_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("dashboard agent actions require an HTTP(S) agent URL")
    return agent_url.rstrip("/")


def _join_url(base_url: str, path: str) -> str:
    """Join a normalized base URL and endpoint path."""
    return base_url.rstrip("/") + "/" + path.lstrip("/")
