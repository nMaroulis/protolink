"""Authentication module for the A2A protocol."""

from __future__ import annotations

import abc
import base64
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import jwt
from pydantic import BaseModel, Field, validator


class AuthenticationError(Exception):
    """Base exception for authentication errors."""
    pass


class AuthToken(BaseModel):
    """Authentication token."""
    
    token: str = Field(..., description="The authentication token")
    token_type: str = Field(default="bearer", description="Type of the token")
    expires_at: Optional[datetime] = Field(
        default=None,
        description="When the token expires"
    )
    
    @property
    def is_expired(self) -> bool:
        """Check if the token is expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() >= self.expires_at


class AuthRequest(BaseModel):
    """Authentication request."""
    
    method: str = Field(..., description="Authentication method")
    credentials: Dict[str, Any] = Field(
        default_factory=dict,
        description="Authentication credentials"
    )


class AuthResponse(BaseModel):
    """Authentication response."""
    
    success: bool = Field(..., description="Whether authentication was successful")
    token: Optional[AuthToken] = Field(
        default=None,
        description="Authentication token if successful"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if authentication failed"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional authentication metadata"
    )


class Authenticator(abc.ABC):
    """Base class for authenticators."""
    
    @abc.abstractmethod
    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        """Authenticate a request.
        
        Args:
            request: The authentication request
            
        Returns:
            Authentication response
        """
        pass
    
    @abc.abstractmethod
    async def validate_token(self, token: str) -> bool:
        """Validate an authentication token.
        
        Args:
            token: The token to validate
            
        Returns:
            True if the token is valid, False otherwise
        """
        pass


class APIKeyAuthenticator(Authenticator):
    """API key-based authenticator."""
    
    def __init__(
        self,
        api_key: str,
        header_name: str = "X-API-Key",
        query_param: str = "api_key",
    ):
        """Initialize the API key authenticator.
        
        Args:
            api_key: The expected API key
            header_name: Name of the header containing the API key
            query_param: Name of the query parameter containing the API key
        """
        self.api_key = api_key
        self.header_name = header_name
        self.query_param = query_param
    
    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        """Authenticate using an API key."""
        if request.method != "api_key":
            return AuthResponse(
                success=False,
                error=f"Unsupported authentication method: {request.method}"
            )
        
        provided_key = request.credentials.get("api_key")
        if not provided_key:
            return AuthResponse(
                success=False,
                error="API key is required"
            )
        
        # Use constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_key, self.api_key):
            return AuthResponse(
                success=False,
                error="Invalid API key"
            )
        
        # Generate a simple token (in a real implementation, this would be a JWT)
        token = base64.b64encode(hashlib.sha256(f"{provided_key}:{time.time()}".encode()).digest()).decode()
        
        return AuthResponse(
            success=True,
            token=AuthToken(
                token=token,
                token_type="bearer",
                expires_at=datetime.utcnow() + timedelta(hours=1)
            )
        )
    
    async def validate_token(self, token: str) -> bool:
        """Validate an API key token."""
        # In a real implementation, you would validate the token format and signature
        # For API keys, we just check if it matches the expected format
        try:
            # Check if the token is a valid base64 string
            decoded = base64.b64decode(token.encode())
            return len(decoded) == 32  # SHA-256 hash length
        except Exception:
            return False


class JWTAuthenticator(Authenticator):
    """JWT-based authenticator."""
    
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: Optional[str] = None,
        audience: Optional[Union[str, List[str]]] = None,
        leeway: int = 0,
    ):
        """Initialize the JWT authenticator.
        
        Args:
            secret_key: Secret key for signing and verifying tokens
            algorithm: JWT signing algorithm
            issuer: Optional token issuer
            audience: Optional token audience
            leeway: Leeway in seconds for token expiration validation
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience
        self.leeway = leeway
    
    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        """Authenticate using JWT."""
        if request.method != "jwt":
            return AuthResponse(
                success=False,
                error=f"Unsupported authentication method: {request.method}"
            )
        
        token = request.credentials.get("token")
        if not token:
            return AuthResponse(
                success=False,
                error="JWT token is required"
            )
        
        try:
            # Verify the token
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
                leeway=self.leeway,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": self.audience is not None,
                    "verify_iss": self.issuer is not None,
                }
            )
            
            # Check if the token is valid
            return AuthResponse(
                success=True,
                token=AuthToken(
                    token=token,
                    token_type="bearer",
                    expires_at=datetime.fromtimestamp(payload["exp"])
                ),
                metadata={"payload": payload}
            )
            
        except jwt.PyJWTError as e:
            return AuthResponse(
                success=False,
                error=f"Invalid token: {str(e)}"
            )
    
    async def validate_token(self, token: str) -> bool:
        """Validate a JWT token."""
        try:
            jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": self.audience is not None,
                    "verify_iss": self.issuer is not None,
                }
            )
            return True
        except jwt.PyJWTError:
            return False
    
    def create_token(
        self,
        subject: str,
        expires_in: int = 3600,
        issuer: Optional[str] = None,
        audience: Optional[Union[str, List[str]]] = None,
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new JWT token.
        
        Args:
            subject: Subject of the token (usually the user/agent ID)
            expires_in: Token expiration time in seconds
            issuer: Token issuer
            audience: Token audience
            additional_claims: Additional claims to include in the token
            
        Returns:
            The signed JWT token
        """
        now = datetime.utcnow()
        payload = {
            "sub": subject,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=expires_in),
            "jti": hashlib.sha256(f"{subject}:{time.time()}".encode()).hexdigest(),
            **(additional_claims or {})
        }
        
        if issuer:
            payload["iss"] = issuer
        if audience:
            payload["aud"] = audience
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)


class TokenAuthenticator(Authenticator):
    """Simple token-based authenticator."""
    
    def __init__(
        self,
        valid_tokens: Dict[str, Dict[str, Any]],
        token_lifetime: int = 3600,
    ):
        """Initialize the token authenticator.
        
        Args:
            valid_tokens: Dictionary of valid tokens and their metadata
            token_lifetime: Default token lifetime in seconds
        """
        self.valid_tokens = valid_tokens
        self.token_lifetime = token_lifetime
    
    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        """Authenticate using a token."""
        if request.method != "token":
            return AuthResponse(
                success=False,
                error=f"Unsupported authentication method: {request.method}"
            )
        
        token = request.credentials.get("token")
        if not token:
            return AuthResponse(
                success=False,
                error="Token is required"
            )
        
        # Look up the token
        token_info = self.valid_tokens.get(token)
        if not token_info:
            return AuthResponse(
                success=False,
                error="Invalid token"
            )
        
        # Check if the token is expired
        expires_at = token_info.get("expires_at")
        if expires_at and datetime.utcnow() > expires_at:
            return AuthResponse(
                success=False,
                error="Token has expired"
            )
        
        # Create a new token with updated expiration
        expires_at = datetime.utcnow() + timedelta(seconds=self.token_lifetime)
        
        return AuthResponse(
            success=True,
            token=AuthToken(
                token=token,
                token_type="bearer",
                expires_at=expires_at
            ),
            metadata={"token_info": token_info}
        )
    
    async def validate_token(self, token: str) -> bool:
        """Validate a token."""
        if token not in self.valid_tokens:
            return False
        
        expires_at = self.valid_tokens[token].get("expires_at")
        if expires_at and datetime.utcnow() > expires_at:
            return False
        
        return True
