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
from typing import Any, Dict, Optional

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
        "model_signature",
    }
    assert document["kg_trust"] == "anchored"
    assert document["kg_signer_key_id"] == strict_rig.anchor_key_id
    assert document["kg_version"] == "airgap-fixture-1"
    assert document["model_id"] == "conformance/stub-vllm"
    assert document["model_hash_verified"] is True
    assert document["model_hash_source"] == "verified-file-digest"
    assert document["ledger_role"] == {"role": "ski_ledger_writer", "least_privilege": True}
    signature = document["model_signature"]
    assert signature["verified"] is True and signature["files"] == 2  # OpenSSF Model Signing at boot
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


def test_ledger_is_format5_with_signed_checkpoints_inside_the_airgap(strict_rig: AirgapRig) -> None:
    """Every entry carries the spec §7.1 columns and a verdict signature, and a checkpoint signed by
    the attested key covers the ledger."""
    import hashlib
    import time

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from ski_schemas.merkle import checkpoint_statement, merkle_root

    strict_rig.replay_workload()
    key_id = _attestation(strict_rig)["signature"]["signing_key_id"]
    assert strict_rig.sql(
        "SELECT count(*) FROM ledger_entries WHERE schema_version = '3.0.0' AND tenant_id = 'default' "  # nosec B608 -- test fixture SQL with constant values
        f"AND verdict_signature IS NOT NULL AND verdict_signing_key_id = '{key_id}'"
    ) == str(len(_WORKLOAD))
    deadline = time.monotonic() + 30
    while strict_rig.sql("SELECT count(*) FROM ledger_checkpoints") != "2" and time.monotonic() < deadline:
        time.sleep(0.5)  # checkpoints are written in the background
    tenant, size, root, last, created_at, signature = strict_rig.sql(
        "SELECT tenant_id, tree_size, root_hash, last_entry_hash, created_at, signature "
        "FROM ledger_checkpoints ORDER BY tree_size DESC LIMIT 1"
    ).split("|")
    hashes = strict_rig.sql("SELECT entry_hash FROM ledger_entries ORDER BY sequence_number").split()
    assert int(size) == len(_WORKLOAD) and merkle_root(hashes) == root and hashes[-1] == last
    pem = strict_rig.sql(f"SELECT public_key_pem FROM ledger_signing_keys WHERE key_id = '{key_id}'")  # nosec B608 -- test fixture SQL with constant values
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    assert isinstance(key, Ed25519PublicKey)
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == key_id
    key.verify(
        bytes.fromhex(signature),
        checkpoint_statement(
            tenant_id=tenant, tree_size=int(size), root_hash=root, last_entry_hash=last, created_at=created_at
        ),
    )


def test_ledger_entries_are_scitt_statements_with_receipts_and_trace_records(strict_rig: AirgapRig) -> None:
    """The statement and the receipt for a checkpointed entry verify as plain COSE_Sign1 (RFC 9052)."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from ski_schemas.merkle import merkle_root

    strict_rig.replay_workload()
    status, evidence = strict_rig.api("GET", "/api/ledger/2/evidence")
    assert status == 200, evidence
    pem = _attestation(strict_rig)["signature"]["public_key_pem"]
    raw = serialization.load_pem_public_key(pem.encode("ascii")).public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    _cose_verify(base64.b64decode(evidence["scitt"]["signed_statement"]), raw)
    size = evidence["scitt"]["receipt_tree_size"]
    assert size is not None
    query = f"SELECT entry_hash FROM ledger_entries WHERE sequence_number <= {int(size)}"  # nosec B608 -- int
    hashes = strict_rig.sql(query + " ORDER BY sequence_number").split()
    _cose_verify(
        base64.b64decode(evidence["scitt"]["receipt"]), raw, detached=bytes.fromhex(merkle_root(hashes))
    )
    record = evidence["trace_record"]
    assert record["eat_profile"] == "tag:agentrust-io.com,2026:trace-v0.2"
    assert record["policy"]["enforcement_mode"] == "enforce"


def _cose_verify(message: bytes, raw_key: bytes, detached: Optional[bytes] = None) -> dict[Any, Any]:
    """Verify a COSE_Sign1 independently of ski_schemas.cose: cbor2 decodes it and builds RFC 9052's
    Sig_structure; raises on a bad signature. Returns the protected header."""
    import cbor2
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _Key

    tagged = cbor2.loads(message)
    assert tagged.tag == 18, "not a tagged COSE_Sign1"
    protected, _unprotected, payload, signature = tagged.value
    header = cbor2.loads(protected)
    assert header[1] == -8, "not EdDSA"
    to_be_signed = cbor2.dumps(["Signature1", protected, b"", payload if payload is not None else detached])
    _Key.from_public_bytes(raw_key).verify(signature, to_be_signed)
    return dict(header)


def test_ml_bom_inside_the_airgap(strict_rig: AirgapRig) -> None:
    status, bom = strict_rig.api("GET", "/api/mlbom")
    assert status == 200 and bom["specVersion"] == "1.6"
    model = bom["components"][0]
    assert model["type"] == "machine-learning-model" and model["name"] == "conformance/stub-vllm"
    props = {p["name"]: p["value"] for p in model["properties"]}
    assert props["ski:model_hash_verified"] == "true" and props["ski:model_signature_signer"].startswith(
        "sha256:"
    )


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
