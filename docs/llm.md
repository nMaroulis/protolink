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
    - `LMStudioLLM`: connects to an **LM Studio** OpenAI-compatible server.
    - `OpenAICompatibleLLM`: connects to any server exposing OpenAI-compatible `/v1/chat/completions` and `/v1/models` endpoints.

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
    If you only need a subset of LLMs (e.g. OpenAI API), it is advised to **install them manually** instead of using the `llms` extra, which will install all the supported libraries.

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

For local and server‑style LLMs (`LlamaCPPLocalLLM`, `LlamaCPPServerLLM`, `OllamaLLM`, `LMStudioLLM`, `OpenAICompatibleLLM`), configuration additionally includes paths to model files or server URLs. Refer to the corresponding example scripts for concrete usage patterns.

---

## Agent History Isolation And Concurrency

An `LLM` instance still exposes `llm.history` for direct usage and backward-compatible introspection. When the same LLM is plugged into an `Agent`, Protolink binds a task-local `ConversationHistory` around each run so concurrent tasks do not interleave messages on one shared mutable history object.

For stateless agents, each task receives a fresh history seeded by the compiled system prompt. After the task finishes, `llm.history` points at a copy of the last completed task history for debugging and simple scripts.

For persistent conversation state, enable `state=["conversation"]`. The Agent loads the requested `session_id`, serializes concurrent tasks for that same session with an async lock, saves the completed history back to state, and exposes a copy as `llm.history` after completion.

```python
from protolink import Agent, AgentCard, RunContext, Task, create_llm

agent = Agent(
    AgentCard(name="assistant", description="Assistant", url="runtime://assistant"),
    llm=create_llm("mock", default_response="ok"),
    state=["conversation"],
)

task = Task.create_infer(prompt="remember this")
RunContext(session_id="customer-42").attach_to_task(task)
await agent.execute_task(task)
```

Direct `llm.infer(...)` calls are unchanged: they use the LLM's default history unless you explicitly call `llm.use_history(history)`.

## Model Profiles, Context Manifests, And Budget Metrics

LLM wrappers can emit pre-call context manifests plus per-call latency, token usage, context-window pressure, and estimated cost through the existing `infer()` event stream and telemetry hooks. This is optional and does not change the request payload sent to the provider.

```python
from protolink import LLMModelProfile, create_llm

llm = create_llm(
    "openai-compatible",
    model="my-model",
    metrics_profile=LLMModelProfile(
        context_window=128_000,
        input_cost_per_million=1.0,   # example value; use your provider's current pricing
        output_cost_per_million=5.0,  # example value; use your provider's current pricing
        supports_tools=True,
        supports_streaming=True,
        supports_json_schema=True,
        tokenizer="cl100k_base",
    ),
)
```

You can also configure metrics after construction:

```python
llm.configure_metrics(
    context_window=128_000,
    input_cost_per_million=1.25,
    output_cost_per_million=10.0,
)
```

Provider-reported token usage is used when the SDK response includes it. Otherwise Protolink estimates token counts locally. If `tiktoken` is installed through `protolink[metrics]`, Protolink uses it for estimates; without it, Protolink falls back to a lightweight character heuristic. Prices, model limits, and capabilities change over time, so Protolink treats `LLMModelProfile` as application-owned metadata rather than a hardcoded billing catalog.

Before each model call, Protolink emits a provider-neutral `context_prepared` event:

```python
{
    "type": "context_prepared",
    "step": 1,
    "manifest": {
        "run_id": "run_123",
        "agent_name": "researcher",
        "system_tokens": 900,
        "tool_prompt_tokens": 300,
        "history_tokens": 2200,
        "user_tokens": 120,
        "total_estimated_tokens": 3520,
        "context_window": 128000,
    },
}
```

When an `event_callback` or telemetry backend is attached, each model call inside the inference loop can also emit:

