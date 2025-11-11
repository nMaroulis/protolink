from protolink.transport.transport import Transport
import httpx
from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task


class HTTPTransport(Transport):
    """JSON-RPC 2.0 transport over HTTP/WebSocket.
    
    Implements A2A protocol communication using:
    - HTTP for synchronous requests
    - WebSocket for streaming/async (future enhancement)
    
    Uses JSON-RPC 2.0 for method calls:
    - tasks/send - Send a task
    - message/send - Send a message
    - /.well-known/agent.json - Get agent card
    """
    
    def __init__(self, timeout: float = 30.0):
        """Initialize JSON-RPC transport.
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
    
    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
    
    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    def _next_request_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id
    
    async def _json_rpc_call(self, url: str, method: str, params: dict) -> dict:
        """Make a JSON-RPC 2.0 call.
        
        Args:
            url: Target URL
            method: RPC method name
            params: Method parameters
            
        Returns:
            Result from RPC call
            
        Raises:
            Exception: If RPC call fails
        """
        client = self._get_client()
        
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._next_request_id()
        }
        
        response = await client.post(url, json=request)
        response.raise_for_status()
        
        result = response.json()
        
        if "error" in result:
            raise Exception(f"RPC Error: {result['error']}")
        
        return result.get("result", {})
    
    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send task via JSON-RPC.
        
        Args:
            agent_url: Target agent URL
            task: Task to send
            
        Returns:
            Processed task
        """
        result = await self._json_rpc_call(
            agent_url,
            "tasks/send",
            {"task": task.to_dict()}
        )
        
        return Task.from_dict(result.get("task", {}))
    
    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send message via JSON-RPC.
        
        Args:
            agent_url: Target agent URL
            message: Message to send
            
        Returns:
            Response message
        """
        result = await self._json_rpc_call(
            agent_url,
            "message/send",
            {"message": message.to_dict()}
        )
        
        return Message.from_dict(result.get("message", {}))
    
    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Fetch agent card via well-known URI.
        
        Args:
            agent_url: Agent base URL
            
        Returns:
            AgentCard
        """
        client = self._get_client()
        
        # Try standard A2A well-known path
        well_known_url = f"{agent_url.rstrip('/')}/.well-known/agent.json"
        
        try:
            response = await client.get(well_known_url)
            response.raise_for_status()
            data = response.json()
            return AgentCard.from_json(data)
        except Exception as e:
            raise Exception(f"Failed to fetch agent card: {e}")
    
    async def close(self):
        """Close the transport and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None