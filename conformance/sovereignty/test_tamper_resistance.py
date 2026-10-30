"""SKI Framework v3.0 §6 — Ledger tamper resistance.

The strong claim: even an attacker with full SQL access who disables
the append-only triggers, edits a row, AND recomputes the hash chain
forward cannot escape detection, because ``verify_integrity``
recomputes every entry hash from the canonical payload — the edited
row's stored hash no longer matches its recomputed hash unless the
attacker also rewrites the hashes, in which case the chain linkage to
the (offline-backed-up) genesis diverges and replay against telemetry
fails.

Infrastructure: requires a throwaway Postgres reachable via the
``SKI_L3_LEDGER_DSN`` environment variable (CI provides a service
container; locally: ``docker run -e POSTGRES_PASSWORD=x -p 5433:5432
postgres:16`` and export the DSN). Skips cleanly when unset — the
suite stays runnable anywhere.
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

DSN = os.environ.get("SKI_L3_LEDGER_DSN")
REPO = Path(__file__).resolve().parent.parent.parent
SCHEMA = REPO / "reference-implementation" / "src" / "ledger" / "schema.sql"
TRIGGERS = REPO / "reference-implementation" / "src" / "ledger" / "append_only.sql"
# The v4 cases append through the runtime's own LedgerClient.
_RUNTIME_SRC = str(REPO / "reference-implementation" / "src")
if _RUNTIME_SRC not in sys.path:
    sys.path.insert(0, _RUNTIME_SRC)

pytestmark = pytest.mark.sovereignty


def _connect() -> tuple[Any, Any]:
    if not DSN:
        pytest.skip("SKI_L3_LEDGER_DSN not set; destructive tamper rig needs a throwaway Postgres.")
    sqlalchemy = pytest.importorskip("sqlalchemy")
    return sqlalchemy, sqlalchemy.create_engine(DSN)


def _seed(engine: Any, sqlalchemy: Any, n: int = 3) -> None:
    from audit_ledger.canonical import canonical_entry_payload

    text = sqlalchemy.text
    with engine.begin() as cx:
        cx.execute(text("DROP TABLE IF EXISTS ledger_entries CASCADE"))
        cx.exec_driver_sql(SCHEMA.read_text(encoding="utf-8").replace("%", "%%"))
        cx.exec_driver_sql(TRIGGERS.read_text(encoding="utf-8").replace("%", "%%"))
        prev = "0" * 64
        for seq in range(1, n + 1):
            ts = datetime(2026, 6, 15, 12, seq, tzinfo=timezone.utc).isoformat()
            payload = canonical_entry_payload(
                sequence_number=seq,
                previous_hash=prev,
                timestamp_iso=ts,
                verdict="CLEAR",
                telemetry_id=f"tel-{seq}",
                telemetry_hash=hashlib.sha256(f"telemetry-{seq}".encode()).hexdigest(),
                rule_id="energy.so2.cap",
                kg_version="kg-1",
                ski_model_version="3.1.0a2",
                reasoning="seeded",
                track="v3-evaluator",
            )
            entry_hash = hashlib.sha256(payload).hexdigest()
            cx.execute(
                text(
                    "INSERT INTO ledger_entries (sequence_number, previous_hash, entry_hash,"
                    " timestamp, verdict, telemetry_id, telemetry_hash, rule_id,"
                    " knowledge_graph_version, ski_model_version, reasoning, track)"
                    " VALUES (:seq, :prev, :eh, :ts, 'CLEAR', :tid, :th, 'energy.so2.cap',"
                    " 'kg-1', '3.1.0a2', 'seeded', 'v3-evaluator')"
                ),
                {
                    "seq": seq,
                    "prev": prev,
                    "eh": entry_hash,
                    "ts": ts,
                    "tid": f"tel-{seq}",
                    "th": hashlib.sha256(f"telemetry-{seq}".encode()).hexdigest(),
                },
            )
            prev = entry_hash


def test_append_only_triggers_block_update() -> None:
    sqlalchemy, engine = _connect()
    _seed(engine, sqlalchemy)
    with (
        pytest.raises(Exception, match=r"(?i)append-only|not allowed|denied|exception"),
        engine.begin() as cx,
    ):
        cx.execute(sqlalchemy.text("UPDATE ledger_entries SET verdict='FLAG' WHERE sequence_number=2"))


def test_modified_ledger_row_fails_verify_integrity() -> None:
    sqlalchemy, engine = _connect()
    _seed(engine, sqlalchemy)
    from audit_ledger.ledger import Ledger

    assert DSN is not None
    assert Ledger(DSN).verify_integrity().is_valid, "seeded ledger must verify clean"

    # Superuser attack: disable triggers, flip a verdict, leave hashes alone.
    with engine.begin() as cx:
        cx.execute(sqlalchemy.text("ALTER TABLE ledger_entries DISABLE TRIGGER USER"))
        cx.execute(sqlalchemy.text("UPDATE ledger_entries SET verdict='CLEAR' WHERE sequence_number=2"))
        cx.execute(sqlalchemy.text("UPDATE ledger_entries SET reasoning='tampered' WHERE sequence_number=2"))
        cx.execute(sqlalchemy.text("ALTER TABLE ledger_entries ENABLE TRIGGER USER"))

    assert DSN is not None
    result = Ledger(DSN).verify_integrity()
    assert not result.is_valid, (
        "verify_integrity must detect an in-place edit via entry-hash recomputation, "
        "even though chain linkage (previous_hash pointers) is untouched."
    )


# ---------------------------------------------------------------------------
# Ledger v4: the chain also commits to the stored envelope and transcript.
# ---------------------------------------------------------------------------


def _evaluation(reading: float, *, signed: bool) -> Any:
    import asyncio

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ski_model.v3.evaluator import FakeLLM, V3Evaluator
    from ski_model.v3.signing import TranscriptSigner

    key = Ed25519PrivateKey.generate()
    evaluator = V3Evaluator(
        llm=FakeLLM(),
        kg_version_hash="sha256:" + "0" * 64,
        signer=TranscriptSigner(key, key.public_key()) if signed else None,
    )
    snapshot = {
        "version": "kg-1",
        "obligations": [
            {"id": "energy.so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
        ],
        "definitions": [],
    }
    return asyncio.run(
        evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": reading},
            kg_snapshot=snapshot,
            subject="stack-1",
            as_of=datetime.now(timezone.utc),
        )
    )


def _seed_mixed(engine: Any, sqlalchemy: Any) -> None:
    """Three v3-format entries, then two v4 entries written by the runtime's LedgerClient."""
    import asyncio

    from ski_model.ledger_client import LedgerClient

    _seed(engine, sqlalchemy, n=3)
    # 142.5 is stored as written; 1e300 comes back from JSONB as a 301-digit
    # integer literal and must still verify (spec/test-vectors/ledger/).
    evaluations = [_evaluation(142.5, signed=True), _evaluation(1e300, signed=False)]

    async def _append() -> None:
        assert DSN is not None
        client = LedgerClient(DSN)
        await client.initialize()
        try:
            for i, result in enumerate(evaluations, start=4):
                await client.append_v3(
                    envelope=result.envelope,
                    transcript=result.transcript,
                    telemetry_id=f"tel-{i}",
                    telemetry_hash=f"{i:064x}",
                    rule_id="energy.so2.cap",
                    kg_version="kg-1",
                    ski_model_version="3.2.0",
                )
        finally:
            await client.close()

    asyncio.run(_append())