```python
{
    "type": "llm_call_metrics",
    "step": 1,
    "provider": "openai-compatible",
    "model": "my-model",
    "latency_ms": 842.37,
    "usage": {"input_tokens": 1200, "output_tokens": 180, "estimated": False},
    "context": {"used_tokens": 1200, "window_tokens": 200000, "used_percent": 0.6},
    "cost": {"input_cost": 0.0036, "output_cost": 0.0027, "total_cost": 0.0063},
}
```

This is especially useful for CLIs, dashboards, and budget-aware agents that want to show context pressure or session cost while a multi-step tool loop is running.

If a `RunContext` carries a `RunBudget`, `LLM.infer()` enforces it through the default `BudgetEnforcer`. Pre-call limits such as `max_llm_calls` and `max_input_tokens` are checked before the provider is invoked; `max_tool_calls` is checked before model-selected tools execute; `max_output_tokens` is checked after provider usage or local estimates are available. Warnings appear as `budget_warning` events and hard denials appear as `budget_exceeded` events.

## History Compaction

Every LLM wrapper owns a modular `HistoryCompactor` at `llm.compactor`. Its `compact()` method mutates the current `ConversationHistory` in place and returns a `HistoryCompactionResult` with before/after message and estimated-token counts. `LLM.compact_history()` remains as a convenient facade, so existing direct usage stays concise.

```python
# Fastest: keep the system prompt and 19 newest messages.
report = llm.compact_history("recent", max_messages=20)

# Local and budget-aware: keep a recent suffix near 8,000 estimated tokens.
report = llm.compact_history(
    "tokens",
    max_tokens=8_000,
    preserve_recent=6,
)

# Highest context fidelity: summarize old turns, preserve the newest 8 verbatim.
report = llm.compact_history(
    "summary",
    preserve_recent=8,
    summary_max_tokens=600,
)

print(report.to_dict())

# Equivalent component-oriented API:
report = llm.compactor.compact("tokens", max_tokens=8_000)
```

Three **strategies** cover different cost and fidelity needs:

- ``"recent"`` keeps the system prompt and newest messages. It is the simplest and fastest option and makes no model call.
- ``"tokens"`` keeps the newest chronological suffix that fits an estimated token budget. It makes no model call and uses the same optional tokenizer/fallback heuristic as LLM metrics.
- ``"summary"`` asks this LLM to summarize older messages in one isolated call, replaces them with a system summary, and preserves the newest messages verbatim.

The summary call receives a temporary ``ConversationHistory`` and does not write into the live history. If it fails or returns an empty summary, the live history remains unchanged.

| Strategy | Model calls | Behavior | Best for |
|----------|-------------|----------|----------|
| `recent` | 0 | Keeps the leading system prompt and newest `max_messages` messages. | A simple, fast sliding window. |
| `tokens` | 0 | Keeps the newest chronological suffix near `max_tokens`, using `tiktoken` when installed or the built-in estimate otherwise. | Deterministic context-budget control. |
| `summary` | 1 | Replaces older turns with a model-generated system summary and keeps `preserve_recent` turns verbatim. | Retaining decisions and constraints from long sessions. |

The `tokens` limit is deliberately soft when the leading system prompt plus protected recent messages already exceed the budget: Protolink preserves those messages instead of silently removing the active request. The `summary` strategy makes its model call with a temporary history. The live history is changed only after a non-empty summary is returned, so a provider failure leaves it untouched.

### Agent-requested compaction

Agent-requested compaction is a control-plane request, not a model tool and not a task part. Call the Agent method directly or use the client request spec. The compaction capability is never appended to the model prompt and is never exposed through provider-native or JSON tool calling, which keeps the prompt smaller and friendlier to very small models.

```python
from protolink import HistoryCompactionRequest

report = await agent.compact_history(
    HistoryCompactionRequest(
        strategy="summary",
        preserve_recent=8,
        summary_max_tokens=600,
        session_id="customer-42",
    )
)
```

