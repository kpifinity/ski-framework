"""SKI Framework v2.1 § B5.2 — Ledger hash chain integrity.

`verify_integrity` must (a) check the chain linkage AND (b) recompute
the entry hash from the canonical payload. A chain-linkage-only checker
is insufficient — an insider who modifies a row and recomputes the
chain forward would pass it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.level1
def test_canonical_serialization_is_documented() -> None:
    p = REPO_ROOT / "tools" / "audit-ledger" / "src" / "audit_ledger" / "canonical.py"
    assert p.exists(), "Canonical serialization module is missing."
    text = p.read_text()
    for required in ("sort_keys=True", "separators=", "ensure_ascii=False", "sha-256", "SHA-256"):
        if required in ("sha-256", "SHA-256"):
            assert "SHA-256" in text or "sha256" in text.lower(), "Canonical doc must reference SHA-256."
        else:
            assert required in text, f"Canonical serialization must use {required}."


@pytest.mark.level1
def test_verify_integrity_recomputes_entry_hash() -> None:
    """Static check: the verifier loads `canonical_entry_payload` and hashes it."""
    ledger_py = (REPO_ROOT / "tools" / "audit-ledger" / "src" / "audit_ledger" / "ledger.py").read_text()
    assert "canonical_entry_payload" in ledger_py, (
        "ledger.verify_integrity must import canonical_entry_payload to recompute the entry hash."
    )
    assert "hashlib.sha256(payload).hexdigest()" in ledger_py, (
        "ledger.verify_integrity must SHA-256 the canonical payload, not just compare chain links."
    )
    assert "ENTRY_HASH_MISMATCH" in ledger_py, (
        "ledger.verify_integrity must surface a distinct ENTRY_HASH_MISMATCH issue type."
    )


@pytest.mark.level1
@pytest.mark.requires_ledger
def test_live_verify_integrity_passes(require_ledger: str) -> None:
    """If a ledger DSN is supplied, the live verifier must pass on a fresh ledger."""
    audit_ledger = pytest.importorskip("audit_ledger")
    ledger = audit_ledger.Ledger(require_ledger)
    result = ledger.verify_integrity()
    assert result.entry_hash_verified_count == result.hash_verification_total, (
        "Entry-hash recomputation failed for some rows."
    )
    assert result.is_valid, f"verify_integrity reported issues: {result.issues}"
