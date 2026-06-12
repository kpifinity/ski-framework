"""Audit ledger client.

Append-only writer for the SKI Framework v3 audit ledger. Hash-chains every
entry and relies on database-side triggers to make UPDATE/DELETE impossible
(see src/ledger/append_only.sql). PR 11 expands the ledger to record signed
LLM transcripts and full model commitments per spec v3.0 §6.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .v3.envelope import V3Verdict as Verdict
from .v3.envelope import V3VerdictEnvelope
from .v3.transcript import LLMTranscript

logger = logging.getLogger(__name__)


def canonical_entry_payload(
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
) -> bytes:
    """Canonical serialization used for the entry hash.

    Documented here so third parties can verify the ledger using standard
    tooling. Field order is fixed; whitespace is stripped; keys sorted.
    """
    payload = {
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
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class LedgerClient:
    def __init__(self, dsn: str):
        if not dsn:
            raise RuntimeError("LEDGER_DSN is required.")
        # SQLAlchemy expects 'postgresql+psycopg' for async psycopg3.
        if dsn.startswith("postgresql://"):
            dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
        self._dsn = dsn
        self._engine: Optional[AsyncEngine] = None
        # Sequence-gap tripwire: this process is THE single writer, so after
        # the first append it knows exactly what the ledger head must be.
        # Any other head means rows appeared/vanished underneath us.
        self._expected_next_seq: Optional[int] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    async def initialize(self) -> None:
        self._engine = create_async_engine(self._dsn, pool_pre_ping=True, future=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    async def append(
        self,
        *,
        verdict: Verdict,
        telemetry_id: str,
        telemetry_hash: str,
        rule_id: Optional[str],
        kg_version: Optional[str],
        ski_model_version: str,
        reasoning: str,
        track: Optional[str],
    ) -> None:
        assert self._session_factory is not None
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT sequence_number, entry_hash FROM ledger_entries "
                        "ORDER BY sequence_number DESC LIMIT 1"
                    )
                )
            ).first()
            if row is None:
                sequence_number = 1
                previous_hash = "0" * 64
            else:
                sequence_number = int(row[0]) + 1
                previous_hash = str(row[1])

            if self._expected_next_seq is not None and sequence_number != self._expected_next_seq:
                from . import metrics

                metrics.LEDGER_SEQUENCE_GAPS.inc()
                logger.warning(
                    "Ledger sequence gap: this writer expected next sequence %d but the "
                    "ledger head implies %d. Single-writer invariant violated - "
                    "investigate for tampering or a concurrent writer.",
                    self._expected_next_seq,
                    sequence_number,
                )
            self._expected_next_seq = sequence_number + 1

            timestamp_iso = datetime.now(timezone.utc).isoformat()
            payload = canonical_entry_payload(
                sequence_number=sequence_number,
                previous_hash=previous_hash,
                timestamp_iso=timestamp_iso,
                verdict=verdict.value,
                telemetry_id=telemetry_id,
                telemetry_hash=telemetry_hash,
                rule_id=rule_id,
                kg_version=kg_version,
                ski_model_version=ski_model_version,
                reasoning=reasoning,
                track=track,
            )
            entry_hash = hashlib.sha256(payload).hexdigest()

            await session.execute(
                text(
                    """
                        INSERT INTO ledger_entries (
                            sequence_number, previous_hash, entry_hash, timestamp,
                            verdict, telemetry_id, telemetry_hash, rule_id,
                            knowledge_graph_version, ski_model_version,
                            reasoning, track
                        ) VALUES (
                            :seq, :prev, :hash, :ts,
                            :verdict, :tid, :thash, :rule_id,
                            :kg_version, :ski_model_version,
                            :reasoning, :track
                        )
                        """
                ),
                {
                    "seq": sequence_number,
                    "prev": previous_hash,
                    "hash": entry_hash,
                    "ts": timestamp_iso,
                    "verdict": verdict.value,
                    "tid": telemetry_id,
                    "thash": telemetry_hash,
                    "rule_id": rule_id,
                    "kg_version": kg_version,
                    "ski_model_version": ski_model_version,
                    "reasoning": reasoning,
                    "track": track,
                },
            )

    async def append_v3(
        self,
        *,
        envelope: V3VerdictEnvelope,
        transcript: Optional[LLMTranscript],
        telemetry_id: str,
        telemetry_hash: str,
        rule_id: Optional[str],
        kg_version: Optional[str],
        ski_model_version: str,
        track: str = "v3-evaluator",
    ) -> None:
        """Append a v3 ledger entry with envelope + signed transcript.

        The envelope JSON, the canonical envelope hash, and the (optional)
        transcript JSON / signature / key_id are all persisted so an
        auditor can independently replay the verdict per spec §6.
        The entry_hash chain continues; both the verdict-line columns and
        the new envelope_hash column are populated so the existing v2 hash
        chain stays unbroken.
        """
        assert self._session_factory is not None

        envelope_json = envelope.model_dump(mode="json")
        envelope_canonical = json.dumps(
            envelope_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        envelope_hash = "sha256:" + hashlib.sha256(envelope_canonical).hexdigest()

        transcript_json = transcript.model_dump(mode="json") if transcript is not None else None
        transcript_signature = transcript.signature_hex if transcript is not None else None
        signing_key_id = transcript.signing_key_id if transcript is not None else None

        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT sequence_number, entry_hash FROM ledger_entries "
                        "ORDER BY sequence_number DESC LIMIT 1"
                    )
                )
            ).first()
            if row is None:
                sequence_number = 1
                previous_hash = "0" * 64
            else:
                sequence_number = int(row[0]) + 1
                previous_hash = str(row[1])

            timestamp_iso = datetime.now(timezone.utc).isoformat()
            payload = canonical_entry_payload(
                sequence_number=sequence_number,
                previous_hash=previous_hash,
                timestamp_iso=timestamp_iso,
                verdict=str(envelope.verdict),
                telemetry_id=telemetry_id,
                telemetry_hash=telemetry_hash,
                rule_id=rule_id,
                kg_version=kg_version,
                ski_model_version=ski_model_version,
                reasoning=envelope.reasoning,
                track=track,
            )
            entry_hash = hashlib.sha256(payload).hexdigest()

            await session.execute(
                text(
                    """
                        INSERT INTO ledger_entries (
                            sequence_number, previous_hash, entry_hash, timestamp,
                            verdict, telemetry_id, telemetry_hash, rule_id,
                            knowledge_graph_version, ski_model_version,
                            reasoning, track,
                            envelope_json, envelope_hash,
                            transcript_json, transcript_signature, signing_key_id,
                            verifier_status
                        ) VALUES (
                            :seq, :prev, :hash, :ts,
                            :verdict, :tid, :thash, :rule_id,
                            :kg_version, :ski_model_version,
                            :reasoning, :track,
                            CAST(:envelope_json AS JSONB), :envelope_hash,
                            CAST(:transcript_json AS JSONB), :transcript_signature, :signing_key_id,
                            :verifier_status
                        )
                        """
                ),
                {
                    "seq": sequence_number,
                    "prev": previous_hash,
                    "hash": entry_hash,
                    "ts": timestamp_iso,
                    "verdict": str(envelope.verdict),
                    "tid": telemetry_id,
                    "thash": telemetry_hash,
                    "rule_id": rule_id,
                    "kg_version": kg_version,
                    "ski_model_version": ski_model_version,
                    "reasoning": envelope.reasoning,
                    "track": track,
                    "envelope_json": json.dumps(envelope_json, ensure_ascii=False),
                    "envelope_hash": envelope_hash,
                    "transcript_json": (
                        json.dumps(transcript_json, ensure_ascii=False)
                        if transcript_json is not None
                        else None
                    ),
                    "transcript_signature": transcript_signature,
                    "signing_key_id": signing_key_id,
                    "verifier_status": str(envelope.verifier_result.status),
                },
            )

    async def list(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        assert self._session_factory is not None
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT sequence_number, timestamp, verdict, telemetry_id,
                               rule_id, knowledge_graph_version, ski_model_version,
                               reasoning, track, entry_hash, previous_hash
                        FROM ledger_entries
                        ORDER BY sequence_number ASC
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    {"limit": limit, "offset": offset},
                )
            ).all()
        return [
            {
                "sequence_number": r[0],
                "timestamp": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
                "verdict": r[2],
                "telemetry_id": r[3],
                "rule_id": r[4],
                "kg_version": r[5],
                "ski_model_version": r[6],
                "reasoning": r[7],
                "track": r[8],
                "entry_hash": r[9],
                "previous_hash": r[10],
            }
            for r in rows
        ]
