from protolink.transport.transport import Transport
from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.agent.agent import Agent


class RuntimeTransport(Transport):
    """In-memory transport for local agent communication.
    
    Agents communicate directly without network overhead.
    Perfect for testing and local multi-agent setups.
    """
    
    def __init__(self):
        """Initialize in-memory transport."""
        self.agents: dict[str, Agent] = {}
    
    def register_agent(self, agent: Agent) -> None:
        """Register an agent for in-memory communication.
        
        Args:
            agent: Agent instance to register
        """
        self.agents[agent.card.url] = agent
        self.agents[agent.card.name] = agent  # Allow lookup by name too
    
    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the transport.
        
        Args:
            agent_id: Agent URL or name
        """
        if agent_id in self.agents:
            del self.agents[agent_id]
    
    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send task to local agent.
        
        Args:
            agent_url: Agent URL or name
            task: Task to send
            
        Returns:
            Processed task
            
        Raises:
            ValueError: If agent not found
        """
        if agent_url not in self.agents:
            raise ValueError(f"Agent not found: {agent_url}")
        
        agent = self.agents[agent_url]
        return agent.handle_task(task)
    
    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send message to local agent.
        
        Args:
            agent_url: Agent URL or name
            message: Message to send
            
        Returns:
            Response message
        """
        # Create a task with the message
        task = Task.create(message)
        result_task = await self.send_task(agent_url, task)
        
        # Extract response message
        if result_task.messages:
            return result_task.messages[-1]
        
        return Message.agent("No response")
    
    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Get agent card from local agent.
        
        Args:
            agent_url: Agent URL or name
            
        Returns:
            AgentCard
            
        Raises:
            ValueError: If agent not found
        """
        if agent_url not in self.agents:
            raise ValueError(f"Agent not found: {agent_url}")
        
        return self.agents[agent_url].get_agent_card()
    
    def list_agents(self) -> list:
        """List all registered agents.
        
        Returns:
            List of agent URLs
        """
        return list(self.agents.keys())
