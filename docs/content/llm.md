import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# LLMs

ProtoLink's LLM package starts with a simple promise: choose where a model runs, then use the same application-facing contract to talk to it. That contract can stop after one text response, stream text as it arrives, or continue into a controlled Agent loop where the model requests tools and delegates work while ProtoLink remains responsible for execution.

The useful mental model is a progression:

1. **Choose a backend**: hosted API, model server, in-process local model, or deterministic mock.
2. **Create one adapter** with `create_llm()` or a concrete provider class.
3. **Pick the interaction level**: `chat()` for one direct response, `infer()` for controlled multi-step work, or the lower-level `call*()` methods when implementing an adapter.
4. **Let an Agent own runtime concerns** such as tool selection, delegation, policy, cancellation, state, and events.
5. **Add operational features when needed**: persistent history, explicit compaction, context reporting, cost estimates, and run budgets.

<ApiSurface
  eyebrow="Model runtime module"
  title="LLM"
  path="protolink.llms"
  description="Choose a model backend, make direct or streamed calls, and graduate to a controlled inference loop without rewriting the rest of the application."
  pills={[
    "Provider-neutral",
    "Direct and streamed text",
    "Tool-aware inference",
    "Agent integration",
    "Optional operations",
  ]}
  cards={[
    {
      title: "Choose",
      text: "Use a hosted API, your own model server, an in-process GGUF model, or a deterministic mock.",
      code: "create_llm()",
    },
    {
      title: "Converse",
      text: "Ask for one complete response or consume text chunks as they arrive.",
      code: "LLM.chat()",
    },
    {
      title: "Act",
      text: "Run the typed action loop used by Agent for tools and delegation.",
      code: "LLM.infer()",
    },
    {
      title: "Operate",
      text: "Manage history and add compaction, metrics, context visibility, and budgets when the application needs them.",
      code: "LLM.compact_history()",
    },
  ]}
/>

## Start with the interaction you need

Most application code should begin with either `chat()` or an `Agent`. The other methods exist so provider adapters and advanced integrations can participate in the same runtime.

- **One complete response - `llm.chat("...")`**<br />
  Adds the user message and performs one synchronous provider call.

- **Visible incremental text - `llm.chat("...", streaming=True)`**<br />
  Returns an asynchronous iterator of text chunks.

- **Tools, delegation, policy, retries, budgets, and multiple steps - `Agent(..., llm=llm)`**<br />
  The Agent prepares the runtime and invokes `LLM.infer()` with the appropriate services.

- **A custom controlled runtime - `await llm.infer(...)`**<br />
  Advanced integration path where the caller prepares the prompt, history, tools, callbacks, and runtime context that an Agent normally supplies.

- **A provider adapter or diagnostic integration - `call()`, `call_stream()`, and `call_action()`**<br />
  Works at the provider boundary with explicit `ConversationHistory` and normalized actions.

`chat()` and `infer()` are intentionally different. A chat call asks the model for text. Inference asks the model for one typed decision at a time: finish with text, call a local tool, or delegate to another Agent. ProtoLink validates that decision and performs the side effect outside the model.

:::tip[The common application path]

Use `chat()` for a small standalone model interaction. Use an `Agent` when model output can cause work to happen. Reach for `call()` and `call_stream()` primarily when extending or diagnosing a provider adapter.

:::

:::note[Provider-neutral scope]

The current common contract is text-oriented: chat inputs, canonical history content, complete responses, and stream chunks are strings. Provider support does not imply that every provider-specific feature is wrapped. Use the provider SDK directly for capabilities outside this surface, such as file-upload APIs, image or audio generation, embeddings, fine-tuning, batch administration, or model management.

:::

## Choose where the model runs

ProtoLink groups model backends into hosted APIs, model servers, and in-process local runtimes. A deterministic testing adapter follows the same contract without making a model request.

<div className="provider-strip-label">[ API ]   [ Server ]   [ Local ]</div>

<div className="provider-strip">
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/openai.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/anthropic_black.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/gemini.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/476aabb842086433647755b0963640c6a0775f79/static/library/grok-light.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/deepseek.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/ollama_light.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/lobehub/lobe-icons/refs/heads/master/packages/static-png/light/vllm-color.png" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/abetlen/llama-cpp-python/main/docs/icon.svg" width="55" className="hover-icon" />
</div>

- **API** - calls a remote provider and normally requires an API key:
    - `OpenAILLM`: OpenAI Responses API, including native function tools and streamed tool-call events.
    - `AnthropicLLM`: Anthropic Messages API, including native `tool_use` blocks.
    - `GeminiLLM`: Google GenAI API, including native function declarations.
    - `DeepSeekLLM`: DeepSeek Chat Completions API, with optional native tools.
    - `GrokLLM`: xAI Chat Completions API, with optional native tools.
    - `HuggingFaceLLM`: Hugging Face Inference API for non-streaming direct calls.

- **Server** - connects to a model server that you run locally or remotely:
    - `OllamaLLM`: connects to an Ollama `/api/chat` endpoint.
    - `LlamaCPPServerLLM`: connects directly to a `llama-server`.
    - `LMStudioLLM`: connects to LM Studio's OpenAI-compatible server.
    - `VLLMLLM`: connects to vLLM's OpenAI-compatible server.
    - `OpenAICompatibleLLM`: connects to a service exposing `/v1/chat/completions` and `/v1/models`.

- **Local** - runs the model inside the Python process:
    - `LlamaCPPLocalLLM`: loads a local GGUF file through `llama-cpp-python`.

For deterministic tests and offline examples, `MockLLM` can return fixed responses, response sequences, or callback-generated responses. It is the fastest way to test Agent behavior without credentials, network access, or nondeterministic model output.

You can also use a third-party LLM client directly when your application only needs that client's raw API. ProtoLink's wrappers become valuable when you want provider-neutral history, streaming, typed actions, Agent integration, compaction, events, metrics, or budgets.

### How to choose

- Choose a **hosted API** when you want a managed model and accept provider credentials, network latency, and usage billing.
- Choose a **server adapter** when the model is exposed by Ollama, llama-server, LM Studio, vLLM, or another OpenAI-compatible endpoint that you control.
- Choose **`LlamaCPPLocalLLM`** when the GGUF model should run inside the Python process and the process can afford model-loading and inference resources.
- Choose **`MockLLM`** for tests, examples, and runtime development.

Native tool support is an adapter-and-model capability, not a requirement for ProtoLink inference. OpenAI, Anthropic, and Gemini use provider-native tool structures. DeepSeek and Grok enable native tools by default but can fall back to the portable JSON action protocol. Self-hosted and local adapters use that JSON path by default unless a known-compatible model/server is explicitly opted into native tool calling.

## Install, configure, and make the first call

Configuration varies by backend, but the first successful model interaction follows one continuous path.

1. **Install the relevant extras**:

   ```bash
   # All supported LLM backends
   uv add "protolink[llms]"
   ```

:::info[Choosing LLM extras]

If you only need a subset of providers, install their SDKs directly instead of the `llms` extra, which installs every supported integration. Server and local adapters may not need a hosted-provider SDK.

:::

2. **Construct the LLM** through the lazy factory:

   ```python
   from protolink import create_llm

   llm = create_llm(
       "openai",
       model="gpt-4o-mini",
       # api_key is normally read from OPENAI_API_KEY
   )
   ```

   Import a concrete adapter when provider-specific configuration makes the code clearer:

   ```python
   from protolink.llms.api import OpenAILLM

   llm = OpenAILLM(model="gpt-4o-mini")
   ```

   The factory lazily imports only the selected adapter and its optional SDK. Construction itself is not deferred: concrete adapters currently validate during initialization and may perform network, server-health, model-loading, or filesystem work.

:::warning[API keys]

Never commit API keys to version control. Read them from environment variables or a secure secrets manager.

:::

3. **Make a direct call**:

   ```python
   response = llm.chat("Explain what this service does in two sentences.")
   print(response)
   ```

   As an alternative, use a fresh or explicitly managed history and consume the asynchronous iterator returned by streaming chat:

   ```python
   streaming_llm = create_llm("openai", model="gpt-4o-mini")

   async for chunk in streaming_llm.chat(
       "Draft a short welcome message.",
       streaming=True,
   ):
       print(chunk, end="", flush=True)
   ```

4. **Pass the same LLM to an Agent** when the model should participate in a controlled runtime:

   ```python
   from protolink.agents import Agent
   from protolink.models import AgentCard

   agent_card = AgentCard(
       url="http://localhost:8020",
       name="llm_agent",
       description="Agent backed by an LLM",
   )

   agent = Agent(card=agent_card, transport="http", llm=llm)
   ```

For local and server-style LLMs (`LlamaCPPLocalLLM`, `LlamaCPPServerLLM`, `OllamaLLM`, `LMStudioLLM`, `VLLMLLM`, and `OpenAICompatibleLLM`), configuration additionally includes a model-file path or server URL. The individual class entries below describe the resolution order for those values.

Generation parameters are deliberately provider-specific. `model_params` is forwarded to the selected SDK or server; ProtoLink does not translate names such as `max_tokens`, `max_output_tokens`, or provider-specific thinking controls into one synthetic schema.

:::note[Direct chat history]

`chat()` appends the user message before calling the provider, but it does not append the returned assistant text. That small behavior keeps the base method predictable across streaming and non-streaming adapters. Manage `ConversationHistory` explicitly for a standalone multi-turn script, or let an `Agent` own task-local and persistent conversation history.

:::

## From text generation to controlled inference

Direct generation ends when the provider returns text. Controlled inference can continue because the model is treated as a planner rather than an executor.

Each inference step follows the same story:

1. ProtoLink adds the user query and prepares the current system prompt, history, tools, and discovered Agents.
2. The provider adapter obtains one decision, either through native function/tool calling or the portable JSON action protocol.
3. ProtoLink validates the decision as `FinalAction`, `ToolCallAction`, or `AgentCallAction`.
4. A final action returns user-facing text. A tool or Agent action passes through authorization and is executed by the runtime.
5. The result becomes a new observation in history, and the model receives another step only when more work is necessary.

```python
answer = await agent.invoke(
    "Summarize the available information.",
    session_id="customer-42",
)
print(answer)
```

The Agent rebuilds the system prompt for the current tool set, action mode, discovered Agents, flow position, and application instructions before it invokes `LLM.infer()`. It also supplies the policy authorizer, cancellation token, run context, budget policy, event callback, and isolated history.

:::caution[Calling `infer()` directly]

Direct inference is available for custom runtimes, but passing a `tools` dictionary does not itself rebuild the LLM's system prompt. A direct caller must call `build_system_prompt()` with the matching tool and Agent descriptions and must provide any callbacks, authorization, cancellation, and context it needs. For normal tool use, prefer `Agent.add_tool()` or `@agent.tool` followed by `await agent.invoke(...)`.

:::

### Streaming means two different things

- `chat(..., streaming=True)` returns an async iterator because the chunks are the result.
- `infer(streaming=True)` still returns one final `Part`. Intermediate model text is emitted as `llm_chunk` events through the inference event callback while the runtime waits for a complete, validated action.

This distinction lets an Agent show live progress without dispatching a partial or malformed tool request.

### Tools and delegated Agents stay behind a runtime boundary

Provider-native adapters expose tool schemas using the provider's function-calling format. Other adapters describe the same choices in the system prompt and parse one JSON action. Both routes converge on the same typed action models before anything executes.

The runtime then applies the protections that a raw model call does not provide: unknown-tool checks, policy and approval decisions, cancellation, duplicate-action detection, parse-error feedback, transient provider retries, per-run budgets, and a ten-step inference limit.

