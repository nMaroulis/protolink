"""
Purpose: Conversation memory and persistence across tasks.

Demonstrates history persistence across sequential calls to the same agent instance.

Demonstrates the difference between stateless agents (`memory="none"`) and persistent agents (`memory="session"`).

Shows how `invoke_sync()` handles session history automatically using a default `session_id`.

Useful for building conversational bots and multi-turn interaction assistants.
"""

from protolink.agents import Agent
from protolink.llms.server import OllamaLLM

# Choose any LLM you want throught the protolink.llms package (API, local etc.)
# For example: from protolink.llms.api import AnthropicLLM, OpenAILLM, GeminiLLM ...
llm = OllamaLLM(base_url="http://localhost:11434", model="gemma4:e4b")  # 8b model for light inference

# Define stateless agent
agent_stateless = Agent(
    card={
        "name": "Stateless Agent",
        "description": "This agent doesn't have memory of past conversations",
        "url": "local/agent_stateless",
    },
    transport="runtime",
    llm=llm,
)

# Define stateful agent with memory
agent_stateful = Agent(
    card={
        "name": "Stateful Agent",
        "description": "This agent has memory of past conversations",
        "url": "local/agent_stateful",
    },
    transport="runtime",
    llm=llm,
    memory="session",  # Session memory is not reset between tasks
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
        res = agent.invoke_sync(question)
        print(f"Response ({i + 1}): {res}\n")


if __name__ == "__main__":
    # Here after each question the agent starts with an empty history
    print("\nRunning pipeline with stateless Agent")
    run_pipeline(agent_stateless)
    print("\n-----------------------------------------------\n")
    # Here after each question the agent starts with the history of the previous questions
    print("\nRunning pipeline with stateful Agent")
    run_pipeline(agent_stateful)
