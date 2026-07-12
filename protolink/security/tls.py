"""TLS configuration shared by ProtoLink network transports.

TLS protects connections in transit and optionally authenticates peers with
certificates. It is intentionally separate from :mod:`protolink.security.auth`,
which handles application credentials such as bearer tokens and API keys.
"""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PathLike = str | os.PathLike[str]


@dataclass(frozen=True, slots=True)
class TLSConfig:
    """Configure TLS for HTTP, SSE, WebSocket, and gRPC transports.

    The same configuration is used for both sides of ProtoLink's dual-role
    transports. ``certfile`` and ``keyfile`` identify the local server and, when
    mutual TLS is used, the local client. ``cafile`` defines the certificate
    authorities trusted for outbound servers and inbound client certificates.

    Secure URL schemes activate TLS: ``https://``, ``wss://``, and
    ``grpcs://``. Insecure schemes continue to work without this configuration.
    TLS 1.2 is the minimum protocol version for Python SSL contexts created by
    this class.

    Args:
        certfile: PEM certificate or certificate-chain file for this process.
        keyfile: PEM private-key file matching ``certfile``.
        cafile: Optional PEM CA bundle. System trust roots are used by clients
            when this is omitted.
        require_client_cert: Require and verify client certificates on inbound
            connections. This enables mutual TLS and requires ``cafile``.
        check_hostname: Verify that outbound server certificates match the
            destination hostname. Keep enabled outside controlled test setups.

    Example:
        >>> from protolink import TLSConfig
        >>> tls = TLSConfig(
        ...     certfile="certs/agent.pem",
        ...     keyfile="certs/agent-key.pem",
        ...     cafile="certs/ca.pem",
        ... )
    """

    certfile: PathLike | None = None
    keyfile: PathLike | None = None
    cafile: PathLike | None = None
    require_client_cert: bool = False
    check_hostname: bool = True

    def __post_init__(self) -> None:
        """Validate relationships between certificate settings."""
        if (self.certfile is None) != (self.keyfile is None):
            raise ValueError("certfile and keyfile must be provided together")
        if self.require_client_cert and self.cafile is None:
            raise ValueError("cafile is required when require_client_cert=True")
        for field_name in ("certfile", "keyfile", "cafile"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, os.fspath(value))

    @property
    def has_identity(self) -> bool:
        """Whether a local certificate and private key are configured."""
        return self.certfile is not None and self.keyfile is not None

    def create_server_context(self) -> ssl.SSLContext:
        """Build a server-side SSL context for HTTPS or secure WebSockets.

        Returns:
            An SSL context loaded with the local certificate identity and,
            when enabled, mutual-TLS client verification.

        Raises:
            ValueError: If no local certificate identity is configured.
            OSError: If a configured certificate file cannot be read.
            ssl.SSLError: If certificate material is invalid.
        """
        certfile, keyfile = self.identity_paths()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)

        if self.cafile is not None:
            context.load_verify_locations(cafile=os.fspath(self.cafile))
        context.verify_mode = ssl.CERT_REQUIRED if self.require_client_cert else ssl.CERT_NONE
        return context

    def create_client_context(self) -> ssl.SSLContext:
        """Build a client-side SSL context with certificate verification.

        The system CA store is used when ``cafile`` is omitted. If a local
        identity is configured, it is also loaded for mutual-TLS handshakes.
        """
        context = ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH,
            cafile=os.fspath(self.cafile) if self.cafile is not None else None,
        )
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = self.check_hostname
        if self.has_identity:
            certfile, keyfile = self.identity_paths()
            context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        return context

    def require_server_identity(self, url: str | None = None) -> None:
        """Raise a clear error when a secure server lacks a certificate pair."""
        if self.has_identity:
            return
        location = f" at {url}" if url else ""
        raise ValueError(f"TLS server{location} requires both certfile and keyfile")

    def identity_paths(self) -> tuple[str, str]:
        """Return normalized certificate and key paths after validation."""
        self.require_server_identity()
        certfile = self.certfile
        keyfile = self.keyfile
        if certfile is None or keyfile is None:  # pragma: no cover - guarded above
            raise ValueError("certfile and keyfile must be provided together")
        return os.fspath(certfile), os.fspath(keyfile)

    def certificate_chain_bytes(self) -> bytes | None:
        """Read the local PEM certificate chain for gRPC credentials."""
        return self._read_bytes(self.certfile)

    def private_key_bytes(self) -> bytes | None:
        """Read the local PEM private key for gRPC credentials."""
        return self._read_bytes(self.keyfile)

    def ca_bytes(self) -> bytes | None:
        """Read the configured PEM CA bundle for gRPC credentials."""
        return self._read_bytes(self.cafile)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-compatible representation without key material."""
        return {
            "certfile": os.fspath(self.certfile) if self.certfile is not None else None,
            "keyfile": os.fspath(self.keyfile) if self.keyfile is not None else None,
            "cafile": os.fspath(self.cafile) if self.cafile is not None else None,
            "require_client_cert": self.require_client_cert,
            "check_hostname": self.check_hostname,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TLSConfig:
        """Construct a TLS configuration from serialized settings."""
        return cls(
            certfile=data.get("certfile"),
            keyfile=data.get("keyfile"),
            cafile=data.get("cafile"),
            require_client_cert=bool(data.get("require_client_cert", False)),
            check_hostname=bool(data.get("check_hostname", True)),
        )

    @staticmethod
    def _read_bytes(path: PathLike | None) -> bytes | None:
        """Read optional certificate material from disk."""
        return Path(path).read_bytes() if path is not None else None
