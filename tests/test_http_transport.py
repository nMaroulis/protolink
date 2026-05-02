from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from protolink.client.request_spec import ClientRequestSpec
from protolink.models import Message, Task
from protolink.transport.http_transport import HTTPTransport


@pytest.mark.asyncio
async def test_http_send_success():
    transport = HTTPTransport(url="http://localhost:8000")

    # Mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_response.raise_for_status = MagicMock()

    # Mock client
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        spec = ClientRequestSpec(name="test", method="POST", path="/task", request_source="body")
        result = await transport.send(spec, base_url="http://agent-b:8000", data={"key": "val"})

        assert result == {"status": "ok"}
        mock_client.request.assert_awaited_once()
        args, kwargs = mock_client.request.call_args
        assert args[0] == "POST"
        assert args[1] == "http://agent-b:8000/task"
        assert kwargs["json"] == {"key": "val"}


@pytest.mark.asyncio
async def test_http_send_connection_error():
    transport = HTTPTransport(url="http://localhost:8000")

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request.side_effect = httpx.ConnectError("Connection failed")

    with patch("httpx.AsyncClient", return_value=mock_client):
        spec = ClientRequestSpec(name="status", method="GET", path="/status")
        with pytest.raises(ConnectionError) as excinfo:
            await transport.send(spec, base_url="http://dead-agent:8000")

        assert "Failed to connect" in str(excinfo.value)


@pytest.mark.asyncio
async def test_http_send_status_error():
    transport = HTTPTransport(url="http://localhost:8000")

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    # httpx raises HTTPStatusError when raise_for_status() is called
    error = httpx.HTTPStatusError("Error", request=MagicMock(), response=mock_response)
    mock_client.request.return_value = mock_response
    mock_response.raise_for_status.side_effect = error

    with patch("httpx.AsyncClient", return_value=mock_client):
        spec = ClientRequestSpec(name="missing", method="GET", path="/missing")
        with pytest.raises(RuntimeError) as excinfo:
            await transport.send(spec, base_url="http://agent:8000")

        assert "returned HTTP 404" in str(excinfo.value)


@pytest.mark.asyncio
async def test_http_auth_headers():
    mock_auth = MagicMock()
    mock_auth.authenticate = AsyncMock(return_value=MagicMock(token="test-token"))

    transport = HTTPTransport(url="http://localhost:8000", authenticator=mock_auth)
    await transport.authenticate("creds")

    headers = transport._build_headers()
    assert headers["Authorization"] == "Bearer test-token"


def test_http_validate_url():
    t1 = HTTPTransport(url="http://ok.com")
    assert t1.validate_url() is True

    t2 = HTTPTransport(url="invalid://url")
    assert t2.validate_url() is False


@pytest.mark.asyncio
async def test_http_serialization_task():
    transport = HTTPTransport(url="http://localhost:8000")
    task = Task(messages=[Message.user("hello")])

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"received": "task"}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        spec = ClientRequestSpec(name="task", method="POST", path="/task", request_source="body")
        await transport.send(spec, base_url="http://agent:8000", data=task)

        _, kwargs = mock_client.request.call_args
        # Should call to_dict() or similar
        assert "json" in kwargs
        assert kwargs["json"]["messages"][0]["parts"][0]["content"] == "hello"
