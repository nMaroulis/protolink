# Type Aliases API Reference

This section provides detailed documentation for the type aliases used throughout the Protolink framework. Type aliases improve code readability, provide type safety, and make the API more consistent across different modules.

## Table of Contents

- [BackendType](#backendtype)
- [LLMProvider](#llmprovider)
- [LLMType](#llmtype)
- [MimeType](#mimetype)
- [RoleType](#roletype)
- [SecuritySchemeType](#securityschemetype)

---

## BackendType

```python
BackendType: TypeAlias = Literal["starlette", "fastapi"]
```

Type alias for supported HTTP backend implementations in Protolink transports.

### Supported Backends

| Backend | Description |
|---------|-------------|
| **starlette** | Lightweight ASGI framework (default) |
| **fastapi** | Full-featured API framework with automatic validation |

### Usage Example

```python
from protolink.types import BackendType
from protolink.transport import HTTPTransport

# Use Starlette backend (default)
transport = HTTPTransport(backend="starlette")

# Use FastAPI backend for automatic validation
transport = HTTPTransport(backend="fastapi", validate_schema=True)
```

---

## LLMProvider

```python
LLMProvider: TypeAlias = Literal["openai", "anthropic", "google", "llama.cpp", "ollama"]
```

Type alias for supported Large Language Model providers in Protolink.

### Supported Providers

| Provider | Description |
|----------|-------------|
| **openai** | OpenAI API (GPT models) |
| **anthropic** | Anthropic Claude API |
| **google** | Google AI models |
| **llama.cpp** | Local LLaMA models |
| **ollama** | Ollama local models |

### Usage Example

```python
from protolink.types import LLMProvider
from protolink.llms.api import OpenAILLM

# Specify provider when creating LLM
llm = OpenAILLM(model="gpt-4", provider="openai")
```

---

## LLMType

```python
LLMType: TypeAlias = Literal["api", "local", "server"]
```

Type alias for different types of LLM deployment methods.

### LLM Types

| Type | Description |
|------|-------------|
| **api** | Cloud-based API models |
| **local** | Local model execution |
| **server** | Self-hosted server models |

### Usage Example

```python
from protolink.types import LLMType

# Different LLM deployment types
api_llm = OpenAILLM(model="gpt-4")  # API type
local_llm = LocalLLM(model_path="./model.gguf")  # Local type
server_llm = ServerLLM(endpoint="http://localhost:8080")  # Server type
```

---

## MimeType

Type alias for supported MIME types in Protolink. These are used to specify the **input** and **output** **formats** that agents can handle.

### Supported Types

| Category | MIME Types |
|----------|------------|
| **Text** | `text/plain`, `text/markdown`, `text/html` |
| **Structured Data** | `application/json` |
| **Images** | `image/png`, `image/jpeg`, `image/webp` |
| **Audio** | `audio/wav`, `audio/mpeg`, `audio/ogg` |
| **Video** | `video/mp4`, `video/webm` |
| **Documents** | `application/pdf` |

### Usage Example

```python
from protolink.types import MimeType
from protolink.models import AgentCard

# Specify supported formats in AgentCard
card = AgentCard(
    name="multimedia-agent",
    description="Agent that handles various media formats",
    url="http://localhost:8000",
    input_formats=["text/plain", "application/json", "image/png"],
    output_formats=["text/plain", "application/json", "image/jpeg"]
)
```

---

## RoleType

```python
RoleType: TypeAlias = Literal["user", "agent", "system"]
```

Type alias for supported message roles in agent communication.

### Message Roles

| Role | Description |
|------|-------------|
| **user** | Human user messages |
| **agent** | Agent responses |
| **system** | System instructions |

### Usage Example

```python
from protolink.types import RoleType
from protolink.models import Message

# Create messages with different roles
user_msg = Message(role="user", content="Hello, how are you?")
agent_msg = Message(role="agent", content="I'm doing well, thank you!")
system_msg = Message(role="system", content="You are a helpful assistant.")
```

---

## SecuritySchemeType

Type alias for supported security schemes in Protolink. These are used to specify the **authentication methods** that agents can use.

### Supported Schemes

| Category | Security Schemes |
|----------|------------|
| **API key** | `apiKey` |
| **HTTP** (bearer/basic/digest) | `http` |
| **full OAuth OAuth2** | `oauth2` |
| **Certificates** | `mutualTLS` |
| **OIDC auto-discovery** | `openIdConnect` |

### Usage Example

```python
from protolink.types import SecuritySchemeType
from protolink.models import AgentCard

# Define security schemes in AgentCard
card = AgentCard(
    name="secure-agent",
    description="Agent with multiple auth methods",
    url="http://localhost:8000",
    security_schemes={
        "bearer": {"type": "http", "description": "Bearer token authentication"},
        "api_key": {"type": "apiKey", "description": "API key authentication"},
        "oauth2": {"type": "oauth2", "description": "OAuth 2.0 authentication"}
    }
)
```

---

## Benefits of Type Aliases

Using type aliases in Protolink provides several advantages:

### 1. **Type Safety**
```python
# Compiler catches invalid values
backend: BackendType = "invalid"  # Type error!
```

### 2. **IDE Support**
```python
# Autocomplete shows valid options
transport = HTTPTransport(backend="")  # IDE shows: "starlette" | "fastapi"
```

### 3. **Documentation**
```python
# Clear intent in function signatures
def create_llm(provider: LLMProvider, model: str) -> LLM:
    # Implementation
```

### 4. **Refactoring**
```python
# Easy to update across the entire codebase
BackendType = Literal["starlette", "fastapi", "new_backend"]
```

### 5. **Consistency**
```python
# Same type used across multiple modules
from protolink.types import MimeType
from protolink.models import AgentCard
from protolink.transport import HTTPTransport
```

---

## Importing Types

All type aliases are available from the central types module:

```python
# Import individual types
from protolink.types import MimeType, SecuritySchemeType, RoleType

# Import all types
from protolink.types import BackendType, LLMProvider, LLMType
```

The types module is organized to provide a single source of truth for all shared type definitions in the Protolink framework, making the codebase more maintainable and easier to understand.
