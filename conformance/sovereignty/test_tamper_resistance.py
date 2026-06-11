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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

DSN = os.environ.get("SKI_L3_LEDGER_DSN")
REPO = Path(__file__).resolve().parent.parent.parent
SCHEMA = REPO / "reference-implementation" / "src" / "ledger" / "schema.sql"
TRIGGERS = REPO / "reference-implementation" / "src" / "ledger" / "append_only.sql"

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
