import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from protolink.agents import Agent
from protolink.agents.builtins import StructuredAgent
from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.flows import Graph, Parallel, Router
from protolink.models import Artifact, Message, Part, Task

REGISTRY_URL = "http://localhost:9030"


# Mock Agents for demonstration
class WriterAgent(Agent):
    async def handle_task(self, task: Task) -> Task:
        print(f"   [Writer] Writing content for task: {task.get_last_part_content()}")
        task.add_artifact(Artifact(parts=[Part.text("Drafted text content.")]))
        return task


class EditorAgent(Agent):
    async def handle_task(self, task: Task) -> Task:
        print("   [Editor] Editing the content...")
        task.add_artifact(Artifact(parts=[Part.text("Edited text content. No errors found.")]))
        return task


class ReviewerAgent(Agent):
    async def handle_task(self, task: Task) -> Task:
        print("   [Reviewer] Reviewing the edited content...")
        task.add_artifact(Artifact(parts=[Part.text("Quality check PASSED.")]))
        return task


class QualityControlAgent(Agent):
    async def handle_task(self, task: Task) -> Task:
        print("   [QualityControl] Performing final pass...")
        task.add_artifact(Artifact(parts=[Part.text("Content is ready for production.")]))
        return task


async def main():
    print("=" * 70)
    print("🚀 Advanced Structured Flows Example")
    print("=" * 70)

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)

    # 2. Setup mock agents
    writer = WriterAgent(
        card={"name": "writer", "url": "http://localhost:8031", "description": "Writes text"},
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    editor = EditorAgent(
        card={"name": "editor", "url": "http://localhost:8032", "description": "Edits text"},
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    reviewer = ReviewerAgent(
        card={"name": "reviewer", "url": "http://localhost:8033", "description": "Reviews text"},
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    qc = QualityControlAgent(
        card={"name": "quality", "url": "http://localhost:8034", "description": "QC check"},
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )

    writer.start(background=True)
    editor.start(background=True)
    reviewer.start(background=True)
    qc.start(background=True)

    await asyncio.sleep(1)  # wait for registration

    # ==========================================
    # Example 1: Parallel Flow
    # ==========================================
    print("\n" + "-" * 50)
    print("🟢 Executing Parallel Flow")
    print("-" * 50)

    # Executes Editor and Reviewer at the exact same time
    parallel = Parallel(branches=["editor", "reviewer"], registry=registry)

    task_parallel = Task.create(Message.user("Please analyze this draft."))
    res_parallel = await parallel.execute(task_parallel)

    print("\n   [Parallel Flow Accumulated Artifacts]")
    for art in res_parallel.artifacts:
        print(f"    - {art.parts[0].content}")

    # ==========================================
    # Example 2: Router Flow (Conditional)
    # ==========================================
    print("\n" + "-" * 50)
    print("🟢 Executing Conditional Router Flow")
    print("-" * 50)

    def route_condition(t: Task) -> str:
        content = t.get_last_part_content()
        return "needs_edit" if "bad" in content.lower() else "good_to_go"

    router = Router(
        routes={"needs_edit": "editor", "good_to_go": "quality"}, condition_fn=route_condition, registry=registry
    )

    task_good = Task.create(Message.user("This looks amazing and ready."))
    await router.execute(task_good)

    task_bad = Task.create(Message.user("This is really bad."))
    await router.execute(task_bad)

    # ================================================
    # Example 3: Graph Flow inside StructuredAgent
    # ================================================
    print("\n" + "-" * 50)
    print("🟢 Executing Graph Flow via StructuredAgent")
    print("-" * 50)

    graph = Graph(registry=registry)

    # Nodes
    graph.add_node("entry", "writer")
    graph.add_node("process", "editor")
    graph.add_node("final", "quality")

    # Edges
    graph.add_edge("entry", "process")

    def review_logic(t: Task) -> str:
        # Complex LangGraph-like iteration logic: route to final
        return "approved"

    graph.add_conditional_edge("process", review_logic, {"approved": "final", "rejected": "process"})
    graph.add_edge("final", "__END__")
    graph.set_entry_point("entry")

    # Wrap the entire graph state machine inside an autonomous Agent!
    structured_agent = StructuredAgent(
        card={"name": "graph_agent", "url": "http://localhost:8035", "description": "LangGraph style Agent"},
        flow=graph,
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=1,
    )
    await structured_agent.start()

    client = AgentClient(transport="http", url="http://localhost:8036")
    task_graph = Task.create(Message.user("Write a blog post about Protolink."))
    res_graph = await client.send_task("http://localhost:8035", task_graph)

    print("\n   [Graph Flow Final Task State]")
    for idx, art in enumerate(res_graph.artifacts):
        print(f"    Step {idx + 1}: {art.parts[0].content}")

    # Cleanup
    print("\n🛑 Shutting down...")
    structured_agent.stop()
    qc.stop()
    reviewer.stop()
    editor.stop()
    writer.stop()
    registry.stop()


if __name__ == "__main__":
    asyncio.run(main())
