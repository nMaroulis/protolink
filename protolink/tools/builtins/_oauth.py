"""Bounded asynchronous JSON requests for fixed OAuth service endpoints."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

OAuthToken = str | Callable[[], str | Awaitable[str]]
"""OAuth access token or application callback supplying a fresh token per request."""


class OAuthJSONAPI:
    """Shared HTTP mechanics; service adapters select the origin and error type."""

    def __init__(
        self,
        token: OAuthToken,
        base_url: str,
        *,
        provider: str,
        error_type: type[Exception],
    ) -> None:
        if not callable(token) and (not isinstance(token, str) or not token.strip()):
            raise ValueError("token must be a nonempty OAuth access token or token callback")
        self._token = token
        self._base_url = base_url
        self._provider = provider
        self._error_type = error_type

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Perform one request, bounded to 2 MiB, without redirects or retries."""
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                f"{self._provider} integrations require httpx: pip install 'protolink[integrations]'"
            ) from exc
        token = self._token() if callable(self._token) else self._token
        if inspect.isawaitable(token):
            token = await token
        if not isinstance(token, str) or not token.strip() or any(c in token for c in "\r\n\x00"):
            raise ValueError("token callback must return a nonempty OAuth access token without control characters")
        request_headers = {**(headers or {}), "Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                method,
                self._base_url + path,
                params=params,
                json=body,
                headers=request_headers,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise self._error_type(response.status_code)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 2 * 1024 * 1024:
                        raise ValueError(f"{self._provider} API response exceeds the 2 MiB limit")
                    content.extend(chunk)
        if not content:
            return {}
        try:
            data = json.loads(content)
        except (ValueError, UnicodeError):
            raise ValueError(f"{self._provider} API returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ValueError(f"{self._provider} API response must be a JSON object")
        return data
