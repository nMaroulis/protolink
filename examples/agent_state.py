"""
Purpose: Conversation memory and persistence across tasks.

Demonstrates history persistence across sequential calls to the same agent instance.

Demonstrates the difference between stateless agents (`state=None`) and persistent agents (`state=["conversation"]`).

Shows how `agent.sync.invoke()` handles session history automatically using a default `session_id`.

Useful for building conversational bots and multi-turn interaction assistants.
"""

from protolink import Agent, create_llm


def memory_demo_response(history, _system_prompt):
    """Return deterministic responses that reveal whether history is present."""
    user_messages = [str(message.get("content", "")) for message in history.messages if message.get("role") == "user"]
    current = user_messages[-1] if user_messages else ""
    previous = user_messages[:-1]

    if "capital of greece" in current.lower():
        return "The capital of Greece is Athens."
    if "5+4" in current:
        return "5 + 4 is 9."
    if "before" in current.lower():
        if previous:
            return "Before this, you asked: " + " | ".join(previous)
        return "I do not have earlier questions in this session."
    return "I can answer this deterministic state example."


# Define stateless agent
agent_stateless = Agent(
    card={
        "name": "Stateless Agent",
        "description": "This agent doesn't have memory of past conversations",
        "url": "local/agent_stateless",
    },
    transport="runtime",
    llm=create_llm("mock", response_callback=memory_demo_response),
)

# Define stateful agent with memory
agent_stateful = Agent(
    card={
        "name": "Stateful Agent",
        "description": "This agent has memory of past conversations",
        "url": "local/agent_stateful",
    },
    transport="runtime",
    llm=create_llm("mock", response_callback=memory_demo_response),
    state=["conversation"],  # Session memory is not reset between tasks
)

QUESTIONS = [
    "What is the capital of Greece?",
    "what did i ask before?",
    "What's 5+4?",
    "what are the questions i asked before?",
]


# Loops through the questions and prints the response
def run_pipeline(agent: Agent):
    for i, question in enumerate(QUESTIONS):
        print(f"({i + 1}) Asking question: {question}")
        res = agent.sync.invoke(question)
        print(f"Response ({i + 1}): {res}\n")


if __name__ == "__main__":
    # Here after each question the agent starts with an empty history
    print("\nRunning pipeline with stateless Agent")
    run_pipeline(agent_stateless)
    print("\n-----------------------------------------------\n")
    # Here after each question the agent starts with the history of the previous questions
    print("\nRunning pipeline with stateful Agent")
    run_pipeline(agent_stateful)
