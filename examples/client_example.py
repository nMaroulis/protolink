#!/usr/bin/env python3
"""
Client Example

A simple client that demonstrates how to interact with the Echo Agent and Task Processor Agent.
"""

import asyncio
import json
import logging
import os
import random
import string
import uuid
from typing import Dict, List, Optional

from protolink import Message, Task, TaskPriority
from protolink.discovery import RegistryClient
from protolink.security import APIKeyAuthenticator
from protolink.transport import HTTPTransport

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("client")


class A2AClient:
    """A simple client for interacting with A2A agents."""
    
    def __init__(self, registry_url: str, api_key: Optional[str] = None):
        """Initialize the client.
        
        Args:
            registry_url: URL of the registry service
            api_key: Optional API key for authentication
        """
        self.registry_url = registry_url
        self.registry_client = RegistryClient(registry_url)
        self.transport = HTTPTransport()
        
        # Set up authentication if API key is provided
        self.authenticator = None
        if api_key:
            self.authenticator = APIKeyAuthenticator(api_key=api_key)
    
    async def list_agents(self) -> List[Dict]:
        """List all registered agents."""
        try:
            agents = await self.registry_client.list_agents()
            logger.info(f"Found {len(agents)} agents:")
            for agent in agents:
                logger.info(f"- {agent['name']} (ID: {agent['agent_id']}, Capabilities: {', '.join(agent.get('capabilities', []))})")
            return agents
        except Exception as e:
            logger.error(f"Failed to list agents: {e}")
            return []
    
    async def find_agent_by_capability(self, capability: str) -> Optional[Dict]:
        """Find an agent with the specified capability.
        
        Args:
            capability: The capability to search for
            
        Returns:
            The first agent with the specified capability, or None if not found
        """
        try:
            agents = await self.registry_client.list_agents()
            for agent in agents:
                if capability in agent.get('capabilities', []):
                    return agent
            return None
        except Exception as e:
            logger.error(f"Failed to find agent with capability '{capability}': {e}")
            return None
    
    async def send_message(self, recipient_id: str, message_type: str, payload: Dict) -> Optional[Dict]:
        """Send a message to an agent.
        
        Args:
            recipient_id: ID of the recipient agent
            message_type: Type of the message
            payload: Message payload
            
        Returns:
            The response from the agent, or None if the request failed
        """
        try:
            # Get agent info from registry
            agent = await self.registry_client.get_agent(recipient_id)
            if not agent:
                logger.error(f"Agent not found: {recipient_id}")
                return None
            
            # Create message
            message = Message(
                message_id=str(uuid.uuid4()),
                message_type=message_type,
                sender_id="client",
                recipient_id=recipient_id,
                payload=payload,
                timestamp=asyncio.get_event_loop().time()
            )
            
            # Send message
            endpoint = f"{agent['endpoint']}/messages"
            headers = {}
            
            # Add authentication if available
            if self.authenticator:
                auth_headers = await self.authenticator.get_auth_headers()
                headers.update(auth_headers)
            
            response = await self.transport.post(
                url=endpoint,
                headers=headers,
                data=message.model_dump_json()
            )
            
            if response.status >= 400:
                logger.error(f"Failed to send message: {response.status} {response.text}")
                return None
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
            return None
    
    async def create_task(self, agent_id: str, task_type: str, parameters: Dict, 
                         priority: TaskPriority = TaskPriority.NORMAL) -> Optional[Dict]:
        """Create a new task for an agent.
        
        Args:
            agent_id: ID of the agent to assign the task to
            task_type: Type of the task
            parameters: Task parameters
            priority: Task priority
            
        Returns:
            The created task, or None if the request failed
        """
        try:
            # Get agent info from registry
            agent = await self.registry_client.get_agent(agent_id)
            if not agent:
                logger.error(f"Agent not found: {agent_id}")
                return None
            
            # Create task
            task_id = f"task-{str(uuid.uuid4())[:8]}"
            task = {
                "task_id": task_id,
                "type": task_type,
                "parameters": parameters,
                "priority": priority.value,
                "created_by": "client"
            }
            
            # Send task request
            endpoint = f"{agent['endpoint']}/tasks"
            headers = {"Content-Type": "application/json"}
            
            # Add authentication if available
            if self.authenticator:
                auth_headers = await self.authenticator.get_auth_headers()
                headers.update(auth_headers)
            
            response = await self.transport.post(
                url=endpoint,
                headers=headers,
                data=json.dumps(task)
            )
            
            if response.status >= 400:
                logger.error(f"Failed to create task: {response.status} {response.text}")
                return None
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error creating task: {e}", exc_info=True)
            return None
    
    async def get_task_status(self, agent_id: str, task_id: str) -> Optional[Dict]:
        """Get the status of a task.
        
        Args:
            agent_id: ID of the agent that has the task
            task_id: ID of the task
            
        Returns:
            The task status, or None if the request failed
        """
        try:
            # Get agent info from registry
            agent = await self.registry_client.get_agent(agent_id)
            if not agent:
                logger.error(f"Agent not found: {agent_id}")
                return None
            
            # Get task status
            endpoint = f"{agent['endpoint']}/tasks/{task_id}"
            headers = {}
            
            # Add authentication if available
            if self.authenticator:
                auth_headers = await self.authenticator.get_auth_headers()
                headers.update(auth_headers)
            
            response = await self.transport.get(
                url=endpoint,
                headers=headers
            )
            
            if response.status >= 400:
                logger.error(f"Failed to get task status: {response.status} {response.text}")
                return None
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error getting task status: {e}", exc_info=True)
            return None


