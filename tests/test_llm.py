"""The provider clients, tested against a fake HTTP transport (no network, no real keys)."""
import json

import httpx
import pytest

from app import config
from app.llm import AnthropicClient, LLMError, OpenAICompatibleClient, get_llm_client


def transport(handler):
    return httpx.MockTransport(handler)


def test_anthropic_request_and_reply():
    seen = {}

    def handler(request):
        seen["headers"], seen["body"] = request.headers, json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Answer [C1]"}]})

    client = AnthropicClient("secret-key", "some-model", transport=transport(handler))
    assert client.generate("SYSTEM", "USER") == "Answer [C1]"
    assert seen["headers"]["x-api-key"] == "secret-key" and seen["headers"]["anthropic-version"]
    assert seen["body"]["system"] == "SYSTEM" and seen["body"]["messages"][0]["content"] == "USER"
    assert seen["body"]["model"] == "some-model" and seen["body"]["temperature"] == 0


def test_temperature_is_dropped_and_retried_if_the_model_rejects_it():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "temperature is not supported for this model"}})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    assert AnthropicClient("k", "m", transport=transport(handler)).generate("s", "u") == "ok"
    assert len(bodies) == 2 and "temperature" not in bodies[1]


def test_http_error_becomes_llm_error_without_leaking_the_key():
    client = AnthropicClient("secret-key", "m", transport=transport(lambda r: httpx.Response(500, text="boom secret-key")))
    with pytest.raises(LLMError) as error:
        client.generate("s", "u")
    assert "500" in str(error.value) and "secret-key" not in str(error.value) and "boom" not in str(error.value)


def test_timeout_and_network_errors_become_llm_error():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(LLMError, match="timed out"):
        AnthropicClient("k", "m", transport=transport(timeout)).generate("s", "u")
    with pytest.raises(LLMError, match="could not reach"):
        AnthropicClient("k", "m", transport=transport(refused)).generate("s", "u")


def test_empty_reply_is_an_error():
    client = AnthropicClient("k", "m", transport=transport(lambda r: httpx.Response(200, json={"content": []})))
    with pytest.raises(LLMError, match="empty"):
        client.generate("s", "u")


def test_openai_compatible_request_and_reply():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers.get("authorization"), json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": " Answer [C1] "}}]})

    client = OpenAICompatibleClient("abc", "gpt-x", "http://localhost:11434/v1/", transport=transport(handler))
    assert client.generate("SYS", "USR") == "Answer [C1]"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions" and seen["auth"] == "Bearer abc"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


def test_openai_compatible_without_key_sends_no_auth_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    OpenAICompatibleClient("", "llama", "http://localhost:11434/v1", transport=transport(handler)).generate("s", "u")
    assert seen["auth"] is None


def test_openai_compatible_malformed_reply_is_an_error():
    client = OpenAICompatibleClient("k", "m", "http://x/v1", transport=transport(lambda r: httpx.Response(200, json={"oops": 1})))
    with pytest.raises(LLMError, match="unexpected"):
        client.generate("s", "u")


@pytest.mark.parametrize("env, expected", [
    ({"LLM_PROVIDER": "none"}, None),
    ({}, None),
    ({"LLM_PROVIDER": "anthropic", "LLM_API_KEY": ""}, None),                 # missing key -> evidence-only mode
    ({"LLM_PROVIDER": "openai_compatible", "LLM_MODEL": "m"}, None),          # missing base url
    ({"LLM_PROVIDER": "something-else"}, None),
    ({"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "k"}, "anthropic"),
    ({"LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": "http://x/v1", "LLM_MODEL": "m"}, "openai_compatible"),
])
def test_provider_selection_from_environment(monkeypatch, env, expected):
    for name in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    client = get_llm_client()
    assert (client.name if client else None) == expected


def test_default_anthropic_model_is_used_when_none_is_set(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert get_llm_client().model == config.DEFAULT_ANTHROPIC_MODEL