For remote agents, use the client spec-backed convenience method:

```python
from protolink.client import AgentClient

client = AgentClient("runtime", url="runtime://client")
report = await client.compact_history(
    "runtime://agent",
    strategy="summary",
    preserve_recent=8,
    summary_max_tokens=600,
    session_id="customer-42",
)
```

The remote path is `POST /llm/history/compact`, represented by `AgentClient.COMPACT_HISTORY_REQUEST` and an `EndpointSpec` registered by `AgentServer`. When `state=["conversation"]` is enabled and `session_id` is supplied, the Agent loads the session history before compaction and saves the compacted history afterward. The runtime action is still evaluated through the policy boundary with the `llm.history.compact` capability, so applications can allow, deny, or require approval for context loss.

!!! note "Compaction is explicit"
    Protolink does not compact history automatically based on an arbitrary context threshold. Applications can call `llm.compact_history()` for local use, `agent.compact_history()` inside an Agent process, or `AgentClient.compact_history()` over a transport. Natural-language requests such as “please compact your context” are application intent; convert them into a control-plane request before calling the Agent if you want deterministic behavior.

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
from protolink.llms.server import LMStudioLLM, OllamaLLM   # or any other provider

# Initialize your chosen LLM
llm = OpenAILLM(model="gpt-4o")
llm = AnthropicLLM(model="claude-3-5-sonnet")
llm = OllamaLLM(model="gemma4:e4b", base_url="http://localhost:11434")
llm = LMStudioLLM(model="local-model", base_url="http://localhost:1234/v1")

# The rest of your code stays EXACTLY the same!
response = llm.chat("Hello! How are you?")
print(response)

# Streaming returns an async iterator
async for chunk in llm.chat("Hello!", streaming=True):
    print(chunk, end="", flush=True)
