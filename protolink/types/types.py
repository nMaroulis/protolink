"""
ProtoLink Type Aliases

This module contains shared type aliases used throughout the Protolink framework.
Centralizing types improves reusability, discoverability, and maintainability.
"""


from typing import Literal, TypeAlias

BackendType: TypeAlias = Literal["starlette", "fastapi"]

LLMProvider: TypeAlias = Literal["openai", "anthropic", "google", "llama.cpp", "ollama"]

LLMType: TypeAlias = Literal["api", "local", "server"]


# Supported Agent IO formats
MimeType: TypeAlias = Literal[
    # Text
    "text/plain",
    "text/markdown",
    "text/html",
    # JSON / structured
    "application/json",
    # Images
    "image/png",
    "image/jpeg",
    "image/webp",
    # Audio
    "audio/wav",
    "audio/mpeg",
    "audio/ogg",
    # Video (rare, but supported)
    "video/mp4",
    "video/webm",
    # Files for RAG
    "application/pdf",
]

# Supported roles in Messages
RoleType: TypeAlias = Literal["user", "agent", "system"]

# Supported security schemes
SecuritySchemeType: TypeAlias = Literal[
    "apiKey",  # API key
    "http",  # bearer / basic / digest
    "oauth2",  # full OAuth OAuth2
    "mutualTLS",  # certificates
    "openIdConnect",  # OIDC auto-discovery
]
