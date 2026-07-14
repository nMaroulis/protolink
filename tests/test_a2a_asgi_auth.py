"""Authenticated A2A 1.0 coverage through the real HTTP ASGI boundary."""

from __future__ import annotations

import httpx
import pytest

from protolink.a2a.v1 import A2A_AGENT_CARD_PATH, A2A_PROTOCOL_VERSION
from protolink.agents import Agent
from protolink.llms import MockLLM
from protolink.security.auth import APIKeyAuth
from protolink.transport.http_transport import HTTPTransport


@pytest.mark.parametrize("backend", ["starlette", "fastapi"])
@pytest.mark.asyncio
async def test_authenticated_a2a_send_message_through_asgi(backend: str) -> None:
    api_key = "secret-key"
    prompt = "Execute this inbound A2A semantic payload."
    expected_response = "The default Agent executed the inbound A2A text."
    authenticator = APIKeyAuth(valid_keys={api_key: ["read"]})
    transport = HTTPTransport(
        url="http://agent.test",
        authenticator=authenticator,
        backend=backend,
    )
    agent = Agent(
        card={
            "name": "authenticated-a2a-agent",
            "description": "Authenticated A2A ASGI test agent",
            "url": "http://agent.test",
            "version": "0.6.6",
        },
        transport=transport,
        llm=MockLLM(
            mock_responses={prompt: expected_response},
            default_response="The A2A prompt was not forwarded to the LLM.",
        ),
        a2a=True,
        authenticator=authenticator,
        expose_chat=False,
        verbosity=0,
    )
    assert agent.server is not None
    agent.server._build_endpoints()

    asgi_transport = httpx.ASGITransport(app=transport.backend.app)
    async with httpx.AsyncClient(
        transport=asgi_transport,
        base_url="http://agent.test",
    ) as client:
        card_response = await client.get(A2A_AGENT_CARD_PATH)
        assert card_response.status_code == 200
        card = card_response.json()
        assert card["supportedInterfaces"] == [
            {
                "url": "http://agent.test",
                "protocolBinding": "JSONRPC",
                "protocolVersion": A2A_PROTOCOL_VERSION,
            }
        ]
        assert card["securitySchemes"]["apiKey"]["apiKeySecurityScheme"]["name"] == "X-API-Key"
        assert card["securityRequirements"] == [{"schemes": {"apiKey": {"list": []}}}]

        request = {
            "jsonrpc": "2.0",
            "id": "send-message-1",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "message-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": prompt}],
                }
            },
        }
        a2a_headers = {"A2A-Version": A2A_PROTOCOL_VERSION}

        missing_credentials = await client.post("/", json=request, headers=a2a_headers)
        assert missing_credentials.status_code == 401
        assert missing_credentials.json() == {"error": "Missing credentials"}

        invalid_credentials = await client.post(
            "/",
            json=request,
            headers={**a2a_headers, "X-API-Key": "invalid-key"},
        )
        assert invalid_credentials.status_code == 401
        assert "Invalid API key" in invalid_credentials.json()["error"]

        response = await client.post(
            "/",
            json=request,
            headers={**a2a_headers, "X-API-Key": api_key},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "send-message-1"
    assert "error" not in payload
    task = payload["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert [part for artifact in task["artifacts"] for part in artifact["parts"]] == [{"text": expected_response}]