```

!!! info "LLM Hierarchy"
    - **`LLM`** - abstract base class with core functionality
    - **`APILLM`** - base for API-based LLMs
    - **`ServerLLM`** - base for server-based LLMs
    - **`LocalLLM`** - base for local runtime LLMs
    - **Concrete implementations**: `OpenAILLM`, `AnthropicLLM`, `GeminiLLM`, `DeepSeekLLM`, `HuggingFaceLLM`, `OllamaLLM`, `LMStudioLLM`, `OpenAICompatibleLLM`, etc.

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
| `history` | `ConversationHistory` | Tracks conversation messages for multi-turn interactions. Automatically managed by the [Agent state system](agent.md#state-persistence) when enabled. |
| `compactor` | `HistoryCompactor` | LLM-owned component that handles compaction algorithms and isolated summary calls. It is not exposed to the model as a tool. |
| `reasoning` | `ReasoningLevel` | Whether to set reasoning/chain-of-thought instructions in the system prompt. When enabled, the LLM is prompted to reason step-by-step before producing a response. Possible values that indicate the level of reasoning to use: `"none"`, `"low"`, `"medium"`, `"high"`. Default: `"none"`. |
| `metrics_profile` | `LLMModelProfile ⎪ None` | Optional application-owned model metadata for context-window percentages, cost estimates, context manifests, and descriptive capabilities such as tool, streaming, and JSON-schema support. |
| `metrics_enabled` | `bool` | Whether metrics events are emitted when telemetry or an `event_callback` is attached. Defaults to `True`. |

!!! info "History Performance"
    Protolink's `ConversationHistory` uses a **`collections.deque`** internally. This optimizes two critical hot-paths in agentic workflows:
    
    1.  **System Prompt Updates**: Updating or prepending the system prompt is an **$O(1)$** operation (no list re-allocation).
    2.  **History Truncation**: Trimming old messages to fit context windows is significantly faster than standard list slicing.

#### Core Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `call()` | `history: ConversationHistory` | `str` | **Abstract.** Generate a single response from the model. |
| `call_stream()` | `history: ConversationHistory` | `AsyncIterator[str]` | **Abstract.** Generate a streaming response, yielding chunks. |
| `call_action()` | `history, tools, agent_callback_available=False, agent_cards=None` | `LLMActionResult` | Return one validated runtime action. Native providers override this to consume provider tool calls; fallback providers parse JSON text. |
| `call_action_stream()` | `history, tools, agent_callback_available=False, agent_cards=None, chunk_callback=None` | `LLMActionResult` | Streaming equivalent of `call_action()`. Native-stream providers consume tool-call events; fallback providers stream JSON text and parse it after completion. |
| `chat()` | `user_query: str, streaming: bool=False` | `str ⎪ AsyncIterator[str]` | High-level convenience method for standard chat usage. |
| `infer()` | `query: str, tools: dict[str, BaseTool], streaming: bool=False, event_callback=None` | `Part` | **Async.** Execute controlled multi-step inference with tool calling, optional streaming LLM calls, and optional event observation. |
| `compact_history()` | `strategy="recent", max_messages=20, max_tokens=4000, preserve_recent=6, summary_max_tokens=512` | `HistoryCompactionResult` | Compact live history using a message window, estimated token budget, or model-generated summary. |
| `compactor.compact()` | Same as `compact_history()` | `HistoryCompactionResult` | Component-oriented form of the same operation. |
| `configure_metrics()` | `profile=None, context_window=None, input_cost_per_million=None, output_cost_per_million=None` | `LLM` | Configure optional context/cost metadata used for emitted metrics. |
| `build_system_prompt()` | `user_instructions, agent_cards, tools, action_mode=None, override_system_prompt=False, persist=False` | `str` | Build the final system prompt. `action_mode="json"` uses the portable JSON action contract; `action_mode="native"` uses provider-native tool instructions. If `persist=True`, preserves existing conversation history. |
| `set_system_prompt()` | `system_prompt: str` | `None` | Set the system prompt for the model. |
| `validate_connection()` | — | `bool` | **Abstract.** Validate that the LLM connection is working. |

#### Properties

| Property | Type | Description |
|----------|-----|-------------|
| `model_params` | `dict[str, Any]` | Get/set model-specific generation parameters. |
| `uses_native_action_prompt` | `bool` | Whether non-streaming `infer()` should use provider-native tool instructions instead of JSON action instructions. |
| `supports_native_action_stream` | `bool` | Whether streaming `infer()` can acquire tool/agent actions from native streaming provider events. |

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
    streaming: bool = False,
    event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> Part
```

#### Parameters

| Parameter | Type | Description |
|-----------|-----|-------------|
| `query` | `str` | The user-provided task or instruction to be processed. |
| `tools` | `dict[str, BaseTool]` | Available tools that the agent may invoke during inference. |
| `streaming` | `bool` | Whether to use streaming mode for underlying LLM calls. |
| `event_callback` | `Callable[[dict], Awaitable[None]] ⎪ None` | Optional observer for normalized inference events such as chunks, tool starts/results, agent calls, parse errors, and final output. |

#### Returns

- `Part` with type `"infer_output"` containing the final response

#### Raises

- `RuntimeError`: LLM call failures, tool execution errors, or step limit exceeded
- `ValueError`: Invalid actions, unknown tools, or malformed responses

#### How It Works

`infer()` always dispatches typed actions, but the LLM can produce those actions through two acquisition modes:

| Mode | Used By | Model Instruction | Runtime Behavior |
|------|---------|-------------------|------------------|
| JSON action mode | Default for local/small models and providers without reliable native tools | Return one JSON object such as `{"type":"tool_call","tool":"search","args":{"q":"..."}}` | `call_action()` or fallback `call_action_stream()` parses the text, validates it with Pydantic, then dispatches it. |
| Native action mode | OpenAI, Anthropic, Gemini, and opted-in tool-capable servers | Use the provider's tool/function interface | The adapter sends real tool declarations, receives native tool events, and normalizes them into the same typed action models. |

