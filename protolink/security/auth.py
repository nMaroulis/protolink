"""
ProtoLink - Security & Authentication

OAuth 2.0, Bearer tokens authorization for enterprise deployments.
"""

import base64
import hmac
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from protolink.types import HttpAuthScheme, SecuritySchemeType
from protolink.utils import utc_now

_HMAC_JWT_ALGORITHMS: dict[str, str] = {
    "HS256": "sha256",
    "HS384": "sha384",
    "HS512": "sha512",
}


def _decode_base64url(segment: str, *, label: str) -> bytes:
    """Decode one unpadded base64url JWT segment."""
    if not segment:
        raise ValueError(f"JWT {label} segment is empty")
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.b64decode(
            (segment + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except Exception as exc:
        raise ValueError(f"JWT {label} segment is not valid base64url") from exc


def _json_segment(segment: str, *, label: str) -> dict[str, Any]:
    """Decode a JWT JSON segment into a mapping."""
    try:
        value = json.loads(_decode_base64url(segment, label=label))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JWT {label} segment is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JWT {label} segment must be a JSON object")
    return value


def _numeric_date(value: Any, *, claim: str) -> float:
    """Convert a JWT NumericDate claim into seconds since the Unix epoch."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"JWT claim '{claim}' must be a numeric date")
    return float(value)


def _numeric_date_to_iso(value: float) -> str:
    """Return an ISO timestamp for a JWT NumericDate value."""
    return datetime.fromtimestamp(value, UTC).isoformat()


@dataclass
class SecurityContext:
    """Authenticated principal context.

    Represents an authenticated user, agent, or service with their token information.

    Attributes:
        principal_id: Identifier of authenticated entity (user, agent, service)
        token: Authentication token (JWT, OAuth token, etc.)
        expires_at: When token expires (ISO format)
        issued_at: When token was issued (ISO format)
        metadata: Additional auth metadata
    """

    principal_id: str
    token: str
    expires_at: str | None = None
    issued_at: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if token is expired.

        Returns:
            True if expired, False if still valid or no expiry set
        """
        if not self.expires_at:
            return False

        expires = datetime.fromisoformat(self.expires_at)
        return datetime.now(UTC) > expires

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "principal_id": self.principal_id,
            "token": self.token,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "metadata": self.metadata,
        }


@dataclass
class SecurityScheme:
    """Security scheme definition for an agent.

    Describes the security requirements and methods supported by an agent.
    Used in AgentCard to declare security capabilities.

    Attributes:
        auth_type: Type of scheme ("http", "oauth2", "api_key")
        auth_scheme: Type of HTTP auth scheme ("bearer", "basic", "digest", etc.)
        description: Human-readable description
        metadata: Additional scheme metadata

    Example:
        { auth_type = "http", auth_scheme = "bearer" }
    """

    auth_type: SecuritySchemeType
    auth_scheme: HttpAuthScheme | None
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.auth_type,
            "scheme": self.auth_scheme,
            "description": self.description,
            "metadata": self.metadata,
        }


class Authenticator(ABC):
    """Abstract authentication provider.

    Implementations provide authentication methods (Bearer, OAuth2, etc.).
    """

    @property
    @abstractmethod
    def security_scheme(self) -> SecurityScheme:
        """Get the security scheme definition for this authenticator."""
        pass

    @abstractmethod
    async def authenticate(self, credentials: str) -> SecurityContext:
        """Authenticate a principal with provided credentials.

        Args:
            credentials: Raw credentials (token, api key, etc.)

        Returns:
            SecurityContext if successful

        Raises:
            Exception: If authentication fails
        """
        pass

    @abstractmethod
    async def refresh_token(self, context: SecurityContext) -> SecurityContext:
        """Refresh an authentication context (if supported).

        Args:
            context: Context to refresh

        Returns:
            New AuthContext with refreshed token

        Raises:
            Exception: If refresh not supported or fails
        """
        pass


