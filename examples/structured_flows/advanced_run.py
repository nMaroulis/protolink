import os
import sys
import time

from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Graph, Parallel, Router
from protolink.llms.api import OpenAILLM
from protolink.models import Message, Task

load_dotenv(".env")

REGISTRY_URL = "http://localhost:9030"


def main():
    print("=" * 70)
    print("🚀 Advanced Structured Flows Example (Semantic Awareness)")
    print("=" * 70)

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)

    # 2. Setup standard LLM agents
    llm = OpenAILLM(model="gpt-4o-mini")

    writer = Agent(
        card={"name": "writer", "url": "http://localhost:8031", "description": "Writes initial blog post drafts."},
        llm=llm,
        system_prompt="You are a content writer. Produce creative and engaging drafts based on user prompts.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    editor = Agent(
        card={"name": "editor", "url": "http://localhost:8032", "description": "Edits content for grammar and style."},
        llm=llm,
        system_prompt="You are an editor. Fix grammar and improve style of the provided draft.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    reviewer = Agent(
        card={
            "name": "reviewer",
            "url": "http://localhost:8033",
            "description": "Reviews content for technical accuracy.",
        },
        llm=llm,
        system_prompt="You are a technical reviewer. Check the draft for accuracy and leave comments.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    qc = Agent(
        card={"name": "quality", "url": "http://localhost:8034", "description": "Final quality control sign-off."},
        llm=llm,
        system_prompt="You are QC.If the text looks good, reply 'APPROVED: [summary]'. Otherwise 'REJECTED: [reason]'.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )

    writer.start(background=True)
    editor.start(background=True)
    reviewer.start(background=True)
    qc.start(background=True)

    time.sleep(1)  # wait for registration

    # ==========================================
    # Example 1: Parallel Flow
    # ==========================================
    print("\n" + "-" * 50)
    print("🟢 Executing Parallel Flow")
    print("-" * 50)

    # Executes Editor and Reviewer at the exact same time
    parallel = Parallel(branches=["editor", "reviewer"], registry=registry)

    task_parallel = Task.create(Message.user("Draft: 'Protolink is an A2A multi-agent framework.'"))
    res_parallel = parallel.sync.execute(task_parallel)

    print("\n   [Parallel Flow Artifacts]")
    for art in res_parallel.artifacts:
        if art.parts:
            print(f"    - {art.parts[0].content}")

    # ==========================================
    # Example 2: Router Flow (Conditional)
    # ==========================================
    print("\n" + "-" * 50)
    print("🟢 Executing Conditional Router Flow")
    print("-" * 50)

    def route_condition(t: Task) -> str:
        content = str(t.get_last_part_content()).lower()
        return "needs_edit" if "bad" in content else "good_to_go"

    router = Router(
        routes={"needs_edit": "editor", "good_to_go": "quality"}, condition_fn=route_condition, registry=registry
    )

    task_good = Task.create(Message.user("This draft looks amazing and ready."))
    router.sync.execute(task_good)

    task_bad = Task.create(Message.user("This draft is really bad and has grammar issues."))
    router.sync.execute(task_bad)

    # ================================================
    # Example 3: Graph Flow (Direct Execution)
    # ================================================
    print("\n" + "-" * 50)
    print("🟢 Executing Graph Flow")
    print("-" * 50)

    graph = Graph(registry=registry)

    # Nodes
    graph.add_node("entry", "writer")
    graph.add_node("process", "editor")
    graph.add_node("final", "quality")

    # Edges
    # The Graph will automatically inject the 'process' card into the 'entry' prompt!
    graph.add_edge("entry", "process")

    def review_logic(t: Task) -> str:
        # Simple routing logic
        return "approved"

    graph.add_conditional_edge("process", review_logic, {"approved": "final", "rejected": "process"})
    graph.add_edge("final", "__END__")
    graph.set_entry_point("entry")

    # Execute graph flow directly
    task_graph = Task.create(Message.user("Write a one sentence pitch about Protolink."))
    res_graph = graph.sync.execute(task_graph)

    print("\n   [Graph Flow Final Output]")
    print(res_graph.get_last_part_content())

    # Cleanup
    print("\n🛑 Shutting down...")
    qc.stop()
    reviewer.stop()
    editor.stop()
    writer.stop()
    registry.stop()


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY is not set. Please set it to run this example.")
    else:
        main()
