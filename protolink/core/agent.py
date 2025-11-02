"""Base Agent class for the A2A protocol implementation.

This module defines the core Agent class that serves as the foundation for
all agents in the Protolink system. Agents can register with a registry,
discover other agents, and communicate via messages.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Type, TypeVar, Union

from pydantic import BaseModel, Field, validator

from protolink.core.message import Message, MessageType
from protolink.core.task import Task, TaskStatus
from protolink.core.artifact import Artifact

logger = logging.getLogger(__name__)

T = TypeVar('T', bound='Agent')

class AgentCapabilities(BaseModel):
    """Defines the capabilities of an agent."""
    can_process: List[str] = Field(
        default_factory=list,
        description="List of task types this agent can process"
    )
    can_provide: List[str] = Field(
        default_factory=list,
        description="List of resource types this agent can provide"
    )

@dataclass
class AgentInfo:
    """Information about a registered agent."""
    agent_id: str
    name: str
    endpoint: str
    capabilities: AgentCapabilities
    metadata: Dict[str, Any] = field(default_factory=dict)

class Agent:
    """Base class for all agents in the A2A protocol.
    
    Agents are the fundamental building blocks of the Protolink system.
    They can register with a registry, discover other agents, and communicate
    via messages.
    """
    
    def __init__(
        self,
        name: str,
        capabilities: Dict[str, List[str]] | None = None,
        registry_endpoint: str | None = None,
        agent_id: str | None = None,
    ):
        """Initialize a new agent.
        
        Args:
            name: A human-readable name for the agent
            capabilities: Dictionary of capabilities (e.g., {"can_process": ["task1", "task2"]})
            registry_endpoint: URL of the registry service
            agent_id: Optional unique identifier for the agent (auto-generated if not provided)
        """
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex}"
        self.name = name
        self.registry_endpoint = registry_endpoint
        self._capabilities = AgentCapabilities(**(capabilities or {}))
        self._message_handlers = {}
        self._task_handlers = {}
        
        # Register default message handlers
        self.register_message_handler(MessageType.PING, self._handle_ping)
        self.register_message_handler(MessageType.TASK_REQUEST, self._handle_task_request)
    
    @property
    def capabilities(self) -> AgentCapabilities:
        """Get the agent's capabilities."""
        return self._capabilities
    
    def register_message_handler(
        self,
        message_type: Union[str, MessageType],
        handler: callable,
    ) -> None:
        """Register a handler for a specific message type.
        
        Args:
            message_type: Type of message to handle (string or MessageType enum)
            handler: Callable that takes a Message and returns an optional response
        """
        if isinstance(message_type, str):
            message_type = MessageType(message_type)
        self._message_handlers[message_type] = handler
    
    def register_task_handler(
        self,
        task_type: str,
        handler: callable,
    ) -> None:
        """Register a handler for a specific task type.
        
        Args:
            task_type: Type of task to handle (e.g., "summarize", "translate")
            handler: Callable that takes a Task and returns a TaskResult
        """
        self._task_handlers[task_type] = handler
        if task_type not in self._capabilities.can_process:
            self._capabilities.can_process.append(task_type)
    
    async def start(self) -> None:
        """Start the agent's main event loop."""
        logger.info(f"Starting agent {self.name} ({self.agent_id})")
        # TODO: Implement WebSocket server for agent-to-agent communication
        
    async def stop(self) -> None:
        """Stop the agent and clean up resources."""
        logger.info(f"Stopping agent {self.name} ({self.agent_id})")
        # TODO: Clean up resources, close connections
    
    async def send_message(
        self,
        to_agent_id: str,
        message_type: Union[str, MessageType],
        payload: Dict[str, Any] | None = None,
        **kwargs
    ) -> Dict[str, Any] | None:
        """Send a message to another agent.
        
        Args:
            to_agent_id: ID of the recipient agent
            message_type: Type of message (string or MessageType enum)
            payload: Message payload (must be JSON-serializable)
            **kwargs: Additional message fields
            
        Returns:
            Optional response from the recipient agent
        """
        # TODO: Implement message sending logic
        raise NotImplementedError("Message sending not yet implemented")
    
    async def process_message(self, message: Message) -> Dict[str, Any] | None:
        """Process an incoming message.
        
        Args:
            message: The message to process
            
        Returns:
            Optional response to send back to the sender
        """
        handler = self._message_handlers.get(message.type)
        if handler:
            return await handler(message)
        logger.warning(f"No handler registered for message type: {message.type}")
        return None
    
    async def _handle_ping(self, message: Message) -> Dict[str, Any]:
        """Handle a ping message."""
        return {"status": "pong", "agent_id": self.agent_id, "timestamp": message.timestamp}
    
    async def _handle_task_request(self, message: Message) -> Dict[str, Any] | None:
        """Handle a task request message."""
        task_data = message.payload.get("task", {})
        task = Task(**task_data)
        
        handler = self._task_handlers.get(task.type)
        if not handler:
            logger.warning(f"No handler registered for task type: {task.type}")
            return None
            
        try:
            result = await handler(task)
            return {"status": "success", "result": result.dict() if result else None}
        except Exception as e:
            logger.exception(f"Error processing task {task.id}")
            return {"status": "error", "error": str(e)}
    
    async def register(self, registry_endpoint: str | None = None) -> bool:
        """Register this agent with a registry.
        
        Args:
            registry_endpoint: Optional override for the registry endpoint
            
        Returns:
            bool: True if registration was successful, False otherwise
        """
        # TODO: Implement registry registration
        logger.info(f"Registering agent {self.name} with registry")
        return True
    
    async def discover_agents(
        self,
        capability: str | None = None,
        name: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Discover other agents in the network.
        
        Args:
            capability: Filter agents by capability
            name: Filter agents by name
            
        Returns:
            List of matching agents and their information
        """
        # TODO: Implement agent discovery
        return []
    
    async def execute_task(
        self,
        task_type: str,
        parameters: Dict[str, Any],
        target_agent_id: str | None = None,
    ) -> Any:
        """Execute a task, either locally or by delegating to another agent.
        
        Args:
            task_type: Type of task to execute
            parameters: Task parameters
            target_agent_id: Optional ID of the agent to execute the task
            
        Returns:
            Task result
        """
        if not target_agent_id:
            # Execute locally if no target agent is specified
            handler = self._task_handlers.get(task_type)
            if not handler:
                raise ValueError(f"No handler registered for task type: {task_type}")
            return await handler(Task(type=task_type, parameters=parameters))
        else:
            # Delegate to another agent
            message = Message(
                sender=self.agent_id,
                receiver=target_agent_id,
                type=MessageType.TASK_REQUEST,
                payload={
                    "task": {
                        "id": f"task_{uuid.uuid4().hex}",
                        "type": task_type,
                        "parameters": parameters,
                    }
                },
            )
            response = await self.send_message(
                to_agent_id=target_agent_id,
                message_type=MessageType.TASK_REQUEST,
                payload=message.payload,
            )
            return response.get("result") if response else None
