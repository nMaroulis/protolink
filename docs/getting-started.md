# Getting Started

This guide shows how to install and start using Protolink.

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


=== "uv"

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

=== "pip"

    ```bash
    # Install with all optional dependencies
    pip install -e "protolink[all]"

    # HTTP support (for web-based agents)
    pip install -e "protolink[http]"

    # All supported LLM libraries
    pip install -e "protolink[llms]"

    # Development (all extras + testing tools)
    pip install -e "protolink[dev]"
    ```

=== "uv & pip"
    *Because.. why not?*
    
    ```bash
    # Install with all optional dependencies
    uv pip install -e "protolink[all]"

    # HTTP support (for web-based agents)
    uv pip install -e "protolink[http]"

    # All supported LLM libraries
    uv pip install -e "protolink[llms]"

    # Development (all extras + testing tools)
    uv pip install -e "protolink[dev]"
    ```

!!! info "Optional extras"
    You usually only need the extras that match your use case. The `protolink[llms]` will install all the supported LLM libraries (OpenAI, Anthropic, Ollama etc.) so it is **advised to install manually the libraries that are needed for your project**.

For development from source:

```bash
git clone https://github.com/nmaroulis/protolink.git
cd protolink
uv pip install -e ".[dev]"
```

## Basic Example

Below is a minimal example that wires together an agent, HTTP transport, an OpenAI LLM, and both native and MCP tools:

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.transport import HTTPTransport
from protolink.tools.adapters import MCPToolAdapter
from protolink.llms.api import OpenAILLM


# Define the agent card
agent_card = AgentCard(
    name="example_agent",
    description="A dummy agent",
)


# Initialize the transport
transport = HTTPTransport()


# OpenAI API LLM
llm = OpenAILLM(model="gpt-5.2")


# Initialize the agent
agent = Agent(agent_card, transport, llm)


# Add Native tool
@agent.tool(name="add", description="Add two numbers")
async def add_numbers(a: int, b: int):
    return a + b


# Add MCP tool
mcp_tool = MCPToolAdapter(mcp_client, "multiply")
agent.add_tool(mcp_tool)


# Start the agent
agent.start()
```

This example demonstrates the core pieces of Protolink:

- **AgentCard** to describe the agent.
- **Transport** (here `HTTPTransport`) to handle communication.
- **LLM** backend (`OpenAILLM`).
- **Native tools** (Python functions decorated with `@agent.tool`).
- **MCP tools** registered via `MCPToolAdapter`.

