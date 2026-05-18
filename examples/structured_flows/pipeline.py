import asyncio
import os

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Pipeline
from protolink.llms import MockLLM, create_llm
from protolink.models import Task

load_dotenv()


class MyMockLLM(MockLLM):
    """Clean custom MockLLM overriding mock_call method."""

    def mock_call(self, last_user_msg: str, system_prompt: str) -> str:
        if "researcher" in system_prompt.lower():
            return f"[RESEARCH INFO] Gathered core details on: '{last_user_msg}'"
        elif "summarizer" in system_prompt.lower():
            return f"[SUMMARY] Distilled key points:\n- Protolink enables stateful A2A workflows.\n- Found context: '{last_user_msg}'"  # noqa: E501
        return f"[MOCK] Unprocessed generic response to '{last_user_msg}'"


# Select LLM
LLM_PROVIDER = "mock"  # <-- UNCOMMENT to use a Mock LLM

# It is suggested to use an actual LLM e.g. local Ollama for free testing
# LLM_PROVIDER = "ollama"  # <-- UNCOMMENT to use Ollama
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
        llm=MyMockLLM() if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="""You are a diligent researcher. Gather facts and present them clearly.
            Use your own knowledge to provide a comprehensive answer. Do not rely on external tools or agents.""",
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
        llm=MyMockLLM() if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are a summarizer. Distill gather facts into high-level points.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
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
