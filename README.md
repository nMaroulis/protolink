# Protolink

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: Ruff](https://img.shields.io/static/v1?label=code%20style&message=Ruff&color=red&style=flat-square)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)



A lightweight, production-ready framework for **agent-to-agent communication**, implementing and extending Google's [Agent-to-Agent Communication (A2A) protocol](https://a2a-protocol.org/v0.3.0/specification/?utm_source=chatgpt.com). Designed to be the go-to Python library for building **interoperable agent systems** with minimal boilerplate.

## Features

- **A2A Protocol Implementation**: Fully compatible with **Google's A2A specification**
- **Extended Capabilities**:
  - Simplified Agent Creation and Registration: Agents can be created and registered with just a few lines of code.
  - **Runtime Transport Layer**: In-process agent communication using a shared memory space. Agents can easily communicate with each other within the same process, making it easier to build and test agent systems.
  - Enhanced security with **OAuth 2.0** and **API key support**.
  - Advanced agent capabilities and discovery.
  - Built-in support for streaming and async operations.
- **Planned Integrations**:
  - **MCP Tooling**: Model Control Protocol integration for tool usage.
  - Multi-modal agent support.
  - Advanced orchestration patterns.

## Why Protolink?

- **Simple API**: Get started with just a few lines of code.
- **Production Ready**: Built from the ground up with performance and reliability in mind.
- **Extensible**: Easily add new transport layers and protocols.
- **Community Focused**: Designed for the open-source community with clear contribution guidelines.



## Installation

### Basic Installation
This will install the base package without any optional dependencies.
```bash
# Using uv (recommended)
uv add protolink

# Using pip
pip install protolink
```

### Optional Dependencies
Protolink supports optional features through extras. Install them using square brackets:
Note: `uv add` can be replace with `pip install` if preferred.
```bash
# Install with all optional dependencies
uv add "protolink[all]"

# Install with HTTP support (for web-based agents)
uv add "protolink[http]"

# Install all the supported LLM libraries
uv add "protolink[llms]"

# For development (includes all optional dependencies and testing tools)
uv add "protolink[dev]"
```


### Development Installation
To install from source and all optional dependencies:

```bash
git clone https://github.com/nmaroulis/protolink.git
cd protolink
uv pip install -e ".[dev]"
```

## Quick Start

```python
from protolink.agent import Agent

# Create a new agent
agent = Agent(name="example_agent")

# Start the agent
agent.start()
```

## Documentation

### API Documentation

TBD

## License

MIT

## Contributing

TBD