The loop is otherwise identical in both modes:

1. **Prompt selection**: `Agent.call_llm()` builds either the JSON prompt or the native-tool prompt. Streaming calls use the native prompt only when `llm.supports_native_action_stream` is true; otherwise they force JSON mode so small/local models keep the simple contract.
2. **Action acquisition**: `LLM.infer()` calls `call_action()` for non-streaming runs or `call_action_stream()` for streaming runs. These methods return an `LLMActionResult`, not raw provider data.
3. **Action validation**: JSON mode validates the parsed object against the typed action union. Native mode validates the normalized provider tool call against the same `FinalAction`, `ToolCallAction`, or `AgentCallAction` models.
4. **Runtime dispatch**: The runtime executes local tools, delegates to agents, or returns a final answer. The LLM declares intent only; Protolink performs all side effects. History compaction is handled outside this loop by `Agent.compact_history()` and the client/server request spec.
5. **Observation injection**: Tool and agent results are added back to `ConversationHistory` through provider-specific injection hooks when needed, or through the provider-neutral fallback message format.
6. **Iteration**: The loop repeats until a `final` action is produced or a guardrail stops execution.

History is automatically committed to the `ConversationHistory` object. If the agent's `state=["conversation"]` is enabled, this history is persisted to the [Storage](storage.md) backend and resumed in later sessions.

!!! info "What streaming JSON means"
    Streaming JSON does not mean Protolink dispatches partial JSON fragments. It means the model streams ordinary text chunks that eventually form one complete JSON action object. Protolink forwards chunks to observers for UI feedback, buffers them internally, and validates the full JSON object only after the provider finishes the response.

!!! tip "Small model support"
    Ollama, llama.cpp, LM Studio, and OpenAI-compatible local servers default to JSON action mode. Enable `supports_tool_calling=True` only for a model/server combination you know can reliably emit native tool calls.

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


#### Tool Call Handling (`call_action`, `call_action_stream`, `_inject_tool_call`)

Tool calls have two separate phases:

1. **Action acquisition**: The adapter gets one model decision and returns `LLMActionResult`.
2. **Observation injection**: After Protolink executes the tool, the adapter adds the result back to history so the model can continue.

```python
def call_action(...) -> LLMActionResult:
    """Return one validated action for the current inference step."""

async def call_action_stream(...) -> LLMActionResult:
    """Return one validated action from a streaming inference step."""

def _inject_tool_call(self, *, tool_name: str, tool_args: dict, tool_result: Any) -> None:
    """Inject the runtime observation after a tool has executed."""
```

The base implementation is intentionally portable: it asks the model for JSON, validates that JSON, executes the tool, and injects the result as a provider-neutral observation. Native adapters override the acquisition methods to consume provider tool events, but still return the same Protolink action objects to the loop.

## Provider-Specific Action Modes

| Provider | Non-Streaming `infer()` | Streaming `infer()` | Notes |
|----------|-------------------------|---------------------|-------|
| OpenAI | Native Responses function tools | Native streamed function-call events | Uses real tool declarations and disables parallel tool calls so the runtime receives one action at a time. |
| Anthropic | Native `tool_use` blocks | Native `input_json_delta` tool streams | Text deltas stream to observers; tool JSON is buffered until complete. |
| Gemini | Native function declarations | Native streamed function-call parts | Function-call parts are normalized into Protolink actions. |
| DeepSeek | Native Chat Completions tools when `supports_tool_calling=True` | Native streamed tool deltas when enabled | Can be disabled to use JSON mode. |
| Grok | Native Chat Completions tools when `supports_tool_calling=True` | Native streamed tool deltas when enabled | Can be disabled to use JSON mode. |
| Ollama | JSON mode by default; native tools only with `supports_tool_calling=True` | JSON stream by default; native tool stream only with `supports_tool_calling=True` | Keeps small/local model behavior simple unless the model is known to support tools. |
| llama.cpp server/local | JSON mode by default; native tools only with `supports_tool_calling=True` | JSON stream by default; native tool stream only with `supports_tool_calling=True` | Depends on the model and chat template. |
| LM Studio / OpenAI-compatible servers | JSON mode by default; native tools only with `supports_tool_calling=True` | JSON stream by default; native tool stream only with `supports_tool_calling=True` | Useful for vLLM, LocalAI, LM Studio, and custom servers. |
| HuggingFace | JSON mode | JSON stream fallback when supported | Provider-native tool calling is not assumed. |

