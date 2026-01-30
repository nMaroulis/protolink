#!/usr/bin/env python3
"""
Vacation Booking Demo - Multi-Agent System

This script demonstrates Protolink's multi-agent capabilities:
- A Coordinator Agent (with LLM) receives user requests
- It delegates to Holiday Advisor (infer), Weather Agent and Hotel Agent (tool_call)
- The inference loop handles tool execution and result aggregation

Run with: python run.py
"""

import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from coordinator_agent import create_coordinator_agent
from holiday_advisor_agent import create_advisor_agent
from hotel_booking_agent import create_hotel_agent
from weather_agent import create_weather_agent

from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.models import Task

# Configuration
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:9000")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

kwargs: dict = {}
# Set API Key manually here, if not set, it will use the environment variable
api_key: str = ""
if api_key:
    kwargs["api_key"] = api_key

# Setup manually for Ollama
base_url: str = "http://localhost:11434"
model: str = "llama3:8b"
if LLM_PROVIDER == "ollama":
    kwargs["base_url"] = os.getenv("OLLAMA_URL", base_url)
    kwargs["model"] = os.getenv("OLLAMA_MODEL", model)


async def main():
    """Run the vacation booking demo."""

    print("=" * 70)
    print("🏖️  VACATION BOOKING DEMO - Protolink Multi-Agent System")
    print("=" * 70)
    print()

    # Track started components for cleanup
    registry = None
    weather_agent = None
    hotel_agent = None
    advisor_agent = None
    coordinator = None

    try:
        # Step 1: Start the Registry
        print("📡 Starting Registry...")
        registry = Registry(url=REGISTRY_URL, transport="http")
        await registry.start()
        print(f"   Registry running at {REGISTRY_URL}")

        # Step 2: Start specialist agents (no LLM - tool only)
        print("\n🌤️  Starting Weather Agent (tool-only)...")
        weather_agent = create_weather_agent(registry)
        await weather_agent.start()
        print(f"   Weather Agent running at {weather_agent.card.url}")

        print("\n🏨 Starting Hotel Agent (tool-only)...")
        hotel_agent = create_hotel_agent(registry)
        await hotel_agent.start()
        print(f"   Hotel Agent running at {hotel_agent.card.url}")

        # Step 3: Start Holiday Advisor (has LLM - for infer action)
        print(f"\n Starting Holiday Advisor (LLM: {LLM_PROVIDER})...")
        advisor_agent = create_advisor_agent(
            registry=registry,
            llm_provider=LLM_PROVIDER,
            **kwargs,
        )
        await advisor_agent.start()
        print(f"   Holiday Advisor running at {advisor_agent.card.url}")

        # Step 4: Start coordinator (with LLM)
        print(f"\n🧠 Starting Coordinator Agent (LLM: {LLM_PROVIDER})...")
        coordinator = create_coordinator_agent(
            registry=registry,
            llm_provider=LLM_PROVIDER,
            **kwargs,
        )
        await coordinator.start()
        print(f"   Coordinator running at {coordinator.card.url}")

        # Step 5: Verify agent discovery
        print("\n🔍 Verifying agent discovery...")
        await asyncio.sleep(1)  # Allow time for registration
        discovered = await coordinator.discover_agents()
        print(f"   Discovered {len(discovered)} agents:")
        for agent in discovered:
            tools = [s.id for s in agent.skills] if agent.skills else []
            has_llm = "LLM" if agent.name in ("holiday_advisor", "coordinator") else "tools"
            print(f"   - {agent.name}: {tools or has_llm}")

        # Step 6: Get user input or use default
        print("\n" + "=" * 70)
        default_query = "Book me a relaxing vacation to Santorini for 5 nights in mid-July 2026"

        if len(sys.argv) > 1:
            user_query = " ".join(sys.argv[1:])
        else:
            print("💬 Enter your vacation request (or press Enter for demo):")
            print(f'   Default: "{default_query}"')
            user_input = input("\n   > ").strip()
            user_query = user_input if user_input else default_query

        print(f'\n📝 Processing: "{user_query}"')
        print("=" * 70)
        print()

        # Step 7: Send task to Coordinator
        print("⏳ Coordinator is working...")
        print("   Step 1: Ask Holiday Advisor (infer) for recommendation")
        print("   Step 2: Check weather (tool_call)")
        print("   Step 3: Book hotel (tool_call)")
        print()

        client = AgentClient(transport=coordinator.transport)
        task = Task.create_infer(prompt=user_query)

        result = await client.send_task(agent_url=coordinator.card.url, task=task)

        print("✅ RESULT:")
        print("-" * 70)
        print(result.get_last_part_content())
        print("-" * 70)

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Cleanup
        await cleanup(registry, weather_agent, hotel_agent, advisor_agent, coordinator)


async def cleanup(registry, weather_agent, hotel_agent, advisor_agent, coordinator):
    """Stop all agents and registry."""
    print("\n🛑 Shutting down agents...")

    if coordinator:
        await coordinator.stop()
    if advisor_agent:
        await advisor_agent.stop()
    if hotel_agent:
        await hotel_agent.stop()
    if weather_agent:
        await weather_agent.stop()
    if registry:
        await registry.stop()

    print("   All agents stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
