"""
ProtoLink Type Aliases

This module contains shared type aliases used throughout the Protolink framework.
Centralizing types improves reusability, discoverability, and maintainability.
"""

from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    from protolink.agents.base import Agent
    from protolink.flows.base import Flow

AgentRoleType: TypeAlias = Literal["gateway", "interface", "observer", "orchestrator", "worker"]

BackendType: TypeAlias = Literal["starlette", "fastapi"]

ContentType: TypeAlias = Literal[
    "application/json",
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
]

HttpAuthScheme: TypeAlias = Literal[
    "bearer",  # OAuth access token
    "basic",  # username:password
    "digest",  # challenge-response
    "hmac",  # custom HMAC headers (some APIs put it under http)
    "negotiate",  # Kerberos / SPNEGO
    "ntlm",  # NT LAN Manager protocol
    # Vendor-specific
    "aws4auth",  # AWS SigV4
    "hawk",  # HAWK MAC authentication
    "edgegrid",  # Akamai
]

HttpMethod: TypeAlias = Literal["GET", "POST", "DELETE", "PUT", "PATCH"]

LLMProvider: TypeAlias = Literal[
    "anthropic",
    "deepseek",
    "gemini",
    "grok",
    "huggingface",
    "llama.cpp-local",
    "llama.cpp-server",
    "lmstudio",
    "mock",
    "ollama",
    "openai",
    "openai-compatible",
    "vllm",
]

LLMType: TypeAlias = Literal["api", "local", "server"]

# State Modes for Agent States, used by the Agent class.
StateMode: TypeAlias = Literal["conversation", "tools", "task", "flow"]

# Supported roles in Messages
MessageRoleType: TypeAlias = Literal["agent", "assistant", "system", "user"]

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

# Reasoning | Chain-of-thought level for LLMs
ReasoningLevel: TypeAlias = Literal["none", "low", "medium", "high"]

# Supported request sources for endpoints
RequestSourceType: TypeAlias = Literal[
    "none",
    "body",
    "query_params",
    "form",
    "headers",
    "path_params",
    "request",
]

# Supported part content types
PartType: TypeAlias = Literal[
    # ---- Core content ----
    "text",
    "json",
    # ---- Files & references ----
    "file",
    "bytes",
    "uri",
    # ---- Media ----
    "image",
    "audio",
    "video",
    # ---- Control & meta ----
    "status",
    "error",
    "warning",
    "route",
    "decision",
    # ---- LLM Call ----
    "infer",
    "infer_output",
    # ---- Tool interaction ----
    "tool_call",
    "tool_output",
    # ---- Reasoning / observability (optional) ----
    "trace",
    "summary",
    "confidence",
    # ---- Contracts ----
    "schema",
]

# Supported security schemes
SecuritySchemeType: TypeAlias = Literal[
    "apiKey",  # API key
    "http",  # bearer / basic / digest
    "oauth2",  # full OAuth OAuth2
    "mutualTLS",  # certificates
    "openIdConnect",  # OIDC auto-discovery
]

TransportType: TypeAlias = Literal["http", "websocket", "sse", "json-rpc", "sse-json-rpc", "grpc", "runtime"]

FlowTarget: TypeAlias = "Agent | str | Flow"
