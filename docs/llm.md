# LLMs

Protolink integrates with various LLM backends.

## LLM Types

Protolink groups LLM backends into three broad categories:

<div align="center" style="font-family: 'Courier New', monospace; color:#888; font-size:14px; margin-bottom:12px;">
  [ API ]   [ Server ]   [ Local ]
</div>
<div align="center" style="
  display:flex;
  flex-wrap:wrap;
  justify-content:center;
  gap:30px;
">
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/openai.svg" width="55" class="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/anthropic_black.svg" width="55" class="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/gemini.svg" width="55" class="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/deepseek.svg" width="55" class="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/ollama_light.svg" width="55" class="hover-icon" />
  <img src="https://raw.githubusercontent.com/abetlen/llama-cpp-python/main/docs/icon.svg" width="55" class="hover-icon" /></div>
<style>
  .hover-icon{ transition: transform .15s ease; }
  .hover-icon:hover{ transform: translateY(-4px) scale(1.08); }
</style>

- **API** — calls a remote API and requires an API key:
    - `OpenAILLM`: uses the **OpenAI API** for sync & async requests.
    - `AnthropicLLM`: uses the **Anthropic API** for sync & async requests.
    - `GeminiLLM`: uses the **Google Gemini API** for sync & async requests.
    - `DeepSeekLLM`: uses the **DeepSeek API** for sync & async requests.
    - `HuggingFaceLLM`: uses the **HuggingFace Inference API** for sync & async requests.

- **Server** — connects to an LLM server, locally or remotely:
    - `OllamaLLM`: connects to an **Ollama** server for sync & async requests.

- **Local** — runs the model directly in your runtime:
    - `LlamaCPPLLM`: uses a local **llama.cpp** runtime for sync & async requests.

You can also use other LLM clients directly without going through Protolink's `LLM` wrappers if you prefer.

## Configuration

Configuration depends on the specific backend, but the general pattern is:

1. **Install the relevant extras** (from the README):

   ```bash
   # All supported LLM backends
   uv add "protolink[llms]"
   ```

!!! info "Choosing LLM extras"
    If you only need a subset of LLMs (e.g. OpenAI API), it is advised to **install them manually** instead of using the `llms` extra, which will intall all the supported libraries.

2. **Instantiate the LLM** with the desired model and credentials:

   ```python
   from protolink.llms.api import OpenAILLM

   llm = OpenAILLM(
       api_key="your_api_key", # api_key is typically read from the environment, e.g. OPENAI_API_KEY
       model="gpt-4o-mini",
   )
   ```

!!! warning "API keys"
    Never commit API keys to version control. Read them from environment variables or a secure secrets manager.

3. **Pass the LLM to your Agent**:

   ```python
   from protolink.agents import Agent
   from protolink.models import AgentCard

   agent_card = AgentCard(
       url="http://localhost:8020",
       name="llm_agent", 
       description="Agent backed by an LLM"
   )

   agent = Agent(card=agent_card, transport="http", llm=llm)
   ```

For local and server‑style LLMs (`LlamaCPPLLM`, `OllamaLLM`), configuration additionally includes paths to model files or server URLs. Refer to the corresponding example scripts for concrete usage patterns.

---

## LLM API Reference

This section provides a detailed API reference for all LLM classes in Protolink. All LLM implementations inherit from the base `LLM` class and provide a consistent interface for generating responses.

!!! success "Unified LLM Interface"
    **Protolink provides a single, consistent API for all LLM providers.** Whether you're using OpenAI, Anthropic, Ollama, or local models, you interact with them through the same methods: `call()`, `call_stream()`, `chat()`, and the advanced `infer()` method. This unified approach means you can swap LLM providers without changing your application code - just update the initialization and you're done!

