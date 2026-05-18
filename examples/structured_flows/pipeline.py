import asyncio
import os
from collections.abc import AsyncIterator
from typing import ClassVar

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Pipeline
from protolink.llms import create_llm  # LLM Factory
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.models import Task

load_dotenv()


# Define a premium MockLLM to make this run 100% offline without API keys
class MockLLM(LLM):
    model_type: ClassVar[str] = "api"
    provider: ClassVar[str] = "mock"

    def __init__(self):
        super().__init__(model="mock-gpt", model_params={})

    def call(self, history: ConversationHistory) -> str:
        import json

        # Simple rule-based mock matching the domain
        last_user_msg = ""
        for m in reversed(history.messages):
            if m.get("role") == "user":
                last_user_msg = str(m.get("content", ""))
                break

        system_prompt = ""
        for m in history.messages:
            if m.get("role") == "system":
                system_prompt = str(m.get("content", ""))

        if "researcher" in system_prompt.lower():
            content = f"[RESEARCH INFO] Gathered core details on: '{last_user_msg}'"
        elif "summarizer" in system_prompt.lower():
            content = f"[SUMMARY] Distilled key points:\n- Protolink enables stateful A2A workflows.\n- Found context: '{last_user_msg}'"  # noqa: E501
        else:
            content = f"[MOCK] Unprocessed generic response to '{last_user_msg}'"

        return json.dumps({"type": "final", "content": content})

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True


# Select LLM
LLM_PROVIDER = "mock"  # <-- UNCOMMENT to use a Mock LLM

# It is suggested to use an actual LLM e.g. local Ollama for free testing
# LLM_PROVIDER = "ollama" # <-- UNCOMMENT to use Ollama
LLM_ARGS = {"base_url": "http://localhost:11434", "model": "gemma4:e4b"}
# OR OpenAI, or any LLM in protolink.llms. Or even your own custom LLM
# LLM_PROVIDER = "openai" # <-- UNCOMMENT to use OpenAI
# LLM_ARGS = {"model": "gpt-4o-mini", "api_key": "xxx"}

REGISTRY_URL = "http://localhost:9040"


async def main():
    print("=" * 70)
    print("🚀 Protolink Flow: Pipeline (Sequential Orchestration)")
    print("=" * 70)
    print("This example demonstrates sequential task orchestration.")
    print("Protolink's Pipeline automatically builds downstream semantic instructions")
    print("and injects them to align adjacent steps.\n")

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)
    print("✅ Registry started")

    # 2. Setup Researcher Agent
    researcher = Agent(
        card={
            "name": "researcher",
            "url": "http://localhost:8041",
            "description": "Expert researcher that gathers comprehensive data on requested topics.",
        },
        llm=MockLLM() if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are a diligent researcher. Gather facts and present them clearly.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )
    researcher.start(background=True)
    print("✅ Researcher agent started")

    # 3. Setup Summarizer Agent
    summarizer = Agent(
        card={
            "name": "summarizer",
            "url": "http://localhost:8042",
            "description": "Expert at synthesizing dense information into clear, concise summaries.",
        },
        llm=MockLLM() if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are a summarizer. Distill gather facts into high-level points.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )
    summarizer.start(background=True)
    print("✅ Summarizer agent started")

    # Allow startup and registry synchronization
    await asyncio.sleep(0.5)

    # 4. Build and Execute Pipeline
    pipeline = Pipeline(
        steps=["researcher", "summarizer"],
        registry=registry,
    )

    task = Task.create_infer(prompt="Research the future of Agentic computing.")
    print("\n🟢 Executing Pipeline Flow...")
    result = await pipeline.execute(task)

    print("\n" + "-" * 50)
    print("🏁 Pipeline Execution Results")
    print("-" * 50)
    print("Final Output:")
    print(result.get_last_part_content())
    print("\nEntire Task Message Flow:")
    for idx, msg in enumerate(result.messages):
        print(f"  [{idx}] {msg.role.upper()}: {msg.parts[0].content}")

    print("\nEntire Task Artifact Flow:")
    for idx, art in enumerate(result.artifacts):
        content = art.parts[0].content if art.parts else "No Content"
        print(f"  [{idx}] ARTIFACT: {content}")

    # Cleanup
    print("\n🛑 Shutting down...")
    summarizer.stop()
    researcher.stop()
    registry.stop()


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("💡 OPENAI_API_KEY not set. Running with lightweight MockLLM (offline-safe).")
    asyncio.run(main())
