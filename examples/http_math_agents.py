"""HTTP math delegation example.

This script spins up two HTTP agents:
1. QuestionAgent: accepts user text and forwards math questions to MathAgent.
2. MathAgent: exposes an ``add`` tool that parses the request, calls the tool, and returns the result.

Run with:
    python examples/http_math_agents.py
"""

from __future__ import annotations

import asyncio
import re

from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import HTTPAgentTransport


class MathAgent(Agent):
    """Agent that exposes a simple addition tool."""

    def __init__(self, port: int = 8020) -> None:
        transport = HTTPAgentTransport(url=f"http://127.0.0.1:{port}")
        card = AgentCard(
            name="math-agent",
            description="Adds two integers via a registered tool",
            url=f"http://127.0.0.1:{port}",
            capabilities={"tools": ["add"]},
        )
        super().__init__(card, transport=transport)

        @self.tool(name="add", description="Add two integers")
        async def add(a: int, b: int) -> int:
            return a + b

    async def handle_task(self, task: Task) -> Task:
        if not task.messages or not task.messages[-1].parts:
            return task.fail("No question provided")

        user_text = task.messages[-1].parts[0].content
        numbers = [int(n) for n in re.findall(r"-?\d+", user_text)]

        if len(numbers) < 2:
            return task.fail("Need two integers in the request, e.g. 'what is 2 + 3?'")

        total = await self.call_tool("add", a=numbers[0], b=numbers[1])
        reply = f"The sum of {numbers[0]} and {numbers[1]} is {total}."
        return task.complete(reply)


class QuestionAgent(Agent):
    """Agent that receives user text and delegates math requests."""

    def __init__(self, math_agent_url: str, port: int = 8021) -> None:
        transport = HTTPAgentTransport(url=f"http://127.0.0.1:{port}")
        card = AgentCard(
            name="question-agent",
            description="Routes user math questions to a dedicated math agent",
            url=f"http://127.0.0.1:{port}",
            capabilities={"routing": True},
        )
        super().__init__(card, transport=transport)
        self.math_agent_url = math_agent_url

    async def handle_task(self, task: Task) -> Task:
        if not task.messages or not task.messages[-1].parts:
            return task.fail("No user message provided")

        user_message = task.messages[-1]
        user_text = user_message.parts[0].content

        math_task = Task.create(Message.user(user_text))
        math_response = await self.send_task_to(self.math_agent_url, math_task)

        if not math_response.messages:
            return task.fail("Math agent returned no messages")

        answer = math_response.messages[-1].parts[0].content
        return task.complete(answer)


async def main() -> None:
    math_agent = MathAgent(port=8020)
    question_agent = QuestionAgent(math_agent_url=math_agent.card.url, port=8021)

    await asyncio.gather(math_agent.start(), question_agent.start())

    # Simulate a user sending a task to the question agent over HTTP.
    user_transport = HTTPAgentTransport(url="http://0.0.0.0:8022")
    try:
        user_task = Task.create(Message.user("dummy what is 2 + 3"))
        response_task = await user_transport.send_task(question_agent.card.url, user_task)
        reply = response_task.messages[-1].parts[0].content
        print(f"Question agent response: {reply}")
    finally:
        await asyncio.gather(math_agent.stop(), question_agent.stop())
        await user_transport.stop()


if __name__ == "__main__":
    asyncio.run(main())
