"""Security middleware for the A2A protocol."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware import Middleware
from fastapi.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.base import RequestEndpoint
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import (
    APIKeyAuthenticator,
    AuthRequest,
    AuthResponse,
    AuthToken,
    Authenticator,
    JWTAuthenticator,
    TokenAuthenticator,
)
from .crypto import (
    CryptoError,
    HashAlgorithm,
    KeyManager,
    KeyPair,
    KeyType,
    sign_message,
    verify_signature,
)

logger = logging.getLogger(__name__)


class SecurityMiddlewareError(Exception):
    """Base exception for security middleware errors."""

    pass


class SecurityConfig(BaseModel):
    """Configuration for security middleware."""

    enabled: bool = True
    require_authentication: bool = True
    require_signature: bool = True
    require_encryption: bool = False
    allowed_algorithms: List[str] = ["RS256", "ES256", "HS256"]
    token_expiry_minutes: int = 60 * 24  # 1 day
    key_manager: Optional[KeyManager] = None
    authenticator: Optional[Authenticator] = None
    excluded_paths: List[str] = ["/health", "/docs", "/openapi.json", "/redoc"]

    class Config:
        arbitrary_types_allowed = True


@dataclass
class SecurityContext:
    """Security context for the current request."""

    is_authenticated: bool = False
    is_authorized: bool = False
    is_encrypted: bool = False
    is_signed: bool = False
    auth_token: Optional[AuthToken] = None
    auth_metadata: Dict[str, Any] = field(default_factory=dict)
    signing_key: Optional[KeyPair] = None
    encryption_key: Optional[KeyPair] = None
    request_metadata: Dict[str, Any] = field(default_factory=dict)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Security middleware for the A2A protocol.
    
    This middleware handles:
    - Request authentication
    - Message signing and verification
    - Request/response encryption
    - Rate limiting
    """

    def __init__(
        self,
        app: ASGIApp,
        config: Optional[SecurityConfig] = None,
    ) -> None:
        """Initialize the security middleware.
        
        Args:
            app: The ASGI application
            config: Security configuration
        """
        super().__init__(app)
        self.config = config or SecurityConfig()
        self._init_authenticator()
        self._init_key_manager()

    def _init_authenticator(self) -> None:
        """Initialize the authenticator if not provided."""
        if self.config.authenticator is None:
            # Default to API key authenticator if no authenticator is provided
            self.config.authenticator = APIKeyAuthenticator()

    def _init_key_manager(self) -> None:
        """Initialize the key manager if not provided."""
        if self.config.key_manager is None:
            self.config.key_manager = KeyManager()
            
            # Generate a default key pair if none exists
            try:
                self.config.key_manager.generate_key(
                    key_type=KeyType.RSA,
                    key_size=4096,
                    metadata={"purpose": "default_signing_key"}
                )
                logger.info("Generated default RSA key pair for signing")
            except Exception as e:
                logger.warning(f"Failed to generate default key pair: {e}")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process the request and response through the security middleware."""
        # Skip security for excluded paths
        if any(request.url.path.startswith(path) for path in self.config.excluded_paths):
            return await call_next(request)
            
        # Initialize security context
        security_ctx = SecurityContext()
        request.state.security = security_ctx
        
        try:
            # Process the request
            response = await self._process_request(request, call_next, security_ctx)
            
            # Process the response
            return await self._process_response(request, response, security_ctx)
            
        except SecurityMiddlewareError as e:
            logger.warning(f"Security error: {e}")
            return Response(
                content=json.dumps({"error": "Unauthorized", "detail": str(e)}),
                status_code=status.HTTP_401_UNAUTHORIZED,
                media_type="application/json",
            )
            
        except Exception as e:
            logger.error(f"Unexpected error in security middleware: {e}", exc_info=True)
            return Response(
                content=json.dumps({"error": "Internal Server Error"}),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                media_type="application/json",
            )
    
    async def _process_request(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
        security_ctx: SecurityContext,
    ) -> Response:
        """Process the incoming request."""
        # Skip if security is disabled
        if not self.config.enabled:
            return await call_next(request)
        
        # Authenticate the request
        if self.config.require_authentication:
            await self._authenticate_request(request, security_ctx)
        
        # Verify message signature if required
        if self.config.require_signature:
            await self._verify_request_signature(request, security_ctx)
            
        # Decrypt the request if needed
        if self.config.require_encryption:
            await self._decrypt_request(request, security_ctx)
        
        # Process the request
        response = await call_next(request)
        
        return response
    
    async def _process_response(
        self,
        request: Request,
        response: Response,
        security_ctx: SecurityContext,
    ) -> Response:
        """Process the outgoing response."""
        # Skip if security is disabled
        if not self.config.enabled:
            return response
            
        # Encrypt the response if needed
        if self.config.require_encryption:
            response = await self._encrypt_response(request, response, security_ctx)
            
        # Sign the response if needed
        if self.config.require_signature:
            response = await self._sign_response(request, response, security_ctx)
            
        # Add security headers
        self._add_security_headers(response)
        
        return response
    
    async def _authenticate_request(
        self,
        request: Request,
        security_ctx: SecurityContext,
    ) -> None:
        """Authenticate the request."""
        if not self.config.authenticator:
            return
            
        try:
            # Create auth request
            auth_request = AuthRequest(
                method=request.method,
                url=str(request.url),
                headers=dict(request.headers),
                body=await request.body(),
            )
            
            # Authenticate the request
            auth_response = await self.config.authenticator.authenticate(auth_request)
            
            if not auth_response or not auth_response.is_authenticated:
                raise SecurityMiddlewareError("Authentication failed")
                
            # Update security context
            security_ctx.is_authenticated = True
            security_ctx.auth_token = auth_response.token
            security_ctx.auth_metadata = auth_response.metadata or {}
            
            # Check if token is expired
            if security_ctx.auth_token and security_ctx.auth_token.is_expired():
                raise SecurityMiddlewareError("Token has expired")
                
        except Exception as e:
            logger.warning(f"Authentication failed: {e}")
            if self.config.require_authentication:
                raise SecurityMiddlewareError("Authentication required") from e
    
    async def _verify_request_signature(
        self,
        request: Request,
        security_ctx: SecurityContext,
    ) -> None:
        """Verify the request signature."""
        try:
            # Get the signature from headers
            signature = request.headers.get("X-Signature")
            key_id = request.headers.get("X-Key-Id")
            algorithm = request.headers.get("X-Signature-Algorithm", "RS256")
            
            if not signature or not key_id:
                if self.config.require_signature:
                    raise SecurityMiddlewareError("Missing required signature headers")
                return
                
            # Get the public key
            try:
                key_pair = self.config.key_manager.get_key(key_id)
                public_key = key_pair.public_key
                security_ctx.signing_key = key_pair
            except Exception as e:
                raise SecurityMiddlewareError(f"Invalid key ID: {key_id}") from e
                
            # Get the message to sign
            message = await self._get_signing_message(request)
            
            # Verify the signature
            if not verify_signature(
                message=message,
                signature=signature.encode(),
                public_key=public_key,
                algorithm=algorithm,
            ):
                raise SecurityMiddlewareError("Invalid signature")
                
            security_ctx.is_signed = True
            
        except SecurityMiddlewareError:
            if self.config.require_signature:
                raise
                
        except Exception as e:
            logger.error(f"Error verifying signature: {e}", exc_info=True)
            if self.config.require_signature:
                raise SecurityMiddlewareError("Failed to verify signature") from e
    
    async def _get_signing_message(self, request: Request) -> bytes:
        """Get the message to be signed."""
        # Include method, path, headers, and body in the signature
        parts = [
            request.method.encode(),
            request.url.path.encode(),
            json.dumps(dict(request.headers), sort_keys=True).encode(),
            await request.body(),
        ]
        return b"\n".join(parts)
    
    async def _decrypt_request(
        self,
        request: Request,
        security_ctx: SecurityContext,
    ) -> None:
        """Decrypt the request body if needed."""
        # Implementation for request decryption
        # This would involve checking for an encryption header,
        # getting the appropriate key, and decrypting the body
        pass  # Placeholder for decryption logic
    
    async def _encrypt_response(
        self,
        request: Request,
        response: Response,
        security_ctx: SecurityContext,
    ) -> Response:
        """Encrypt the response body if needed."""
        # Implementation for response encryption
        # This would involve getting the appropriate key,
        # encrypting the body, and setting the appropriate headers
        return response  # Placeholder for encryption logic
    
    async def _sign_response(
        self,
        request: Request,
        response: Response,
        security_ctx: SecurityContext,
    ) -> Response:
        """Sign the response."""
        if not security_ctx.signing_key:
            # Use the default key if no specific key is set
            try:
                # Get the first available key for signing
                keys = self.config.key_manager.list_keys()
                if not keys:
                    logger.warning("No signing keys available")
                    return response
                    
                key_id = next(iter(keys))
                security_ctx.signing_key = self.config.key_manager.get_key(key_id)
            except Exception as e:
                logger.error(f"Failed to get signing key: {e}")
                return response
        
        try:
            # Get the response body
            if hasattr(response, "body"):
                body = response.body
            elif hasattr(response, "body_iterator"):
                # For streaming responses, we'd need to collect the chunks
                # This is a simplified version
                body = b"".join([chunk async for chunk in response.body_iterator])
                response.body_iterator = [body]  # Reset the iterator
            else:
                body = b""
            
            # Create the message to sign
            message = self._get_response_signing_message(response, body)
            
            # Sign the message
            signature = sign_message(
                message=message,
                private_key=security_ctx.signing_key.private_key,
                algorithm="RS256",  # Default to RS256
            )
            
            # Add signature headers
            response.headers["X-Signature"] = base64.b64encode(signature).decode()
            response.headers["X-Key-Id"] = security_ctx.signing_key.key_id
            response.headers["X-Signature-Algorithm"] = "RS256"
            
            security_ctx.is_signed = True
            
        except Exception as e:
            logger.error(f"Failed to sign response: {e}", exc_info=True)
            
        return response
    
    def _get_response_signing_message(self, response: Response, body: bytes) -> bytes:
        """Get the message to be signed for the response."""
        # Include status code, headers, and body in the signature
        parts = [
            str(response.status_code).encode(),
            json.dumps(dict(response.headers), sort_keys=True).encode(),
            body,
        ]
        return b"\n".join(parts)
    
    def _add_security_headers(self, response: Response) -> None:
        """Add security-related headers to the response."""
        # Security headers
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self';",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        }
        
        # Add headers to response
        for key, value in headers.items():
            if key not in response.headers:
                response.headers[key] = value


def setup_security_middleware(
    app: FastAPI,
    config: Optional[SecurityConfig] = None,
) -> None:
    """Set up security middleware for the FastAPI application.
    
    Args:
        app: The FastAPI application
        config: Security configuration
    """
    # Create middleware instance
    middleware = SecurityMiddleware(app, config=config)
    
    # Add middleware to the app
    app.add_middleware(
        SecurityMiddleware,
        config=config,
    )
    
    # Add security-related dependencies
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        return await middleware.dispatch(request, call_next)
    
    # Add security-related endpoints
    @app.get("/.well-known/security.txt")
    async def security_txt():
        """Return security contact information."""
        return Response(
            content="""Contact: security@example.com\nExpires: 2025-12-31T23:00:00.000Z\n""",
            media_type="text/plain",
        )
    
    # Add security headers to all responses
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        
        # Add security headers
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self';",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        }
        
        for key, value in security_headers.items():
            response.headers[key] = value
            
        return response
