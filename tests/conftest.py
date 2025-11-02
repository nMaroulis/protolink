"""Test configuration and fixtures for the Protolink A2A library."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protolink import Agent, Message, Task, TaskStatus
from protolink.discovery.registry import Registry, RegistryClient, app as registry_app
from protolink.security import (
    APIKeyAuthenticator,
    AuthToken,
    KeyManager,
    KeyPair,
    KeyType,
    SecurityConfig,
    SecurityMiddleware,
    setup_security_middleware,
)
from protolink.transport import HTTPTransport

# Configure logging for tests
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Fixtures for Test Setup ---

@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create and return a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


# --- Registry Fixtures ---

@pytest.fixture
def registry_config(temp_dir: Path) -> Dict[str, Any]:
    """Return configuration for the registry."""
    return {
        "host": "127.0.0.1",
        "port": 8000,
        "debug": True,
        "storage_path": str(temp_dir / "registry.db"),
        "api_key": "test-api-key",
    }


@pytest.fixture
def registry_app_fixture(registry_config: Dict[str, Any]) -> FastAPI:
    """Create a FastAPI app with the registry routes."""
    # Create a fresh registry instance
    registry = Registry(storage_path=registry_config["storage_path"])
    
    # Create a new FastAPI app
    app = FastAPI()
    app.include_router(registry_app.router)
    app.state.registry = registry
    
    # Set up security middleware
    security_config = SecurityConfig(
        require_authentication=True,
        authenticator=APIKeyAuthenticator(api_key=registry_config["api_key"]),
    )
    setup_security_middleware(app, security_config)
    
    return app


@pytest.fixture
def registry_client(registry_app_fixture: FastAPI) -> TestClient:
    """Return a test client for the registry API."""
    return TestClient(registry_app_fixture)


@pytest_asyncio.fixture
async def registry(registry_config: Dict[str, Any]) -> AsyncGenerator[Registry, None]:
    """Create and return a registry instance for testing."""
    registry = Registry(storage_path=registry_config["storage_path"])
    await registry.initialize()
    yield registry
    await registry.close()


# --- Agent Fixtures ---

@pytest.fixture
def agent_config() -> Dict[str, Any]:
    """Return configuration for a test agent."""
    return {
        "agent_id": "test-agent-1",
        "name": "Test Agent",
        "registry_url": "http://localhost:8000",
        "api_key": "test-api-key",
    }


@pytest_asyncio.fixture
async def test_agent(agent_config: Dict[str, Any]) -> AsyncGenerator[Agent, None]:
    """Create and return a test agent instance."""
    agent = Agent(
        agent_id=agent_config["agent_id"],
        name=agent_config["name"],
        registry_url=agent_config["registry_url"],
    )
    
    # Set up security
    agent.authenticator = APIKeyAuthenticator(api_key=agent_config["api_key"])
    
    # Start the agent
    await agent.initialize()
    
    yield agent
    
    # Clean up
    await agent.shutdown()


# --- Security Fixtures ---

@pytest.fixture
def key_manager() -> KeyManager:
    """Return a key manager for testing."""
    return KeyManager()


@pytest.fixture
def test_key_pair(key_manager: KeyManager) -> KeyPair:
    """Generate a test key pair."""
    return key_manager.generate_key(
        key_id="test-key",
        key_type=KeyType.RSA,
        key_size=2048,
    )


@pytest.fixture
def security_config() -> SecurityConfig:
    """Return a security configuration for testing."""
    return SecurityConfig(
        require_authentication=True,
        require_signature=True,
        authenticator=APIKeyAuthenticator(api_key="test-api-key"),
    )


# --- Transport Fixtures ---

@pytest.fixture
def http_transport() -> HTTPTransport:
    """Return an HTTP transport instance for testing."""
    return HTTPTransport()


# --- Test Data ---

@pytest.fixture
def sample_message() -> Message:
    """Return a sample message for testing."""
    return Message(
        message_id="msg-123",
        message_type="test_message",
        sender_id="sender-1",
        recipient_id="recipient-1",
        payload={"key": "value"},
    )


@pytest.fixture
def sample_task() -> Task:
    """Return a sample task for testing."""
    return Task(
        task_id="task-123",
        task_type="test_task",
        parameters={"param1": "value1"},
        created_by="test-user",
    )


# --- Helper Functions ---

def assert_dict_contains(actual: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert that the actual dict contains all items from the expected dict."""
    for key, value in expected.items():
        assert key in actual, f"Key '{key}' not found in {actual}"
        assert actual[key] == value, f"Value for key '{key}' does not match. Expected {value}, got {actual[key]}"
