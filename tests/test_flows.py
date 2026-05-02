import pytest

from protolink.agents.base import Agent
from protolink.flows.graph import Graph
from protolink.flows.parallel import Parallel
from protolink.flows.pipeline import Pipeline
from protolink.flows.router import Router
from protolink.models import AgentCard, Artifact, Message, Task


class MockAgent(Agent):
    def __init__(self, name: str, append_text: str | None = None, artifact_value: str | None = None):
        card = AgentCard(name=name, description=f"Mock {name}", url=f"runtime://{name}")
        super().__init__(card=card)
        self.append_text = append_text
        self.artifact_value = artifact_value

    async def handle_task(self, task: Task) -> Task:
        if self.append_text:
            task.add_message(Message.agent(self.append_text))
        if self.artifact_value:
            art = Artifact(id=f"art_{self.card.name}")
            art.add_text(self.artifact_value)
            task.add_artifact(art)
        return task


@pytest.mark.asyncio
async def test_pipeline_execution():
    agent_a = MockAgent("AgentA", append_text="Hello from A")
    agent_b = MockAgent("AgentB", append_text="Hello from B")

    pipeline = Pipeline(steps=[agent_a, agent_b])
    task = Task(messages=[Message.user("Start")])

    result = await pipeline.execute(task)

    assert len(result.messages) == 3  # User + AgentA + AgentB
    assert result.messages[1].parts[0].content == "Hello from A"
    assert result.messages[2].parts[0].content == "Hello from B"


@pytest.mark.asyncio
async def test_parallel_execution():
    agent_a = MockAgent("AgentA", artifact_value="DataA")
    agent_b = MockAgent("AgentB", artifact_value="DataB")

    parallel = Parallel(branches=[agent_a, agent_b])
    task = Task(messages=[Message.user("Start")])

    result = await parallel.execute(task)

    # Verify fan-in aggregation
    artifact_ids = {a.id for a in result.artifacts}
    assert "art_AgentA" in artifact_ids
    assert "art_AgentB" in artifact_ids
    assert len(result.artifacts) == 2


@pytest.mark.asyncio
async def test_parallel_deep_copy_fix():
    # Test for fix #4: Ensure branches don't see each other's mutations
    class MutatingAgent(Agent):
        def __init__(self, name, key, value):
            card = AgentCard(name=name, description=name, url=f"runtime://{name}")
            super().__init__(card=card)
            self.key = key
            self.value = value

        async def handle_task(self, task: Task) -> Task:
            # Mutate metadata - if shared, both agents would see both keys
            task.metadata[self.key] = self.value
            art = Artifact(id=f"art_{self.key}")
            art.add_text(self.value)
            task.add_artifact(art)
            return task

    agent_a = MutatingAgent("AgentA", "keyA", "valA")
    agent_b = MutatingAgent("AgentB", "keyB", "valB")

    parallel = Parallel(branches=[agent_a, agent_b])
    task = Task(messages=[Message.user("Start")], metadata={"initial": "true"})

    result = await parallel.execute(task)

    # Final task should have both (fan-in logic handles merging)
    assert result.metadata["initial"] == "true"
    assert "keyA" in result.metadata
    assert "keyB" in result.metadata
    assert len(result.artifacts) == 2


@pytest.mark.asyncio
async def test_router_execution():
    agent_even = MockAgent("EvenAgent", append_text="Even")
    agent_odd = MockAgent("OddAgent", append_text="Odd")

    def condition(task: Task) -> str:
        # Route based on metadata value
        val = task.metadata.get("value", 0)
        return "even" if val % 2 == 0 else "odd"

    router = Router(routes={"even": agent_even, "odd": agent_odd}, condition_fn=condition)

    # Test even path
    task_even = Task(messages=[Message.user("Test even")], metadata={"value": 2})
    result_even = await router.execute(task_even)
    assert result_even.messages[-1].parts[0].content == "Even"

    # Test odd path
    task_odd = Task(messages=[Message.user("Test odd")], metadata={"value": 3})
    result_odd = await router.execute(task_odd)
    assert result_odd.messages[-1].parts[0].content == "Odd"


@pytest.mark.asyncio
async def test_graph_execution():
    agent_start = MockAgent("StartAgent", append_text="Starting")
    agent_mid = MockAgent("MidAgent", append_text="Processing")
    agent_end = MockAgent("EndAgent", append_text="Finished")

    graph = Graph()
    graph.add_node("start", agent_start)
    graph.add_node("mid", agent_mid)
    graph.add_node("end", agent_end)

    graph.set_entry_point("start")
    graph.add_edge("start", "mid")
    graph.add_edge("mid", "end")
    graph.add_edge("end", "__END__")

    task = Task(messages=[Message.user("Begin")])
    result = await graph.execute(task)

    # Messages should be: User, Start, Mid, End
    assert len(result.messages) == 4
    assert result.messages[1].parts[0].content == "Starting"
    assert result.messages[2].parts[0].content == "Processing"
    assert result.messages[3].parts[0].content == "Finished"


@pytest.mark.asyncio
async def test_graph_conditional_loop():
    class CounterAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            count = task.metadata.get("count", 0)
            task.metadata["count"] = count + 1
            return task

    agent_counter = CounterAgent(card=AgentCard(name="Counter", description="C", url="runtime://c"))

    def loop_condition(task: Task) -> str:
        return "continue" if task.metadata["count"] < 3 else "stop"

    graph = Graph()
    graph.add_node("counter", agent_counter)
    graph.set_entry_point("counter")

    graph.add_conditional_edge("counter", loop_condition, {"continue": "counter", "stop": "__END__"})

    task = Task(messages=[Message.user("Loop")], metadata={"count": 0})
    result = await graph.execute(task)

    assert result.metadata["count"] == 3