class BearerTokenAuth(Authenticator):
    """Bearer JWT authentication.

    Validates compact JSON Web Tokens signed with an HMAC SHA algorithm. This
    keeps the default implementation dependency-free while still checking the
    important security properties: algorithm, signature, expiration, not-before
    time, issuer, and audience.

    Example:
        auth = BearerTokenAuth(
            secret="your-secret-key",
            algorithm="HS256",
            issuer="https://auth.example.com",
            audience="protolink-agent",
        )
        context = await auth.authenticate(token)
    """

    @property
    def security_scheme(self) -> SecurityScheme:
        return SecurityScheme(
            auth_type="http",
            auth_scheme="bearer",
            description="Bearer JWT authentication",
            metadata={
                "algorithms": list(_HMAC_JWT_ALGORITHMS),
                "issuer": self.issuer,
                "audience": self.audience,
            },
        )

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        *,
        issuer: str | None = None,
        audience: str | None = None,
        leeway_seconds: int = 0,
    ) -> None:
        """Initialize bearer JWT authentication.

        Args:
            secret: Shared HMAC signing secret used to verify JWT signatures.
            algorithm: HMAC JWT algorithm. Supported values are ``HS256``,
                ``HS384``, and ``HS512``.
            issuer: Optional required ``iss`` claim.
            audience: Optional required ``aud`` claim. The token may provide
                either a string or a list of strings.
            leeway_seconds: Clock-skew allowance for ``exp``, ``nbf``, and
                ``iat`` checks.

        Raises:
            ValueError: If the configuration cannot safely validate tokens.
        """
        if not secret:
            raise ValueError("BearerTokenAuth requires a non-empty JWT signing secret")
        if algorithm not in _HMAC_JWT_ALGORITHMS:
            supported = ", ".join(sorted(_HMAC_JWT_ALGORITHMS))
            raise ValueError(f"Unsupported JWT algorithm '{algorithm}'. Supported algorithms: {supported}")
        if leeway_seconds < 0:
            raise ValueError("leeway_seconds must be non-negative")

        self.secret = secret
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience
        self.leeway_seconds = leeway_seconds

    async def authenticate(self, credentials: str) -> SecurityContext:
        """Validate a signed JWT and return its security context.

        Args:
            credentials: Compact JWT string from an Authorization bearer token.

        Returns:
            SecurityContext extracted from verified token claims.

        Raises:
            Exception: If the token is malformed, unsigned, expired, uses the
                wrong algorithm, has the wrong issuer/audience, or fails
                signature verification.
        """
        try:
            parts = credentials.split(".")
            if len(parts) != 3:
                raise ValueError("JWT must contain header, payload, and signature segments")

            header_segment, payload_segment, signature_segment = parts
            header = _json_segment(header_segment, label="header")
            payload = _json_segment(payload_segment, label="payload")

            alg = header.get("alg")
            if alg != self.algorithm:
                raise ValueError(f"JWT algorithm mismatch: expected {self.algorithm}, got {alg!r}")
            if alg not in _HMAC_JWT_ALGORITHMS:
                raise ValueError(f"Unsupported JWT algorithm: {alg!r}")

            signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
            expected = hmac.new(
                self.secret.encode("utf-8"),
                signing_input,
                _HMAC_JWT_ALGORITHMS[self.algorithm],
            ).digest()
            expected_segment = base64.urlsafe_b64encode(expected).rstrip(b"=")
            if not hmac.compare_digest(expected_segment, signature_segment.encode("ascii")):
                raise ValueError("JWT signature verification failed")

            now = time.time()
            leeway = float(self.leeway_seconds)
            expires_at: str | None = None
            issued_at: str | None = None

            if "exp" in payload:
                exp = _numeric_date(payload["exp"], claim="exp")
                if now > exp + leeway:
                    raise ValueError("JWT has expired")
                expires_at = _numeric_date_to_iso(exp)
            if "nbf" in payload:
                nbf = _numeric_date(payload["nbf"], claim="nbf")
                if now + leeway < nbf:
                    raise ValueError("JWT is not valid yet")
            if "iat" in payload:
                iat = _numeric_date(payload["iat"], claim="iat")
                if now + leeway < iat:
                    raise ValueError("JWT issued-at time is in the future")
                issued_at = _numeric_date_to_iso(iat)

            if self.issuer is not None and payload.get("iss") != self.issuer:
                raise ValueError("JWT issuer mismatch")
            if self.audience is not None:
                aud = payload.get("aud")
                if isinstance(aud, str):
                    audiences = {aud}
                elif isinstance(aud, list) and all(isinstance(item, str) for item in aud):
                    audiences = set(aud)
                else:
                    raise ValueError("JWT audience claim is missing or invalid")
                if self.audience not in audiences:
                    raise ValueError("JWT audience mismatch")

            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            extra_claims = {
                key: value
                for key, value in payload.items()
                if key not in {"sub", "exp", "nbf", "iat", "iss", "aud", "jti", "metadata"}
            }
            if extra_claims:
                metadata = {**metadata, "claims": extra_claims}

            return SecurityContext(
                principal_id=str(payload.get("sub") or payload.get("client_id") or "unknown"),
                token=credentials,
                expires_at=expires_at,
                issued_at=issued_at or utc_now(),
                metadata=metadata,
            )
        except Exception as e:
            raise Exception(f"Token authentication failed: {e}")  # noqa: B904

    async def refresh_token(self, context: SecurityContext) -> SecurityContext:
        """Bearer tokens typically don't refresh.

        Args:
            context: Current context

        Returns:
            Same context (no refresh possible)
        """
        return context


