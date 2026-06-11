import asyncio

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Parallel
from protolink.llms import MockLLM, create_llm
from protolink.models import Task


class CustomMockLLM(MockLLM):
    def mock_call(self, last_user_msg: str, system_prompt: str) -> str:
        if "security" in system_prompt.lower():
            return (
                f"[SECURITY REVIEW] Checked '{last_user_msg}'. Looks secure, no SQLi or XSS vulnerabilities detected."
            )
        elif "performance" in system_prompt.lower():
            return (
                f"[PERFORMANCE REVIEW] Analyzed '{last_user_msg}'. Complexity is O(N), highly optimal memory footprint."
            )

        return f"[MOCK] Generic output to '{last_user_msg}'"


mock_llm = CustomMockLLM()


# Select LLM
LLM_PROVIDER = "mock"  # <-- UNCOMMENT to use a Mock LLM

# It is suggested to use an actual LLM e.g. local Ollama for free testing
# LLM_PROVIDER = "ollama"  # <-- UNCOMMENT to use Ollama
LLM_ARGS = {"base_url": "http://localhost:11434", "model": "gemma4:e4b"}
# OR OpenAI, or any LLM in protolink.llms. Or even your own custom LLM
# LLM_PROVIDER = "openai" # <-- UNCOMMENT to use OpenAI
# LLM_ARGS = {"model": "gpt-4o-mini", "api_key": "xxx"}


AGENT_REVIEWER_URL_1 = "http://localhost:8060"
AGENT_REVIEWER_URL_2 = "http://localhost:8061"
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
    sec_agent = Agent(
        card={
            "name": "security_reviewer",
            "url": AGENT_REVIEWER_URL_1,
            "description": "Expert at scanning code for vulnerabilities and backdoors.",
        },
        system_prompt="You are a security reviewer. Audit the code for security flaws.",
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )
    perf_agent = Agent(
        card={
            "name": "performance_reviewer",
            "url": AGENT_REVIEWER_URL_2,
            "description": "Expert at profiling performance and complexity constraints.",
        },
        system_prompt="You are a performance reviewer. Audit the code for complexity bottlenecks.",
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )

    sec_agent.start(background=True)
    perf_agent.start(background=True)

    await asyncio.sleep(0.5)

    # 3. Create a Parallel Flow
    # Runs security_reviewer and performance_reviewer concurrently.
    parallel = Parallel(branches=["security_reviewer", "performance_reviewer"], registry=registry)

    # 4. Execute
    code_snippet = "def process_data(data):\n    return [x * 2 for x in data]"
    user_prompt = f"Review this Python function:\n{code_snippet}"
    task = Task.create_infer(prompt=user_prompt)

    print("🟢 Executing Parallel Flow (reviews will execute concurrently)...")
    result = await parallel.execute(task)

    print("\n" + "-" * 50)
    print("🏁 Parallel Execution Results")
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
    perf_agent.stop()
    sec_agent.stop()
    registry.stop()


if __name__ == "__main__":
    if LLM_PROVIDER == "mock":
        print("💡 Running with lightweight CustomMockLLM (offline-safe).")
    asyncio.run(main())
