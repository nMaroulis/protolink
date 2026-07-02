import base64
import hashlib
import hmac
import json
import socket
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from protolink.agents import Agent
from protolink.client.request_spec import ClientRequestSpec
from protolink.security.auth import (
    APIKeyAuth,
    BasicAuth,
    BearerTokenAuth,
    extract_credentials,
)
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport.http_transport import HTTPTransport
from protolink.transport.websocket_transport import WebSocketTransport


def get_free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _b64url_json(value: dict[str, Any]) -> str:
    data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_hs256_jwt(claims: dict[str, Any], secret: str = "super-secret") -> str:
    """Create a compact HS256 JWT for auth tests."""
    header = _b64url_json({"alg": "HS256", "typ": "JWT"})
    payload = _b64url_json(claims)
    signature = hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    signature_segment = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{header}.{payload}.{signature_segment}"


@pytest.mark.asyncio
async def test_basic_auth():
    auth = BasicAuth(valid_credentials={"user1": "pass1", "user2": "pass2"})

    # Test scheme property
    scheme = auth.security_scheme
    assert scheme.auth_type == "http"
    assert scheme.auth_scheme == "basic"

    # Test raw string auth
    context = await auth.authenticate("user1:pass1")
    assert context.principal_id == "user1"
    assert context.token == "user1:pass1"

    # Test base64 auth
    b64_creds = base64.b64encode(b"user2:pass2").decode("utf-8")
    context = await auth.authenticate(b64_creds)
    assert context.principal_id == "user2"
    assert context.token == b64_creds

    # Test failure cases
    with pytest.raises(Exception, match="Invalid username or password"):
        await auth.authenticate("user1:wrongpass")

    with pytest.raises(Exception, match="Invalid username or password"):
        await auth.authenticate("wronguser:pass1")

    with pytest.raises(Exception, match="Invalid Basic authentication format"):
        await auth.authenticate("not_colon_separated")


def test_extract_credentials():
    # 1. Test Authorization header (Bearer)
    headers = {"Authorization": "Bearer token123"}
    assert extract_credentials(headers) == "token123"

    # 2. Test Authorization header (Basic)
    headers = {"authorization": "Basic dXNlcjpwYXNz"}
    assert extract_credentials(headers) == "dXNlcjpwYXNz"

    # 3. Test Authorization header (ApiKey)
    headers = [("Authorization", "ApiKey key456")]
    assert extract_credentials(headers) == "key456"

    # 4. Test X-API-Key header
    headers = {"X-API-Key": "my-api-key"}
    assert extract_credentials(headers) == "my-api-key"

    headers = [("x-api-key", "my-api-key-2")]
    assert extract_credentials(headers) == "my-api-key-2"

    # 5. Test Query params
    query = {"api_key": "query-api-key"}
    assert extract_credentials(None, query) == "query-api-key"

    query = {"token": "query-token"}
    assert extract_credentials({}, query) == "query-token"

    # 6. Test None cases
    assert extract_credentials(None) is None
    assert extract_credentials({}) is None


@pytest.mark.asyncio
async def test_http_lazy_authentication():
    # Setup auth and transport
    auth = APIKeyAuth(valid_keys={"secret-key": ["read"]})
    transport = HTTPTransport(url="http://localhost:8000", authenticator=auth, credentials="secret-key")

    assert transport.security_context is None

    # Mock client and response to test header injection
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        spec = ClientRequestSpec(name="test", method="GET", path="/test")
        await transport.send(spec, base_url="http://other-agent:8080")

        # Lazy auth should have run
        assert transport.security_context is not None
        assert transport.security_context.principal_id == "api-key-secret-k"

        # Headers should contain X-API-Key and ApiKey Authorization
        mock_client.request.assert_awaited_once()
        _, kwargs = mock_client.request.call_args
        headers = kwargs["headers"]
        assert headers["X-API-Key"] == "secret-key"
        assert headers["Authorization"] == "ApiKey secret-key"


def test_agent_security_scheme_mapping():
    auth = BasicAuth(valid_credentials={"user": "pass"})
    agent = Agent(
        card={"name": "AuthAgent", "description": "Secure agent", "url": "http://localhost:8000"},
        transport="http",
        authenticator=auth,
    )

    # Verify authenticator is passed to transport
    assert agent.transport.authenticator is auth

    # Verify AgentCard security schemes are updated automatically
    assert agent.card.security_schemes is not None
    assert "http" in agent.card.security_schemes
    scheme_dict = agent.card.security_schemes["http"]
    assert scheme_dict["type"] == "http"
    assert scheme_dict["scheme"] == "basic"


