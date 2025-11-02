# Protolink A2A

[![PyPI](https://img.shields.io/pypi/v/protolink?color=blue)](https://pypi.org/project/protolink/)
[![Python Version](https://img.shields.io/pypi/pyversions/protolink)](https://pypi.org/project/protolink/)
[![License](https://img.shields.io/pypi/l/protolink)](https://github.com/nmaroulis/protolink/blob/main/LICENSE)
[![Tests](https://github.com/nmaroulis/protolink/actions/workflows/ci.yml/badge.svg)](https://github.com/nmaroulis/protolink/actions)


A Python implementation of the [Agent-to-Agent (A2A) protocol](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/) for building distributed, autonomous agent systems, including a seemless integration with [MCP servers](https://modelcontextprotocol.io/docs/getting-started/intro) for integration with agents, tools, and other services. The library simplifies the process of creating agents and their interactions, making it easy for users to build and deploy their own agent systems.

## Features

- **Agent Framework**: Create autonomous agents with message and task handling capabilities
- **Service Discovery**: Built-in registry service for agent discovery and coordination
- **Secure Communication**: End-to-end encryption and authentication
- **Multiple Transports**: HTTP and WebSocket support out of the box
- **Task Management**: Built-in task queue and processing
- **Extensible**: Plugin architecture for custom transports, authenticators, and more
- **Async-First**: Built on Python's asyncio for high-performance concurrency

## Installation

```bash
# Install the core package
pip install protolink

# Install with optional dependencies
pip install "protolink[all]"  # All features
pip install "protolink[http-server]"  # For HTTP server support
pip install "protolink[encryption]"  # For encryption features
pip install "protolink[grpc]"  # For gRPC support
pip install "protolink[llms]"  # For LLM integration
```

## Quick Start

### Create a Simple Agent

```python
import asyncio
from protolink import Agent, Message

class EchoAgent(Agent):
    def __init__(self):
        super().__init__(
            agent_id="echo-agent",
            name="Echo Agent",
            capabilities=["echo"]
        )
        
    async def on_message(self, message: Message) -> dict:
        """Handle incoming messages."""
        if message.message_type == "echo":
            return {"echo": message.payload}
        return {"error": "Unknown message type"}

async def main():
    agent = EchoAgent()
    await agent.start()
    
    try:
        # Keep the agent running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await agent.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

### Discover and Communicate with Agents

```python
from protolink import Agent

async def discover_and_communicate():
    # Create an agent
    agent = Agent(agent_id="client-1", name="Client")
    await agent.start()
    
    try:
        # Discover agents with a specific capability
        echo_agents = await agent.discover_agents(capability="echo")
        
        for echo_agent in echo_agents:
            # Send a message to the agent
            response = await agent.send_message(
                recipient_id=echo_agent.agent_id,
                message_type="echo",
                payload={"text": "Hello, world!"}
            )
            print(f"Response from {echo_agent.agent_id}: {response}")
            
    finally:
        await agent.shutdown()
```

## Core Concepts

### Agents

Agents are autonomous entities that can send and receive messages, process tasks, and interact with other agents. Each agent has:

- A unique ID and name
- A set of capabilities
- Message and task handlers
- Security credentials

### Messages

Messages are the primary means of communication between agents. They include:

- Sender and recipient IDs
- Message type
- Payload (arbitrary data)
- Metadata and timestamps

### Tasks

Tasks represent units of work that can be processed by agents. They include:

- Task type and parameters
- Status tracking
- Progress updates
- Results or errors

### Registry

The registry is a central service that enables agent discovery and coordination. It provides:

- Agent registration and lookup
- Capability-based discovery
- Health monitoring
- Service metadata

## Documentation

For detailed documentation, see the [documentation](https://github.com/nmaroulis/protolink/tree/main/docs).

## Examples

Check out the [examples](examples/) directory for more usage examples, including:

- [Echo Agent](examples/echo_agent.py) - A simple echo service
- [Task Processor](examples/task_processor_agent.py) - An agent that processes tasks
- [Client Example](examples/client_example.py) - How to interact with agents

## Contributing

Contributions are welcome! Please read our [contributing guidelines](CONTRIBUTING.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by [Google's A2A protocol](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/) and [Anthropic's MCP protocol](https://modelcontextprotocol.io/docs/getting-started/intro)