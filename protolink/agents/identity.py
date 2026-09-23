"""Transport-aware defaults for the Agent identity shorthand."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote, urlsplit

from protolink.models import AgentCard
from protolink.transport.base import Transport
from protolink.types import TransportType

_SCHEMES = {
    "http": {"http", "https"},
    "sse": {"http", "https"},
    "json-rpc": {"http", "https"},
    "sse-json-rpc": {"http", "https"},
    "websocket": {"ws", "wss"},
    "grpc": {"grpc", "grpcs"},
    "runtime": {"runtime"},
}


def _parse_url(url: str):
    if not isinstance(url, str) or not url or any(char.isspace() or ord(char) < 32 for char in url):
        raise ValueError("url must be a non-empty absolute URL without whitespace")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise ValueError("url has an invalid hostname or port") from exc
    if not parsed.scheme or not host:
        raise ValueError("url must include a scheme and hostname, for example http://127.0.0.1:8000")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("Agent URLs cannot contain credentials, query parameters, or fragments")
    if port == 0:
        raise ValueError("Agent URLs require a usable endpoint; port 0 cannot be advertised to peers")
    return parsed


def validate_identity_transport(url: str, transport: TransportType | Transport | None) -> None:
    """Validate shorthand endpoints before creating clients or changing the card.

    A concrete transport owns its bind URL; the card may advertise a different
    public URL for a reverse proxy. Custom transports retain their URL contract.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    if transport is None:
        _parse_url(url)
        return
    kind = transport.lower() if isinstance(transport, str) else transport.transport_type
    schemes = _SCHEMES.get(kind)
    if schemes is None:
        if isinstance(transport, Transport) and not transport.validate_url():
            raise ValueError("The configured custom transport has an invalid URL")
        return
    parsed = _parse_url(url)
    if parsed.scheme not in schemes:
        raise ValueError(f"transport={kind!r} requires a URL with scheme {', '.join(sorted(schemes))}")
    binding = parsed if isinstance(transport, str) else _parse_url(transport.url)
    if binding.scheme not in schemes:
        raise ValueError(f"The configured {kind} transport has an incompatible bind URL scheme")
    if kind == "runtime":
        if isinstance(transport, Transport) and transport.url != url:
            raise ValueError("A runtime transport URL must match the agent's advertised URL")
        return
    if binding.port is None:
        raise ValueError("Network transports require an explicit bind port, for example url='http://127.0.0.1:8000'")
    if binding.path not in {"", "/"}:
        raise ValueError("The transport bind URL must have no path; use a configured transport for a public URL prefix")
    if binding.scheme in {"https", "wss", "grpcs"}:
        tls = getattr(transport, "tls", None)
        if tls is None:
            raise ValueError("Secure bind URLs require a configured transport with TLSConfig (certificate and key)")
        tls.require_server_identity()


def resolve_identity(
    card: AgentCard | dict[str, Any] | None,
    *,
    name: str | None,
    description: str | None,
    url: str | None,
    transport: TransportType | Transport | None,
) -> tuple[AgentCard, str | None]:
    """Return the card and, for shorthand, the URL automatically supplied by us."""
    if card is not None:
        if any(value is not None for value in (name, description, url)):
            raise ValueError("Pass either card or name/description/url, not both")
        if not isinstance(card, AgentCard | dict):
            raise TypeError("card must be an AgentCard or dictionary; use name= for the shorthand")
        return (AgentCard.from_dict(card) if isinstance(card, dict) else card), None
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Provide a non-empty name= or an explicit card= to create an Agent")
    if description is not None and (not isinstance(description, str) or not description.strip()):
        raise ValueError("description must be a non-empty string when supplied")
    if transport is not None and not isinstance(transport, str | Transport):
        raise ValueError("Invalid transport type")
    automatic_url = url is None
    if url is None:
        if isinstance(transport, Transport):
            url = transport.url
        elif transport is None or transport.lower() == "runtime":
            url = "runtime://" + quote(name, safe="")
        else:
            raise ValueError(
                "url is required for a network or custom transport; "
                "pass url='http://127.0.0.1:8000' or a configured Transport with its own URL"
            )
    validate_identity_transport(url, transport)
    kind = transport.lower() if isinstance(transport, str) else getattr(transport, "transport_type", None)
    if kind is None:
        kind = {"https": "http", "ws": "websocket", "wss": "websocket", "grpcs": "grpc"}.get(
            urlsplit(url).scheme, urlsplit(url).scheme
        )
    kind = "sse" if kind in {"json-rpc", "sse-json-rpc"} else kind
    resolved = AgentCard(
        name=name, description=description or f"Agent {name}", url=url, transport=cast(TransportType, kind)
    )
    return resolved, url if automatic_url else None
