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
  <img src="https://raw.githubusercontent.com/pheralb/svgl/476aabb842086433647755b0963640c6a0775f79/static/library/grok-light.svg" width="55" class="hover-icon" />
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
    - `GrokLLM`: uses the **Grok API** for sync & async requests.
    - `HuggingFaceLLM`: uses the **HuggingFace Inference API** for sync & async requests.

- **Server** — connects to an LLM server, locally or remotely:
    - `OllamaLLM`: connects to an **Ollama** server for sync & async requests.
    - `LlamaCPPServerLLM`: connects to a **llama-server** for sync & async requests.

- **Local** — runs the model directly in your runtime:
    - `LlamaCPPLocalLLM`: uses a local **llama-cpp-python** runtime for sync & async requests.

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

For local and server‑style LLMs (`LlamaCPPLocalLLM`, `LlamaCPPServerLLM`, `OllamaLLM`), configuration additionally includes paths to model files or server URLs. Refer to the corresponding example scripts for concrete usage patterns.

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
llm = OllamaLLM(model="gemma4:latest", base_url="http://localhost:11434")

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
| `reasoning` | `ReasoningLevel` | Whether to set reasoning/chain-of-thought instructions in the system prompt. When enabled, the LLM is prompted to reason step-by-step before producing a response. Possible values that indicate the level of reasoning to use: `"none"`, `"low"`, `"medium"`, `"high"`. Default: `"none"`. |

#### Core Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `call()` | `history: ConversationHistory` | `str` | **Abstract.** Generate a single response from the model. |
| `call_stream()` | `history: ConversationHistory` | `AsyncIterator[str]` | **Abstract.** Generate a streaming response, yielding chunks. |
| `chat()` | `user_query: str, streaming: bool=False` | `str ⎪ AsyncIterator[str]` | High-level convenience method for standard chat usage. |
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

1. **Multi-step Loop**: The method executes a loop up to `MAX_INFER_STEPS` (default: 10).
2. **Deterministic Execution**: At each step, the LLM is invoked with the current history.
3. **JSON Action Protocol**: The LLM must respond with a strict JSON object declaring one of three actions:
   - `"final"`: The task is complete. The content is returned to the user.
   - `"tool_call"`: The LLM wants to execute a tool. The runtime executes the tool and feeds the result back.
   - `"agent_call"`: The LLM wants to delegate to another agent (not yet fully implemented).
4. **Validation & Error Handling**: 
   - Malformed JSON or invalid actions raise `ValueError`.
   - Tool execution failures raise `RuntimeError` but catchable within the loop context if desired (currently propagates).
   - Exceeding the step limit raises `RuntimeError`.

### Inference Loop Safety Guardrails

The `infer()` method implements multiple layers of safety guarantees to ensure robust, deterministic execution:

#### 1. Deduplication Detection

The runtime tracks recent actions using a sliding window (default: 5 actions). If the LLM produces an identical action (same tool/agent call with identical arguments), the runtime:

- **Does not re-execute** the action
- **Injects corrective guidance** into the conversation history
- Prompts the LLM to proceed with its task or take a different action

This prevents infinite loops where the LLM repeatedly calls the same tool expecting different results.

```
# Example: LLM tries to call get_weather("Tokyo") twice in a row
# Runtime detects the duplicate and injects:
"You have already performed this action: tool_call. The result is in your context.
Please proceed with your task - either produce a 'final' response or take a different action."
```

#### 2. Parse Failure Circuit Breaker

Instead of consuming the entire step budget on parse failures, the runtime implements a circuit breaker:

- **Tracks consecutive parse failures** (not total failures)
- After **3 consecutive failures**, raises `RuntimeError` immediately
- Each failure **injects corrective feedback** to help the LLM self-correct

```python
# After a parse failure, the runtime injects:
"Your previous response could not be parsed as valid JSON. Error: {error}
Please respond with a valid JSON object containing 'type' and required fields."
```

#### 3. Self-Correcting Error Recovery

Rather than failing immediately on validation errors, the runtime injects helpful context back to the LLM:

| Error Type | Runtime Response |
|------------|------------------|
| Unknown tool | Lists available tools |
| Missing required fields | Shows expected JSON format |
| Type errors (wrong args) | Prompts to check `input_schema` |
| Agent not found | Provides the error message |
| Invalid action type | Lists valid action types |

This approach allows the LLM to self-correct without consuming the entire step budget on recoverable errors.

#### 4. Bounded Execution

A hard limit of `MAX_INFER_STEPS` (default: 10) prevents runaway execution:

- If exceeded, raises `RuntimeError` with diagnostic information
- The error message indicates the LLM may be stuck in a loop
- Suggests simplifying the task or checking prompts

