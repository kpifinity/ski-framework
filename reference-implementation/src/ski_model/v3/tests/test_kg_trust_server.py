"""Server-level tests for KG trust anchors, hot-load gating and the
transcript-key guard (framework v3.2.0; findings C2 and C6).

Uses the same in-memory-double + ``TestClient`` harness as
``test_endpoint.py`` (no live database, KG file or ``/app`` key path). The
startup tests drive the real ``lifespan`` with the ledger stubbed out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from ski_model import server
from ski_model.kg_loader import (
    KGTrustError,
    KGTrustPolicy,
    KnowledgeGraph,
    TrustAnchor,
    ed25519_key_id,
)
from ski_model.v3 import FakeLLM, TranscriptSigner, V3Evaluator, V3VerdictEnvelope
from ski_model.v3.signing import TranscriptKeyError

_ADMIN_KEY = "admin-" + "a" * 58
_RULES: List[Dict[str, Any]] = [
    {"id": "energy.so2.lte_100ppm", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
]
_TAGS: Dict[str, str] = {"emissions": "energy.so2.lte_100ppm"}


def _public_pem(key: Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )


def _signed_kg(key: Ed25519PrivateKey, *, version: str = "kgtrust-0001", cap: int = 100) -> Dict[str, Any]:
    metadata = {"version": version}
    rules = [dict(_RULES[0], value=cap)]
    canonical = json.dumps(
        {"metadata": metadata, "rules": rules, "tag_registry": _TAGS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        "metadata": metadata,
        "rules": rules,
        "tag_registry": _TAGS,
        "signature": {
            "algorithm": "ed25519",
            "public_key_pem": _public_pem(key),
            "value_hex": key.sign(canonical).hex(),
        },
    }


def _policy(*keys: Ed25519PrivateKey) -> KGTrustPolicy:
    return KGTrustPolicy(anchors=tuple(TrustAnchor.from_public_key(k.public_key()) for k in keys))


@dataclass
class _FakeLedger:
    appended: List[Dict[str, Any]] = field(default_factory=list)
    _engine: Any = None

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def append_v3(self, **kwargs: Any) -> None:
        self.appended.append(kwargs)


_STATE_ATTRS = (
    "knowledge_graph",
    "kg_trust_policy",
    "tag_registry",
    "ledger",
    "llm_backend",
    "evaluator",
    "telemetry_buffer",
    "kg_version_hash",
    "transcript_signer",
    "agreement_monitor",
    "max_clock_skew_seconds",
)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot server.state and the trust/hot-load env; restore afterwards."""
    saved = {name: getattr(server.state, name) for name in _STATE_ATTRS}
    for name in (
        "SKI_KG_TRUST_ANCHORS",
        "SKI_KG_ALLOW_UNANCHORED",
        "SKI_ENABLE_KG_HOT_LOAD",
        "SKI_ADMIN_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    for name, value in saved.items():
        setattr(server.state, name, value)


def _install(kg: Optional[KnowledgeGraph], policy: KGTrustPolicy, tmp_path: Path) -> _FakeLedger:
    ledger = _FakeLedger()
    llm = FakeLLM()
    server.state.kg_trust_policy = policy
    server.state.knowledge_graph = kg
    server.state.ledger = ledger  # type: ignore[assignment]
    server.state.llm_backend = llm
    server.state.telemetry_buffer = None
    server.state.agreement_monitor = None
    server.state.max_clock_skew_seconds = 0
    server.state.transcript_signer = TranscriptSigner.auto_provision(
        tmp_path / "t.ed25519", allow_generation=True
    )
    server.state.kg_version_hash = server._compute_kg_version_hash(kg) if kg else "sha256:" + "0" * 64
    server.state.evaluator = V3Evaluator(
        llm=llm,
        kg_version_hash=server.state.kg_version_hash,
        kg_signer_key_id=kg.signer_key_id if kg else None,
        kg_trust=kg.kg_trust if kg else None,
    )
    return ledger


def _measurement(value: int = 50, *, ts: str = "2026-01-15T12:00:00Z") -> Dict[str, Any]:
    return {
        "measurement_id": f"m-{value}",
        "timestamp": ts,
        "subject": "emissions",
        "measurement": {"so2_ppm": value},
    }


def _enable_hot_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKI_ENABLE_KG_HOT_LOAD", "true")
    monkeypatch.setenv("SKI_ADMIN_API_KEY", _ADMIN_KEY)


# ---- Hot-load gating ------------------------------------------------------------


class TestHotLoadGating:
    def test_hot_load_is_off_by_default(self, tmp_path: Path) -> None:
        key = Ed25519PrivateKey.generate()
        _install(None, _policy(key), tmp_path)
        resp = TestClient(server.app).post(
            "/api/kg/load", json=_signed_kg(key), headers={"X-SKI-Admin-Key": _ADMIN_KEY}
        )
        assert resp.status_code == 403
        assert "SKI_ENABLE_KG_HOT_LOAD" in resp.json()["detail"]
        assert server.state.knowledge_graph is None

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"X-SKI-Admin-Key": "wrong"},
            {"X-API-Key": _ADMIN_KEY},  # right value, wrong (normal API key) header
        ],
    )
    def test_wrong_or_missing_admin_credential_is_401(
        self, headers: Dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = Ed25519PrivateKey.generate()
        _install(None, _policy(key), tmp_path)
        _enable_hot_load(monkeypatch)
        resp = TestClient(server.app).post("/api/kg/load", json=_signed_kg(key), headers=headers)
        assert resp.status_code == 401
        assert server.state.knowledge_graph is None

    def test_normal_api_key_is_never_the_admin_credential(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = Ed25519PrivateKey.generate()
        _install(None, _policy(key), tmp_path)
        monkeypatch.setenv("SKI_ENABLE_KG_HOT_LOAD", "true")
        monkeypatch.setattr(server, "_API_KEY", "sidecar-key")
        resp = TestClient(server.app).post(
            "/api/kg/load", json=_signed_kg(key), headers={"X-SKI-Admin-Key": "sidecar-key"}
        )
        assert resp.status_code == 503  # no SKI_ADMIN_API_KEY configured
        monkeypatch.setenv("SKI_ADMIN_API_KEY", "sidecar-key")
        resp = TestClient(server.app).post(
            "/api/kg/load", json=_signed_kg(key), headers={"X-SKI-Admin-Key": "sidecar-key"}
        )
        assert resp.status_code == 503
        assert "must differ from API_KEY" in resp.json()["detail"]
        assert server.state.knowledge_graph is None

    def test_anchored_kg_hot_loads_and_envelope_carries_signer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = Ed25519PrivateKey.generate()
        _install(None, _policy(key), tmp_path)
        _enable_hot_load(monkeypatch)
        client = TestClient(server.app)
        resp = client.post("/api/kg/load", json=_signed_kg(key), headers={"X-SKI-Admin-Key": _ADMIN_KEY})
        assert resp.status_code == 200, resp.text
        assert resp.json()["kg_trust"] == "anchored"
        assert resp.json()["kg_signer_key_id"] == ed25519_key_id(key.public_key())

        resp = client.post("/api/evaluate", json=_measurement(50))
        assert resp.status_code == 200, resp.text
        envelope = V3VerdictEnvelope.model_validate(resp.json())
        assert envelope.model_provenance.kg_signer_key_id == ed25519_key_id(key.public_key())
        assert envelope.model_provenance.kg_trust == "anchored"

    def test_hot_load_of_kg_resigned_with_non_anchor_key_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        anchor = Ed25519PrivateKey.generate()
        original = KnowledgeGraph.from_dict(_signed_kg(anchor), require_signature=True, trust=_policy(anchor))
        _install(original, _policy(anchor), tmp_path)
        _enable_hot_load(monkeypatch)
        forged = _signed_kg(Ed25519PrivateKey.generate(), version="kgtrust-evil", cap=10_000)
        resp = TestClient(server.app).post(
            "/api/kg/load", json=forged, headers={"X-SKI-Admin-Key": _ADMIN_KEY}
        )
        assert resp.status_code == 400
        assert "not a configured trust anchor" in resp.json()["detail"]
        assert server.state.knowledge_graph is original

    def test_hot_load_without_signature_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = Ed25519PrivateKey.generate()
        _install(None, _policy(key), tmp_path)
        _enable_hot_load(monkeypatch)
        unsigned = {k: v for k, v in _signed_kg(key).items() if k != "signature"}
        resp = TestClient(server.app).post(
            "/api/kg/load", json=unsigned, headers={"X-SKI-Admin-Key": _ADMIN_KEY}
        )
        assert resp.status_code == 400

    def test_hot_load_without_startup_policy_reads_env_and_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = Ed25519PrivateKey.generate()
        _install(None, _policy(key), tmp_path)
        server.state.kg_trust_policy = None
        _enable_hot_load(monkeypatch)
        resp = TestClient(server.app).post(
            "/api/kg/load", json=_signed_kg(key), headers={"X-SKI-Admin-Key": _ADMIN_KEY}
        )
        assert resp.status_code == 400
        assert "No KG trust anchors configured" in resp.json()["detail"]


# ---- Health + envelope provenance ------------------------------------------------


class TestProvenance:
    def test_health_reports_kg_trust_signer_anchors_and_transcript_key(self, tmp_path: Path) -> None:
        key = Ed25519PrivateKey.generate()
        kg = KnowledgeGraph.from_dict(_signed_kg(key), require_signature=True, trust=_policy(key))
        _install(kg, _policy(key), tmp_path)
        body = TestClient(server.app).get("/api/health").json()
        assert body["kg_signature_verified"] is True
        prov = body["provenance"]
        assert prov["kg_trust"] == "anchored"
        assert prov["kg_signer_key_id"] == ed25519_key_id(key.public_key())
        assert prov["kg_trust_anchors"] == [ed25519_key_id(key.public_key())]
        assert prov["kg_version_hash"] == server.state.kg_version_hash
        assert prov["transcript_key_id"] == server.state.transcript_signer.key_id  # type: ignore[union-attr]

    def test_health_without_kg_reports_nulls(self, tmp_path: Path) -> None:
        _install(None, KGTrustPolicy(), tmp_path)
        prov = TestClient(server.app).get("/api/health").json()["provenance"]
        assert prov["kg_trust"] is None and prov["kg_signer_key_id"] is None
        assert prov["kg_version_hash"] is None and prov["kg_trust_anchors"] == []

    def test_unanchored_mode_is_visible_on_health_and_every_envelope(self, tmp_path: Path) -> None:
        key = Ed25519PrivateKey.generate()
        policy = KGTrustPolicy(allow_unanchored=True)
        kg = KnowledgeGraph.from_dict(_signed_kg(key), require_signature=True, trust=policy)
        _install(kg, policy, tmp_path)
        client = TestClient(server.app)
        health = client.get("/api/health").json()
        assert health["provenance"]["kg_trust"] == "unanchored"
        assert health["kg_signature_verified"] is False
        envelope = V3VerdictEnvelope.model_validate(
            client.post("/api/evaluate", json=_measurement(50)).json()
        )
        assert envelope.model_provenance.kg_trust == "unanchored"

    def test_clock_skew_short_circuit_envelope_also_carries_kg_trust(self, tmp_path: Path) -> None:
        key = Ed25519PrivateKey.generate()
        kg = KnowledgeGraph.from_dict(_signed_kg(key), require_signature=True, trust=_policy(key))
        _install(kg, _policy(key), tmp_path)
        server.state.max_clock_skew_seconds = 60
        stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        resp = TestClient(server.app).post("/api/evaluate", json=_measurement(50, ts=stale))
        envelope = V3VerdictEnvelope.model_validate(resp.json())
        assert envelope.verdict == "DISCRETIONARY"
        assert envelope.model_provenance.kg_trust == "anchored"
        assert envelope.model_provenance.kg_signer_key_id == ed25519_key_id(key.public_key())


# ---- Startup (lifespan) ----------------------------------------------------------


class _StubLedgerClient(_FakeLedger):
    def __init__(self, dsn: str) -> None:
        super().__init__()


async def _run_lifespan() -> None:
    async with server.lifespan(server.app):
        pass


def _startup_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    kg: Optional[Dict[str, Any]],
    ledger_signed: bool = False,
) -> Tuple[Path, Path]:
    kg_path = tmp_path / "kg.json"
    if kg is not None:
        kg_path.write_text(json.dumps(kg), encoding="utf-8")
    key_path = tmp_path / "keys" / "transcript.ed25519"
    monkeypatch.setenv("KG_PATH", str(kg_path))
    monkeypatch.setenv("SKI_TRANSCRIPT_KEY_PATH", str(key_path))
    monkeypatch.setattr(server, "LedgerClient", _StubLedgerClient)
    # A fresh process starts with no KG; other test modules leave one in the
    # module-level state (the autouse fixture restores it afterwards).
    server.state.knowledge_graph = None

    async def _has_signed(_engine: Any) -> bool:
        return ledger_signed

    monkeypatch.setattr(server, "_ledger_has_signed_transcripts", _has_signed)
    return kg_path, key_path


class TestStartup:
    async def test_startup_loads_anchored_kg_and_stamps_evaluator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = Ed25519PrivateKey.generate()
        _startup_env(monkeypatch, tmp_path, kg=_signed_kg(key))
        anchors = tmp_path / "anchors.pem"
        anchors.write_text(_public_pem(key), encoding="utf-8")
        monkeypatch.setenv("SKI_KG_TRUST_ANCHORS", str(anchors))
        await _run_lifespan()
        assert server.state.knowledge_graph is not None
        assert server.state.knowledge_graph.kg_trust == "anchored"
        assert server.state.evaluator is not None
        assert server.state.evaluator.kg_signer_key_id == ed25519_key_id(key.public_key())
        assert server.state.evaluator.kg_trust == "anchored"

    async def test_startup_refuses_signed_kg_without_anchors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _startup_env(monkeypatch, tmp_path, kg=_signed_kg(Ed25519PrivateKey.generate()))
        with pytest.raises(KGTrustError, match="No KG trust anchors configured"):
            await _run_lifespan()

    async def test_startup_refuses_kg_signed_by_non_anchor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _startup_env(monkeypatch, tmp_path, kg=_signed_kg(Ed25519PrivateKey.generate()))
        anchors = tmp_path / "anchors.pem"
        anchors.write_text(_public_pem(Ed25519PrivateKey.generate()), encoding="utf-8")
        monkeypatch.setenv("SKI_KG_TRUST_ANCHORS", str(anchors))
        with pytest.raises(KGTrustError, match="not a configured trust anchor"):
            await _run_lifespan()

    async def test_startup_refuses_invalid_anchor_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _startup_env(monkeypatch, tmp_path, kg=None)
        monkeypatch.setenv("SKI_KG_TRUST_ANCHORS", str(tmp_path / "missing.pem"))
        monkeypatch.setenv("SKI_KG_ALLOW_UNANCHORED", "true")
        with pytest.raises(KGTrustError, match="Cannot read KG trust-anchor bundle"):
            await _run_lifespan()

    async def test_startup_refuses_hot_load_without_admin_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _startup_env(monkeypatch, tmp_path, kg=None)
        monkeypatch.setenv("SKI_ENABLE_KG_HOT_LOAD", "true")
        with pytest.raises(RuntimeError, match="requires SKI_ADMIN_API_KEY"):
            await _run_lifespan()

    async def test_startup_with_hot_load_and_admin_key_starts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _startup_env(monkeypatch, tmp_path, kg=None)
        _enable_hot_load(monkeypatch)
        await _run_lifespan()
        assert server.state.knowledge_graph is None

    async def test_startup_refuses_missing_transcript_key_when_ledger_has_signed_transcripts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _kg, key_path = _startup_env(monkeypatch, tmp_path, kg=None, ledger_signed=True)
        monkeypatch.setenv("SKI_ALLOW_KEY_GENERATION", "true")
        with pytest.raises(TranscriptKeyError, match="already holds signed transcripts"):
            await _run_lifespan()
        assert not key_path.exists()

    async def test_startup_refuses_missing_transcript_key_without_opt_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _startup_env(monkeypatch, tmp_path, kg=None)
        monkeypatch.delenv("SKI_ALLOW_KEY_GENERATION", raising=False)
        with pytest.raises(TranscriptKeyError, match="SKI_ALLOW_KEY_GENERATION=true"):
            await _run_lifespan()

    async def test_first_boot_generates_transcript_key_with_opt_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _kg, key_path = _startup_env(monkeypatch, tmp_path, kg=None)
        monkeypatch.setenv("SKI_ALLOW_KEY_GENERATION", "true")
        await _run_lifespan()
        assert key_path.exists()
        assert server.state.transcript_signer is not None


# ---- Ledger probe ----------------------------------------------------------------


@dataclass
class _Result:
    row: Optional[Tuple[int]]

    def first(self) -> Optional[Tuple[int]]:
        return self.row


@dataclass
class _Conn:
    row: Optional[Tuple[int]]
    statements: List[str] = field(default_factory=list)

    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(str(statement))
        return _Result(self.row)


@dataclass
class _Engine:
    row: Optional[Tuple[int]]

    def connect(self) -> _Conn:
        return _Conn(self.row)


class TestLedgerProbe:
    async def test_detects_signed_transcripts(self) -> None:
        assert await server._ledger_has_signed_transcripts(_Engine((1,))) is True  # type: ignore[arg-type]

    async def test_empty_ledger_is_a_first_boot(self) -> None:
        assert await server._ledger_has_signed_transcripts(_Engine(None)) is False  # type: ignore[arg-type]

    async def test_unanswerable_ledger_fails_closed(self) -> None:
        with pytest.raises(TranscriptKeyError, match="could not be checked"):
            await server._ledger_has_signed_transcripts(None)
