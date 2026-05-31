"""Tests for OllamaV3Backend using ``pytest-httpx`` to mock Ollama.

We don't talk to a live Ollama in CI; pytest-httpx intercepts HTTP
calls and lets us assert on request payloads and inject fake responses.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from pytest_httpx import HTTPXMock

from ski_model.v3 import PROMPT_TEMPLATE_HASH, STRUCTURED_GRAMMAR_HASH, OllamaV3Backend


def _backend(base_url: str = "http://ollama-test:11434") -> OllamaV3Backend:
    return OllamaV3Backend(
        base_url=base_url,
        model_name="test-model:1b",
        seed=42,
        max_tokens=256,
        prompt_template_hash=PROMPT_TEMPLATE_HASH,
        structured_grammar_hash=STRUCTURED_GRAMMAR_HASH,
    )


def _good_response_text() -> str:
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


# ---- Provenance / model weight hash -------------------------------------------


class TestProvenance:
    def test_model_weight_hash_uses_ollama_digest_when_available(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {"digest": "sha256:abc123def456"}},
        )
        backend = _backend()
        assert backend.model_weight_hash == "sha256:abc123def456"

    def test_model_weight_hash_falls_back_when_show_404s(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            status_code=404,
            json={"error": "model not found"},
        )
        backend = _backend()
        # Vendor commitment fallback — sha256("ollama:test-model:1b")
        assert backend.model_weight_hash.startswith("sha256:")
        assert len(backend.model_weight_hash) == 71

    def test_model_weight_hash_falls_back_when_digest_missing(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {}, "modelfile": "FROM ..."},
        )
        backend = _backend()
        assert backend.model_weight_hash.startswith("sha256:")


# ---- Request shape ------------------------------------------------------------


class TestRequestPayload:
    @pytest.mark.asyncio
    async def test_request_is_deterministic_and_json_format(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {"digest": "sha256:zzz"}},
        )
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/generate",
            method="POST",
            json={"response": _good_response_text()},
        )

        backend = _backend()
        await backend.evaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot={"version": "v1", "obligations": []},
            seed=7,
        )

        # Last request is /api/generate; verify its body.
        requests = httpx_mock.get_requests()
        generate_req = [r for r in requests if r.url.path == "/api/generate"][0]
        body: Dict[str, Any] = json.loads(generate_req.content)
        assert body["model"] == "test-model:1b"
        assert body["stream"] is False
        assert body["format"] == "json"
        opts = body["options"]
        assert opts["temperature"] == 0
        assert opts["seed"] == 7  # The seed kwarg from evaluate(), not the constructor.
        assert opts["num_predict"] == 256
        assert opts["top_p"] == 1.0
        assert opts["top_k"] == 1
        # The prompt must include the canonical PROMPT_TEMPLATE markers.
        assert "MEASUREMENT:" in body["prompt"]
        assert "KG SNAPSHOT:" in body["prompt"]


# ---- Response parsing ---------------------------------------------------------


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_happy_path_parses_structured_output(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {"digest": "sha256:zzz"}},
        )
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/generate",
            method="POST",
            json={"response": _good_response_text()},
        )

        backend = _backend()
        result = await backend.evaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot={"version": "v1", "obligations": []},
            seed=0,
        )
        assert result["verdict"] == "CLEAR"
        assert result["kg_citations"][0]["node_id"] == "ob.x"

    @pytest.mark.asyncio
    async def test_malformed_json_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {"digest": "sha256:zzz"}},
        )
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/generate",
            method="POST",
            json={"response": "this is not JSON"},
        )

        backend = _backend()
        result = await backend.evaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot={"version": "v1", "obligations": []},
            seed=0,
        )
        assert result["verdict"] == "DISCRETIONARY"
        assert "not valid JSON" in result["reasoning"]
        assert result["formalizable_assertions"] == []

    @pytest.mark.asyncio
    async def test_missing_required_keys_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {"digest": "sha256:zzz"}},
        )
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/generate",
            method="POST",
            json={"response": json.dumps({"verdict": "CLEAR"})},  # missing other keys
        )

        backend = _backend()
        result = await backend.evaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot={"version": "v1", "obligations": []},
            seed=0,
        )
        assert result["verdict"] == "DISCRETIONARY"
        assert "missing required keys" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_non_taxonomy_verdict_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {"digest": "sha256:zzz"}},
        )
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/generate",
            method="POST",
            json={
                "response": json.dumps(
                    {
                        "verdict": "MAYBE",
                        "reasoning": "uncertain",
                        "kg_citations": [],
                        "formalizable_assertions": [],
                    }
                )
            },
        )

        backend = _backend()
        result = await backend.evaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot={"version": "v1", "obligations": []},
            seed=0,
        )
        assert result["verdict"] == "DISCRETIONARY"
        assert "not in the five-verdict taxonomy" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_transport_error_yields_discretionary(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/show",
            method="POST",
            json={"details": {"digest": "sha256:zzz"}},
        )
        # /api/generate returns 503 — transport-level error.
        httpx_mock.add_response(
            url="http://ollama-test:11434/api/generate",
            method="POST",
            status_code=503,
        )

        backend = _backend()
        result = await backend.evaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot={"version": "v1", "obligations": []},
            seed=0,
        )
        assert result["verdict"] == "DISCRETIONARY"
        assert "transport error" in result["reasoning"]
