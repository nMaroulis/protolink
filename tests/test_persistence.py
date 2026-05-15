import json

import pytest

from protolink.agents.base import Agent
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.models import AgentCard, Message, Part, Task


class MockLLM(LLM):
    model_type = "mock"
    provider = "mock"

    def __init__(self):
        super().__init__(model="mock", model_params={})
        self.responses = []
        self.call_count = 0

    def call(self, history: ConversationHistory) -> str:
        self.call_count += 1
        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]
        return json.dumps({"type": "final", "content": "Done"})

    async def call_stream(self, history: ConversationHistory):
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True


def create_infer_task(prompt: str, session_id: str | None = None) -> Task:
    task = Task.create(Message(parts=[Part("infer", {"prompt": prompt})]))
    if session_id:
        task.metadata["session_id"] = session_id
    return task


@pytest.mark.asyncio
async def test_stateless_by_default():
    # Setup agent with default (stateless) memory
    llm = MockLLM()
    card = AgentCard(name="stateless", description="test", url="runtime://stateless")
    agent = Agent(card=card, llm=llm)

    # Task 1
    task_1 = create_infer_task("Hello 1")
    await agent.execute_task(task_1)

    # History should have: System, User, Assistant (Done)
    assert len(agent.llm.history) == 3

    # Task 2
    task_2 = create_infer_task("Hello 2")
    await agent.execute_task(task_2)

    # History should have been WIPED and reset: System, User, Assistant (Done)
    assert len(agent.llm.history) == 3
    assert agent.llm.history._messages[1].content == "Hello 2"


@pytest.mark.asyncio
async def test_session_persistence():
    # Setup agent with session memory
    llm = MockLLM()
    card = AgentCard(name="persistent", description="test", url="runtime://persistent")
    agent = Agent(card=card, llm=llm, state=["conversation"])

    session_id = "user-123"

    # Task 1
    task_1 = create_infer_task("My name is Alice", session_id)
    await agent.execute_task(task_1)

    assert len(agent.llm.history) == 3

    # Task 2 - Same session
    task_2 = create_infer_task("What is my name?", session_id)
    await agent.execute_task(task_2)

    # History should be PRESERVED:
    # [System, User1, Assistant1, User2, Assistant2]
    assert len(agent.llm.history) == 5
    assert agent.llm.history._messages[1].content == "My name is Alice"
    assert agent.llm.history._messages[3].content == "What is my name?"


@pytest.mark.asyncio
async def test_different_sessions_isolation():
    llm = MockLLM()
    card = AgentCard(name="isolated", description="test", url="runtime://isolated")
    agent = Agent(card=card, llm=llm, state=["conversation"])

    # Session A
    task_a = create_infer_task("I am A", "session-A")
    await agent.execute_task(task_a)
    assert len(agent.llm.history) == 3
    assert "A" in agent.llm.history._messages[1].content

    # Session B
    task_b = create_infer_task("I am B", "session-B")
    await agent.execute_task(task_b)

    # History for B should be fresh (but still persistent for B)
    assert len(agent.llm.history) == 3
    assert "B" in agent.llm.history._messages[1].content

    # Back to Session A
    task_a2 = create_infer_task("Who am I?", "session-A")
    await agent.execute_task(task_a2)

    # History for A should be restored and have 5 messages
    assert len(agent.llm.history) == 5
    assert "A" in agent.llm.history._messages[1].content
