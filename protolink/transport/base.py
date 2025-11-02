"""Base transport interface and common functionality."""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from pydantic import BaseModel, Field

from ..core.message import Message, MessageType

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Message], None]

class TransportError(Exception):
    """Base exception for transport-related errors."""
    pass


class ConnectionError(TransportError):
    """Raised when a connection cannot be established."""
    pass


class MessageDeliveryError(TransportError):
    """Raised when a message cannot be delivered."""
    pass


class TransportConfig(BaseModel):
    """Base configuration for transport implementations."""
    timeout: float = 30.0
    max_message_size: int = 10 * 1024 * 1024  # 10MB
    reconnect_attempts: int = 3
    reconnect_delay: float = 1.0
    ssl_verify: bool = True


@dataclass
class Endpoint:
    """Represents a network endpoint."""
    url: str
    protocol: str
    host: str
    port: int
    path: str = "/"
    secure: bool = False

    @classmethod
    def from_url(cls, url: str) -> Endpoint:
        """Create an Endpoint from a URL string."""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError(f"Invalid URL: {url}")
            
        return cls(
            url=url,
            protocol=parsed.scheme,
            host=parsed.hostname,
            port=parsed.port or (443 if parsed.scheme == 'https' else 80),
            path=parsed.path or "/",
            secure=parsed.scheme in ('https', 'wss')
        )


class Transport(ABC):
    """Abstract base class for transport implementations."""
    
    def __init__(self, config: TransportConfig):
        self.config = config
        self._message_handlers: Dict[Union[str, MessageType], MessageHandler] = {}
        self._connected = False
        self._connection_lock = asyncio.Lock()
    
    @property
    def is_connected(self) -> bool:
        """Check if the transport is connected."""
        return self._connected
    
    async def connect(self) -> None:
        """Establish a connection."""
        if self._connected:
            return
            
        async with self._connection_lock:
            if not self._connected:
                await self._connect_impl()
                self._connected = True
    
    async def disconnect(self) -> None:
        """Close the connection."""
        if not self._connected:
            return
            
        async with self._connection_lock:
            if self._connected:
                await self._disconnect_impl()
                self._connected = False
    
    def register_message_handler(
        self,
        message_type: Union[str, MessageType],
        handler: MessageHandler,
    ) -> None:
        """Register a message handler.
        
        Args:
            message_type: The message type to handle
            handler: The handler function
        """
        self._message_handlers[message_type] = handler
    
    async def send_message(
        self,
        message: Union[Message, Dict[str, Any]],
        endpoint: Optional[Endpoint] = None,
    ) -> None:
        """Send a message.
        
        Args:
            message: The message to send
            endpoint: Optional endpoint to send the message to
            
        Raises:
            MessageDeliveryError: If the message cannot be delivered
        """
        if not self._connected:
            raise TransportError("Not connected")
            
        if isinstance(message, dict):
            message = Message(**message)
            
        try:
            await self._send_message_impl(message, endpoint)
        except Exception as e:
            raise MessageDeliveryError(f"Failed to send message: {e}") from e
    
    async def _handle_incoming_message(self, data: bytes) -> None:
        """Handle an incoming message."""
        try:
            message_dict = json.loads(data)
            message = Message(**message_dict)
            
            # Find a handler for this message type
            handler = self._message_handlers.get(message.type)
            if handler:
                await handler(message)
            else:
                logger.warning(f"No handler registered for message type: {message.type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message: {e}")
        except Exception as e:
            logger.exception(f"Error handling message: {e}")
    
    @abstractmethod
    async def _connect_impl(self) -> None:
        """Implementation-specific connection logic."""
        pass
    
    @abstractmethod
    async def _disconnect_impl(self) -> None:
        """Implementation-specific disconnection logic."""
        pass
    
    @abstractmethod
    async def _send_message_impl(
        self,
        message: Message,
        endpoint: Optional[Endpoint] = None,
    ) -> None:
        """Implementation-specific message sending logic.
        
        Args:
            message: The message to send
            endpoint: Optional endpoint to send the message to
        """
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


class MessageAck(BaseModel):
    """Message acknowledgment."""
    message_id: str = Field(..., description="ID of the message being acknowledged")
    status: str = Field(..., description="Status of the message delivery")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")
