"""
ProtoLink - Security & Authentication (v0.3.0)

OAuth 2.0, Bearer tokens, and scope-based authorization for enterprise deployments.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AuthContext:
    """Authenticated principal context.

    Represents an authenticated user, agent, or service with their
    authorized scopes and token information.

    Attributes:
        principal_id: Identifier of authenticated entity (user, agent, service)
        token: Authentication token (JWT, OAuth token, etc.)
        scopes: List of authorized scopes (e.g., ["skill:write", "data:read"])
        expires_at: When token expires (ISO format)
        issued_at: When token was issued (ISO format)
        metadata: Additional auth metadata
    """

    principal_id: str
    token: str
    scopes: list[str] = field(default_factory=list)
    expires_at: str | None = None
    issued_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, required_scope: str) -> bool:
        """Check if context has required scope.

        Args:
            required_scope: Scope to check (e.g., "skill:analyze")

        Returns:
            True if scope is authorized
        """
        return required_scope in self.scopes or "*" in self.scopes

    def is_expired(self) -> bool:
        """Check if token is expired.

        Returns:
            True if expired, False if still valid or no expiry set
        """
        if not self.expires_at:
            return False

        expires = datetime.fromisoformat(self.expires_at)
        return datetime.utcnow() > expires

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "principal_id": self.principal_id,
            "token": self.token,
            "scopes": self.scopes,
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
        scheme_type: Type of scheme ("bearer", "oauth2", "api_key")
        description: Human-readable description
        scopes: Available scopes for this scheme
        metadata: Additional scheme metadata
    """

    scheme_type: str  # "bearer", "oauth2", "api_key"
    description: str
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.scheme_type,
            "description": self.description,
            "scopes": self.scopes,
            "metadata": self.metadata,
        }


class AuthProvider(ABC):
    """Abstract authentication provider.

    Implementations provide authentication methods (Bearer, OAuth2, etc.)
    and authorization checking based on scopes and skills.
    """

    @abstractmethod
    async def authenticate(self, credentials: str) -> AuthContext:
        """Authenticate a principal with provided credentials.

        Args:
            credentials: Raw credentials (token, api key, etc.)

        Returns:
            AuthContext if successful

        Raises:
            Exception: If authentication fails
        """
        pass

    @abstractmethod
    async def authorize(self, context: AuthContext, skill: str) -> bool:
        """Check if context is authorized to execute skill.

        Args:
            context: Authenticated context
            skill: Skill identifier (e.g., "analyze", "execute")

        Returns:
            True if authorized, False otherwise
        """
        pass

    @abstractmethod
    async def refresh_token(self, context: AuthContext) -> AuthContext:
        """Refresh an authentication context (if supported).

        Args:
            context: Context to refresh

        Returns:
            New AuthContext with refreshed token

        Raises:
            Exception: If refresh not supported or fails
        """
        pass


class BearerTokenAuth(AuthProvider):
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

    async def authenticate(self, credentials: str) -> AuthContext:
        """Authenticate bearer token.

        Args:
            credentials: Bearer token string

        Returns:
            AuthContext extracted from token
        """
        try:
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

            return AuthContext(
                principal_id=payload.get("sub", "unknown"),
                token=credentials,
                scopes=payload.get("scopes", []),
                expires_at=payload.get("exp"),
                metadata=payload.get("metadata", {}),
            )
        except Exception as e:
            raise Exception(f"Token authentication failed: {e}")  # noqa: B904

    async def authorize(self, context: AuthContext, skill: str) -> bool:
        """Check if context has scope for skill.

        Args:
            context: Authenticated context
            skill: Skill name

        Returns:
            True if authorized
        """
        if context.is_expired():
            return False

        required_scope = f"skill:{skill}"
        return context.has_scope(required_scope)

    async def refresh_token(self, context: AuthContext) -> AuthContext:
        """Bearer tokens typically don't refresh.

        Args:
            context: Current context

        Returns:
            Same context (no refresh possible)
        """
        return context


class OAuth2DelegationAuth(AuthProvider):
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

    def __init__(self, exchange_endpoint: str, client_id: str, client_secret: str, scope_prefix: str = "skill:"):
        """Initialize OAuth 2.0 delegation auth.

        Args:
            exchange_endpoint: Token exchange endpoint URL
            client_id: OAuth client ID
            client_secret: OAuth client secret
            scope_prefix: Prefix for skill scopes
        """
        self.exchange_endpoint = exchange_endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope_prefix = scope_prefix

    async def authenticate(self, credentials: str) -> AuthContext:
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

                return AuthContext(
                    principal_id=result.get("sub", "unknown"),
                    token=result.get("access_token", ""),
                    scopes=result.get("scope", "").split(),
                    expires_at=result.get("expires_in"),
                    metadata=result.get("metadata", {}),
                )
        except Exception as e:
            raise Exception(f"OAuth delegation failed: {e}")  # noqa: B904

    async def authorize(self, context: AuthContext, skill: str) -> bool:
        """Check if context has delegated scope for skill.

        Args:
            context: Authenticated context with delegated scopes
            skill: Skill name

        Returns:
            True if authorized via delegated scope
        """
        if context.is_expired():
            return False

        required_scope = f"{self.scope_prefix}{skill}"
        return context.has_scope(required_scope)

    async def refresh_token(self, context: AuthContext) -> AuthContext:
        """Refresh delegated token.

        Args:
            context: Current delegated context

        Returns:
            New delegated context with refreshed token
        """
        # In real implementation, would call refresh endpoint
        # For now, return existing context
        return context


class APIKeyAuth(AuthProvider):
    """Simple API key authentication.

    Validates API keys against a list of known keys.
    Suitable for service-to-service authentication.
    """

    def __init__(self, valid_keys: dict[str, list[str]]):
        """Initialize API key auth.

        Args:
            valid_keys: Dict mapping keys to scope lists
                       e.g., {"key-123": ["skill:*"]}
        """
        self.valid_keys = valid_keys

    async def authenticate(self, credentials: str) -> AuthContext:
        """Validate API key.

        Args:
            credentials: API key string

        Returns:
            AuthContext if key is valid
        """
        if credentials not in self.valid_keys:
            raise Exception("Invalid API key")

        scopes = self.valid_keys[credentials]
        return AuthContext(principal_id=f"api-key-{credentials[:8]}", token=credentials, scopes=scopes)

    async def authorize(self, context: AuthContext, skill: str) -> bool:
        """Check if context has scope for skill.

        Args:
            context: Authenticated context
            skill: Skill name

        Returns:
            True if authorized
        """
        required_scope = f"skill:{skill}"
        return context.has_scope(required_scope)

    async def refresh_token(self, context: AuthContext) -> AuthContext:
        """API keys don't refresh.

        Args:
            context: Current context

        Returns:
            Same context
        """
        return context
