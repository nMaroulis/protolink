# Telemetry

The Telemetry subsystem provides standard observable tracing to agent task execution, tool calling, and LLM inference. Protolink supports a non-invasive integration with external tracing services using Python's `contextvars`. This means it tracks nested traces, spans, and runs in the background without cluttering core execution method signatures.

Protolink includes a built-in local trace recorder and native integrations for **[Langfuse](https://langfuse.com/)** and **[LangSmith](https://www.langchain.com/langsmith)**.

## Installation

Telemetry dependencies are handled as optional plugins. To use a telemetry integration, you must install its corresponding library:

```bash
# Install telemetry with langfuse and langsmith
uv add protolink[telemetry]

# Or install telemetry with just langfuse
uv add langfuse
# Or install telemetry with just langsmith
uv add langsmith

# Optional: improve local token estimates for LLM metrics
uv add "protolink[metrics]"
```

## Setup & Usage

To enable observability, instantiate your preferred telemetry tracker and inject it into your `Agent`. Tasks executed by this agent will now automatically trace their internal states and synchronize with your observability platform.

### Local Trace Example

`LocalTraceTelemetry` records task traces in memory and can append replayable JSONL records to disk. It captures trace IDs, parent-child spans, model metadata, token estimates, raw inference-loop events, retry counts, and redacted payloads without requiring an external service.

```python
from protolink import Agent, AgentCard, LocalTraceTelemetry, Task

telemetry = LocalTraceTelemetry(path="traces.jsonl")

agent = Agent(
    card=AgentCard(
        name="local_observer",
        description="A locally traced agent",
        url="runtime://local-observer",
    ),
    telemetry=telemetry,
)

@agent.tool(name="add", description="Add two integers")
async def add(a: int, b: int) -> int:
    return a + b

result = await agent.handle_task(Task.create_tool_call(tool_name="add", args={"a": 2, "b": 3}))
records = telemetry.recorder.replay()
```

### LLM Metrics and Context Usage

When an agent has both an LLM and telemetry, Protolink records live budget metrics for every model call inside `LLM.infer()`. This includes latency, token usage, context-window pressure, and estimated cost. Provider-reported usage is used when available; otherwise Protolink estimates usage without requiring extra dependencies.

```python
from protolink import Agent, AgentCard, LLMModelProfile, LocalTraceTelemetry, Task, create_llm

telemetry = LocalTraceTelemetry(path="traces.jsonl")
llm = create_llm(
    "openai-compatible",
    model="my-model",
    metrics_profile=LLMModelProfile(
        context_window=128_000,
        input_cost_per_million=1.0,   # example value; use your provider's current pricing
        output_cost_per_million=5.0,  # example value; use your provider's current pricing
    ),
)

agent = Agent(
    card=AgentCard(name="budgeted", description="Observed LLM agent", url="runtime://budgeted"),
    llm=llm,
    telemetry=telemetry,
)

result = await agent.handle_task(Task.create_infer(prompt="Plan the next release"))
trace = telemetry.recorder.replay()[-1]
llm_span = next(span for span in trace["spans"] if span["kind"] == "llm")
print(llm_span["metadata"]["llm_metrics"])
```

The same data is emitted live as `llm_context` and `llm_call_metrics` events through `event_callback`, so terminal apps can render a status line such as context used, call latency, and session cost while the agent is still running.

For application-facing stream snapshots, use `RunEvent` and `InMemoryEventSink` from the [Runtime](runtime.md) layer. Telemetry keeps detailed traces and spans; run events provide the stable progress envelope for UIs, CLIs, and golden tests.

!!! note "Cost estimates"
    Protolink does not ship a fixed provider pricing catalog. Prices and context windows are application-owned metadata passed through `LLMModelProfile`, which keeps the core package stable and avoids stale billing assumptions.

### Langfuse Example

The `LangfuseTelemetry` tracks tasks as traces, and LLM/Tool executions as spans/generations.

```python
import os
from protolink.telemetry import LangfuseTelemetry
from protolink.agents.base import Agent

# Ensure environment variables are set:
# os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-..."
# os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-..."
# os.environ["LANGFUSE_HOST"] = "https://cloud.langfuse.com"

# Initialize tracking
telemetry_tracker = LangfuseTelemetry()

# Inject into an agent
agent = Agent(
    card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"},
    telemetry=telemetry_tracker
)
```

### LangSmith Example

The `LangSmithTelemetry` uses the `RunTree` API to track tasks hierarchically.

```python
import os
from protolink.telemetry import LangSmithTelemetry
from protolink.agents.base import Agent

# Ensure environment variables are set:
# os.environ["LANGCHAIN_API_KEY"] = "lsv2_pt_..."
# os.environ["LANGCHAIN_PROJECT"] = "my-protolink-project"

# Initialize tracking
telemetry_tracker = LangSmithTelemetry()

# Inject into an agent
agent = Agent(
    card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"},
    telemetry=telemetry_tracker
)
```

## Multiplexing Telemetry

If you want to broadcast telemetry events to multiple trackers simultaneously, you can use the `MultiTelemetry` class:

```python
from protolink.telemetry import LangfuseTelemetry, LangSmithTelemetry, MultiTelemetry
from protolink.agents.base import Agent

# Initialize tracking
langfuse_tracker = LangfuseTelemetry()
langsmith_tracker = LangSmithTelemetry()
multi_tracker = MultiTelemetry([langfuse_tracker, langsmith_tracker])

# Inject into an agent
agent = Agent(
    card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"},
    telemetry=multi_tracker
)
```

## Setting Telemetry Dynamically

You can also change or assign a telemetry tracker after agent initialization using the `.telemetry` property:

```python
agent = Agent(card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"})

# Later in your code...
agent.telemetry = LangfuseTelemetry()
```

## Creating Custom Telemetry Implementations

If you wish to integrate with a different observability platform (e.g., Datadog, Prometheus, Arize Phoenix), you can subclass the `Telemetry` base class and implement the required asynchronous hooks:

```python
from typing import Any
from protolink.models import Task, Part
from protolink.telemetry.base import Telemetry

class MyCustomTelemetry(Telemetry):
    async def on_task_start(self, task: Task, agent_name: str) -> Any:
        pass
        
    async def on_task_end(self, task: Task, result: Task, agent_name: str) -> Any:
        pass
        
    async def on_llm_start(
        self,
        prompt: str,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        pass
        
    async def on_llm_end(self, response: Part) -> Any:
        pass
        
    async def on_tool_start(self, tool_name: str, args: dict[str, Any]) -> Any:
        pass
        
    async def on_tool_end(self, tool_name: str, result: Any, error: str | None = None) -> Any:
        pass

    async def on_llm_event(self, event: dict[str, Any]) -> Any:
        pass
```

## Example Code

Here is a complete, simple example demonstrating telemetry tracking with an `Agent` using Langfuse:

```python
from protolink.agents.base import Agent
from protolink.telemetry import LangfuseTelemetry
from protolink.llms.api.openai_client import OpenAILLM

# Setup LLM (requires openai)
llm = OpenAILLM()

# Setup Telemetry (requires langfuse)
telemetry = LangfuseTelemetry()

# Initialize Agent
agent = Agent(
    card={"name": "HelperAgent", "description": "Observed helper", "url": "runtime://helper"},
    llm=llm,
    telemetry=telemetry
)
```
