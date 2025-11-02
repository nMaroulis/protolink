#!/usr/bin/env python3
"""
Task Processor Agent Example

An agent that processes various types of tasks and can delegate work to other agents.
"""

import asyncio
import json
import logging
import os
import random
import signal
import sys
from datetime import datetime

from protolink import Agent, Message, Task, TaskStatus, TaskPriority
from protolink.discovery import RegistryClient
from protolink.security import (
    APIKeyAuthenticator,
    KeyManager,
    KeyType,
    SecurityConfig,
    sign_message,
    verify_signature,
)
from protolink.transport import HTTPTransport

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("task_processor")


class TaskProcessorAgent(Agent):
    """A task processor agent that can handle various types of tasks."""

    def __init__(self, agent_id: str, name: str, registry_url: str):
        """Initialize the task processor agent.
        
        Args:
            agent_id: Unique identifier for the agent
            name: Human-readable name for the agent
            registry_url: URL of the registry service
        """
        super().__init__(agent_id=agent_id, name=name)
        self.registry_url = registry_url
        self.registry_client = RegistryClient(registry_url)
        self.running = False
        self.known_agents = {}  # Cache of known agents
        
        # Initialize security
        self.key_manager = KeyManager()
        self._setup_security()
        
        # Initialize transport
        self.transport = HTTPTransport()
        
        # Register message handlers
        self.register_message_handler("task_request", self.handle_task_request)
        self.register_message_handler("task_result", self.handle_task_result)
        self.register_message_handler("ping", self.handle_ping)
        
        # Register task handlers
        self.register_task_handler("process_data", self.handle_process_data_task)
        self.register_task_handler("aggregate_results", self.handle_aggregate_task)
        self.register_task_handler("batch_process", self.handle_batch_process_task)
    
    def _setup_security(self) -> None:
        """Set up security components."""
        # Generate or load keys
        try:
            # Try to load existing keys
            self.key_pair = self.key_manager.get_key("task_processor_key")
            logger.info("Loaded existing key pair")
        except Exception:
            # Generate a new key pair if none exists
            logger.info("Generating new key pair")
            self.key_pair = self.key_manager.generate_key(
                key_id="task_processor_key",
                key_type=KeyType.RSA,
                key_size=2048,
                metadata={"purpose": "task_processor_signing"}
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
                    # Refresh the list of known agents
                    await self.refresh_known_agents()
                    
                    # Process any pending tasks
                    await self.process_tasks()
                    
                    # Sleep briefly to prevent high CPU usage
                    await asyncio.sleep(2)
                    
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
            "description": "A task processor agent that can handle various types of tasks",
            "version": "1.0.0",
            "endpoint": f"http://localhost:8001/agent/{self.agent_id}",
            "capabilities": ["process_data", "aggregate_results", "batch_process"],
            "public_key": self.key_pair.public_key.decode() if self.key_pair.public_key else None,
            "metadata": {
                "language": "python",
                "framework": "protolink",
                "max_concurrent_tasks": 10,
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
    
    async def refresh_known_agents(self) -> None:
        """Refresh the list of known agents from the registry."""
        try:
            agents = await self.registry_client.list_agents()
            self.known_agents = {agent["agent_id"]: agent for agent in agents}
            logger.debug(f"Refreshed known agents: {len(self.known_agents)} agents")
        except Exception as e:
            logger.error(f"Failed to refresh known agents: {e}")
    
    async def handle_ping(self, message: Message) -> None:
        """Handle a ping message.
        
        Args:
            message: The received message
        """
        logger.info(f"Received ping from {message.sender_id}")
        
        # Create a pong response
        response = message.create_response(
            message_type="pong",
            payload={
                "agent_id": self.agent_id,
                "timestamp": str(datetime.utcnow()),
                "status": "active"
            }
        )
        
        # Send the pong response
        try:
            await self.send_message(response)
            logger.info("Sent pong response")
        except Exception as e:
            logger.error(f"Failed to send pong response: {e}")
    
    async def handle_task_request(self, message: Message) -> None:
        """Handle a task request message.
        
        Args:
            message: The received message
        """
        logger.info(f"Received task request from {message.sender_id}")
        
        try:
            # Extract task details from the message
            task_data = message.payload
            task_id = task_data.get("task_id")
            task_type = task_data.get("type")
            parameters = task_data.get("parameters", {})
            
            if not task_id or not task_type:
                raise ValueError("Missing required task fields")
            
            # Create a new task
            task = Task(
                task_id=task_id,
                task_type=task_type,
                parameters=parameters,
                priority=TaskPriority.NORMAL,
                created_by=message.sender_id,
                metadata={"received_via": "message", "source_message_id": message.message_id}
            )
            
            # Add the task to the queue
            await self.add_task(task)
            
            # Send acknowledgment
            ack = message.create_response(
                message_type="task_ack",
                payload={
                    "task_id": task_id,
                    "status": "queued",
                    "timestamp": str(datetime.utcnow())
                }
            )
            
            await self.send_message(ack)
            logger.info(f"Acknowledged task {task_id}")
            
        except Exception as e:
            logger.error(f"Failed to process task request: {e}")
            
            # Send error response
            error_msg = message.create_response(
                message_type="task_error",
                payload={
                    "task_id": message.payload.get("task_id", "unknown"),
                    "error": str(e),
                    "timestamp": str(datetime.utcnow())
                }
            )
            
            try:
                await self.send_message(error_msg)
            except Exception as send_error:
                logger.error(f"Failed to send error response: {send_error}")
    
    async def handle_task_result(self, message: Message) -> None:
        """Handle a task result message from another agent.
        
        Args:
            message: The received message
        """
        logger.info(f"Received task result from {message.sender_id}")
        
        try:
            result = message.payload
            task_id = result.get("task_id")
            status = result.get("status")
            
            if not task_id or not status:
                raise ValueError("Missing required result fields")
            
            # Update the task with the result
            task = await self.get_task(task_id)
            if not task:
                logger.warning(f"Received result for unknown task: {task_id}")
                return
            
            task.status = TaskStatus(status)
            task.result = result.get("result")
            task.progress = 1.0
            
            if status == "completed":
                await self.complete_task(task)
            elif status == "failed":
                task.error = result.get("error")
                await self.fail_task(task)
            
            logger.info(f"Updated task {task_id} with result from {message.sender_id}")
            
        except Exception as e:
            logger.error(f"Failed to process task result: {e}", exc_info=True)
    
    async def handle_process_data_task(self, task: Task) -> None:
        """Handle a data processing task.
        
        Args:
            task: The task to process
        """
        logger.info(f"Processing data task: {task.task_id}")
        
        try:
            # Update task status
            task.status = TaskStatus.RUNNING
            task.progress = 0.1
            await self.update_task(task)
            
            # Extract parameters
            data = task.parameters.get("data")
            operation = task.parameters.get("operation", "uppercase")
            
            if not data:
                raise ValueError("No data provided for processing")
            
            # Process the data
            processed_data = []
            total_items = len(data)
            
            for i, item in enumerate(data):
                # Simulate processing time
                await asyncio.sleep(0.1)
                
                # Apply the operation
                if operation == "uppercase" and isinstance(item, str):
                    processed_item = item.upper()
                elif operation == "reverse" and isinstance(item, str):
                    processed_item = item[::-1]
                elif operation == "square" and isinstance(item, (int, float)):
                    processed_item = item ** 2
                else:
                    processed_item = f"Processed: {item}"
                
                processed_data.append(processed_item)
                
                # Update progress
                progress = min(0.9, 0.1 + (i + 1) / total_items * 0.8)  # Cap at 90%
                task.progress = progress
                await self.update_task(task)
            
            # Prepare the result
            task.result = {
                "processed_data": processed_data,
                "original_length": len(data),
                "processed_length": len(processed_data),
                "operation": operation,
                "processed_by": self.agent_id,
                "timestamp": str(datetime.utcnow())
            }
            
            # Complete the task
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            await self.complete_task(task)
            
            logger.info(f"Completed data processing task: {task.task_id}")
            
        except Exception as e:
            logger.error(f"Failed to process data task: {e}", exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)
            await self.fail_task(task)
    
    async def handle_aggregate_task(self, task: Task) -> None:
        """Handle an aggregation task that combines results from multiple sources.
        
        Args:
            task: The task to process
        """
        logger.info(f"Processing aggregation task: {task.task_id}")
        
        try:
            # Update task status
            task.status = TaskStatus.RUNNING
            task.progress = 0.1
            await self.update_task(task)
            
            # Extract parameters
            subtasks = task.parameters.get("subtasks", [])
            aggregation_type = task.parameters.get("type", "sum")
            
            if not subtasks:
                raise ValueError("No subtasks provided for aggregation")
            
            # Process each subtask (could be delegated to other agents)
            results = []
            total_subtasks = len(subtasks)
            
            for i, subtask in enumerate(subtasks):
                # Simulate processing or delegating subtasks
                await asyncio.sleep(0.5)
                
                # For demonstration, just process locally
                if subtask.get("type") == "sum":
                    result = sum(subtask.get("data", []))
                elif subtask.get("type") == "average":
                    data = subtask.get("data", [])
                    result = sum(data) / len(data) if data else 0
                else:
                    result = f"Processed: {subtask}"
                
                results.append({
                    "subtask_id": subtask.get("id", f"subtask-{i}"),
                    "result": result,
                    "status": "completed"
                })
                
                # Update progress
                progress = min(0.9, 0.1 + (i + 1) / total_subtasks * 0.8)  # Cap at 90%
                task.progress = progress
                await self.update_task(task)
            
            # Aggregate the results
            if aggregation_type == "sum":
                aggregated = sum(r["result"] for r in results if isinstance(r["result"], (int, float)))
            elif aggregation_type == "average":
                values = [r["result"] for r in results if isinstance(r["result"], (int, float))]
                aggregated = sum(values) / len(values) if values else 0
            else:
                aggregated = results
            
            # Prepare the result
            task.result = {
                "aggregated_result": aggregated,
                "subtask_count": len(subtasks),
                "successful_subtasks": len([r for r in results if r["status"] == "completed"]),
                "aggregation_type": aggregation_type,
                "processed_by": self.agent_id,
                "timestamp": str(datetime.utcnow())
            }
            
            # Complete the task
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            await self.complete_task(task)
            
            logger.info(f"Completed aggregation task: {task.task_id}")
            
        except Exception as e:
            logger.error(f"Failed to process aggregation task: {e}", exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)
            await self.fail_task(task)
    
    async def handle_batch_process_task(self, task: Task) -> None:
        """Handle a batch processing task that can be parallelized.
        
        Args:
            task: The task to process
        """
        logger.info(f"Processing batch task: {task.task_id}")
        
        try:
            # Update task status
            task.status = TaskStatus.RUNNING
            task.progress = 0.1
            await self.update_task(task)
            
            # Extract parameters
            items = task.parameters.get("items", [])
            batch_size = min(task.parameters.get("batch_size", 5), 10)  # Max 10 items per batch
            
            if not items:
                raise ValueError("No items provided for batch processing")
            
            # Process items in batches
            results = []
            total_batches = (len(items) + batch_size - 1) // batch_size
            
            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = start_idx + batch_size
                batch = items[start_idx:end_idx]
                
                # Process the batch (in a real scenario, this could be parallelized)
                batch_results = []
                for item in batch:
                    # Simulate processing
                    await asyncio.sleep(0.2)
                    batch_results.append({
                        "item": item,
                        "processed": True,
                        "result": f"Processed: {item}"
                    })
                
                results.extend(batch_results)
                
                # Update progress
                progress = min(0.9, 0.1 + (batch_num + 1) / total_batches * 0.8)  # Cap at 90%
                task.progress = progress
                await self.update_task(task)
            
            # Prepare the result
            task.result = {
                "processed_items": len(results),
                "successful_items": len([r for r in results if r["processed"]]),
                "batch_count": total_batches,
                "batch_size": batch_size,
                "processed_by": self.agent_id,
                "timestamp": str(datetime.utcnow()),
                "sample_results": results[:3]  # Include a few sample results
            }
            
            # Complete the task
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            await self.complete_task(task)
            
            logger.info(f"Completed batch processing task: {task.task_id}")
            
        except Exception as e:
            logger.error(f"Failed to process batch task: {e}", exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)
            await self.fail_task(task)


async def main():
    """Run the task processor agent."""
    # Configuration
    agent_id = os.getenv("AGENT_ID", "task-processor-1")
    agent_name = os.getenv("AGENT_NAME", "Task Processor")
    registry_url = os.getenv("REGISTRY_URL", "http://localhost:8000")
    
    # Create and start the agent
    agent = TaskProcessorAgent(
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