@pytest.mark.asyncio
async def test_bearer_token_auth_validates_signature_and_registered_claims():
    auth = BearerTokenAuth(
        secret="super-secret",
        issuer="https://issuer.example",
        audience="protolink-agent",
    )
    now = int(time.time())
    token = make_hs256_jwt(
        {
            "sub": "test-user",
            "iss": "https://issuer.example",
            "aud": ["protolink-agent", "other-service"],
            "iat": now,
            "exp": now + 60,
            "metadata": {"scope": "read"},
            "tenant": "demo",
        }
    )

    context = await auth.authenticate(token)
    assert context.principal_id == "test-user"
    assert context.expires_at is not None
    assert context.metadata["scope"] == "read"
    assert context.metadata["claims"] == {"tenant": "demo"}

    tampered = token.rsplit(".", 1)[0] + ".invalid"
    with pytest.raises(Exception, match="signature verification failed"):
        await auth.authenticate(tampered)

    expired = make_hs256_jwt(
        {
            "sub": "test-user",
            "iss": "https://issuer.example",
            "aud": "protolink-agent",
            "exp": now - 1,
        }
    )
    with pytest.raises(Exception, match="expired"):
        await auth.authenticate(expired)

    wrong_issuer = make_hs256_jwt(
        {
            "sub": "test-user",
            "iss": "https://other.example",
            "aud": "protolink-agent",
            "exp": now + 60,
        }
    )
    with pytest.raises(Exception, match="issuer mismatch"):
        await auth.authenticate(wrong_issuer)


@pytest.mark.asyncio
async def test_http_server_backend_authentication_starlette():
    port = get_free_port()
    auth = BearerTokenAuth(secret="super-secret")
    valid_token = make_hs256_jwt({"sub": "test-user", "exp": int(time.time()) + 60})

    transport = HTTPTransport(
        url=f"http://127.0.0.1:{port}",
        authenticator=auth,
        backend="starlette",
    )

    # Register a test route
    def handle_test():
        return {"ok": True}

    endpoints = [
        EndpointSpec(
            name="test",
            path="/test",
            method="GET",
            handler=handle_test,
            request_source="none",
        )
    ]
    transport.setup_routes(endpoints)

    await transport.start()
    try:
        async with httpx.AsyncClient() as client:
            # 1. No credentials -> 401
            resp = await client.get(f"http://127.0.0.1:{port}/test")
            assert resp.status_code == 401
            assert "Missing credentials" in resp.json()["error"]

            # 2. Wrong credentials -> 401
            resp = await client.get(f"http://127.0.0.1:{port}/test", headers={"Authorization": "Bearer invalid_token"})
            assert resp.status_code == 401
            assert "Authentication failed" in resp.json()["error"]

            # 3. Valid credentials -> 200
            resp = await client.get(f"http://127.0.0.1:{port}/test", headers={"Authorization": f"Bearer {valid_token}"})
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_http_server_backend_authentication_fastapi():
    port = get_free_port()
    auth = BearerTokenAuth(secret="super-secret")
    valid_token = make_hs256_jwt({"sub": "test-user", "exp": int(time.time()) + 60})

    transport = HTTPTransport(
        url=f"http://127.0.0.1:{port}",
        authenticator=auth,
        backend="fastapi",
    )

    def handle_test():
        return {"ok": True}

    endpoints = [
        EndpointSpec(
            name="test",
            path="/test",
            method="GET",
            handler=handle_test,
            request_source="none",
        )
    ]
    transport.setup_routes(endpoints)

    await transport.start()
    try:
        async with httpx.AsyncClient() as client:
            # 1. No credentials -> 401
            resp = await client.get(f"http://127.0.0.1:{port}/test")
            assert resp.status_code == 401
            assert "Missing credentials" in resp.json()["error"]

            # 2. Wrong credentials -> 401
            resp = await client.get(f"http://127.0.0.1:{port}/test", headers={"Authorization": "Bearer invalid_token"})
            assert resp.status_code == 401
            assert "Authentication failed" in resp.json()["error"]

            # 3. Valid credentials -> 200
            resp = await client.get(f"http://127.0.0.1:{port}/test", headers={"Authorization": f"Bearer {valid_token}"})
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_websocket_server_handshake_authentication():
    port = get_free_port()
    auth = APIKeyAuth(valid_keys={"ws-key": ["connect"]})

    transport = WebSocketTransport(
        url=f"ws://127.0.0.1:{port}",
        authenticator=auth,
    )

    # Empty endpoints, since we only test the handshake layer
    transport.setup_routes([])

    await transport.start()
    try:
        import websockets

        # 1. No credentials -> Handshake Exception / 401
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}"):
                pass
            pytest.fail("Handshake succeeded but should have failed with 401")
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code is None:
                resp = getattr(exc, "response", None)
                if resp is not None:
                    status_code = getattr(resp, "status_code", None)
            assert status_code == 401

        # 2. Wrong credentials -> Handshake Exception / 401
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}", additional_headers={"X-API-Key": "wrong-key"}):
                pass
            pytest.fail("Handshake succeeded but should have failed with 401")
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code is None:
                resp = getattr(exc, "response", None)
                if resp is not None:
                    status_code = getattr(resp, "status_code", None)
            assert status_code == 401

        # 3. Valid credentials -> Connection successfully established
        async with websockets.connect(f"ws://127.0.0.1:{port}", additional_headers={"X-API-Key": "ws-key"}) as ws:
            # We connected successfully, send close frame
            await ws.close()
    finally:
        await transport.stop()
