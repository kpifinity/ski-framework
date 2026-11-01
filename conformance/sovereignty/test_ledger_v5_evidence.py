"""SKI Framework v3.3.0 — ledger format 5: tamper-evident evidence, end to end (spec §7).

Against a real PostgreSQL ledger written by the runtime's own
``LedgerClient`` (as ``ski_ledger_writer``) and checked by ``audit-ledger
verify``, this rig proves:

* a clean format-5 ledger verifies: chain, entry hashes, every verdict
  signature (pinned key) and every checkpoint;
* an edit to any chained field, the spec §7.1 columns included, is detected;
* a verdict signature moved to another row is detected;
* a key that is not pinned is reported, and a substituted key row is caught;
* a **forward rewrite** by someone holding the runtime's own key (every hash
  and signature recomputed) is caught by the ledger's checkpoint, and, when
  the checkpoint rows were rewritten too, by an exported checkpoint file;
* a v3.2.x ledger (format 4) migrates in place with ``0003_ledger_v5.sql``:
  old entries keep verifying, new ones are format 5, and the writer role
  alone cannot migrate (the runtime keeps writing format 4).

Infrastructure: a throwaway Postgres via ``SKI_L3_LEDGER_DSN`` (superuser);
the rig drops and recreates the ledger tables. Skips cleanly otherwise.
"""

from __future__ import annotations

import asyncio
import hashlib
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

_RUNTIME_SRC = str(REPO / "reference-implementation" / "src")
if _RUNTIME_SRC not in sys.path:
    sys.path.insert(0, _RUNTIME_SRC)

pytestmark = pytest.mark.sovereignty

_TABLES = "telemetry_buffer, tenants, ledger_checkpoints, ledger_signing_keys, ledger_entries"
_V5_COLUMNS = (
    "tenant_id",
    "kg_version_hash",
    "model_weight_hash",
    "schema_version",
    "verdict_signature",
    "verdict_signing_key_id",
)


def _libpq(url: Any) -> str:
    rendered: str = url.set(drivername="postgresql").render_as_string(hide_password=False)
    return rendered


@pytest.fixture
def dsns() -> Iterator[dict[str, str]]:
    """A fresh format-5 ledger built by the owner from the shipped SQL; owner and writer DSNs."""
    if not DSN:
        pytest.skip("SKI_L3_LEDGER_DSN not set; the ledger-v5 rig needs a throwaway Postgres.")
    psycopg = pytest.importorskip("psycopg")
    sqlalchemy = pytest.importorskip("sqlalchemy")
    owner = sqlalchemy.engine.make_url(DSN)
    password = secrets.token_hex(16)
    with psycopg.connect(_libpq(owner), autocommit=True) as cx:
        cx.execute(f"DROP TABLE IF EXISTS {_TABLES} CASCADE")
        for name in ("schema.sql", "append_only.sql", "telemetry_buffer.sql"):
            cx.execute((LEDGER_SQL / name).read_text(encoding="utf-8"))
        cx.execute(f"ALTER ROLE {WRITER} WITH LOGIN PASSWORD '{password}'")
    yield {"owner": _libpq(owner), "writer": _libpq(owner.set(username=WRITER, password=password))}
    with psycopg.connect(_libpq(owner), autocommit=True) as cx:
        cx.execute(f"DROP TABLE IF EXISTS {_TABLES} CASCADE")


def _signer() -> Any:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ski_model.v3.signing import TranscriptSigner

    key = Ed25519PrivateKey.generate()
    return TranscriptSigner(key, key.public_key())


def _evaluation(signer: Any, so2: int) -> Any:
    from ski_model.v3.evaluator import FakeLLM, V3Evaluator

    evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash="sha256:" + "0" * 64, signer=signer)
    snapshot = {
        "version": "kg-v5-test",
        "obligations": [
            {"id": "energy.so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
        ],
        "definitions": [],
    }
    return asyncio.run(
        evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": so2},
            kg_snapshot=snapshot,
            subject="stack-1",
            as_of=datetime.now(timezone.utc),
        )
    )


