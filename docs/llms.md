# LLMs

Protolink integrates with various LLM backends.

## LLM Types

Protolink groups LLM backends into three broad categories:

- **API** — calls a remote API and requires an API key:
  - `OpenAILLM`: uses the **OpenAI API** for sync & async requests.
  - `AnthropicLLM`: uses the **Anthropic API** for sync & async requests.

- **Local** — runs the model directly in your runtime:
  - `LlamaCPPLLM`: uses a local **llama.cpp** runtime for sync & async requests.

- **Server** — connects to an LLM server, locally or remotely:
  - `OllamaLLM`: connects to an **Ollama** server for sync & async requests.

You can also use other LLM clients directly without going through Protolink’s `LLM` wrappers if you prefer.

## Configuration

Configuration depends on the specific backend, but the general pattern is:

1. **Install the relevant extras** (from the README):

   ```bash
   # All supported LLM backends
   uv add "protolink[llms]"
   ```

   !!! info "Choosing LLM extras"
       If you only need a subset of backends, you can install more targeted extras once they are exposed (for example, only OpenAI or only local backends).

2. **Instantiate the LLM** with the desired model and credentials:

   ```python
   from protolink.llms.api import OpenAILLM


   llm = OpenAILLM(
       model="gpt-5.1",
       # api_key is typically read from the environment, e.g. OPENAI_API_KEY
   )
   ```

   !!! warning "API keys"
       Never commit API keys to version control. Read them from environment variables or a secure secrets manager.

3. **Pass the LLM to your Agent**:

   ```python
   from protolink.agents import Agent
   from protolink.models import AgentCard
   from protolink.transport import HTTPTransport


   agent_card = AgentCard(name="llm_agent", description="Agent backed by an LLM")
   transport = HTTPTransport()

   agent = Agent(agent_card, transport, llm)
   ```

For local and server‑style LLMs (`LlamaCPPLLM`, `OllamaLLM`), configuration additionally includes paths to model files or server URLs. Refer to the corresponding example scripts in `examples/llms.py` for concrete usage patterns.

---

# LLM API Reference

This section provides a detailed API reference for all LLM classes in Protolink. All LLM implementations inherit from the base `LLM` class and provide a consistent interface for generating responses.

!!! success "Unified LLM Interface"
    **Protolink provides a single, consistent API for all LLM providers.** Whether you're using OpenAI, Anthropic, Ollama, or local models, you interact with them through the same methods: `generate_response()`, `generate_stream_response()`, and configuration helpers. This unified approach means you can swap LLM providers without changing your application code - just update the initialization and you're done!

!!! tip "Why Use Protolink's LLM Wrappers?"
    - **Provider Agnostic**: Switch between OpenAI, Anthropic, Ollama, and future providers with minimal code changes
    - **Consistent Interface**: Same method signatures and behavior across all implementations
    - **Built-in Features**: Connection validation, parameter validation, and error handling out of the box
    - **Extensible**: Easy to add new LLM providers while maintaining compatibility
    - **Production Ready**: Robust error handling and logging for real-world applications

!!! example "Provider Switching in Action"
    ```python
    # The same code works with ANY LLM provider
    
    # Choose your provider - just change the import and initialization!
    from protolink.llms.api import OpenAILLM    # or AnthropicLLM
    from protolink.llms.server import OllamaLLM  # or any other provider
    
    # Initialize your chosen LLM
    llm = OpenAILLM(model="gpt-4", temperature=0.7)
    # llm = AnthropicLLM(model="claude-3-sonnet", temperature=0.7)
    # llm = OllamaLLM(model="llama3", temperature=0.7)
    
    # The rest of your code stays EXACTLY the same!
    messages = [Message(role="user", content="Hello!")]
    response = llm.generate_response(messages)
    print(response.content)
    
    # Streaming also works identically
    for chunk in llm.generate_stream_response(messages):
        print(chunk.content, end="", flush=True)
    ```

!!! info "LLM Hierarchy"
    - **`LLM`** (abstract base class)
    - **`APILLM`** (base for API-based LLMs)
    - **`ServerLLM`** (base for server-based LLMs)
    - **Concrete implementations**: `OpenAILLM`, `AnthropicLLM`, `OllamaLLM`, etc.

## Base LLM Class

The `LLM` class defines the common interface that all LLM implementations must follow.

### Attributes

| Attribute | Type | Description |
|-----------|-----|-------------|
| `model_type` | `LLMType` | The type of LLM (`"api"`, `"local"`, or `"server"`). |
| `provider` | `LLMProvider` | The provider name (`"openai"`, `"anthropic"`, `"ollama"`, etc.). |
| `model` | `str` | The model name/identifier. |
| `model_params` | `dict[str, Any]` | Model-specific parameters (temperature, max_tokens, etc.). |
| `system_prompt` | `str` | Default system prompt for the model. |

