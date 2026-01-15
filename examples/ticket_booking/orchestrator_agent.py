import os

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.llms.api import OpenAILLM

load_dotenv("./endpoints.env")


AGENT_CARD = {
    "url": os.getenv("ORCHESTRATOR_AGENT_URL"),
    "name": "orchestrator_agent",
    "description": "Orchestrates the ticket booking process",
}

# Replace OpenAI API LLM with the one you want to use
llm = OpenAILLM(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-5")


class OrchestratorAgent(Agent):
    def get_user_input(self, query: str) -> str:
        response = self.llm.invoke(query)

        return response.content


agent = OrchestratorAgent(
    card=AGENT_CARD,  # pass as a dict or as AgentCard object
    transport="http",
    llm=llm,
    registry="http",
    registry_url=os.getenv("REGISTRY_URL"),
)
