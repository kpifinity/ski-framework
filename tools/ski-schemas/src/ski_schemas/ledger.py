"""Ledger entry hashing: the chain commits to the v3 evidence (spec §6, §7.1, §7.3).

A v3-format ledger entry hashes only the verdict-line columns, so the
envelope and the signed transcript stored beside it are not covered by the
chain. A v4 entry adds them, by digest:

``entry_hash`` = lowercase hex SHA-256 of :func:`ski_schemas.canonical.canonicalize`
of this JSON object (keys in any order)::

    {
      "ledger_format": 4,
      "sequence_number": <int>,
      "previous_hash": <64 hex; "0"*64 for sequence 1>,
      "timestamp": <ISO-8601 with offset, as stored>,
      "verdict": <str>,
      "telemetry_id": <str>,
      "telemetry_hash": <64 hex>,
      "rule_id": <str | null>,
      "kg_version": <str | null>,
      "ski_model_version": <str>,
      "reasoning": <str | null>,
      "track": <str | null>,
      "envelope_hash": <"sha256:<hex>" | null>,
      "transcript_hash": <"sha256:<hex>" | null>,
      "transcript_signature": <str | null>,
      "signing_key_id": <str | null>,
      "verifier_status": <str | null>
    }

``envelope_hash`` and ``transcript_hash`` are :func:`evidence_hash` of the
stored ``envelope_json`` / ``transcript_json``. The evidence is hashed from
its JSON *text*, parsed the way ``JSON.parse`` does it, because the ledger
stores it as JSONB: JSONB keeps every number's value but not its spelling
(``1e+300`` comes back as a 301-digit integer literal), and parsing the text
recovers the same double on both sides.

``"ledger_format"`` is in the hashed object, so payloads of different
formats can never hash to the same value: a verifier tells the formats
apart by which one reproduces the stored ``entry_hash``.

**Format 5** chains the spec §7.1 columns a v4 entry leaves out. Its object
is the v4 object with ``"ledger_format": 5`` plus::

      "tenant_id": <str>,
      "kg_version_hash": <"sha256:<hex>" | null>,
      "model_weight_hash": <"sha256:<hex>" | null>,
      "schema_version": <str; currently "3.0.0">

**Verdict signature.** A format-5 entry also carries ``verdict_signature``:
the runtime's Ed25519 signature over :func:`verdict_signing_bytes`, which
binds the entry's sequence number, ``entry_hash``, ``telemetry_id`` and
``transcript_id``. The entry hash already covers the content; the signature
proves the runtime's key produced *this* row at *this* position, so it
cannot be copied onto another row, and a re-chained ledger cannot be
re-signed without the key.

The language-neutral vectors are ``spec/test-vectors/ledger/``.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional, Union

from .canonical import canonicalize, canonicalize_json_text

__all__ = [
    "LEDGER_FORMAT_V4",
    "LEDGER_FORMAT_V5",
    "LEDGER_SCHEMA_VERSION",
    "VERDICT_SIGNATURE_PURPOSE",
    "entry_payload_v4",
    "entry_payload_v5",
    "evidence_hash",
    "verdict_signing_bytes",
]

#: The value of ``ledger_format`` inside a v4 entry's hashed payload.
LEDGER_FORMAT_V4 = 4
#: The value of ``ledger_format`` inside a v5 entry's hashed payload.
LEDGER_FORMAT_V5 = 5
#: ``schema_version`` (spec §7.1) written on format-5 entries.
LEDGER_SCHEMA_VERSION = "3.0.0"
#: Domain separator inside :func:`verdict_signing_bytes`.
VERDICT_SIGNATURE_PURPOSE = "ski.ledger.verdict-signature.v1"


def evidence_hash(json_text: Union[str, bytes, None]) -> Optional[str]:
    """``"sha256:<hex>"`` of the §7.3 canonical form of stored JSON text; ``None`` for no evidence.

    Raises :class:`ski_schemas.canonical.CanonicalizationError` for text with
    no canonical form.
    """
    if json_text is None:
        return None
    return "sha256:" + hashlib.sha256(canonicalize_json_text(json_text)).hexdigest()


def _verdict_line(
    ledger_format: int,
    *,
    sequence_number: int,
    previous_hash: str,
    timestamp_iso: str,
    verdict: str,
    telemetry_id: str,
    telemetry_hash: str,
    rule_id: Optional[str],
    kg_version: Optional[str],
    ski_model_version: str,
    reasoning: Optional[str],
    track: Optional[str],
    envelope_hash: Optional[str],
    transcript_hash: Optional[str],
    transcript_signature: Optional[str],
    signing_key_id: Optional[str],
    verifier_status: Optional[str],
) -> dict[str, Any]:
    return {
        "ledger_format": ledger_format,
        "sequence_number": sequence_number,
        "previous_hash": previous_hash,
        "timestamp": timestamp_iso,
        "verdict": verdict,
        "telemetry_id": telemetry_id,
        "telemetry_hash": telemetry_hash,
        "rule_id": rule_id,
        "kg_version": kg_version,
        "ski_model_version": ski_model_version,
        "reasoning": reasoning,
        "track": track,
        "envelope_hash": envelope_hash,
        "transcript_hash": transcript_hash,
        "transcript_signature": transcript_signature,
        "signing_key_id": signing_key_id,
        "verifier_status": verifier_status,
    }


def entry_payload_v4(
    *,
    sequence_number: int,
    previous_hash: str,
    timestamp_iso: str,
    verdict: str,
    telemetry_id: str,
    telemetry_hash: str,
    rule_id: Optional[str],
    kg_version: Optional[str],
    ski_model_version: str,
    reasoning: Optional[str],
    track: Optional[str],
    envelope_hash: Optional[str],
    transcript_hash: Optional[str],
    transcript_signature: Optional[str],
    signing_key_id: Optional[str],
    verifier_status: Optional[str],
) -> bytes:
    """The §7.3 canonical bytes a v4 ``entry_hash`` is the SHA-256 of."""
    return canonicalize(
        _verdict_line(
            LEDGER_FORMAT_V4,
            sequence_number=sequence_number,
            previous_hash=previous_hash,
            timestamp_iso=timestamp_iso,
            verdict=verdict,
            telemetry_id=telemetry_id,
            telemetry_hash=telemetry_hash,
            rule_id=rule_id,
            kg_version=kg_version,
            ski_model_version=ski_model_version,
            reasoning=reasoning,
            track=track,
            envelope_hash=envelope_hash,
            transcript_hash=transcript_hash,
            transcript_signature=transcript_signature,
            signing_key_id=signing_key_id,
            verifier_status=verifier_status,
        )
    )


def entry_payload_v5(
    *,
    sequence_number: int,
    previous_hash: str,
    timestamp_iso: str,
    verdict: str,
    telemetry_id: str,
    telemetry_hash: str,
    rule_id: Optional[str],
    kg_version: Optional[str],
    ski_model_version: str,
    reasoning: Optional[str],
    track: Optional[str],
    envelope_hash: Optional[str],
    transcript_hash: Optional[str],
    transcript_signature: Optional[str],
    signing_key_id: Optional[str],
    verifier_status: Optional[str],
    tenant_id: str,
    kg_version_hash: Optional[str],
    model_weight_hash: Optional[str],
    schema_version: str,
) -> bytes:
    """The §7.3 canonical bytes a v5 ``entry_hash`` is the SHA-256 of: v4 plus the §7.1 columns."""
    fields = _verdict_line(
        LEDGER_FORMAT_V5,
        sequence_number=sequence_number,
        previous_hash=previous_hash,
        timestamp_iso=timestamp_iso,
        verdict=verdict,
        telemetry_id=telemetry_id,
        telemetry_hash=telemetry_hash,
        rule_id=rule_id,
        kg_version=kg_version,
        ski_model_version=ski_model_version,
        reasoning=reasoning,
        track=track,
        envelope_hash=envelope_hash,
        transcript_hash=transcript_hash,
        transcript_signature=transcript_signature,
        signing_key_id=signing_key_id,
        verifier_status=verifier_status,
    )
    fields.update(
        tenant_id=tenant_id,
        kg_version_hash=kg_version_hash,
        model_weight_hash=model_weight_hash,
        schema_version=schema_version,
    )
    return canonicalize(fields)


def verdict_signing_bytes(
    *, sequence_number: int, entry_hash: str, telemetry_id: str, transcript_id: Optional[str]
) -> bytes:
    """The §7.3 canonical bytes a format-5 ``verdict_signature`` signs."""
    return canonicalize(
        {
            "purpose": VERDICT_SIGNATURE_PURPOSE,
            "sequence_number": sequence_number,
            "entry_hash": entry_hash,
            "telemetry_id": telemetry_id,
            "transcript_id": transcript_id,
        }
    )