### Core Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `generate_response()` | `messages: list[Message]` | `Message` | Generate a single response from the model. |
| `generate_stream_response()` | `messages: list[Message]` | `Iterable[Message]` | Generate a streaming response, yielding messages as they're generated. |
| `set_model_params()` | `model_params: dict[str, Any]` | `None` | Update model parameters. |
| `set_system_prompt()` | `system_prompt: str` | `None` | Set the system prompt for the model. |
| `validate_connection()` | — | `bool` | Validate that the LLM connection is working. |

!!! note "Abstract Methods"
    The `LLM` base class is abstract. You should use one of the concrete implementations like `OpenAILLM` or `AnthropicLLM`.

## API-based LLMs

API-based LLMs connect to external services and require API keys or authentication.

### APILLM Base Class

Base class for all API-based LLM implementations.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `set_model_params()` | `model_params: dict[str, Any]` | `None` | Update existing model parameters, ignoring invalid keys. |
| `set_system_prompt()` | `system_prompt: str` | `None` | Set the system prompt for the model. |
| `validate_connection()` | — | `bool` | **Abstract.** Validate API connection (implemented by subclasses). |

### OpenAILLM

OpenAI API implementation using the official OpenAI client.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str \| None` | `None` | OpenAI API key. If not provided, uses `OPENAI_API_KEY` environment variable. |
| `model` | `str \| None` | `"gpt-5"` | OpenAI model name. |
| `model_params` | `dict[str, Any] \| None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str \| None` | `None` | Custom base URL for OpenAI-compatible APIs. |

```python
from protolink.llms.api import OpenAILLM

# Basic usage
llm = OpenAILLM(model="gpt-4")

# With custom parameters
llm = OpenAILLM(
    model="gpt-4-turbo",
    model_params={
        "temperature": 0.7,
        "max_tokens": 1000,
        "top_p": 0.9
    }
)

# With custom base URL (for OpenAI-compatible APIs)
llm = OpenAILLM(
    model="custom-model",
    base_url="https://api.custom-provider.com/v1",
    api_key="your-api-key"
)
```

#### Default Model Parameters

| Parameter | Type | Default | Range/Description |
|-----------|-----|---------|-------------------|
| `temperature` | `float` | `1.0` | `0.0` to `2.0` - Controls randomness |
| `top_p` | `float` | `1.0` | Nucleus sampling parameter |
| `n` | `int` | `1` | Number of completions to generate |
| `stream` | `bool` | `False` | Whether to stream responses |
| `stop` | `str \| list[str] \| None` | `None` | Stop sequences |
| `max_tokens` | `int \| None` | `None` | Maximum tokens to generate |
| `presence_penalty` | `float` | `0.0` | `-2.0` to `2.0` - Presence penalty |
| `frequency_penalty` | `float` | `0.0` | `-2.0` to `2.0` - Frequency penalty |
| `logit_bias` | `dict \| None` | `None` | Token bias dictionary |

#### Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `generate_response()` | `messages: list[Message]` | `Message` | Generate a single response using OpenAI's API. |
| `generate_stream_response()` | `messages: list[Message]` | `Iterable[Message]` | Generate streaming response, yielding partial messages. |
| `validate_connection()` | — | `bool` | Check if the model is available and API key is valid. |

!!! warning "API Key Required"
    OpenAI requires a valid API key. Set the `OPENAI_API_KEY` environment variable or pass the `api_key` parameter.

### AnthropicLLM

Anthropic Claude API implementation using the official Anthropic client.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str \| None` | `None` | Anthropic API key. If not provided, uses `ANTHROPIC_API_KEY` environment variable. |
| `model` | `str \| None` | `"claude-sonnet-4-20250514"` | Claude model name. |
| `model_params` | `dict[str, Any] \| None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str \| None` | `None` | Custom base URL for Anthropic-compatible APIs. |

```python
from protolink.llms.api import AnthropicLLM

# Basic usage
llm = AnthropicLLM(model="claude-3-5-sonnet-20241022")

# With custom parameters
llm = AnthropicLLM(
    model="claude-3-5-haiku-20241022",
    model_params={
        "temperature": 0.5,
        "max_tokens": 2000,
        "top_p": 0.8
    }
)
```

#### Default Model Parameters

