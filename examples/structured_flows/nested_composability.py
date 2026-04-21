import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from protolink.agents import Agent
from protolink.flows import Parallel, Pipeline
from protolink.models import Artifact, Message, Part, Task


async def main():
    print("=" * 70)
    print("🚀 Nested Flow Composability Example (No StructuredAgent)")
    print("=" * 70)

    # 1. Define sample Agents
    class MockAgent(Agent):
        def __init__(self, name, url, description):
            super().__init__(card={"name": name, "url": url, "description": description}, transport="http")

        async def handle_task(self, task: Task) -> Task:
            print(f"   [{self.card.name}] Processing...")
            task.add_artifact(Artifact(parts=[Part.text(f"Output from {self.card.name}")]))
            return task

    researcher_a = MockAgent("researcher_a", "http://localhost:8031", "Researcher A")
    researcher_b = MockAgent("researcher_b", "http://localhost:8032", "Researcher B")
    writer = MockAgent("writer", "http://localhost:8033", "Writer")
    editor = MockAgent("editor", "http://localhost:8034", "Editor")

    # 2. Build a Nested Flow
    # Pipeline: (Parallel Researchers) -> Writer -> Editor

    print("\n📦 Building nested flow architecture...")

    # Nested Parallel block for research
    research_block = Parallel(branches=[researcher_a, researcher_b])

    # Main Pipeline using the new fluid API
    main_flow = Pipeline().add_step(research_block).add_step(writer).add_step(editor)

    print("✅ Flow built: Pipeline( Parallel(A, B) -> Writer -> Editor )")

    # 3. Execute the Flow
    print("\n🟢 Executing nested flow...")
    initial_task = Task.create(Message.user("Create a report about Protolink."))

    result_task = await main_flow.execute(initial_task)

    print("\n" + "-" * 40)
    print("🏁 Final Flow Results")
    print("-" * 40)

    # Check artifacts to see the journey
    for i, artifact in enumerate(result_task.artifacts):
        for part in artifact.parts:
            if part.type == "text":
                print(f"Artifact {i + 1}: {part.content}")

    print("\n✨ Notice how Parallel gathered multiple outputs before passing them to Writer!")
    print(f"Total messages: {len(result_task.messages)}")
    print(f"Total artifacts: {len(result_task.artifacts)}")


if __name__ == "__main__":
    asyncio.run(main())
