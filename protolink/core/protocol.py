"""Core A2A protocol implementation.

This module implements the core logic of the A2A protocol, including
message routing, task management, and communication between agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel, Field, ValidationError

from .message import Message, MessageType
from .task import Task, TaskResult, TaskStatus
from .artifact import Artifact

logger = logging.getLogger(__name__)

T = TypeVar('T', bound='Protocol')

class ProtocolError(Exception):
    """Base class for protocol-related errors."""
    pass


class ProtocolConfig(BaseModel):
    """Configuration for the A2A protocol."""
    
    # Agent settings
    agent_id: str = Field(
        ...,
        description="Unique identifier for this agent"
    )
    agent_name: str = Field(
        ...,
        description="Human-readable name for this agent"
    )
    
    # Registry settings
    registry_endpoint: Optional[str] = Field(
        default=None,
        description="URL of the registry service"
    )
    heartbeat_interval: int = Field(
        default=30,
        description="Interval in seconds between heartbeats"
    )
    
    # Communication settings
    max_message_size: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="Maximum size of a single message in bytes"
    )
    request_timeout: int = Field(
        default=30,
        description="Default timeout for requests in seconds"
    )
    
    # Security settings
    require_message_signing: bool = Field(
        default=False,
        description="Whether to require message signing"
    )
    allowed_agents: Optional[List[str]] = Field(
        default=None,
        description="List of agent IDs allowed to communicate with this agent"
    )


class Protocol:
    """Core implementation of the A2A protocol.
    
    This class handles the core protocol logic, including message routing,
    task management, and communication between agents.
    """
    
    def __init__(self, config: ProtocolConfig):
        """Initialize the protocol with the given configuration."""
        self.config = config
        self.message_handlers: Dict[Union[str, MessageType], Callable] = {}
        self.task_handlers: Dict[str, Callable] = {}
        self.connected = False
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._message_queue: asyncio.Queue = asyncio.Queue()
        
        # Register default message handlers
        self.register_message_handler(MessageType.PING, self._handle_ping)
        self.register_message_handler(MessageType.TASK_REQUEST, self._handle_task_request)
        self.register_message_handler(MessageType.TASK_RESPONSE, self._handle_task_response)
    
    async def start(self) -> None:
        """Start the protocol."""
        if self.connected:
            return
        
        logger.info(f"Starting protocol for agent {self.config.agent_name} ({self.config.agent_id})")
        
        # Start background tasks
        self._message_processor_task = asyncio.create_task(self._process_messages())
        
        # Register with the registry if configured
        if self.config.registry_endpoint:
            await self._register_with_registry()
        
        self.connected = True
    
    async def stop(self) -> None:
        """Stop the protocol and clean up resources."""
        if not self.connected:
            return
        
        logger.info(f"Stopping protocol for agent {self.config.agent_name}")
        
        # Cancel background tasks
        if hasattr(self, '_message_processor_task'):
            self._message_processor_task.cancel()
            try:
                await self._message_processor_task
            except asyncio.CancelledError:
                pass
        
        # Unregister from the registry if configured
        if self.config.registry_endpoint:
            await self._unregister_from_registry()
        
        # Cancel any pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        
        self.connected = False
    
    def register_message_handler(
        self,
        message_type: Union[str, MessageType],
        handler: Callable[[Message], Any],
    ) -> None:
        """Register a handler for a specific message type.
        
        Args:
            message_type: Type of message to handle
            handler: Callable that processes the message and returns a response
        """
        if isinstance(message_type, str):
            message_type = MessageType(message_type)
        self.message_handlers[message_type] = handler
    
    def register_task_handler(
        self,
        task_type: str,
        handler: Callable[[Task], Any],
    ) -> None:
        """Register a handler for a specific task type.
        
        Args:
            task_type: Type of task to handle
            handler: Callable that processes the task and returns a result
        """
        self.task_handlers[task_type] = handler
    
    async def send_message(
        self,
        to_agent_id: str,
        message_type: Union[str, MessageType],
        payload: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Send a message to another agent.
        
        Args:
            to_agent_id: ID of the recipient agent
            message_type: Type of message to send
            payload: Message payload
            **kwargs: Additional message fields
            
        Returns:
            Response from the recipient agent, if any
        """
        if not self.connected:
            raise ProtocolError("Protocol is not connected")
        
        message = Message(
            sender=self.config.agent_id,
            receiver=to_agent_id,
            type=message_type,
            payload=payload or {},
            **kwargs
        )
        
        # For request/response patterns, create a future to await the response
        if message_type in (MessageType.TASK_REQUEST, MessageType.DISCOVER, MessageType.REGISTER):
            future = asyncio.Future()
            self._pending_requests[message.id] = future
            
            try:
                # TODO: Implement actual message sending
                logger.debug(f"Sending message: {message}")
                
                # Simulate a response for now
                if message_type == MessageType.TASK_REQUEST:
                    response = {
                        "status": "received",
                        "task_id": message.payload.get("task", {}).get("id"),
                    }
                    future.set_result(response)
                
                # Wait for the response with timeout
                return await asyncio.wait_for(future, timeout=self.config.request_timeout)
            except asyncio.TimeoutError:
                raise ProtocolError(f"Request timed out after {self.config.request_timeout} seconds")
            finally:
                self._pending_requests.pop(message.id, None)
        else:
            # Fire and forget for non-request messages
            # TODO: Implement actual message sending
            logger.debug(f"Sending fire-and-forget message: {message}")
            return None
    
    async def process_incoming_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process an incoming message.
        
        Args:
            message_data: Raw message data (JSON-serializable dict)
            
        Returns:
            Response to send back to the sender, if any
        """
        try:
            message = Message(**message_data)
        except ValidationError as e:
            logger.error(f"Invalid message format: {e}")
            return {"error": f"Invalid message format: {str(e)}"}
        
        # Check if this is a response to a pending request
        if message.type == MessageType.TASK_RESPONSE and message.correlation_id in self._pending_requests:
            future = self._pending_requests.pop(message.correlation_id)
            if not future.done():
                future.set_result(message.payload)
            return None
        
        # Otherwise, process the message
        await self._message_queue.put(message)
        return None
    
    async def _process_messages(self) -> None:
        """Process incoming messages from the queue."""
        while True:
            try:
                message = await self._message_queue.get()
                await self._handle_message(message)
            except asyncio.CancelledError:
                logger.info("Message processing task cancelled")
                break
            except Exception as e:
                logger.exception(f"Error processing message: {e}")
    
    async def _handle_message(self, message: Message) -> Optional[Dict[str, Any]]:
        """Handle an incoming message.
        
        Args:
            message: The message to handle
            
        Returns:
            Response to send back to the sender, if any
        """
        try:
            logger.debug(f"Processing message: {message}")
            
            # Check if we have a handler for this message type
            handler = self.message_handlers.get(message.type)
            if not handler:
                logger.warning(f"No handler registered for message type: {message.type}")
                return None
            
            # Process the message
            response = await handler(message)
            return response
            
        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            return {"error": str(e)}
    
    async def _handle_ping(self, message: Message) -> Dict[str, Any]:
        """Handle a ping message."""
        return {"status": "pong", "agent_id": self.config.agent_id}
    
    async def _handle_task_request(self, message: Message) -> Dict[str, Any]:
        """Handle a task request message."""
        task_data = message.payload.get("task", {})
        if not task_data:
            return {"error": "No task data provided"}
        
        try:
            task = Task(**task_data)
        except Exception as e:
            logger.error(f"Invalid task data: {e}")
            return {"error": f"Invalid task data: {str(e)}"}
        
        # Find a handler for this task type
        handler = self.task_handlers.get(task.type)
        if not handler:
            return {
                "error": f"No handler registered for task type: {task.type}",
                "task_id": task.id,
            }
        
        # Execute the task
        try:
            result = await handler(task)
            return {
                "status": "success",
                "task_id": task.id,
                "result": result.dict() if hasattr(result, 'dict') else result,
            }
        except Exception as e:
            logger.exception(f"Error executing task {task.id}")
            return {
                "status": "error",
                "task_id": task.id,
                "error": str(e),
            }
    
    async def _handle_task_response(self, message: Message) -> None:
        """Handle a task response message."""
        # This is handled in process_incoming_message
        pass
    
    async def _register_with_registry(self) -> bool:
        """Register this agent with the registry."""
        try:
            response = await self.send_message(
                to_agent_id="registry",
                message_type=MessageType.REGISTER,
                payload={
                    "agent_id": self.config.agent_id,
                    "name": self.config.agent_name,
                    "capabilities": list(self.task_handlers.keys()),
                },
            )
            return response.get("status") == "success"
        except Exception as e:
            logger.error(f"Failed to register with registry: {e}")
            return False
    
    async def _unregister_from_registry(self) -> bool:
        """Unregister this agent from the registry."""
        try:
            response = await self.send_message(
                to_agent_id="registry",
                message_type=MessageType.UNREGISTER,
                payload={"agent_id": self.config.agent_id},
            )
            return response.get("status") == "success"
        except Exception as e:
            logger.error(f"Failed to unregister from registry: {e}")
            return False
