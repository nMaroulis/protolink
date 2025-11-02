"""End-to-end tests for the Protolink A2A library."""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from protolink import Agent, Message, Task, TaskStatus
from protolink.discovery.registry import Registry, app as registry_app
from protolink.security import APIKeyAuthenticator, SecurityConfig, setup_security_middleware
from protolink.transport import HTTPTransport

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_API_KEY = "test-api-key"
REGISTRY_HOST = "127.0.0.1"
REGISTRY_PORT = 8000
REGISTRY_URL = f"http://{REGISTRY_HOST}:{REGISTRY_PORT}"


@asynccontextmanager
async def run_registry() -> AsyncGenerator[Tuple[asyncio.subprocess.Process, str], None]:
    """Run the registry server in a separate process."""
    # Create a test registry database
    db_path = Path("test_registry.db")
    if db_path.exists():
        db_path.unlink()
    
    # Create a test registry app
    app = FastAPI()
    app.include_router(registry_app.router)
    
    # Set up security
    security_config = SecurityConfig(
        require_authentication=True,
        authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
    )
    setup_security_middleware(app, security_config)
    
    # Create and configure the registry
    registry = Registry(storage_path=str(db_path))
    app.state.registry = registry
    
    # Start the registry server
    config = uvicorn.Config(
        app,
        host=REGISTRY_HOST,
        port=REGISTRY_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    
    # Run the server in a separate thread
    server_task = asyncio.create_task(server.serve())
    
    # Wait for the server to start
    await asyncio.sleep(1)
    
    try:
        yield server_task, REGISTRY_URL
    finally:
        # Shutdown the server
        server.should_exit = True
        await server_task
        
        # Clean up
        if db_path.exists():
            db_path.unlink()


class TestProtolinkE2E:
    """End-to-end tests for the Protolink A2A library."""
    
    @pytest.mark.asyncio
    async def test_agent_registration_and_discovery(self):
        """Test agent registration and discovery flow."""
        async with run_registry() as (_, registry_url):
            # Create and register agent 1
            agent1 = Agent(
                agent_id="agent-1",
                name="Test Agent 1",
                registry_url=registry_url,
                capabilities=["process_data"],
                authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
            )
            
            # Create and register agent 2
            agent2 = Agent(
                agent_id="agent-2",
                name="Test Agent 2",
                registry_url=registry_url,
                capabilities=["analyze"],
                authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
            )
            
            try:
                # Start both agents
                await agent1.start()
                await agent2.start()
                
                # Register both agents
                await agent1.register()
                await agent2.register()
                
                # Agent 1 should be able to discover Agent 2 by capability
                found_agents = await agent1.discover_agents(capability="analyze")
                assert len(found_agents) == 1
                assert found_agents[0].agent_id == "agent-2"
                
                # Agent 2 should be able to discover Agent 1 by capability
                found_agents = await agent2.discover_agents(capability="process_data")
                assert len(found_agents) == 1
                assert found_agents[0].agent_id == "agent-1"
                
                # Test getting agent info
                agent_info = await agent1.get_agent_info("agent-2")
                assert agent_info.agent_id == "agent-2"
                assert agent_info.name == "Test Agent 2"
                assert "analyze" in agent_info.capabilities
                
            finally:
                # Clean up
                await agent1.shutdown()
                await agent2.shutdown()
    
    @pytest.mark.asyncio
    async def test_message_passing_between_agents(self):
        """Test message passing between two agents."""
        async with run_registry() as (_, registry_url):
            # Create sender agent
            sender = Agent(
                agent_id="sender-1",
                name="Message Sender",
                registry_url=registry_url,
                authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
            )
            
            # Create receiver agent with a message handler
            received_messages = []
            
            async def message_handler(message: Message) -> dict:
                received_messages.append(message)
                return {"status": "received", "message_id": message.message_id}
            
            receiver = Agent(
                agent_id="receiver-1",
                name="Message Receiver",
                registry_url=registry_url,
                authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
            )
            
            # Add message handler to receiver
            receiver.add_message_handler("test_message", message_handler)
            
            try:
                # Start both agents
                await sender.start()
                await receiver.start()
                
                # Register both agents
                await sender.register()
                await receiver.register()
                
                # Send a message from sender to receiver
                message = Message(
                    message_id="msg-123",
                    message_type="test_message",
                    sender_id="sender-1",
                    recipient_id="receiver-1",
                    payload={"text": "Hello, world!"},
                )
                
                response = await sender.send_message(
                    recipient_id="receiver-1",
                    message=message,
                )
                
                # Check the response
                assert response["status"] == "received"
                assert response["message_id"] == "msg-123"
                
                # Check the receiver got the message
                await asyncio.sleep(0.5)  # Give some time for the message to be processed
                assert len(received_messages) == 1
                assert received_messages[0].message_id == "msg-123"
                assert received_messages[0].payload == {"text": "Hello, world!"}
                
            finally:
                # Clean up
                await sender.shutdown()
                await receiver.shutdown()
    
    @pytest.mark.asyncio
    async def test_task_processing_flow(self):
        """Test task submission and processing flow."""
        async with run_registry() as (_, registry_url):
            # Create a processor agent with a task handler
            processed_tasks = []
            
            async def process_data_task(task: Task) -> Task:
                # Simulate processing
                task.status = TaskStatus.RUNNING
                task.progress = 0.5
                await asyncio.sleep(0.1)
                
                # Complete the task
                task.status = TaskStatus.COMPLETED
                task.progress = 1.0
                task.result = {
                    "processed": True,
                    "input": task.parameters,
                    "timestamp": time.time(),
                }
                
                processed_tasks.append(task)
                return task
            
            processor = Agent(
                agent_id="processor-1",
                name="Task Processor",
                registry_url=registry_url,
                capabilities=["process_data"],
                authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
            )
            
            # Add task handler to processor
            processor.add_task_handler("process_data", process_data_task)
            
            # Create a client agent
            client = Agent(
                agent_id="client-1",
                name="Client",
                registry_url=registry_url,
                authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
            )
            
            try:
                # Start both agents
                await processor.start()
                await client.start()
                
                # Register both agents
                await processor.register()
                await client.register()
                
                # Create a task
                task = Task(
                    task_id=f"task-{int(time.time())}",
                    task_type="process_data",
                    parameters={"data": [1, 2, 3, 4, 5]},
                    created_by="client-1",
                )
                
                # Submit the task to the processor
                response = await client.create_task(
                    agent_id="processor-1",
                    task=task,
                )
                
                assert "task_id" in response
                task_id = response["task_id"]
                
                # Monitor the task status
                max_attempts = 10
                attempts = 0
                status = "pending"
                task_info = None
                
                while status not in ["completed", "failed", "cancelled"] and attempts < max_attempts:
                    task_info = await client.get_task_status(
                        agent_id="processor-1",
                        task_id=task_id,
                    )
                    
                    status = task_info.get("status")
                    attempts += 1
                    await asyncio.sleep(0.5)
                
                # Check the final status
                assert status == "completed"
                assert task_info["result"]["processed"] is True
                assert task_info["result"]["input"] == {"data": [1, 2, 3, 4, 5]}
                
                # Check the processor processed the task
                assert len(processed_tasks) == 1
                assert processed_tasks[0].task_id == task_id
                
            finally:
                # Clean up
                await processor.shutdown()
                await client.shutdown()
    
    @pytest.mark.asyncio
    async def test_agent_heartbeat_and_cleanup(self):
        """Test agent heartbeat and cleanup of stale agents."""
        async with run_registry() as (_, registry_url):
            # Create a registry client to interact directly with the registry
            registry = Registry()
            
            # Create and register an agent with a short heartbeat interval
            agent = Agent(
                agent_id="heartbeat-agent",
                name="Heartbeat Test Agent",
                registry_url=registry_url,
                heartbeat_interval=1.0,  # 1 second heartbeat
                heartbeat_timeout=2.0,    # 2 seconds until marked as stale
                authenticator=APIKeyAuthenticator(api_key=TEST_API_KEY),
            )
            
            try:
                # Start the agent (this will start the heartbeat loop)
                await agent.start()
                
                # Register the agent
                await agent.register()
                
                # Check that the agent is registered
                agent_info = await registry.get_agent("heartbeat-agent")
                assert agent_info is not None
                assert agent_info.agent_id == "heartbeat-agent"
                
                # Wait for a couple of heartbeats
                await asyncio.sleep(2.5)
                
                # The agent should still be registered
                agent_info = await registry.get_agent("heartbeat-agent")
                assert agent_info is not None
                
                # Stop the agent (this will stop the heartbeat loop)
                await agent.shutdown()
                
                # Wait for the agent to be marked as stale
                await asyncio.sleep(2.5)
                
                # The agent should be marked as inactive
                agent_info = await registry.get_agent("heartbeat-agent")
                assert agent_info is not None
                assert agent_info.status == "inactive"
                
                # Clean up stale agents (older than 1 second)
                await registry.cleanup_stale_agents(timeout=1.0)
                
                # The agent should be removed
                agent_info = await registry.get_agent("heartbeat-agent")
                assert agent_info is None
                
            finally:
                # Make sure the agent is stopped
                if agent.is_running:
                    await agent.shutdown()
