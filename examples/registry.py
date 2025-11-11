"""
Registry Example

Shows how to use the Registry for agent discovery.
"""
from protolink.models import AgentCard, Task
from protolink.discovery import Registry
from protolink.agent import Agent

class DataAgent(Agent):
    """Agent that processes data."""
    
    def __init__(self):
        card = AgentCard(
            name="data-agent",
            description="Processes and analyzes data",
            url="http://localhost:8001",
            capabilities={"streaming": False, "tasks": True, "data_analysis": True}
        )
        super().__init__(card)
    
    def handle_task(self, task: Task) -> Task:
        return task.complete("Data processed successfully")


class ChatAgent(Agent):
    """Agent for conversations."""
    
    def __init__(self):
        card = AgentCard(
            name="chat-agent",
            description="Conversational AI agent",
            url="http://localhost:8002",
            capabilities={"streaming": True, "tasks": True, "chat": True}
        )
        super().__init__(card)
    
    def handle_task(self, task: Task) -> Task:
        return task.complete("I'm here to chat!")


class CodeAgent(Agent):
    """Agent for code generation."""
    
    def __init__(self):
        card = AgentCard(
            name="code-agent",
            description="Generates and reviews code",
            url="http://localhost:8003",
            capabilities={"streaming": False, "tasks": True, "code_generation": True}
        )
        super().__init__(card)
    
    def handle_task(self, task: Task) -> Task:
        return task.complete("def hello(): return 'Hello World'")


def main():
    # Create agents
    data_agent = DataAgent()
    chat_agent = ChatAgent()
    code_agent = CodeAgent()
    
    # Create registry
    registry = Registry()
    
    # Register all agents
    print("=== Agent Registry Demo ===\n")
    print("Registering agents...")
    registry.register_agent(data_agent.get_agent_card())
    registry.register_agent(chat_agent.get_agent_card())
    registry.register_agent(code_agent.get_agent_card())
    print(f"Total agents registered: {registry.count()}\n")
    
    # Discover all agents
    print("All agents in registry:")
    all_agents = registry.discover_agents()
    for agent in all_agents:
        print(f"  - {agent.name}: {agent.description}")
        print(f"    URL: {agent.url}")
        print(f"    Capabilities: {agent.capabilities}")
    print()
    
    # Find agents with streaming capability
    print("Agents with streaming capability:")
    streaming_agents = registry.discover_agents(filter_by={"capabilities.streaming": True})
    for agent in streaming_agents:
        print(f"  - {agent.name}")
    print()
    
    # Get specific agent by name
    print("Getting specific agent by name:")
    agent = registry.get_agent("code-agent")
    if agent:
        print(f"  Found: {agent.name} - {agent.description}")
    print()
    
    # List all agent URLs
    print("All agent URLs:")
    urls = registry.list_agents()
    for url in urls:
        print(f"  - {url}")
    print()
    
    # Unregister an agent
    print("Unregistering 'data-agent'...")
    registry.unregister_agent("data-agent")
    print(f"Agents remaining: {registry.count()}")
    remaining = registry.discover_agents()
    for agent in remaining:
        print(f"  - {agent.name}")


if __name__ == "__main__":
    main()