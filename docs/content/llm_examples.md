# LLM Examples

This guide provides detailed examples of how to integrate and use LLMs within the Protolink framework. It distinguishes between **Direct Usage** (for simple chat interactions) and the **Automated Pipeline** (for complex Agent interactions with tool calling).

## Supported Providers

Protolink supports several major LLM providers. You can initialize them by setting environment variables or passing API keys and configuration parameters directly.

Common parameters for all wrappers include:
- `api_key`: The API key for the provider (alternative to env variables).
- `model`: The specific model version to use (e.g., "gpt-4o", "claude-3-opus").
- `model_params`: A dictionary of model-specific parameters (e.g., temperature, max_tokens).
- `base_url`: Optional base URL if using a compatible API proxy.

:::tip[Supported Classes]

- `OpenAILLM`
- `AnthropicLLM`
- `GeminiLLM`
- `DeepSeekLLM`
- `GrokLLM`
- `HuggingFaceLLM`
- `OllamaLLM`
- `LlamaCPPServerLLM`
- `LlamaCPPLocalLLM`
- `LMStudioLLM`
- `VLLMLLM`
- `OpenAICompatibleLLM`

:::
---

## Direct Usage

For simple text generation or chat interfaces where you don't need agents, identity, or complex tool orchestration, you can use the LLM classes directly.

:::tip[Example here]

[api_llms.ipynb](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/llm_test/api_llms.ipynb)

:::
### Basic Chat

```python
from protolink.llms.api import OpenAILLM

# Initialize the LLM
llm = OpenAILLM(model="gpt-4o")

# Send a query
query = "What's the capital of Greece?"
print("Testing non-streaming response:")
response = llm.chat(query)
print(f"Response: {response}")
# Output: Response: The capital of Greece is Athens.
```

### Streaming Responses

To receive tokens in real-time as they are generated, set `streaming=True`.

```python
import asyncio

async def test_streaming():
    print("\nTesting streaming response:")
    query = "Explain quantum computing in one sentence."
    async for chunk in llm.chat(query, streaming=True):
        print(chunk, end="", flush=True)
    print("\n")

await test_streaming()
```

---

## Automated Pipeline (Agent Integration)

The automated pipeline uses the `Agent` class to coordinate identity, communication, and reasoning. This is where Protolink shines, enabling automated tool execution and multi-step reasoning through the **inference loop**.

### The Inference Loop

When an agent receives an `infer` task, it delegates to `LLM.infer()` which implements a **ReAct-style** (Reasoning + Acting) loop:

1. **Query Injection**: User query added to conversation history
2. **LLM Invocation**: LLM generates a typed action through provider-native tools or the portable JSON action protocol
3. **Action Dispatch**: Runtime executes the declared action
4. **Result Injection**: Results fed back to LLM
5. **Iteration**: Loop continues until `final` response

The LLM can produce three action types:

| Action | Description |
|--------|-------------|
| `final` | Produce final user-facing response |
| `tool_call` | Execute a local tool owned by this agent |
| `agent_call` | Delegate to another agent |

---

## Example 1: Tool Calling (Single Agent)

:::tip[Full Notebook]

[llm_infer_tool_call.ipynb](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/llm_test/llm_infer_tool_call.ipynb)

:::
This example demonstrates **tool_call** - the ability for an LLM to request execution of a local tool.

### Execution Flow

In this example we:

1. **Create and start an Agent with an LLM** - Choose any LLM provider Protolink supports (OpenAI, Anthropic, Ollama, etc.). The agent is started at `AGENT_URL` with an `http` **transport**. You can check its status at `AGENT_URL/status` in your browser.

2. **Create a Task with an `infer` Part** - The `infer` part tells the agent to use its LLM to process the request. This triggers Protolink's inference loop.

3. **Ask a question requiring real-time data (without tools)** - The LLM cannot answer because it has no access to external data sources. It will politely decline.

4. **Add a tool to the Agent** - We register a `weather_info` tool. Protolink automatically injects this tool's schema into the LLM's system prompt.

5. **Ask the same question again (with tools)** - Now the LLM sees it has a tool available. It produces a `tool_call` action, Protolink executes it, and the result is fed back to the LLM to formulate the final response.

### 1. Setup the Agent

```python
from protolink.agents import Agent
from protolink.llms.api import OpenAILLM

AGENT_URL = "http://localhost:8050"
llm = OpenAILLM(api_key="...", model="gpt-4o")

# Create the agent with a system prompt
agent = Agent(
    card={
        "name": "Reasoning Agent",
        "description": "An agent capable of tool use",
        "url": AGENT_URL,
    },
    transport="http",
    llm=llm,
    system_prompt="You are a helpful assistant.",
)

agent.start(background=True)
```

