"""Standards-native evidence for one ledger entry: a SCITT transparent statement and a TRACE record.

``GET /api/ledger/{sequence}/evidence`` serves both, signed with the runtime's
deployment key (the transcript key, whose id is on every ledger entry):

* a SCITT **signed statement** (COSE_Sign1) over the entry's verdict line and
  envelope, and, once a ledger checkpoint covers the entry, a **COSE Receipt**
  (RFC9162_SHA256) proving its place in that checkpoint's Merkle tree; the
  *transparent statement* carries the receipt in its ``receipts`` header
  (:mod:`ski_schemas.scitt`);
* a **TRACE v0.2 Trust Record** for the same run (:mod:`ski_schemas.trace`).

A generic COSE verifier checks the statement and the receipt with the
runtime's public key; the receipt's Merkle root matches the signed checkpoint
``audit-ledger checkpoint export`` writes out.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Optional

from cryptography.hazmat.primitives import serialization
from ski_schemas.canonical import sha256_canonical
from ski_schemas.scitt import make_receipt, make_signed_statement, transparent_statement
from ski_schemas.trace import sign_record, trust_record

from .v3.signing import TranscriptSigner

# The verdict-line columns a statement carries (with entry_hash, which binds them).
_STATEMENT_FIELDS = (
    "sequence_number",
    "entry_hash",
    "previous_hash",
    "timestamp",
    "tenant_id",
    "verdict",
    "telemetry_id",
    "telemetry_hash",
    "rule_id",
    "kg_version_hash",
    "model_weight_hash",
    "schema_version",
    "verifier_status",
    "envelope_hash",
    "signing_key_id",
    "verdict_signature",
    "verdict_signing_key_id",
)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _b64(data: Optional[bytes]) -> Optional[str]:
    return base64.b64encode(data).decode("ascii") if data is not None else None


def ledger_evidence(
    evidence: dict[str, Any],
    *,
    signer: TranscriptSigner,
    strict: bool,
    kg_version: Optional[str],
    data_class: str,
    image_digest: Optional[str],
    codebase_commit: Optional[str],
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """The SCITT statement (+ receipt) and the TRACE record for one entry from :meth:`LedgerClient.evidence`."""
    row = evidence["entry"]
    entry = {k: row.get(k) for k in _STATEMENT_FIELDS}
    envelope = _json(row.get("envelope_json"))
    transcript = _json(row.get("transcript_json"))
    issued_at = int((now or datetime.now(timezone.utc)).timestamp())

    def sign(message: bytes) -> bytes:
        return bytes.fromhex(signer.sign(message))

    statement = make_signed_statement(
        entry=entry, envelope=envelope, key_id=signer.key_id, issued_at=issued_at, sign_fn=sign
    )
    hashes = evidence.get("checkpoint_hashes")
    receipt = (
        make_receipt(
            entry_hashes=hashes,
            leaf_index=int(row["sequence_number"]) - 1,
            key_id=signer.key_id,
            sign_fn=sign,
        )
        if hashes
        else None
    )
    seq, tenant = row["sequence_number"], row.get("tenant_id") or "default"
    provenance = dict((envelope or {}).get("model_provenance") or {})
    raw_key = serialization.load_pem_public_key(signer.public_key_pem.encode("ascii")).public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    record = trust_record(
        entry=entry,
        provenance=provenance,
        verifier_status=row.get("verifier_status"),
        transcript_hash=sha256_canonical(transcript) if transcript is not None else None,
        strict=strict,
        kg_version=kg_version,
        data_class=data_class,
        image_digest=image_digest,
        codebase_commit=codebase_commit,
        receipt_uri=f"ski:ledger:{tenant}:{seq}#receipt" if receipt is not None else None,
        raw_public_key=raw_key,
        issued_at=issued_at,
    )
    return {
        "sequence_number": seq,
        "signing_key_id": signer.key_id,
        "scitt": {
            "signed_statement": _b64(statement),
            "receipt": _b64(receipt),
            "receipt_tree_size": len(hashes) if hashes else None,
            "transparent_statement": _b64(transparent_statement(statement, [receipt] if receipt else [])),
        },
        "trace_record": sign_record(record, sign),
    }
