"""Exercise the real OpenAI SDK code path against a fake HTTP transport."""

import json

import httpx
import pytest
from openai import OpenAI

from backend.config import settings
from backend.services.llm_service import LLMService


def make_service(handler, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    service = LLMService()
    service._client = OpenAI(
        api_key="sk-test",
        base_url="https://fake.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return service


def completion(content):
    return httpx.Response(200, json={
        "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
    })


def test_generate_content_sends_context(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return completion("  Hello.  ")

    service = make_service(handler, monkeypatch)
    assert service.generate_content("Summarise", context="From a: facts") == "Hello."
    assert seen["model"] == settings.openai_model
    assert "From a: facts" in seen["messages"][1]["content"]
    assert "max_completion_tokens" in seen and "temperature" not in seen


def test_retries_with_max_tokens_for_older_models(monkeypatch):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if "max_completion_tokens" in body:
            return httpx.Response(400, json={"error": {
                "message": "Unsupported parameter: 'max_completion_tokens'", "type": "invalid_request_error"}})
        return completion("ok")

    service = make_service(handler, monkeypatch)
    assert service.generate_content("hi") == "ok"
    assert len(calls) == 2 and "max_tokens" in calls[1]


def test_placeholder_values_are_normalised(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        # Wrapped in prose, with a list, a number and a missing key.
        return completion('Here you go:\n{"POINTS": ["a", "b"], "COUNT": 3, "EXTRA": "x"}')

    service = make_service(handler, monkeypatch)
    values = service.generate_placeholder_values(
        "report", ["TITLE", "POINTS", "COUNT", "MISSING"], known_values={"TITLE": "Fixed"}
    )
    assert values == {"TITLE": "Fixed", "POINTS": "- a\n- b", "COUNT": "3", "MISSING": ""}


def test_non_json_reply_is_an_error(monkeypatch):
    service = make_service(lambda request: completion("sorry, no"), monkeypatch)
    with pytest.raises(ValueError):
        service.generate_placeholder_values("report", ["TITLE"])


def test_embeddings_are_batched(monkeypatch):
    sizes = []

    def handler(request):
        inputs = json.loads(request.content)["input"]
        sizes.append(len(inputs))
        return httpx.Response(200, json={
            "object": "list", "model": "e", "usage": {"prompt_tokens": 0, "total_tokens": 0},
            "data": [{"object": "embedding", "index": i, "embedding": [float(i), 1.0]}
                     for i in range(len(inputs))],
        })

    service = make_service(handler, monkeypatch)
    vectors = service.get_embeddings([f"t{i}" for i in range(200)])
    assert sizes == [96, 96, 8] and len(vectors) == 200 and vectors[97] == [1.0, 1.0]


def test_unknown_model_gives_a_clear_error(monkeypatch):
    from backend.services.llm_service import LLMModelNotFound

    def handler(request):
        return httpx.Response(404, json={"error": {"message": "models/x is not found", "code": 404}})

    service = make_service(handler, monkeypatch)
    with pytest.raises(LLMModelNotFound, match="OPENAI_MODEL"):
        service.generate_content("hi")
    with pytest.raises(LLMModelNotFound, match="OPENAI_EMBEDDING_MODEL"):
        service.get_embeddings(["hi"])


def test_list_models(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": "b-model", "object": "model", "created": 0, "owned_by": "x"},
            {"id": "a-model", "object": "model", "created": 0, "owned_by": "x"}]})

    service = make_service(handler, monkeypatch)
    assert service.list_models() == ["a-model", "b-model"]


def test_falls_back_to_next_model_when_busy(monkeypatch):
    seen = []

    def handler(request):
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "main":
            return httpx.Response(503, json={"error": {"message": "overloaded", "code": 503}})
        if model == "second":
            return httpx.Response(429, json={"error": {"message": "quota", "code": 429}})
        return completion(f"from {model}")

    monkeypatch.setattr(settings, "openai_model", "main")
    monkeypatch.setattr(settings, "openai_fallback_models", "second, third")
    service = make_service(handler, monkeypatch)
    assert service.generate_content("hi") == "from third"
    assert seen == ["main", "second", "third"]


def test_all_models_failing_is_a_clear_error(monkeypatch):
    from backend.services.llm_service import LLMUnavailable

    monkeypatch.setattr(settings, "openai_model", "main")
    monkeypatch.setattr(settings, "openai_fallback_models", "second")
    service = make_service(lambda r: httpx.Response(503, json={"error": {"message": "x"}}), monkeypatch)
    with pytest.raises(LLMUnavailable, match="main: InternalServerError; second: InternalServerError"):
        service.generate_content("hi")


def test_bad_request_is_not_retried_on_other_models(monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(400, json={"error": {"message": "invalid prompt"}})

    monkeypatch.setattr(settings, "openai_model", "main")
    monkeypatch.setattr(settings, "openai_fallback_models", "second")
    service = make_service(handler, monkeypatch)
    with pytest.raises(Exception):
        service.generate_content("hi")
    assert seen == ["main"]


def test_embeddings_request_dimensions_and_fall_back(monkeypatch):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body.get("dimensions"))
        if "dimensions" in body:
            return httpx.Response(400, json={"error": {"message": "Unknown parameter: dimensions"}})
        return httpx.Response(200, json={
            "object": "list", "model": "e", "usage": {"prompt_tokens": 0, "total_tokens": 0},
            "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]}]})

    service = make_service(handler, monkeypatch)
    assert service.get_embeddings(["x"], dimensions=2) == [[1.0, 0.0, 0.0]]
    assert seen == [2, None]
