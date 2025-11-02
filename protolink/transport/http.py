"""HTTP/HTTPS transport implementation."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Union

import aiohttp
from pydantic import Field

from .base import Transport, TransportConfig, Endpoint, TransportError, MessageDeliveryError
from ..core.message import Message, MessageType

logger = logging.getLogger(__name__)


class HTTPTransportConfig(TransportConfig):
    """Configuration for HTTP transport."""
    max_connections: int = 100
    keepalive_timeout: float = 30.0
    ttl_dns_cache: int = 300
    enable_compression: bool = True
    max_redirects: int = 5
    headers: Dict[str, str] = Field(
        default_factory=lambda: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Protolink/1.0",
        }
    )


class HTTPTransport(Transport):
    """HTTP/HTTPS transport implementation."""
    
    def __init__(self, config: Optional[HTTPTransportConfig] = None):
        """Initialize the HTTP transport.
        
        Args:
            config: Configuration for the HTTP transport
        """
        super().__init__(config or HTTPTransportConfig())
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None
    
    async def _connect_impl(self) -> None:
        """Establish an HTTP connection pool."""
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(
                limit=self.config.max_connections,
                ttl_dns_cache=self.config.ttl_dns_cache,
                ssl=None if not self.config.ssl_verify else True,
                enable_cleanup_closed=True,
                force_close=False,
            )
            
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                connector_owner=True,
                timeout=aiohttp.ClientTimeout(
                    total=self.config.timeout,
                    connect=self.config.timeout / 2,
                    sock_connect=self.config.timeout / 2,
                    sock_read=self.config.timeout,
                ),
                headers=self.config.headers,
                auto_decompress=True,
                raise_for_status=True,
            )
    
    async def _disconnect_impl(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connector = None
    
    async def _send_message_impl(
        self,
        message: Message,
        endpoint: Optional[Endpoint] = None,
    ) -> None:
        """Send a message over HTTP/HTTPS.
        
        Args:
            message: The message to send
            endpoint: The endpoint to send the message to
            
        Raises:
            MessageDeliveryError: If the message cannot be delivered
        """
        if not self._session or self._session.closed:
            raise TransportError("Not connected to HTTP transport")
        
        if not endpoint:
            raise ValueError("Endpoint is required for HTTP transport")
        
        url = endpoint.url
        headers = self.config.headers.copy()
        
        # Add message metadata to headers
        headers.update({
            "X-Message-ID": message.id,
            "X-Message-Type": str(message.type),
            "X-Sender-ID": message.sender,
            "X-Timestamp": message.timestamp,
        })
        
        # Prepare the request data
        data = message.json()
        
        # Retry logic
        last_error = None
        for attempt in range(self.config.reconnect_attempts):
            try:
                async with self._session.post(
                    url,
                    data=data,
                    headers=headers,
                    compress=self.config.enable_compression,
                    allow_redirects=True,
                    max_redirects=self.config.max_redirects,
                ) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        raise MessageDeliveryError(
                            f"HTTP {response.status}: {error_text}"
                        )
                    
                    # Process the response if needed
                    content_type = response.headers.get('Content-Type', '')
                    if 'application/json' in content_type:
                        return await response.json()
                    return await response.text()
                    
            except asyncio.TimeoutError as e:
                last_error = MessageDeliveryError(f"Request timed out: {e}")
                logger.warning(f"Request timed out (attempt {attempt + 1}/{self.config.reconnect_attempts})")
                
            except aiohttp.ClientError as e:
                last_error = MessageDeliveryError(f"HTTP client error: {e}")
                logger.warning(f"HTTP client error (attempt {attempt + 1}/{self.config.reconnect_attempts}): {e}")
                
            except Exception as e:
                last_error = MessageDeliveryError(f"Unexpected error: {e}")
                logger.exception(f"Unexpected error (attempt {attempt + 1}/{self.config.reconnect_attempts})")
            
            # Exponential backoff
            if attempt < self.config.reconnect_attempts - 1:
                delay = self.config.reconnect_delay * (2 ** attempt)
                await asyncio.sleep(min(delay, 30))  # Cap at 30 seconds
        
        # If we get here, all retries failed
        raise last_error or MessageDeliveryError("Failed to send message")
    
    async def start_server(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        ssl_context: Optional[Any] = None,
    ) -> None:
        """Start an HTTP server to receive messages.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            ssl_context: Optional SSL context for HTTPS
        """
        from aiohttp import web
        
        app = web.Application()
        app.add_routes([web.post("/", self._handle_http_request)])
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(
            runner,
            host=host,
            port=port,
            ssl_context=ssl_context,
            reuse_address=True,
            reuse_port=False,
        )
        
        await site.start()
        logger.info(f"HTTP server started on {host}:{port}")
        
        # Keep the server running
        while True:
            await asyncio.sleep(3600)  # Sleep for an hour
    
    async def _handle_http_request(self, request: Any) -> Any:
        """Handle an incoming HTTP request."""
        from aiohttp import web
        
        try:
            # Parse the message
            try:
                data = await request.json()
                message = Message(**data)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Invalid message format: {e}")
                return web.json_response(
                    {"error": "Invalid message format"},
                    status=400,
                )
            
            # Process the message
            await self._handle_incoming_message(data)
            
            # Return a success response
            return web.json_response(
                {"status": "received", "message_id": message.id},
                status=202,
            )
            
        except Exception as e:
            logger.exception("Error handling HTTP request")
            return web.json_response(
                {"error": str(e)},
                status=500,
            )
