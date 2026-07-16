"""Bounded public-network access shared by ProtoLink's web tools.

The helpers in this module deliberately avoid the process proxy configuration
and connect to a DNS answer that was validated immediately before use. This
keeps the built-in fetcher from becoming an accidental private-network proxy.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_FORBIDDEN_REQUEST_HEADERS = frozenset({"connection", "content-length", "host", "transfer-encoding"})
_MAX_CONNECT_ATTEMPT_SECONDS = 2.0
_MAX_CHUNK_LINE_BYTES = 4096
_DEFAULT_MAX_URL_CHARS = 2048
_HTTP_TOKEN_CHARACTERS = frozenset("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
_HEX_DIGITS = frozenset(b"0123456789abcdefABCDEF")

# Python's ``ipaddress`` special-purpose classifications changed materially in
# 3.13. Keep the security boundary stable across ProtoLink's supported Python
# versions by spelling out the non-public ranges that matter to an HTTP client.
_IPV4_NON_PUBLIC_NETWORKS: tuple[ipaddress.IPv4Network, ...] = tuple(
    ipaddress.IPv4Network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_IPV6_NON_PUBLIC_NETWORKS: tuple[ipaddress.IPv6Network, ...] = tuple(
    ipaddress.IPv6Network(cidr)
    for cidr in (
        "::/96",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
        "5f00::/16",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
        "ff00::/8",
    )
)


@dataclass(frozen=True)
class _HttpResponse:
    """Small immutable HTTP response returned to a built-in tool."""

    url: str
    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class _ResolvedUrl:
    """Validated URL plus the public addresses eligible for its connection."""

    url: str
    scheme: str
    hostname: str
    port: int
    target: str
    host_header: str
    connect_ips: tuple[str, ...]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection whose socket target is a prevalidated IP address."""

    def __init__(self, hostname: str, connect_ip: str, port: int, timeout: float) -> None:
        tls_context = ssl.create_default_context()
        super().__init__(hostname, port=port, timeout=timeout, context=tls_context)
        self._connect_ip = connect_ip
        self._tls_context = tls_context

    def connect(self) -> None:
        """Connect to the pinned address while verifying TLS for the URL host."""
        raw_socket = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
        )
        self.sock = raw_socket
        try:
            self.sock = self._tls_context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