def _write(
    dsn: str, signer: Any, readings: list[int], *, checkpoint_every: int = 0, format5: bool = True
) -> None:
    """Append one entry per reading through the runtime's LedgerClient, checkpointing as configured."""
    from ski_model.ledger_client import LedgerClient

    results = [_evaluation(signer, so2) for so2 in readings]

    async def run() -> None:
        client = LedgerClient(dsn)
        await client.initialize()
        client.format5, client.signer, client.tenant_id = format5, signer, "plant-7"
        try:
            if format5:
                await client.register_signing_key()
            for i, result in enumerate(results, start=1):
                await client.append_v3(
                    envelope=result.envelope,
                    transcript=result.transcript,
                    telemetry_id=f"m-{secrets.token_hex(4)}",
                    telemetry_hash=hashlib.sha256(os.urandom(8)).hexdigest(),
                    rule_id="energy.so2.cap",
                    kg_version="kg-v5-test",
                    ski_model_version="3.3.0-test",
                    kg_version_hash="sha256:" + "1" * 64,
                    model_weight_hash="sha256:" + "2" * 64,
                )
                if checkpoint_every and i % checkpoint_every == 0:
                    await client.checkpoint()
        finally:
            await client.close()

    asyncio.run(run())


def _sa(dsn: str) -> str:
    """The SQLAlchemy URL for a libpq DSN, on psycopg 3 (the driver the runtime and CI install)."""
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def _verify(dsn: str, **kwargs: Any) -> Any:
    from audit_ledger.ledger import Ledger

    return Ledger(_sa(dsn)).verify_integrity(**kwargs)


def _kinds(result: Any) -> set[str]:
    return {issue.issue_type for issue in result.issues}


def _owner_sql(dsns: dict[str, str], *statements: str) -> None:
    """Run statements as the owner with the append-only triggers off: what a malicious DBA can do."""
    import psycopg

    with psycopg.connect(dsns["owner"], autocommit=True) as cx:
        for table in ("ledger_entries", "ledger_checkpoints"):
            cx.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        try:
            for statement in statements:
                cx.execute(statement)
        finally:
            for table in ("ledger_entries", "ledger_checkpoints"):
                cx.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")


# ---------------------------------------------------------------------------
# A clean format-5 ledger
# ---------------------------------------------------------------------------


def test_clean_format5_ledger_verifies_with_signatures_and_checkpoints(dsns: dict[str, str]) -> None:
    signer = _signer()
    _write(dsns["writer"], signer, [40, 140, 60, 70], checkpoint_every=2)
    result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert result.is_valid, result.issues
    assert result.entry_hash_verified_count == 4
    assert result.verdict_signatures_verified == 4
    assert result.checkpoints_verified == 2


def test_spec_7_1_columns_are_written(dsns: dict[str, str]) -> None:
    import psycopg

    _write(dsns["writer"], _signer(), [40])
    with psycopg.connect(dsns["owner"]) as cx:
        row = cx.execute(
            "SELECT tenant_id, kg_version_hash, model_weight_hash, schema_version FROM ledger_entries"
        ).fetchone()
    assert row == ("plant-7", "sha256:" + "1" * 64, "sha256:" + "2" * 64, "3.0.0")


# ---------------------------------------------------------------------------
# Edits, moved signatures, keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column, value",
    [
        ("tenant_id", "'plant-8'"),
        ("model_weight_hash", "'sha256:" + "3" * 64 + "'"),
        ("kg_version_hash", "NULL"),
        ("schema_version", "'2.0.0'"),
        ("verdict", "'CLEAR'"),
        ("envelope_json", "jsonb_set(envelope_json, '{reasoning}', '\"edited\"')"),
        ("transcript_json", "jsonb_set(transcript_json, '{backend_name}', '\"edited\"')"),
    ],
)
def test_an_edit_to_any_chained_field_is_detected(dsns: dict[str, str], column: str, value: str) -> None:
    signer = _signer()
    _write(dsns["writer"], signer, [40, 140, 60])
    _owner_sql(dsns, f"UPDATE ledger_entries SET {column} = {value} WHERE sequence_number = 2")  # nosec B608 -- test fixture SQL with constant values
    result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert not result.is_valid
    assert "ENTRY_HASH_MISMATCH" in _kinds(result), result.issues


def test_a_verdict_signature_moved_to_another_row_is_detected(dsns: dict[str, str]) -> None:
    signer = _signer()
    _write(dsns["writer"], signer, [40, 60])
    _owner_sql(
        dsns,
        "UPDATE ledger_entries SET verdict_signature = "
        "(SELECT verdict_signature FROM ledger_entries WHERE sequence_number = 1) WHERE sequence_number = 2",
    )
    result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert "VERDICT_SIGNATURE_INVALID" in _kinds(result)
    assert result.verdict_signatures_verified == 1


