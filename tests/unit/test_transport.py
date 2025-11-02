"""Unit tests for the transport module in the Protolink A2A library."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from protolink import Message, Task
from protolink.transport import (
    HTTPTransport,
    TransportError,
    TransportConfig,
    WebSocketTransport,
)


class TestHTTPTransport:
    """Tests for the HTTPTransport class."""
    
    @pytest.fixture
    def mock_http_client(self):
        """Create a mock HTTP client."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            
            mock_response = AsyncMock()
            mock_session.request.return_value = mock_response
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"status": "ok"})
            
            yield mock_session
    
    @pytest.mark.asyncio
    async def test_send_message_success(self, mock_http_client):
        """Test sending a message successfully."""
        transport = HTTPTransport()
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="recipient-1",
            payload={"key": "value"},
        )
        
        # Mock the response
        mock_response = mock_http_client.request.return_value
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "received"})
        
        # Send the message
        response = await transport.send_message(
            url="http://example.com/api/messages",
            message=message,
            headers={"X-Custom-Header": "value"},
            timeout=10.0,
        )
        
        # Check the request was made correctly
        mock_http_client.request.assert_awaited_once()
        args, kwargs = mock_http_client.request.call_args
        assert args[0] == "POST"
        assert args[1] == "http://example.com/api/messages"
        
        # Check headers
        headers = kwargs["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Custom-Header"] == "value"
        
        # Check the message was serialized correctly
        data = json.loads(kwargs["data"])
        assert data["message_id"] == "msg-123"
        assert data["message_type"] == "test_message"
        assert data["payload"] == {"key": "value"}
        
        # Check the response
        assert response == {"status": "received"}
    
    @pytest.mark.asyncio
    async def test_send_message_error(self, mock_http_client):
        """Test error handling when sending a message."""
        transport = HTTPTransport()
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="recipient-1",
            payload={"key": "value"},
        )
        
        # Mock an error response
        mock_response = mock_http_client.request.return_value
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        
        # Expect a TransportError
        with pytest.raises(TransportError) as exc_info:
            await transport.send_message(
                url="http://example.com/api/messages",
                message=message,
            )
        
        assert "HTTP 500" in str(exc_info.value)
        assert "Internal Server Error" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_create_task_success(self, mock_http_client):
        """Test creating a task successfully."""
        transport = HTTPTransport()
        task = Task(
            task_id="task-123",
            task_type="process_data",
            parameters={"input": "test"},
            created_by="user-1",
        )
        
        # Mock the response
        mock_response = mock_http_client.request.return_value
        mock_response.status = 202
        mock_response.json = AsyncMock(return_value={"task_id": "task-123", "status": "pending"})
        
        # Create the task
        result = await transport.create_task(
            url="http://example.com/api/tasks",
            task=task,
            headers={"X-Request-ID": "req-123"},
            timeout=10.0,
        )
        
        # Check the request was made correctly
        mock_http_client.request.assert_awaited_once()
        args, kwargs = mock_http_client.request.call_args
        assert args[0] == "POST"
        assert args[1] == "http://example.com/api/tasks"
        
        # Check the task was serialized correctly
        data = json.loads(kwargs["data"])
        assert data["task_id"] == "task-123"
        assert data["task_type"] == "process_data"
        assert data["parameters"] == {"input": "test"}
        
        # Check the response
        assert result == {"task_id": "task-123", "status": "pending"}
    
    @pytest.mark.asyncio
    async def test_get_task_status(self, mock_http_client):
        """Test getting task status."""
        transport = HTTPTransport()
        
        # Mock the response
        mock_response = mock_http_client.request.return_value
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "task_id": "task-123",
            "status": "completed",
            "result": {"output": "processed"},
        })
        
        # Get task status
        result = await transport.get_task_status(
            url="http://example.com/api/tasks/task-123",
            headers={"X-Request-ID": "req-456"},
            timeout=5.0,
        )
        
        # Check the request was made correctly
        mock_http_client.request.assert_awaited_once()
        args, kwargs = mock_http_client.request.call_args
        assert args[0] == "GET"
        assert args[1] == "http://example.com/api/tasks/task-123"
        assert kwargs["headers"]["X-Request-ID"] == "req-456"
        
        # Check the response
        assert result == {
            "task_id": "task-123",
            "status": "completed",
            "result": {"output": "processed"},
        }