### 2. The Task

We create a `Task` that instructs the agent to infer an answer.

```python
from protolink.models import Message, Part, Task
from protolink.client import AgentClient

# Define the user's question
task = Task(
    messages=[
        Message(
            role="user", 
            parts=[Part.infer(prompt="What's the weather right now in Geneva?")]
        )
    ]
)

# Or use the convenience method
task = Task.create_infer(prompt="What's the weather right now in Geneva?")

client = AgentClient(transport=agent.transport)
```

### 3. Execution: Without Tools (Failure Case)

First, we send the task **without** giving the agent any weather tools. The LLM, knowing it cannot access the internet effectively, should decline or hallucinate plausibly (but usually declines for real-time data).

```python
result = await client.send_task(agent_url=AGENT_URL, task=task)
print(f"Response:\n{result.get_last_part_content()}")

# Expected Output:
# "I cannot provide real-time weather information as I don't have access to live data or tools."
```

### 4. Adding the Tool

Now, we dynamically register a tool with the agent. Protolink automatically exposes this to the LLM.

```python
# Stop the agent to modify it safely (optional but good practice)
agent.stop()

@agent.tool(
    name="weather_info", 
    description="Get weather information for a location", 
    input_schema={"location": str}
)
def get_weather(location: str) -> str:
    # Simulating an API call
    return f"The weather in {location} is sunny."

agent.start(background=True)
```

### 5. Execution: With Tools (Success Case)

We send the **exact same task** again. This time, the automated pipeline kicks in:

1. The LLM sees the `weather_info` tool in its system prompt.
2. It generates a `tool_call` action:
   ```json
   {"type": "tool_call", "tool": "weather_info", "args": {"location": "Geneva"}}
   ```
3. The Agent executes the function.
4. The result (`...sunny`) is fed back to the LLM.
5. The LLM generates the final natural language response.

```python
# Ask the question again
result = await client.send_task(agent_url=AGENT_URL, task=task)
print(result.get_last_part_content())

# Expected Output:
# "The weather in Geneva is currently sunny."
```

---

## Example 2: Agent Delegation (Multi-Agent)

:::tip[Full Notebook]

[llm_infer_agent_call.ipynb](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/llm_test/llm_infer_agent_call.ipynb)

:::
This example demonstrates **agent_call** - the ability for an LLM to delegate work to other agents. This enables building **multi-agent systems** where specialized agents handle specific domains.

### Execution Flow

In this example we:

1. **Start a Registry** - The registry enables agent discovery. Agents register themselves and can discover other agents in the network.

2. **Create a Weather Agent (specialist)** - This agent owns the `get_weather` tool but has **no LLM**. It's a pure tool executor that responds to tool_call requests.

3. **Create a Coordinator Agent (with LLM)** - This agent has an LLM and knows about other agents via the Registry. It cannot answer weather questions directly but can delegate.

4. **Verify agent discovery** - The Coordinator discovers the Weather Agent and sees its available tools.

5. **Send a weather query to the Coordinator** - The LLM recognizes it needs weather data, produces an `agent_call` to delegate to the Weather Agent, receives the result, and formulates the final response.

The key difference from Example 1: The tool lives on a **different agent**, requiring cross-agent communication via the transport layer.

### Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                     Registry                        │
│  (Agent Discovery - knows about all agents)         │
└─────────────────────────────────────────────────────┘
              ↑                       ↑
         registers              registers
              ↑                       ↑
┌─────────────────────┐   ┌─────────────────────────┐
│  Coordinator Agent  │──▶│     Weather Agent       │
│  (Has LLM)          │   │  (Has get_weather tool) │
│                     │   │                         │
│  Delegates weather  │   │  Executes tool calls    │
│  queries via        │   │  Returns weather data   │
│  agent_call         │   │                         │
└─────────────────────┘   └─────────────────────────┘
```

### Agent Call Actions

When producing an `agent_call`, the LLM specifies:

- `agent`: Name of the target agent
- `action`: Either `tool_call` (execute a tool) or `infer` (ask for LLM response)
- Action-specific fields (`tool`, `args` for tool_call; `prompt` for infer)

### 1. Setup Registry and Agents

```python
from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.llms.server import OllamaLLM

# URLs for our agents
REGISTRY_URL = "http://localhost:8000"
WEATHER_AGENT_URL = "http://localhost:8001"
COORDINATOR_URL = "http://localhost:8002"

