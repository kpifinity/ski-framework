"""SKIClient request/response handling and error mapping.

Uses httpx's built-in MockTransport (injected via the client's ``transport``
parameter) — no pytest-httpx dependency, and version-agnostic across httpx 0.27/0.28.
"""

from __future__ import annotations

import httpx
import pytest
from ski_sdk import SKIAuthError, SKIClient, SKIServiceUnavailable

BASE = "https://ski.test:8000"

_ENVELOPE = {
    "verdict": "FLAG",
    "reasoning": "breach",
    "kg_citations": [],
    "formalizable_assertions": [],
    "verifier_result": {"status": "AGREED", "checked_assertions": 1, "divergences": []},
    "model_provenance": {
        "model_weight_hash": "sha256:" + "f" * 64,
        "kg_version_hash": "sha256:" + "a" * 64,
        "prompt_template_id": "ski.v3.evaluate.1",
        "prompt_template_hash": "sha256:" + "1" * 64,
        "decoder_seed": 0,
        "structured_grammar_hash": "sha256:" + "2" * 64,
    },
    "transcript_ref": "transcript:abc",
    "notes": [],
}


def _client(handler, **kw) -> SKIClient:
    return SKIClient(BASE, api_key=kw.pop("api_key", "s3cret"), transport=httpx.MockTransport(handler), **kw)


def test_evaluate_parses_envelope_and_sends_api_key() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_ENVELOPE)

    with _client(handler) as client:
        env = client.evaluate(
            measurement_id="m1",
            timestamp="2026-06-05T12:00:00Z",
            subject="emissions",
            measurement={"so2_ppm": 150},
        )
    assert env.verdict == "FLAG"
    assert env.verifier_result.status == "AGREED"
    assert seen[0].headers["x-api-key"] == "s3cret"
    assert seen[0].url.path == "/api/evaluate"


def test_401_maps_to_auth_error() -> None:
    with (
        _client(
            lambda r: httpx.Response(401, json={"detail": "Invalid or missing API key."}), api_key="bad"
        ) as client,
        pytest.raises(SKIAuthError),
    ):
        client.evaluate(measurement_id="m1", timestamp="t", subject="s", measurement={})


def test_503_maps_to_service_unavailable() -> None:
    with (
        _client(lambda r: httpx.Response(503, json={"detail": "No KG loaded."}), max_retries=0) as client,
        pytest.raises(SKIServiceUnavailable),
    ):
        client.health()
