import os

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.llms.api import OpenAILLM
from protolink.models import Task

load_dotenv("./endpoints.env")


AGENT_CARD = {
    "url": os.getenv("VACATION_ADVISOR_AGENT_URL"),
    "name": "vacation_advisor",
    "description": "Given the User's prefereance, I propose a vacation plan.",
}

# Replace OpenAI API LLM with the one you want to use
llm = OpenAILLM(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-5")


class VacationAdvisorAgent(Agent):
    def handle_task(self, task: Task) -> Task:
        # response = self.llm.invoke(task)

        return


agent = VacationAdvisorAgent(
    card=AGENT_CARD,  # pass as a dict or as AgentCard object
    transport="http",
    llm=llm,
    registry="http",
    registry_url=os.getenv("REGISTRY_URL"),
)
