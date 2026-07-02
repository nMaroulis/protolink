"""Authentication and Security Example - Protolink.

This script demonstrates and verifies all authentication options available in ProtoLink.
It covers API Key, Bearer Token (JWT), and Basic Authentication, as well as lazy client-side credential signing and
server-side request verification. It also shows both success and failure scenarios for HTTP and WebSocket transports.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import socket
import time
from typing import Any

import httpx
import websockets

from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.security.auth import APIKeyAuth, BasicAuth, BearerTokenAuth
from protolink.transport import HTTPTransport, WebSocketTransport


def get_free_port() -> int:
    """Find a free TCP port on localhost."""
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _b64url_json(value: dict[str, Any]) -> str:
    """Encode a JSON object as an unpadded base64url JWT segment."""
    data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def create_hs256_jwt(claims: dict[str, Any], secret: str) -> str:
    """Create a compact HS256 JWT for the authentication example."""
    header = _b64url_json({"alg": "HS256", "typ": "JWT"})
    payload = _b64url_json(claims)
    signature = hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    signature_segment = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{header}.{payload}.{signature_segment}"


class SecureEchoAgent(Agent):
    """An agent that requires authentication and echoes back messages."""

    def __init__(self, name: str, port: int, authenticator: Any, backend: str = "starlette") -> None:
        transport = HTTPTransport(url=f"http://127.0.0.1:{port}", backend=backend)
        card = AgentCard(name=name, description="A secure echo agent", url=f"http://127.0.0.1:{port}")
        super().__init__(card, transport=transport, authenticator=authenticator)

    async def handle_task(self, task: Task) -> Task:
        user_text = task.messages[-1].parts[0].content
        return task.complete(f"[{self.card.name}] secure echo: {user_text}")


async def run_tests() -> None:
    print("======================================================================")
    print("                     PROTOLINK AUTHENTICATION TESTS                   ")
    print("======================================================================")

    # ------------------------------------------------------------------
    # Setup for Tests 1, 2, 3: API Key Auth (Starlette)
    # ------------------------------------------------------------------
    print("\n--- Initializing API Key Auth (Starlette) Agent ---")
    apikey_port = get_free_port()
    apikey_auth = APIKeyAuth(valid_keys={"my-secret-key": ["read", "write"]})
    apikey_agent = SecureEchoAgent("apikey_agent", apikey_port, apikey_auth, backend="starlette")
    apikey_agent.start(background=True)

    try:
        # Test 1: API Key Authentication (Success)
        print("\n--- Test 1: API Key Authentication (Success) ---")
        task_data = Task.create(Message.user("Hello via API Key")).to_dict()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{apikey_port}/tasks/", json=task_data, headers={"X-API-Key": "my-secret-key"}
            )
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.json()}")
            assert resp.status_code == 200
            assert "secure echo: Hello via API Key" in resp.json()["messages"][-1]["parts"][0]["content"]
            print("SUCCESS")

        # Test 2: API Key Authentication (Failure - Wrong Key)
        print("\n--- Test 2: API Key Authentication (Failure - Wrong Key) ---")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{apikey_port}/tasks/", json=task_data, headers={"X-API-Key": "wrong-key"}
            )
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.json()}")
            assert resp.status_code == 401
            assert "Authentication failed" in resp.json()["error"]
            print("SUCCESS (Caught expected 401)")

        # Test 3: API Key Authentication (Failure - No Key)
        print("\n--- Test 3: API Key Authentication (Failure - No Key) ---")
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"http://127.0.0.1:{apikey_port}/tasks/", json=task_data)
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.json()}")
            assert resp.status_code == 401
            assert "Missing credentials" in resp.json()["error"]
            print("SUCCESS (Caught expected 401)")

    finally:
        print("Stopping API Key agent...")
        apikey_agent.stop()

    # ------------------------------------------------------------------
    # Setup for Tests 4, 5: Bearer Token Auth (FastAPI)
    # ------------------------------------------------------------------
    print("\n--- Initializing Bearer Token Auth (FastAPI) Agent ---")
    bearer_port = get_free_port()
    jwt_secret = "test-secret"
    bearer_auth = BearerTokenAuth(secret=jwt_secret)
    bearer_agent = SecureEchoAgent("bearer_agent", bearer_port, bearer_auth, backend="fastapi")
    bearer_agent.start(background=True)

    try:
        valid_token = create_hs256_jwt({"sub": "test-user", "exp": int(time.time()) + 300}, jwt_secret)

        # Test 4: Bearer Token Authentication (Success)
        print("\n--- Test 4: Bearer Token Authentication (Success) ---")
        task_data = Task.create(Message.user("Hello via Bearer Token")).to_dict()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{bearer_port}/tasks/",
                json=task_data,
                headers={"Authorization": f"Bearer {valid_token}"},
            )
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.json()}")
            assert resp.status_code == 200
            assert "secure echo: Hello via Bearer" in resp.json()["messages"][-1]["parts"][0]["content"]
            print("SUCCESS")

        # Test 5: Bearer Token Authentication (Failure - Invalid Token)
        print("\n--- Test 5: Bearer Token Authentication (Failure - Invalid Token) ---")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{bearer_port}/tasks/",
                json=task_data,
                headers={"Authorization": "Bearer invalid.format.token"},
            )
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.json()}")
            assert resp.status_code == 401
            assert "Authentication failed" in resp.json()["error"]
            print("SUCCESS (Caught expected 401)")

    finally:
        print("Stopping Bearer Token agent...")
        bearer_agent.stop()

    # ------------------------------------------------------------------
    # Setup for Tests 6, 7: Basic Auth (Starlette)
    # ------------------------------------------------------------------
    print("\n--- Initializing Basic Auth (Starlette) Agent ---")
    basic_port = get_free_port()
    basic_auth = BasicAuth(valid_credentials={"admin": "password123"})
    basic_agent = SecureEchoAgent("basic_agent", basic_port, basic_auth, backend="starlette")
    basic_agent.start(background=True)

    try:
        # Test 6: Basic Auth (Success)
        print("\n--- Test 6: Basic Auth (Success) ---")
        task_data = Task.create(Message.user("Hello via Basic Auth")).to_dict()
        encoded_creds = base64.b64encode(b"admin:password123").decode()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{basic_port}/tasks/",
                json=task_data,
                headers={"Authorization": f"Basic {encoded_creds}"},
            )
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.json()}")
            assert resp.status_code == 200
            assert "secure echo: Hello via Basic" in resp.json()["messages"][-1]["parts"][0]["content"]
            print("SUCCESS")

        # Test 7: Basic Auth (Failure - Wrong Password)
        print("\n--- Test 7: Basic Auth (Failure - Wrong Password) ---")
        wrong_encoded_creds = base64.b64encode(b"admin:wrongpass").decode()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{basic_port}/tasks/",
                json=task_data,
                headers={"Authorization": f"Basic {wrong_encoded_creds}"},
            )
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.json()}")
            assert resp.status_code == 401
            assert "Authentication failed" in resp.json()["error"]
            print("SUCCESS (Caught expected 401)")

    finally:
        print("Stopping Basic Auth agent...")
        basic_agent.stop()

    # ------------------------------------------------------------------
    # Test 8: Lazy Client-Side Authentication
    # ------------------------------------------------------------------
    print("\n--- Test 8: Lazy Client-Side Authentication ---")
    server_port = get_free_port()
    server_auth = APIKeyAuth(valid_keys={"client-key": ["read"]})
    server_agent = SecureEchoAgent("server_agent", server_port, server_auth)
    server_agent.start(background=True)

    try:
        # Create a client-side HTTPTransport with credentials parameter.
        # It should perform lazy authentication on the first send() call.
        client_transport = HTTPTransport(
            url=f"http://127.0.0.1:{server_port}", authenticator=server_auth, credentials="client-key"
        )
        assert client_transport.security_context is None, "Security Context should be initialized lazily"

        # Construct ClientRequestSpec for the send task endpoint
        from protolink.client.request_spec import ClientRequestSpec

        task = Task.create(Message.user("Lazy hello"))
        request_spec = ClientRequestSpec(
            name="send_task",
            method="POST",
            path="/tasks/",
        )

        # Trigger send. It should authenticate automatically behind the scenes.
        response = await client_transport.send(request_spec, base_url=client_transport.url, data=task)
        print(f"Response from server: {response}")
        assert client_transport.security_context is not None, "Security Context should now be populated"
        assert client_transport.security_context.principal_id == "api-key-client-k"
        assert response["state"] == "completed"
        print("SUCCESS")
    finally:
        print("Stopping Lazy Auth server...")
        server_agent.stop()

    # ------------------------------------------------------------------
    # Test 9: Agent-Level Authentication Integration
    # ------------------------------------------------------------------
    print("\n--- Test 9: Agent-Level Authentication Integration ---")
    agent_auth = BasicAuth(valid_credentials={"user": "pass"})
    agent = Agent(
        card={"name": "integrated-agent", "description": "integrated description", "url": "http://127.0.0.1:9999"},
        transport="http",
        authenticator=agent_auth,
        credentials="user:pass",
    )
    # Check security schemes mapped from authenticator
    print(f"Agent Security Schemes: {agent.card.security_schemes}")
    assert agent.card.security_schemes is not None
    assert "http" in agent.card.security_schemes
    assert agent.card.security_schemes["http"]["scheme"] == "basic"
    assert agent.transport.authenticator is agent_auth
    assert agent.transport.credentials == "user:pass"
    print("SUCCESS")

    # ------------------------------------------------------------------
    # Test 10: WebSocket Authentication (Success & Failure)
    # ------------------------------------------------------------------
    print("\n--- Test 10: WebSocket Authentication (Success & Failure) ---")
    ws_port = get_free_port()
    ws_auth = APIKeyAuth(valid_keys={"ws-secret": ["connect"]})
    ws_transport = WebSocketTransport(url=f"ws://127.0.0.1:{ws_port}", authenticator=ws_auth)
    ws_transport.setup_routes([])
    await ws_transport.start()

    try:
        # 10a. Connection Failure (No header)
        print("Connecting to WebSocket with NO credentials...")
        try:
            async with websockets.connect(f"ws://127.0.0.1:{ws_port}"):
                pass
            raise AssertionError("WebSocket handshake succeeded when it should have failed!")
        except Exception as exc:
            # Check for a 401 rejection
            status_code = getattr(exc, "status_code", None)
            if status_code is None:
                resp = getattr(exc, "response", None)
                if resp is not None:
                    status_code = getattr(resp, "status_code", None)
            print(f"WebSocket rejected connection. Status code: {status_code}")
            assert status_code == 401
            print("WS Failure test passed.")

        # 10b. Connection Success (With valid header)
        print("Connecting to WebSocket with VALID credentials...")
        async with websockets.connect(f"ws://127.0.0.1:{ws_port}", additional_headers={"X-API-Key": "ws-secret"}) as ws:
            print("Successfully connected to authenticated WebSocket server!")
            await ws.close()
            print("WS Success test passed.")

        print("SUCCESS")
    finally:
        print("Stopping WebSocket server...")
        await ws_transport.stop()

    print("\n======================================================================")
    print("                       ALL 10 TESTS COMPLETED                         ")
    print("======================================================================")


def main() -> None:
    asyncio.run(run_tests())


if __name__ == "__main__":
    main()
