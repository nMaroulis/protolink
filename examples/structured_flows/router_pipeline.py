import asyncio
import os
from collections.abc import AsyncIterator
from typing import ClassVar

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Pipeline, Router
from protolink.llms.api import OpenAILLM
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.models import Message, Task

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

        # Writer Agent
        if "writer" in system_prompt.lower():
            # Mock the writer producing output and evaluating next steps based on user input
            if "bad" in last_user_msg.lower() or "draft" in last_user_msg.lower():
                return "Draft: This is a draft that requires intensive review. [ROUTE: editor]"
            return "Perfect Output: This content is absolutely beautiful and ready. [ROUTE: qa]"

        # Editor Agent
        elif "editor" in system_prompt.lower():
            return f"[EDITED] Polished the draft: '{last_user_msg}' to look neat."

        # QA Agent
        elif "quality" in system_prompt.lower():
            return f"[APPROVED] QA Verified successfully: '{last_user_msg}'"

        return f"[MOCK] Generic output to '{last_user_msg}'"

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        yield self.call(history)


LLM_PROVIDER = OpenAILLM(model="gpt-4o-mini") if os.getenv("OPENAI_API_KEY") else MockLLM()
REGISTRY_URL = "http://localhost:9040"


async def main():
    print("=" * 70)
    print("🚀 Protolink Flow: Router + Pipeline Integration")
    print("=" * 70)
    print("This example showcases how a Router seamlessly integrates as a step")
    print("within a Pipeline, allowing dynamic, LLM-based branching topology.\n")

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)

    # 2. Setup Agents
    writer = Agent(
        card={"name": "writer", "url": "http://localhost:8051", "description": "Writes drafts and decides routes."},
        llm=LLM_PROVIDER,
        system_prompt="You are a writer. Draft content and route to 'editor' if it needs work, or 'qa' if it looks excellent.",  # noqa: E501
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    editor = Agent(
        card={"name": "editor", "url": "http://localhost:8052", "description": "Polishes draft content."},
        llm=LLM_PROVIDER,
        system_prompt="You are a professional editor. Format, improve structure and polish the content.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    qa = Agent(
        card={"name": "qa", "url": "http://localhost:8053", "description": "Quality assurance check."},
        llm=LLM_PROVIDER,
        system_prompt="You are a QA specialist. Verify the draft is clean and output a final approval message.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )

    writer.start(background=True)
    editor.start(background=True)
    qa.start(background=True)

    await asyncio.sleep(0.5)

    # 3. Define the Router
    # The router decides to dispatch to either editor or qa based on [ROUTE: key]
    router = Router(
        routes={"editor": "editor", "qa": "qa"},
        routing_prompt="If the content requires editing, output '[ROUTE: editor]'. If it is perfect, output '[ROUTE: qa]'.",  # noqa: E501
        registry=registry,
    )

    # 4. Integrate Router as step 2 in the Pipeline
    pipeline = Pipeline(registry=registry)
    pipeline.add_step(writer).add_step(router)

    # Execution 1: Bad Draft (Routes to editor)
    print("\n🟢 Scenario 1: Drafting content that needs edits...")
    task1 = Task.create(
        Message.user("Write a rough draft about quantum mechanics. Use the word 'draft' and make it look unfinished.")
    )
    result1 = await pipeline.execute(task1)

    print("\n🏁 Scenario 1 Result:")
    print(f"Final Step Output: {result1.get_last_part_content()}")
    print("Messages Path:")
    for idx, msg in enumerate(result1.messages):
        print(f"  [{idx}] {msg.role.upper()}: {msg.parts[0].content}")

    # Execution 2: Excellent Draft (Routes to qa)
    print("\n" + "=" * 50)
    print("🟢 Scenario 2: Drafting perfect content...")
    task2 = Task.create(Message.user("Write a neat and perfect sentence about butterflies."))
    result2 = await pipeline.execute(task2)

    print("\n🏁 Scenario 2 Result:")
    print(f"Final Step Output: {result2.get_last_part_content()}")
    print("Messages Path:")
    for idx, msg in enumerate(result2.messages):
        print(f"  [{idx}] {msg.role.upper()}: {msg.parts[0].content}")

    # Cleanup
    print("\n🛑 Shutting down...")
    qa.stop()
    editor.stop()
    writer.stop()
    registry.stop()


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("💡 OPENAI_API_KEY not set. Running with lightweight MockLLM (offline-safe).")
    asyncio.run(main())