class OAuth2DelegationAuth(Authenticator):
    """OAuth 2.0 token exchange with delegated scopes.

    Exchanges a broad-scoped token for an agent-specific token
    with narrower scopes (following OAuth 2.0 delegated credentials).

    Suitable for multi-organization deployments where different
    agents need different permissions.

    Example:
        auth = OAuth2DelegationAuth(
            exchange_endpoint="https://auth.example.com/exchange",
            client_id="agent-client",
            client_secret="secret"
        )
        context = await auth.authenticate(user_token)
    """

    @property
    def security_scheme(self) -> SecurityScheme:
        return SecurityScheme(
            auth_type="oauth2",
            auth_scheme=None,
            description="OAuth 2.0 token exchange with delegated scopes",
            metadata={"exchange_endpoint": self.exchange_endpoint},
        )

    def __init__(self, exchange_endpoint: str, client_id: str, client_secret: str):
        """Initialize OAuth 2.0 delegation auth.

        Args:
            exchange_endpoint: Token exchange endpoint URL
            client_id: OAuth client ID
            client_secret: OAuth client secret
        """
        self.exchange_endpoint = exchange_endpoint
        self.client_id = client_id
        self.client_secret = client_secret

    async def authenticate(self, credentials: str) -> SecurityContext:
        """Exchange user token for delegated agent token.

        Args:
            credentials: User-level token to exchange

        Returns:
            AuthContext with delegated scopes
        """
        try:
            import httpx

            # Exchange token (simplified - in production use proper OAuth library)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.exchange_endpoint,
                    json={
                        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                        "subject_token": credentials,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )

                if response.status_code != 200:
                    raise Exception(f"Token exchange failed: {response.text}")

                result = response.json()

                return SecurityContext(
                    principal_id=result.get("sub", "unknown"),
                    token=result.get("access_token", ""),
                    expires_at=result.get("expires_in"),
                    metadata=result.get("metadata", {}),
                )
        except Exception as e:
            raise Exception(f"OAuth delegation failed: {e}")  # noqa: B904

    async def refresh_token(self, context: SecurityContext) -> SecurityContext:
        """Refresh delegated token.

        Args:
            context: Current delegated context

        Returns:
            New delegated context with refreshed token
        """
        # In real implementation, would call refresh endpoint
        # For now, return existing context
        return context