### Prompt Selection

Protolink uses two prompt families:

- **JSON prompt**: Describes `final`, `tool_call`, and `agent_call` JSON objects. This is the default compatibility path and is optimized for small/local model support.
- **Native prompt**: Tells the model to use the provider tool interface. It does not include JSON action examples, so OpenAI, Anthropic, Gemini, and opted-in native providers are not given conflicting instructions.

For streaming agent calls, Protolink chooses the prompt based on `supports_native_action_stream`:

```python
action_mode = "native" if llm.supports_native_action_stream else "json"
```

This matters because native tool calls are not text. A provider may stream text deltas, function argument deltas, or SDK objects. `call_action_stream()` hides that provider shape and returns a single typed action to the infer loop.

### Agent Delegation Tools

Native providers receive synthetic delegation tools only when both conditions are true:

- The current agent can dispatch agent calls.
- Discovered agent cards are available.

This avoids exposing a callable delegation surface with no valid targets. JSON mode still supports `agent_call` objects directly and can self-correct if delegation is unavailable.

## Design Rationale

This layered design keeps the core runtime strict while avoiding unnecessary prompt complexity:

- `LLM.infer()` dispatches one typed action at a time.
- Provider adapters own provider-specific request and stream parsing.
- Small/local models keep the simple JSON protocol by default.
- Native providers use native tools without seeing JSON action instructions.
- Every path converges on the same `FinalAction`, `ToolCallAction`, and `AgentCallAction` models.


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

#### JSON Mode Response Format

When an adapter is using JSON action mode, the model must respond with one valid JSON object:

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

### Prompt Architecture

Protolink uses prompt families in `protolink/llms/prompts` to match the action acquisition mode. The runtime deliberately avoids giving the model two tool-calling contracts at once.

#### The System Prompt Blueprint

The `LLM.build_system_prompt()` method dynamically assembles the prompt used by `infer()`. In JSON mode it describes the portable action objects. In native mode it tells the model to use the provider tool interface and leaves the function-call syntax to the backend SDK/API.

By default, this method calls `reset_to_system(self, new_system_prompt: str)` which clears the history. However, when using the **`persist=True`** flag, it calls `set_system()`, which updates the instructions while keeping the conversation history intact—essential for persistent sessions.

It is composed of several key components:

1. **Base Instructions**:
    - Define the agent's role inside a deterministic runtime.
    - Prohibit the LLM from pretending to execute actions itself.
    - Use either `BASE_SYSTEM_PROMPT` for JSON mode or `NATIVE_SYSTEM_PROMPT` for native mode.

2. **Tool Instructions**:
    - JSON mode injects `TOOL_CALL_PROMPT` with available tool schemas and the `tool_call` JSON format.
    - Native mode injects a short instruction to use the provider tool interface; concrete schemas are sent through the provider API.

3. **Agent Capabilities**:
    - JSON mode injects `AGENT_LIST_PROMPT` with the `agent_call` JSON format.
    - Native mode exposes synthetic delegation tools only when discovered agents are available.

4. **Semantic Context Injection**:
    - Injected automatically when the Agent is executing inside a Flow (`Pipeline`, `Router`, `Graph`).
    - Provides downstream topology awareness for the current flow step.

