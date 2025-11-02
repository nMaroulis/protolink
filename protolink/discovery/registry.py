"""Registry service for agent discovery.

This module implements a registry service that allows agents to register
themselves and discover other agents in the network.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..core.agent import AgentInfo, AgentCapabilities
from ..core.message import Message, MessageType
from ..transport.http import JSONRPCRequest, JSONRPCResponse, json_rpc_method

logger = logging.getLogger(__name__)


class RegistryConfig(BaseModel):
    """Configuration for the registry service."""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    heartbeat_timeout: int = 60  # seconds
    cleanup_interval: int = 300  # seconds


@dataclass
class RegisteredAgent:
    """Information about a registered agent."""
    info: AgentInfo
    last_seen: datetime = field(default_factory=datetime.utcnow)
    ws_connection: Optional[WebSocket] = None


class Registry:
    """Registry service for agent discovery.
    
    This class implements a registry service that allows agents to register
    themselves and discover other agents in the network. It provides both
    HTTP/JSON-RPC and WebSocket interfaces for communication.
    """
    
    def __init__(self, config: Optional[RegistryConfig] = None):
        """Initialize the registry."""
        self.config = config or RegistryConfig()
        self.agents: Dict[str, RegisteredAgent] = {}
        self.app = FastAPI(debug=self.config.debug)
        self._setup_routes()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def _setup_routes(self) -> None:
        """Set up the HTTP and WebSocket routes."""
        @self.app.post("/rpc")
        async def handle_rpc(request: JSONRPCRequest) -> JSONRPCResponse:
            """Handle JSON-RPC requests."""
            try:
                if request.method == "register_agent":
                    result = await self.register_agent(**request.params)
                    return JSONRPCResponse(result=result, id=request.id)
                elif request.method == "discover_agents":
                    result = await self.discover_agents(**request.params)
                    return JSONRPCResponse(result=result, id=request.id)
                elif request.method == "heartbeat":
                    result = await self.heartbeat(**request.params)
                    return JSONRPCResponse(result=result, id=request.id)
                else:
                    return JSONRPCResponse(
                        error={"code": -32601, "message": "Method not found"},
                        id=request.id
                    )
            except Exception as e:
                logger.exception("Error processing RPC request")
                return JSONRPCResponse(
                    error={"code": -32603, "message": str(e)},
                    id=getattr(request, 'id', None)
                )
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            """Handle WebSocket connections."""
            await websocket.accept()
            agent_id = None
            
            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        message = Message.parse_raw(data)
                        
                        if message.type == MessageType.REGISTER:
                            # Handle registration
                            agent_id = message.sender
                            if agent_id in self.agents:
                                self.agents[agent_id].ws_connection = websocket
                                self.agents[agent_id].last_seen = datetime.utcnow()
                                await websocket.send_json({
                                    "type": "registered",
                                    "agent_id": agent_id
                                })
                            else:
                                await websocket.close(code=4000, reason="Agent not registered")
                                break
                        
                        elif message.type == MessageType.HEARTBEAT:
                            # Update last seen time
                            if agent_id in self.agents:
                                self.agents[agent_id].last_seen = datetime.utcnow()
                                await websocket.send_json({"type": "pong"})
                        
                        elif message.type == MessageType.DISCOVER:
                            # Handle discovery request
                            capabilities = message.payload.get("capabilities", [])
                            name = message.payload.get("name")
                            agents = await self._find_agents(capabilities, name)
                            await websocket.send_json({
                                "type": "discovery_response",
                                "agents": [agent.info.dict() for agent in agents]
                            })
                        
                    except Exception as e:
                        logger.exception("Error processing WebSocket message")
                        await websocket.send_json({
                            "type": "error",
                            "error": str(e)
                        })
            
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected: {agent_id}")
            except Exception as e:
                logger.exception("WebSocket error")
            finally:
                if agent_id in self.agents:
                    self.agents[agent_id].ws_connection = None
    
    async def start(self) -> None:
        """Start the registry service."""
        import uvicorn
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # Start the server
        config = uvicorn.Config(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level="info" if not self.config.debug else "debug",
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def stop(self) -> None:
        """Stop the registry service."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def _cleanup_loop(self) -> None:
        """Periodically clean up stale agent registrations."""
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                await self._cleanup_stale_agents()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in cleanup loop")
    
    async def _cleanup_stale_agents(self) -> None:
        """Remove agents that haven't sent a heartbeat recently."""
        now = datetime.utcnow()
        stale = []
        
        for agent_id, agent in list(self.agents.items()):
            if (now - agent.last_seen).total_seconds() > self.config.heartbeat_timeout:
                stale.append(agent_id)
        
        for agent_id in stale:
            logger.info(f"Removing stale agent: {agent_id}")
            if self.agents[agent_id].ws_connection:
                try:
                    await self.agents[agent_id].ws_connection.close()
                except Exception:
                    pass
            del self.agents[agent_id]
    
    async def register_agent(
        self,
        agent_id: str,
        name: str,
        endpoint: str,
        capabilities: Optional[Dict[str, List[str]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Register a new agent.
        
        Args:
            agent_id: Unique identifier for the agent
            name: Human-readable name for the agent
            endpoint: Endpoint where the agent can be reached
            capabilities: Dictionary of agent capabilities
            **kwargs: Additional agent metadata
            
        Returns:
            Registration result
        """
        if agent_id in self.agents:
            raise ValueError(f"Agent with ID {agent_id} is already registered")
        
        agent_info = AgentInfo(
            agent_id=agent_id,
            name=name,
            endpoint=endpoint,
            capabilities=AgentCapabilities(**(capabilities or {})),
            metadata=kwargs
        )
        
        self.agents[agent_id] = RegisteredAgent(info=agent_info)
        logger.info(f"Registered agent: {agent_id} ({name})")
        
        return {
            "status": "success",
            "agent_id": agent_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def discover_agents(
        self,
        capabilities: Optional[List[str]] = None,
        name: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Discover agents matching the given criteria.
        
        Args:
            capabilities: List of required capabilities
            name: Optional agent name to filter by
            **kwargs: Additional filter criteria
            
        Returns:
            Dictionary containing matching agents
        """
        agents = await self._find_agents(capabilities, name)
        
        return {
            "agents": [agent.info.dict() for agent in agents],
            "count": len(agents),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _find_agents(
        self,
        capabilities: Optional[List[str]] = None,
        name: Optional[str] = None,
    ) -> List[RegisteredAgent]:
        """Find agents matching the given criteria."""
        now = datetime.utcnow()
        matching = []
        
        for agent in self.agents.values():
            # Skip stale agents
            if (now - agent.last_seen).total_seconds() > self.config.heartbeat_timeout:
                continue
            
            # Filter by name if specified
            if name and name.lower() not in agent.info.name.lower():
                continue
            
            # Filter by capabilities if specified
            if capabilities:
                has_capabilities = all(
                    cap in agent.info.capabilities.can_process or
                    cap in agent.info.capabilities.can_provide
                    for cap in capabilities
                )
                if not has_capabilities:
                    continue
            
            matching.append(agent)
        
        return matching
    
    async def heartbeat(self, agent_id: str) -> Dict[str, Any]:
        """Update the last seen timestamp for an agent.
        
        Args:
            agent_id: ID of the agent sending the heartbeat
            
        Returns:
            Acknowledgment of the heartbeat
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} is not registered")
        
        self.agents[agent_id].last_seen = datetime.utcnow()
        return {"status": "ok", "timestamp": self.agents[agent_id].last_seen.isoformat()}


class RegistryClient:
    """Client for interacting with a registry service."""
    
    def __init__(self, endpoint: str):
        """Initialize the registry client.
        
        Args:
            endpoint: URL of the registry service
        """
        self.endpoint = endpoint.rstrip('/')
        self.session = None
    
    async def __aenter__(self) -> RegistryClient:
        """Async context manager entry."""
        import aiohttp
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def register_agent(
        self,
        agent_id: str,
        name: str,
        endpoint: str,
        capabilities: Optional[Dict[str, List[str]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Register an agent with the registry.
        
        Args:
            agent_id: Unique identifier for the agent
            name: Human-readable name for the agent
            endpoint: Endpoint where the agent can be reached
            capabilities: Dictionary of agent capabilities
            **kwargs: Additional agent metadata
            
        Returns:
            Registration result
        """
        if not self.session:
            raise RuntimeError("RegistryClient must be used as a context manager")
        
        request = JSONRPCRequest(
            method="register_agent",
            params={
                "agent_id": agent_id,
                "name": name,
                "endpoint": endpoint,
                "capabilities": capabilities or {},
                **kwargs
            }
        )
        
        async with self.session.post(
            f"{self.endpoint}/rpc",
            json=request.dict(),
            headers={"Content-Type": "application/json"}
        ) as response:
            data = await response.json()
            if "error" in data:
                raise ValueError(f"Registry error: {data['error']}")
            return data["result"]
    
    async def discover_agents(
        self,
        capabilities: Optional[List[str]] = None,
        name: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Discover agents matching the given criteria.
        
        Args:
            capabilities: List of required capabilities
            name: Optional agent name to filter by
            **kwargs: Additional filter criteria
            
        Returns:
            Dictionary containing matching agents
        """
        if not self.session:
            raise RuntimeError("RegistryClient must be used as a context manager")
        
        request = JSONRPCRequest(
            method="discover_agents",
            params={
                "capabilities": capabilities or [],
                "name": name,
                **kwargs
            }
        )
        
        async with self.session.post(
            f"{self.endpoint}/rpc",
            json=request.dict(),
            headers={"Content-Type": "application/json"}
        ) as response:
            data = await response.json()
            if "error" in data:
                raise ValueError(f"Registry error: {data['error']}")
            return data["result"]
    
    async def heartbeat(self, agent_id: str) -> Dict[str, Any]:
        """Send a heartbeat to the registry.
        
        Args:
            agent_id: ID of the agent sending the heartbeat
            
        Returns:
            Acknowledgment of the heartbeat
        """
        if not self.session:
            raise RuntimeError("RegistryClient must be used as a context manager")
        
        request = JSONRPCRequest(
            method="heartbeat",
            params={"agent_id": agent_id}
        )
        
        async with self.session.post(
            f"{self.endpoint}/rpc",
            json=request.dict(),
            headers={"Content-Type": "application/json"}
        ) as response:
            data = await response.json()
            if "error" in data:
                raise ValueError(f"Registry error: {data['error']}")
            return data["result"]