The detailed [controlled inference and tool-use](#controlled-inference-and-tool-use) chapter below explains action acquisition, recovery, prompts, and delegation. The `LLM.infer()` reference documents every integration hook.

## Conversation history inside and outside an Agent

An `LLM` instance still exposes `llm.history` for direct usage and backward-compatible introspection. When the same LLM is plugged into an `Agent`, ProtoLink binds a task-local `ConversationHistory` around each run so concurrent tasks do not interleave messages on one shared mutable history object.

For stateless agents, each task receives a fresh history seeded by the compiled system prompt. After normal completion, `llm.history` points at a copy of that task history for debugging and simple scripts. A failed turn normally stays isolated; if an `action_result` receipt proves that a side effect completed, ProtoLink retains the history containing that observation so a retry does not behave as though the action never ran.

For persistent conversation state, enable `state=["conversation"]`. The Agent loads the requested `session_id`, serializes concurrent tasks for that same session with an async lock, saves normally completed history back to state, and exposes a copy as `llm.history`. Failed history is saved only when a new `action_result` receipt proves that the turn completed a tool or delegation side effect.

```python
from protolink import Agent, AgentCard, RunContext, Task, create_llm

agent = Agent(
    AgentCard(
        name="assistant",
        description="Assistant",
        url="runtime://assistant",
    ),
    llm=create_llm("mock", default_response="ok"),
    state=["conversation"],
)

task = Task.create_infer(prompt="remember this")
RunContext(session_id="customer-42").attach_to_task(task)
await agent.execute_task(task)
```

Direct `llm.infer(...)` calls are unchanged: they use the LLM's default history unless you explicitly call `llm.use_history(history)`.

## History compaction

Every LLM wrapper owns a modular `HistoryCompactor` at `llm.compactor`. Its `compact()` method mutates the current `ConversationHistory` in place and returns a `HistoryCompactionResult` with before/after message and estimated-token counts. `LLM.compact_history()` remains as a convenient facade, so direct usage stays concise.

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

Three strategies cover different cost and fidelity needs:

| Strategy | Model calls | Behavior | Best for |
|----------|-------------|----------|----------|
| `recent` | 0 | Keeps the leading system prompt and newest `max_messages` messages. | A simple, fast sliding window. |
| `tokens` | 0 | Keeps the newest chronological suffix near `max_tokens`, using `tiktoken` when installed or the built-in estimate otherwise. | Deterministic context-budget control. |
| `summary` | 1 | Replaces older turns with a model-generated system summary and keeps `preserve_recent` turns verbatim. | Retaining decisions and constraints from long sessions. |

The `tokens` limit is deliberately soft when the leading system prompt plus protected recent messages already exceed the budget: ProtoLink preserves those messages instead of silently removing the active request. The `summary` strategy makes its model call with a temporary history. The live history is changed only after a non-empty summary is returned, so a provider failure leaves it untouched.

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

:::note[Compaction is explicit]

ProtoLink does not compact history automatically based on an arbitrary context threshold. Applications can call `llm.compact_history()` for local use, `agent.compact_history()` inside an Agent process, or `AgentClient.compact_history()` over a transport. Natural-language requests such as “please compact your context” are application intent; convert them into a control-plane request before calling the Agent if you want deterministic behavior.

:::

## How the LLM package is organized

The public facade is `protolink.llms.base.LLM`. Internally, the base class owns provider-neutral orchestration: history binding, metrics, budgets, retries, tool execution, Agent delegation, and final response handling. The strict action parser lives in `protolink.llms.parsing`, where raw model text becomes one validated `LLMAction` and narrow fallback shorthands are repaired only when the target tool or Agent is unambiguous.

Provider adapters keep request and stream handling in their own modules, then return typed results to the shared inference loop:

- `protolink.llms.api` contains hosted-provider adapters.
- `protolink.llms.server` contains HTTP model-server adapters.
- `protolink.llms.local` contains the in-process llama.cpp adapter.
- `protolink.llms.mock_client` provides deterministic testing behavior.

The rest of the package is partitioned by responsibility:

- `factory.py` lazily resolves provider names and constructs adapters.
- `history.py` defines canonical messages and provider-neutral conversation history.
- `actions.py`, `parsing.py`, and `tool_calling.py` define typed runtime actions and translate provider-native function calls into them.
- `context.py` builds a context manifest for each inference step.
- `compaction.py` owns explicit history reduction and summary compaction.
- `metrics.py` normalizes usage, estimates missing token counts, and calculates application-supplied costs.
- `prompts/` keeps JSON-action and provider-native prompt families separate so the model never receives conflicting tool instructions.
- `serialization.py` provides JSON-safe conversion for history and runtime payloads.
- `_deps.py` loads optional provider SDKs only when their adapter is selected.

This separation keeps the everyday API small while allowing native tool-calling providers and JSON-fallback models to participate in the same controlled runtime.

## Observe and constrain model work

Profiles, context manifests, call metrics, and run budgets matter when a working model integration becomes an operated system. They are intentionally optional and do not need to be configured before the first call.

### Model metadata

`LLMModelProfile` describes the deployment information ProtoLink cannot safely hardcode: context-window size, application-supplied input and output prices, tokenizer metadata, and descriptive capability flags. A profile does not change the provider request or enable a feature in the selected model.

```python
from protolink import LLMModelProfile, create_llm

llm = create_llm(
    "openai-compatible",
    model="my-model",
    metrics_profile=LLMModelProfile(
        context_window=128_000,
        input_cost_per_million=1.0,   # example value; use current provider pricing
        output_cost_per_million=5.0,  # example value; use current provider pricing
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

Provider-reported token usage is used when the SDK response includes it. Otherwise ProtoLink estimates token counts locally. If `tiktoken` is installed through `protolink[metrics]`, ProtoLink resolves an encoder from the active model name and falls back to `cl100k_base`; without it, ProtoLink uses a lightweight character heuristic. The profile's `tokenizer` field is currently descriptive metadata and does not select the estimator. Prices, model limits, and capabilities change over time, so `LLMModelProfile` is application-owned metadata rather than a hardcoded billing catalog.

### Context and call events

LLM wrappers can emit pre-call context manifests plus per-call latency, token usage, context-window pressure, and estimated cost through the existing `infer()` event stream and telemetry hooks. Observing these events does not change the request payload sent to the provider.

Before each model call, ProtoLink emits a provider-neutral `context_prepared` event:

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
    "usage": {
        "input_tokens": 1200,
        "output_tokens": 180,
        "estimated": False,
    },
    "context": {
        "used_tokens": 1200,
        "window_tokens": 128000,
        "used_percent": 0.938,
    },
    "cost": {
        "input_cost": 0.0012,
        "output_cost": 0.0009,
        "total_cost": 0.0021,
    },
}
```

This is especially useful for CLIs, dashboards, and budget-aware agents that want to show context pressure or session cost while a multi-step tool loop is running.

### Run-budget enforcement

Model profiles are observational metadata. Run budgets are the separate enforcement mechanism.

If a `RunContext` carries a `RunBudget`, `LLM.infer()` enforces it through the default `BudgetEnforcer`. When an Agent executes a task, one task-local enforcer is shared by every infer part and explicit tool-call part, so counters do not reset between parts. A nested task gets its own scope, and direct `LLM.infer()` calls still create an independent enforcer unless the advanced caller supplies `budget_enforcer=` explicitly.

Pre-call limits such as `max_llm_calls` and `max_input_tokens` are checked before every physical provider attempt, including transient retries. `max_tool_calls` applies before explicit and model-selected tools execute; `max_output_tokens` is checked after provider usage or local estimates are available. Provider runtime is checked again after each request, including a final response. A tool or delegated call can already have committed a side effect when it returns, so ProtoLink records and injects that result before cancellation or runtime enforcement stops the next step. Warnings appear as `budget_warning` events and hard denials appear as `budget_exceeded` events.

## LLM API reference

The rest of this page is the detailed contract. It starts with construction and the base methods, then follows controlled inference, prompts, concrete providers, related objects, examples, and failure handling.

### Provider switching in action

The same application code works across providers. Keep provider choice in configuration, construct exactly one adapter, and leave the calling code unchanged. `chat()` is the high-level convenience method for direct text generation; internally it selects `call()` or `call_stream()`.

```python
from protolink import create_llm

# Choose one deployment in application configuration.
provider = "ollama"
provider_options = {
    "openai": {
        "model": "gpt-4o-mini",
    },
    "anthropic": {
        "model": "claude-sonnet-4-20250514",
    },
    "ollama": {
        "model": "qwen3",
        "base_url": "http://localhost:11434",
    },
    "lmstudio": {
        "model": "local-model",
        "base_url": "http://localhost:1234/v1",
    },
    "vllm": {
        "model": "Qwen/Qwen3-8B",
        "base_url": "http://localhost:8000/v1",
    },
}

llm = create_llm(provider, **provider_options[provider])

# The calling code stays the same.
response = llm.chat("Hello! How are you?")
print(response)
```

:::info[LLM hierarchy]

- **`LLM`** - abstract base class with the common runtime behavior.
- **`APILLM`** - base for API-hosted adapters.
- **`ServerLLM`** - base for HTTP model servers.
- **`LocalLLM`** - base for in-process local runtimes.
- **Concrete implementations** - `OpenAILLM`, `AnthropicLLM`, `GeminiLLM`, `DeepSeekLLM`, `GrokLLM`, `HuggingFaceLLM`, `OllamaLLM`, `LlamaCPPServerLLM`, `LMStudioLLM`, `VLLMLLM`, `OpenAICompatibleLLM`, `LlamaCPPLocalLLM`, and `MockLLM`.

:::

Each callable below keeps the scikit-learn-style layout: exact signature, explanation, separately labeled parameters and defaults, return values, raised errors, notes, and focused examples.

### create_llm

<ApiReference
  kind="function"
  path="protolink.create_llm"
  signature={`create_llm(
    provider: str | LLMProvider,
    **kwargs,
) -> LLM`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/factory.py#L97"
>

Create an LLM adapter without importing the selected provider until it is needed.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="create_llm parameters">
    <ApiField name="provider" type="str | LLMProvider" required>
      Provider selector. Supported string values are <code>anthropic</code>, <code>deepseek</code>, <code>gemini</code>, <code>grok</code>, <code>huggingface</code>, <code>llama.cpp-local</code>, <code>llama.cpp-server</code>, <code>lmstudio</code>, <code>mock</code>, <code>ollama</code>, <code>openai</code>, <code>openai-compatible</code>, and <code>vllm</code>.
    </ApiField>
    <ApiField name="**kwargs" type="Any">
      Forwarded to the selected adapter constructor. Three factory-only keywords are also recognized:
      <code>metrics_profile</code> configures model metrics after construction,
      <code>metrics_enabled</code> enables or disables their emission, and
      <code>max_parse_failures</code> sets the validated consecutive action-parse failure limit without forwarding
      that ProtoLink-only option to the provider.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="create_llm return value">
    <ApiField name="llm" type="LLM">
      An initialized concrete adapter for the requested provider.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="create_llm errors">
    <ApiField name="ValueError">
      Raised when the provider string is unknown or <code>max_parse_failures</code> is outside the supported range.
    </ApiField>
    <ApiField name="TypeError">
      Raised when <code>max_parse_failures</code> is not an integer. Boolean values are not accepted as integers for
      this option.
    </ApiField>
    <ApiField name="ImportError">
      Raised when the selected adapter requires an optional dependency that is not installed.
    </ApiField>
    <ApiField name="provider or constructor error">
      Credential, model-path, URL, and client-construction errors from the selected adapter are not hidden.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Current behavior">
  Pass provider names as strings. Although the annotation includes <code>LLMProvider</code>, enum instances are not currently normalized correctly by the factory.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import LLMModelProfile, create_llm

llm = create_llm(
    "openai-compatible",
    base_url="http://localhost:1234/v1",
    model="local-model",
    metrics_profile=LLMModelProfile(context_window=32_768),
    max_parse_failures=4,
)
```

`max_parse_failures` defaults to `3` and accepts integers from `1` through `10`. Keep it as a top-level factory
argument. Do not place it in `model_params`, whose entries are provider generation options.

</ApiSection>

</ApiReference>

## Base LLM contract

The `LLM` class defines the common interface that every implementation follows. Concrete adapters are deliberately thin at the runtime boundary: they translate `ConversationHistory` into a provider request, translate responses and streams back into ProtoLink values, and validate connectivity. The base class supplies the shared behavior around those calls.

Application code normally constructs a provider through `create_llm()` and calls `chat()` for direct text generation. `Agent` uses the more powerful `infer()` path, which adds typed actions, tool execution, delegation, policy checks, budgets, events, retries, and bounded iteration.

The core surface falls into four groups:

- **Provider invocation**: `call()` and `call_stream()` are implemented by concrete adapters.
- **Direct conversation**: `chat()` appends a user message and selects the blocking or streaming provider path.
- **Structured action acquisition**: `call_action()` and `call_action_stream()` normalize native tool calls or JSON output into `LLMActionResult`.
- **Runtime orchestration**: `infer()` repeatedly validates and dispatches those actions until the model returns a final answer.

:::info[History performance]

`ConversationHistory` uses a `collections.deque` internally. Prepending or replacing the system prompt is an O(1) operation, and trimming older turns avoids repeated list reallocation on hot agent paths.

:::

:::note[Abstract base class]

Do not instantiate `LLM` directly. Use a concrete implementation such as `OpenAILLM`, `AnthropicLLM`, `OllamaLLM`, or `MockLLM`, normally through `create_llm()`.

:::

### LLM

<ApiReference
  kind="abstract class"
  path="protolink.llms.base.LLM"
  signature={`class LLM(
    model: str,
    model_params: dict[str, Any],
    *,
    reasoning: Literal["none", "low", "medium", "high"] = "none",
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L154"
>

Abstract provider-neutral model contract. Subclasses implement text generation and connection validation; the base class owns history binding, typed action parsing, inference orchestration, compaction, and metrics.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM constructor parameters">
    <ApiField name="model" type="str" required>
      Provider-specific model identifier or local model path.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any]" required>
      Generation parameters passed to the adapter. The base class verifies only that later assignments remain dictionaries; the downstream SDK or server validates individual keys and values.
    </ApiField>
    <ApiField name="reasoning" type={'"none" | "low" | "medium" | "high"'} defaultValue={'"none"'}>
      Selects the reasoning instruction block included when the base system prompt is built. This argument is mainly for custom subclasses; current concrete provider constructors do not expose it.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="LLM attributes">
    <ApiField name="model" type="str">
      Resolved model identifier.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any]">
      Mutable provider generation parameters.
    </ApiField>
    <ApiField name="history" type="ConversationHistory">
      Default history for direct calls, or the task-local history currently bound by <code>use_history()</code>.
    </ApiField>
    <ApiField name="has_active_history" type="bool">
      Whether the current execution context has a task-local history binding.
    </ApiField>
    <ApiField name="compactor" type="HistoryCompactor">
      Component that mutates the live history using recent-message, token-budget, or summary compaction.
    </ApiField>
    <ApiField name="system_prompt" type="str">
      Prompt last built or assigned on the adapter.
    </ApiField>
    <ApiField name="metrics_profile" type="LLMModelProfile | None">
      Optional application-owned context-window and cost metadata.
    </ApiField>
    <ApiField name="metrics_enabled" type="bool">
      Whether inference may emit metrics when an observer is attached.
    </ApiField>
    <ApiField name="max_parse_failures" type="int">
      Maximum consecutive JSON-action parsing or validation failures allowed during one inference run. Defaults to
      <code>3</code> and accepts values from <code>1</code> through the ten-step inference ceiling. This runtime
      control is deliberately separate from provider generation parameters.
    </ApiField>
    <ApiField name="sync" type="SyncLLM">
      Blocking wrapper for <code>infer()</code>. Do not use it inside an active event loop.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Module constant">
  The ten-step inference limit is <code>protolink.llms.base.MAX_INFER_STEPS</code>. It is a module constant, not an <code>LLM</code> class attribute.
</ApiCallout>

</ApiReference>

### LLM.chat

<ApiReference
  kind="method"
  path="protolink.llms.base.LLM.chat"
  signature={`chat(
    user_query: str,
    *,
    streaming: bool = False,
) -> str | AsyncIterator[str]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L441"
>

Add one user message to the active history, then make a direct provider call.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM chat parameters">
    <ApiField name="user_query" type="str" required>
      User text appended to the current <code>ConversationHistory</code>.
    </ApiField>
    <ApiField name="streaming" type="bool" defaultValue="False">
      When <code>False</code>, return the complete provider response. When <code>True</code>, return an asynchronous iterator of text chunks.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM chat return value">
    <ApiField name="response" type="str">
      Complete model text when <code>streaming=False</code>.
    </ApiField>
    <ApiField name="chunks" type="AsyncIterator[str]">
      Asynchronous text stream when <code>streaming=True</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="History behavior">
  <code>chat()</code> appends the user message, but it does not append the returned assistant text. Use <code>Agent</code> state or manage <code>ConversationHistory</code> explicitly when you need durable multi-turn history.
</ApiCallout>

<ApiSection title="Examples">

```python
answer = llm.chat("Give me a title for this report.")

async for chunk in llm.chat("Draft the introduction.", streaming=True):
    print(chunk, end="")
```

</ApiSection>

</ApiReference>

### LLM.call

<ApiReference
  kind="abstract method"
  path="protolink.llms.base.LLM.call"
  signature={`call(
    history: ConversationHistory,
) -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L407"
>

Generate one complete text response from a conversation history. Concrete adapters translate the history into their provider’s request format.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM call parameters">
    <ApiField name="history" type="ConversationHistory" required>
      Ordered system, user, assistant, and tool messages sent to the model.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM call return value">
    <ApiField name="response" type="str">
      Raw text extracted from the provider response.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LLM call errors">
    <ApiField name="NotImplementedError">
      Raised by the abstract base implementation.
    </ApiField>
    <ApiField name="provider error">
      Concrete adapters generally propagate authentication, HTTP, SDK, and model errors from the provider call.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### LLM.call_stream

<ApiReference
  kind="abstract method"
  path="protolink.llms.base.LLM.call_stream"
  signature={`call_stream(
    history: ConversationHistory,
) -> AsyncIterator[str]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L421"
>

Start a streaming provider call and yield incremental text chunks.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM call stream parameters">
    <ApiField name="history" type="ConversationHistory" required>
      Conversation sent to the provider.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Yields">
  <ApiFields ariaLabel="LLM call stream yields">
    <ApiField name="chunk" type="str">
      The next incremental piece of model output.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Consumption">
  Consume the returned object with <code>async for</code>. Do not await <code>call_stream()</code> itself.
</ApiCallout>

</ApiReference>

### LLM.call_action

<ApiReference
  kind="method"
  path="protolink.llms.base.LLM.call_action"
  signature={`call_action(
    history: ConversationHistory,
    *,
    tools: dict[str, BaseTool],
    agent_callback_available: bool = False,
    agent_cards: list[Any] | None = None,
) -> LLMActionResult`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L480"
>

Acquire one validated runtime action. The base implementation parses a JSON action from text; native-capable adapters override it and normalize provider tool calls into the same result type.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM call action parameters">
    <ApiField name="history" type="ConversationHistory" required>
      Conversation for the current inference step.
    </ApiField>
    <ApiField name="tools" type="dict[str, BaseTool]" required>
      Tool names mapped to executable tool objects. Native adapters turn this mapping into provider tool declarations.
    </ApiField>
    <ApiField name="agent_callback_available" type="bool" defaultValue="False">
      Whether the runtime can dispatch agent-delegation actions.
    </ApiField>
    <ApiField name="agent_cards" type="list[Any] | None" defaultValue="None">
      Discovered agents available for native declarations and unambiguous fallback repair.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM call action return value">
    <ApiField name="result" type="LLMActionResult">
      A validated <code>FinalAction</code>, <code>ToolCallAction</code>, or <code>AgentCallAction</code>, together with the raw response and provider metadata.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LLM call action errors">
    <ApiField name="ValueError">
      Raised when direct fallback parsing cannot produce a valid action.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### LLM.call_action_stream

<ApiReference
  kind="async method"
  path="protolink.llms.base.LLM.call_action_stream"
  signature={`async call_action_stream(
    history: ConversationHistory,
    *,
    tools: dict[str, BaseTool],
    agent_callback_available: bool = False,
    agent_cards: list[Any] | None = None,
    chunk_callback: Callable[[str], Awaitable[None]] | None = None,
) -> LLMActionResult`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L518"
>

Streaming counterpart to `call_action()`. The fallback implementation forwards text chunks to the observer, buffers the complete response, and validates exactly one action after the stream ends.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM streaming action parameters">
    <ApiField name="history" type="ConversationHistory" required>
      Conversation for the current inference step.
    </ApiField>
    <ApiField name="tools" type="dict[str, BaseTool]" required>
      Tools available to the model.
    </ApiField>
    <ApiField name="agent_callback_available" type="bool" defaultValue="False">
      Whether agent delegation can be dispatched.
    </ApiField>
    <ApiField name="agent_cards" type="list[Any] | None" defaultValue="None">
      Discovered agents available for delegation.
    </ApiField>
    <ApiField name="chunk_callback" type="Callable[[str], Awaitable[None]] | None" defaultValue="None">
      Async observer invoked for each emitted text chunk.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM streaming action return value">
    <ApiField name="result" type="LLMActionResult">
      One complete validated runtime action. Partial JSON fragments are never dispatched.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LLM streaming action errors">
    <ApiField name="ValueError">
      Raised when an empty or malformed fallback stream cannot be parsed as an action.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## Controlled inference and tool use

### What inference means in ProtoLink

`infer()` is the cornerstone of ProtoLink's agent runtime. A normal model call asks for text and returns text. Inference instead treats the model as a decision-maker inside a controlled loop: the model declares one typed action, ProtoLink validates and performs that action, the result is returned to the model as an observation, and the cycle continues until the model can produce a final answer.

This distinction is important. The LLM never executes Python code, invokes a remote agent, grants its own approval, or decides whether a budget may be exceeded. It can only request a `final`, `tool_call`, or `agent_call` action. ProtoLink remains the executor and policy boundary.

In normal applications, `Agent` prepares the prompt and calls `infer()` automatically. Direct calls remain available for advanced integrations that already have tools, callbacks, runtime policy, and history under their own control.

`infer()` enables a model to:

1. **Make tool calls** - request external functions with structured arguments.
2. **Delegate to agents** - pass work to a discovered specialized agent.
3. **Observe results** - receive tool or agent output in conversation history.
4. **Self-correct** - revise malformed actions, wrong arguments, or unavailable targets.
5. **Generate a final response** - return user-facing content only after the required work is complete.

### How action acquisition works

Every provider ultimately returns the same `LLMActionResult`, but it can acquire that action in one of two ways:

| Mode | Used by | Model instruction | Runtime behavior |
|------|---------|-------------------|------------------|
| JSON action mode | Default for local/small models and providers without reliable native tools | Return one JSON object such as `{"type":"tool_call","tool":"search","args":{"q":"..."}}` | `call_action()` or the fallback `call_action_stream()` parses text, validates it with Pydantic, and returns a typed action. |
| Native action mode | OpenAI, Anthropic, Gemini, and opted-in tool-capable servers | Use the provider's function or tool interface | The adapter sends real tool declarations, receives provider-native tool events, and normalizes them into the same typed action models. |

The rest of the loop is identical:

1. **Prompt selection**: the Agent builds either the portable JSON prompt or the native-tool prompt. Streaming uses native instructions only when the adapter supports native streamed actions.
2. **Context preparation**: the current query, history, tools, discovered agents, flow context, and runtime manifest are assembled.
3. **Action acquisition**: `call_action()` or `call_action_stream()` obtains one model decision.
4. **Validation**: the decision becomes a `FinalAction`, `ToolCallAction`, or `AgentCallAction`. Raw provider objects never reach the dispatcher.
5. **Policy and budget checks**: cancellation, authorization, capabilities, approvals, and remaining run budget are evaluated before side effects.
6. **Dispatch**: ProtoLink executes a local tool, delegates to another agent, or accepts the final response.
7. **Observation injection**: tool and agent results are appended through the provider-specific or provider-neutral history path.
8. **Iteration**: the process repeats until `final` is produced or a guardrail stops the run.

:::info[What streaming JSON means]

Streaming JSON does not mean ProtoLink dispatches incomplete JSON fragments. The model streams ordinary text chunks that eventually form one complete action object. ProtoLink can forward those chunks to observers, but it buffers and validates the complete object before executing anything.

:::

:::tip[Small-model support]

Ollama, llama.cpp, LM Studio, vLLM, and generic OpenAI-compatible servers default to JSON action mode. Enable `supports_tool_calling=True` only for a model and chat-template combination that reliably emits native tool calls.

:::

### Inference-loop safety guardrails

The inference loop includes multiple layers of protection against unreliable model output and runaway execution.

#### 1. Deduplication detection

The runtime tracks a sliding window of successfully completed side-effect signatures. If the model requests an identical tool or agent action with identical arguments, ProtoLink:

- does not execute the duplicate;
- injects corrective guidance into history; and
- asks the model to use the existing observation, choose a different action, or finish.

Failed validation or execution does not poison the window, delegated infer signatures include the complete prompt, and final actions are returned immediately even when their text repeats. This prevents repeated side effects without suppressing a valid answer.

```text
You have already performed this action. The result is in your context.
Proceed with the task: produce a final response or choose a different action.
```

#### 2. Action parsing and the parse-failure circuit breaker

The parser is a security and interoperability boundary between untrusted model output and the runtime dispatcher. It
does not execute a tool or contact an Agent while trying to understand malformed text. It first produces one typed
`FinalAction`, `ToolCallAction`, or `AgentCallAction`; only that validated action can continue to policy, budget, and
dispatch checks.

Provider-native tool calls and portable JSON actions enter this boundary differently:

- A native-capable adapter translates the provider's structured tool event into the same Pydantic action models.
- A JSON-mode adapter passes the complete model text through the shared prompt-fallback parser.

The JSON path follows a deliberately conservative pipeline:

1. **Decode the untouched whole response.** Valid JSON is never rewritten first. This preserves literal text such as
   `"<think>keep this</think>"` inside a valid final response.
2. **Recover syntax-only wrappers when whole-response decoding fails.** ProtoLink can unwrap a complete JSON code
   fence, ignore one complete leading `<think>` or `<thought>` block, remove trailing commas outside JSON strings, or
   extract exactly one balanced object embedded in surrounding prose. The balanced scanner tracks nesting, quoted
   strings, and escapes in one pass.
3. **Normalize only deterministic response shapes.** A structured value placed in `FinalAction.content` can be
   serialized losslessly as JSON text. A non-empty application object that omits the outer action envelope can become
   final content only when it contains no ProtoLink action-envelope fields. Existing legacy tool-call shorthands are
   repaired only when the tool and optional Agent target are unambiguous and their arguments are literal data.
4. **Validate the complete action with Pydantic.** Required fields, discriminated action types, forbidden extra fields,
   delegated-action combinations, and content types are checked before the infer loop sees the result.

Common small-model variations therefore have explicit outcomes:

| Model output | Parser behavior |
|--------------|-----------------|
| `{"type":"final","content":{"answer":42}}` | Serializes the object to JSON text and returns a `FinalAction`. |
| `{"answer":42,"sources":["doc-1"]}` | Wraps the application object as final JSON content because no action-envelope field is present. |
| ```` ```json {"type":"final","content":"done"} ``` ```` | Unwraps the complete fence and validates the action. |
| `Result: {"type":"final","content":"done"}` | Extracts and validates the single balanced object. |
| `{"type":"final","content":"done",}` | Removes the unambiguous trailing comma outside strings, then validates. |
| A complete leading `<think>...</think>` followed by one action | Ignores the reasoning wrapper only after untouched JSON decoding failed. |

The parser intentionally refuses cases where repair would require choosing or inventing meaning:

- two or more valid top-level JSON objects;
- an incomplete leading reasoning wrapper;
- an empty object or a non-object action payload;
- an explicit unknown action type;
- a tool- or Agent-shaped object with a missing action type;
- a missing tool, target, prompt, or argument that cannot be inferred uniquely; or
- an action found only inside a private reasoning wrapper with no public action after it.

Raw responses and parsed payloads use deterministic, 2,000-character head-and-tail previews in diagnostics. This keeps
an oversized valid or invalid response from flooding logs and telemetry while retaining enough beginning/end context
to diagnose truncation. For a decoded action that fails schema validation, correction history receives the concise
field-level feedback and detected outer action type, not another copy of the parsed-payload preview.

##### Correction attempts

Parsing and action-schema failures are recoverable inside `infer()`. ProtoLink emits an `llm_parse_error` event,
retains bounded diagnostics for observability, and adds a correction message to conversation history. When JSON
decoding succeeded, the parser carries the decoded outer `type` separately from the rendered error. The retry can
therefore distinguish a malformed `agent_call`, malformed `tool_call`, invalid `final`, unknown action type, or object
with no recognizable outer type without scraping its own diagnostic text.

The correction also uses the current runtime capabilities. If the model selected `agent_call` but this inference has
no delegation callback, ProtoLink says that the action cannot be dispatched and does not show Agent-call examples. If
local tools or delegation are available, their canonical action shapes are included. ProtoLink does not silently
convert an explicit malformed side-effect request into final content.

```text
Your previous response was not a dispatchable ProtoLink action.
Validation feedback:
Action validation failed. Field-level errors:
  - Field 'agent_call -> action': Input should be 'tool_call' or 'infer'

The response selected `agent_call`, but no agent delegation route is available
for this inference, so that action cannot be dispatched.
Return exactly one JSON object using a currently dispatchable action:
- `final`: {"type":"final","content":"..."}
```

That is representative rather than a fixed template: field details and available alternatives depend on the rejected
payload, local tools, and delegation callback. A structurally valid `tool_call` or `agent_call` that reaches the
dispatcher but names an unavailable capability receives similarly explicit correction. It is not counted as a parse
failure because its action envelope was valid; the overall inference-step limit still prevents an endless correction
loop.

`max_parse_failures` controls the consecutive failure circuit breaker. It defaults to `3`, accepts integers from `1`
through `10`, and resets after a successfully validated action:

```python
from protolink import create_llm

llm = create_llm(
    "ollama",
    base_url="http://localhost:11434",
    model="qwen3",
    max_parse_failures=4,
)
```

Pass this option directly to `create_llm()`, or assign `llm.max_parse_failures` after construction. Do not put it in
`model_params`: those values are provider generation settings and are forwarded to the selected backend, while the
parse limit is ProtoLink runtime configuration.

The parse limit counts consecutive model action proposals that fail JSON decoding or action validation. It does not
configure transient HTTP/provider retries, and it does not validate an application-specific schema inside final text.
Those are separate boundaries whose retry budgets can multiply. Raising the limit can help a smaller model
self-correct, but repeating a deterministic shape error is better handled by a lossless normalization or a clearer
prompt than by unlimited retries.

##### The action envelope is not the application schema

`FinalAction.content` is user-facing text. ProtoLink validates the outer action but cannot know whether that text must
also satisfy a domain-specific JSON schema. If an application expects a decision, invoice, ballot, or other structured
result, it should validate `part.content` separately and apply only domain-safe recovery:

```python
from pydantic import BaseModel, Field

class Decision(BaseModel):
    label: str
    confidence: float = Field(ge=0, le=1)

part = await llm.infer(
    query="Return the requested decision as JSON in final content.",
    tools={},
)
decision = Decision.model_validate_json(part.content)
```

Do not infer missing high-impact fields from prose merely to make validation pass. A harmless public statement may
permit a text fallback; a payment instruction, tool target, categorical decision, or authorization result normally
should fail closed and request a new structured response.

:::caution[Parsing validates action shape, not semantic truth or authorization]

A hallucinated tool call can be perfectly valid JSON with the correct field types. Parsing proves that the requested
action is unambiguous and structurally valid; it does not prove that the action is factually correct, appropriate, or
authorized. Keep tools narrowly allowlisted, use strict argument schemas and capability policies, require approval for
important operations, enforce budgets and idempotency, and validate external identifiers at the execution boundary.

:::

#### 3. Self-correcting error recovery

Many model mistakes are observations, not immediate application failures:

| Error type | Runtime response |
|------------|------------------|
| Unknown or unavailable tool | Lists tools that are actually available, or states that this inference has none. |
| Missing required fields | Returns field-level validation details. |
| Wrong tool arguments | Explains the callable mismatch and asks the model to check the input schema. |
| Agent not found | Reports the unavailable target through the delegation callback. |
| Agent delegation unavailable | States that no delegation route exists and suggests only dispatchable alternatives. |
| Invalid action type | Reports the detected type and lists only action kinds available in the current inference. |

Tool arguments are validated and conservatively coerced before authorization, deduplication, or tool-budget consumption. These model mistakes normally remain inside `infer()` so the model can correct them. An exception raised by the tool body, including `TypeError`, remains an execution failure and is not relabeled as an argument mismatch.

When an Agent-owned inference tool or delegation succeeds, the Agent also attaches and immediately snapshots an `Artifact(kind="action_result")` receipt keyed by the runtime `action_id`. The receipt records completion and correlation metadata but deliberately omits the internal result, which remains in private LLM history. If a later step fails, exceeds budget, or is canceled, the Task and optional `RunStore` snapshot still show what already happened without exposing model-only observations or inviting an unsafe blind retry. Non-JSON or circular results receive a bounded serialization fallback in that private history so the completion observation cannot be lost.

#### 4. Physical retry safety

Transient provider failures use exponential backoff and jitter. Each physical attempt consumes the same LLM-call and input-token budget as an initial request and produces structured attempt metadata. Non-streaming calls may retry up to the configured retry limit; streaming calls may retry only before the first output chunk is exposed, preventing duplicated or discontinuous client output.

#### 5. Bounded execution

`MAX_INFER_STEPS` limits a run to ten model decisions. If the model never produces a final action, the method raises `RuntimeError` with diagnostic context instead of looping indefinitely.

:::note[Observers do not control execution]

Inference `event_callback` failures are logged and the observer is disabled for the remainder of that infer call. A telemetry or UI exporter cannot turn an otherwise successful provider or tool operation into an application failure.

:::

:::tip[Debugging inference loops]

If “maximum inference steps exceeded” appears frequently:

1. make the completion condition explicit in the system prompt;
2. split a broad task into smaller agent or flow steps;
3. improve tool names, descriptions, and input schemas;
4. observe normalized inference events to inspect each decision; and
5. verify that tool observations give the model enough information to finish.

:::

### Tool-call handling

Tool use has two separate phases:

1. **Action acquisition**: the adapter obtains one model decision and returns `LLMActionResult`.
2. **Observation injection**: after ProtoLink executes the tool, the adapter adds the result to history so the model can continue.

```python
def call_action(...) -> LLMActionResult:
    """Return one validated action for the current inference step."""

async def call_action_stream(...) -> LLMActionResult:
    """Return one validated action from a streaming inference step."""

def _inject_tool_call(
    self,
    *,
    tool_name: str,
    tool_args: dict,
    tool_result: Any,
) -> None:
    """Inject the runtime observation after a tool has executed."""
```

The base implementation asks for JSON, validates it, and injects a provider-neutral observation. Native adapters override action acquisition and observation injection where their API requires provider-specific tool-call IDs or message roles, but all paths converge before runtime dispatch.

### Provider-specific action modes

| Provider | Non-streaming `infer()` | Streaming `infer()` | Notes |
|----------|-------------------------|---------------------|-------|
| OpenAI | Native Responses function tools | Native streamed function-call events | Parallel tool calls are disabled so the runtime receives one action at a time. |
| Anthropic | Native `tool_use` blocks | Native streamed `input_json_delta` tool input | System instructions come from the task-local history; parallel tool calls are rejected. |
| Gemini | Native function declarations | Native streamed function-call parts | Function-call parts are normalized into ProtoLink actions. |
| DeepSeek | Native Chat Completions tools when `supports_tool_calling=True` | Native streamed tool deltas when enabled | Set the flag to `False` to force JSON action mode. |
| Grok | Native Chat Completions tools when `supports_tool_calling=True` | Native streamed tool deltas when enabled | Set the flag to `False` to force JSON action mode. |
| Ollama | JSON by default; native tools when explicitly enabled | JSON by default; native tool events when explicitly enabled | Keeps small/local model behavior simple unless tool support is known to work. |
| llama.cpp server/local | JSON by default; native tools when explicitly enabled | JSON by default; native tool events when explicitly enabled | Reliability depends on the selected model and chat template. |
| LM Studio / vLLM / OpenAI-compatible | JSON by default; native tools when explicitly enabled | JSON by default; native tool events when explicitly enabled | Dedicated subclasses provide conventional defaults and provider identity; the generic adapter covers LocalAI and compatible custom servers. |
| Hugging Face | JSON fallback for non-streaming inference | Not currently usable | `call_stream()` currently yields an empty chunk, so streaming inference is unsupported. |

### Prompt selection

ProtoLink uses two prompt families:

- **JSON prompt**: describes `final`, `tool_call`, and `agent_call` objects. It is the compatibility path for small and local models.
- **Native prompt**: tells the model to use the provider tool interface. It intentionally omits JSON action examples so native providers do not receive two conflicting tool protocols.

For streaming inference, prompt selection follows the adapter capability:

```python
action_mode = "native" if llm.supports_native_action_stream else "json"
```

Native tool calls are not ordinary text. A provider may stream text deltas, function-argument fragments, or SDK objects. `call_action_stream()` hides those shapes and returns one complete typed action to the shared loop.

### Agent delegation tools

Native providers receive synthetic delegation tools only when both conditions are true:

- the current runtime can dispatch agent calls; and
- discovered agent cards provide valid targets.

This avoids advertising a callable delegation interface that cannot succeed. JSON action mode can still produce an `agent_call`; if delegation is unavailable, the runtime injects corrective feedback instead of performing a side effect.

### Design rationale

The layered design keeps the runtime strict without making every provider use the same wire protocol:

- `LLM.infer()` dispatches one typed action at a time.
- Provider adapters own provider-specific request and stream parsing.
- Small and local models keep a compact JSON protocol by default.
- On the Agent-prepared path, native providers use their real tool API without receiving JSON tool instructions.
- Every path converges on `FinalAction`, `ToolCallAction`, and `AgentCallAction`.
- Policy, approval, cancellation, budgets, retries, events, and execution remain outside the model.

### Inference example

```python
from protolink import Agent, AgentCard, create_llm

agent = Agent(
    AgentCard(
        name="weather-assistant",
        description="Answers weather questions",
        url="runtime://weather-assistant",
    ),
    transport="runtime",
    llm=create_llm("openai", model="gpt-4o-mini"),
)

@agent.tool(name="weather", description="Return the weather for a location")
async def weather(location: str) -> str:
    return f"The weather in {location} is sunny."

answer = await agent.invoke("What's the weather in Tokyo?")
print(answer)
```

In JSON action mode, the intermediate model response must be exactly one supported object:

```json
{
  "type": "tool_call",
  "tool": "weather",
  "args": {"location": "Tokyo"}
}
```

After observing the tool result, the model completes with:

```json
{
  "type": "final",
  "content": "The weather in Tokyo is sunny."
}
```

### LLM.infer

<ApiReference
  kind="async method"
  path="protolink.llms.base.LLM.infer"
  signature={`async infer(
    *,
    query: str,
    tools: dict[str, BaseTool],
    agent_callback: Callable[[str, str, dict[str, Any]], Awaitable[Any]] | None = None,
    agent_cards: list[Any] | None = None,
    streaming: bool = False,
    event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    event_metrics: bool | None = None,
    action_authorizer: Callable[[RunAction], Awaitable[ActionAuthorization]] | None = None,
    cancellation_token: CancellationToken | None = None,
    run_context: RunContext | dict[str, Any] | None = None,
    budget_policy: BudgetPolicy | None = None,
    budget_enforcer: BudgetEnforcer | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L560"
>

Run the controlled multi-step inference loop used by `Agent`. The model declares typed intent; ProtoLink validates and executes tools or agent calls, feeds observations back to the model, and stops on a final action or safety limit.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM infer parameters">
    <ApiField name="query" type="str" required>
      User task added to the active conversation history.
    </ApiField>
    <ApiField name="tools" type="dict[str, BaseTool]" required>
      Executable tools available during this run.
    </ApiField>
    <ApiField name="agent_callback" type="Callable[[str, str, dict[str, Any]], Awaitable[Any]] | None" defaultValue="None">
      Async dispatcher for delegated <code>tool_call</code> and <code>infer</code> actions. Without it, attempted delegation is returned to the model as corrective feedback.
    </ApiField>
    <ApiField name="agent_cards" type="list[Any] | None" defaultValue="None">
      Discovered agents exposed to the model for delegation.
    </ApiField>
    <ApiField name="streaming" type="bool" defaultValue="False">
      Acquire each model action from the streaming adapter path.
    </ApiField>
    <ApiField name="event_callback" type="Callable[[dict[str, Any]], Awaitable[None]] | None" defaultValue="None">
      Async observer for normalized chunks, actions, tool events, delegation events, budget decisions, errors, and final output. The observer is non-authoritative; its first exception is logged and disables further callbacks for this infer call.
    </ApiField>
    <ApiField name="event_metrics" type="bool | None" defaultValue="None">
      Controls whether an attached event callback activates optional per-call metrics. Direct callers retain the existing default behavior; Agent sets this to <code>false</code> when its callback exists only to maintain internal completion receipts.
    </ApiField>
    <ApiField name="action_authorizer" type="Callable[[RunAction], Awaitable[ActionAuthorization]] | None" defaultValue="None">
      Policy boundary invoked after validation and before any tool or delegated-agent side effect.
    </ApiField>
    <ApiField name="cancellation_token" type="CancellationToken | None" defaultValue="None">
      Live token checked before provider calls and action dispatch.
    </ApiField>
    <ApiField name="run_context" type="RunContext | dict[str, Any] | None" defaultValue="None">
      Correlation, session, and budget context for the run.
    </ApiField>
    <ApiField name="budget_policy" type="BudgetPolicy | None" defaultValue="None">
      Allow, warn, or deny policy used by the built-in budget enforcer.
    </ApiField>
    <ApiField name="budget_enforcer" type="BudgetEnforcer | None" defaultValue="None">
      Existing stateful enforcer shared across several inference or tool operations. Omit it for an independent direct call; Agent supplies its task-local enforcer when the override accepts this keyword.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM infer return value">
    <ApiField name="part" type="Part">
      A part with type <code>infer_output</code> and the final user-facing content.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LLM infer errors">
    <ApiField name="RuntimeError">
      Raised after three consecutive parse failures, after ten steps without a final action, or when an unrecoverable provider, tool, or delegated-agent failure is wrapped by the loop.
    </ApiField>
    <ApiField name="BudgetExceededError">
      Raised when the configured run budget denies further work.
    </ApiField>
    <ApiField name="ApprovalRequiredError | ActionDeniedError">
      Raised when runtime authorization requires approval or denies an action.
    </ApiField>
    <ApiField name="asyncio.CancelledError">
      Raised when the run is cancelled.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Self-correction">
  Unknown tools, malformed actions, missing agents, and argument mismatches are normally reported back to the model for correction. They do not usually escape from <code>infer()</code> as <code>ValueError</code>.
</ApiCallout>

<ApiCallout label="Direct-call responsibility">
  <code>Agent</code> normally rebuilds the system prompt before calling this method. A custom runtime that invokes <code>infer()</code> directly must prepare matching tool and Agent descriptions with <code>build_system_prompt()</code>; supplying <code>tools</code> here only provides executables to the loop.
</ApiCallout>

<ApiCallout label="Override compatibility">
  The new <code>budget_enforcer</code> parameter is optional. When an Agent uses a custom <code>LLM.infer()</code> override with the pre-0.6.7 signature, it supplies the shared enforcer only if the override declares that keyword or accepts arbitrary keyword arguments.
</ApiCallout>

<ApiSection title="Examples">

```python
# Safe direct use when no tools or delegated Agents need to be advertised.
result = await llm.infer(
    query="Summarize the supplied context.",
    tools={},
)

print(result.content)
```

</ApiSection>

</ApiReference>

### LLM.sync.infer

<ApiReference
  kind="method"
  path="protolink.llms.base.SyncLLM.infer"
  signature={`llm.sync.infer(
    *,
    query: str,
    tools: dict[str, BaseTool],
    agent_callback: Callable | None = None,
    agent_cards: list[Any] | None = None,
    streaming: bool = False,
    event_callback: Callable | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L1704"
>

Blocking wrapper around `LLM.infer()` for scripts and synchronous command-line programs.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="synchronous infer parameters">
    <ApiField name="query" type="str" required>
      User task passed to the asynchronous inference loop.
    </ApiField>
    <ApiField name="tools" type="dict[str, BaseTool]" required>
      Tools available during inference.
    </ApiField>
    <ApiField name="agent_callback" type="Callable | None" defaultValue="None">
      Optional async agent dispatcher.
    </ApiField>
    <ApiField name="agent_cards" type="list[Any] | None" defaultValue="None">
      Discovered agents available for delegation.
    </ApiField>
    <ApiField name="streaming" type="bool" defaultValue="False">
      Use the underlying streaming action path.
    </ApiField>
    <ApiField name="event_callback" type="Callable | None" defaultValue="None">
      Optional async event observer.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="synchronous infer return value">
    <ApiField name="part" type="Part">
      Final <code>infer_output</code> part.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Event loops">
  This wrapper uses <code>asyncio.run()</code>. Do not call it from FastAPI handlers, asynchronous notebook cells, or any other active event loop; await <code>llm.infer()</code> there instead.
</ApiCallout>

</ApiReference>

### LLM.use_history

<ApiReference
  kind="context manager"
  path="protolink.llms.base.LLM.use_history"
  signature={`use_history(
    history: ConversationHistory,
) -> ContextManager[ConversationHistory]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L291"
>

Temporarily bind a conversation history to the current execution context. The binding uses `contextvars`, so concurrent asyncio tasks can share one LLM instance without sharing mutable messages.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM use history parameters">
    <ApiField name="history" type="ConversationHistory" required>
      History returned by <code>llm.history</code> inside the context.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Yields">
  <ApiFields ariaLabel="LLM use history yield value">
    <ApiField name="history" type="ConversationHistory">
      The same object supplied by the caller.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LLM use history errors">
    <ApiField name="TypeError">
      Raised when <code>history</code> is not a <code>ConversationHistory</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.history import ConversationHistory

customer_history = ConversationHistory("You support account customer-42.")

with llm.use_history(customer_history):
    response = llm.chat("What do you remember about this account?")
```

</ApiSection>

</ApiReference>

### LLM.compact_history {#llm-compact-history}

<ApiReference
  kind="method"
  path="protolink.llms.base.LLM.compact_history"
  signature={`compact_history(
    strategy: Literal["recent", "tokens", "summary"] = "recent",
    *,
    max_messages: int = 20,
    max_tokens: int = 4000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
) -> HistoryCompactionResult`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L370"
>

Compact the active history in place. `recent` and `tokens` are local operations; `summary` makes one isolated synchronous model call before replacing older messages.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM compact history parameters">
    <ApiField name="strategy" type={'"recent" | "tokens" | "summary"'} defaultValue={'"recent"'}>
      <code>recent</code> retains a message window, <code>tokens</code> retains the newest suffix near a soft estimated-token ceiling, and <code>summary</code> replaces older messages with model-generated durable context.
    </ApiField>
    <ApiField name="max_messages" type="int" defaultValue="20">
      Maximum retained messages for the <code>recent</code> strategy, including a leading system prompt.
    </ApiField>
    <ApiField name="max_tokens" type="int" defaultValue="4000">
      Soft estimated-token ceiling for the <code>tokens</code> strategy. Protected messages may exceed it.
    </ApiField>
    <ApiField name="preserve_recent" type="int" defaultValue="6">
      Newest non-system messages protected by <code>tokens</code> and <code>summary</code>.
    </ApiField>
    <ApiField name="summary_max_tokens" type="int" defaultValue="512">
      Requested maximum length of a generated summary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM compact history return value">
    <ApiField name="report" type="HistoryCompactionResult">
      Before/after message counts, estimated token counts, removed-message count, selected strategy, and whether a summary was created.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LLM compact history errors">
    <ApiField name="ValueError">
      Raised for an unknown strategy, invalid limits, or an empty summary result.
    </ApiField>
    <ApiField name="provider error">
      Errors from the isolated summary call propagate when <code>strategy="summary"</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Equivalent API">
  <code>llm.compactor.compact(...)</code> has the same signature and behavior.
</ApiCallout>

<ApiSection title="Examples">

```python
report = llm.compact_history("recent", max_messages=20)
report = llm.compact_history("tokens", max_tokens=8_000, preserve_recent=6)
report = llm.compact_history("summary", preserve_recent=8, summary_max_tokens=600)

print(report.to_dict())
```

</ApiSection>

</ApiReference>

### LLM.configure_metrics

<ApiReference
  kind="method"
  path="protolink.llms.base.LLM.configure_metrics"
  signature={`configure_metrics(
    profile: LLMModelProfile | dict[str, Any] | None = None,
    *,
    context_window: int | None = None,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
    currency: str = "USD",
    enabled: bool = True,
) -> LLM`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L313"
>

Attach application-owned model limits and prices used for observational inference metrics.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM configure metrics parameters">
    <ApiField name="profile" type="LLMModelProfile | dict[str, Any] | None" defaultValue="None">
      Complete profile object or equivalent mapping. When supplied, it takes precedence and the individual context/cost arguments are ignored.
    </ApiField>
    <ApiField name="context_window" type="int | None" defaultValue="None">
      Model context window used to calculate pressure and remaining-token estimates.
    </ApiField>
    <ApiField name="input_cost_per_million" type="float | None" defaultValue="None">
      Input-token price per one million tokens.
    </ApiField>
    <ApiField name="output_cost_per_million" type="float | None" defaultValue="None">
      Output-token price per one million tokens.
    </ApiField>
    <ApiField name="currency" type="str" defaultValue={'"USD"'}>
      Currency label attached to calculated costs.
    </ApiField>
    <ApiField name="enabled" type="bool" defaultValue="True">
      Whether inference may emit metrics events.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM configure metrics return value">
    <ApiField name="self" type="LLM">
      The same LLM instance for fluent configuration.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Observational only">
  Metrics do not change provider payloads, retry behavior, or responses. They are emitted by <code>infer()</code> when an event observer or telemetry backend is attached.
</ApiCallout>

</ApiReference>

## Prompt architecture

ProtoLink keeps its prompt families in `protolink/llms/prompts` and chooses between them according to the action-acquisition mode. The runtime deliberately avoids giving a model two tool-calling contracts at once.

### The system-prompt blueprint

`LLM.build_system_prompt()` assembles the prompt used by `infer()`. In JSON mode it describes the portable action objects. In native mode it tells the model to use the provider tool interface and leaves function-call syntax to the backend SDK or API.

By default, building a prompt resets history to the new system message. Passing `persist=True` updates the system message while retaining the rest of the current conversation, which is essential for long-lived sessions.

The final prompt is composed from:

1. **Base instructions**
    - Define the model's role inside a deterministic runtime.
    - Make it clear that the model requests actions rather than pretending to execute them.
    - Select `BASE_SYSTEM_PROMPT` for JSON mode or `NATIVE_SYSTEM_PROMPT` for native mode.

2. **Tool instructions**
    - JSON mode injects the available tool descriptions and the `tool_call` object format.
    - Native mode adds a short instruction to use the provider tool interface; concrete schemas travel in the provider request.

3. **Agent capabilities**
    - JSON mode describes the `agent_call` object and discovered targets.
    - Native mode exposes synthetic delegation functions only when dispatch is available and agent cards exist.

4. **Flow context**
    - Pipelines, routers, and graphs can inject topology-aware instructions for the current step.
    - The model receives only the semantic context it needs for the active flow position.

5. **Application instructions**
    - Your domain-specific prompt, such as “You are a coding assistant.”
    - Appended to the shared runtime rules unless `override_system_prompt=True`.

Tool and discovered-Agent metadata is serialized as deterministic valid JSON with stable ordering and explicit capabilities. The surrounding prompt labels those descriptions, schemas, and examples as untrusted data rather than executable instructions. This avoids Python-repr syntax and brace-escaping artifacts while keeping prompt caching and smaller-model parsing predictable.

### Reasoning versus execution

When `infer()` runs, the prompt makes the LLM a reasoning and action-selection engine while ProtoLink remains the executor:

1. **Input**: the model receives the task, history, tools, agents, and relevant flow context.
2. **Selection**: it chooses `final`, `tool_call`, or `agent_call`.
3. **Structured output**: it returns JSON or uses the provider-native tool channel.
4. **Validation**: ProtoLink converts the result into a typed action.
5. **Execution**: the runtime applies policy and performs the actual Python call or agent dispatch.
6. **Observation**: the result is returned to the model for its next decision.

```json
{
  "type": "tool_call",
  "tool": "get_weather",
  "args": {"location": "Geneva"}
}
```

This separation of reasoning from execution is what allows one inference loop to support hosted APIs, local servers, and in-process models without handing runtime authority to untrusted model output.

### LLM.build_system_prompt

<ApiReference
  kind="method"
  path="protolink.llms.base.LLM.build_system_prompt"
  signature={`build_system_prompt(
    user_instructions: str | None = None,
    agent_cards: str | None = None,
    tools: str | None = None,
    *,
    action_mode: Literal["json", "native"] | None = None,
    flow_instructions: str | None = None,
    override_system_prompt: bool = False,
    persist: bool = False,
    agent_name: str | None = None,
) -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L1530"
>

Build and store the complete runtime system prompt from base instructions, action mode, tools, discovered agents, flow context, and application instructions.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM build system prompt parameters">
    <ApiField name="user_instructions" type="str | None" defaultValue="None">
      Application instructions appended to the shared runtime prompt, or used as the complete prompt when <code>override_system_prompt=True</code>.
    </ApiField>
    <ApiField name="agent_cards" type="str | None" defaultValue="None">
      Serialized discovered-agent descriptions used for delegation guidance.
    </ApiField>
    <ApiField name="tools" type="str | None" defaultValue="None">
      Serialized tool descriptions used by the selected action prompt.
    </ApiField>
    <ApiField name="action_mode" type={'"json" | "native" | None'} defaultValue="None">
      Explicit action acquisition mode. When omitted, the adapter’s <code>uses_native_action_prompt</code> property selects the mode.
    </ApiField>
    <ApiField name="flow_instructions" type="str | None" defaultValue="None">
      Optional pipeline, router, or graph context.
    </ApiField>
    <ApiField name="override_system_prompt" type="bool" defaultValue="False">
      Replace the shared runtime template with <code>user_instructions</code>.
    </ApiField>
    <ApiField name="persist" type="bool" defaultValue="False">
      Preserve non-system history while updating the system message. The default clears history and resets it to the newly built system prompt.
    </ApiField>
    <ApiField name="agent_name" type="str | None" defaultValue="None">
      Current registered agent name used to prohibit self-delegation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM build system prompt return value">
    <ApiField name="prompt" type="str">
      The assembled prompt, also stored on <code>llm.system_prompt</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="History mutation">
  With <code>persist=False</code>, this method removes existing conversation turns. Use <code>persist=True</code> to retain them.
</ApiCallout>

</ApiReference>

### LLM.set_system_prompt

<ApiReference
  kind="method"
  path="protolink.llms.base.LLM.set_system_prompt"
  signature={`set_system_prompt(
    system_prompt: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L1649"
>

Assign a new value to `llm.system_prompt`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLM set system prompt parameters">
    <ApiField name="system_prompt" type="str" required>
      Replacement prompt string.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM set system prompt return value">
    <ApiField name="None" type="None">
      This method mutates the adapter.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Important">
  This setter does not rewrite the system message already stored in <code>llm.history</code>. Use <code>build_system_prompt(..., override_system_prompt=True)</code> when history and prompt state must be updated together.
</ApiCallout>

</ApiReference>

### LLM.validate_connection

<ApiReference
  kind="abstract method"
  path="protolink.llms.base.LLM.validate_connection"
  signature={`validate_connection() -> bool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/base.py#L1623"
>

Check whether the provider client, server, or local model can respond.

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLM validate connection return value">
    <ApiField name="connected" type="bool">
      <code>True</code> when adapter-specific validation succeeds; otherwise usually <code>False</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Construction">
  Current concrete adapters already call validation during initialization. Most implementations catch validation failures, log them, and return <code>False</code> rather than failing construction.
</ApiCallout>

</ApiReference>

## API providers

Hosted-provider adapters read credentials from their conventional environment variable when `api_key` is omitted. They all implement direct `call()`, `call_stream()`, and `validate_connection()` methods and inherit `chat()`, history management, compaction, metrics, and the controlled `infer()` loop.

OpenAI, Anthropic, and Gemini always acquire actions through their provider-native function interface. DeepSeek and Grok use native Chat Completions tools by default but can be forced into portable JSON mode. Hugging Face currently supports non-streaming text generation only, so it is best suited to direct `call()` or `chat(..., streaming=False)` usage.

- **OpenAI** - `OpenAILLM`, default model `gpt-4o-mini`, credential `OPENAI_API_KEY`.
- **Anthropic** - `AnthropicLLM`, default model `claude-sonnet-4-20250514`, credential `ANTHROPIC_API_KEY`.
- **Google Gemini** - `GeminiLLM`, default model `gemini-3-flash-preview`, credential `GEMINI_API_KEY`.
- **DeepSeek** - `DeepSeekLLM`, default model `deepseek-chat`, credential `DEEPSEEK_API_KEY`.
- **Grok** - `GrokLLM`, default model `grok-4-latest`, credential `XAI_API_KEY` or `GROK_API_KEY`.
- **Hugging Face** - `HuggingFaceLLM`, explicit model recommended, credential `HF_API_TOKEN`.

### OpenAILLM

<ApiReference
  kind="class"
  path="protolink.llms.api.OpenAILLM"
  signature={`class OpenAILLM(
    *,
    api_key: str | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    base_url: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/openai_client.py#L25"
>

OpenAI Responses API adapter with native function tools and native streamed tool-call events. Use it for the official OpenAI service or for a custom `base_url` that implements the Responses API, not merely Chat Completions.

Direct calls translate `ConversationHistory` into Responses input and extract text from the returned response. In inference mode, real function declarations are sent to the provider, parallel tool calls are disabled, and returned function calls are normalized into ProtoLink actions before the runtime executes them. Streaming follows the same contract while forwarding text deltas and buffering function arguments until they form one complete action.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="OpenAILLM parameters">
    <ApiField name="api_key" type="str | None" defaultValue="None">
      OpenAI API key. Falls back to <code>OPENAI_API_KEY</code>.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Model identifier. <code>None</code> resolves to <code>gpt-4o-mini</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=1.0</code>, <code>top_p=1.0</code>, <code>top_logprobs=None</code>, and <code>truncation="disabled"</code>.
    </ApiField>
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Optional OpenAI client base URL. The endpoint must implement the Responses API; use <code>OpenAICompatibleLLM</code> for Chat Completions-only servers.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="OpenAILLM errors">
    <ApiField name="ImportError">
      Raised when the OpenAI SDK is not installed.
    </ApiField>
    <ApiField name="OpenAI client error">
      Missing credentials and request errors originate from the SDK.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.api import OpenAILLM

llm = OpenAILLM(
    model="gpt-4o-mini",
    model_params={"temperature": 0.3, "max_output_tokens": 800},
)
```

</ApiSection>

</ApiReference>

### AnthropicLLM

<ApiReference
  kind="class"
  path="protolink.llms.api.AnthropicLLM"
  signature={`class AnthropicLLM(
    *,
    api_key: str | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    base_url: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/anthropic_client.py#L26"
>

Anthropic Messages API adapter with native `tool_use` actions and streamed tool-input deltas. The adapter derives both the separated system prompt and conversational messages from the supplied task-local `ConversationHistory`, converts ProtoLink tools to Anthropic tool schemas, and keeps the provider's tool-use identifier in action metadata.

After ProtoLink executes a requested tool, the adapter uses that identifier to inject the observation in the shape expected by the Messages API. Both streaming and non-streaming inference therefore share the same public `LLMActionResult` even though Anthropic's wire representation differs from OpenAI's. The runtime accepts one action per step and rejects multiple parallel `tool_use` blocks instead of silently selecting or merging them.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AnthropicLLM parameters">
    <ApiField name="api_key" type="str | None" defaultValue="None">
      Anthropic API key. Falls back to <code>ANTHROPIC_API_KEY</code>.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Claude model identifier. <code>None</code> resolves to <code>claude-sonnet-4-20250514</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=1.0</code>, <code>top_p=1.0</code>, and <code>max_tokens=1024</code>.
    </ApiField>
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Optional Anthropic-compatible API base URL passed to the SDK.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.api import AnthropicLLM

llm = AnthropicLLM(
    model="claude-sonnet-4-20250514",
    model_params={"max_tokens": 2048},
)
```

</ApiSection>

</ApiReference>

### GeminiLLM

<ApiReference
  kind="class"
  path="protolink.llms.api.GeminiLLM"
  signature={`class GeminiLLM(
    *,
    api_key: str | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    base_url: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/gemini_client.py#L24"
>

Google GenAI adapter with native function declarations and native streamed actions. It converts conversation messages and tool schemas into Google GenAI content, generation configuration, and function declarations.

Function-call parts are normalized into `ToolCallAction` or `AgentCallAction` before dispatch. Text-only responses become final actions, so application and Agent code sees the same result types used by every other provider.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="GeminiLLM parameters">
    <ApiField name="api_key" type="str | None" defaultValue="None">
      Google API key. Falls back to <code>GEMINI_API_KEY</code>.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Gemini model identifier. <code>None</code> resolves to <code>gemini-3-flash-preview</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Generation configuration merged over <code>temperature=1.0</code> and <code>top_p=1.0</code>.
    </ApiField>
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Stored by the shared API base class. The current Gemini client does not forward this value to <code>genai.Client</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.api import GeminiLLM

llm = GeminiLLM(model="gemini-3-flash-preview")
```

</ApiSection>

</ApiReference>

### DeepSeekLLM

<ApiReference
  kind="class"
  path="protolink.llms.api.DeepSeekLLM"
  signature={`class DeepSeekLLM(
    *,
    api_key: str | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    base_url: str | None = "https://api.deepseek.com",
    supports_tool_calling: bool = True,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/deepseek_client.py#L27"
>

DeepSeek Chat Completions adapter implemented through the OpenAI SDK with DeepSeek's API root. It supports ordinary text calls, incremental content streams, native Chat Completions tool calls, and streamed tool-argument deltas.

Native action acquisition is enabled by default. Set `supports_tool_calling=False` when the selected model behaves more reliably with ProtoLink's JSON action prompt; the surrounding inference loop, tool execution, and return types remain unchanged.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="DeepSeekLLM parameters">
    <ApiField name="api_key" type="str | None" defaultValue="None">
      DeepSeek API key. Falls back to <code>DEEPSEEK_API_KEY</code>.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Model identifier. <code>None</code> resolves to <code>deepseek-chat</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=1.0</code> and <code>top_p=1.0</code>.
    </ApiField>
    <ApiField name="base_url" type="str | None" defaultValue={'"https://api.deepseek.com"'}>
      DeepSeek-compatible API root.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="True">
      Use native Chat Completions tools. Set to <code>False</code> to force the portable JSON action fallback.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.api import DeepSeekLLM

llm = DeepSeekLLM(model="deepseek-chat")
```

</ApiSection>

</ApiReference>

### GrokLLM

<ApiReference
  kind="class"
  path="protolink.llms.api.GrokLLM"
  signature={`class GrokLLM(
    *,
    api_key: str | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    base_url: str | None = None,
    supports_tool_calling: bool = True,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/grok_client.py#L31"
>

xAI Chat Completions adapter using direct synchronous and asynchronous HTTP clients. It builds OpenAI-style message and tool payloads, parses content or tool calls, and normalizes usage metadata when the response includes it.

Native tools and streamed tool deltas are enabled by default. Disable `supports_tool_calling` to use the portable JSON action protocol with a model or endpoint that cannot reliably follow the native function format.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="GrokLLM parameters">
    <ApiField name="api_key" type="str | None" defaultValue="None">
      xAI key. Falls back to <code>XAI_API_KEY</code>, then <code>GROK_API_KEY</code>.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Model identifier. <code>None</code> resolves to <code>grok-4-latest</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=1.0</code>.
    </ApiField>
    <ApiField name="base_url" type="str | None" defaultValue="None">
      API root. <code>None</code> resolves to <code>https://api.x.ai/v1</code>.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="True">
      Use native tool calls and streamed tool deltas. Set to <code>False</code> for JSON action mode.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.api import GrokLLM

llm = GrokLLM(model="grok-4-latest")
```

</ApiSection>

</ApiReference>

### HuggingFaceLLM

<ApiReference
  kind="class"
  path="protolink.llms.api.HuggingFaceLLM"
  signature={`class HuggingFaceLLM(
    *,
    api_key: str | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/hugging_face_client.py#L16"
>

Hugging Face Inference API adapter for non-streaming direct calls. It is useful when a hosted Hub model is available through the inference service and you want that model behind the same `LLM` interface.

Pass an explicit Hub model identifier. The current adapter does not implement a usable text stream or provider-native actions, and only part of `model_params` is forwarded by `call()`, so choose another adapter when streaming or agent tool loops are required.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HuggingFaceLLM parameters">
    <ApiField name="api_key" type="str | None" defaultValue="None">
      Hugging Face token. Falls back to <code>HF_API_TOKEN</code>.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Hub model identifier. The effective built-in default is an empty string, so pass an explicit model for normal use.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>max_new_tokens=512</code>, <code>temperature=1.0</code>, <code>top_p=1.0</code>, and <code>repetition_penalty=1.0</code>. The current <code>call()</code> path forwards only <code>temperature</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Streaming limitation">
  <code>HuggingFaceLLM.call_stream()</code> is not implemented yet and currently yields one empty string. Do not use <code>chat(..., streaming=True)</code> or <code>infer(streaming=True)</code> with this adapter.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink.llms.api import HuggingFaceLLM

llm = HuggingFaceLLM(model="your-org/your-chat-model")
```

</ApiSection>

</ApiReference>

## Server providers

Server adapters connect to a model process over HTTP, whether that process runs on the same machine or on remote infrastructure. The server owns model loading and hardware resources; the ProtoLink adapter owns history serialization, request construction, streaming, action normalization, connection validation, and integration with the shared inference loop.

All server adapters inherit from `ServerLLM`. Their common configuration consists of a server URL, a model identifier understood by that server, optional generation parameters, and a `supports_tool_calling` capability flag. Native tool calling is opt-in because protocol compatibility alone does not guarantee that the selected model and chat template can use tools reliably.

The inherited `model_params` property can be replaced with a dictionary, `set_system_prompt()` updates the adapter's prompt value, and each concrete provider implements `call()`, `call_stream()`, and `validate_connection()` for its endpoint.

### OllamaLLM

<ApiReference
  kind="class"
  path="protolink.llms.server.OllamaLLM"
  signature={`class OllamaLLM(
    *,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    supports_tool_calling: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/server/ollama_client.py#L27"
>

Client for Ollama's `/api/chat` endpoint. It serializes `ConversationHistory` into Ollama messages and supports ordinary responses, streamed chunks, usage normalization, and optional native tool events.

JSON action mode is the default because local-model tool reliability depends on both the model and its template. Set `supports_tool_calling=True` only after verifying that the selected Ollama model produces correct native tool calls; direct `chat()` and `call()` usage does not require that flag.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="OllamaLLM parameters">
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Ollama server root. Falls back to <code>OLLAMA_URL</code>; if neither is supplied, construction raises <code>ValueError</code>.
    </ApiField>
    <ApiField name="headers" type="dict[str, str] | None" defaultValue="None">
      Accepted by the constructor, but the current request path does not forward custom headers.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Ollama model name. <code>None</code> resolves to <code>gemma4:e4b</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=1.0</code>, <code>num_predict=8192</code>, and <code>num_ctx=8192</code>.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="False">
      Opt into native Ollama tools. The default uses JSON action mode.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="OllamaLLM errors">
    <ApiField name="ValueError">
      Raised for a missing base URL, unsupported URL scheme, missing hostname, or unavailable client during a call.
    </ApiField>
    <ApiField name="RuntimeError">
      Raised for non-success Ollama responses or malformed response payloads.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.server import OllamaLLM

llm = OllamaLLM(
    base_url="http://localhost:11434",
    model="qwen3",
)
```

</ApiSection>

</ApiReference>

### LlamaCPPServerLLM

<ApiReference
  kind="class"
  path="protolink.llms.server.LlamaCPPServerLLM"
  signature={`class LlamaCPPServerLLM(
    *,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    supports_tool_calling: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/server/llamacpp_client.py#L27"
>

Direct client for a `llama-server` OpenAI-style Chat Completions endpoint. It talks to the server over HTTP without loading a model in the ProtoLink process, making it suitable when model lifecycle and hardware allocation belong to a separate service.

The adapter supports direct and streamed text calls. Native tool declarations are opt-in because correctness depends on the loaded model, chat template, and server build; JSON actions remain the compatibility default.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LlamaCPPServerLLM parameters">
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Server root. Resolution order is the argument, <code>LLAMACPP_SERVER_URL</code>, then <code>http://localhost:8080</code>.
    </ApiField>
    <ApiField name="headers" type="dict[str, str] | None" defaultValue="None">
      Extra HTTP headers. <code>Content-Type: application/json</code> is added when absent.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Server model identifier. <code>None</code> resolves to <code>gemma4:e4b</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=1.0</code>.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="False">
      Opt into native Chat Completions tools for a compatible model/template.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.server import LlamaCPPServerLLM

llm = LlamaCPPServerLLM(base_url="http://localhost:8080")
```

</ApiSection>

</ApiReference>

### OpenAICompatibleLLM

<ApiReference
  kind="class"
  path="protolink.llms.server.OpenAICompatibleLLM"
  signature={`class OpenAICompatibleLLM(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    headers: dict[str, str] | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    supports_tool_calling: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/server/openai_compatible_client.py#L29"
>

Generic client for servers exposing `/v1/chat/completions` and `/v1/models`, including LocalAI and compatible custom services. Use it when the endpoint follows the Chat Completions protocol but is not the official OpenAI Responses API. Prefer `VLLMLLM` or `LMStudioLLM` when their conventional URL, credential environment variables, and provider identity are useful.

It supports custom headers, optional bearer authentication, direct and streamed content, and opt-in native tools. The default JSON response format makes the adapter well suited to ProtoLink's portable action protocol, while `supports_tool_calling=True` switches action acquisition to provider-style tool payloads.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="OpenAICompatibleLLM parameters">
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Server root. Falls back to <code>OPENAI_COMPATIBLE_BASE_URL</code>, then <code>http://localhost:1234/v1</code>.
    </ApiField>
    <ApiField name="api_key" type="str | None" defaultValue="None">
      Optional bearer token. Falls back to <code>OPENAI_COMPATIBLE_API_KEY</code>.
    </ApiField>
    <ApiField name="headers" type="dict[str, str] | None" defaultValue="None">
      Extra request headers merged with the JSON defaults and authorization header.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Model id passed to the server. <code>None</code> resolves to <code>local-model</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=1.0</code>. Direct text calls also add <code>{'response_format={"type": "json_object"}'}</code> unless you override it.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="False">
      Enable native Chat Completions tool payloads for a compatible server/model pair.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.server import OpenAICompatibleLLM

llm = OpenAICompatibleLLM(
    base_url="http://localhost:8000/v1",
    model="Qwen/Qwen3-8B",
)
```

</ApiSection>

</ApiReference>

### VLLMLLM

<ApiReference
  kind="class"
  path="protolink.llms.server.VLLMLLM"
  signature={`class VLLMLLM(
    *,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    headers: dict[str, str] | None = None,
    model_params: dict[str, Any] | None = None,
    supports_tool_calling: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/server/vllm_client.py#L9"
>

Convenience specialization of `OpenAICompatibleLLM` for a separately managed vLLM server. It inherits the compatible adapter's direct and streamed Chat Completions requests, portable JSON action fallback, usage normalization, connection validation, custom headers, optional bearer authentication, and opt-in native tools. The adapter itself does not install or import the `vllm` Python package.

The model is required because it must match the identifier accepted by the running server: normally the model passed to `vllm serve`, or a name configured with vLLM's `--served-model-name` option. The subclass supplies vLLM's conventional port and provider-specific environment variables and reports `vllm` in events and metrics.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="VLLMLLM parameters">
    <ApiField name="model" type="str" required>
      Model identifier exposed by the vLLM server. It must match the served model name.
    </ApiField>
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Resolution order is the argument, <code>VLLM_URL</code>, then <code>http://localhost:8000/v1</code>.
    </ApiField>
    <ApiField name="api_key" type="str | None" defaultValue="None">
      Optional bearer token. Falls back to <code>VLLM_API_KEY</code>; no placeholder credential is added when both are absent.
    </ApiField>
    <ApiField name="headers" type="dict[str, str] | None" defaultValue="None">
      Extra request headers merged with the inherited JSON defaults and optional authorization header.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Generation parameters forwarded to vLLM and merged over <code>temperature=1.0</code>.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="False">
      Opt into native Chat Completions tools only after the vLLM server and selected model are configured for automatic tool choice.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Native tool setup">
  The default portable JSON action mode needs no vLLM tool parser. Before setting <code>supports_tool_calling=True</code>, start vLLM with <code>--enable-auto-tool-choice</code> and a model-appropriate <code>--tool-call-parser</code>, and ensure the selected model and chat template support tools.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink.llms.server import VLLMLLM

# Start the model server separately: vllm serve Qwen/Qwen3-8B
llm = VLLMLLM(model="Qwen/Qwen3-8B")
```

</ApiSection>

</ApiReference>

### LMStudioLLM

<ApiReference
  kind="class"
  path="protolink.llms.server.LMStudioLLM"
  signature={`class LMStudioLLM(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    headers: dict[str, str] | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    supports_tool_calling: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/server/openai_compatible_client.py#L377"
>

Convenience specialization of `OpenAICompatibleLLM` for LM Studio. It keeps the complete compatible-server behavior while supplying LM Studio's conventional URL, credential fallback, and provider identity.

Use the generic parent class when you want environment variables and labels that are not tied to LM Studio. Use this subclass when local development should work with LM Studio's normal defaults and appear as `lmstudio` in events and metrics.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LMStudioLLM parameters">
    <ApiField name="base_url" type="str | None" defaultValue="None">
      Resolution order is the argument, <code>LMSTUDIO_URL</code>, then <code>http://localhost:1234/v1</code>.
    </ApiField>
    <ApiField name="api_key" type="str | None" defaultValue="None">
      Optional token. Falls back to <code>LMSTUDIO_API_KEY</code>, then the local placeholder <code>lm-studio</code>.
    </ApiField>
    <ApiField name="headers" type="dict[str, str] | None" defaultValue="None">
      Extra request headers.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Model id selected in LM Studio. Inherited default: <code>local-model</code>.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Generation parameters forwarded to the compatible server.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="False">
      Opt into native tools when the selected model supports them.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.llms.server import LMStudioLLM

llm = LMStudioLLM(model="local-model")
```

</ApiSection>

</ApiReference>

## Local provider

Local adapters run inference inside the Python host rather than transmitting prompts to a server. This offers complete control over model files and data movement, but it also makes the application responsible for compatible native libraries, model loading, memory use, acceleration, and process stability.

### LlamaCPPLocalLLM

<ApiReference
  kind="class"
  path="protolink.llms.local.llamacpp_client.LlamaCPPLocalLLM"
  signature={`class LlamaCPPLocalLLM(
    *,
    model: str,
    model_params: dict[str, Any] | None = None,
    supports_tool_calling: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/local/llamacpp_client.py#L25"
>

In-process `llama-cpp-python` adapter for a local GGUF model file. Unlike `LlamaCPPServerLLM`, it loads the model in the current Python process, so model initialization time, native-library installation, memory use, and hardware configuration belong to the application.

The class implements complete and streamed chat-completion calls. Native tools are opt-in and depend on the loaded model and chat handler; JSON action mode is the safer default for portable inference.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LlamaCPPLocalLLM parameters">
    <ApiField name="model" type="str" required>
      Path to the local model file.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Values merged over <code>temperature=0.8</code> and <code>max_tokens=8192</code>.
    </ApiField>
    <ApiField name="supports_tool_calling" type="bool" defaultValue="False">
      Opt into native llama.cpp tools when the loaded model and chat handler support them.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LlamaCPPLocalLLM errors">
    <ApiField name="ImportError">
      Raised when <code>llama-cpp-python</code> is not installed.
    </ApiField>
    <ApiField name="FileNotFoundError">
      Raised when <code>model</code> does not exist.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Recommended construction">
  The local package currently has no convenience <code>__init__</code> export. Prefer <code>create_llm("llama.cpp-local", model="...")</code>, or import the class from the full path shown above.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import create_llm

llm = create_llm(
    "llama.cpp-local",
    model="/models/qwen3-8b.gguf",
)
```

</ApiSection>

</ApiReference>

## Testing provider

### MockLLM

<ApiReference
  kind="class"
  path="protolink.llms.MockLLM"
  signature={`class MockLLM(
    model: str = "mock-gpt",
    model_params: dict[str, Any] | None = None,
    *,
    mock_responses: dict[str, Any] | None = None,
    sequential_responses: list[Any] | None = None,
    response_callback: Callable[[ConversationHistory, str], Any] | None = None,
    default_response: str = "Unprocessed generic mock response",
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/mock_client.py#L9"
>

Dependency-free deterministic adapter for tests, examples, and offline runtime development. It implements the same `LLM` contract without network access, credentials, model files, or nondeterministic generation.

Responses are selected in a predictable priority order: a custom callback can inspect the full history, sequential responses can model multi-step action loops, keyword mappings can match prompts, and `default_response` handles everything else. This makes `MockLLM` suitable for testing Agent behavior, tool dispatch, parsing, history isolation, and failure paths rather than only simple chat.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MockLLM parameters">
    <ApiField name="model" type="str" defaultValue={'"mock-gpt"'}>
      Identifier reported by the mock adapter.
    </ApiField>
    <ApiField name="model_params" type="dict[str, Any] | None" defaultValue="None">
      Optional generation metadata retained on the instance.
    </ApiField>
    <ApiField name="mock_responses" type="dict[str, Any] | None" defaultValue="None">
      Keyword-based response mapping. Nested mappings can first match system-prompt text and then the latest user message.
    </ApiField>
    <ApiField name="sequential_responses" type="list[Any] | None" defaultValue="None">
      Responses consumed in order across calls.
    </ApiField>
    <ApiField name="response_callback" type="Callable[[ConversationHistory, str], Any] | None" defaultValue="None">
      Custom callback receiving the full history and system prompt.
    </ApiField>
    <ApiField name="default_response" type="str" defaultValue={'"Unprocessed generic mock response"'}>
      Fallback returned when no callback, sequential response, or mapping matches.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink import create_llm

llm = create_llm(
    "mock",
    sequential_responses=[
        {"type": "tool_call", "tool": "search", "args": {"query": "ProtoLink"}},
        {"type": "final", "content": "Done"},
    ],
)
```

</ApiSection>

</ApiReference>

## Related objects

### LLMModelProfile

<ApiReference
  kind="dataclass"
  path="protolink.LLMModelProfile"
  signature={`class LLMModelProfile(
    context_window: int | None = None,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
    currency: str = "USD",
    provider: str | None = None,
    model: str | None = None,
    supports_tools: bool | None = None,
    supports_streaming: bool | None = None,
    supports_json_schema: bool | None = None,
    tokenizer: str | None = None,
    metadata: dict[str, Any] = {},
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/metrics.py#L21"
>

Immutable application-owned metadata used to calculate context pressure and estimated cost. It describes a deployment rather than configuring the provider request: changing this profile cannot enable tools, streaming, JSON schema support, or a larger model context window.

ProtoLink does not maintain a provider pricing catalog because limits and prices change independently of the library. Supply values from the provider contract used by your application and update them on your own release schedule. The class does not range-check those supplied values.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLMModelProfile parameters">
    <ApiField name="context_window" type="int | None" defaultValue="None">
      Total model context window in tokens.
    </ApiField>
    <ApiField name="input_cost_per_million" type="float | None" defaultValue="None">
      Input price per one million tokens.
    </ApiField>
    <ApiField name="output_cost_per_million" type="float | None" defaultValue="None">
      Output price per one million tokens.
    </ApiField>
    <ApiField name="currency" type="str" defaultValue={'"USD"'}>
      Currency label for estimates.
    </ApiField>
    <ApiField name="provider" type="str | None" defaultValue="None">
      Optional provider label.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Optional model label.
    </ApiField>
    <ApiField name="supports_tools" type="bool | None" defaultValue="None">
      Descriptive tool support flag.
    </ApiField>
    <ApiField name="supports_streaming" type="bool | None" defaultValue="None">
      Descriptive streaming support flag.
    </ApiField>
    <ApiField name="supports_json_schema" type="bool | None" defaultValue="None">
      Descriptive JSON-schema support flag.
    </ApiField>
    <ApiField name="tokenizer" type="str | None" defaultValue="None">
      Optional tokenizer name used by application metadata.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Additional application-defined metadata.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## Usage examples

### Basic chat

```python
from protolink import create_llm

llm = create_llm("openai", model="gpt-4o-mini")

response = llm.chat("Hello, how are you?")
print(response)
```

Choose streaming as a separate interaction with a fresh or explicitly managed history:

```python
streaming_llm = create_llm("openai", model="gpt-4o-mini")

async for chunk in streaming_llm.chat(
    "Draft a short welcome message.",
    streaming=True,
):
    print(chunk, end="", flush=True)
```

`chat()` is deliberately small: it appends the user message and makes one provider call. It does not run tools, delegate to agents, apply the multi-step safety loop, or append the returned assistant text. Use `infer()` through an Agent when those runtime capabilities are needed.

### Advanced inference with tools

```python
import asyncio

from protolink import Agent, AgentCard, create_llm

async def main():
    agent = Agent(
        AgentCard(
            name="calculator",
            description="Performs checked calculations",
            url="runtime://calculator",
        ),
        transport="runtime",
        llm=create_llm("openai", model="gpt-4o-mini"),
    )

    @agent.tool(name="multiply", description="Multiply two numbers")
    async def multiply(left: float, right: float) -> float:
        return left * right

    answer = await agent.invoke("What is 15 multiplied by 8?")
    print(f"Final answer: {answer}")

asyncio.run(main())
```

The Agent prepares the tool prompt and executable mapping, history binding, discovered-Agent context, policy boundary, cancellation token, run context, and budget configuration before invoking the LLM loop.

### Updating parameters and prompts

```python
llm.model_params = {
    "temperature": 0.7,
    "max_output_tokens": 500,
}

llm.set_system_prompt("You are a helpful coding assistant.")
```

Generation-parameter names are provider-specific. The base class requires a dictionary but does not translate keys such as `max_tokens` and `max_output_tokens`; the selected SDK or server decides which values are valid.

`set_system_prompt()` changes the adapter attribute only. To rebuild the runtime prompt and update the system message in history, use `build_system_prompt()`. Pass `persist=True` when existing turns must be retained.

### Connection validation

```python
if llm.validate_connection():
    print("LLM is reachable.")
else:
    print("LLM validation failed.")
```

Concrete constructors currently perform their own validation during initialization. Calling the method explicitly is still useful for health checks and diagnostics after a server, credential, network, or model state may have changed.

## Error handling

LLM failures can originate at several different boundaries:

- **Authentication errors**: a provider rejects a missing, expired, or invalid credential.
- **Connection errors**: a server is unavailable, a URL is invalid, or the network call fails.
- **Model errors**: a model identifier is unknown, unavailable, or incompatible with the requested feature.
- **Parameter errors**: the downstream SDK or server rejects generation settings.
- **Action errors**: a model emits malformed or invalid structured intent.
- **Execution errors**: a selected tool, delegated agent, authorization policy, cancellation token, or run budget stops the loop.
- **Guardrail errors**: repeated parse failures or the ten-step safety limit produces `RuntimeError`.

Recoverable action mistakes are normally injected back into history so the model can self-correct. Application-level exception handling should focus on provider failures and runtime boundaries that cannot be repaired inside the loop.

A direct `call_action()` or `call_action_stream()` invocation raises `ValueError` when its one response cannot become a
valid action. `infer()` catches that validation failure, emits `llm_parse_error`, requests a correction, and raises
`RuntimeError` only when `max_parse_failures` consecutive proposals have failed. Inspect the final field-level
diagnostic before increasing the limit: repeated syntax drift may benefit from another attempt, while an unavailable
tool, ambiguous action, or application-schema mismatch needs a prompt, capability, or application-layer fix.

```python
import asyncio

from protolink import (
    ActionDeniedError,
    ApprovalRequiredError,
    BudgetExceededError,
    create_llm,
)

async def safe_inference():
    llm = create_llm("openai", model="gpt-4o-mini")

    try:
        result = await llm.infer(
            query="Summarize the available information.",
            tools={},
        )
        print(f"Success: {result.content}")
    except BudgetExceededError as exc:
        print(f"Budget stopped the run: {exc}")
    except (ApprovalRequiredError, ActionDeniedError) as exc:
        print(f"Policy stopped the action: {exc}")
    except asyncio.CancelledError:
        print("The run was cancelled.")
        raise
    except RuntimeError as exc:
        print(f"Inference failed: {exc}")
    except Exception as exc:
        print(f"Provider or configuration error: {exc}")

asyncio.run(safe_inference())
```

## Type aliases

The public type aliases describe provider-neutral model metadata:

```python
from typing import Literal, TypeAlias

LLMType: TypeAlias = Literal["api", "local", "server"]

LLMProvider: TypeAlias = Literal[
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "grok",
    "huggingface",
    "llama.cpp-local",
    "llama.cpp-server",
    "lmstudio",
    "mock",
    "ollama",
    "openai-compatible",
    "vllm",
]

ReasoningLevel: TypeAlias = Literal["none", "low", "medium", "high"]
```

The factory also defines an `LLMProvider` enum with the same provider values. For current factory behavior, pass the string value such as `"openai"` or `"ollama"`.

## Migration guide

When migrating code written against earlier ProtoLink model wrappers:

1. Replace `generate_response()` with `chat()`.
2. Replace `generate_stream_response()` with `chat(..., streaming=True)`.
3. Use `Agent.invoke()` for normal tool calling, delegation, policy, and multi-step execution.
4. Use `LLM.infer()` directly only when implementing the surrounding prompt and runtime preparation yourself.
5. Await Agent or inference calls; direct non-streaming `chat()` remains synchronous.
6. Expect a string from `chat()` and `Agent.invoke()`, or a `Part` with type `infer_output` from direct `infer()`.

```python
# Earlier style
# response = llm.generate_response(messages)
# print(response.content)

# Direct text generation
response = llm.chat("Hello, how are you?")
print(response)

# Controlled Agent inference
answer = await agent.invoke("What's the weather?")
print(answer)
```

## See also

- [LLM examples](llm_examples.md) for larger provider and tool-call examples.
- [Agents](agent.md) for how `Agent` binds state and invokes `LLM.infer()`.
- [State](state.md) for persistent conversation sessions.
- [Runtime](runtime.md) for cancellation, policy, approvals, budgets, and event recording.
