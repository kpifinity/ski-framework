"""Deterministic replay of v3 audit ledger entries (spec §8.1).

For every entry in a contiguous range that the language model evaluated
(it has a stored envelope and signed transcript), this module:

  1. Recovers the exact measurement and scoped KG snapshot the model was
     given from the transcript's ``request_canonical`` prompt.
  2. Loads the telemetry buffer row by ``telemetry_hash`` and checks it
     holds that measurement (the ledger and the buffer agree).
  3. Checks the KG supplied with ``--kg-path`` reproduces the recorded
     ``kg_version_hash`` and, re-scoped as recorded, the same snapshot.
  4. Verifies the transcript: its request/response hashes are recomputed
     from the stored prompt and response, its Ed25519 signature is checked
     against the key the ledger holds for its ``signing_key_id`` (or one
     given with ``--signing-key``), and, when it was recorded under the
     current prompt template, the prompt is re-rendered from the recovered
     inputs and must equal the stored one byte for byte.
  5. Re-runs the runtime's own ``V3Evaluator`` with the model call
     replaced by the transcript's recorded response, with the same risk
     tier, subject, telemetry time and buffer: the verifier, freshness
     gate and risk-tier policy are deterministic, so the verdict and the
     verifier status must come out as recorded.
  6. Emits a structured report and (optionally) exits non-zero on
     divergence, or when no entry in the range could be replayed at all.

Re-generating the model output itself is out of scope (spec §8.2: model
replay is judged by tolerance bounds, not identity). Entries the model did
not evaluate (no transcript: the clock-skew guard path) and entries that
pre-date the v3 envelope (schema_version 0.1.0 / v0.2 rows, pre-buffer or
without a stored envelope) are skipped with a note.

This is the deterministic-replay primitive the SKI Framework Level 3
conformance suite depends on. See docs/replay.md for the user-facing
documentation and docs/RFCs/0001-stateful-evaluation.md for the
architectural rationale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from ski_schemas.transcript import hash_pair, signing_message
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from .evidence import KeyRing, key_id_of, load_key, signature_valid


@dataclass
class ReplayMismatch:
    sequence_number: int
    telemetry_id: str
    rule_id: Optional[str]
    recorded_verdict: str
    replayed_verdict: str
    recorded_reasoning: Optional[str]
    replayed_reasoning: str
    reason: str


@dataclass
class ReplayReport:
    started_at: datetime
    finished_at: Optional[datetime] = None
    from_sequence: int = 0
    to_sequence: int = 0
    total_entries: int = 0
    replayed_entries: int = 0
    skipped_entries: int = 0
    matched_entries: int = 0
    transcript_signatures_verified: int = 0
    mismatches: list[ReplayMismatch] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """Every replayed entry matched, and at least one entry was replayed (an empty replay proves nothing)."""
        return (
            not self.mismatches
            and self.replayed_entries > 0
            and self.replayed_entries == self.matched_entries
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "from_sequence": self.from_sequence,
            "to_sequence": self.to_sequence,
            "total_entries": self.total_entries,
            "replayed_entries": self.replayed_entries,
            "skipped_entries": self.skipped_entries,
            "matched_entries": self.matched_entries,
            "transcript_signatures_verified": self.transcript_signatures_verified,
            "is_clean": self.is_clean,
            "mismatches": [
                {
                    "sequence_number": m.sequence_number,
                    "telemetry_id": m.telemetry_id,
                    "rule_id": m.rule_id,
                    "recorded_verdict": m.recorded_verdict,
                    "replayed_verdict": m.replayed_verdict,
                    "recorded_reasoning": m.recorded_reasoning,
                    "replayed_reasoning": m.replayed_reasoning,
                    "reason": m.reason,
                }
                for m in self.mismatches
            ],
            "notes": self.notes,
        }


def replay(
    *,
    dsn: str,
    from_sequence: int,
    to_sequence: int,
    kg_path: str,
    tenant_id: str = "default",
    signing_keys: Sequence[str] = (),
) -> ReplayReport:
    """Re-check the ledger entries in [from_sequence, to_sequence].

    ``signing_keys`` are PEM public keys to verify transcript signatures
    with, in addition to the ledger's own ``ledger_signing_keys``.
    Synchronous wrapper; called from the ``audit-ledger replay`` CLI command.
    """
    import asyncio

    return asyncio.run(
        _replay_async(
            dsn=dsn,
            from_sequence=from_sequence,
            to_sequence=to_sequence,
            kg_path=kg_path,
            tenant_id=tenant_id,
            signing_keys=signing_keys,
        )
    )


_MEASUREMENT_MARKER = "\nMEASUREMENT:\n"
_SNAPSHOT_MARKER = "\nKG SNAPSHOT:\n"


def recover_prompt_inputs(request_canonical: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The ``(measurement, kg_snapshot)`` a transcript's canonical prompt was rendered from.

    The evaluator renders both as one-line JSON after fixed markers
    (``PROMPT_TEMPLATE``); raises ``ValueError`` when the prompt does not
    have that shape.
    """
    _, sep, rest = request_canonical.partition(_MEASUREMENT_MARKER)
    measurement_line, sep2, snapshot_text = rest.partition(_SNAPSHOT_MARKER)
    if not sep or not sep2:
        raise ValueError("transcript prompt has no MEASUREMENT / KG SNAPSHOT sections")
    measurement = json.loads(measurement_line.strip())
    snapshot = json.loads(snapshot_text.strip())
    if not isinstance(measurement, dict) or not isinstance(snapshot, dict):
        raise ValueError("transcript prompt MEASUREMENT / KG SNAPSHOT are not JSON objects")
    return measurement, snapshot


