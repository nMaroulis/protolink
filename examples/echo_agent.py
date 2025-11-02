#!/usr/bin/env python3
"""
Echo Agent Example

A simple agent that echoes back any message it receives and processes echo tasks.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any, Dict, Optional

from protolink import Agent, Message, Task, TaskStatus
from protolink.discovery import RegistryClient
from protolink.security import (
    APIKeyAuthenticator,
    KeyManager,
    KeyType,
    SecurityConfig,
    setup_security_middleware,
)
from protolink.transport import HTTPTransport

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("echo_agent")


class EchoAgent(Agent):
    """A simple echo agent that responds to messages and processes echo tasks."""

    def __init__(self, agent_id: str, name: str, registry_url: str):
        """Initialize the echo agent.
        
        Args:
            agent_id: Unique identifier for the agent
            name: Human-readable name for the agent
            registry_url: URL of the registry service
        """
        super().__init__(agent_id=agent_id, name=name)
        self.registry_url = registry_url
        self.registry_client = RegistryClient(registry_url)
        self.running = False
        
        # Initialize security
        self.key_manager = KeyManager()
        self._setup_security()
        
        # Initialize transport
        self.transport = HTTPTransport()
        
        # Register message handlers
        self.register_message_handler("echo", self.handle_echo_message)
        self.register_message_handler("ping", self.handle_ping_message)
        
        # Register task handlers
        self.register_task_handler("echo", self.handle_echo_task)
    
    def _setup_security(self) -> None:
        """Set up security components."""
        # Generate or load keys
        try:
            # Try to load existing keys
            self.key_pair = self.key_manager.get_key("echo_agent_key")
            logger.info("Loaded existing key pair")
        except Exception:
            # Generate a new key pair if none exists
            logger.info("Generating new key pair")
            self.key_pair = self.key_manager.generate_key(
                key_id="echo_agent_key",
                key_type=KeyType.RSA,
                key_size=2048,
                metadata={"purpose": "echo_agent_signing"}
            )
        
        # Set up authenticator
        self.authenticator = APIKeyAuthenticator(api_key=os.getenv("AGENT_API_KEY"))
    
    async def start(self) -> None:
        """Start the agent."""
        if self.running:
            logger.warning("Agent is already running")
            return
            
        logger.info(f"Starting {self.name} (ID: {self.agent_id})")
        
        try:
            # Register with the registry
            await self.register()
            
            # Start the agent's main loop
            self.running = True
            
            # Keep the agent running until interrupted
            while self.running:
                try:
                    # Process any pending tasks
                    await self.process_tasks()
                    
                    # Sleep briefly to prevent high CPU usage
                    await asyncio.sleep(1)
                    
                except asyncio.CancelledError:
                    logger.info("Received shutdown signal")
                    break
                except Exception as e:
                    logger.error(f"Error in agent loop: {e}", exc_info=True)
                    await asyncio.sleep(5)  # Prevent tight loop on errors
                    
        except Exception as e:
            logger.error(f"Failed to start agent: {e}", exc_info=True)
            raise
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the agent."""
        if not self.running:
            return
            
        logger.info(f"Stopping {self.name}")
        self.running = False
        
        try:
            # Unregister from the registry
            await self.unregister()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)
    
    async def register(self) -> None:
        """Register the agent with the registry."""
        logger.info(f"Registering with registry at {self.registry_url}")
        
        # Prepare agent info
        agent_info = {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": "A simple echo agent",
            "version": "1.0.0",
            "endpoint": f"http://localhost:8000/agent/{self.agent_id}",
            "capabilities": ["echo", "ping"],
            "public_key": self.key_pair.public_key.decode() if self.key_pair.public_key else None,
            "metadata": {
                "language": "python",
                "framework": "protolink",
            }
        }
        
        # Register with the registry
        try:
            await self.registry_client.register_agent(agent_info)
            logger.info("Successfully registered with registry")
        except Exception as e:
            logger.error(f"Failed to register with registry: {e}")
            raise
    
    async def unregister(self) -> None:
        """Unregister the agent from the registry."""
        logger.info("Unregistering from registry")
        
        try:
            await self.registry_client.unregister_agent(self.agent_id)
            logger.info("Successfully unregistered from registry")
        except Exception as e:
            logger.error(f"Failed to unregister from registry: {e}")
    
    async def handle_echo_message(self, message: Message) -> None:
        """Handle an echo message.
        
        Args:
            message: The received message
        """
        logger.info(f"Received echo message: {message.payload}")
        
        # Create a response message
        response = message.create_response(
            message_type="echo_response",
            payload={"original": message.payload, "echoed": True}
        )
        
        # Send the response
        try:
            await self.send_message(response)
            logger.info("Sent echo response")
        except Exception as e:
            logger.error(f"Failed to send echo response: {e}")
    
    async def handle_ping_message(self, message: Message) -> None:
        """Handle a ping message.
        
        Args:
            message: The received message
        """
        logger.info(f"Received ping from {message.sender_id}")
        
        # Create a pong response
        response = message.create_response(
            message_type="pong",
            payload={"timestamp": str(datetime.utcnow())}
        )
        
        # Send the pong response
        try:
            await self.send_message(response)
            logger.info("Sent pong response")
        except Exception as e:
            logger.error(f"Failed to send pong response: {e}")
    
    async def handle_echo_task(self, task: Task) -> None:
        """Handle an echo task.
        
        Args:
            task: The task to process
        """
        logger.info(f"Processing echo task: {task.task_id}")
        
        try:
            # Update task status to running
            task.status = TaskStatus.RUNNING
            task.progress = 0.5
            await self.update_task(task)
            
            # Simulate some work
            await asyncio.sleep(1)
            
            # Prepare the result
            result = {
                "original": task.parameters,
                "echoed": True,
                "processed_by": self.agent_id,
                "timestamp": str(datetime.utcnow())
            }
            
            # Complete the task
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            await self.complete_task(task)
            
            logger.info(f"Completed echo task: {task.task_id}")
            
        except Exception as e:
            logger.error(f"Failed to process echo task: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            await self.fail_task(task)


async def main():
    """Run the echo agent."""
    # Configuration
    agent_id = os.getenv("AGENT_ID", "echo-agent-1")
    agent_name = os.getenv("AGENT_NAME", "Echo Agent")
    registry_url = os.getenv("REGISTRY_URL", "http://localhost:8000")
    
    # Create and start the agent
    agent = EchoAgent(
        agent_id=agent_id,
        name=agent_name,
        registry_url=registry_url
    )
    
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(agent.stop()))
    
    try:
        await agent.start()
    except asyncio.CancelledError:
        pass
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