!!! tip "Why Use Protolink's LLM Wrappers?"
    - **Provider Agnostic**: Switch between OpenAI, Anthropic, Ollama, and future providers with minimal code changes
    - **Consistent Interface**: Same method signatures and behavior across all implementations
    - **Built-in Features**: Connection validation, parameter validation, and error handling out of the box
    - **Agent-Ready**: Built-in support for tool calling, agent delegation, and structured inference
    - **Production Ready**: Robust error handling and logging for real-world applications


#### Provider Switching in Action

Protolink provides a single, consistent API for all LLM providers. Whether you're using OpenAI, Anthropic, Ollama, or local models, you interact with them through the same methods: `call()`, `call_stream()`, `chat()`, and the advanced `infer()` method.

Protolink also provides the method **`chat()`** which is a convenience method for chat-style interactions. It calls the `call()` and `call_stream()` methods.

```python
# The same code works with ANY LLM provider

# Choose your provider - just change the import and initialization!
from protolink.llms.api import OpenAILLM, AnthropicLLM, GeminiLLM # etc.
from protolink.llms.server import OllamaLLM   # or any other provider

# Initialize your chosen LLM
llm = OpenAILLM(model="gpt-4o")
llm = AnthropicLLM(model="claude-3-5-sonnet")
llm = OllamaLLM(model="llama3", base_url="http://localhost:11434")

# The rest of your code stays EXACTLY the same!
response = llm.chat("Hello! How are you?")
print(response)

# Streaming also works identically
for chunk in llm.chat("Hello!", streaming=True):
    print(chunk, end="", flush=True)
```

!!! info "LLM Hierarchy"
    - **`LLM`** - abstract base class with core functionality
    - **`APILLM`** - base for API-based LLMs
    - **`ServerLLM`** - base for server-based LLMs
    - **`LocalLLM`** - base for local runtime LLMs
    - **Concrete implementations**: `OpenAILLM`, `AnthropicLLM`, `GeminiLLM`, `DeepSeekLLM`, `HuggingFaceLLM`, `OllamaLLM`, etc.

### Base LLM Class

The `LLM` class defines the common interface that all LLM implementations must follow.

#### Core Constants

| Constant | Type | Value | Description |
|----------|-----|-------|-------------|
| `MAX_INFER_STEPS` | `int` | `10` | Safety limit for inference loops to prevent infinite execution |

#### Attributes

| Attribute | Type | Description |
|-----------|-----|-------------|
| `model_type` | `LLMType` | The type of LLM (`"api"`, `"local"`, or `"server"`). |
| `provider` | `LLMProvider` | The provider name (`"openai"`, `"anthropic"`, `"ollama"`, etc.). |
| `model` | `str` | The model name/identifier. |
| `model_params` | `dict[str, Any]` | Model-specific parameters (temperature, max_tokens, etc.). |
| `system_prompt` | `str` | Default system prompt for the model. |
| `history` | `ConversationHistory` | Tracks conversation messages for multi-turn interactions. |

#### Core Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `call()` | `history: ConversationHistory` | `str` | **Abstract.** Generate a single response from the model. |
| `call_stream()` | `history: ConversationHistory` | `Iterable[str]` | **Abstract.** Generate a streaming response, yielding chunks. |
| `chat()` | `user_query: str, streaming: bool=False` | `str \| Iterable[str]` | High-level convenience method for standard chat usage. |
| `infer()` | `query: str, tools: dict[str, BaseTool], streaming: bool=False` | `Part` | **Async.** Execute controlled multi-step inference with tool calling. |
| `build_system_prompt()` | `user_instructions, agent_cards, tools, override_system_prompt` | `str` | Build the final system prompt for the LLM. |
| `set_system_prompt()` | `system_prompt: str` | `None` | Set the system prompt for the model. |
| `validate_connection()` | — | `bool` | **Abstract.** Validate that the LLM connection is working. |

#### Properties

| Property | Type | Description |
|----------|-----|-------------|
| `model_params` | `dict[str, Any]` | Get/set model-specific generation parameters. |

