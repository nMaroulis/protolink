import os
import sys
import time

from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.flows import Pipeline
from protolink.llms.api import OpenAILLM
from protolink.models import Message, Task

load_dotenv(".env")

REGISTRY_URL = "http://localhost:9020"


def main():
    print("=" * 70)
    print("🚀 Structured Flows Example (Semantic Context Injection)")
    print("=" * 70)
    print("This example demonstrates how Protolink's Pipeline automatically")
    print("injects the capabilities of the 'next' agent into the current")
    print("agent's LLM prompt, ensuring semantic alignment between steps.\n")

    # 1. Start Registry
    registry = Registry(url=REGISTRY_URL, transport="http")
    registry.start(background=True)
    print("✅ Registry started")

    # 2. Setup Agent A (Researcher)
    # We use standard LLM agents. No custom handle_task overrides are needed!
    researcher = Agent(
        card={
            "name": "researcher",
            "url": "http://localhost:8021",
            "description": "Expert researcher that gathers comprehensive data on requested topics.",
        },
        llm=OpenAILLM(model="gpt-4o-mini"),
        system_prompt="You are a diligent researcher. Gather facts and present them clearly.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=1,
    )
    researcher.start(background=True)
    print("✅ Researcher agent started")

    # 3. Setup Agent B (Summarizer)
    summarizer = Agent(
        card={
            "name": "summarizer",
            "url": "http://localhost:8022",
            "description": "Expert at synthesizing dense information into clear, concise summaries.",
        },
        llm=OpenAILLM(model="gpt-4o-mini"),
        system_prompt="You are a summarizer. Take the provided text and distill it into 2-3 bullet points.",
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=1,
    )
    summarizer.start(background=True)
    print("✅ Summarizer agent started")

    time.sleep(1)  # wait for registration

    # ==========================================
    # Running Script-based Pipeline Flow
    # ==========================================
    print("\n" + "-" * 40)
    print("🟢 Executing Pipeline Flow")
    print("-" * 40)

    # We define a Pipeline out of agents that executes them sequentially.
    # The pipeline will automatically inject 'summarizer's AgentCard into the 'researcher's prompt!
    pipeline = Pipeline(
        steps=["researcher", "summarizer"],
        registry=registry,
    )

    # Initial user request
    task_p = Task.create(Message.user("Research the Protolink multi-agent framework."))

    # Execute synchronously
    result_p = pipeline.sync.execute(task_p)
    print("\n   [Final Pipeline Output]")
    print(result_p.get_last_part_content())

    # Cleanup
    print("\n🛑 Shutting down...")
    summarizer.stop()
    researcher.stop()
    registry.stop()


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY is not set. Please set it to run this example.")
    else:
        main()
