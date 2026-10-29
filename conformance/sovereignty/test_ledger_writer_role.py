"""SKI Framework v3.2.0 — least-privilege ledger role (``ski_ledger_writer``).

The runtime must not connect to the audit ledger as the schema owner or
the bootstrap superuser: either could disable the append-only triggers
(``ALTER TABLE ... DISABLE TRIGGER``) or rewrite rows outright. The
reference schema therefore creates ``ski_ledger_writer`` (INSERT + SELECT
on the ledger, USAGE on its id sequence, nothing else) and the reference
deployments (docker-compose, Helm) connect the SKI Model as that role.

This rig proves, against a real PostgreSQL server, that the writer role:

* **cannot** UPDATE, DELETE or TRUNCATE ledger rows -- refused by the
  privilege system itself, before the append-only triggers even run;
* **cannot** ``ALTER TABLE ... DISABLE TRIGGER``, drop or create triggers,
  bypass them with ``session_replication_role``, rewind the id sequence,
  or create objects in schema ``public``;
* **can** still do everything the runtime needs: the v3 schema probe, the
  tenant clock-skew lookup, telemetry-buffer appends, and real
  ``LedgerClient.append_v3`` appends with signed transcripts that chain.

Infrastructure: requires a throwaway Postgres reachable via
``SKI_L3_LEDGER_DSN`` as a superuser (CI's sovereignty-l3 job provides
one). The rig drops and recreates the ledger tables. Skips cleanly when
the variable is unset.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

DSN = os.environ.get("SKI_L3_LEDGER_DSN")
REPO = Path(__file__).resolve().parent.parent.parent
LEDGER_SQL = REPO / "reference-implementation" / "src" / "ledger"
WRITER = "ski_ledger_writer"

# The runtime's own ledger client is exercised as the writer; the CI job
# does not install the reference implementation, so import it from source.
_RUNTIME_SRC = str(REPO / "reference-implementation" / "src")
if _RUNTIME_SRC not in sys.path:
    sys.path.insert(0, _RUNTIME_SRC)

pytestmark = pytest.mark.sovereignty


def _libpq_url(url: Any) -> str:
    rendered: str = url.set(drivername="postgresql").render_as_string(hide_password=False)
    return rendered


@pytest.fixture(scope="module")
def ledger() -> Iterator[dict[str, str]]:
    """Fresh ledger built by the owner from the shipped SQL; returns DSNs."""
    if not DSN:
        pytest.skip("SKI_L3_LEDGER_DSN not set; the writer-role rig needs a throwaway Postgres.")
    psycopg = pytest.importorskip("psycopg")
    sqlalchemy = pytest.importorskip("sqlalchemy")
    owner_url = sqlalchemy.engine.make_url(DSN)
    password = secrets.token_hex(16)  # hex only: safe to inline below
    with psycopg.connect(_libpq_url(owner_url), autocommit=True) as cx:
        cx.execute("DROP TABLE IF EXISTS telemetry_buffer, tenants, ledger_entries CASCADE")
        for path in (
            LEDGER_SQL / "schema.sql",
            LEDGER_SQL / "append_only.sql",
            LEDGER_SQL / "migrations" / "0002_transcript_columns.sql",
            LEDGER_SQL / "telemetry_buffer.sql",
        ):
            cx.execute(path.read_text(encoding="utf-8"))  # no params => simple protocol
        cx.execute("CREATE TABLE telemetry_buffer_default PARTITION OF telemetry_buffer DEFAULT")
        cx.execute(
            "INSERT INTO tenants (tenant_id, display_name, buffer_retention_days, max_clock_skew_seconds)"
            " VALUES ('default', 'Default', 30, 60)"
        )
        # What ledger_writer_login.sh does on first init in compose/Helm.
        cx.execute(f"ALTER ROLE {WRITER} WITH LOGIN PASSWORD '{password}'")
    writer_url = owner_url.set(username=WRITER, password=password)
    yield {"owner": _libpq_url(owner_url), "writer": _libpq_url(writer_url)}


def _as_writer(ledger: dict[str, str], sql: str) -> None:
    import psycopg

    with psycopg.connect(ledger["writer"], autocommit=True) as cx:
        cx.execute(sql)


def _owner_scalar(ledger: dict[str, str], sql: str) -> Any:
    import psycopg

    with psycopg.connect(ledger["owner"], autocommit=True) as cx:
        row = cx.execute(sql).fetchone()
    assert row is not None
    return row[0]


def _envelope_and_transcript(seq: int) -> Any:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ski_model.v3.evaluator import FakeLLM, V3Evaluator
    from ski_model.v3.signing import TranscriptSigner

    key = Ed25519PrivateKey.generate()
    evaluator = V3Evaluator(
        llm=FakeLLM(),
        kg_version_hash="sha256:" + "0" * 64,
        signer=TranscriptSigner(key, key.public_key()),
    )
    snapshot = {
        "version": "kg-writer-test",
        "obligations": [
            {"id": "energy.so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
        ],
        "definitions": [],
    }
    return asyncio.run(
        evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": 40 + seq},
            kg_snapshot=snapshot,
            subject="stack-1",
            as_of=datetime.now(timezone.utc),
        )
    )


# ---------------------------------------------------------------------------
# The role itself
# ---------------------------------------------------------------------------


def test_writer_role_attributes_are_minimal(ledger: dict[str, str]) -> None:
    # WRITER is a fixed module constant (the role name under test), not external
    # input; these are read-only diagnostic queries. nosec silences B608's
    # string-built-query heuristic on the line it flags.
    attrs = _owner_scalar(
        ledger,
        "SELECT row(rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls)::text"  # nosec B608
        f" FROM pg_roles WHERE rolname = '{WRITER}'",
    )
    assert attrs == "(f,f,f,f,f)", f"{WRITER} must hold no elevated role attributes, got {attrs}"
    owner = _owner_scalar(ledger, "SELECT tableowner FROM pg_tables WHERE tablename = 'ledger_entries'")
    assert owner != WRITER, "the runtime role must not own the ledger table"


@pytest.mark.parametrize(
    ("privilege", "expected"),
    [
        ("SELECT", True),
        ("INSERT", True),
        ("UPDATE", False),
        ("DELETE", False),
        ("TRUNCATE", False),
        ("REFERENCES", False),
        ("TRIGGER", False),
    ],
)
def test_writer_table_privileges_are_exactly_insert_select(
    ledger: dict[str, str], privilege: str, expected: bool
) -> None:
    granted = _owner_scalar(
        ledger, f"SELECT has_table_privilege('{WRITER}', 'ledger_entries', '{privilege}')"
    )
    assert granted is expected, f"{WRITER} {privilege} on ledger_entries: expected {expected}"


# ---------------------------------------------------------------------------
# Tamper attempts the writer must not be able to make
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ledger_entries SET reasoning = 'tampered'",
        "DELETE FROM ledger_entries",
        "TRUNCATE ledger_entries",
        "UPDATE telemetry_buffer SET subject = 'tampered'",
        "DELETE FROM telemetry_buffer",
        "TRUNCATE telemetry_buffer",
    ],
)
def test_writer_cannot_rewrite_or_remove_rows(ledger: dict[str, str], sql: str) -> None:
    import psycopg

    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied for table"):
        _as_writer(ledger, sql)


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE ledger_entries DISABLE TRIGGER ledger_block_update",
        "ALTER TABLE ledger_entries DISABLE TRIGGER ALL",
        "DROP TRIGGER ledger_block_delete ON ledger_entries",
        "ALTER TABLE ledger_entries ADD COLUMN backdoor TEXT",
        "CREATE TRIGGER evil BEFORE INSERT ON ledger_entries"
        " FOR EACH ROW EXECUTE FUNCTION ledger_block_update_delete()",
        "SET session_replication_role = replica",
        "SELECT setval(pg_get_serial_sequence('ledger_entries', 'id'), 1)",
        "CREATE TABLE public.writer_owned (x int)",
    ],
)
def test_writer_cannot_disable_bypass_or_alter(ledger: dict[str, str], sql: str) -> None:
    import psycopg

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_writer(ledger, sql)


# ---------------------------------------------------------------------------
# ... while the runtime still works as that role
# ---------------------------------------------------------------------------


def test_runtime_reads_tenant_config_and_appends_to_buffer(ledger: dict[str, str]) -> None:
    import psycopg

    with psycopg.connect(ledger["writer"], autocommit=True) as cx:
        skew = cx.execute("SELECT max_clock_skew_seconds FROM tenants WHERE tenant_id = 'default'").fetchone()
        assert skew == (60,)
        cx.execute(
            "INSERT INTO telemetry_buffer (tenant_id, subject, telemetry_id, telemetry_ts,"
            " measurement, measurement_hash) VALUES ('default', 'stack-1', 'tel-1', NOW(),"
            " '{\"so2_ppm\": 41}', repeat('a', 64))"
        )
        count = cx.execute("SELECT count(*) FROM telemetry_buffer").fetchone()
    assert count == (1,)


def test_runtime_ledger_client_appends_as_writer(ledger: dict[str, str]) -> None:
    from ski_model.ledger_client import LedgerClient
    from ski_model.ledger_migrations import ensure_v3_ledger_schema

    results = [_envelope_and_transcript(seq) for seq in (1, 2)]

    async def _append() -> None:
        client = LedgerClient(ledger["writer"])
        await client.initialize()
        try:
            assert client._engine is not None
            # Startup schema probe must succeed (no-op) without DDL rights.
            await ensure_v3_ledger_schema(client._engine)
            for seq, result in enumerate(results, start=1):
                await client.append_v3(
                    envelope=result.envelope,
                    transcript=result.transcript,
                    telemetry_id=f"m-{seq}",
                    telemetry_hash=f"{seq:064x}",
                    rule_id="energy.so2.cap",
                    kg_version="kg-writer-test",
                    ski_model_version="3.2.0-test",
                )
        finally:
            await client.close()

    before = _owner_scalar(ledger, "SELECT count(*) FROM ledger_entries")
    asyncio.run(_append())
    assert _owner_scalar(ledger, "SELECT count(*) FROM ledger_entries") == before + 2
    assert _owner_scalar(ledger, "SELECT bool_and(chain_link_valid) FROM ledger_chain_linkage") is True
    assert (
        _owner_scalar(
            ledger,
            "SELECT count(*) FROM ledger_entries WHERE transcript_signature IS NOT NULL"
            " AND envelope_hash IS NOT NULL",
        )
        == before + 2
    )