5. **User Instructions**:
    - Your specific customization (e.g., "You are a coding assistant").
    - Appended to guide the task domain.

#### How It Works

When `infer()` is called, the prompt ensures the LLM acts as a reasoning engine while Protolink remains the executor.

1.  **Input**: The LLM receives the Task context.
2.  **Action Selection**: The model chooses a valid action: `final`, `tool_call`, or `agent_call`.
3.  **Structured Output**: JSON mode returns a JSON object; native mode returns a provider tool call or final text.
    ```json
    { "type": "tool_call", "tool": "get_weather", "args": { ... } }
    ```
4.  **Runtime Execution**: Protolink validates the action, executes the real Python code or agent dispatch, and feeds the result back to the LLM.

This separation of **Reasoning (LLM)** and **Execution (Runtime)** is what allows Protolink to stay provider-agnostic while still using native provider tools where they are reliable.

## API-based LLMs

API-based LLMs connect to external services and require API keys or authentication.

### Available API LLMs

| Provider | Class | Default Model | API Key Env Var |
|----------|-------|---------------|----------------|
| OpenAI | `OpenAILLM` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `AnthropicLLM` | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| Google Gemini | `GeminiLLM` | `gemini-3-flash-preview` | `GEMINI_API_KEY` |
| DeepSeek | `DeepSeekLLM` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| Grok | `GrokLLM` | `grok-4-latest` | `XAI_API_KEY` or `GROK_API_KEY` |
| HuggingFace | `HuggingFaceLLM` | Explicit `model` required | `HF_API_TOKEN` |

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
| `model` | `str ⎪ None` | `"claude-sonnet-4-20250514"` | Claude model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str ⎪ None` | `None` | Custom base URL for Anthropic-compatible APIs. |

```python
from protolink.llms.api import AnthropicLLM

# Basic usage
llm = AnthropicLLM(model="claude-sonnet-4-20250514")

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
| `max_tokens` | `int` | `8192` | Maximum tokens to generate |
| `temperature` | `float` | `1.0` | `0.0` to `1.0` - Controls randomness |
| `top_p` | `float` | `1.0` | Nucleus sampling parameter |
| `top_k` | `int ⎪ None` | `None` | Top-k sampling parameter |

### GeminiLLM

Google Gemini API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | Google API key. Uses `GEMINI_API_KEY` env var if not provided. |
| `model` | `str ⎪ None` | `"gemini-3-flash-preview"` | Gemini model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |

### DeepSeekLLM

DeepSeek API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | DeepSeek API key. Uses `DEEPSEEK_API_KEY` env var if not provided. |
| `model` | `str ⎪ None` | `"deepseek-chat"` | DeepSeek model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str ⎪ None` | `"https://api.deepseek.com"` | DeepSeek-compatible base URL. |
| `supports_tool_calling` | `bool` | `True` | Whether to use native Chat Completions tool calls and streamed tool deltas. Set to `False` to force JSON mode. |

### GrokLLM

xAI Grok API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | xAI API key. Uses `XAI_API_KEY` or `GROK_API_KEY` if not provided. |
| `model` | `str ⎪ None` | `"grok-4-latest"` | Grok model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, max_tokens, etc.). |
| `base_url` | `str ⎪ None` | `"https://api.x.ai/v1"` | xAI-compatible base URL. |
| `supports_tool_calling` | `bool` | `True` | Whether to use native Chat Completions tool calls and streamed tool deltas. Set to `False` to force JSON mode. |

### HuggingFaceLLM

HuggingFace Inference API implementation.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `api_key` | `str ⎪ None` | `None` | HuggingFace API token. Uses `HF_API_TOKEN` env var if not provided. |
| `model` | `str ⎪ None` | `""` | HuggingFace model name. Pass a concrete model id for production use. |
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
| `base_url` | `str ⎪ None` | `None` | Ollama server URL. If not provided, uses the `OLLAMA_URL` environment variable. |
| `headers` | `dict[str, str] ⎪ None` | `None` | Additional HTTP headers (including auth). |
| `model` | `str ⎪ None` | `"gemma4:e4b"` | Ollama model name. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, etc.). |
| `supports_tool_calling` | `bool` | `False` | Whether this model/server should use native Ollama tool calling. Defaults to JSON mode for small-model reliability. |

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
# Set OLLAMA_URL=http://localhost:11434 or pass directly
llm = OllamaLLM(model="mistral", base_url="http://localhost:11434")
```

