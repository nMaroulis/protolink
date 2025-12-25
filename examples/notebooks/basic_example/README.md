# Basic Example

This directory contains a basic example of how to use ProtoLink to create a multi-agent system with HTTP transport. The example demonstrates:

- **Registry**: A central service for agent discovery and registration
- **Weather Agent**: An agent that provides weather data
- **Alert Agent**: An agent that processes weather data and sends alerts

## Files

- [`registry.ipynb`](registry.ipynb) - Sets up the HTTP registry for agent discovery
- [`weather_agent.ipynb`](weather_agent.ipynb) - Creates a weather agent with mock weather data
- [`alert_agent.ipynb`](alert_agent.ipynb) - Creates an alert agent that communicates with the weather agent

## Architecture Overview

```
┌─────────────────┐    HTTP REST API   ┌─────────────────┐
│   Registry      │◄──────────────────►│  Alert Agent    │
│  (localhost:    │                    │  (localhost:    │
│   9000)         │                    │   8020)         │
└─────────────────┘                    └─────────────────┘
         ▲                                   ▲
         │                                   │
         │ HTTP REST API                     │ HTTP REST API
         │                                   │
┌─────────────────┐                    ┌─────────────────┐
│ Weather Agent   │◄──────────────────►│  Alert Agent    │
│ (localhost:     │                    │                 │
│  8010)          │                    │                 │
└─────────────────┘                    └─────────────────┘
```

## Getting Started

### 1. Start the Registry

First, run the [`registry.ipynb`](registry.ipynb) notebook to start the registry service:

```python
from protolink.discovery import Registry
from protolink.transport import HTTPRegistryTransport

REGISTRY_URL = "http://localhost:9000"
transport = HTTPRegistryTransport(url=REGISTRY_URL)
registry = Registry(transport=transport)
await registry.start()
```

The registry exposes these endpoints:
- **GET** `/agents` - List all registered agents
- **POST** `/agents` - Register a new agent  
- **DELETE** `/agents/{agent_url}` - Unregister an agent
- **GET** `/status` - View registry status and registered agents

### 2. Start the Weather Agent

Run the [`weather_agent.ipynb`](weather_agent.ipynb) notebook:

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.transport import HTTPAgentTransport

URL = "http://localhost:8010"
REGISTRY_URL = "http://localhost:9000"

class WeatherAgent(Agent):
    async def handle_task(self, task: Task):
        result = await self.call_tool("get_weather", city="Geneva")
        return task.complete(f"Weather data: {result}")

transport = HTTPAgentTransport(url=URL)
card = AgentCard(url=URL, name="WeatherAgent", description="Produces weather data")
agent = WeatherAgent(card=card, transport=transport, registry=REGISTRY_URL)

@agent.tool(name="get_weather", description="Return weather data for a city")
async def get_weather(city: str):
    return {"city": city, "temperature": 28, "condition": "sunny"}

await agent.start(register=True)
```

### 3. Start the Alert Agent

Run the [`alert_agent.ipynb`](alert_agent.ipynb) notebook:

```python
from protolink.agents import Agent
from protolink.models import Message, Task
from protolink.transport import HTTPAgentTransport, HTTPRegistryTransport

URL = "http://localhost:8020"
REGISTRY_URL = "http://localhost:9000"

class AlertAgent(Agent):
    async def handle_task(self, task: Task):
        data = task.payload
        if data["temperature"] > 25:
            await self.call_tool("alert_tool", message=f"Hot weather in {data['city']}! {data['temperature']}°C")
        return task

transport = HTTPAgentTransport(url=URL)
registry = HTTPRegistryTransport(url=REGISTRY_URL)
card = {"url": URL, "name": "AlertAgent", "description": "Sends alerts based on data"}
agent = AlertAgent(card=card, transport=transport, registry=registry)

@agent.tool(name="alert_tool", description="Send an alert")
async def send_alert(message: str):
    print(f"ALERT: {message}")
    return {"status": "sent", "message": message}

await agent.start(register=True)
```

## Key Concepts

### Registry
- **Purpose**: Central service for agent discovery and registration
- **Transport**: Uses HTTPRegistryTransport for REST API communication
- **Endpoints**: Provides agent management and status endpoints

### Agents
- **Transport**: Both agents use HTTPAgentTransport for agent-to-agent communication
- **Registration**: Agents automatically register with the registry on startup
- **Tools**: Agents can define native tools using the `@tool` decorator
- **Task Handling**: Agents implement `handle_task` to process incoming tasks

### Communication Patterns
- **Agent-to-Registry**: HTTP REST API for registration and discovery
- **Agent-to-Agent**: HTTP client-server for task delegation and responses
- **Tool Calling**: Agents can call their own tools and receive results

## Testing the System

Once all agents are running:

1. **Check Registry Status**: Visit `http://localhost:9000/status`
2. **Check Agent Status**: 
   - Weather Agent: `http://localhost:8010/status`
   - Alert Agent: `http://localhost:8020/status`
3. **Send Tasks**: Use the Alert Agent to send tasks to the Weather Agent and observe the alert system

## Ports Used

- **Registry**: 9000
- **Weather Agent**: 8010  
- **Alert Agent**: 8020

Make sure these ports are available before starting the system.