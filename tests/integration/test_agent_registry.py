"""Integration tests for agent and registry interaction."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protolink import Agent, Message, Task, TaskStatus
from protolink.discovery.registry import Registry, app as registry_app
from protolink.security import APIKeyAuthenticator, SecurityConfig, setup_security_middleware
from protolink.transport import HTTPTransport


@pytest.fixture
def registry_app_with_auth():
    """Create a test registry app with authentication."""
    app = FastAPI()
    app.include_router(registry_app.router)
    
    # Set up security
    security_config = SecurityConfig(
        require_authentication=True,
        authenticator=APIKeyAuthenticator(api_key="test-api-key"),
    )
    setup_security_middleware(app, security_config)
    
    # Create a test registry
    registry = Registry()
    app.state.registry = registry
    
    return app


@pytest.fixture
def registry_client(registry_app_with_auth):
    """Create a test client for the registry API."""
    return TestClient(registry_app_with_auth)


class TestAgentRegistryIntegration:
    """Integration tests for agent and registry interaction."""
    
    @pytest.mark.asyncio
    async def test_register_agent(self, registry_client):
        """Test registering an agent with the registry."""
        # Create a test agent
        agent = Agent(
            agent_id="test-agent-1",
            name="Test Agent",
            registry_url="http://testserver",
            capabilities=["process_data", "analyze"],
            authenticator=APIKeyAuthenticator(api_key="test-api-key"),
        )
        
        # Mock the HTTP transport
        transport = HTTPTransport()
        transport._client = registry_client
        agent._transport = transport
        
        # Register the agent
        await agent.register()
        
        # Check the agent was registered
        response = registry_client.get("/agents/test-agent-1")
        assert response.status_code == 200
        agent_data = response.json()
        assert agent_data["agent_id"] == "test-agent-1"
        assert agent_data["name"] == "Test Agent"
        assert set(agent_data["capabilities"]) == {"process_data", "analyze"}
    
    @pytest.mark.asyncio
    async def test_discover_agents(self, registry_client):
        """Test discovering agents by capability."""
        # Register some test agents
        agents = [
            {"agent_id": "agent-1", "name": "Processor", "capabilities": ["process_data"]},
            {"agent_id": "agent-2", "name": "Analyzer", "capabilities": ["analyze"]},
            {"agent_id": "agent-3", "name": "Multi", "capabilities": ["process_data", "analyze"]},
        ]
        
        for agent_data in agents:
            response = registry_client.post(
                "/agents",
                json=agent_data,
                headers={"Authorization": "Bearer test-api-key"},
            )
            assert response.status_code == 200
        
        # Create a test agent for discovery
        agent = Agent(
            agent_id="test-client",
            name="Test Client",
            registry_url="http://testserver",
            authenticator=APIKeyAuthenticator(api_key="test-api-key"),
        )
        
        # Mock the HTTP transport
        transport = HTTPTransport()
        transport._client = registry_client
        agent._transport = transport
        
        # Discover agents with capability "process_data"
        found_agents = await agent.discover_agents(capability="process_data")
        
        # Should find agent-1 and agent-3
        assert len(found_agents) == 2
        agent_ids = {a.agent_id for a in found_agents}
        assert "agent-1" in agent_ids
        assert "agent-3" in agent_ids
        
        # Discover agents with capability "analyze"
        found_agents = await agent.discover_agents(capability="analyze")
        
        # Should find agent-2 and agent-3
        assert len(found_agents) == 2
        agent_ids = {a.agent_id for a in found_agents}
        assert "agent-2" in agent_ids
        assert "agent-3" in agent_ids
    
    @pytest.mark.asyncio
    async def test_send_message_between_agents(self, registry_client):
        """Test sending a message from one agent to another through the registry."""
        # Register two test agents
        sender = Agent(
            agent_id="sender-1",
            name="Sender",
            registry_url="http://testserver",
            authenticator=APIKeyAuthenticator(api_key="test-api-key"),
        )
        
        receiver = Agent(
            agent_id="receiver-1",
            name="Receiver",
            registry_url="http://testserver",
            authenticator=APIKeyAuthenticator(api_key="test-api-key"),
        )
        
        # Mock the HTTP transport for both agents
        transport = HTTPTransport()
        transport._client = registry_client
        
        sender._transport = transport
        receiver._transport = transport
        
        # Register both agents
        await sender.register()
        await receiver.register()
        
        # Mock the message handler on the receiver
        received_message = None
        
        async def message_handler(message):
            nonlocal received_message
            received_message = message
            return {"status": "received"}
        
        receiver.add_message_handler("test_message", message_handler)
        
        # Send a message from sender to receiver
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="receiver-1",
            payload={"text": "Hello, world!"},
        )
        
        # In a real scenario, the sender would use the registry to resolve the receiver's endpoint
        # and then send the message directly to that endpoint. For this test, we'll mock that.
        
        # Mock the receiver's endpoint
        receiver_endpoint = "http://receiver-endpoint"
        
        # Mock the registry lookup
        async def mock_send_message(url, message, **kwargs):
            if url == "http://testserver/agents/receiver-1/endpoint":
                return {"endpoint": receiver_endpoint}
            elif url == f"{receiver_endpoint}/messages":
                # Simulate the receiver processing the message
                if hasattr(receiver, 'handle_message'):
                    response = await receiver.handle_message(message)
                    return response
                return {"status": "received"}
            else:
                raise ValueError(f"Unexpected URL: {url}")
        
        with patch.object(transport, 'send_message', side_effect=mock_send_message):
            response = await sender.send_message(
                recipient_id="receiver-1",
                message=message,
            )
        
        # Check the response
        assert response == {"status": "received"}
        
        # Check the receiver got the message
        assert received_message is not None
        assert received_message.message_id == "msg-123"
        assert received_message.sender_id == "sender-1"
        assert received_message.recipient_id == "receiver-1"
        assert received_message.payload == {"text": "Hello, world!"}


class TestTaskManagement:
    """Integration tests for task management between agents."""
    
    @pytest.mark.asyncio
    async def test_create_and_monitor_task(self, registry_client):
        """Test creating a task and monitoring its progress."""
        # Create a test agent with task processing capability
        processor = Agent(
            agent_id="processor-1",
            name="Task Processor",
            registry_url="http://testserver",
            capabilities=["process_data"],
            authenticator=APIKeyAuthenticator(api_key="test-api-key"),
        )
        
        # Mock the HTTP transport
        transport = HTTPTransport()
        transport._client = registry_client
        processor._transport = transport
        
        # Register the processor
        await processor.register()
        
        # Add a task handler to the processor
        async def process_data_task(task):
            # Simulate processing
            task.status = TaskStatus.RUNNING
            task.progress = 0.5
            await asyncio.sleep(0.1)
            
            # Complete the task
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            task.result = {"processed": True, "input": task.parameters}
            return task
        
        processor.add_task_handler("process_data", process_data_task)
        
        # Create a client agent
        client = Agent(
            agent_id="client-1",
            name="Client",
            registry_url="http://testserver",
            authenticator=APIKeyAuthenticator(api_key="test-api-key"),
        )
        client._transport = transport
        
        # Create a task
        task = Task(
            task_id="task-123",
            task_type="process_data",
            parameters={"data": [1, 2, 3, 4, 5]},
            created_by="client-1",
        )
        
        # In a real scenario, the client would use the registry to find a suitable agent
        # and then submit the task to that agent's endpoint. For this test, we'll mock that.
        
        # Mock the processor's endpoint
        processor_endpoint = "http://processor-endpoint"
        
        # Track task status updates
        task_updates = []
        
        async def mock_send_message(url, message, **kwargs):
            if url == "http://testserver/agents/processor-1/endpoint":
                return {"endpoint": processor_endpoint}
            elif url == f"{processor_endpoint}/tasks":
                # Simulate the processor accepting the task
                task_id = message.get("task_id", "task-123")
                
                # In a background task, process the task
                async def process_task():
                    task_data = message
                    task = Task(**task_data)
                    
                    # Simulate task processing
                    task.status = TaskStatus.RUNNING
                    task_updates.append(task.model_dump())
                    
                    # Call the task handler
                    if hasattr(processor, 'handle_task'):
                        task = await processor.handle_task(task)
                    
                    task_updates.append(task.model_dump())
                
                asyncio.create_task(process_task())
                
                return {"task_id": task_id, "status": "accepted"}
            
            elif url == f"{processor_endpoint}/tasks/task-123":
                # Return the latest task status
                if task_updates:
                    return task_updates[-1]
                return {"task_id": "task-123", "status": "pending"}
            
            else:
                raise ValueError(f"Unexpected URL: {url}")
        
        with patch.object(transport, 'send_message', side_effect=mock_send_message):
            # Submit the task
            response = await client.create_task(
                agent_id="processor-1",
                task=task,
            )
            
            assert response["status"] == "accepted"
            
            # Monitor the task
            max_attempts = 10
            attempts = 0
            status = "pending"
            
            while status not in ["completed", "failed", "cancelled"] and attempts < max_attempts:
                task_info = await client.get_task_status(
                    agent_id="processor-1",
                    task_id="task-123",
                )
                
                status = task_info.get("status")
                attempts += 1
                await asyncio.sleep(0.1)
            
            # Check the final status
            assert status == "completed"
            assert task_info["result"] == {"processed": True, "input": {"data": [1, 2, 3, 4, 5]}}
