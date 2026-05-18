import asyncio
import os
from collections.abc import AsyncIterator
from typing import ClassVar

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Parallel
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

        if "security" in system_prompt.lower():
            return (
                f"[SECURITY REVIEW] Checked '{last_user_msg}'. Looks secure, no SQLi or XSS vulnerabilities detected."
            )
        elif "performance" in system_prompt.lower():
            return (
                f"[PERFORMANCE REVIEW] Analyzed '{last_user_msg}'. Complexity is O(N), highly optimal memory footprint."
            )

        return f"[MOCK] Generic output to '{last_user_msg}'"

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        yield self.call(history)


# Override handle_task for the mock agents to produce artifacts to make the example highly visual
class ReviewerAgent(Agent):
    def __init__(self, name: str, description: str, system_prompt: str, llm):
        super().__init__(
            card={"name": name, "url": f"http://localhost:806{name[-1]}", "description": description},
            llm=llm,
            system_prompt=system_prompt,
            transport="http",
            registry="http",
            registry_url="http://localhost:9040",
            verbosity=0,
        )

    async def handle_task(self, task: Task) -> Task:
        # Get response from the LLM
        res = await self.call_llm(task)
        # Create an artifact
        art = Artifact(id=f"art_{self.card.name}")
        art.add_text(res)
        task.add_artifact(art)
        # Add a friendly progress message
        task.add_message(Message.agent(f"Finished {self.card.name} evaluation."))
        return task


LLM_PROVIDER = OpenAILLM(model="gpt-4o-mini") if os.getenv("OPENAI_API_KEY") else MockLLM()
REGISTRY_URL = "http://localhost:9040"


async def main():
    print("=" * 70)
    print("🚀 Protolink Flow: Parallel Execution (Fan-out / Fan-in)")
    print("=" * 70)
    print("This example demonstrates running multiple specialized agents")
    print("concurrently on the same task, and merging their outputs safely.\n")

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)

    # 2. Setup Specialized Reviewers
    sec_agent = ReviewerAgent(
        name="security_reviewer",
        description="Expert at scanning code for vulnerabilities and backdoors.",
        system_prompt="You are a security reviewer. Audit the code for security flaws.",
        llm=LLM_PROVIDER,
    )
    perf_agent = ReviewerAgent(
        name="performance_reviewer",
        description="Expert at profiling performance and complexity constraints.",
        system_prompt="You are a performance reviewer. Audit the code for complexity bottlenecks.",
        llm=LLM_PROVIDER,
    )

    sec_agent.start(background=True)
    perf_agent.start(background=True)

    await asyncio.sleep(0.5)

    # 3. Create a Parallel Flow
    # Runs security_reviewer and performance_reviewer concurrently.
    parallel = Parallel(branches=["security_reviewer", "performance_reviewer"], registry=registry)

    # 4. Execute
    code_snippet = "def process_data(data):\n    return [x * 2 for x in data]"
    task = Task.create(Message.user(f"Review this Python function:\n{code_snippet}"))

    print("🟢 Executing Parallel Flow (reviews will execute concurrently)...")
    result = await parallel.execute(task)

    print("\n" + "-" * 50)
    print("🏁 Parallel Execution Results")
    print("-" * 50)

    print("\n📦 Gathered Artifacts:")
    for art in result.artifacts:
        print(f"  - Artifact ID: {art.id}")
        if art.parts:
            print(f"    Content: {art.parts[0].content}")

    print("\n💬 Final Task Messages:")
    for idx, msg in enumerate(result.messages):
        print(f"  [{idx}] {msg.role.upper()}: {msg.parts[0].content}")

    # Cleanup
    print("\n🛑 Shutting down...")
    perf_agent.stop()
    sec_agent.stop()
    registry.stop()


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("💡 OPENAI_API_KEY not set. Running with lightweight MockLLM (offline-safe).")
    asyncio.run(main())