!!! note "Abstract Methods"
    The `LLM` base class is abstract. You should use one of the concrete implementations like `OpenAILLM` or `AnthropicLLM`.

### Advanced Inference System

#### The `infer()` Method

The `infer()` method is the core of Protolink's agent system. It implements a deterministic, multi-step inference loop that enables LLMs to:

1. **Make tool calls** - Execute external tools with structured arguments
2. **Delegate to agents** - Pass work to other specialized agents  
3. **Generate final responses** - Produce user-facing answers

!!! note "The **infer** method is the cornerstone of Protolink's agent system."
    This method implements a deterministic, multi-step inference loop that enables LLMs to make tool calls, delegate to agents, and generate final responses. **This method is called automatically by the agent and not manually by the user.**


#### Method Signature

```python
async def infer(
    *, 
    query: str, 
    tools: dict[str, BaseTool], 
    streaming: bool = False
) -> Part
```

#### Parameters

| Parameter | Type | Description |
|-----------|-----|-------------|
| `query` | `str` | The user-provided task or instruction to be processed. |
| `tools` | `dict[str, BaseTool]` | Available tools that the agent may invoke during inference. |
| `streaming` | `bool` | Whether to use streaming mode for underlying LLM calls. |

#### Returns

- `Part` with type `"infer_output"` containing the final response

#### Raises

- `RuntimeError`: LLM call failures, tool execution errors, or step limit exceeded
- `ValueError`: Invalid actions, unknown tools, or malformed responses

#### How It Works

1. **Multi-step Loop**: Executes up to `MAX_INFER_STEPS` (10) iterations
2. **JSON Action Protocol**: LLM must respond with structured JSON declaring actions
3. **Action Types**: 
   - `"final"` - Return a user-facing response
   - `"tool_call"` - Execute a tool with arguments
   - `"agent_call"` - Delegate to another agent
4. **Safety Features**: Bounded execution, error handling, response validation

#### Example Usage

```python
from protolink.llms.api import OpenAILLM
from protolink.tools import BaseTool

class WeatherTool(BaseTool):
    async def __call__(self, location: str) -> str:
        return f"The weather in {location} is sunny."

llm = OpenAILLM(model="gpt-4o")
tools = {"weather": WeatherTool()}

# Execute inference with tool calling
result = await llm.infer(
    query="What's the weather in Tokyo?",
    tools=tools
)
print(result.content)  # "The weather in Tokyo is sunny."
```

#### Response Format

The LLM must respond with valid JSON:

```json
{
  "type": "final",
  "content": "The capital of Greece is Athens."
}
```

```json
{
  "type": "tool_call", 
  "tool": "weather",
  "args": {"location": "Geneva"}
}
```

### Prompt Engineering Architecture

Protolink uses a sophisticated prompt engineering system to turn standard LLMs into autonomous agents. This system is located in `protolink/llms/prompts` and is responsible for creating the "blueprint" that guides the LLM's behavior.

#### The System Prompt Blueprint

The `LLM.build_system_prompt()` method dynamically assembles a comprehensive system prompt that enforces a **deterministic execution loop**. This blueprint tells the LLM exactly how to behave, how to format its output, and what capabilities it has.

It is composed of several key components:

1.  **Base Instructions (`BASE_SYSTEM_PROMPT`)**:
    -   Defines the agent's role (operating in a deterministic runtime).
    -   Enforces a strict **JSON output schema**.
    -   Prohibits the LLM from executing actions itself (it must *declare* intent).

2.  **Tool Definitions (`TOOL_CALL_PROMPT`)**:
    -   Injected only if `tools` are provided.
    -   Lists available tools with their schemas.
    -   Defines the `tool_call` JSON format.

3.  **Agent Capabilities (`AGENT_LIST_PROMPT`)**:
    -   Injected only if `agent_cards` are provided.
    -   Lists other available agents in the registry.
    -   Defines the `agent_call` JSON format for delegation.

4.  **User Instructions**:
    -   Your specific customization (e.g., "You are a coding assistant").
    -   Appended to the blueprint to guide the specific task domain.