class _RecordedResponse:
    """A V3 backend that answers with the transcript's recorded model output."""

    name = "recorded-transcript"

    def __init__(self, response: dict[str, Any], provenance: dict[str, Any]) -> None:
        self._response = response
        self._provenance = provenance

    @property
    def model_weight_hash(self) -> str:
        return str(self._provenance.get("model_weight_hash", "sha256:" + "0" * 64))

    @property
    def prompt_template_id(self) -> str:
        return str(self._provenance.get("prompt_template_id", ""))

    @property
    def prompt_template_hash(self) -> str:
        return str(self._provenance.get("prompt_template_hash", "sha256:" + "0" * 64))

    @property
    def structured_grammar_hash(self) -> str:
        return str(self._provenance.get("structured_grammar_hash", "sha256:" + "0" * 64))

    async def evaluate(self, **_: Any) -> dict[str, Any]:
        fresh: dict[str, Any] = json.loads(json.dumps(self._response))  # a fresh copy each call
        return fresh


def _value(enum_or_str: Any) -> str:
    return str(getattr(enum_or_str, "value", enum_or_str))


async def _replay_async(
    *,
    dsn: str,
    from_sequence: int,
    to_sequence: int,
    kg_path: str,
    tenant_id: str,
    signing_keys: Sequence[str],
) -> ReplayReport:
    # The evaluator, KG loader and telemetry buffer live in the
    # reference-implementation package; imported lazily so `audit-ledger
    # verify` works without them.
    import sys
    from pathlib import Path

    ref_impl_src = Path(__file__).resolve().parents[4] / "reference-implementation" / "src"
    if str(ref_impl_src) not in sys.path:
        sys.path.insert(0, str(ref_impl_src))

    from ski_model.kg_loader import load_signed_kg
    from ski_model.server import _compute_kg_version_hash
    from ski_model.v3 import V3Evaluator
    from ski_model.v3.backends.hashes import PROMPT_TEMPLATE_HASH
    from sqlalchemy.ext.asyncio import create_async_engine
    from tag_registry import RiskTierGovernor
    from telemetry_buffer import TelemetryBuffer

    report = ReplayReport(
        started_at=datetime.now(timezone.utc), from_sequence=from_sequence, to_sequence=to_sequence
    )

    kg = load_signed_kg(Path(kg_path), require_signature=True)
    kg_version_hash = _compute_kg_version_hash(kg)
    report.notes.append(
        f"Replaying against KG version {kg.version} ({kg_version_hash}) loaded from {kg_path}"
    )

    async_dsn = (
        dsn.replace("postgresql://", "postgresql+psycopg://", 1) if dsn.startswith("postgresql://") else dsn
    )
    engine = create_async_engine(async_dsn, pool_pre_ping=True)
    buffer = TelemetryBuffer(engine, tenant_id=tenant_id)
    sync_engine = create_engine(dsn)

    with Session(sync_engine) as session:
        ring = KeyRing.load(session)
    for pem in signing_keys:
        key = load_key(pem)
        if key is None:
            raise ValueError("--signing-key is not an Ed25519 public key PEM.")
        ring.keys[key_id_of(key)] = key
    unverifiable_keys: set[str] = set()

    with sync_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT sequence_number, telemetry_id, telemetry_hash, rule_id, verdict, reasoning,
                       envelope_json::text, transcript_json::text
                FROM ledger_entries
                WHERE sequence_number BETWEEN :from_seq AND :to_seq
                ORDER BY sequence_number ASC
                """
            ),
            {"from_seq": from_sequence, "to_seq": to_sequence},
        ).all()
    report.total_entries = len(rows)

    def mismatch(
        entry: tuple[int, str, Optional[str], str, Optional[str]], replayed: str, detail: str, reason: str
    ) -> None:
        seq, telemetry_id, rule_id, recorded, recorded_reasoning = entry
        report.mismatches.append(
            ReplayMismatch(
                sequence_number=seq,
                telemetry_id=telemetry_id,
                rule_id=rule_id,
                recorded_verdict=recorded,
                replayed_verdict=replayed,
                recorded_reasoning=recorded_reasoning,
                replayed_reasoning=detail,
                reason=reason,
            )
        )

    try:
        for (
            seq,
            telemetry_id,
            telemetry_hash,
            rule_id,
            recorded_verdict,
            recorded_reasoning,
            env_text,
            tr_text,
        ) in rows:
            seq = int(seq)
            if env_text is None:
                report.skipped_entries += 1
                report.notes.append(f"seq={seq}: pre-v3 entry (no stored envelope); skipped.")
                continue
            if tr_text is None:
                report.skipped_entries += 1
                report.notes.append(f"seq={seq}: not evaluated by the model (no transcript); skipped.")
                continue
            envelope = json.loads(env_text)
            transcript = json.loads(tr_text)
            recorded_status = str((envelope.get("verifier_result") or {}).get("status"))
            report.replayed_entries += 1

            entry = (seq, telemetry_id, rule_id, recorded_verdict, recorded_reasoning)

            provenance = envelope.get("model_provenance") or {}

            # The transcript itself: hashes, signature, prompt (spec §8.1 step 3).
            request_text = str(transcript.get("request_canonical", ""))
            response = dict(transcript.get("response_canonical") or {})
            if hash_pair(request_text=request_text, response=response) != (
                transcript.get("request_hash"),
                transcript.get("response_hash"),
            ):
                mismatch(
                    entry,
                    "<not replayed>",
                    "The stored prompt or response no longer hashes to the transcript's recorded hashes.",
                    "transcript_hash_mismatch",
                )
                continue
            key_id = str(transcript.get("signing_key_id", ""))
            key = ring.get(key_id)
            if key is None:
                unverifiable_keys.add(key_id)
            elif signature_valid(
                key,
                signing_message(
                    request_hash=str(transcript["request_hash"]),
                    response_hash=str(transcript["response_hash"]),
                ),
                transcript.get("signature_hex"),
            ):
                report.transcript_signatures_verified += 1
            else:
                mismatch(
                    entry,
                    "<not replayed>",
                    f"The transcript's signature does not verify with key {key_id}.",
                    "transcript_signature_invalid",
                )
                continue

            # A flat KG recorded before v3.3.0 was hashed in its flat form.
            accepted = {kg_version_hash, getattr(kg, "legacy_version_hash", None)} - {None}
            if provenance.get("kg_version_hash") not in accepted:
                mismatch(
                    entry,
                    "<not replayed>",
                    f"--kg-path hashes to {kg_version_hash}, the entry recorded {provenance.get('kg_version_hash')}.",
                    "kg_version_mismatch",
                )
                continue
            try:
                measurement, snapshot = recover_prompt_inputs(str(transcript.get("request_canonical", "")))
            except ValueError as exc:
                mismatch(
                    entry,
                    "<not replayed>",
                    f"Cannot recover the prompt inputs: {exc}.",
                    "transcript_unreadable",
                )
                continue

            record = await buffer.fetch_at(telemetry_hash=telemetry_hash)
            if record is None:
                mismatch(
                    entry,
                    "<not replayed>",
                    f"No buffer row for telemetry_hash={telemetry_hash}.",
                    "buffer_row_missing",
                )
                continue
            buffered = record["measurement"]
            buffered = buffered if isinstance(buffered, dict) else json.loads(buffered)
            if buffered != measurement:
                mismatch(
                    entry,
                    "<not replayed>",
                    "The buffer row's measurement differs from the transcript's.",
                    "telemetry_divergence",
                )
                continue
            as_of = record["telemetry_ts"]

            scope = snapshot.get("scope") or {}
            rescoped = kg.scope_to(
                jurisdiction=scope.get("jurisdiction"), as_of=as_of, subject=scope.get("subject")
            )
            if [ob.get("id") for ob in rescoped["obligations"]] != [
                ob.get("id") for ob in snapshot.get("obligations", [])
            ]:
                mismatch(
                    entry,
                    "<not replayed>",
                    "The KG, scoped as recorded, gives a different obligation set.",
                    "kg_snapshot_divergence",
                )
                continue

            evaluator = V3Evaluator(
                llm=_RecordedResponse(response, provenance),
                kg_version_hash=kg_version_hash,
                decoder_seed=int(provenance.get("decoder_seed", 0)),
            )
            if provenance.get("prompt_template_hash") == PROMPT_TEMPLATE_HASH:
                if evaluator._render_canonical_prompt(measurement, snapshot) != request_text:
                    mismatch(
                        entry,
                        "<not replayed>",
                        "Re-rendering the recorded prompt template from the recovered inputs does not "
                        "reproduce the stored prompt.",
                        "prompt_divergence",
                    )
                    continue
            else:
                report.notes.append(
                    f"seq={seq}: recorded under prompt template {provenance.get('prompt_template_hash')}, "
                    "not this runtime's; the prompt was not re-rendered."
                )
            result = await evaluator.aevaluate_with_transcript(
                measurement=measurement,
                kg_snapshot=snapshot,
                risk_tier=RiskTierGovernor.tier_for_snapshot(snapshot),
                subject=record["subject"],
                as_of=as_of,
                buffer=buffer,
            )
            replayed_verdict = _value(result.envelope.verdict)
            replayed_status = _value(result.envelope.verifier_result.status)
            if replayed_verdict == recorded_verdict and replayed_status == recorded_status:
                report.matched_entries += 1
            else:
                mismatch(
                    entry,
                    replayed_verdict,
                    f"verifier status recorded {recorded_status}, replayed {replayed_status}: "
                    f"{result.envelope.reasoning}",
                    "verdict_divergence",
                )
    finally:
        await engine.dispose()
        sync_engine.dispose()
    if unverifiable_keys:
        report.notes.append(
            "Transcript signatures not verified for key(s) "
            f"{', '.join(sorted(unverifiable_keys))}: not in ledger_signing_keys (a pre-format-5 ledger); "
            "pass the runtime's public key with --signing-key."
        )
    if report.replayed_entries == 0:
        report.notes.append(
            "No entry in the range was replayed, so the replay proves nothing; it is reported as not clean."
        )
    report.finished_at = datetime.now(timezone.utc)
    return report
