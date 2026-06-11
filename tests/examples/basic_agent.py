"""
Basic Agent Example

Shows how to create a simple agent that echoes user input.
"""

from protolink.agents import Agent

# To Enable LLM Inference import e.g. -> from protolink.llms.api import OpenAILLM
# e.g. a local ollama LLM below uncomment code below and comment llm = None

# from protolink.llms.server import OllamaLLM
# llm = OllamaLLM(base_url="http://localhost:11434", model="gemma4:e4b")  # 8b model for light inference

llm = None

agent_card = {
    "name": "echo-agent",
    "description": "An agent that echoes back your messages",
    "url": "local://echo-agent",
}

# Create the agent
agent = Agent(agent_card, transport="runtime", llm=llm, verbosity=2)


# Add Native tool using the decorator, Input/Output signatures are automatically inferred by Protolink
@agent.tool(name="echo_tool", description="Echoes back your messages")
async def echo_tool(message: str):
    return {"response": f"Echo: {message}"}


print("\n------------- AGENT INFORMATION -------------")
print(f"Agent: {agent.card.name}")
print(f"Description: {agent.card.description}")
print(f"URL: {agent.card.url}")
print("-----------------------------------------------")


def tool_call_example():
    # Test the agent with direct processing
    # The invoke(sync.invoke) is a convenience method that is used to directly invoke the agent to handle a task..
    response = agent.sync.invoke("hello", part_type="tool_call", tool_name="echo_tool", tool_args={"message": "world"})
    print("---------------- RESPONSE -----------------------")
    print(response)


def llm_inference_example(message: str = "Hey, how are you doing today?"):
    response = agent.sync.invoke(message=message, part_type="infer")
    print("---------------- RESPONSE -----------------------")
    print(response)


if __name__ == "__main__":
    tool_call_example()

    # LLM Inference Example (Configure an LLM using the built-in LLM classes)
    # Uncomment the following line to enable LLM inference
    # llm_inference_example(message="Hey, how are you doing today?")