async def run_example():
    """Run the client example."""
    # Configuration
    registry_url = os.getenv("REGISTRY_URL", "http://localhost:8000")
    api_key = os.getenv("API_KEY")
    
    # Create client
    client = A2AClient(registry_url=registry_url, api_key=api_key)
    
    # List available agents
    print("\n=== Listing available agents ===")
    agents = await client.list_agents()
    
    if not agents:
        print("No agents found. Make sure the registry and agents are running.")
        return
    
    # Example 1: Send a message to the echo agent
    print("\n=== Sending a message to the echo agent ===")
    echo_agent = await client.find_agent_by_capability("echo")
    
    if echo_agent:
        print(f"Found echo agent: {echo_agent['name']} (ID: {echo_agent['agent_id']})")
        
        # Send an echo message
        response = await client.send_message(
            recipient_id=echo_agent['agent_id'],
            message_type="echo",
            payload={"text": "Hello from the client!"}
        )
        
        if response:
            print(f"Received response: {response}")
        else:
            print("Failed to get a response from the echo agent")
    else:
        print("No echo agent found. Make sure the echo agent is running and registered.")
    
    # Example 2: Create a data processing task
    print("\n=== Creating a data processing task ===")
    processor_agent = await client.find_agent_by_capability("process_data")
    
    if processor_agent:
        print(f"Found processor agent: {processor_agent['name']} (ID: {processor_agent['agent_id']})")
        
        # Create a task to process some data
        task = await client.create_task(
            agent_id=processor_agent['agent_id'],
            task_type="process_data",
            parameters={
                "data": ["apple", "banana", "cherry", "date", "elderberry"],
                "operation": "uppercase"
            },
            priority=TaskPriority.NORMAL
        )
        
        if task:
            task_id = task.get("task_id")
            print(f"Created task: {task_id}")
            
            # Poll for task completion
            print("Waiting for task to complete...")
            max_attempts = 10
            for attempt in range(max_attempts):
                status = await client.get_task_status(processor_agent['agent_id'], task_id)
                if status:
                    print(f"Task status: {status.get('status')} (progress: {status.get('progress', 0) * 100:.0f}%)")
                    
                    if status.get("status") == "completed":
                        print(f"Task completed! Result: {status.get('result')}")
                        break
                    elif status.get("status") == "failed":
                        print(f"Task failed: {status.get('error')}")
                        break
                
                await asyncio.sleep(1)
            else:
                print("Timed out waiting for task to complete")
        else:
            print("Failed to create task")
    else:
        print("No processor agent found. Make sure the task processor agent is running and registered.")
    
    # Example 3: Create a batch processing task
    print("\n=== Creating a batch processing task ===")
    batch_agent = await client.find_agent_by_capability("batch_process")
    
    if batch_agent:
        print(f"Found batch processor agent: {batch_agent['name']} (ID: {batch_agent['agent_id']})")
        
        # Generate some random data
        items = [f"item-{i}" for i in range(1, 16)]  # 15 items
        
        # Create a batch processing task
        task = await client.create_task(
            agent_id=batch_agent['agent_id'],
            task_type="batch_process",
            parameters={
                "items": items,
                "batch_size": 5  # Process 5 items at a time
            },
            priority=TaskPriority.LOW
        )
        
        if task:
            task_id = task.get("task_id")
            print(f"Created batch task: {task_id}")
            print(f"Processing {len(items)} items in batches of 5...")
            
            # Poll for task completion
            print("Waiting for batch task to complete...")
            max_attempts = 20  # Allow more time for batch processing
            for attempt in range(max_attempts):
                status = await client.get_task_status(batch_agent['agent_id'], task_id)
                if status:
                    progress = status.get('progress', 0) * 100
                    print(f"Batch task status: {status.get('status')} (progress: {progress:.0f}%)")
                    
                    if status.get("status") == "completed":
                        result = status.get('result', {})
                        print(f"Batch task completed!")
                        print(f"Processed {result.get('processed_items', 0)} items in "
                              f"{result.get('batch_count', 0)} batches")
                        print(f"Sample results: {result.get('sample_results')}")
                        break
                    elif status.get("status") == "failed":
                        print(f"Batch task failed: {status.get('error')}")
                        break
                
                await asyncio.sleep(1)
            else:
                print("Timed out waiting for batch task to complete")
        else:
            print("Failed to create batch task")
    else:
        print("No batch processor agent found. Make sure the task processor agent is running and registered.")


if __name__ == "__main__":
    asyncio.run(run_example())