def test_an_unpinned_key_is_not_trusted(dsns: dict[str, str]) -> None:
    _write(dsns["writer"], _signer(), [40], checkpoint_every=1)
    result = _verify(dsns["owner"], trusted_key_ids=[_signer().key_id])
    assert not result.is_valid
    assert "UNTRUSTED_SIGNING_KEY" in _kinds(result)


def test_without_a_pin_the_keys_are_reported_not_trusted(dsns: dict[str, str]) -> None:
    signer = _signer()
    _write(dsns["writer"], signer, [40], checkpoint_every=1)
    result = _verify(dsns["owner"])
    assert result.is_valid
    assert any("--trusted-key-id" in w and signer.key_id in w for w in result.warnings)


def test_a_substituted_public_key_is_caught(dsns: dict[str, str]) -> None:
    signer, attacker = _signer(), _signer()
    _write(dsns["writer"], signer, [40])
    _owner_sql(
        dsns,
        "ALTER TABLE ledger_signing_keys DISABLE TRIGGER USER",
        f"UPDATE ledger_signing_keys SET public_key_pem = '{attacker.public_key_pem}'",  # nosec B608 -- test fixture SQL with constant values
        "ALTER TABLE ledger_signing_keys ENABLE TRIGGER USER",
    )
    result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert {"SIGNING_KEY_MISMATCH", "VERDICT_SIGNATURE_INVALID"} <= _kinds(result)


# ---------------------------------------------------------------------------
# Forward rewrite with the runtime's own key: only checkpoints catch it
# ---------------------------------------------------------------------------


def _rewrite_forward(dsns: dict[str, str], signer: Any, from_seq: int) -> None:
    """Change entry ``from_seq``'s verdict and re-chain and re-sign every later entry with the real key."""
    import psycopg
    from ski_schemas.ledger import entry_payload_v5, evidence_hash, verdict_signing_bytes

    with psycopg.connect(dsns["owner"], autocommit=True) as cx:
        rows = cx.execute(
            "SELECT sequence_number, previous_hash, timestamp, verdict, telemetry_id, telemetry_hash, rule_id, "
            "knowledge_graph_version, ski_model_version, reasoning, track, envelope_json::text, "
            "transcript_json::text, transcript_signature, signing_key_id, verifier_status, tenant_id, "
            "kg_version_hash, model_weight_hash, schema_version, transcript_json->>'transcript_id' "
            "FROM ledger_entries ORDER BY sequence_number"
        ).fetchall()
        prev = rows[from_seq - 2][0:2] and None
        cx.execute("ALTER TABLE ledger_entries DISABLE TRIGGER USER")
        try:
            prev_hash = None
            for row in rows:
                seq = row[0]
                if seq < from_seq:
                    prev_hash = None
                    continue
                verdict = "CLEAR" if seq == from_seq else row[3]
                previous = row[1] if prev_hash is None else prev_hash
                payload = entry_payload_v5(
                    sequence_number=seq,
                    previous_hash=previous,
                    timestamp_iso=row[2].isoformat(),
                    verdict=verdict,
                    telemetry_id=row[4],
                    telemetry_hash=row[5],
                    rule_id=row[6],
                    kg_version=row[7],
                    ski_model_version=row[8],
                    reasoning=row[9],
                    track=row[10],
                    envelope_hash=evidence_hash(row[11]),
                    transcript_hash=evidence_hash(row[12]),
                    transcript_signature=row[13],
                    signing_key_id=row[14].strip() if row[14] else None,
                    verifier_status=row[15],
                    tenant_id=row[16],
                    kg_version_hash=row[17],
                    model_weight_hash=row[18],
                    schema_version=row[19],
                )
                entry_hash = hashlib.sha256(payload).hexdigest()
                signature = signer.sign(
                    verdict_signing_bytes(
                        sequence_number=seq, entry_hash=entry_hash, telemetry_id=row[4], transcript_id=row[20]
                    )
                )
                cx.execute(
                    "UPDATE ledger_entries SET verdict = %s, previous_hash = %s, entry_hash = %s, "
                    "verdict_signature = %s WHERE sequence_number = %s",
                    (verdict, previous, entry_hash, signature, seq),
                )
                prev_hash = entry_hash
        finally:
            cx.execute("ALTER TABLE ledger_entries ENABLE TRIGGER USER")
        del prev


