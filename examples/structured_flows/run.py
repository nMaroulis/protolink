import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from protolink.agents import Agent
from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.flows import Pipeline
from protolink.models import Task

REGISTRY_URL = "http://localhost:9020"


async def main():
    print("=" * 70)
    print("🚀 Structured Flows Example")
    print("=" * 70)

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)
    print("✅ Registry started")

    # 2. Setup Agent A (Researcher)
    class ResearcherAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            print("   [Researcher] Analyzing task...")
            # Simulate some processing without needing an LLM or complex tools
            from protolink.models import Artifact, Part

            task.add_artifact(
                Artifact(parts=[Part.text("Research output: Protolink A2A protocol is highly extensible.")])
            )
            return task

    researcher = ResearcherAgent(
        card={"name": "researcher", "url": "http://localhost:8021", "description": "Researches topics"},
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )
    researcher.start(background=True)
    print("✅ Researcher agent started")

    # 3. Setup Agent B (Summarizer)
    class SummarizerAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            print("   [Summarizer] Summarizing previous steps...")
            # Retrieve last info and summarize
            from protolink.models import Artifact, Part

            last_content = task.get_last_part_content()
            task.add_artifact(Artifact(parts=[Part.text(f"Summary of findings: We learned that '{last_content}'")]))
            return task

    summarizer = SummarizerAgent(
        card={"name": "summarizer", "url": "http://localhost:8022", "description": "Summarizes text"},
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )
    summarizer.start(background=True)
    print("✅ Summarizer agent started")

    await asyncio.sleep(1)  # wait for registration

    # ==========================================
    # Approach 1: Script-based Pipeline Flow
    # ==========================================
    print("\n" + "-" * 40)
    print("🟢 Running Script-based Pipeline Flow")
    print("-" * 40)

    # We define a Pipeline out of agents that executes them sequentially
    pipeline = Pipeline(
        steps=[
            "researcher",  # Step 1: Researcher agent via Registry name
            "summarizer",  # Step 2: Summarizer agent via Registry name
        ],
        registry=registry,
    )

    # Initial user request
    from protolink.models import Message

    task_p = Task.create(Message.user("Research Protolink please."))

    result_p = await pipeline.execute(task_p)
    print("\n   [Pipeline Output]")
    print(result_p.get_last_part_content())

    # ==========================================
    # Approach 2: Autonomous StructuredAgent
    # ==========================================
    print("\n" + "-" * 40)
    print("🟢 Running Autonomous StructuredAgent")
    print("-" * 40)

    # User interacts with the StructuredAgent as if it were a single agent
    client = AgentClient(transport="http", url="http://localhost:8024")

    task_s = Task.create(Message.user("Research Protolink please."))

    result_s = await client.send_task("http://localhost:8023", task_s)

    print("\n   [StructuredAgent Output]")
    print(result_s.get_last_part_content())

    # Cleanup
    print("\n🛑 Shutting down...")
    summarizer.stop()
    researcher.stop()
    registry.stop()


if __name__ == "__main__":
    asyncio.run(main())
