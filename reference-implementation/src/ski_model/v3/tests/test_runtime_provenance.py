"""v3.2.0 backend truth at the API surface (C4).

* ``/api/health`` reports a ``provenance`` object naming the backend that
  actually serves verdicts, its model ID, the model weight hash and
  whether that hash was verified against an operator pin.
* Every verdict envelope's ``model_provenance`` carries the optional
  ``inference_backend`` and ``model_hash_verified`` fields.
* Envelopes from v3.1.x (no optional fields) still validate and
  re-serialise byte-identically, so stored envelope hashes stay stable.
* The runtime refuses to start on an implicit / un-opted-in FakeLLM.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from ski_model import server
from ski_model.kg_loader import KnowledgeGraph
from ski_model.v3 import FakeLLM, ModelProvenance, V3Evaluator, V3VerdictEnvelope
from ski_model.v3.backends import BackendConfigError

_H = "sha256:" + "a" * 64


class _Ledger:
    async def append_v3(self, **kwargs: Any) -> None:
        return None


class _PinnedBackend(FakeLLM):
    """A stand-in for a real backend whose weights matched an operator pin."""

    name = "pinned-test"
    model_id = "org/model-7b"
    model_hash_verified = True
    model_hash_source = "verified-file-digest"


def _install(backend: FakeLLM) -> None:
    server.state.knowledge_graph = KnowledgeGraph(
        version="v-prov",
        rules=[{"id": "so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}],
        tag_registry={},
        metadata={"version": "v-prov"},
        signature_verified=True,
    )
    server.state.ledger = _Ledger()  # type: ignore[assignment]
    server.state.llm_backend = backend
    server.state.evaluator = V3Evaluator(llm=backend, kg_version_hash=_H, decoder_seed=0)
    server.state.telemetry_buffer = None
    server.state.agreement_monitor = None
    server.state.max_clock_skew_seconds = 0


def _health() -> Dict[str, Any]:
    resp = TestClient(server.app).get("/api/health")
    assert resp.status_code == 200
    body: Dict[str, Any] = resp.json()
    return body


def test_health_reports_fake_backend_unverified() -> None:
    _install(FakeLLM())
    prov = _health()["provenance"]
    assert prov["backend"] == "fake-llm"
    assert prov["model_id"] == "fake-llm"
    assert prov["model_weight_hash"] == "sha256:" + "f" * 64
    assert prov["model_hash_verified"] is False


def test_health_reports_verified_backend() -> None:
    _install(_PinnedBackend())
    prov = _health()["provenance"]
    # /api/health merges backend provenance (this workstream) with KG-trust
    # provenance (wp0a-trust); assert the backend keys are present and correct
    # rather than exact-equality, which would break as trust keys are added.
    backend_keys = {
        "backend": "pinned-test",
        "model_id": "org/model-7b",
        "model_weight_hash": "sha256:" + "f" * 64,
        "model_hash_verified": True,
        "model_hash_source": "verified-file-digest",
    }
    assert backend_keys.items() <= prov.items()


def test_health_before_backend_is_built() -> None:
    _install(FakeLLM())
    server.state.llm_backend = None
    prov = _health()["provenance"]
    assert prov["backend"] is None
    assert prov["model_hash_verified"] is False


@pytest.mark.parametrize(
    ("backend", "expected_name", "expected_verified"),
    [(FakeLLM(), "fake-llm", False), (_PinnedBackend(), "pinned-test", True)],
)
def test_envelope_carries_backend_and_hash_verification(
    backend: FakeLLM, expected_name: str, expected_verified: bool
) -> None:
    _install(backend)
    resp = TestClient(server.app).post(
        "/api/evaluate",
        json={
            "measurement_id": "m-prov",
            "timestamp": "2026-01-15T12:00:00Z",
            "subject": "s",
            "measurement": {"so2_ppm": 50},
        },
    )
    assert resp.status_code == 200, resp.text
    prov = resp.json()["model_provenance"]
    assert prov["inference_backend"] == expected_name
    assert prov["model_hash_verified"] is expected_verified
    assert V3VerdictEnvelope.model_validate(resp.json()).model_provenance.inference_backend == expected_name


def test_truthy_non_bool_is_not_treated_as_verified() -> None:
    class _Sloppy(FakeLLM):
        model_hash_verified = "yes"

    _install(_Sloppy())
    assert _health()["provenance"]["model_hash_verified"] is False


def test_v31_shape_provenance_reserialises_byte_identically() -> None:
    v31 = {
        "model_weight_hash": _H,
        "kg_version_hash": _H,
        "prompt_template_id": "ski.v3.evaluate.1",
        "prompt_template_hash": _H,
        "decoder_seed": 0,
        "structured_grammar_hash": _H,
    }
    dumped = ModelProvenance.model_validate(v31).model_dump(mode="json")
    canonical = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
    assert canonical == json.dumps(v31, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == (
        hashlib.sha256(json.dumps(v31, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


def test_unknown_provenance_fields_are_still_rejected() -> None:
    with pytest.raises(ValueError):
        ModelProvenance.model_validate(
            {
                "model_weight_hash": _H,
                "kg_version_hash": _H,
                "prompt_template_id": "x",
                "prompt_template_hash": _H,
                "decoder_seed": 0,
                "structured_grammar_hash": _H,
                "model_hash_verifed": True,  # typo => extra field
            }
        )


@pytest.mark.asyncio
async def test_lifespan_refuses_to_start_on_unopted_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_kg(*_a: Any, **_k: Any) -> KnowledgeGraph:
        raise FileNotFoundError("no KG in this test")

    monkeypatch.setattr(server, "load_signed_kg", _no_kg)
    monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
    monkeypatch.delenv("SKI_ALLOW_FAKE_LLM", raising=False)
    with pytest.raises(BackendConfigError, match="SKI_ALLOW_FAKE_LLM"):
        async with server.lifespan(server.app):
            pass  # pragma: no cover - must not get here


@pytest.mark.asyncio
async def test_lifespan_refuses_conflicting_backend_names(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_kg(*_a: Any, **_k: Any) -> KnowledgeGraph:
        raise FileNotFoundError("no KG in this test")

    monkeypatch.setattr(server, "load_signed_kg", _no_kg)
    monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
    monkeypatch.setenv("SKI_INFERENCE_BACKEND", "ollama")
    monkeypatch.setenv("SKI_ALLOW_FAKE_LLM", "true")
    with pytest.raises(BackendConfigError, match="disagree"):
        async with server.lifespan(server.app):
            pass  # pragma: no cover - must not get here