!!! tip "Debugging Inference Loops"
    If you encounter "Maximum inference steps exceeded" errors frequently:
    
    1. **Check your prompts**: Ensure clear instructions for when to produce `final` responses
    2. **Simplify the task**: Break complex tasks into smaller steps
    3. **Review tool schemas**: Ensure tools have clear descriptions and valid schemas
    4. **Enable logging**: Add logging to track LLM decisions at each step


#### Tool Call Handling (`_inject_tool_call`)

When a tool is executed, the result needs to be added back to the conversation history so the LLM can see it. Protolink uses a **provider-agnostic** approach by default but allows for provider-specific overrides.

```python
def _inject_tool_call(self, *, tool_name: str, tool_args: dict, tool_result: Any) -> None:
    """
    Handle the completion of a tool invocation.
    
    Default behavior: Inject result as a SYSTEM message.
    """
```

**Why System Messages?**
By default, Protolink adds tool results as `system` messages containing a JSON dump of the result. This works across *any* LLM provider (OpenAI, Anthropic, Ollama, etc.) without needing to know their specific API schemas for tool roles.

**Provider-Specific Tool Call Semantics**
Subclasses like `OpenAILLM` or `AnthropicLLM` override this method to use their native tool confirmation APIs (e.g., `role="tool"`, `tool_call_id`, etc.), ensuring strict compliance with those platforms while keeping the main loop in `LLM.infer()` generic.

## Provider-Specific Tool Call Semantics

While Protolink’s inference loop and JSON action protocol are fully **provider-agnostic**, the way **tool calls and tool results are injected into the conversation history is not**. Each provider enforces a different conversational contract, message schema, and role semantics.

To handle this cleanly, Protolink defines a generic `_inject_tool_call` hook on `LLM`, which is overridden by provider-specific subclasses where native tool calling is supported.

---

### OpenAI (Responses API)

OpenAI’s **Responses API** enforces a strict and non-negotiable tool-calling protocol that differs from the legacy Chat Completions interface.

A complete tool interaction is represented as a **correlated pair of messages**:

1. An `assistant` message declaring the tool invocation via a `tool_calls` field, including:
   - A generated `tool_call_id`
   - The tool (function) name
   - The serialized tool arguments

2. A subsequent `user` message containing a `tool_result` content block, which supplies:
   - The same `tool_call_id`
   - The serialized tool execution result

Important constraints enforced by the Responses API:

- A dedicated `tool` role is **explicitly forbidden**
- Tool results **must** be embedded in a `user` message
- The `tool_call_id` must match exactly between declaration and result
- Any deviation from this schema results in request validation errors

#### Implications for Protolink

- `OpenAILLM` overrides `_inject_tool_call` to:
  - Generate a unique `tool_call_id`
  - Inject messages using the exact schema required by the Responses API
- Tool execution itself is handled by the runtime; this method only adapts results into OpenAI’s required format

This strictness is why OpenAI requires a fully custom implementation, even though the high-level behavior (execute tool → feed result back) is conceptually identical to other providers.

Official references:
- OpenAI Responses API – Tool calling  
  https://platform.openai.com/docs/guides/tools
- OpenAI Responses API – Message schema  
  https://platform.openai.com/docs/api-reference/responses

---

### Anthropic (Claude / Messages API)

Anthropic models use a **block-based message format** rather than dedicated tool roles. Tool interactions are expressed through structured content blocks embedded within normal messages.

A complete tool round-trip consists of:

1. An `assistant` message containing a `tool_use` content block that declares:
   - The name of the tool
   - The structured input arguments

2. A subsequent `user` message containing a `tool_result` content block that supplies:
   - The identifier of the originating tool use
   - The tool execution result

Key characteristics of Anthropic’s protocol:

- Tool interactions are represented via content blocks, not message roles
- Tool outputs are conceptually treated as **user-provided information**
- No `tool` or `system` role is introduced for tool results
- Structural correctness at the block level is strictly enforced

#### Implications for Protolink

- `AnthropicLLM` overrides `_inject_tool_call` to:
  - Inject a `tool_result` content block with the correct identifier
  - Preserve Anthropic’s expected message ordering and block semantics
- Tool correlation is handled via block semantics rather than explicit role-based IDs

Anthropic is less restrictive about message roles than OpenAI, but equally strict about content structure.

---

### Ollama / Server-Based Models

Ollama follows a **Chat Completions–style** protocol for tool usage, closer to OpenAI’s legacy interface than the Responses API.

When native tool calling is enabled:

- The assistant declares a tool invocation via a `tool_calls` field
- The tool result is returned as a separate message with:
  - `role="tool"`
  - The corresponding `tool_name`
- No explicit tool call identifier is required
- Tool calls and results are implicitly associated by message order