class APIKeyAuth(Authenticator):
    """Simple API key authentication.

    Validates API keys against a list of known keys.
    Suitable for service-to-service authentication.
    """

    @property
    def security_scheme(self) -> SecurityScheme:
        return SecurityScheme(
            auth_type="apiKey",
            auth_scheme=None,
            description="Simple API key authentication",
        )

    def __init__(self, valid_keys: dict[str, list[str]]):
        """Initialize API key auth.

        Args:
            valid_keys: Dict mapping keys to scope lists
                       e.g., {"key-123": ["abc..."]}
        """
        self.valid_keys = valid_keys

    async def authenticate(self, credentials: str) -> SecurityContext:
        """Validate API key.

        Args:
            credentials: API key string

        Returns:
            AuthContext if key is valid
        """
        if credentials not in self.valid_keys:
            raise Exception("Invalid API key")

        return SecurityContext(principal_id=f"api-key-{credentials[:8]}", token=credentials)

    async def refresh_token(self, context: SecurityContext) -> SecurityContext:
        """API keys don't refresh.

        Args:
            context: Current context

        Returns:
            Same context
        """
        return context


class BasicAuth(Authenticator):
    """HTTP Basic Authentication (username & password).

    Validates username and password credentials.
    """

    def __init__(self, valid_credentials: dict[str, str]):
        """Initialize with a dictionary mapping username -> password."""
        self.valid_credentials = valid_credentials

    @property
    def security_scheme(self) -> SecurityScheme:
        return SecurityScheme(
            auth_type="http",
            auth_scheme="basic",
            description="HTTP Basic authentication (username:password)",
        )

    async def authenticate(self, credentials: str) -> SecurityContext:
        """Authenticate base64 encoded username:password string or raw username:password.

        Args:
            credentials: Base64 encoded 'username:password' string, or raw 'username:password'
        """
        import base64

        decoded = credentials
        # Check if it looks like base64
        try:
            # Try to decode from base64 first
            decoded_bytes = base64.b64decode(credentials.encode("utf-8"), validate=True)
            decoded = decoded_bytes.decode("utf-8")
        except Exception:
            # If not valid base64, assume it is already decoded
            pass

        if ":" not in decoded:
            raise Exception("Invalid Basic authentication format")

        username, password = decoded.split(":", 1)
        if username not in self.valid_credentials or self.valid_credentials[username] != password:
            raise Exception("Invalid username or password")

        return SecurityContext(principal_id=username, token=credentials)

    async def refresh_token(self, context: SecurityContext) -> SecurityContext:
        """Basic credentials don't refresh."""
        return context


def extract_credentials(headers: Any, query_params: dict[str, str] | None = None) -> str | None:
    """Helper to extract credentials from headers or query parameters.

    Looks for:
    1. 'Authorization' header: extracts value after 'Bearer ', 'Basic ', 'ApiKey ' prefix (or raw if no prefix)
    2. 'X-API-Key' / 'x-api-key' header
    3. 'api_key' / 'apikey' query parameter
    """
    if headers is not None:
        auth_header = None
        if hasattr(headers, "get"):
            auth_header = headers.get("authorization") or headers.get("Authorization")
        else:
            # Fallback for dict/list-like headers
            for k, v in headers:
                if k.lower() == "authorization":
                    auth_header = v
                    break

        if auth_header:
            for prefix in ["Bearer ", "Basic ", "ApiKey ", "apikey "]:
                if auth_header.lower().startswith(prefix.lower()):
                    return auth_header[len(prefix) :].strip()
            return auth_header.strip()

        api_key_header = None
        if hasattr(headers, "get"):
            api_key_header = headers.get("x-api-key") or headers.get("X-API-Key")
        else:
            for k, v in headers:
                if k.lower() == "x-api-key":
                    api_key_header = v
                    break
        if api_key_header:
            return api_key_header.strip()

    if query_params:
        for key in ["api_key", "apikey", "token"]:
            if key in query_params:
                return query_params[key].strip()

    return None
