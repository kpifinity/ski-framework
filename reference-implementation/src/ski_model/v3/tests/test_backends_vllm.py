"""Tests for VLLMV3Backend using ``pytest-httpx`` to mock the vLLM server."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from pytest_httpx import HTTPXMock

from ski_model.v3 import PROMPT_TEMPLATE_HASH, STRUCTURED_GRAMMAR_HASH, VLLMV3Backend

BASE = "http://vllm-test:8000"


def _mock_models(httpx_mock: HTTPXMock, ids: list[str] | None = None) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/v1/models",
        json={"object": "list", "data": [{"id": i} for i in (ids or ["test/model-7b"])]},
    )


def _backend(httpx_mock: HTTPXMock, *, sha: str | None = None) -> VLLMV3Backend:
    _mock_models(httpx_mock)
    return VLLMV3Backend(
        base_url=BASE,
        model_name="test/model-7b",
        seed=42,
        max_tokens=1536,
        prompt_template_hash=PROMPT_TEMPLATE_HASH,
        structured_grammar_hash=STRUCTURED_GRAMMAR_HASH,
        model_file_sha256=sha,
    )


def _chat_response(content: str) -> Dict[str, Any]:
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
    }


def _good_content() -> str:
    return json.dumps(
        {
            "verdict": "CLEAR",
            "reasoning": "Within limit.",
            "kg_citations": [{"node_id": "ob.x", "version": "v1", "role": "obligation"}],
            "formalizable_assertions": [
                {
                    "predicate": "must_not_exceed",
                    "metric": "so2_ppm",
                    "value": 100,
                    "observed": 50,
                    "satisfied": True,
                    "obligation_id": "ob.x",
                }
            ],
        }
    )


_SNAPSHOT = {"version": "v1", "obligations": [{"id": "ob.x", "metric": "so2_ppm"}], "definitions": []}


class TestProvenance:
    def test_operator_digest_is_the_anchor_when_supplied(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock, sha="AB" * 32)
        assert b.model_weight_hash == "sha256:" + "ab" * 32

    def test_vendor_commitment_fallback_without_digest(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        assert b.model_weight_hash.startswith("sha256:")
        assert b.model_weight_hash != "sha256:" + "ab" * 32

    def test_models_endpoint_unreachable_still_constructs(self, httpx_mock: HTTPXMock) -> None:
        import httpx

        httpx_mock.add_exception(httpx.ConnectError("boom"), url=f"{BASE}/v1/models")
        # construction must not raise; provenance falls back
        b = VLLMV3Backend(
            base_url=BASE,
            model_name="test/model-7b",
            seed=42,
            max_tokens=1536,
            prompt_template_hash=PROMPT_TEMPLATE_HASH,
            structured_grammar_hash=STRUCTURED_GRAMMAR_HASH,
        )
        assert b.model_weight_hash.startswith("sha256:")

    def test_prompt_and_grammar_hashes_are_framework_constants(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        assert b.prompt_template_hash == PROMPT_TEMPLATE_HASH
        assert b.structured_grammar_hash == STRUCTURED_GRAMMAR_HASH


class TestRequestPayload:
    @pytest.mark.asyncio
    async def test_request_is_deterministic_with_guided_json(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        httpx_mock.add_response(url=f"{BASE}/v1/chat/completions", json=_chat_response(_good_content()))
        await b.evaluate(measurement={"so2_ppm": 50}, kg_snapshot=_SNAPSHOT, seed=42)
        request = httpx_mock.get_requests(url=f"{BASE}/v1/chat/completions")[0]
        payload = json.loads(request.content)
        assert payload["temperature"] == 0
        assert payload["seed"] == 42
        assert payload["top_p"] == 1.0
        assert payload["max_tokens"] == 1536
        assert payload["guided_json"]["required"] == [
            "verdict",
            "reasoning",
            "kg_citations",
            "formalizable_assertions",
        ]
        prompt = payload["messages"][0]["content"]
        assert "ob.x" in prompt and "so2_ppm" in prompt


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_happy_path_parses_structured_output(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        httpx_mock.add_response(url=f"{BASE}/v1/chat/completions", json=_chat_response(_good_content()))
        out = await b.evaluate(measurement={"so2_ppm": 50}, kg_snapshot=_SNAPSHOT, seed=42)
        assert out["verdict"] == "CLEAR"
        assert out["formalizable_assertions"][0]["observed"] == 50

    @pytest.mark.asyncio
    async def test_malformed_json_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        httpx_mock.add_response(url=f"{BASE}/v1/chat/completions", json=_chat_response("{not json"))
        out = await b.evaluate(measurement={"so2_ppm": 50}, kg_snapshot=_SNAPSHOT, seed=42)
        assert out["verdict"] == "DISCRETIONARY"
        assert out["formalizable_assertions"] == []

    @pytest.mark.asyncio
    async def test_non_taxonomy_verdict_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        bad = json.loads(_good_content())
        bad["verdict"] = "MAYBE"
        httpx_mock.add_response(url=f"{BASE}/v1/chat/completions", json=_chat_response(json.dumps(bad)))
        out = await b.evaluate(measurement={"so2_ppm": 50}, kg_snapshot=_SNAPSHOT, seed=42)
        assert out["verdict"] == "DISCRETIONARY"

    @pytest.mark.asyncio
    async def test_empty_choices_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        httpx_mock.add_response(url=f"{BASE}/v1/chat/completions", json={"choices": []})
        out = await b.evaluate(measurement={"so2_ppm": 50}, kg_snapshot=_SNAPSHOT, seed=42)
        assert out["verdict"] == "DISCRETIONARY"

    @pytest.mark.asyncio
    async def test_transport_error_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        b = _backend(httpx_mock)
        httpx_mock.add_response(url=f"{BASE}/v1/chat/completions", status_code=503)
        out = await b.evaluate(measurement={"so2_ppm": 50}, kg_snapshot=_SNAPSHOT, seed=42)
        assert out["verdict"] == "DISCRETIONARY"
        assert "transport error" in out["reasoning"]


class TestFactory:
    def test_factory_builds_vllm(self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
        from ski_model.v3.backends import build_backend

        _mock_models(httpx_mock)
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "vllm")
        monkeypatch.setenv("VLLM_BASE_URL", BASE)
        monkeypatch.setenv("SKI_MODEL_NAME", "test/model-7b")
        b = build_backend()
        assert b.name == "vllm-v3"
