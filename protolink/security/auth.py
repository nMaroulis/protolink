"""
ProtoLink - Security & Authentication

OAuth 2.0, Bearer tokens authorization for enterprise deployments.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from protolink.types import HttpAuthScheme, SecuritySchemeType
from protolink.utils import utc_now


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
        return datetime.now(timezone.utc) > expires

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
    """Bearer token authentication (JWT or opaque).

    Validates bearer tokens against a secret or verification endpoint.
    Suitable for simple deployments with pre-issued tokens.

    Example:
        auth = BearerTokenAuth(
            secret="your-secret-key",
            algorithm="HS256"
        )
        context = await auth.authenticate(token)
    """

    def __init__(self, secret: str = "", algorithm: str = "HS256"):
        """Initialize bearer token auth.

        Args:
            secret: Secret key for JWT validation
            algorithm: JWT algorithm (HS256, RS256, etc.)
        """
        self.secret = secret
        self.algorithm = algorithm

    async def authenticate(self, credentials: str) -> SecurityContext:
        """Authenticate bearer token.

        Args:
            credentials: Bearer token string

        Returns:
            AuthContext extracted from token
        """
        try:
            # TODO(): Implement proper JWT validation
            # For demo: parse JWT format (in production, use PyJWT)
            # Expected format: header.payload.signature
            parts = credentials.split(".")
            if len(parts) != 3:
                raise ValueError("Invalid token format")

            # Decode payload (base64)
            import base64

            payload_str = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload_bytes = base64.urlsafe_b64decode(payload_str)
            payload = json.loads(payload_bytes)

            return SecurityContext(
                principal_id=payload.get("sub", "unknown"),
                token=credentials,
                expires_at=payload.get("exp"),
                metadata=payload.get("metadata", {}),
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