| Parameter | Type | Default | Range/Description |
|-----------|-----|---------|-------------------|
| `max_tokens` | `int` | `4096` | Maximum tokens to generate |
| `temperature` | `float` | `1.0` | `0.0` to `1.0` - Controls randomness |
| `top_p` | `float` | `1.0` | Nucleus sampling parameter |
| `top_k` | `int \| None` | `None` | Top-k sampling parameter |
| `stop_sequences` | `list[str] \| None` | `None` | Stop sequences |
| `metadata` | `dict \| None` | `None` | Additional metadata |

#### Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `generate_response()` | `messages: list[Message]` | `Message` | Generate a single response using Anthropic's API. |
| `generate_stream_response()` | `messages: list[Message]` | `Iterable[Message]` | Generate streaming response, yielding partial messages. |
| `validate_connection()` | — | `bool` | Check if the model is available and API key is valid. |

!!! warning "API Key Required"
    Anthropic requires a valid API key. Set the `ANTHROPIC_API_KEY` environment variable or pass the `api_key` parameter.

## Server-based LLMs

Server-based LLMs connect to local or remote LLM servers.

### ServerLLM Base Class

Base class for all server-based LLM implementations.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `base_url` | `str` | — | **Required.** URL of the LLM server. |

#### Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `set_model_params()` | `model_params: dict[str, Any]` | `None` | Update existing model parameters, ignoring invalid keys. |
| `set_system_prompt()` | `system_prompt: str` | `None` | Set the system prompt for the model. |
| `validate_connection()` | — | `bool` | Validate that the server is reachable. |

### OllamaLLM

Ollama server implementation for connecting to local or remote Ollama instances.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `base_url` | `str \| None` | `None` | Ollama server URL. If not provided, uses `OLLAMA_HOST` environment variable. |
| `headers` | `dict[str, str] \| None` | `None` | Additional HTTP headers (including auth). |
| `model` | `str \| None` | `"gemma3"` | Ollama model name. |
| `model_params` | `dict[str, Any] \| None` | `None` | Model parameters (temperature, etc.). |

```python
from protolink.llms.server import OllamaLLM

# Local Ollama server
llm = OllamaLLM(
    base_url="http://localhost:11434",
    model="llama3"
)

# Remote Ollama with authentication
llm = OllamaLLM(
    base_url="https://ollama.example.com",
    headers={"Authorization": "Bearer your-token"},
    model="codellama"
)

# Using environment variables
# Set OLLAMA_HOST=http://localhost:11434
llm = OllamaLLM(model="mistral")
```

#### Default Model Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `temperature` | `float` | `1.0` | Controls randomness (range depends on model). |

#### Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `generate_response()` | `messages: list[Message]` | `Message` | Generate a single response using Ollama's API. |
| `generate_stream_response()` | `messages: list[Message]` | `Iterable[Message]` | Generate streaming response, yielding partial messages. |
| `validate_connection()` | — | `bool` | Check if Ollama server is reachable and has models available. |

!!! note "Ollama Server Required"
    OllamaLLM requires a running Ollama server. Install Ollama and start it with `ollama serve`.

## Usage Examples

### Basic LLM Usage

```python
from protolink.llms.api import OpenAILLM
from protolink.models import Message

# Initialize LLM
llm = OpenAILLM(model="gpt-4")

# Create messages
messages = [
    Message(role="user", content="Hello, how are you?")
]

# Generate response
response = llm.generate_response(messages)
print(response.content)
```

### Streaming Responses

```python
# Generate streaming response
for chunk in llm.generate_stream_response(messages):
    print(chunk.content, end="", flush=True)
```

### Updating Parameters

```python
# Update model parameters
llm.set_model_params({
    "temperature": 0.7,
    "max_tokens": 500
})

# Update system prompt
llm.set_system_prompt("You are a helpful coding assistant.")
```

### Connection Validation

```python
# Validate connection before use
if llm.validate_connection():
    print("LLM is ready!")
else:
    print("LLM connection failed.")
```

## Error Handling

All LLM implementations include error handling for common issues:

- **Authentication Errors**: Missing or invalid API keys
- **Connection Errors**: Network issues or unavailable servers
- **Model Errors**: Invalid model names or unavailable models
- **Parameter Errors**: Invalid parameter values

!!! tip "Connection Validation"
    Always call `validate_connection()` before using an LLM to ensure it's properly configured and reachable.

## Type Aliases

The LLM module defines several type aliases for clarity:

```python
LLMType: TypeAlias = Literal["api", "local", "server"]
LLMProvider: TypeAlias = Literal["openai", "anthropic", "google", "llama.cpp", "ollama"]
```

These are used throughout the LLM implementations to ensure type safety and clarity.

