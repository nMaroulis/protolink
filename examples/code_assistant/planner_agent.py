"""
Planner Agent — The "Brain" of the Coding Assistant (LLM-Only)

This agent is a pure reasoning engine. It has an LLM but NO tools.
When the Orchestrator needs to analyze code, create a plan, or generate
edits, it delegates to this agent via `agent_call` with action `infer`.

═══════════════════════════════════════════════════════════════════════════
PROTOLINK CONCEPTS DEMONSTRATED:
─────────────────────────────────
1. LLM-ONLY AGENT: An agent with an LLM but no tools. It's a pure
   "thinker" that reasons about problems without side effects.
2. LLM-TO-LLM DELEGATION (infer): When the Orchestrator calls this
   agent with action="infer", Protolink routes the prompt to this
   agent's LLM and returns the response. This is the `infer` action
   in action — pun intended.
3. LLM-AGNOSTIC DESIGN: We use `create_llm()` factory, so switching
   from OpenAI to Anthropic to Ollama is a one-line change.
4. CUSTOM handle_task: We override handle_task to add logging,
   showing how agents can customize their behavior while still
   using the parent's inference pipeline.

WHY A SEPARATE REASONING AGENT?
────────────────────────────────
In production coding assistants, the reasoning step is the most
expensive and critical. By isolating it:
  • You can use a DIFFERENT (cheaper?) LLM for planning vs orchestration
  • You can scale the reasoning agent independently
  • You get a clean separation: brain ≠ hands ≠ coordinator
═══════════════════════════════════════════════════════════════════════════
"""

import os

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.llms.factory import create_llm

# ─────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────
# This prompt shapes the Planner's "personality" and output format.
# In Protolink, this is APPENDED to the built-in system prompt that
# already explains agent_call, tool_call, and A2A protocol mechanics.
# So we only need to define the agent's ROLE, not the protocol.
# ─────────────────────────────────────────────────────────────────────────
PLANNER_SYSTEM_PROMPT = """You are an expert software engineer and code planner.

Your role is to ANALYZE coding tasks and GENERATE precise code modifications.
You do NOT have access to the filesystem — another agent (the Coder) handles that.

When asked to ANALYZE a task, respond with:
1. **Understanding**: What the user wants to achieve
2. **Files Involved**: Which files likely need changes
3. **Plan**: Step-by-step plan with specific actions

When given file contents and asked to GENERATE changes, respond with:
1. **Analysis**: Brief assessment of the current code
2. **Changes**: The complete, updated file content ready to be written
3. **Summary**: What was changed and why

IMPORTANT RULES:
- Always provide COMPLETE file contents when generating changes (not just diffs)
- Be precise with indentation and formatting
- Preserve existing functionality unless explicitly asked to change it
- Add clear, helpful docstrings and comments
- Follow Python best practices (PEP 8, PEP 257)
"""


def create_planner_agent(
    registry: Registry | None = None,
    llm_provider: str = "ollama",
    **kwargs,
) -> Agent:
    """
    Create and configure the Planner Agent.

    The Planner is a pure LLM agent — it has a "brain" but no "hands".
    Other agents call it via `agent_call` with action `infer` to get
    reasoning, analysis, and code generation.

    Parameters
    ----------
    registry : Registry, optional
        The agent registry for discovery
    llm_provider : str
        e.g. "ollama", "openai", "anthropic", "gemini"
    **kwargs
        Additional arguments passed to the LLM constructor
        (e.g., api_key, model, base_url)
    """

    # ─── Create the LLM ──────────────────────────────────────────────
    # Protolink's factory pattern makes LLM creation a one-liner.
    # Swap providers by changing a single string:
    #   create_llm("openai")      → GPT-4o
    #   create_llm("anthropic")   → Claude 3.5 Sonnet
    #   create_llm("ollama")      → Local Llama3
    #   create_llm("gemini")      → Google Gemini
    # ──────────────────────────────────────────────────────────────────
    llm = create_llm(llm_provider, **kwargs)

    # ─── Custom Agent Subclass (optional) ─────────────────────────────
    # We subclass Agent to add logging. This is OPTIONAL — you could
    # use Agent directly. But subclassing lets you hook into the
    # task lifecycle for observability, metrics, etc.
    # ──────────────────────────────────────────────────────────────────
    class PlannerAgent(Agent):
        async def handle_task(self, task):
            """Override to add logging around the inference call."""
            content = task.get_last_part_content() if task.messages else "No prompt"

            # Handle both string (text part) and dict (infer part) content
            if isinstance(content, dict):
                prompt = content.get("prompt", str(content))
            else:
                prompt = str(content)

            # Truncate for display
            preview = prompt[:120].replace("\n", " ") if prompt else ""
            print(f"\n   🧠 [planner] infer called: {preview}...")

            # Delegate to parent's handle_task, which invokes the LLM
            result = await super().handle_task(task)

            response_content = result.get_last_part_content() if result else "No response"
            response_str = str(response_content)
            resp_preview = response_str[:100].replace("\n", " ") if response_str else ""
            print(f"   🧠 [planner] → {resp_preview}...")

            return result

    # ─── Create the Agent Instance ────────────────────────────────────
    # Notice: We pass `llm` but define NO tools.
    # This agent is pure reasoning — it thinks, but cannot act.
    # ──────────────────────────────────────────────────────────────────
    agent = PlannerAgent(
        card={
            "name": "planner",
            "description": (
                "Expert code planner and analyzer. Analyzes coding tasks, "
                "creates implementation plans, reviews code, and generates "
                "precise code modifications. Ask this agent for reasoning "
                "about code changes."
            ),
            "url": os.getenv("PLANNER_AGENT_URL", "http://localhost:8020"),
        },
        transport="http",
        registry=registry,
        llm=llm,
        system_prompt=PLANNER_SYSTEM_PROMPT,
    )
    agent.transport.timeout = 120

    return agent


# ---------------------------------------------------------------------------
# Standalone execution (for distributed deployment)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from protolink.discovery import Registry

    registry = Registry(
        url=os.getenv("REGISTRY_URL", "http://localhost:9000"),
        transport="http",
    )

    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    agent = create_planner_agent(registry, llm_provider)
    print(f"Planner Agent running at {agent.card.url}")
    print("Press Ctrl+C to stop")
    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()