# Start the registry for agent discovery
registry = Registry(url=REGISTRY_URL, transport="http")
registry.start(background=True)
```

### 2. Create the Weather Agent (Specialist)

This agent owns the `get_weather` tool but has no LLM - it just executes tools.

```python
weather_agent = Agent(
    card={
        "name": "weather_agent",
        "description": "Provides weather information for any location",
        "url": WEATHER_AGENT_URL,
    },
    transport="http",
    registry=registry,
)

@weather_agent.tool(
    name="get_weather", 
    description="Get current weather for a location", 
    input_schema={"location": str}
)
def get_weather(location: str) -> str:
    """Simulated weather lookup."""
    weather_data = {
        "athens": "Sunny, 28°C",
        "london": "Cloudy, 15°C",
        "tokyo": "Rainy, 22°C",
        "new york": "Partly cloudy, 20°C",
    }
    return weather_data.get(location.lower(), f"Weather data not available for {location}")

weather_agent.start(background=True)
print(f"Weather Agent running at {WEATHER_AGENT_URL}")
```

### 3. Create the Coordinator Agent (Has LLM)

This agent has an LLM and knows about the Weather Agent via the Registry.

```python
llm = OllamaLLM(base_url="http://localhost:11434", model="gemma4:e4b")

COORDINATOR_SYSTEM_PROMPT = """You are a coordinator agent. When users ask about weather, 
delegate to the weather_agent using agent_call with action 'tool_call'. 
Use the weather_agent's get_weather tool."""

coordinator = Agent(
    card={
        "name": "coordinator",
        "description": "Coordinates tasks and delegates to specialized agents",
        "url": COORDINATOR_URL,
    },
    transport="http",
    registry=registry,
    llm=llm,
    system_prompt=COORDINATOR_SYSTEM_PROMPT,
)

coordinator.start(background=True)
```

### 4. Verify Agent Discovery

The Coordinator should discover the Weather Agent:

```python
discovered = await coordinator.discover_agents()
print(f"Discovered {len(discovered)} agents:")
for agent in discovered:
    print(f"  - {agent.name}: {agent.description}")
    if agent.skills:
        print(f"    Tools: {[s.id for s in agent.skills]}")

# Output:
# Discovered 2 agents:
#   - weather_agent: Provides weather information for any location
#     Tools: ['get_weather']
#   - coordinator: Coordinates tasks and delegates to specialized agents
```

### 5. Send Task Requiring Agent Delegation

```python
from protolink.client import AgentClient
from protolink.models import Task

client = AgentClient(transport=coordinator.transport)
task = Task.create_infer(prompt="What's the weather like in Athens right now?")

print("Sending task to Coordinator...")
result = await client.send_task(agent_url=COORDINATOR_URL, task=task)
print(f"\nResult: {result.get_last_part_content()}")

# Expected Output:
# "The weather in Athens is currently Sunny, 28°C."
```

### What Happened Under the Hood

1. The Coordinator's LLM received the query
2. It recognized this requires the Weather Agent and produced:
   ```json
   {
     "type": "agent_call",
     "action": "tool_call",
     "agent": "weather_agent",
     "tool": "get_weather",
     "args": {"location": "Athens"}
   }
   ```
3. Protolink's `_handle_agent_call` resolved `weather_agent` to its URL via the Registry
4. A Task was sent to the Weather Agent via `call_agent()`
5. The Weather Agent executed `get_weather("Athens")`
6. The result was returned to the Coordinator's LLM loop via `_inject_agent_call`
7. The LLM produced a final response incorporating the weather data

### Agent Call vs Tool Call

| Aspect | `tool_call` | `agent_call` |
|--------|-------------|--------------|
| **Scope** | Local tool on same agent | Tool/inference on remote agent |
| **Discovery** | Tools registered locally | Agents discovered via Registry |
| **Use Case** | Single-agent with tools | Multi-agent coordination |
| **Execution** | Direct function call | Transport-based RPC |

---

## Safety Guardrails in Action

The inference loop includes safety mechanisms that protect against common failure modes:

### Deduplication Detection

If the LLM tries to make the same `agent_call` or `tool_call` twice:

```
# LLM output: agent_call to weather_agent with same args
# Runtime injects:
"You have already performed this action: agent_call. The result is in your context.
Please proceed with your task - either produce a 'final' response or take a different action."
```

### Self-Correcting Errors

If the LLM references an unknown agent:

```
# LLM output: agent_call to "unknown_agent"
# Runtime injects:
"Agent call failed: Agent 'unknown_agent' not found in registry. 
Available agents: ['weather_agent', 'coordinator']"
```

### Parse Failures

If the LLM produces invalid JSON:

```
# Runtime injects:
"Your previous response could not be parsed as valid JSON. Error: Expecting property name
Please respond with a valid JSON object containing 'type' and required fields."
```

These guardrails enable the LLM to self-correct without consuming the entire step budget.
