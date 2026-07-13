from __future__ import annotations

import os
import ssl
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from protolink.server.endpoint_handler import EndpointSpec
from protolink.utils.serialization import Serializer

if TYPE_CHECKING:
    from protolink.security.auth import Authenticator
    from protolink.security.tls import TLSConfig
    from protolink.transport.base import Transport


class BackendInterface(ABC):
    @abstractmethod
    def setup_routes(
        self,
        endpoints: list[EndpointSpec],
        authenticator: Authenticator | None = None,
        transport: Transport | None = None,
    ) -> None:
        """Register all abstract endpoints onto the physical ASGI routing table.

        Subclasses must implement this to iterate over the provided `EndpointSpec` models
        and mount them as concrete HTTP routes within their specific web framework
        (e.g., Starlette or FastAPI).
        """
        raise NotImplementedError()

    @abstractmethod
    async def start(self, url: str, tls: TLSConfig | None = None) -> None:
        """Initialize and spin up the underlying ASGI HTTP server daemon.

        Implementations should bind to the parsed host/port from the provided `url`
        and execute the server loop inside an isolated `asyncio.Task`. ``https://``
        URLs must apply the supplied TLS certificate configuration.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully terminate the ASGI HTTP server daemon.

        Implementations must signal the server to exit, gracefully complete any
        in-flight connections, and safely `await` the background server task until closure.
        """
        ...

    def _get_host_port(self, url: str) -> tuple[str | None, int | None]:
        """Extract host and port integers from an absolute URI string."""
        from urllib.parse import urlparse

        parsed = urlparse(url.rstrip("/"))
        return parsed.hostname, parsed.port

    def _uvicorn_tls_kwargs(self, url: str, tls: TLSConfig | None) -> dict[str, Any]:
        """Translate shared TLS settings into Uvicorn server arguments."""
        if urlparse(url).scheme.lower() != "https":
            return {}
        if tls is None:
            raise ValueError(f"HTTPS server at {url} requires TLSConfig with certfile and keyfile")

        certfile, keyfile = tls.identity_paths()
        kwargs: dict[str, Any] = {
            "ssl_certfile": certfile,
            "ssl_keyfile": keyfile,
            "ssl_cert_reqs": ssl.CERT_REQUIRED if tls.require_client_cert else ssl.CERT_NONE,
        }
        if tls.cafile is not None:
            kwargs["ssl_ca_certs"] = os.fspath(tls.cafile)
        return kwargs

    def _serialize_result(self, result: object) -> object:
        """Recursively normalize a transport result into JSON-compatible values."""
        return Serializer.serialize_to_dict(result)