#### How It Works

When `infer()` is called, this blueprint ensures the LLM does not just generating text, but acts as a reasoning engine.

1.  **Input**: The LLM receives the Task context.
2.  **Blueprint Enforcement**: The system prompt forces the LLM to choose a valid action: `final`, `tool_call`, or `agent_call`.
3.  **Structured Output**: The LLM acts by returning a JSON object, not free text.
    ```json
    { "type": "tool_call", "tool": "get_weather", "args": { ... } }
    ```
4.  **Runtime Execution**: Protolink intercepts this JSON, executes the real Python code, and feeds the result back to the LLM.

This separation of **Reasoning (LLM)** and **Execution (Runtime)**, mediated by the prompt blueprint, is what allows Protolink to be robust and provider-agnostic.

## API-based LLMs

API-based LLMs connect to external services and require API keys or authentication.

### Available API LLMs

| Provider | Class | Default Model | API Key Env Var |
|----------|-------|---------------|----------------|
| OpenAI | `OpenAILLM` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `AnthropicLLM` | `claude-3-5-sonnet-20241022` | `ANTHROPIC_API_KEY` |
| Google Gemini | `GeminiLLM` | `gemini-1.5-flash` | `GEMINI_API_KEY` |
| DeepSeek | `DeepSeekLLM` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| HuggingFace | `HuggingFaceLLM` | `HuggingFaceH4/zephyr-7b-beta` | `HF_API_TOKEN` |

### OpenAILLM

OpenAI API implementation using the official OpenAI client.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str \| None` | `None` | OpenAI API key. Uses `OPENAI_API_KEY` env var if not provided. |
| `model` | `str \| None` | `"gpt-4o-mini"` | OpenAI model name. |
| `model_params` | `dict[str, Any] \| None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str \| None` | `None` | Custom base URL for OpenAI-compatible APIs. |

```python
from protolink.llms.api import OpenAILLM

# Basic usage
llm = OpenAILLM(model="gpt-4o")