def test_forward_rewrite_with_the_real_key_passes_the_chain_but_not_the_checkpoint(
    dsns: dict[str, str],
) -> None:
    signer = _signer()
    _write(dsns["writer"], signer, [40, 140, 60, 70], checkpoint_every=4)
    _rewrite_forward(dsns, signer, from_seq=2)  # the FLAG becomes CLEAR, the chain is re-made
    result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert result.entry_hash_verified_count == 4 and result.verdict_signatures_verified == 4
    assert _kinds(result) == {"CHECKPOINT_MISMATCH"}, result.issues


def test_exported_checkpoint_catches_a_rewrite_of_the_checkpoints_too(
    dsns: dict[str, str], tmp_path: Path
) -> None:
    from audit_ledger.evidence import export_checkpoints
    from audit_ledger.ledger import Ledger

    signer = _signer()
    _write(dsns["writer"], signer, [40, 140, 60, 70], checkpoint_every=4)
    ledger = Ledger(_sa(dsns["owner"]))
    with ledger.Session() as session:
        (exported,) = export_checkpoints(session, tmp_path)  # to WORM storage
    _rewrite_forward(dsns, signer, from_seq=2)
    _owner_sql(dsns, "DELETE FROM ledger_checkpoints")
    in_ledger_only = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert in_ledger_only.is_valid  # nothing left in the database to contradict the rewrite
    with_export = _verify(dsns["owner"], trusted_key_ids=[signer.key_id], checkpoints=[exported])
    assert _kinds(with_export) == {"CHECKPOINT_MISMATCH"}, with_export.issues


def test_deleted_entries_beyond_a_checkpoint_are_detected(dsns: dict[str, str]) -> None:
    signer = _signer()
    _write(dsns["writer"], signer, [40, 60, 70], checkpoint_every=3)
    _owner_sql(dsns, "DELETE FROM ledger_entries WHERE sequence_number = 3")
    assert "CHECKPOINT_BEYOND_LEDGER" in _kinds(_verify(dsns["owner"], trusted_key_ids=[signer.key_id]))


def test_new_tables_are_append_only_for_the_writer(dsns: dict[str, str]) -> None:
    import psycopg

    signer = _signer()
    _write(dsns["writer"], signer, [40], checkpoint_every=1)
    for statement in (
        "UPDATE ledger_checkpoints SET root_hash = repeat('0', 64)",
        "DELETE FROM ledger_checkpoints",
        "UPDATE ledger_signing_keys SET public_key_pem = 'x'",
        "DELETE FROM ledger_signing_keys",
    ):
        with psycopg.connect(dsns["writer"], autocommit=True) as cx, pytest.raises(psycopg.Error):
            cx.execute(statement)


# ---------------------------------------------------------------------------
# Migration from a v3.2.x (format 4) ledger
# ---------------------------------------------------------------------------


def _downgrade_to_v32(dsns: dict[str, str]) -> None:
    """The v3.2.x schema: no format-5 columns or tables."""
    import psycopg

    with psycopg.connect(dsns["owner"], autocommit=True) as cx:
        cx.execute("DROP TABLE ledger_checkpoints, ledger_signing_keys")
        cx.execute("ALTER TABLE ledger_entries " + ", ".join(f"DROP COLUMN {c}" for c in _V5_COLUMNS))


def _ensure_v5(dsn: str) -> bool:
    from ski_model.ledger_client import LedgerClient
    from ski_model.ledger_migrations import ensure_v5_ledger_schema

    async def run() -> bool:
        client = LedgerClient(dsn)
        await client.initialize()
        try:
            assert client._engine is not None
            return await ensure_v5_ledger_schema(client._engine)
        finally:
            await client.close()

    return asyncio.run(run())


