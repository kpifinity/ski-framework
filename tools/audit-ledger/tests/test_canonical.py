"""Tests for the canonical serialization (used for entry hash computation)."""

from __future__ import annotations

import hashlib
import json

from audit_ledger.canonical import canonical_entry_payload


def test_payload_is_sorted_and_compact() -> None:
    payload = canonical_entry_payload(
        sequence_number=42,
        previous_hash="0" * 64,
        timestamp_iso="2026-05-22T10:00:00+00:00",
        verdict="CLEAR",
        telemetry_id="tel_001",
        telemetry_hash="a" * 64,
        rule_id="energy.so2.lte_100ppm",
        kg_version="v0.1-demo",
        ski_model_version="0.1.0-alpha",
        reasoning="ok",
        track="symbolic",
    )
    decoded = payload.decode("utf-8")
    # Keys are sorted, no whitespace.
    assert decoded.startswith('{"kg_version":')
    assert " " not in decoded


def test_payload_is_deterministic() -> None:
    """Recomputing the same payload twice yields identical bytes — the whole
    point of the canonical serialization is that third parties can re-derive
    the entry hash without our code."""
    kwargs = dict(
        sequence_number=1,
        previous_hash="0" * 64,
        timestamp_iso="2026-05-22T10:00:00+00:00",
        verdict="CLEAR",
        telemetry_id="tel_001",
        telemetry_hash="a" * 64,
        rule_id="r1",
        kg_version="v1",
        ski_model_version="0.1.0-alpha",
        reasoning=None,
        track=None,
    )
    a = canonical_entry_payload(**kwargs)
    b = canonical_entry_payload(**kwargs)
    assert a == b
    # And SHA-256 of it matches a manual round trip.
    obj = json.loads(a.decode("utf-8"))
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
