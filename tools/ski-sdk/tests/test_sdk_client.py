"""SKIClient request/response handling and error mapping (mocked transport)."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock
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


def test_evaluate_parses_envelope_and_sends_api_key(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/evaluate", method="POST", json=_ENVELOPE)
    with SKIClient(BASE, api_key="s3cret") as client:
        env = client.evaluate(
            measurement_id="m1",
            timestamp="2026-06-05T12:00:00Z",
            subject="emissions",
            measurement={"so2_ppm": 150},
        )
    assert env.verdict == "FLAG"
    assert env.verifier_result.status == "AGREED"
    sent = httpx_mock.get_requests()[0]
    assert sent.headers["x-api-key"] == "s3cret"


def test_401_maps_to_auth_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/api/evaluate",
        method="POST",
        status_code=401,
        json={"detail": "Invalid or missing API key."},
    )
    with SKIClient(BASE, api_key="bad") as client, pytest.raises(SKIAuthError):
        client.evaluate(measurement_id="m1", timestamp="t", subject="s", measurement={})


def test_503_maps_to_service_unavailable(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/api/health", method="GET", status_code=503, json={"detail": "No KG loaded."}
    )
    with SKIClient(BASE, api_key="x", max_retries=0) as client, pytest.raises(SKIServiceUnavailable):
        client.health()
