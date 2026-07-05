"""
Orchestrator Agent - The "Coordinator" of the Coding Assistant (LLM + Agent Calls)

This is the user-facing agent. It receives coding requests and coordinates
the Planner (for reasoning) and Coder (for file operations) to fulfill them.

═══════════════════════════════════════════════════════════════════════════
PROTOLINK CONCEPTS DEMONSTRATED:
─────────────────────────────────
1. AGENT CALL - BOTH MODES: This agent uses `agent_call` in two ways:
   • `infer`: Asks the Planner to reason about code (LLM-to-LLM)
   • `tool_call`: Tells the Coder to read/write files (tool delegation)
   This is the CORE of Protolink's agent mesh, agents delegating
   to each other over the network using a standard protocol.

2. DYNAMIC DISCOVERY: The Orchestrator doesn't hard-code agent URLs.
   It discovers available agents via the Registry at runtime.
   This means you can add/remove agents without changing any code.

3. LLM-DRIVEN ORCHESTRATION: The Orchestrator's LLM reads its system
   prompt, discovers available agents and their capabilities, and
   DECIDES which agent to call, in what order, with what arguments.
   Protolink handles the routing, HTTP requests, and response parsing.

4. MULTI-STEP WORKFLOWS: The LLM can chain multiple agent_calls
   in sequence (read → plan → write), creating complex workflows
   autonomously, just like a real coding assistant.

HOW IT WORKS UNDER THE HOOD:
────────────────────────────
When the Orchestrator's LLM decides to call another agent, it outputs
a structured response like:
    {
      "type": "agent_call",
      "agent": "planner",
      "action": "infer",
      "payload": {"prompt": "Analyze this code and suggest improvements"}
    }
Protolink intercepts this, resolves "planner" to its URL via the
Registry, sends an HTTP request, gets the response, and feeds it
back to the LLM as an observation. The loop continues until the
LLM produces a "final" response for the user.
═══════════════════════════════════════════════════════════════════════════
"""

import os

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.llms.factory import create_llm

# ─────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT - The Orchestrator's "Playbook"
# ─────────────────────────────────────────────────────────────────────────
# This prompt defines HOW the Orchestrator should coordinate the team.
# It's appended to Protolink's built-in prompt (which explains agent_call
# mechanics), so we focus on the WORKFLOW, not the protocol.
#
# KEY INSIGHT: The LLM reads this prompt + the discovered agent cards
# and autonomously decides how to orchestrate the workflow. We don't
# hard-code the steps, the LLM figures out the right sequence.
# ─────────────────────────────────────────────────────────────────────────
ORCHESTRATOR_SYSTEM_PROMPT = """You are an AI coding assistant coordinator, similar to Claude Code.

Your job is to help users modify, understand, and improve their code by coordinating
a team of specialist agents. You do NOT write code yourself, you delegate to specialists.

YOUR WORKFLOW:
1. **Understand**: When a user asks for a code change, first understand what they want.
2. **Explore**: Use the Coder agent to list files and read relevant code.
3. **Plan**: Ask the Planner agent to analyze the code and create a plan.
4. **Execute**: Based on the plan, use the Coder to read files, ask the Planner to
   generate the updated code, then use the Coder to write the changes.
5. **Verify**: After making changes read the modified files to verify the changes.
6. **Report**: Summarize what was done clearly for the user.

IMPORTANT RULES:
- Always READ files before asking the Planner to modify them (context matters!)
- When the Planner generates new code, write it using the Coder's write_file tool
- If uncertain, explore the workspace first using list_directory and search_in_files
- Provide a clear, concise summary of changes at the end
- If a task is ambiguous, explore first, then make reasonable decisions
"""


def create_orchestrator_agent(
    registry: Registry,
    llm_provider: str = "ollama",
    **kwargs,
) -> Agent:
    """
    Create and configure the Orchestrator Agent.

    The Orchestrator is the "glue" of the system. It has an LLM for
    decision-making and uses `agent_call` to delegate to Planner and Coder.

    Parameters
    ----------
    registry : Registry
        The agent registry for discovery (required - the Orchestrator
        MUST be able to discover other agents)
    llm_provider : str
        e.g. "ollama", "openai", "anthropic", "gemini"
    **kwargs
        Additional arguments for LLM creation
    """

    # ─── Create the LLM ──────────────────────────────────────────────
    # The Orchestrator typically uses the same LLM as the Planner,
    # but you could use a cheaper/faster model here since its job
    # is coordination, not deep reasoning.
    # ──────────────────────────────────────────────────────────────────
    llm = create_llm(llm_provider, **kwargs)
    from protolink.telemetry import LocalTraceTelemetry

    agent = Agent(
        card={
            "name": "orchestrator",
            "description": (
                "AI coding assistant coordinator. Receives user coding requests "
                "and orchestrates specialist agents (Planner for reasoning, "
                "Coder for file operations) to fulfill them."
            ),
            "url": os.getenv("ORCHESTRATOR_URL", "http://localhost:8010"),
        },
        transport="http",
        registry=registry,
        llm=llm,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        verbosity=2,
        telemetry=LocalTraceTelemetry(path=f"{os.getcwd()}/traces.json"),  # Log Telemetry Traces locally
    )
    agent.transport.timeout = 600

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
    agent = create_orchestrator_agent(registry, llm_provider)
    print(f"Orchestrator Agent running at {agent.card.url}")
    print("Press Ctrl+C to stop")
    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()