def _tamper(engine: Any, sqlalchemy: Any, statement: str) -> None:
    with engine.begin() as cx:
        cx.execute(sqlalchemy.text("ALTER TABLE ledger_entries DISABLE TRIGGER USER"))
        cx.execute(sqlalchemy.text(statement))
        cx.execute(sqlalchemy.text("ALTER TABLE ledger_entries ENABLE TRIGGER USER"))


def _issue_types(result: Any) -> set[str]:
    return {issue.issue_type for issue in result.issues}


def test_mixed_v3_and_v4_ledger_verifies() -> None:
    sqlalchemy, engine = _connect()
    _seed_mixed(engine, sqlalchemy)
    from audit_ledger.ledger import Ledger

    assert DSN is not None
    result = Ledger(DSN).verify_integrity()
    assert result.is_valid, result.issues
    assert result.entry_hash_verified_count == 5


def test_edited_v4_envelope_fails_verify_integrity() -> None:
    sqlalchemy, engine = _connect()
    _seed_mixed(engine, sqlalchemy)
    from audit_ledger.ledger import Ledger

    # The verdict-line columns are untouched; only the stored evidence changes.
    _tamper(
        engine,
        sqlalchemy,
        "UPDATE ledger_entries SET envelope_json = jsonb_set(envelope_json, '{reasoning}', '\"rewritten\"')"
        " WHERE sequence_number = 4",
    )
    assert DSN is not None
    result = Ledger(DSN).verify_integrity()
    assert not result.is_valid
    assert "ENTRY_HASH_MISMATCH" in _issue_types(result)


