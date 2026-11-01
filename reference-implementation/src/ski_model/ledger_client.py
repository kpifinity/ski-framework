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
from typing import TYPE_CHECKING, Any, Optional

from ski_schemas.ledger import (
    LEDGER_SCHEMA_VERSION,
    entry_payload_v4,
    entry_payload_v5,
    evidence_hash,
    verdict_signing_bytes,
)
from ski_schemas.merkle import checkpoint_statement, merkle_root
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .v3.envelope import V3Verdict as Verdict
from .v3.envelope import V3VerdictEnvelope
from .v3.signing import TranscriptSigner
from .v3.transcript import LLMTranscript

if TYPE_CHECKING:
    from .timestamping import TimestampAuthority

logger = logging.getLogger(__name__)


def _enum_value(value: Any) -> str:
    """Return an enum member's ``.value``, or a plain string unchanged."""
    return str(getattr(value, "value", value))


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


_INSERT_V4 = """
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
# Format 5 adds the spec §7.1 columns and the verdict signature.
_INSERT_V5 = """
    INSERT INTO ledger_entries (
        sequence_number, previous_hash, entry_hash, timestamp,
        verdict, telemetry_id, telemetry_hash, rule_id,
        knowledge_graph_version, ski_model_version,
        reasoning, track,
        envelope_json, envelope_hash,
        transcript_json, transcript_signature, signing_key_id,
        verifier_status,
        tenant_id, kg_version_hash, model_weight_hash, schema_version,
        verdict_signature, verdict_signing_key_id
    ) VALUES (
        :seq, :prev, :hash, :ts,
        :verdict, :tid, :thash, :rule_id,
        :kg_version, :ski_model_version,
        :reasoning, :track,
        CAST(:envelope_json AS JSONB), :envelope_hash,
        CAST(:transcript_json AS JSONB), :transcript_signature, :signing_key_id,
        :verifier_status,
        :tenant_id, :kg_version_hash, :model_weight_hash, :schema_version,
        :verdict_signature, :verdict_signing_key_id
    )
