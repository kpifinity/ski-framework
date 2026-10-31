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
    egress_allowlist,
    enforce,
    is_local_host,
    kg_anchored_check,
    local_suffixes,
    model_hash_check,
    model_hash_verified_check,
    resolve_mode,
    runtime_checks,
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


@pytest.mark.parametrize(
    "verified, source, ok",
    [
        (True, "verified-file-digest", True),
        (True, "verified-backend-digest", True),
        (False, "operator-asserted", False),  # a pin nothing was checked against
        (False, "name-commitment", False),
    ],
)
def test_model_weight_must_be_verified(verified: bool, source: str, ok: bool) -> None:
    assert model_hash_verified_check(verified, source).ok is ok


@pytest.mark.parametrize(
    "loaded, trust, ok",
    [(True, "anchored", True), (True, "unanchored", False), (True, "unsigned", False), (False, None, False)],
)
def test_loaded_kg_must_be_anchored(loaded: bool, trust: Any, ok: bool) -> None:
    check = kg_anchored_check(loaded, trust)
    assert check.ok is ok
    assert ("no KG loaded" in check.detail) is (not loaded)


@pytest.mark.parametrize(
    "env, failing",
    [
        ({}, set()),
        ({"TLS_ENABLED": "true", "SKI_MODEL_WORKERS": "1"}, set()),
        ({"TLS_ENABLED": "false"}, {"tls_enabled"}),
        ({"SKI_MODEL_WORKERS": "4"}, {"single_worker"}),
    ],
)
def test_runtime_checks(env: Dict[str, str], failing: set[str]) -> None:
    assert {c.id for c in runtime_checks(env) if not c.ok} == failing


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


def _backend_must_not_be_contacted() -> Any:
    raise AssertionError("the backend was contacted before a failed check refused startup")


@pytest.mark.parametrize(
    "env, failing",
    [({"TLS_ENABLED": "false"}, "tls_enabled"), ({"SKI_MODEL_WORKERS": "2"}, "single_worker")],
)
async def test_strict_server_refuses_plaintext_or_extra_workers(
    monkeypatch: pytest.MonkeyPatch, env: Dict[str, str], failing: str
) -> None:
    monkeypatch.setenv("SKI_SOVEREIGNTY", "strict")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(server, "_build_v3_llm_backend", _backend_must_not_be_contacted)
    with pytest.raises(SovereigntyError, match=failing):
        async with server.lifespan(server.app):
            pass