def test_v32_ledger_migrates_and_keeps_verifying(dsns: dict[str, str]) -> None:
    signer = _signer()
    _downgrade_to_v32(dsns)
    _write(dsns["writer"], signer, [40, 140], format5=False)  # a v3.2.x runtime: format 4
    assert _verify(dsns["owner"]).is_valid

    assert _ensure_v5(dsns["writer"]) is False  # least privilege: cannot migrate, keeps format 4
    assert _ensure_v5(dsns["owner"]) is True  # 0003_ledger_v5.sql, applied in place
    assert _ensure_v5(dsns["owner"]) is True  # idempotent

    _write(dsns["writer"], signer, [60, 70], checkpoint_every=2)  # the writer has the new grants
    result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert result.is_valid, result.issues
    assert result.entry_hash_verified_count == 4
    assert result.verdict_signatures_verified == 2  # the two format-5 entries
    assert result.checkpoints_verified == 1  # over all four


def test_a_format4_entry_after_format5_is_a_downgrade(dsns: dict[str, str]) -> None:
    signer = _signer()
    _write(dsns["writer"], signer, [40])
    _write(dsns["writer"], signer, [60], format5=False)
    assert "FORMAT_DOWNGRADE" in _kinds(_verify(dsns["owner"], trusted_key_ids=[signer.key_id]))


def test_migration_sql_is_embedded_in_the_runtime() -> None:
    from ski_model.ledger_migrations import _V5_LEDGER_MIGRATION_SQL

    shipped = (LEDGER_SQL / "migrations" / "0003_ledger_v5.sql").read_text(encoding="utf-8")
    assert shipped.endswith(_V5_LEDGER_MIGRATION_SQL)


# ---------------------------------------------------------------------------
# RFC 3161: checkpoints time-stamped by an in-boundary TSA
# ---------------------------------------------------------------------------


def test_checkpoint_timestamp_from_an_in_boundary_tsa_verifies(dsns: dict[str, str], tmp_path: Path) -> None:
    from audit_ledger.evidence import export_checkpoints
    from audit_ledger.ledger import Ledger
    from ski_model.ledger_client import LedgerClient
    from ski_model.timestamping import TimestampAuthority

    from .tsa_stub import running_tsa

    signer = _signer()
    _write(dsns["writer"], signer, [40, 60])
    with running_tsa() as (url, ca):

        async def checkpoint() -> Any:
            client = LedgerClient(dsns["writer"])
            await client.initialize()
            client.format5, client.signer, client.tenant_id = True, signer, "plant-7"
            try:
                return await client.checkpoint(TimestampAuthority(url))
            finally:
                await client.close()

        row = asyncio.run(checkpoint())
        assert row is not None and row["tsa_response"]
        result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id], tsa_ca=ca)
        assert result.is_valid, result.issues
        assert result.checkpoints_verified == 1 and result.timestamps_verified == 1

        # The exported file carries the token too, and verifies on its own.
        with Ledger(_sa(dsns["owner"])).Session() as session:
            (exported,) = export_checkpoints(session, tmp_path)
        assert _verify(
            dsns["owner"], trusted_key_ids=[signer.key_id], checkpoints=[exported], tsa_ca=ca
        ).is_valid

        # A token from this TSA over a different statement does not verify for this checkpoint.
        other = asyncio.run(TimestampAuthority(url).timestamp(b"another statement"))
        _owner_sql(dsns, f"UPDATE ledger_checkpoints SET tsa_response = '\\x{other.hex()}'::bytea")  # nosec B608 -- test fixture SQL with constant values
        tampered = _verify(dsns["owner"], trusted_key_ids=[signer.key_id], tsa_ca=ca)
        assert _kinds(tampered) == {"CHECKPOINT_TIMESTAMP_INVALID"}, tampered.issues


def test_timestamps_are_reported_unverified_without_the_tsa_ca(dsns: dict[str, str]) -> None:
    from ski_model.ledger_client import LedgerClient
    from ski_model.timestamping import TimestampAuthority

    from .tsa_stub import running_tsa

    signer = _signer()
    _write(dsns["writer"], signer, [40])
    with running_tsa() as (url, _ca):

        async def checkpoint() -> None:
            client = LedgerClient(dsns["writer"])
            await client.initialize()
            client.format5, client.signer = True, signer
            try:
                await client.checkpoint(TimestampAuthority(url))
            finally:
                await client.close()

        asyncio.run(checkpoint())
    result = _verify(dsns["owner"], trusted_key_ids=[signer.key_id])
    assert result.is_valid and result.timestamps_verified == 0
    assert any("--tsa-ca" in w for w in result.warnings)
