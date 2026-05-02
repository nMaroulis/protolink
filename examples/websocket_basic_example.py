"""WebSocket transport basic example.

Mirrors the notebooks/basic_example flow (Registry + WeatherAgent + AlertAgent)
but uses WebSocketTransport instead of HTTP.

Run:
    python examples/websocket_basic_example.py

Ports used:
- Registry: 9000
- WeatherAgent: 8010
- AlertAgent: 8020

All URLs must use ws:// scheme for WebSocketTransport.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from protolink.agents import Agent
from protolink.core.events import TaskProgressEvent, TaskStatusUpdateEvent
from protolink.discovery import Registry
from protolink.models import AgentCard, Message, Task


class WeatherAgent(Agent):
    async def handle_task(self, task: Task) -> Task:
        """Handle a task by calling the local weather tool and returning the completed task."""
        result = await self.call_tool("get_weather", city="Geneva")
        return task.complete(f"Weather data: {result}")

    async def handle_task_streaming(self, task: Task) -> AsyncIterator[Any]:
        """Stream progress events while the task is being handled."""
        yield TaskStatusUpdateEvent(task_id=task.id, previous_state="submitted", new_state="working")
        for step in range(1, 4):
            await asyncio.sleep(0.25)
            yield TaskProgressEvent(task_id=task.id, progress=step * 30, message=f"Fetching weather ({step}/3)")

        result_task = await self.handle_task(task)
        yield TaskStatusUpdateEvent(
            task_id=result_task.id,
            previous_state="working",
            new_state="completed",
            final=True,
        )


class AlertAgent(Agent):
    async def handle_task(self, task: Task) -> Task:
        """Simple no-op task handler for the example."""
        return task.complete("AlertAgent received task")


async def main() -> None:
    """Run a tiny multi-agent system over WebSockets (including streaming)."""
    registry_url = "ws://127.0.0.1:9000"
    weather_url = "ws://127.0.0.1:8010"
    alert_url = "ws://127.0.0.1:8020"

    registry = Registry(transport="websocket", url=registry_url)
    await registry.start()

    weather_card = AgentCard(url=weather_url, name="WeatherAgent", description="Produces weather data")
    weather_agent = WeatherAgent(
        card=weather_card,
        transport="websocket",
        registry="websocket",
        registry_url=registry_url,
    )

    @weather_agent.tool(name="get_weather", description="Return weather data for a city")
    async def get_weather(city: str) -> dict[str, Any]:
        return {"city": city, "temperature": 28, "condition": "sunny"}

    alert_card = AgentCard(url=alert_url, name="AlertAgent", description="Consumes weather data and sends alerts")
    alert_agent = AlertAgent(
        card=alert_card,
        transport="websocket",
        registry="websocket",
        registry_url=registry_url,
    )

    @alert_agent.tool(name="alert_tool", description="Send an alert")
    async def alert_tool(message: str) -> dict[str, Any]:
        print(f"ALERT: {message}")
        return {"status": "sent", "message": message}

    await asyncio.gather(weather_agent.start(register=True), alert_agent.start(register=True))

    await asyncio.sleep(0.3)

    print("\n--- Registry discovery (via AlertAgent) ---")
    discovered = await alert_agent.discover_agents()
    for a in discovered:
        print(f"- {a.name} @ {a.url}")

    print("\n--- Request/response task: AlertAgent -> WeatherAgent ---")
    task = Task.create(Message.user("What's the weather in Geneva?"))
    res_task = await alert_agent.call_agent(weather_url, task)
    print(res_task.messages[-1].parts[0].content)

    print("\n--- Streaming task events: AlertAgent -> WeatherAgent (/tasks/stream) ---")
    stream_task = Task.create(Message.user("Stream the weather request"))
    if alert_agent.client is None:
        raise RuntimeError("Alert agent has no client configured")

    event_count = 0
    async for event in alert_agent.client.send_task_streaming(weather_url, stream_task):
        event_count += 1
        print(f"[event {event_count}] {event}")

    print("\nShutting down...")
    await asyncio.gather(weather_agent.stop(), alert_agent.stop())
    await registry.stop()


if __name__ == "__main__":
    asyncio.run(main())
