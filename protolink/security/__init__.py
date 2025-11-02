"""Security module for the A2A protocol.

This module provides security features for agent communication, including:
- Authentication (API Key, JWT, Token)
- Message signing and verification
- Request/response encryption
- Security middleware for FastAPI applications

## Authentication

The module provides several authenticator implementations:
- `APIKeyAuthenticator`: Authenticate using API keys
- `JWTAuthenticator`: Authenticate using JSON Web Tokens (JWT)
- `TokenAuthenticator`: Authenticate using opaque tokens

## Cryptography

Cryptographic utilities for:
- Key generation and management
- Message signing and verification
- Symmetric and asymmetric encryption

## Middleware

Security middleware for FastAPI applications that handles:
- Request authentication
- Message signing and verification
- Request/response encryption
- Security headers

## Example Usage

```python
from fastapi import FastAPI
from protolink.security import (
    SecurityConfig,
    setup_security_middleware,
    KeyManager,
    KeyType,
    APIKeyAuthenticator
)

app = FastAPI()

# Setup security
config = SecurityConfig(
    require_authentication=True,
    require_signature=True,
    authenticator=APIKeyAuthenticator()
)

# Initialize key manager
key_manager = KeyManager()
key_manager.generate_key(
    key_type=KeyType.RSA,
    key_size=4096,
    metadata={"purpose": "api_signing"}
)

# Add security middleware
setup_security_middleware(app, config=config)
```
"""

from .auth import (
    AuthToken,
    AuthRequest,
    AuthResponse,
    Authenticator,
    APIKeyAuthenticator,
    JWTAuthenticator,
    TokenAuthenticator,
)

from .crypto import (
    CryptoError,
    KeyNotFoundError,
    InvalidKeyError,
    KeyType,
    KeyUsage,
    HashAlgorithm,
    KeyPair,
    KeyManager,
    sign_message,
    verify_signature,
    generate_key_pair,
    encrypt_message,
    decrypt_message,
)

from .middleware import (
    SecurityConfig,
    SecurityContext,
    SecurityMiddleware,
    SecurityMiddlewareError,
    setup_security_middleware,
    AuthMiddleware,
    MessageSigningMiddleware,
    EncryptionMiddleware,
)

__all__ = [
    # Auth
    'AuthToken',
    'AuthRequest',
    'AuthResponse',
    'Authenticator',
    'APIKeyAuthenticator',
    'JWTAuthenticator',
    'TokenAuthenticator',
    'AuthenticationError',
    
    # Crypto
    'CryptoError',
    'KeyNotFoundError',
    'InvalidKeyError',
    'KeyType',
    'KeyUsage',
    'HashAlgorithm',
    'KeyPair',
    'KeyManager',
    'sign_message',
    'verify_signature',
    'generate_key_pair',
    'encrypt_message',
    'decrypt_message',
    
    # Middleware
    'SecurityConfig',
    'SecurityContext',
    'SecurityMiddleware',
    'SecurityMiddlewareError',
    'setup_security_middleware',
    'AuthMiddleware',
    'MessageSigningMiddleware',
    'EncryptionMiddleware',
]
