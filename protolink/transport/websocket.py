"""WebSocket transport implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set, Union

import aiohttp
import websockets
from pydantic import Field
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
    ConnectionClosedOK,
)

from .base import Transport, TransportConfig, Endpoint, TransportError, MessageDeliveryError
from ..core.message import Message, MessageType

logger = logging.getLogger(__name__)


class WebSocketTransportConfig(TransportConfig):
    """Configuration for WebSocket transport."""
    ping_interval: float = 20.0
    ping_timeout: float = 10.0
    max_queue_size: int = 1000
    max_message_size: int = 16 * 1024 * 1024  # 16MB
    auto_reconnect: bool = True
    reconnect_interval: float = 5.0
    headers: Dict[str, str] = Field(
        default_factory=lambda: {
            "User-Agent": "Protolink/1.0",
        }
    )


class WebSocketTransport(Transport):
    """WebSocket transport implementation."""
    
    def __init__(self, config: Optional[WebSocketTransportConfig] = None):
        """Initialize the WebSocket transport.
        
        Args:
            config: Configuration for the WebSocket transport
        """
        super().__init__(config or WebSocketTransportConfig())
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._send_queue: asyncio.Queue = asyncio.Queue(
            maxsize=self.config.max_queue_size
        )
        self._connected_peers: Set[str] = set()
        self._connection_event = asyncio.Event()
        self._reconnect_lock = asyncio.Lock()
    
    @property
    def is_connected(self) -> bool:
        """Check if the WebSocket is connected."""
        return self._ws is not None and not self._ws.closed
    
    async def _connect_impl(self) -> None:
        """Establish a WebSocket connection."""
        if self.is_connected:
            return
            
        async with self._reconnect_lock:
            if self.is_connected:
                return
                
            # Start the receive task if it's not running
            if not self._receive_task or self._receive_task.done():
                self._receive_task = asyncio.create_task(self._receive_messages())
            
            self._connection_event.clear()
            self._connected = True
    
    async def _disconnect_impl(self) -> None:
        """Close the WebSocket connection."""
        if not self.is_connected:
            return
            
        async with self._reconnect_lock:
            if not self.is_connected:
                return
                
            # Cancel the receive task
            if self._receive_task and not self._receive_task.done():
                self._receive_task.cancel()
                try:
                    await self._receive_task
                except (asyncio.CancelledError, Exception):
                    pass
            
            # Close the WebSocket connection
            if self._ws and not self._ws.closed:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                
            self._ws = None
            self._connected = False
            self._connection_event.clear()
    
    async def connect_to_server(self, url: str) -> None:
        """Connect to a WebSocket server.
        
        Args:
            url: WebSocket server URL (ws:// or wss://)
            
        Raises:
            ConnectionError: If the connection fails
        """
        if self.is_connected:
            await self.disconnect()
            
        try:
            self._ws = await websockets.connect(
                url,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,
                max_size=self.config.max_message_size,
                extra_headers=self.config.headers,
                ssl=None if not self.config.ssl_verify else True,
                open_timeout=self.config.timeout,
                close_timeout=self.config.timeout,
            )
            
            self._connection_event.set()
            logger.info(f"Connected to WebSocket server at {url}")
            
        except Exception as e:
            self._ws = None
            self._connection_event.clear()
            raise ConnectionError(f"Failed to connect to WebSocket server: {e}") from e
    
    async def _receive_messages(self) -> None:
        """Continuously receive messages from the WebSocket."""
        while self._connected:
            try:
                if not self.is_connected:
                    await asyncio.sleep(1)
                    continue
                
                message = await self._ws.recv()
                if isinstance(message, bytes):
                    try:
                        message = message.decode('utf-8')
                    except UnicodeDecodeError:
                        logger.error("Received non-UTF-8 binary message")
                        continue
                
                await self._handle_incoming_message(message)
                
            except (ConnectionClosedOK, ConnectionClosedError) as e:
                logger.warning(f"WebSocket connection closed: {e}")
                await self._handle_disconnect()
                
            except asyncio.CancelledError:
                logger.debug("WebSocket receive task cancelled")
                break
                
            except Exception as e:
                logger.exception(f"Error receiving WebSocket message: {e}")
                await self._handle_disconnect()
    
    async def _handle_disconnect(self) -> None:
        """Handle WebSocket disconnection."""
        self._ws = None
        self._connection_event.clear()
        
        if self.config.auto_reconnect and self._connected:
            await self._reconnect()
    
    async def _reconnect(self) -> None:
        """Attempt to reconnect to the WebSocket server."""
        if not self._connected:
            return
            
        async with self._reconnect_lock:
            if not self._connected or self.is_connected:
                return
                
            retry_count = 0
            max_retries = 10
            
            while retry_count < max_retries and self._connected:
                try:
                    if self._ws:
                        await self._ws.close()
                    
                    # Reconnect with exponential backoff
                    delay = min(
                        self.config.reconnect_interval * (2 ** retry_count),
                        60.0,  # Cap at 60 seconds
                    )
                    
                    logger.info(f"Attempting to reconnect in {delay:.1f} seconds...")
                    await asyncio.sleep(delay)
                    
                    if not self._ws or self._ws.closed:
                        # Re-establish the connection
                        # Note: This assumes the URL was provided when connecting initially
                        # In a real implementation, you'd want to store the connection URL
                        logger.info("Reconnecting to WebSocket server...")
                        await self.connect()
                        return
                        
                except Exception as e:
                    logger.warning(f"Reconnection attempt {retry_count + 1} failed: {e}")
                    retry_count += 1
            
            if retry_count >= max_retries:
                logger.error("Max reconnection attempts reached")
                self._connected = False
    
    async def _send_message_impl(
        self,
        message: Message,
        endpoint: Optional[Endpoint] = None,
    ) -> None:
        """Send a message over WebSocket.
        
        Args:
            message: The message to send
            endpoint: Optional endpoint to send the message to
            
        Raises:
            MessageDeliveryError: If the message cannot be delivered
        """
        if not self.is_connected:
            raise TransportError("Not connected to WebSocket")
            
        if not self._ws or self._ws.closed:
            raise TransportError("WebSocket connection is closed")
        
        try:
            # Wait for the connection to be established
            await self._connection_event.wait()
            
            # Serialize the message
            message_data = message.json()
            
            # Send the message
            await self._ws.send(message_data)
            
        except (ConnectionClosed, ConnectionError) as e:
            await self._handle_disconnect()
            raise MessageDeliveryError("WebSocket connection closed") from e
            
        except asyncio.TimeoutError as e:
            raise MessageDeliveryError("WebSocket send timed out") from e
            
        except Exception as e:
            raise MessageDeliveryError(f"Failed to send WebSocket message: {e}") from e
    
    async def broadcast(self, message: Union[Message, Dict[str, Any]]) -> None:
        """Broadcast a message to all connected peers.
        
        Args:
            message: The message to broadcast
        """
        if not self.is_connected:
            raise TransportError("Not connected to WebSocket")
            
        if isinstance(message, dict):
            message = Message(**message)
            
        message_data = message.json()
        
        # In a real implementation, you would iterate over all connected peers
        # and send the message to each one. This is a simplified version.
        if self._ws and not self._ws.closed:
            try:
                await self._ws.send(message_data)
            except Exception as e:
                logger.error(f"Failed to broadcast message: {e}")
    
    async def start_server(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        ssl_context: Optional[Any] = None,
    ) -> None:
        """Start a WebSocket server.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            ssl_context: Optional SSL context for secure connections
        """
        if self.is_connected:
            await self.disconnect()
        
        async def handler(websocket: websockets.WebSocketServerProtocol, path: str) -> None:
            """Handle incoming WebSocket connections."""
            client_id = id(websocket)
            self._connected_peers.add(str(client_id))
            
            try:
                logger.info(f"New WebSocket connection from {websocket.remote_address}")
                
                async for message in websocket:
                    try:
                        if isinstance(message, bytes):
                            message = message.decode('utf-8')
                        
                        await self._handle_incoming_message(message)
                        
                    except Exception as e:
                        logger.exception(f"Error handling WebSocket message: {e}")
                        
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"WebSocket connection closed: {websocket.remote_address}")
                
            except Exception as e:
                logger.exception(f"WebSocket error: {e}")
                
            finally:
                self._connected_peers.discard(str(client_id))
        
        # Start the WebSocket server
        server = await websockets.serve(
            handler,
            host=host,
            port=port,
            ssl=ssl_context,
            ping_interval=self.config.ping_interval,
            ping_timeout=self.config.ping_timeout,
            max_size=self.config.max_message_size,
            reuse_address=True,
            reuse_port=False,
        )
        
        logger.info(f"WebSocket server started on {host}:{port}")
        
        # Keep the server running
        try:
            await server.wait_closed()
        except asyncio.CancelledError:
            logger.info("WebSocket server shutting down...")
            server.close()
            await server.wait_closed()
            logger.info("WebSocket server stopped")