def _ipv4_is_non_public(address: ipaddress.IPv4Address) -> bool:
    """Return whether an IPv4 address belongs to a stable non-public class."""
    return (
        any(address in network for network in _IPV4_NON_PUBLIC_NETWORKS)
        or not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _embedded_ipv4_addresses(address: ipaddress.IPv6Address) -> tuple[ipaddress.IPv4Address, ...]:
    """Return IPv4 endpoints encoded by supported IPv6 transition formats."""
    embedded: list[ipaddress.IPv4Address] = []
    for candidate in (address.ipv4_mapped, address.sixtofour):
        if candidate is not None:
            embedded.append(candidate)
    if address.teredo is not None:
        embedded.extend(address.teredo)
    return tuple(embedded)


def _public_ip(address: str) -> str:
    """Return a canonical public IP address or reject the address."""
    if "%" in address:
        raise ValueError("Scoped IP addresses are not valid public URL targets")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ValueError(f"DNS returned an invalid address: {address!r}") from exc
    if isinstance(parsed, ipaddress.IPv4Address):
        blocked = _ipv4_is_non_public(parsed)
    else:
        blocked = (
            any(parsed in network for network in _IPV6_NON_PUBLIC_NETWORKS)
            or not parsed.is_global
            or parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_reserved
            or parsed.is_unspecified
            or parsed.is_site_local
            or any(_ipv4_is_non_public(embedded) for embedded in _embedded_ipv4_addresses(parsed))
        )
    if blocked:
        raise ValueError(f"URL resolves to a non-public address: {parsed.compressed}")
    return parsed.compressed


def _ascii_hostname(hostname: str) -> str:
    """Normalize an international hostname for DNS, TLS, and Host headers."""
    normalized = hostname.rstrip(".").lower()
    if not normalized:
        raise ValueError("URL must include a hostname")
    if normalized == "localhost" or normalized.endswith((".localhost", ".local")):
        raise ValueError("URL hostname is not public")
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("URL contains an invalid hostname") from exc


def _resolve_public_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve a hostname and require every returned address to be public."""
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RuntimeError(f"Could not resolve public URL host {hostname!r}") from exc
    if not records:
        raise RuntimeError(f"Could not resolve public URL host {hostname!r}")

    addresses: list[str] = []
    for record in records:
        socket_address = record[4]
        if not socket_address:
            continue
        address = _public_ip(str(socket_address[0]))
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise RuntimeError(f"Could not resolve public URL host {hostname!r}")
    return tuple(addresses)


def _normalized_netloc(hostname: str) -> str:
    """Build a normalized authority for a default-port HTTP(S) URL."""
    try:
        parsed = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    return f"[{hostname}]" if parsed.version == 6 else hostname


def _validate_and_resolve(url: str, *, max_url_chars: int = _DEFAULT_MAX_URL_CHARS) -> _ResolvedUrl:
    """Validate a URL and pin it to its public DNS answers."""
    candidate = url.strip()
    if not candidate:
        raise ValueError("URL must not be empty")
    if max_url_chars <= 0:
        raise ValueError("max_url_chars must be greater than zero")
    if len(candidate) > max_url_chars:
        raise ValueError(f"URL must not exceed {max_url_chars} characters")

    try:
        parsed: SplitResult = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port or address") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL user information is not allowed")
    if parsed.hostname is None:
        raise ValueError("URL must include a hostname")

    hostname = _ascii_hostname(parsed.hostname)
    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        raise ValueError(f"Only the default {scheme} port ({default_port}) is allowed")

    try:
        direct_address = _public_ip(hostname)
        addresses = (direct_address,)
    except ValueError:
        addresses = _resolve_public_addresses(hostname, default_port)

    netloc = _normalized_netloc(hostname)
    path = parsed.path or "/"
    target = path + (f"?{parsed.query}" if parsed.query else "")
    normalized_url = urlunsplit((scheme, netloc, path, parsed.query, ""))
    return _ResolvedUrl(
        url=normalized_url,
        scheme=scheme,
        hostname=hostname,
        port=default_port,
        target=target,
        host_header=netloc,
        connect_ips=addresses,
    )


def _request_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Merge fixed safe request headers with integration-owned headers."""
    merged = {
        "Accept": "text/html, text/plain, application/json, application/xml;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": "ProtoLink-Builtin-Tools",
    }
    for name, value in (headers or {}).items():
        normalized_name = str(name)
        normalized_value = str(value)
        if not normalized_name or any(character not in _HTTP_TOKEN_CHARACTERS for character in normalized_name):
            raise ValueError(f"Request header name {normalized_name!r} is invalid")
        if normalized_name.lower() in _FORBIDDEN_REQUEST_HEADERS:
            raise ValueError(f"Request header {normalized_name!r} cannot be overridden")
        if any(
            character in "\r\n" or (ord(character) < 32 and character != "\t") or ord(character) == 127
            for character in normalized_value
        ):
            raise ValueError(f"Request header {normalized_name!r} contains an invalid value")
        try:
            normalized_value.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise ValueError(f"Request header {normalized_name!r} contains an invalid value") from exc
        merged[normalized_name] = normalized_value
    return merged


def _read_exact(stream: Any, size: int) -> bytes:
    """Read exactly ``size`` bytes without ever requesting an unbounded read."""
    output = bytearray()
    while len(output) < size:
        piece = stream.read(size - len(output))
        if not isinstance(piece, bytes) or not piece:
            raise RuntimeError("URL returned a truncated chunked response")
        output.extend(piece)
    return bytes(output)


def _read_bounded_chunked(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    """Decode strict HTTP chunking while keeping every read within ``max_bytes``."""
    stream = response.fp
    if stream is None:
        raise RuntimeError("URL returned a chunked response without a readable body")

    output = bytearray()
    while True:
        line = stream.readline(_MAX_CHUNK_LINE_BYTES + 1)
        if not isinstance(line, bytes) or not line or len(line) > _MAX_CHUNK_LINE_BYTES:
            raise RuntimeError("URL returned an invalid chunk-size line")
        if not line.endswith(b"\r\n"):
            raise RuntimeError("URL returned an invalid chunk-size line")
        size_token = line[:-2].partition(b";")[0].strip()
        if not size_token or any(byte not in _HEX_DIGITS for byte in size_token):
            raise RuntimeError("URL returned an invalid chunk size")
        chunk_size = int(size_token, 16)
        if chunk_size == 0:
            # The request uses ``Connection: close``, so trailers do not need to
            # be retained or drained for connection reuse.
            return bytes(output)
        if chunk_size > max_bytes - len(output):
            raise RuntimeError(f"URL response exceeds the {max_bytes}-byte limit")
        output.extend(_read_exact(stream, chunk_size))
        if _read_exact(stream, 2) != b"\r\n":
            raise RuntimeError("URL returned an invalid chunk terminator")


def _request_once(
    resolved: _ResolvedUrl,
    *,
    headers: dict[str, str] | None,
    timeout: float,
    max_bytes: int,
) -> _HttpResponse:
    """Issue one GET request across pinned addresses under one hard deadline."""
    request_headers = _request_headers(headers)
    request_headers["Host"] = resolved.host_header
    deadline_expired = threading.Event()
    deadline = time.monotonic() + timeout
    connection_lock = threading.Lock()
    active_connection: http.client.HTTPConnection | None = None

    def abort_at_deadline() -> None:
        """Interrupt any in-flight socket operation when the deadline expires."""
        deadline_expired.set()
        with connection_lock:
            connection = active_connection
        if connection is None:
            return
        active_socket = connection.sock
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()

    deadline_timer = threading.Timer(timeout, abort_at_deadline)
    deadline_timer.daemon = True
    deadline_timer.start()
    try:
        connection: http.client.HTTPConnection | None = None
        last_connection_error: http.client.HTTPException | OSError | None = None
        address_count = len(resolved.connect_ips)
        for address_index, connect_ip in enumerate(resolved.connect_ips):
            remaining = deadline - time.monotonic()
            if deadline_expired.is_set() or remaining <= 0:
                raise RuntimeError(f"URL request exceeded the {timeout:g}-second deadline")
            addresses_left = address_count - address_index
            attempt_timeout = (
                remaining if addresses_left == 1 else min(_MAX_CONNECT_ATTEMPT_SECONDS, remaining / addresses_left)
            )

            if resolved.scheme == "https":
                candidate = _PinnedHTTPSConnection(
                    resolved.hostname,
                    connect_ip,
                    resolved.port,
                    attempt_timeout,
                )
            else:
                candidate = http.client.HTTPConnection(connect_ip, resolved.port, timeout=attempt_timeout)

            with connection_lock:
                if deadline_expired.is_set():
                    candidate.close()
                    raise RuntimeError(f"URL request exceeded the {timeout:g}-second deadline")
                active_connection = candidate
            try:
                candidate.connect()
            except (http.client.HTTPException, OSError) as exc:
                last_connection_error = exc
                with connection_lock:
                    if active_connection is candidate:
                        active_connection = None
                candidate.close()
                if deadline_expired.is_set():
                    raise RuntimeError(f"URL request exceeded the {timeout:g}-second deadline") from exc
                continue
            connection = candidate
            break

        if connection is None:
            message = f"Public URL request failed for {resolved.hostname!r}"
            if last_connection_error is not None:
                message = f"{message}: {last_connection_error}"
            raise RuntimeError(message) from last_connection_error
        if deadline_expired.is_set():
            raise RuntimeError(f"URL request exceeded the {timeout:g}-second deadline")
        response_timeout = deadline - time.monotonic()
        if response_timeout <= 0:
            raise RuntimeError(f"URL request exceeded the {timeout:g}-second deadline")
        if connection.sock is not None:
            connection.sock.settimeout(response_timeout)
        connection.request("GET", resolved.target, headers=request_headers)
        response = connection.getresponse()
        response_header_items = response.getheaders()
        response_headers = {name.lower(): value.strip() for name, value in response_header_items}
        if response.status in _REDIRECT_STATUSES:
            body = b""
        else:
            content_encoding = response_headers.get("content-encoding", "identity").lower()
            if content_encoding not in {"", "identity"}:
                raise RuntimeError(f"URL returned unsupported content encoding {content_encoding!r}")
            transfer_values = [value for name, value in response_header_items if name.lower() == "transfer-encoding"]
            transfer_tokens = [
                token.strip().lower() for value in transfer_values for token in value.split(",") if token.strip()
            ]
            content_lengths = [
                value.strip() for name, value in response_header_items if name.lower() == "content-length"
            ]
            if len(content_lengths) > 1:
                raise RuntimeError("URL returned multiple Content-Length headers")
            content_length = content_lengths[0] if content_lengths else None
            if content_length:
                try:
                    announced_size = int(content_length)
                except ValueError as exc:
                    raise RuntimeError("URL returned an invalid Content-Length header") from exc
                if announced_size < 0 or announced_size > max_bytes:
                    raise RuntimeError(f"URL response exceeds the {max_bytes}-byte limit")
            if transfer_values:
                if transfer_tokens != ["chunked"] or not getattr(response, "chunked", False):
                    raise RuntimeError("URL returned an unsupported Transfer-Encoding header")
                if content_length is not None:
                    raise RuntimeError("URL returned both Transfer-Encoding and Content-Length headers")
                body = _read_bounded_chunked(response, max_bytes)
            else:
                if getattr(response, "chunked", False):
                    raise RuntimeError("URL returned inconsistent chunked framing")
                body = response.read(max_bytes + 1)
            if deadline_expired.is_set():
                raise RuntimeError(f"URL request exceeded the {timeout:g}-second deadline")
            if len(body) > max_bytes:
                raise RuntimeError(f"URL response exceeds the {max_bytes}-byte limit")
        return _HttpResponse(
            url=resolved.url,
            status=int(response.status),
            headers=response_headers,
            body=body,
        )
    except (http.client.HTTPException, OSError) as exc:
        if deadline_expired.is_set():
            raise RuntimeError(f"URL request exceeded the {timeout:g}-second deadline") from exc
        raise RuntimeError(f"Public URL request failed for {resolved.hostname!r}: {exc}") from exc
    finally:
        deadline_timer.cancel()
        with connection_lock:
            connection = active_connection
            active_connection = None
        if connection is not None:
            connection.close()


def _http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_bytes: int = 1_000_000,
    max_redirects: int = 4,
    max_url_chars: int = _DEFAULT_MAX_URL_CHARS,
) -> _HttpResponse:
    """GET one public HTTP(S) URL with DNS pinning and bounded redirects.

    Args:
        url: Absolute public HTTP or HTTPS URL.
        headers: Integration-owned headers. Connection-routing headers cannot
            be overridden.
        timeout: Per-request transport deadline in seconds, beginning after DNS
            validation. Each redirect starts a new transport deadline after its
            destination is validated.
        max_bytes: Maximum accepted final response size.
        max_redirects: Maximum number of validated redirects.
        max_url_chars: Maximum URL length. The public fetch tool keeps the
            conservative default; a fixed first-party endpoint may raise it for
            a percent-encoded query.

    Returns:
        The final successful response.

    Raises:
        ValueError: The URL, address, port, or redirect is unsafe.
        RuntimeError: DNS resolution, transport, redirect, or response bounds
            fail.
    """
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero")
    if max_redirects < 0:
        raise ValueError("max_redirects must not be negative")
    if max_url_chars <= 0:
        raise ValueError("max_url_chars must be greater than zero")

    resolved = _validate_and_resolve(url, max_url_chars=max_url_chars)
    seen = {resolved.url}
    for redirect_count in range(max_redirects + 1):
        response = _request_once(resolved, headers=headers, timeout=timeout, max_bytes=max_bytes)
        if response.status not in _REDIRECT_STATUSES:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"URL request returned HTTP status {response.status}")
            return response

        location = response.headers.get("location")
        if not location:
            raise RuntimeError("URL redirect did not include a Location header")
        if redirect_count >= max_redirects:
            raise RuntimeError(f"URL exceeded the {max_redirects}-redirect limit")

        next_url = urljoin(resolved.url, location)
        next_resolved = _validate_and_resolve(next_url, max_url_chars=max_url_chars)
        if resolved.scheme == "https" and next_resolved.scheme != "https":
            raise ValueError("HTTPS redirects may not downgrade to HTTP")
        if next_resolved.url in seen:
            raise RuntimeError("URL redirect loop detected")
        seen.add(next_resolved.url)
        resolved = next_resolved

    raise RuntimeError("URL redirect handling ended unexpectedly")


def _response_for_tests(**values: Any) -> _HttpResponse:
    """Construct an internal response for tests without exposing the type."""
    return _HttpResponse(**values)
