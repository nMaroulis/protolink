#!/usr/bin/env python3
"""
Code Assistant Demo - Multi-Agent Coding System with Protolink

This script demonstrates building a simplified "Claude Code", a terminal
coding assistant powered by three autonomous agents:

  1. ORCHESTRATOR (LLM) - receives user requests, coordinates the team
  2. PLANNER (LLM)       - analyzes code, creates plans, generates edits
  3. CODER (Tools)       - reads, writes, lists, and searches files

═══════════════════════════════════════════════════════════════════════════
WHAT THIS DEMO SHOWS:
─────────────────────
• agent_call with "infer"    - LLM-to-LLM delegation (Orchestrator → Planner)
• agent_call with "tool_call" - Tool delegation (Orchestrator → Coder)
• Registry Discovery          - Agents find each other dynamically
• LLM-Agnostic Design         - Works with OpenAI, Anthropic, Ollama, etc.
• Separation of Concerns      - Brain (Planner) vs Hands (Coder)
═══════════════════════════════════════════════════════════════════════════

Run with:
    python run.py                              # Interactive mode (Ollama)
    LLM_PROVIDER=openai python run.py          # Interactive mode (OpenAI)
    python run.py "Add docstrings to utils.py"  # Single query mode
"""

import asyncio
import os
import sys
import textwrap

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from coder_agent import create_coder_agent
from orchestrator_agent import create_orchestrator_agent
from planner_agent import create_planner_agent

from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.models import Task

# ─────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:9000")
CLIENT_URL = os.getenv("CLIENT_URL", "http://localhost:8300")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
WORKSPACE_DIR = os.path.join(os.path.dirname(__file__), "workspace")

# LLM kwargs (API keys, base URLs, etc.)
kwargs: dict = {}
api_key: str = ""
if api_key:
    kwargs["api_key"] = api_key

# Ollama-specific config
if LLM_PROVIDER == "ollama":
    kwargs["base_url"] = os.getenv("OLLAMA_URL", "http://localhost:11434")
    kwargs["model"] = os.getenv("OLLAMA_MODEL", "gemma4:e4b")


# ─────────────────────────────────────────────────────────────────────────
# Demo Workspace Setup
# ─────────────────────────────────────────────────────────────────────────
# We create a small Python project for the agents to work on.
# This simulates a real codebase that the coding assistant can modify.
# ─────────────────────────────────────────────────────────────────────────

DEMO_FILES = {
    "main.py": textwrap.dedent('''\
        """Main entry point for the calculator application."""
        from utils import add, subtract, multiply
        from config import APP_NAME, VERSION


        def main():
            print(f"Welcome to {APP_NAME} v{VERSION}")
            print(f"2 + 3 = {add(2, 3)}")
            print(f"10 - 4 = {subtract(10, 4)}")
            print(f"5 * 6 = {multiply(5, 6)}")


        if __name__ == "__main__":
            main()
    '''),
    "utils.py": textwrap.dedent("""\
        def add(a, b):
            return a + b


        def subtract(a, b):
            return a - b


        def multiply(a, b):
            return a * b


        def divide(a, b):
            if b == 0:
                raise ValueError("Cannot divide by zero")
            return a / b


        def power(base, exponent):
            return base ** exponent


        def factorial(n):
            if n < 0:
                raise ValueError("Factorial not defined for negative numbers")
            if n <= 1:
                return 1
            return n * factorial(n - 1)
    """),
    "config.py": textwrap.dedent('''\
        """Application configuration."""

        APP_NAME = "PyCalc"
        VERSION = "1.0.0"
        DEBUG = False
        MAX_HISTORY = 100
    '''),
}


