import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Getting Started

This guide shows how to install and start using Protolink.

The following article on 📝 [level-up coding on medium](https://levelup.gitconnected.com/your-first-autonomous-agent-mesh-easier-than-you-think-ce697b3dd87a) also gives a hands-on guide and overview of Protolink.

## Installation

Protolink is published on PyPI and can be installed with either `uv` (recommended) or `pip`.

### Basic Installation

This installs the base package without optional extras:

```bash
# Using uv (recommended)
uv add protolink

# Using pip
pip install protolink
```

### Optional Dependencies

Protolink exposes several extras to enable additional functionality:


<Tabs groupId="doc-tabs-1">
<TabItem value="uv" label="uv" default>

```bash
# Install with all optional dependencies
uv add "protolink[all]"

# HTTP support (for web-based agents)
uv add "protolink[http]"

# All supported LLM libraries
uv add "protolink[llms]"

# Development (all extras + testing tools)
uv add "protolink[dev]"
```

</TabItem>
<TabItem value="pip" label="pip">

```bash
# Install with all optional dependencies
pip install "protolink[all]"

# HTTP support (for web-based agents)
pip install "protolink[http]"

# All supported LLM libraries
pip install "protolink[llms]"

# Development (all extras + testing tools)
pip install "protolink[dev]"
```

</TabItem>
<TabItem value="source-checkout" label="Source checkout">

```bash
git clone https://github.com/nmaroulis/protolink.git
cd protolink

# Editable install for local development
uv pip install -e ".[dev]"
```

</TabItem>
</Tabs>
:::info[Optional extras]

You usually only need the extras that match your use case. `protolink[llms]` installs every supported LLM SDK, so production projects may prefer installing only the provider libraries they actually use.

:::
For development from source:

```bash
git clone https://github.com/nmaroulis/protolink.git
cd protolink
uv pip install -e ".[dev]"
```

:::info[A2A from the first agent]

Even the smallest ProtoLink agent uses the A2A model: `AgentCard` declares identity and capabilities, while `Task`, `Message`, `Part`, and `Artifact` carry work and results. `transport="http"` serves ProtoLink's native API by default. Add `a2a=True` when the agent should also expose and consume the [A2A 1.0](https://a2a-protocol.org/latest/specification/) JSON-RPC boundary. This is additive: native endpoints and native peer calls remain available. See [A2A Core and 1.0 Compatibility](a2a.md) for the exact scope.

:::

## First Agent

Below is a compact example that wires together an agent, HTTP transport, an OpenAI-compatible LLM wrapper, and built-in, native, and MCP tools:

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.tools import current_datetime, web_search
from protolink.tools.adapters import MCPToolAdapter
from protolink.llms.api import OpenAILLM
from protolink.discovery import Registry

# Initialize Registry for A2A Discovery
registry = Registry(url="http://127.0.0.1:9000", transport="http")
registry.start(background=True)

# Define the agent card
agent_card = AgentCard(
    name="example_agent",
    description="A dummy agent",
    url="http://127.0.0.1:8020",
)

# OpenAI API LLM. If model is omitted, OpenAILLM uses its built-in default.
llm = OpenAILLM(model="gpt-4o-mini")

# Initialize the agent
agent = Agent(agent_card, transport="http", a2a=True, llm=llm, registry=registry)

# Add opt-in built-in tools
agent.add_tool(current_datetime())
agent.add_tool(web_search())

# Add Native tool
@agent.tool(name="add", description="Add two numbers")
async def add_numbers(a: int, b: int):
    return a + b

# Add MCP tools and return them as Protolink native tools
mcp_adapter = MCPToolAdapter(transport="sse", url="https://api.example.com/mcp/sse")
mcp_tools = mcp_adapter.get_tools()
for mcp_tool in mcp_tools:
    agent.add_tool(mcp_tool)

# Start the agent
agent.start()
```

This example demonstrates the core pieces of Protolink:

- **AgentCard** to describe the agent.
- **Transport** (here the `"http"` shortcut) for native agent communication, with `a2a=True` adding the A2A 1.0 inbound and outbound adapters.
- **LLM** backend (`OpenAILLM`).
- **Built-in tools** registered explicitly as ordinary `Tool` instances.
- **Native tools** (Python functions decorated with `@agent.tool`).
- **MCP tools** registered via `MCPToolAdapter`.

The built-ins require no additional package extra. `web_search()` defaults to Brave and reads `BRAVE_SEARCH_API_KEY` only when invoked. Pass `engine="wikipedia"` for documented, keyless English Wikipedia search or `engine="duckduckgo"` for keyless, best-effort DuckDuckGo HTML search. It declares `network.read`, and registering it does not perform a network request. Built-ins are opt-in, and the default capability policy is allow-by-default, so configure a restrictive `CapabilityPolicy` when network access should be denied or approval-gated. See [Tools](tool.md#built-in-tools) for the complete API and safety behavior.


### Using the CLI

Create a runnable one-file starter agent:

```bash
protolink init agent
uv run python agent.py
```

The default starter uses the top-level API:

```python
from protolink import Agent, AgentCard, LocalTraceTelemetry, Task, create_llm
```

It runs locally without an API key by executing a tool call directly. If `OPENAI_API_KEY` is set, it also enables LLM inference. Use `--template tool` for a tool-only starter or `--force` to overwrite an existing file.