async def test_strict_server_refuses_an_unanchored_kg_before_the_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Every configuration check passes; the KG is the only failure, so it is named alone."""
    from .test_kg_graph import _graph, _sign

    key = Ed25519PrivateKey.generate()
    kg_path = tmp_path / "kg.json"
    kg_path.write_text(__import__("json").dumps(_sign(_graph(), key)), encoding="utf-8")
    monkeypatch.setenv("KG_PATH", str(kg_path))
    monkeypatch.setenv("SKI_SOVEREIGNTY", "strict")
    monkeypatch.setenv("SKI_V3_LLM_BACKEND", "vllm")
    monkeypatch.setenv("VLLM_BASE_URL", "http://vllm:8000")
    monkeypatch.setenv("LEDGER_DSN", _COMPOSE_ENV["LEDGER_DSN"])
    monkeypatch.setenv("TLS_ENABLED", "true")
    monkeypatch.delenv("SKI_KG_TRUST_ANCHORS", raising=False)
    monkeypatch.setenv("SKI_KG_ALLOW_UNANCHORED", "true")
    monkeypatch.setattr(sovereignty, "config_checks", lambda **_: [])
    monkeypatch.setattr(server, "_build_v3_llm_backend", _backend_must_not_be_contacted)
    with pytest.raises(SovereigntyError, match=r"1 requirement\(s\) unmet: kg_anchored\."):
        async with server.lifespan(server.app):
            pass


# ---- §6.3 egress guard ---------------------------------------------------------------


def test_egress_allowlist_is_the_ledger_and_the_backend() -> None:
    assert egress_allowlist("ollama", _COMPOSE_ENV) == ("ollama", "postgres")
    assert egress_allowlist("vllm", {"VLLM_BASE_URL": "https://VLLM.gpu:8000"}) == ("vllm.gpu",)
    assert egress_allowlist("fake", {}) == ()


@pytest.fixture
def strict_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[EgressGuard]:
    resolved = {"ledger.test": "10.9.8.7"}
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> list[Any]:
        if host in resolved:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved[host], 0))]
        if host == "llm.test":
            raise socket.gaierror(host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    guard = sovereignty.install_egress_guard(EgressGuard(STRICT, ["ledger.test", "llm.test"]).arm())
    try:
        yield guard
    finally:
        sovereignty._active_guard = None


def test_connect_outside_the_allowlist_is_refused_and_counted(strict_guard: EgressGuard) -> None:
    before = metrics.EGRESS_ATTEMPTS.labels(mode=STRICT)._value.get()
    with pytest.raises(EgressRefused):
        socket.create_connection(("8.8.8.8", 443), timeout=0.01)
    assert strict_guard.attempts == 1 and strict_guard.tripped
    assert metrics.EGRESS_ATTEMPTS.labels(mode=STRICT)._value.get() == before + 1


def test_a_private_address_is_not_allowlisted_by_being_private(strict_guard: EgressGuard) -> None:
    """The guard allows the configured destinations, not "anything inside a private range"."""
    with pytest.raises(EgressRefused):
        strict_guard.audit("socket.connect", (None, ("10.0.0.99", 5432)))
    assert strict_guard.attempts == 1


@pytest.mark.parametrize(
    "event, args",
    [
        ("socket.getaddrinfo", ("api.openai.com", 443, 0, 0, 0)),
        ("socket.gethostbyname", ("api.openai.com",)),
        ("socket.sendto", (None, ("1.1.1.1", 53))),
    ],
)
def test_lookups_and_datagrams_outside_the_allowlist_are_refused(
    strict_guard: EgressGuard, event: str, args: tuple[Any, ...]
) -> None:
    with pytest.raises(EgressRefused):
        strict_guard.audit(event, args)


@pytest.mark.parametrize(
    "event, args",
    [
        ("socket.getaddrinfo", ("ledger.test", 5432, 0, 0, 0)),
        ("socket.getaddrinfo", ("LLM.test.", 8000, 0, 0, 0)),
        ("socket.connect", (None, ("10.9.8.7", 5432))),  # what ledger.test resolves to
        ("socket.connect", (None, ("::1", 8000, 0, 0))),
        ("socket.getaddrinfo", ("localhost", 8000, 0, 0, 0)),
        ("socket.getaddrinfo", (None, 8000, 0, 0, 0)),
        ("socket.connect", (None, "/run/postgresql/.s.PGSQL.5432")),  # AF_UNIX
    ],
)
def test_allowlisted_and_local_destinations_pass(
    strict_guard: EgressGuard, event: str, args: tuple[Any, ...]
) -> None:
    strict_guard.audit(event, args)
    assert strict_guard.attempts == 0


def test_a_real_loopback_connection_passes(strict_guard: EgressGuard) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    try:
        socket.create_connection(listener.getsockname(), timeout=1).close()
    finally:
        listener.close()
    assert strict_guard.attempts == 0


def test_the_guard_is_inactive_until_armed() -> None:
    guard = EgressGuard(STRICT, [])
    guard.audit("socket.connect", (None, ("8.8.8.8", 443)))
    assert guard.attempts == 0 and not guard.armed
    assert guard.arm().armed


def test_advisory_counts_without_refusing() -> None:
    guard = EgressGuard(ADVISORY).arm()
    guard.audit("socket.connect", (None, ("8.8.8.8", 443)))
    assert guard.attempts == 1 and not guard.tripped
    assert guard.state() == {
        "mode": ADVISORY,
        "enforcing": False,
        "armed": True,
        "allowlist": ["loopback"],
        "attempts_total": 1,
        "tripped": False,
    }


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
    server.state.egress_guard = EgressGuard(ADVISORY, ["postgres"]).arm()
    server.state.ledger_role = "ski_ledger_writer"
    monkeypatch.setenv("SKI_BUILD_COMMIT", "abc123")
    monkeypatch.setenv("SKI_IMAGE_DIGEST", "sha256:" + "9" * 64)
    try:
        body = TestClient(server.app).get("/api/sovereignty").json()
    finally:
        server.state.transcript_signer = None
        server.state.egress_guard = None
        server.state.ledger_role = None
    document, signature = body["document"], body["signature"]
    assert document["sovereignty_mode"] == ADVISORY
    assert document["codebase_commit_hash"] == "abc123"
    assert document["checks"][0]["id"] == "model_weight_registered" and document["checks"][0]["ok"] is False
    assert document["egress_attempts_total"] == 0
    assert document["strict"] is False
    assert document["egress_guard"]["allowlist"] == ["loopback", "postgres"]
    assert document["ledger_role"] == {"role": "ski_ledger_writer", "least_privilege": None}
    assert document["image_digest"] == "sha256:" + "9" * 64
    assert server.state.knowledge_graph is not None
    assert document["kg_version"] == server.state.knowledge_graph.version
    for field in ("model_id", "model_hash_verified", "kg_signer_key_id", "kg_trust"):
        assert field in document
    for field in ("model_weight_hash", "kg_version_hash", "build_provenance_attestation", "signed_at"):
        assert field in document
    assert signature["signing_key_id"] == signer.key_id
    assert verify_signature(
        public_key_pem=signature["public_key_pem"],
        message=canonicalize(document),
        signature_hex=signature["value_hex"],
    )