def test_edited_v4_transcript_fails_verify_integrity() -> None:
    sqlalchemy, engine = _connect()
    _seed_mixed(engine, sqlalchemy)
    from audit_ledger.ledger import Ledger

    _tamper(
        engine,
        sqlalchemy,
        "UPDATE ledger_entries SET transcript_json = jsonb_set(transcript_json, '{backend_name}', '\"other\"')"
        " WHERE sequence_number = 4",
    )
    assert DSN is not None
    result = Ledger(DSN).verify_integrity()
    assert not result.is_valid
    assert "ENTRY_HASH_MISMATCH" in _issue_types(result)


def test_rewritten_envelope_hash_column_is_detected() -> None:
    sqlalchemy, engine = _connect()
    _seed_mixed(engine, sqlalchemy)
    from audit_ledger.ledger import Ledger

    _tamper(
        engine,
        sqlalchemy,
        "UPDATE ledger_entries SET envelope_hash = 'sha256:' || repeat('0', 64) WHERE sequence_number = 5",
    )
    assert DSN is not None
    result = Ledger(DSN).verify_integrity()
    assert not result.is_valid
    assert "EVIDENCE_HASH_MISMATCH" in _issue_types(result)


def test_v3_format_entry_after_v4_is_flagged() -> None:
    sqlalchemy, engine = _connect()
    _seed_mixed(engine, sqlalchemy)
    from audit_ledger.canonical import canonical_entry_payload
    from audit_ledger.ledger import Ledger

    # A correctly chained entry in the old format: what a pre-v4 runtime
    # pointed at this ledger would write. Its evidence is not chained.
    with engine.begin() as cx:
        head = cx.execute(
            sqlalchemy.text("SELECT entry_hash FROM ledger_entries ORDER BY sequence_number DESC LIMIT 1")
        ).scalar_one()
        ts = datetime.now(timezone.utc).isoformat()
        payload = canonical_entry_payload(
            sequence_number=6,
            previous_hash=head,
            timestamp_iso=ts,
            verdict="CLEAR",
            telemetry_id="tel-6",
            telemetry_hash="6" * 64,
            rule_id=None,
            kg_version="kg-1",
            ski_model_version="3.1.0",
            reasoning="old writer",
            track="v3-evaluator",
        )
        cx.execute(
            sqlalchemy.text(
                "INSERT INTO ledger_entries (sequence_number, previous_hash, entry_hash, timestamp, verdict,"
                " telemetry_id, telemetry_hash, knowledge_graph_version, ski_model_version, reasoning, track)"
                " VALUES (6, :prev, :eh, :ts, 'CLEAR', 'tel-6', :th, 'kg-1', '3.1.0', 'old writer', 'v3-evaluator')"
            ),
            {"prev": head, "eh": hashlib.sha256(payload).hexdigest(), "ts": ts, "th": "6" * 64},
        )
    assert DSN is not None
    result = Ledger(DSN).verify_integrity()
    assert not result.is_valid
    assert _issue_types(result) == {"FORMAT_DOWNGRADE"}