"""


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
        # Ledger format 5 (spec §7.1 columns + verdict signatures): enabled by
        # the server once the schema has it (ensure_v5_ledger_schema).
        self.format5 = False
        self.tenant_id = "default"
        self.signer: Optional[TranscriptSigner] = None

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
        kg_version_hash: Optional[str] = None,
        model_weight_hash: Optional[str] = None,
    ) -> None:
        """Append a ledger entry (format 5, or 4 on an unmigrated ledger) with envelope + signed transcript.

        The envelope JSON, its canonical hash, and the (optional)
        transcript JSON / signature / key_id are all persisted so an
        auditor can independently replay the verdict per spec §6. The
        entry hash is the v4 payload (:mod:`ski_schemas.ledger`), which
        commits to the envelope and transcript digests as well as the
        verdict-line columns, so editing the stored evidence breaks the
        chain. Earlier (v3-format) entries keep their hashes; the chain
        continues across the format change.

        In format 5 the payload also chains the spec §7.1 columns
        (``tenant_id``, ``kg_version_hash``, ``model_weight_hash``,
        ``schema_version``) and the runtime signs the row's position
        (:func:`ski_schemas.ledger.verdict_signing_bytes`).
        """
        assert self._session_factory is not None

        # ``use_enum_values`` only applies on validation; an envelope built via
        # ``model_copy(update=...)`` can still hold enum members, and ``str()``
        # on a ``(str, Enum)`` member is ``'V3Verdict.X'`` on Python 3.11+ --
        # which would break the verdict CHECK constraint and the entry hash.
        verdict = _enum_value(envelope.verdict)
        verifier_status = _enum_value(envelope.verifier_result.status)

        # Hash the evidence from the exact JSON text stored, as the verifier does.
        envelope_text = json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False)
        envelope_hash = evidence_hash(envelope_text)

        transcript_text = (
            json.dumps(transcript.model_dump(mode="json"), ensure_ascii=False)
            if transcript is not None
            else None
        )
        transcript_hash = evidence_hash(transcript_text)
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
            line: dict[str, Any] = {
                "sequence_number": sequence_number,
                "previous_hash": previous_hash,
                "timestamp_iso": timestamp_iso,
                "verdict": verdict,
                "telemetry_id": telemetry_id,
                "telemetry_hash": telemetry_hash,
                "rule_id": rule_id,
                "kg_version": kg_version,
                "ski_model_version": ski_model_version,
                "reasoning": envelope.reasoning,
                "track": track,
                "envelope_hash": envelope_hash,
                "transcript_hash": transcript_hash,
                "transcript_signature": transcript_signature,
                "signing_key_id": signing_key_id,
                "verifier_status": verifier_status,
            }
            v5: dict[str, Any] = {
                "tenant_id": None,
                "kg_version_hash": None,
                "model_weight_hash": None,
                "schema_version": None,
                "verdict_signature": None,
                "verdict_signing_key_id": None,
            }
            if self.format5:
                v5.update(
                    tenant_id=self.tenant_id,
                    kg_version_hash=kg_version_hash,
                    model_weight_hash=model_weight_hash,
                    schema_version=LEDGER_SCHEMA_VERSION,
                )
                payload = entry_payload_v5(
                    **line,
                    tenant_id=self.tenant_id,
                    kg_version_hash=kg_version_hash,
                    model_weight_hash=model_weight_hash,
                    schema_version=LEDGER_SCHEMA_VERSION,
                )
                entry_hash = hashlib.sha256(payload).hexdigest()
                if self.signer is not None:
                    v5["verdict_signature"] = self.signer.sign(
                        verdict_signing_bytes(
                            sequence_number=sequence_number,
                            entry_hash=entry_hash,
                            telemetry_id=telemetry_id,
                            transcript_id=transcript.transcript_id if transcript is not None else None,
                        )
                    )
                    v5["verdict_signing_key_id"] = self.signer.key_id
            else:
                entry_hash = hashlib.sha256(entry_payload_v4(**line)).hexdigest()

            params: dict[str, Any] = {
                "seq": sequence_number,
                "prev": previous_hash,
                "hash": entry_hash,
                "ts": timestamp_iso,
                "verdict": verdict,
                "tid": telemetry_id,
                "thash": telemetry_hash,
                "rule_id": rule_id,
                "kg_version": kg_version,
                "ski_model_version": ski_model_version,
                "reasoning": envelope.reasoning,
                "track": track,
                "envelope_json": envelope_text,
                "envelope_hash": envelope_hash,
                "transcript_json": transcript_text,
                "transcript_signature": transcript_signature,
                "signing_key_id": signing_key_id,
                "verifier_status": verifier_status,
            }
            # An unmigrated (format-4) ledger has no format-5 columns to name.
            await session.execute(
                text(_INSERT_V5 if self.format5 else _INSERT_V4), {**params, **v5} if self.format5 else params
            )

    async def register_signing_key(self) -> None:
        """Record the runtime's public key, so signatures verify from the ledger (format 5)."""
        assert self._session_factory is not None and self.signer is not None
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO ledger_signing_keys (key_id, public_key_pem) VALUES (:k, :pem) "
                    "ON CONFLICT (key_id) DO NOTHING"
                ),
                {"k": self.signer.key_id, "pem": self.signer.public_key_pem},
            )

    async def entries_since_checkpoint(self) -> int:
        """How many entries the latest checkpoint does not cover yet."""
        assert self._session_factory is not None
        async with self._session_factory() as session:
            head = (
                await session.execute(text("SELECT COALESCE(MAX(sequence_number), 0) FROM ledger_entries"))
            ).scalar()
            covered = (
                await session.execute(
                    text("SELECT COALESCE(MAX(tree_size), 0) FROM ledger_checkpoints WHERE tenant_id = :t"),
                    {"t": self.tenant_id},
                )
            ).scalar()
        return int(head or 0) - int(covered or 0)

    async def checkpoint(self, tsa: Optional[TimestampAuthority] = None) -> Optional[dict[str, Any]]:
        """Sign (and, with ``tsa``, timestamp) the Merkle root of every entry so far; None if nothing new."""
        assert self._session_factory is not None and self.signer is not None
        async with self._session_factory() as session:
            hashes = [
                str(h)
                for (h,) in (
                    await session.execute(
                        text("SELECT entry_hash FROM ledger_entries ORDER BY sequence_number")
                    )
                ).all()
            ]
            covered = (
                await session.execute(
                    text("SELECT COALESCE(MAX(tree_size), 0) FROM ledger_checkpoints WHERE tenant_id = :t"),
                    {"t": self.tenant_id},
                )
            ).scalar()
        if not hashes or len(hashes) <= int(covered or 0):
            return None
        created_at = datetime.now(timezone.utc).isoformat()
        root = merkle_root(hashes)
        statement = checkpoint_statement(
            tenant_id=self.tenant_id,
            tree_size=len(hashes),
            root_hash=root,
            last_entry_hash=hashes[-1],
            created_at=created_at,
        )
        row: dict[str, Any] = {
            "tenant": self.tenant_id,
            "size": len(hashes),
            "root": root,
            "last": hashes[-1],
            "created_at": created_at,
            "key": self.signer.key_id,
            "sig": self.signer.sign(statement),
            "tsa_url": tsa.url if tsa is not None else None,
            "tsa_response": await tsa.timestamp(statement) if tsa is not None else None,
        }
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO ledger_checkpoints (
                        tenant_id, tree_size, root_hash, last_entry_hash, created_at,
                        signing_key_id, signature, tsa_url, tsa_response
                    ) VALUES (:tenant, :size, :root, :last, :created_at, :key, :sig, :tsa_url, :tsa_response)
                    ON CONFLICT (tenant_id, tree_size) DO NOTHING
                    """
                ),
                row,
            )
        logger.info("Ledger checkpoint: tree_size=%d root=%s", len(hashes), root)
        return row

    async def evidence(self, sequence_number: int) -> Optional[dict[str, Any]]:
        """One format-5 entry's evidence: its row, and the entry hashes of the latest checkpoint covering it.

        ``checkpoint_hashes`` is ``None`` until a checkpoint covers the entry
        (no receipt can be issued yet). Returns ``None`` for no such entry.
        """
        assert self._session_factory is not None
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT sequence_number, entry_hash, previous_hash, timestamp, verdict,
                                   telemetry_id, telemetry_hash, rule_id, knowledge_graph_version,
                                   ski_model_version, track, envelope_json, envelope_hash,
                                   transcript_json, signing_key_id, verifier_status, tenant_id,
                                   kg_version_hash, model_weight_hash, schema_version,
                                   verdict_signature, verdict_signing_key_id
                            FROM ledger_entries WHERE sequence_number = :seq
                            """
                        ),
                        {"seq": sequence_number},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            tree_size = (
                await session.execute(
                    text(
                        "SELECT MIN(tree_size) FROM ledger_checkpoints "
                        "WHERE tree_size >= :seq AND tenant_id = :tenant"
                    ),
                    {"seq": sequence_number, "tenant": self.tenant_id},
                )
            ).scalar()
            hashes = (
                [
                    str(h)
                    for (h,) in (
                        await session.execute(
                            text(
                                "SELECT entry_hash FROM ledger_entries WHERE sequence_number <= :n "
                                "ORDER BY sequence_number"
                            ),
                            {"n": int(tree_size)},
                        )
                    ).all()
                ]
                if tree_size is not None
                else None
            )
        entry = {
            k: (v.strip() if isinstance(v, str) and k.endswith(("_hash", "_key_id")) else v)
            for k, v in row.items()
        }
        entry["timestamp"] = row["timestamp"].isoformat() if row["timestamp"] is not None else None
        return {"entry": entry, "checkpoint_hashes": hashes}

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
