# LLM Examples

This guide provides detailed examples of how to integrate and use LLMs within the Protolink framework. It distinguishes between **Direct Usage** (for simple chat interactions) and the **Automated Pipeline** (for complex Agent interactions with tool calling).

## Supported Providers

Protolink supports several major LLM providers. You can initialize them by setting environment variables or passing API keys and configuration parameters directly.

Common parameters for all wrappers include:
- `api_key`: The API key for the provider (alternative to env variables).
- `model`: The specific model version to use (e.g., "gpt-4o", "claude-3-opus").
- `model_params`: A dictionary of model-specific parameters (e.g., temperature, max_tokens).
- `base_url`: Optional base URL if using a compatible API proxy.

!!! tip "Supported Classes"
    - `OpenAILLM`
    - `AnthropicLLM`
    - `GeminiLLM`
    - `DeepSeekLLM`

---

## Direct Usage

For simple text generation or chat interfaces where you don't need agents, identity, or complex tool orchestration, you can use the LLM classes directly.

!!! tip "Example here"
    [api_llms.ipynb](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/llm_test/api_llms.ipynb)

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
# Output: Response: {'text': 'The capital of Greece is Athens.'}
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

The automated pipeline uses the `Agent` class to coordinate identity, communication, and reasoning. This is where Protolink shines, enabling automated tool execution and multi-step reasoning.

!!! tip "Example here"
    [llm_infer_call.ipynb](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/llm_test/llm_infer_call.ipynb)

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

await agent.start()
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
# Stop the agent to modify it safeley (optional but good practice)
await agent.stop()

@agent.tool(
    name="weather_info", 
    description="Get weather information for a location", 
    input_schema={"location": "str"}
)
def get_weather(location: str) -> str:
    # Simulating an API call
    return f"The weather in {location} is sunny."

await agent.start()
```

### 5. Execution: With Tools (Success Case)

We send the **exact same task** again. This time, the automated pipeline kicks in:

1. The LLM sees the `weather_info` tool in its system prompt.
2. It generates a tool call for `get_weather(location="Geneva")`.
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
