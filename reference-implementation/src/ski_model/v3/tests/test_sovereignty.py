"""Spec §6 sovereignty: mode, the §6.2 startup checks, the §6.3 egress guard, §6.4 attestation."""

from __future__ import annotations

import socket
from typing import Any, Dict, Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ski_schemas.canonical import canonicalize

from ski_model import metrics, server, sovereignty
from ski_model.sovereignty import (
    ADVISORY,
    STRICT,
    EgressGuard,
    EgressRefused,
    SovereigntyError,
    config_checks,
    enforce,
    is_local_host,
    local_suffixes,
    model_hash_check,
    resolve_mode,
)
from ski_model.v3.signing import TranscriptSigner, verify_signature

from .test_endpoint import _install_test_state

_COMPOSE_ENV = {
    "OLLAMA_BASE_URL": "http://ollama:11434",
    "LEDGER_DSN": "postgresql://ski_ledger_writer:pw@postgres:5432/ski_ledger",
}


def _by_id(checks: list[sovereignty.Check]) -> Dict[str, sovereignty.Check]:
    return {c.id: c for c in checks}


# ---- mode --------------------------------------------------------------------------


def test_mode_defaults_to_strict() -> None:
    assert resolve_mode({}) == STRICT
    assert resolve_mode({"SKI_SOVEREIGNTY": " Advisory "}) == ADVISORY


def test_unknown_mode_refuses_to_start() -> None:
    with pytest.raises(SovereigntyError, match="not 'strict' or 'advisory'"):
        resolve_mode({"SKI_SOVEREIGNTY": "off"})


# ---- what counts as inside the deployment ------------------------------------------


_LOCAL_HOSTS = [
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
    "10.1.2.3",
    "192.168.0.9",
    "172.20.0.2",
    "fd00::1",
    "169.254.1.1",
    "100.64.0.5",
    "postgres",
    "ollama",
    "vllm.default.svc",
    "vllm.gpu.svc.cluster.local",
    "db.internal",
]


@pytest.mark.parametrize("host", _LOCAL_HOSTS)
def test_local_hosts(host: str) -> None:
    assert is_local_host(host)


@pytest.mark.parametrize(
    "host", ["8.8.8.8", "2001:4860:4860::8888", "api.openai.com", "vllm.gpu-pool", "", "db.corp.example"]
)
def test_hosts_outside_the_deployment(host: str) -> None:
    assert not is_local_host(host)


def test_operator_declared_domains_are_local() -> None:
    suffixes = local_suffixes({"SKI_SOVEREIGN_LOCAL_DOMAINS": "corp.example, .gpu-pool"})
    assert is_local_host("db.corp.example", suffixes)
    assert is_local_host("vllm.gpu-pool", suffixes)


# ---- §6.2 checks ---------------------------------------------------------------------


def test_stock_compose_configuration_passes_the_config_checks() -> None:
    checks = config_checks(backend="ollama", env=_COMPOSE_ENV, trust_anchor_count=1, unanchored=False)
    assert all(c.ok for c in checks), checks


@pytest.mark.parametrize(
    "overrides, failing",
    [
        ({"backend": "fake"}, "sovereign_backend"),
        ({"trust_anchor_count": 0, "unanchored": True}, "kg_trust_anchor"),
        ({"env": {**_COMPOSE_ENV, "LEDGER_DSN": "postgresql://u:p@db.example.com/ski"}}, "ledger_local"),
        ({"env": {**_COMPOSE_ENV, "LEDGER_DSN": ""}}, "ledger_local"),
        ({"env": {**_COMPOSE_ENV, "OLLAMA_BASE_URL": "https://llm.example.com"}}, "egress_allowlist_local"),
    ],
)
def test_each_config_check_fails_on_its_own(overrides: Dict[str, Any], failing: str) -> None:
    kwargs: Dict[str, Any] = {
        "backend": "ollama",
        "env": _COMPOSE_ENV,
        "trust_anchor_count": 1,
        "unanchored": False,
    }
    kwargs.update(overrides)
    failed = {c.id for c in config_checks(**kwargs) if not c.ok}
    assert failing in failed


@pytest.mark.parametrize(
    "source, ok",
    [
        ("verified-backend-digest", True),
        ("verified-file-digest", True),
        ("operator-asserted", True),  # vLLM with a pin and no weights file to hash
        ("name-commitment", False),  # no SKI_MODEL_FILE_SHA256 pin
        (None, False),
    ],
)
def test_model_weight_must_be_pinned(source: Any, ok: bool) -> None:
    assert model_hash_check(source).ok is ok


