# Telemetry

The Telemetry subsystem provides standard observable tracing to agent task execution, tool calling, and LLM inference. Protolink supports a non-invasive integration with external tracing services using Python's `contextvars`. This means it tracks nested traces, spans, and runs in the background without cluttering core execution method signatures.

Currently, Protolink offers native integrations for **[Langfuse](https://langfuse.com/)** and **[LangSmith](https://www.langchain.com/langsmith)**.

## Installation

Telemetry dependencies are handled as optional plugins. To use a telemetry integration, you must install its corresponding library:

```bash
# Install telemetry with langfuse and langsmith
uv add protolink[telemetry]

# Or install telemetry with just langfuse
uv add langfuse
# Or install telemetry with just langsmith
uv add langsmith
```

## Setup & Usage

To enable observability, instantiate your preferred telemetry tracker and inject it into your `Agent`. Tasks executed by this agent will now automatically trace their internal states and synchronize with your observability platform.

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
    card={"name": "ObserverAgent", "capabilities": {}},
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
    card={"name": "ObserverAgent", "capabilities": {}},
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
    card={"name": "ObserverAgent", "capabilities": {}},
    telemetry=multi_tracker
)
```

## Setting Telemetry Dynamically

You can also change or assign a telemetry tracker after agent initialization using the `.telemetry` property:

```python
agent = Agent(card={"name": "ObserverAgent", "capabilities": {}})

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
        
    async def on_llm_start(self, prompt: str, model: str | None = None) -> Any:
        pass
        
    async def on_llm_end(self, response: Part) -> Any:
        pass
        
    async def on_tool_start(self, tool_name: str, args: dict[str, Any]) -> Any:
        pass
        
    async def on_tool_end(self, tool_name: str, result: Any, error: str | None = None) -> Any:
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
    card={"name": "HelperAgent", "capabilities": {}},
    llm=llm,
    telemetry=telemetry
)
```