class TestWebSocketTransport:
    """Tests for the WebSocketTransport class."""
    
    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket connection."""
        with patch('websockets.connect') as mock_connect:
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws
            mock_connect.return_value.__aenter__.return_value = mock_ws
            mock_connect.return_value.__aexit__.return_value = None
            
            # Mock message responses
            mock_ws.recv.side_effect = [
                json.dumps({"type": "welcome", "message": "Connected"}),
                json.dumps({"type": "message", "message_id": "msg-123"}),
                asyncio.CancelledError(),  # To break the receive loop
            ]
            
            yield mock_ws
    
    @pytest.mark.asyncio
    async def test_connect_and_send_message(self, mock_websocket):
        """Test connecting to a WebSocket and sending a message."""
        transport = WebSocketTransport()
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="recipient-1",
            payload={"key": "value"},
        )
        
        # Connect to the WebSocket
        async with await transport.connect("ws://example.com/ws") as ws_conn:
            # Send a message
            await ws_conn.send_message(message)
            
            # Receive a message
            received = await ws_conn.receive_message()
            assert received["type"] == "message"
            assert received["message_id"] == "msg-123"
        
        # Check the WebSocket was connected to
        assert mock_websocket.connect.called
        
        # Check the message was sent
        mock_websocket.send.assert_awaited_once()
        sent_data = json.loads(mock_websocket.send.await_args[0])
        assert sent_data["message_id"] == "msg-123"
        assert sent_data["message_type"] == "test_message"
    
    @pytest.mark.asyncio
    async def test_websocket_reconnect(self, mock_websocket):
        """Test WebSocket reconnection logic."""
        # Make the first connection attempt fail
        mock_websocket.connect.side_effect = [
            ConnectionError("Connection failed"),
            mock_websocket,  # Second attempt succeeds
        ]
        
        transport = WebSocketTransport(reconnect_attempts=3, reconnect_delay=0.1)
        
        # This should succeed after a retry
        async with await transport.connect("ws://example.com/ws") as ws_conn:
            assert ws_conn is not None
        
        # Should have tried to connect twice
        assert mock_websocket.connect.call_count == 2
    
    @pytest.mark.asyncio
    async def test_websocket_send_error(self, mock_websocket):
        """Test error handling when sending a WebSocket message."""
        # Make send fail
        mock_websocket.send.side_effect = ConnectionError("Send failed")
        
        transport = WebSocketTransport()
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="recipient-1",
            payload={"key": "value"},
        )
        
        async with await transport.connect("ws://example.com/ws") as ws_conn:
            with pytest.raises(TransportError) as exc_info:
                await ws_conn.send_message(message)
            
            assert "Send failed" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_websocket_receive_error(self, mock_websocket):
        """Test error handling when receiving a WebSocket message."""
        # Make recv fail
        mock_websocket.recv.side_effect = [
            json.dumps({"type": "welcome"}),
            ConnectionError("Receive failed"),
        ]
        
        transport = WebSocketTransport()
        
        async with await transport.connect("ws://example.com/ws") as ws_conn:
            with pytest.raises(TransportError) as exc_info:
                await ws_conn.receive_message()
            
            assert "Receive failed" in str(exc_info.value)


class TestTransportConfig:
    """Tests for the TransportConfig class."""
    
    def test_default_config(self):
        """Test creating a transport config with default values."""
        config = TransportConfig()
        
        assert config.timeout == 30.0
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.max_message_size == 1024 * 1024  # 1MB
        assert config.headers == {}
    
    def test_custom_config(self):
        """Test creating a transport config with custom values."""
        config = TransportConfig(
            timeout=60.0,
            max_retries=5,
            retry_delay=2.0,
            max_message_size=10 * 1024 * 1024,  # 10MB
            headers={"X-Custom-Header": "value"},
        )
        
        assert config.timeout == 60.0
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.max_message_size == 10 * 1024 * 1024
        assert config.headers == {"X-Custom-Header": "value"}
    
    def test_config_validation(self):
        """Test validation of transport config values."""
        # Negative timeout
        with pytest.raises(ValueError):
            TransportConfig(timeout=-1.0)
        
        # Negative max_retries
        with pytest.raises(ValueError):
            TransportConfig(max_retries=-1)
        
        # Negative retry_delay
        with pytest.raises(ValueError):
            TransportConfig(retry_delay=-1.0)
        
        # Negative max_message_size
        with pytest.raises(ValueError):
            TransportConfig(max_message_size=-1)
        
        # Invalid headers type
        with pytest.raises(TypeError):
            TransportConfig(headers="not-a-dict")
