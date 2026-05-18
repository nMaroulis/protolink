import asyncio

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Graph
from protolink.llms import MockLLM, create_llm
from protolink.models import Task


class CustomMockLLM(MockLLM):
    def mock_call(self, last_user_msg: str, system_prompt: str) -> str:
        print(f"DEBUG mock_call: system_prompt={system_prompt[:200]}..., last_user_msg={last_user_msg}")
        # Check for registered name to distinguish between agents
        is_generator = "your registered name in the system is 'generator'" in system_prompt.lower()
        is_evaluator = "your registered name in the system is 'evaluator'" in system_prompt.lower()
        print(f"DEBUG checks: is_generator={is_generator}, is_evaluator={is_evaluator}")
        result = ""
        if is_generator:
            result = "Generated Concept: Protolink state machines are excellent for looping."
        elif is_evaluator:
            result = "APPROVED: Quality standards fully satisfied."
        else:
            result = f"[MOCK] Generic output to '{last_user_msg}'"
        print(f"DEBUG mock_returning: {result}")
        return result


mock_llm = CustomMockLLM()

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
    print("🚀 Protolink Flow: Graph State Machine (Cyclic Looping)")
    print("=" * 70)
    print("This example demonstrates how a Graph flow defines complex state machine topologies,")
    print("enabling cyclic loops, dynamic branching, and multi-step reviews.\n")

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)

    # 2. Setup Generator and Evaluator Agents
    gen_agent = Agent(
        card={
            "name": "generator",
            "url": "http://localhost:8071",
            "description": "Generates ideas.",
        },
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are a generator. Write an interesting sentence about Protolink.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )

    eval_agent = Agent(
        card={
            "name": "evaluator",
            "url": "http://localhost:8072",
            "description": "Evaluates quality.",
        },
        llm=mock_llm if LLM_PROVIDER == "mock" else create_llm(LLM_PROVIDER, **LLM_ARGS),
        system_prompt="You are an evaluator. Decide if a draft is approved or rejected.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=0,
    )

    gen_agent.start(background=True)
    eval_agent.start(background=True)

    await asyncio.sleep(0.5)

    # 3. Define the Graph State Machine
    graph = Graph(registry=registry)

    # Nodes
    graph.add_node("gen", gen_agent)
    graph.add_node("eval", eval_agent)

    # Entry point
    graph.set_entry_point("gen")

    # Simple sequential edge to evaluation step
    graph.add_edge("gen", "eval")

    # Conditional branching edge based on LLM's evaluation message
    def check_evaluation(t: Task) -> str:
        count = t.metadata.get("gen_count", 0)
        t.metadata["gen_count"] = count + 1

        last_msg = t.get_last_part_content()
        if last_msg and "approved" in str(last_msg).lower():
            print(f"   [Graph Edge] Evaluation Approved on Revision {count}! Moving to completion.")
            return "approved"
        print(f"   [Graph Edge] Evaluation Rejected (Revision {count}). Looping back to generator.")
        return "needs_revision"

    # Define conditional branching routes (matching parameter names in protolink.flows.graph)
    graph.add_conditional_edge(
        from_node="eval", condition_fn=check_evaluation, path_map={"approved": "__END__", "needs_revision": "gen"}
    )

    # 4. Execute the Loop
    user_prompt = "Please generate a perfect sentence about Protolink state machines."
    task = Task.create_infer(prompt=user_prompt)

    print("🟢 Executing Graph Flow...")
    result = await graph.execute(task)

    print("\n" + "-" * 50)
    print("🏁 Graph Loop Completed Successfully")
    print("-" * 50)
    print(f"Total loop iterations: {result.metadata.get('gen_count', 0)}")

    print("\nEntire Task Message Flow:")
    for idx, msg in enumerate(result.messages):
        # Snippet the content to keep it neat
        content = msg.parts[0].content if msg.parts else "No Content"
        if len(content) > 80:
            content = content[:77] + "..."
        print(f"  [{idx}] {msg.role.upper()}: {content}")

    print("\nEntire Task Artifact Flow:")
    for idx, art in enumerate(result.artifacts):
        content = art.parts[0].content if art.parts else "No Content"
        print(f"  [{idx}] ARTIFACT: {content}")

    # Cleanup
    print("\n🛑 Shutting down...")
    eval_agent.stop()
    gen_agent.stop()
    registry.stop()


if __name__ == "__main__":
    if LLM_PROVIDER == "mock":
        print("💡 Running with lightweight CustomMockLLM (offline-safe).")
    asyncio.run(main())
