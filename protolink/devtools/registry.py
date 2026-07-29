"""Registry inspection helpers used by CLI and dashboard tooling."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_MAX_REGISTRY_RESPONSE_BYTES = 4 * 1024 * 1024


def fetch_registry_agents(
    registry_url: str,
    *,
    filter_by: dict[str, Any] | None = None,
    timeout: float = 3.0,
) -> list[dict[str, Any]]:
    """Fetch agent cards from a running HTTP registry.

    Args:
        registry_url: Base registry URL.
        filter_by: Optional discovery filter encoded as query parameters.
        timeout: HTTP timeout in seconds.

    Returns:
        Serialized agent cards returned by the registry.
    """
    if not registry_url.startswith(("http://", "https://")):
        raise ValueError("registry devtools currently support HTTP(S) registry URLs")

    query = ""
    if filter_by:
        clean = {key: value for key, value in filter_by.items() if value not in (None, "", [])}
        if clean:
            query = "?" + urlencode(clean, doseq=True)
    url = registry_url.rstrip("/") + "/agents/" + query
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        declared_size = getattr(response, "headers", {}).get("Content-Length")
        if declared_size:
            try:
                if int(declared_size) > _MAX_REGISTRY_RESPONSE_BYTES:
                    raise RuntimeError("Registry response exceeds the 4 MB inspection limit")
            except ValueError:
                pass
        body = response.read(_MAX_REGISTRY_RESPONSE_BYTES + 1)
        if len(body) > _MAX_REGISTRY_RESPONSE_BYTES:
            raise RuntimeError("Registry response exceeds the 4 MB inspection limit")
        payload = json.loads(body.decode("utf-8"))

    if not isinstance(payload, list):
        raise RuntimeError(f"Registry returned {type(payload).__name__}, expected list")
    return [dict(item) for item in payload if isinstance(item, dict)]


def inspect_registry_agent(
    registry_url: str,
    selector: str,
    *,
    timeout: float = 3.0,
) -> dict[str, Any] | None:
    """Return one registry agent by URL or name."""
    cards = fetch_registry_agents(registry_url, timeout=timeout)
    for card in cards:
        if card.get("url") == selector or card.get("name") == selector:
            return card
    return None