#### Default Model Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `temperature` | `float` | `1.0` | Controls randomness (range depends on model). |

#### Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `call()` | `history: ConversationHistory` | `str` | Generate a single response using Ollama's API. |
| `call_stream()` | `history: ConversationHistory` | `AsyncIterator[str]` | Generate a streaming response, yielding text chunks. |
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
| `model` | `str ⎪ None` | `"gemma4:e4b"` | The requested model representation. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters (temperature, etc.). |
| `supports_tool_calling` | `bool` | `False` | Whether this `llama-server` model/template supports native Chat Completions tool calls. |

```python
from protolink.llms.server import LlamaCPPServerLLM

llm = LlamaCPPServerLLM(
    base_url="http://localhost:8080",
    model="llama3"
)
```

### OpenAICompatibleLLM

Generic server client for OpenAI-compatible chat completion APIs. Use this for LM Studio-compatible servers, vLLM, LocalAI, llama.cpp server variants, or any custom service exposing `/v1/chat/completions` and `/v1/models`.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `base_url` | `str ⎪ None` | `None` | Server URL. Defaults to `OPENAI_COMPATIBLE_BASE_URL` or `http://localhost:1234/v1`. |
| `api_key` | `str ⎪ None` | `None` | Optional bearer token. Defaults to `OPENAI_COMPATIBLE_API_KEY`. |
| `headers` | `dict[str, str] ⎪ None` | `None` | Additional HTTP headers. |
| `model` | `str ⎪ None` | `"local-model"` | Model id passed to the server. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters such as `temperature`. |
| `supports_tool_calling` | `bool` | `False` | Whether the server/model supports native tool calling payloads. |

```python
from protolink.llms.server import OpenAICompatibleLLM

llm = OpenAICompatibleLLM(
    base_url="http://localhost:1234/v1",
    api_key="optional-token",
    model="qwen2.5-coder-7b-instruct",
)
```

### LMStudioLLM

Convenience wrapper for LM Studio's local OpenAI-compatible server.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `base_url` | `str ⎪ None` | `None` | LM Studio URL. Defaults to `LMSTUDIO_URL` or `http://localhost:1234/v1`. |
| `api_key` | `str ⎪ None` | `None` | Optional bearer token. Defaults to `LMSTUDIO_API_KEY`; otherwise uses `lm-studio`. |
| `headers` | `dict[str, str] ⎪ None` | `None` | Additional HTTP headers. |
| `model` | `str ⎪ None` | `"local-model"` | Model id selected in LM Studio. |
| `model_params` | `dict[str, Any] ⎪ None` | `None` | Model parameters such as `temperature`. |
| `supports_tool_calling` | `bool` | `False` | Whether the selected model/server supports native tool calling. |

```python
from protolink.llms.server import LMStudioLLM

llm = LMStudioLLM(
    model="local-model",
    base_url="http://localhost:1234/v1",
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
| `supports_tool_calling` | `bool` | `False` | Whether the loaded model/chat handler supports native tool calls. Defaults to JSON mode. |

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
async for chunk in llm.chat("Hello!", streaming=True):
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
    "openai", "anthropic", "gemini", "deepseek", "grok",
    "huggingface", "llama.cpp-local", "llama.cpp-server",
    "lmstudio", "mock", "ollama", "openai-compatible"
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
