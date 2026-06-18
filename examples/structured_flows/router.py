import asyncio
import os

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Pipeline, Router
from protolink.llms import MockLLM, create_llm
from protolink.models import Task

MOCK_RESPONSES = {
    "writer": {
        "bad": "Draft: This is a draft that requires intensive review. [ROUTE: editor]",
        "draft": "Draft: This is a draft that requires intensive review. [ROUTE: editor]",
        "*": "Perfect Output: This content is absolutely beautiful and ready. [ROUTE: qa]",
    },
    "editor": "[EDITED] Polished the draft to look neat.",
    "qa": "[APPROVED] QA Verified successfully.",
}

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
    print("🚀 Protolink Flow: Router + Pipeline Integration")
    print("=" * 70)
    print("This example showcases how a Router seamlessly integrates as a step")
    print("within a Pipeline, allowing dynamic, LLM-based branching topology.\n")

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)

    # 2. Setup Agents
    writer = Agent(
        card={
            "name": "writer",
            "url": "http://localhost:8051",
            "description": "Writes drafts and decides routes.",
            "capabilities": {
                "delegation": False
            },  # With this capability set to false, the agent will not be able to call other agents.
        },
        llm=MockLLM(mock_responses={"writer": MOCK_RESPONSES["writer"]})
        if LLM_PROVIDER == "mock"
        else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are a writer. Draft content and route to 'editor' if it needs work, or 'qa' if it looks excellent.",  # noqa: E501
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )
    editor = Agent(
        card={
            "name": "editor",
            "url": "http://localhost:8052",
            "description": "Polishes draft content.",
            "capabilities": {"delegation": False},
        },
        llm=MockLLM(default_response=MOCK_RESPONSES["editor"])
        if LLM_PROVIDER == "mock"
        else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are a professional editor. Format, improve structure and polish the content.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )
    qa = Agent(
        card={
            "name": "qa",
            "url": "http://localhost:8053",
            "description": "Quality assurance check.",
            "capabilities": {"delegation": False},
        },
        llm=MockLLM(default_response=MOCK_RESPONSES["qa"])
        if LLM_PROVIDER == "mock"
        else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are a QA specialist. Verify the draft is clean and output a final approval message.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )

    writer.start(background=True)
    editor.start(background=True)
    qa.start(background=True)

    await asyncio.sleep(0.5)

    # 3. Define the Router
    # The router prefers structured Part.route(...) decisions and still accepts [ROUTE: key] tags from text-only models.
    router = Router(
        routes={"editor": "editor", "qa": "qa"},
        routing_prompt="If the content requires editing, choose 'editor'. If it is perfect, choose 'qa'.",
        registry=registry,
    )

    # 4. Integrate Router as step 2 in the Pipeline
    pipeline = Pipeline(registry=registry)
    pipeline.add_step(writer).add_step(router)

    # Execution 1: Bad Draft (Routes to editor)
    print("\n🟢 Scenario 1: Drafting content that needs edits...")
    user_prompt_1 = "Write a rough draft about quantum mechanics. Use the word 'draft' and make it look unfinished."
    task1 = Task.create_infer(prompt=user_prompt_1)

    result1 = await pipeline.execute(task1)

    print("\n🏁 Scenario 1 Result:")
    print(f"Final Step Output: {result1.get_last_part_content()}")
    print("\nEntire Task Message Flow:")
    for idx, msg in enumerate(result1.messages):
        print(f"  [{idx}] {msg.role.upper()}: {msg.parts[0].content}")

    print("\nEntire Task Artifact Flow:")
    for idx, art in enumerate(result1.artifacts):
        content = art.parts[0].content if art.parts else "No Content"
        print(f"  [{idx}] ARTIFACT: {content}")

    # Execution 2: Excellent Draft (Routes to qa)
    print("\n" + "=" * 50)
    print("🟢 Scenario 2: Drafting perfect content...")
    user_prompt_2 = "Write a neat and perfect sentence about butterflies."
    task2 = Task.create_infer(prompt=user_prompt_2)

    result2 = await pipeline.execute(task2)

    print("\n🏁 Scenario 2 Result:")
    print(f"Final Step Output: {result2.get_last_part_content()}")
    print("\nEntire Task Message Flow:")
    for idx, msg in enumerate(result2.messages):
        print(f"  [{idx}] {msg.role.upper()}: {msg.parts[0].content}")

    print("\nEntire Task Artifact Flow:")
    for idx, art in enumerate(result2.artifacts):
        content = art.parts[0].content if art.parts else "No Content"
        print(f"  [{idx}] ARTIFACT: {content}")

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
