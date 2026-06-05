"""Deterministic replay of audit ledger entries (v0.2.0).

Given a contiguous range of ledger entries, this module:

  1. Loads the corresponding rows from the telemetry buffer using
     ``telemetry_hash`` as the lookup key.
  2. Loads the Knowledge Graph at the entry's recorded version (supplied
     by the caller via ``--kg-path``; an in-deployment KG store is a
     future enhancement).
  3. Re-runs the Symbolic Evaluator (and, for Track 2 entries, refuses
     to claim determinism — Track 2 is best-effort).
  4. Compares the replayed verdict to the originally-recorded verdict.
  5. Emits a structured report and (optionally) exits non-zero on
     divergence.

This is the deterministic-replay primitive the SKI Framework Level 3
conformance suite depends on. See docs/replay.md for the user-facing
documentation and docs/RFCs/0001-stateful-evaluation.md for the
architectural rationale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import create_engine, text


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
    mismatches: list[ReplayMismatch] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.mismatches and self.replayed_entries == self.matched_entries

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
) -> ReplayReport:
    """Re-evaluate the ledger entries in [from_sequence, to_sequence].

    Synchronous wrapper around the async Symbolic Evaluator; this is
    intended to be called from the ``audit-ledger replay`` CLI command.
    """
    import asyncio

    return asyncio.run(
        _replay_async(
            dsn=dsn,
            from_sequence=from_sequence,
            to_sequence=to_sequence,
            kg_path=kg_path,
            tenant_id=tenant_id,
        )
    )


async def _replay_async(
    *,
    dsn: str,
    from_sequence: int,
    to_sequence: int,
    kg_path: str,
    tenant_id: str,
) -> ReplayReport:
    # The Symbolic Evaluator + TelemetryBuffer + KG loader live in the
    # reference-implementation package. They are imported here lazily so
    # the audit-ledger tool doesn't take a hard dependency on them at
    # import time (helpful for offline `audit-ledger verify` use cases).
    import sys
    from pathlib import Path

    ref_impl_src = Path(__file__).resolve().parents[5] / "reference-implementation" / "src"
    if str(ref_impl_src) not in sys.path:
        sys.path.insert(0, str(ref_impl_src))

    from ski_model.kg_loader import load_signed_kg  # type: ignore
    from sqlalchemy.ext.asyncio import create_async_engine
    from symbolic_evaluator import SymbolicEvaluator  # type: ignore
    from tag_registry import TagRegistry  # type: ignore
    from telemetry_buffer import TelemetryBuffer  # type: ignore

    report = ReplayReport(started_at=datetime.utcnow(), from_sequence=from_sequence, to_sequence=to_sequence)

    # 1. Load the KG once. Per-entry KG-version resolution is a v0.3 feature;
    #    today we replay against the KG supplied on the command line.
    kg = load_signed_kg(Path(kg_path), require_signature=True)
    registry = TagRegistry.from_knowledge_graph(kg)
    evaluator = SymbolicEvaluator()
    report.notes.append(f"Replaying against KG version {kg.version} loaded from {kg_path}")

    # 2. Open the ledger and buffer.
    async_dsn = (
        dsn.replace("postgresql://", "postgresql+psycopg://", 1) if dsn.startswith("postgresql://") else dsn
    )
    engine = create_async_engine(async_dsn, pool_pre_ping=True, future=True)
    buffer = TelemetryBuffer(engine, tenant_id=tenant_id)

    sync_engine = create_engine(dsn)

    # 3. Iterate ledger entries in [from, to].
    with sync_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT sequence_number, telemetry_id, telemetry_hash, rule_id,
                       verdict, reasoning, track, knowledge_graph_version,
                       schema_version
                FROM ledger_entries
                WHERE sequence_number BETWEEN :from_seq AND :to_seq
                ORDER BY sequence_number ASC
                """
            ),
            {"from_seq": from_sequence, "to_seq": to_sequence},
        ).all()

    report.total_entries = len(rows)

    for row in rows:
        (
            seq,
            telemetry_id,
            telemetry_hash,
            rule_id,
            recorded_verdict,
            recorded_reasoning,
            track,
            _kg_version,  # read for schema completeness; not used during replay
            schema_version,
        ) = row

        # Backwards compatibility: v0.1 entries pre-date the buffer.
        if schema_version is None or schema_version == "0.1.0":
            report.skipped_entries += 1
            report.notes.append(
                f"seq={seq}: v0.1 entry — pre-buffer; stateful evaluation cannot be replayed."
            )
            continue

        if track == "llm":
            report.skipped_entries += 1
            report.notes.append(f"seq={seq}: Track 2 (LLM) entry — replay is best-effort only; skipped.")
            continue

        # Reconstruct telemetry from the buffer.
        record = await buffer.fetch_at(telemetry_hash=telemetry_hash)
        if record is None:
            report.skipped_entries += 1
            report.notes.append(
                f"seq={seq}: buffer row not found (telemetry_hash={telemetry_hash[:12]}…); skipped."
            )
            continue

        telemetry = {
            "subject": record["subject"],
            "telemetry_id": record["telemetry_id"],
            "timestamp": record["telemetry_ts"].isoformat()
            if isinstance(record["telemetry_ts"], datetime)
            else record["telemetry_ts"],
            "measurement": record["measurement"]
            if isinstance(record["measurement"], dict)
            else json.loads(record["measurement"]),
        }

        # Re-route via the Tag Registry (must produce the same rule_id).
        rule = registry.resolve(telemetry["subject"])
        if rule is None or rule.get("id") != rule_id:
            report.replayed_entries += 1
            report.mismatches.append(
                ReplayMismatch(
                    sequence_number=int(seq),
                    telemetry_id=telemetry_id,
                    rule_id=rule_id,
                    recorded_verdict=recorded_verdict,
                    replayed_verdict="<routing diverged>",
                    recorded_reasoning=recorded_reasoning,
                    replayed_reasoning=(
                        f"Tag Registry now resolves {telemetry['subject']!r} to "
                        f"{rule.get('id') if rule else None!r}, not {rule_id!r}."
                    ),
                    reason="tag_registry_divergence",
                )
            )
            continue

        # Re-evaluate against the buffer state as of telemetry_ts.
        decision = await evaluator.aevaluate(
            rule,
            telemetry,
            buffer=buffer,
            as_of=record["telemetry_ts"],
        )

        report.replayed_entries += 1
        if decision.verdict == recorded_verdict:
            report.matched_entries += 1
        else:
            report.mismatches.append(
                ReplayMismatch(
                    sequence_number=int(seq),
                    telemetry_id=telemetry_id,
                    rule_id=rule_id,
                    recorded_verdict=recorded_verdict,
                    replayed_verdict=str(decision.verdict),
                    recorded_reasoning=recorded_reasoning,
                    replayed_reasoning=decision.reasoning,
                    reason="verdict_divergence",
                )
            )

    await engine.dispose()
    sync_engine.dispose()
    report.finished_at = datetime.utcnow()
    return report