#### Conditional Behavior in Protolink

Ollama support is intentionally **conditional**:

- If `self._supports_tool_calling` is `True`:
  - Ollama-native tool messages are emitted
- If `self._supports_tool_calling` is `False`:
  - The method delegates to the base `LLM` implementation
  - Tool results are injected using the provider-agnostic fallback
    (typically a serialized `system` message)

This design allows:

- Disabling native tool calling for models that do not reliably support it (e.g. some LLaMA variants)
- Preserving a single, deterministic inference loop
- Avoiding provider-specific branching outside `_inject_tool_call`

Official reference:
- Ollama Tool Calling  
  https://docs.ollama.com/capabilities/tool-calling

---

## Design Rationale

This layered design allows Protolink to:

- Keep the core inference loop (`LLM.infer`) fully generic
- Support strict APIs (OpenAI, Anthropic) without polluting the main control flow
- Support looser or local models (Ollama, custom servers) safely and deterministically
- Centralize all protocol-specific complexity inside small, well-defined overrides

**In short:**

- The inference logic is generic  
- The message protocol is provider-specific  

Protolink cleanly separates the two.


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

This method calls `reset_to_system(self, new_system_prompt: str)` to reset the history and set the new system prompt. This means the history is stateless, and is reset for each inference task.

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
| `api_key` | `str ⎪ None` | `None` | OpenAI API key. Uses `OPENAI_API_KEY` env var if not provided. |
| `model` | `str ⎪ None` | `"gpt-4o-mini"` | OpenAI model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str ⎪ None` | `None` | Custom base URL for OpenAI-compatible APIs. |

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
| `max_tokens` | `int ⎪ None` | `None` | Maximum tokens to generate |
| `presence_penalty` | `float` | `0.0` | `-2.0` to `2.0` - Presence penalty |
| `frequency_penalty` | `float` | `0.0` | `-2.0` to `2.0` - Frequency penalty |

### AnthropicLLM

Anthropic Claude API implementation using the official Anthropic client.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | Anthropic API key. Uses `ANTHROPIC_API_KEY` env var if not provided. |
| `model` | `str ⎪ None` | `"claude-3-5-sonnet-20241022"` | Claude model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str ⎪ None` | `None` | Custom base URL for Anthropic-compatible APIs. |

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
| `top_k` | `int ⎪ None` | `None` | Top-k sampling parameter |

### GeminiLLM

Google Gemini API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | Google API key. Uses `GEMINI_API_KEY` env var if not provided. |
| `model` | `str ⎪ None` | `"gemini-1.5-flash"` | Gemini model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |

### DeepSeekLLM

DeepSeek API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | DeepSeek API key. Uses `DEEPSEEK_API_KEY` env var if not provided. |
| `model` | `str ⎪ None` | `"deepseek-chat"` | DeepSeek model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |

### HuggingFaceLLM

HuggingFace Inference API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | HuggingFace API token. Uses `HF_API_TOKEN` env var if not provided. |
| `model` | `str ⎪ None` | `"HuggingFaceH4/zephyr-7b-beta"` | HuggingFace model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |

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
| `base_url` | `str ⎪ None` | `None` | Ollama server URL. If not provided, uses `OLLAMA_HOST` environment variable. |
| `headers` | `dict[str, str] ⎪ None` | `None` | Additional HTTP headers (including auth). |
| `model` | `str ⎪ None` | `"gemma3"` | Ollama model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, etc.). |

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

### LlamaCPPServerLLM

Llama.cpp server implementation for communicating directly with `llama-server`.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `base_url` | `str ⎪ None` | `None` | `llama-server` URL. Defaults to `http://localhost:8080`. |
| `headers` | `dict[str, str] ⎪ None` | `None` | Additional HTTP headers. |
| `model` | `str ⎪ None` | `"llama3"` | The requested model representation. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, etc.). |

```python
from protolink.llms.server import LlamaCPPServerLLM

llm = LlamaCPPServerLLM(
    base_url="http://localhost:8080",
    model="llama3"
)
```

## Local LLMs

Local LLMs run natively within the Python host machine rather than transmitting requests over the network.

### LlamaCPPLocalLLM

Local LLM integration using the `llama-cpp-python` distribution explicitly loading a local `.gguf` file path.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `model` | `str` | — | **Required.** Absolute Path to your downloaded `.gguf` model file. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters. |

```python
from protolink.llms.local import LlamaCPPLocalLLM

llm = LlamaCPPLocalLLM(
    model="/Users/dev/models/llama-3-8b-instruct.gguf",
    model_params={"temperature": 0.5, "max_tokens": 1024}
)
```

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
    "openai", "anthropic", "gemini", "deepseek", 
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

