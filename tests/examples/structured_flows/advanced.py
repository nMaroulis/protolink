import asyncio

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Parallel, Pipeline
from protolink.llms import MockLLM, create_llm
from protolink.models import Artifact, Message, Task


class CustomMockLLM(MockLLM):
    def mock_call(self, last_user_msg: str, system_prompt: str) -> str:
        if "research" in system_prompt.lower():
            return f"[RESEARCHER] Gathered information about: '{last_user_msg}'"
        elif "security" in system_prompt.lower():
            return "[SECURITY] Audited the research content. Confirmed no credential leaks or sensitive data exposure."
        elif "format" in system_prompt.lower() or "performance" in system_prompt.lower():
            return "[FORMATTING] Verified structural layout. Formatting is optimized and clean."
        elif "summarizer" in system_prompt.lower():
            return f"[SUMMARY] Synthesized the research and reviews. Everything looks solid.\nInput payload: {last_user_msg}"  # noqa: E501

        return f"[MOCK] Generic output to '{last_user_msg}'"


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


mock_llm = CustomMockLLM()

# Select LLM
LLM_PROVIDER = "mock"  # <-- UNCOMMENT to use a Mock LLM

# It is suggested to use an actual LLM e.g. local Ollama for free testing
LLM_PROVIDER = "ollama"  # <-- UNCOMMENT to use Ollama
LLM_ARGS = {"base_url": "http://localhost:11434", "model": "gemma4:e4b"}
# OR OpenAI, or any LLM in protolink.llms. Or even your own custom LLM
# LLM_PROVIDER = "openai" # <-- UNCOMMENT to use OpenAI
# LLM_ARGS = {"model": "gpt-4o-mini", "api_key": "xxx"}

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
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
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
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
    )

    perf_agent = ArtifactReviewerAgent(
        name="format_inspector",
        description="Profiles formatting.",
        system_prompt="Audit content for format standard issues.",
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
    )

    summarizer = Agent(
        card={"name": "summarizer", "url": "http://localhost:8084", "description": "Summarizes research + reviews."},
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
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
    user_prompt = "Please analyze and write a secure report on the modern WebSockets protocol."
    task = Task.create_infer(prompt=user_prompt)

    print("🟢 Executing Advanced Nested Flow (Sequential -> Concurrent -> Sequential)...")
    result = await pipeline.execute(task)

    print("\n" + "-" * 50)
    print("🏁 Advanced Nested Flow Completed Successfully")
    print("-" * 50)

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
    perf_agent.stop()
    sec_agent.stop()
    researcher.stop()
    registry.stop()


if __name__ == "__main__":
    if LLM_PROVIDER == "mock":
        print("💡 Running with lightweight CustomMockLLM (offline-safe).")
    asyncio.run(main())
