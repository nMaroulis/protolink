import asyncio
import os
from collections.abc import AsyncIterator
from typing import ClassVar

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Parallel, Pipeline
from protolink.llms.api import OpenAILLM
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.models import Artifact, Message, Task

load_dotenv()


class MockLLM(LLM):
    model_type: ClassVar[str] = "api"
    provider: ClassVar[str] = "mock"

    def __init__(self):
        super().__init__(model="mock-gpt")

    def call(self, history: ConversationHistory) -> str:
        last_user_msg = ""
        for m in reversed(history.messages):
            if m.get("role") == "user":
                last_user_msg = str(m.get("content", ""))
                break

        system_prompt = ""
        for m in history.messages:
            if m.get("role") == "system":
                system_prompt = str(m.get("content", ""))

        if "research" in system_prompt.lower():
            return f"[RESEARCHER] Gathered information about: '{last_user_msg}'"
        elif "security" in system_prompt.lower():
            return "[SECURITY] Audited the research content. Confirmed no credential leaks or sensitive data exposure."
        elif "performance" in system_prompt.lower():
            return "[PERFORMANCE] Verified structural layout. Formatting is optimized and clean."
        elif "summarizer" in system_prompt.lower():
            return f"[SUMMARY] Synthesized the research and reviews. Everything looks solid.\nInput payload: {last_user_msg}"  # noqa: E501

        return f"[MOCK] Generic output to '{last_user_msg}'"

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        yield self.call(history)


# Specialized Reviewer Agent that appends a custom artifact
class ArtifactReviewerAgent(Agent):
    def __init__(self, name: str, description: str, system_prompt: str, llm):
        super().__init__(
            card={"name": name, "url": f"http://localhost:808{name[-1]}", "description": description},
            llm=llm,
            system_prompt=system_prompt,
            transport="http",
            registry="http",
            registry_url="http://localhost:9040",
            verbosity=0,
        )

    async def handle_task(self, task: Task) -> Task:
        res = await self.call_llm(task)
        art = Artifact(id=f"nested_art_{self.card.name}")
        art.add_text(res)
        task.add_artifact(art)
        task.add_message(Message.agent(f"NESTED: completed {self.card.name} check."))
        return task


LLM_PROVIDER = OpenAILLM(model="gpt-4o-mini") if os.getenv("OPENAI_API_KEY") else MockLLM()
REGISTRY_URL = "http://localhost:9040"


async def main():
    print("=" * 80)
    print("🚀 Protolink Advanced Flow: Nested Composition (Pipeline -> Parallel)")
    print("=" * 80)
    print("This example demonstrates Deep Composability: nesting a Parallel")
    print("review flow as a single step inside a sequential Pipeline.\n")

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)

    # 2. Setup Agents
    researcher = Agent(
        card={"name": "researcher", "url": "http://localhost:8081", "description": "Gathers rich raw data."},
        llm=LLM_PROVIDER,
        system_prompt="You are a researcher. Generate comprehensive domain information.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )

    sec_agent = ArtifactReviewerAgent(
        name="security_inspector",
        description="Inspects for leaks.",
        system_prompt="Audit content for leak issues.",
        llm=LLM_PROVIDER,
    )

    perf_agent = ArtifactReviewerAgent(
        name="format_inspector",
        description="Profiles formatting.",
        system_prompt="Audit content for format standard issues.",
        llm=LLM_PROVIDER,
    )

    summarizer = Agent(
        card={"name": "summarizer", "url": "http://localhost:8084", "description": "Summarizes research + reviews."},
        llm=LLM_PROVIDER,
        system_prompt="You are a summarizer. Take everything (messages & artifacts) and build a unified report.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )

    researcher.start(background=True)
    sec_agent.start(background=True)
    perf_agent.start(background=True)
    summarizer.start(background=True)

    await asyncio.sleep(0.5)

    # 3. Build Nested Parallel Committee
    review_committee = Parallel(branches=["security_inspector", "format_inspector"], registry=registry)

    # 4. Build Parent Pipeline containing the Parallel Flow
    # Steps:
    # 1. Researcher (Agent)
    # 2. review_committee (Parallel Flow!)
    # 3. Summarizer (Agent)
    pipeline = Pipeline(registry=registry)
    pipeline.add_step(researcher).add_step(review_committee).add_step(summarizer)

    # 5. Execute
    task = Task.create(Message.user("Please analyze and write a secure report on the modern WebSockets protocol."))

    print("🟢 Executing Advanced Nested Flow (Sequential -> Concurrent -> Sequential)...")
    result = await pipeline.execute(task)

    print("\n" + "-" * 50)
    print("🏁 Advanced Nested Flow Completed Successfully")
    print("-" * 50)

    print("\n📦 Unified Output Artifacts:")
    for art in result.artifacts:
        print(f"  - Artifact ID: {art.id}")
        if art.parts:
            print(f"    Content: {art.parts[0].content}")

    print("\n💬 Final Summary Output:")
    print(result.get_last_part_content())

    # Cleanup
    print("\n🛑 Shutting down...")
    summarizer.stop()
    perf_agent.stop()
    sec_agent.stop()
    researcher.stop()
    registry.stop()


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("💡 OPENAI_API_KEY not set. Running with lightweight MockLLM (offline-safe).")
    asyncio.run(main())
