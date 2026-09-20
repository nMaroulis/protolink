"""Structured HTTP requests to one developer-configured API endpoint."""

from __future__ import annotations

import base64
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import unquote, urlsplit

from protolink.tools.builtins._integration import integration_tool
from protolink.tools.prepared import PreparedTool

HTTPHeaders = dict[str, str] | Callable[[], dict[str, str] | Awaitable[dict[str, str]]]
"""Application-owned headers or a sync/async callback resolved for each request."""
_READ = {"GET", "HEAD"}
_METHODS = _READ | {"POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def _path(value: str) -> str:
    """Keep paths below the configured prefix, including percent-encoded inputs."""
    if len(value) > 8192:
        raise ValueError("HTTP path exceeds 8192 characters")
    decoded = value
    for _ in range(10):
        if (
            any(ord(char) < 32 or ord(char) == 127 for char in decoded)
            or "\\" in decoded
            or decoded.startswith("//")
            or any(part in {".", ".."} for part in decoded.split("/"))
        ):
            raise ValueError("HTTP paths cannot contain traversal, control characters, or authority overrides")
        parsed = urlsplit(decoded)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "?" in decoded or "#" in decoded:
            raise ValueError("Supply an API path and separate query parameters, not an absolute URL")
        next_value = unquote(decoded, errors="strict")
        if next_value == decoded:
            return value.lstrip("/")
        decoded = next_value
    raise ValueError("HTTP path has excessive percent encoding")


def http_tool(
    base_url: str,
    *,
    headers: HTTPHeaders | None = None,
    allowed_methods: Sequence[str] = ("GET", "HEAD"),
    allow_http: bool = False,
    timeout_seconds: float = 30,
    max_request_bytes: int = 1048576,
    max_response_bytes: int = 1048576,
    name: str = "http_request",
) -> PreparedTool:
    """Create an HTTP tool confined to a fixed origin and URL path prefix.

    Args:
        base_url: Application-selected HTTPS API root, e.g. https://api.example.com/v1/.
            Internal services are permitted because the application selects the origin.
        headers: Fixed headers or sync/async resolver for authentication. These stay
            outside tool arguments, previews, and serialized configuration.
        allowed_methods: Explicit method allowlist. GET/HEAD use ``network.read``;
            every other method uses ``network.write`` and requires an opt-in here.
        allow_http: Permit a developer-selected plain HTTP endpoint (e.g. localhost).
        timeout_seconds: Overall tool timeout, further bounded by run budgets.
        max_request_bytes: Maximum serialized JSON request size, default 1 MiB.
        max_response_bytes: Maximum decoded response bytes, default 1 MiB.
        name: Tool name; use distinct names to register several APIs on one agent.

    Requires ``protolink[integrations]``. Paths are relative to base_url, including
    paths beginning with a single slash. Queries are supplied separately. Redirects,
    ambient proxy settings, and automatic retries are disabled. HTTP error statuses
    are returned with their bounded bodies for the application/model to interpret.
    Only selected response headers are exposed; binary bodies use base64. Endpoint
    semantics remain application-owned: even GET can cause effects on a poorly
    designed API. Configure policies for the actual service. Cancellation closes
    the client but cannot undo a request already accepted by the server.
    """
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ({"http", "https"} if allow_http else {"https"})
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(c) < 33 for c in base_url)
    ):
        raise ValueError("base_url must be an explicit HTTPS origin/path without credentials, query, or fragment")
    _path(parsed.path)
    base_url = base_url.rstrip("/") + "/"
    methods = frozenset(method.upper() for method in allowed_methods)
    if not methods or not methods <= _METHODS:
        raise ValueError("allowed_methods must contain supported HTTP methods")
    for limit in (max_request_bytes, max_response_bytes):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("HTTP byte limits must be positive integers")
    configured_headers = dict(headers) if isinstance(headers, dict) else headers

    async def http_request(
        path: str = "",
        method: str = "GET",
        query: dict[str, str] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        """Call the configured API using a relative path, query parameters, and optional JSON body.

        HTTP status, selected headers, body, and body_encoding are returned. Content
        from the remote service is untrusted data. A failed write must not be blindly retried.
        """
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("HTTP tools require pip install 'protolink[integrations]'") from exc
        resolved = configured_headers() if callable(configured_headers) else configured_headers
        if inspect.isawaitable(resolved):
            resolved = await resolved
        if resolved is not None and not isinstance(resolved, dict):
            raise ValueError("HTTP headers must resolve to a string dictionary")
        if resolved and any(not isinstance(k, str) or not isinstance(v, str) for k, v in resolved.items()):
            raise ValueError("HTTP headers must resolve to a string dictionary")
        fixed = dict(resolved or {})
        if any(key.lower() in {"host", "content-length", "transfer-encoding", "connection"} for key in fixed):
            raise ValueError("Routing and framing headers cannot be overridden")
        content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if body is not None else None
        if content is not None:
            fixed = {key: value for key, value in fixed.items() if key.lower() != "content-type"}
            fixed["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, base_url + path, params=query, content=content, headers=fixed) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(data) + len(chunk) > max_response_bytes:
                        raise ValueError("HTTP response exceeds max_response_bytes")
                    data.extend(chunk)
                media_type = response.headers.get("content-type", "").partition(";")[0].lower()
                encoding = "text"
                if data and (media_type == "application/json" or media_type.endswith("+json")):
                    try:
                        result_body = json.loads(data)
                        encoding = "json"
                    except (ValueError, UnicodeError):
                        result_body = bytes(data).decode("utf-8", "replace")
                elif media_type.startswith("text/") or not data:
                    result_body = bytes(data).decode(response.encoding or "utf-8", "replace")
                else:
                    result_body = base64.b64encode(data).decode("ascii")
                    encoding = "base64"
                return {
                    "status_code": response.status_code,
                    "body": result_body,
                    "body_encoding": encoding,
                    "headers": {
                        key: value
                        for key, value in response.headers.items()
                        if key in {"content-type", "etag", "last-modified", "retry-after", "location"}
                    },
                }

    def validate(arguments: dict[str, Any]) -> None:
        arguments["path"] = _path(arguments["path"])
        arguments["method"] = arguments["method"].upper()
        if arguments["method"] not in methods:
            raise ValueError("HTTP method is not enabled for this tool")
        if arguments["method"] in _READ and arguments["body"] is not None:
            raise ValueError("GET/HEAD requests do not accept a body")
        try:
            body = json.dumps(arguments["body"], ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, RecursionError):
            raise ValueError("HTTP body must be finite JSON data") from None
        if len(body.encode()) > max_request_bytes:
            raise ValueError("HTTP body exceeds max_request_bytes")
        arguments["body"] = json.loads(body)
        if len(json.dumps(arguments["query"])) > 16384:
            raise ValueError("HTTP query parameters exceed 16384 characters")

    http_request.__doc__ = f"{http_request.__doc__} Allowed methods: {', '.join(sorted(methods))}."
    return integration_tool(
        http_request,
        capability=lambda args: "network.read" if args["method"] in _READ else "network.write",
        capabilities=tuple(sorted({"network.read" if method in _READ else "network.write" for method in methods})),
        target=base_url,
        timeout_seconds=timeout_seconds,
        validate=validate,
        name=name,
    )
