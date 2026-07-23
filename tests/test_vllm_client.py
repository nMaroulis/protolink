from __future__ import annotations

from typing import Any
from urllib.request import Request

import pytest

import protolink.llms as llms
from protolink.llms import create_llm
from protolink.llms.history import ConversationHistory
from protolink.llms.server import VLLMLLM, OpenAICompatibleLLM


def _skip_connection_validation(monkeypatch) -> None:
    monkeypatch.setattr(VLLMLLM, "validate_connection", lambda self: True)


def test_vllm_defaults_and_openai_compatible_inheritance(monkeypatch):
    monkeypatch.delenv("VLLM_URL", raising=False)
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://generic.example.test/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "generic-key")
    _skip_connection_validation(monkeypatch)

    llm = VLLMLLM(model="Qwen/Qwen3-8B")

    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm.provider == "vllm"
    assert llm.base_url == "http://localhost:8000/v1"
    assert llm.api_key is None
    assert llms.VLLMLLM is VLLMLLM


def test_vllm_requires_served_model(monkeypatch):
    _skip_connection_validation(monkeypatch)

    with pytest.raises(TypeError, match="model"):
        VLLMLLM()


def test_vllm_reads_environment_configuration(monkeypatch):
    monkeypatch.setenv("VLLM_URL", "https://vllm.example.test/v1/")
    monkeypatch.setenv("VLLM_API_KEY", "environment-key")
    _skip_connection_validation(monkeypatch)

    llm = VLLMLLM(model="served-model")

    assert llm.base_url == "https://vllm.example.test/v1"
    assert llm.api_key == "environment-key"
    assert llm.headers["Authorization"] == "Bearer environment-key"


def test_vllm_explicit_configuration_wins_over_environment(monkeypatch):
    monkeypatch.setenv("VLLM_URL", "https://environment.example.test/v1")
    monkeypatch.setenv("VLLM_API_KEY", "environment-key")
    _skip_connection_validation(monkeypatch)

    llm = VLLMLLM(
        base_url="https://explicit.example.test/v1/",
        api_key="explicit-key",
        model="served-model",
    )

    assert llm.base_url == "https://explicit.example.test/v1"
    assert llm.api_key == "explicit-key"
    assert llm.headers["Authorization"] == "Bearer explicit-key"


def test_vllm_validate_connection_sends_authentication_header(monkeypatch):
    requests: list[tuple[Request, int]] = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request: Request, timeout: int):
        requests.append((request, timeout))
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    llm = VLLMLLM(
        base_url="https://vllm.example.test/v1",
        api_key="secret-token",
        model="served-model",
    )

    assert llm.validate_connection() is True
    request, timeout = requests[-1]
    assert request.full_url == "https://vllm.example.test/v1/models"
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert request.get_header("Accept") == "application/json"
    assert timeout == 3


def test_vllm_inherits_chat_completion_call_payload(monkeypatch):
    _skip_connection_validation(monkeypatch)
    llm = VLLMLLM(
        base_url="https://vllm.example.test/v1",
        model="Qwen/Qwen3-8B",
        model_params={"temperature": 0.2, "max_tokens": 128},
    )
    captured: dict[str, Any] = {}

    def fake_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(llm, "_post_json", fake_post_json)
    history = ConversationHistory()
    history.add_user("Hello, vLLM")

    assert llm.call(history) == "done"
    assert captured["url"] == "https://vllm.example.test/v1/chat/completions"
    assert captured["payload"] == {
        "model": "Qwen/Qwen3-8B",
        "messages": history.messages,
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 128,
        "response_format": {"type": "json_object"},
    }


def test_create_llm_builds_vllm_provider(monkeypatch):
    _skip_connection_validation(monkeypatch)

    llm = create_llm("vllm", model="served-model")

    assert isinstance(llm, VLLMLLM)
    assert llm.provider == "vllm"