def test_strict_refuses_to_start_and_names_every_failed_check() -> None:
    checks = config_checks(backend="fake", env={}, trust_anchor_count=0, unanchored=False)
    with pytest.raises(SovereigntyError) as excinfo:
        enforce(STRICT, checks)
    for check_id in ("sovereign_backend", "kg_trust_anchor", "ledger_local"):
        assert check_id in str(excinfo.value)


def test_advisory_starts_with_unmet_requirements() -> None:
    enforce(ADVISORY, config_checks(backend="fake", env={}, trust_anchor_count=0, unanchored=False))


async def test_strict_server_refuses_to_start_before_contacting_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SKI_SOVEREIGNTY", "strict")
    monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
    monkeypatch.delenv("SKI_KG_TRUST_ANCHORS", raising=False)
    built: list[bool] = []
    monkeypatch.setattr(server, "_build_v3_llm_backend", lambda: built.append(True))
    with pytest.raises(SovereigntyError, match="sovereign_backend"):
        async with server.lifespan(server.app):
            pass
    assert built == []


# ---- §6.3 egress guard ---------------------------------------------------------------


@pytest.fixture
def strict_guard() -> Iterator[EgressGuard]:
    guard = sovereignty.install_egress_guard(EgressGuard(STRICT))
    try:
        yield guard
    finally:
        sovereignty._active_guard = None


def test_non_local_connect_during_evaluation_is_refused_and_counted(strict_guard: EgressGuard) -> None:
    before = metrics.EGRESS_ATTEMPTS.labels(mode=STRICT)._value.get()
    with strict_guard.evaluation(), pytest.raises(EgressRefused):
        socket.create_connection(("8.8.8.8", 443), timeout=0.01)
    assert strict_guard.attempts == 1 and strict_guard.tripped
    assert metrics.EGRESS_ATTEMPTS.labels(mode=STRICT)._value.get() == before + 1


def test_dns_lookup_of_an_outside_name_is_refused(strict_guard: EgressGuard) -> None:
    with strict_guard.evaluation(), pytest.raises(EgressRefused):
        socket.getaddrinfo("api.openai.com", 443)


def test_local_connects_and_calls_outside_an_evaluation_are_not_guarded(strict_guard: EgressGuard) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    try:
        with strict_guard.evaluation():
            socket.create_connection(listener.getsockname(), timeout=1).close()
        strict_guard.audit("socket.connect", (None, ("8.8.8.8", 443)))  # not evaluating: ignored
    finally:
        listener.close()
    assert strict_guard.attempts == 0


def test_advisory_counts_without_refusing() -> None:
    guard = EgressGuard(ADVISORY)
    with guard.evaluation():
        guard.audit("socket.connect", (None, ("8.8.8.8", 443)))
    assert guard.attempts == 1 and not guard.tripped


def test_tripped_strict_guard_refuses_further_evaluation() -> None:
    ledger = _install_test_state()
    guard = EgressGuard(STRICT)
    guard.attempts = 1
    server.state.egress_guard = guard
    try:
        response = TestClient(server.app).post(
            "/api/evaluate",
            json={
                "measurement_id": "m",
                "timestamp": "2026-01-15T12:00:00Z",
                "subject": "s",
                "measurement": {"so2_ppm": 1},
            },
        )
    finally:
        server.state.egress_guard = None
    assert response.status_code == 503
    assert "egress" in response.json()["detail"]
    assert ledger.appended == []


# ---- §6.4 attestation ----------------------------------------------------------------


def test_sovereignty_attestation_is_signed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_test_state()
    key = Ed25519PrivateKey.generate()
    signer = TranscriptSigner(key, key.public_key())
    server.state.transcript_signer = signer
    server.state.sovereignty_mode = ADVISORY
    server.state.sovereignty_checks = (model_hash_check(None),)
    server.state.egress_guard = EgressGuard(ADVISORY)
    monkeypatch.setenv("SKI_BUILD_COMMIT", "abc123")
    try:
        body = TestClient(server.app).get("/api/sovereignty").json()
    finally:
        server.state.transcript_signer = None
        server.state.egress_guard = None
    document, signature = body["document"], body["signature"]
    assert document["sovereignty_mode"] == ADVISORY
    assert document["codebase_commit_hash"] == "abc123"
    assert document["checks"][0]["id"] == "model_weight_registered" and document["checks"][0]["ok"] is False
    assert document["egress_attempts_total"] == 0
    for field in ("model_weight_hash", "kg_version_hash", "build_provenance_attestation", "signed_at"):
        assert field in document
    assert signature["signing_key_id"] == signer.key_id
    assert verify_signature(
        public_key_pem=signature["public_key_pem"],
        message=canonicalize(document),
        signature_hex=signature["value_hex"],
    )
