"""SKI Framework v3 § Pillar S, ``sovereignty-strict`` dimension of the air-gap rig (spec §6).

The same loopback-only pod as ``test_air_gapped.py``, booted the way a
production deployment must run: ``SKI_SOVEREIGNTY=strict``, a sovereign
backend (the vLLM API, from ``airgap/stub_vllm.py``) inside the namespace
with its weights file verified against the pinned digest, the KG anchored,
the ledger reached as ``ski_ledger_writer``, TLS on and one worker. The
runtime refuses to start unless every check passes, so a healthy pod is
itself the first proof. The tests then show:

* ``/api/sovereignty`` is signed by the key the ledger records, verifies
  offline with ``ski_sdk.verify_sovereignty_attestation``, and attests the
  strict posture field by field;
* the fixed workload evaluates with the same verdicts as the advisory rig;
* the egress guard refuses an outbound connect and DNS lookup scripted
  from inside the runtime process, counts both in
  ``ski_egress_attempts_total``, and the runtime then refuses to evaluate
  (fail closed) while the attestation reports the trip.

The tests run in file order: the egress probe trips the guard, so it runs last.
"""

from __future__ import annotations

import re
from typing import Any, Dict

import pytest

from .test_air_gapped import _WORKLOAD, AirgapRig, _boot_rig

pytestmark = pytest.mark.sovereignty


@pytest.fixture(scope="module")
def strict_rig(request: pytest.FixtureRequest) -> AirgapRig:
    return _boot_rig(request, strict=True)


def _attestation(rig: AirgapRig) -> Dict[str, Any]:
    status, body = rig.api("GET", "/api/sovereignty")
    assert status == 200, body
    return body


def _egress_counter(rig: AirgapRig) -> float:
    status, text = rig.api_text("GET", "/metrics")
    assert status == 200
    match = re.search(r'^ski_egress_attempts_total\{mode="strict"\} (\S+)$', text, re.MULTILINE)
    return float(match.group(1)) if match else 0.0


def test_strict_runtime_boots_with_tls_inside_the_airgap(strict_rig: AirgapRig) -> None:
    """Strict mode started (every check passed) and serves only over TLS."""
    status, health = strict_rig.api("GET", "/api/health")
    assert status == 200, f"{health}\n{strict_rig.logs(strict_rig.model)}"
    assert health["kg_signature_verified"] is True
    plaintext = strict_rig.exec(strict_rig.model, ["curl", "-sS", "http://localhost:8000/api/health"])
    assert plaintext.returncode != 0, "the strict runtime must not answer plaintext HTTP"


def test_attestation_verifies_offline_against_the_ledger_key(strict_rig: AirgapRig) -> None:
    """The signature verifies with only the key id the ledger records on every entry."""
    from ski_sdk import verify_sovereignty_attestation

    strict_rig.replay_workload()
    ledger_key_ids = set(
        strict_rig.sql("SELECT DISTINCT signing_key_id FROM ledger_entries WHERE signing_key_id IS NOT NULL")
        .strip()
        .splitlines()
    )
    assert len(ledger_key_ids) == 1
    report = verify_sovereignty_attestation(_attestation(strict_rig), trusted_key_id=ledger_key_ids.pop())
    assert report.ok and report.strict


def test_attestation_reports_the_strict_posture(strict_rig: AirgapRig) -> None:
    document = _attestation(strict_rig)["document"]
    assert document["sovereignty_mode"] == "strict" and document["strict"] is True
    failed = [c for c in document["checks"] if c["ok"] is not True]
    assert failed == [], failed
    assert {c["id"] for c in document["checks"]} >= {
        "sovereign_backend",
        "model_weight_registered",
        "model_weight_verified",
        "kg_trust_anchor",
        "kg_anchored",
        "ledger_local",
        "ledger_least_privilege",
        "egress_allowlist_local",
        "tls_enabled",
        "single_worker",
    }
    assert document["kg_trust"] == "anchored"
    assert document["kg_signer_key_id"] == strict_rig.anchor_key_id
    assert document["kg_version"] == "airgap-fixture-1"
    assert document["model_id"] == "conformance/stub-vllm"
    assert document["model_hash_verified"] is True
    assert document["model_hash_source"] == "verified-file-digest"
    assert document["ledger_role"] == {"role": "ski_ledger_writer", "least_privilege": True}
    assert document["image_digest"].startswith("sha256:")
    guard = document["egress_guard"]
    assert guard["mode"] == "strict" and guard["enforcing"] and guard["armed"]
    assert guard["allowlist"] == ["loopback", "127.0.0.1", "localhost"]
    assert guard["attempts_total"] == 0 and not guard["tripped"]


def test_workload_replays_with_expected_verdicts_in_strict_mode(strict_rig: AirgapRig) -> None:
    produced = {mid: verdict for mid, verdict, _ in strict_rig.replay_workload()}
    assert produced == {mid: verdict for mid, _, verdict in _WORKLOAD}
    for mid, _, envelope in strict_rig.replay_workload():
        provenance = envelope.get("model_provenance") or {}
        assert provenance.get("model_hash_verified") is True, mid


def test_egress_guard_blocks_a_scripted_outbound_call_and_fails_closed(strict_rig: AirgapRig) -> None:
    strict_rig.replay_workload()
    before = _egress_counter(strict_rig)

    status, outcome = strict_rig.api("POST", "/conformance/egress-probe")
    assert status == 200, outcome
    assert outcome == {"connect": "EgressRefused", "lookup": "EgressRefused"}
    assert _egress_counter(strict_rig) == before + 2

    guard = _attestation(strict_rig)["document"]["egress_guard"]
    assert guard["attempts_total"] == 2 and guard["tripped"] is True

    _, measurement, _ = _WORKLOAD[0]
    status, body = strict_rig.api(
        "POST",
        "/api/evaluate",
        {
            "measurement_id": "airgap-after-egress",
            "timestamp": "2026-06-15T12:00:00Z",
            "subject": f"facility.{next(iter(measurement))}",
            "measurement": measurement,
        },
    )
    assert status == 503 and "egress" in body["detail"], body