# With custom parameters
llm = OpenAILLM(
    model="gpt-4o",
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
| `max_tokens` | `int \| None` | `None` | Maximum tokens to generate |
| `presence_penalty` | `float` | `0.0` | `-2.0` to `2.0` - Presence penalty |
| `frequency_penalty` | `float` | `0.0` | `-2.0` to `2.0` - Frequency penalty |

### AnthropicLLM

Anthropic Claude API implementation using the official Anthropic client.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str \| None` | `None` | Anthropic API key. Uses `ANTHROPIC_API_KEY` env var if not provided. |
| `model` | `str \| None` | `"claude-3-5-sonnet-20241022"` | Claude model name. |
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

### GeminiLLM

Google Gemini API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str \| None` | `None` | Google API key. Uses `GEMINI_API_KEY` env var if not provided. |
| `model` | `str \| None` | `"gemini-1.5-flash"` | Gemini model name. |
| `model_params` | `dict[str, Any] \| None` | `None` | Model parameters (temperature, max_tokens, etc.). |

### DeepSeekLLM

DeepSeek API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str \| None` | `None` | DeepSeek API key. Uses `DEEPSEEK_API_KEY` env var if not provided. |
| `model` | `str \| None` | `"deepseek-chat"` | DeepSeek model name. |
| `model_params` | `dict[str, Any] \| None` | `None` | Model parameters (temperature, max_tokens, etc.). |

### HuggingFaceLLM

HuggingFace Inference API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str \| None` | `None` | HuggingFace API token. Uses `HF_API_TOKEN` env var if not provided. |
| `model` | `str \| None` | `"HuggingFaceH4/zephyr-7b-beta"` | HuggingFace model name. |
| `model_params` | `dict[str, Any] \| None` | `None` | Model parameters (temperature, max_tokens, etc.). |

!!! warning "Model Availability"
    Not all HuggingFace models are available through the Inference API. Use models that are explicitly supported for inference.

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
# Set OLLAMA_HOST=http://localhost:11434 or pass directly
llm = OllamaLLM(model="mistral", base_url="http://localhost:11434")
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

### Usage Examples

#### Basic Chat Usage

```python
from protolink.llms.api import OpenAILLM

# Initialize LLM
llm = OpenAILLM(model="gpt-4o")

# Simple chat
response = llm.chat("Hello, how are you?")
print(response)

# Streaming chat
for chunk in llm.chat("Hello!", streaming=True):
    print(chunk, end="", flush=True)
```

#### Advanced Inference with Tools

```python
from protolink.llms.api import OpenAILLM
from protolink.tools import BaseTool
import asyncio

class CalculatorTool(BaseTool):
    """Simple calculator tool."""
    
    async def __call__(self, expression: str) -> str:
        try:
            result = eval(expression)  # Simple evaluation
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {e}"

async def main():
    llm = OpenAILLM(model="gpt-4o")
    tools = {"calculator": CalculatorTool()}
    
    # Execute inference with tool calling
    result = await llm.infer(
        query="What is 15 * 8?",
        tools=tools
    )
    
    print(f"Final answer: {result.content}")

asyncio.run(main())
```

#### Updating Parameters

```python
# Update model parameters
llm.model_params = {
    "temperature": 0.7,
    "max_tokens": 500
}

# Update system prompt
llm.set_system_prompt("You are a helpful coding assistant.")
```

#### Connection Validation

```python
# Validate connection before use
if llm.validate_connection():
    print("LLM is ready!")
else:
    print("LLM connection failed.")
```

### Error Handling

All LLM implementations include comprehensive error handling:

#### Common Error Types

- **Authentication Errors**: Missing or invalid API keys
- **Connection Errors**: Network issues or unavailable servers
- **Model Errors**: Invalid model names or unavailable models
- **Parameter Errors**: Invalid parameter values
- **Inference Errors**: Tool execution failures, response parsing errors
- **Runtime Errors**: Maximum inference steps exceeded

#### Error Handling Patterns

```python
from protolink.llms.api import OpenAILLM
import asyncio

async def safe_inference():
    llm = OpenAILLM(model="gpt-4o")
    
    try:
        result = await llm.infer(
            query="What's the weather like?",
            tools={}  # No tools in this example
        )
        print(f"Success: {result.content}")
    except RuntimeError as e:
        print(f"Runtime error: {e}")
    except ValueError as e:
        print(f"Value error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

asyncio.run(safe_inference())
```

!!! tip "Connection Validation"
    Always call `validate_connection()` before using an LLM to ensure it's properly configured and reachable.

### Type Aliases

The LLM module defines several type aliases for clarity:

```python
LLMType: TypeAlias = Literal["api", "local", "server"]
LLMProvider: TypeAlias = Literal[
    "openai", "anthropic", "google", "deepseek", 
    "huggingface", "llama.cpp", "ollama"
]
```

These are used throughout the LLM implementations to ensure type safety and clarity.

### Migration Guide

#### From Previous Versions

If you're migrating from an earlier version of Protolink:

1. **Method Changes**: 
   - `generate_response()` → `chat()`
   - `generate_stream_response()` → `chat(..., streaming=True)`

2. **New Inference System**: 
   - Use `infer()` for agent-based interactions with tool calling
   - Old methods still work for simple chat use cases

3. **Async Required**: 
   - `infer()` is async and requires `await`
   - Simple `chat()` methods remain synchronous

4. **Response Format**: 
   - `chat()` returns strings directly
   - `infer()` returns `Part` objects with structured content

```python
# Old way (deprecated)
# response = llm.generate_response(messages)
# print(response.content)

# New way (recommended)
response = llm.chat("Hello, how are you?")
print(response)

# For agent use cases with tools
result = await llm.infer(query="What's the weather?", tools=tools)
print(result.content)
```