def create_demo_workspace():
    """Create the demo workspace with sample Python files."""
    os.makedirs(WORKSPACE_DIR, exist_ok=True)

    for filename, content in DEMO_FILES.items():
        filepath = os.path.join(WORKSPACE_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                f.write(content)
            print(f"   Created {filename}")
        else:
            print(f"   {filename} already exists (skipping)")


async def main():
    """Run the Code Assistant demo."""

    print("=" * 70)
    print("🤖 CODE ASSISTANT - Protolink Multi-Agent Coding System")
    print("=" * 70)
    print()
    print("Architecture: Orchestrator (LLM) → Planner (LLM) + Coder (Tools)")
    print()

    # Track components for cleanup
    registry = None
    coder = None
    planner = None
    orchestrator = None

    try:
        # ─── Step 1: Create Demo Workspace ────────────────────────────
        print("📂 Setting up demo workspace...")
        create_demo_workspace()
        # Set the workspace dir so the Coder agent knows where to operate
        os.environ["WORKSPACE_DIR"] = WORKSPACE_DIR

        # ─── Step 2: Start Registry ──────────────────────────────────
        # The Registry is Protolink's discovery service. Agents register
        # themselves here, and the Orchestrator queries it to find
        # available agents at runtime.
        print("\n📡 Starting Registry...")
        registry = Registry(url=REGISTRY_URL, transport="http")
        registry.start(background=True)
        print(f"   Registry running at {REGISTRY_URL}")

        # ─── Step 3: Start Coder Agent (Tools-Only) ──────────────────
        # The Coder starts first because it has no dependencies.
        # It registers its tools (read_file, write_file, etc.) with
        # the Registry so the Orchestrator can discover them.
        print("\n🔧 Starting Coder Agent (tools-only, no LLM)...")
        coder = create_coder_agent(registry)
        coder.start(background=True)
        print(f"   Coder running at {coder.card.url}")
        print(f"   Tools: {list(coder.tools.keys())}")

        # ─── Step 4: Start Planner Agent (LLM-Only) ──────────────────
        # The Planner has an LLM for reasoning but no tools.
        # The Orchestrator will call it via agent_call(action="infer")
        # to get analysis and code generation.
        print(f"\n🧠 Starting Planner Agent (LLM: {LLM_PROVIDER})...")
        planner = create_planner_agent(
            registry=registry,
            llm_provider=LLM_PROVIDER,
            **kwargs,
        )
        planner.start(background=True)
        print(f"   Planner running at {planner.card.url}")

        # ─── Step 5: Start Orchestrator Agent (LLM + Agent Calls) ────
        # The Orchestrator is the coordinator. It has an LLM to decide
        # WHAT to do, and uses agent_call to delegate to Planner and Coder.
        print(f"\n🎯 Starting Orchestrator Agent (LLM: {LLM_PROVIDER})...")
        orchestrator = create_orchestrator_agent(
            registry=registry,
            llm_provider=LLM_PROVIDER,
            **kwargs,
        )
        orchestrator.start(background=True)
        print(f"   Orchestrator running at {orchestrator.card.url}")

        # ─── Step 6: Verify Agent Discovery ──────────────────────────
        print("\n🔍 Verifying agent discovery...")
        await asyncio.sleep(1)  # Allow time for registration
        discovered = await orchestrator.discover_agents()
        print(f"   Discovered {len(discovered)} agents:")
        for agent in discovered:
            tools = [s.id for s in agent.skills] if agent.skills else []
            agent_type = "LLM" if agent.capabilities.has_llm else "Tools"
            print(f"   • {agent.name} ({agent_type}): {tools if tools else 'reasoning'}")

        # ─── Step 7: Process User Query ──────────────────────────────
        print("\n" + "=" * 70)
        default_query = "Add docstrings to all functions in utils.py"

        if len(sys.argv) > 1:
            # Command-line argument mode
            user_query = " ".join(sys.argv[1:])
        else:
            # Interactive mode
            print("💬 Welcome to Code Assistant!")
            print(f"   Workspace: {WORKSPACE_DIR}")
            print(f"   Files: {', '.join(DEMO_FILES.keys())}")
            print(f'\n   Default: "{default_query}"')
            user_input = input("\n   > ").strip()
            user_query = user_input if user_input else default_query

        print(f'\n📝 Processing: "{user_query}"')
        print("=" * 70)
        print()

        # ─── Step 8: Send Task to Orchestrator ───────────────────────
        # This is where the magic happens! We create a Task with the
        # user's query and send it to the Orchestrator. The Orchestrator's
        # LLM will then:
        #   1. Call Coder.list_directory() to explore the workspace
        #   2. Call Coder.read_file("utils.py") to get current code
        #   3. Call Planner.infer() to analyze and generate changes
        #   4. Call Coder.write_file("utils.py", new_content) to apply
        #   5. Return a summary to the user
        # All of this happens AUTONOMOUSLY through Protolink's inference
        # loop — we just send one task and get the final result back.
        print("⏳ Orchestrator is working...")
        print("   (watch the agent logs below to see the delegation chain)")
        print()

        # Create and send the task
        client = AgentClient(url=CLIENT_URL, transport="http", timeout=600)
        task = Task.create_infer(prompt=user_query)
        result = await client.send_task(agent_url=orchestrator.card.url, task=task)

        # Display result
        print("\n" + "=" * 70)
        print("✅ RESULT:")
        print("-" * 70)
        print(result.get_last_part_content())
        print("-" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await cleanup(registry, coder, planner, orchestrator)


async def cleanup(registry, coder, planner, orchestrator):
    """Stop all agents and registry."""
    print("\n🛑 Shutting down agents...")

    if orchestrator:
        orchestrator.stop()
    if planner:
        planner.stop()
    if coder:
        coder.stop()
    if registry:
        registry.stop()

    print("   All agents stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
