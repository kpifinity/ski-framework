"""Spec §5.5, §7.1, §7.2: the ledger, checked from outside.

Two views, neither using the implementation's code:

* the evidence API (``GET /api/ledger/{n}/evidence``, OpenAPI): every entry
  as a SCITT signed statement (COSE_Sign1) and a TRACE record, with a COSE
  Receipt once a checkpoint covers it. The suite verifies the signatures,
  the hash chain, the envelope hash and the Merkle inclusion proofs with
  ``checkers.py``. An implementation without the evidence API skips these;
* SQL (``--ledger-dsn``): storage-layer append-only enforcement (§7.2).
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import re
from typing import Any, Iterator, Optional

import cbor2
import pytest

from .answers import answer, so2
from .checkers import (
    Sign1,
    b64url_decode,
    canonicalize,
    ed25519_verify,
    parse_json,
    root_from_inclusion_proof,
    sha256_prefixed,
)
from .conftest import SUT
from .prepare import SO2_SUBJECT

pytestmark = pytest.mark.blackbox

_CONTENT_TYPE = "application/vnd.ski.ledger-entry+json"
_HEADER_CTY, _HEADER_KID, _HEADER_CWT, _HEADER_VDS, _HEADER_VDP = 3, 4, 15, 395, 396


def _hex(digest: str) -> str:
    return digest.split(":", 1)[-1]


class Entry:
    """One ledger entry as the evidence API presents it, verified on construction."""

    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = evidence
        record = evidence["trace_record"]
        jwk = record["cnf"]["jwk"]
        assert (jwk["kty"], jwk["crv"]) == ("OKP", "Ed25519")
        self.public_key = b64url_decode(jwk["x"])
        self.key_id = "sha256:" + hashlib.sha256(self.public_key).hexdigest()
        unsigned = {k: v for k, v in record.items() if k != "signature"}
        assert ed25519_verify(self.public_key, b64url_decode(record["signature"]), canonicalize(unsigned)), (
            "TRACE record signature does not verify against its cnf.jwk"
        )
        self.statement = Sign1(base64.b64decode(evidence["scitt"]["signed_statement"]))
        assert self.statement.verify(self.public_key), "SCITT signed statement does not verify"
        assert self.statement.protected.get(_HEADER_CTY) == _CONTENT_TYPE
        assert self.statement.payload is not None
        body = parse_json(self.statement.payload)
        assert canonicalize(body) == self.statement.payload, "statement payload is not §7.3 canonical"
        self.entry: dict[str, Any] = body["ledger_entry"]
        self.envelope: Optional[dict[str, Any]] = body["envelope"]

    @property
    def receipt(self) -> Optional[Sign1]:
        encoded = self.evidence["scitt"].get("receipt")
        return Sign1(base64.b64decode(encoded)) if encoded else None


def _entries(sut: SUT) -> Iterator[Entry]:
    seq = 1
    while True:
        response = sut.http.get(f"/api/ledger/{seq}/evidence")
        if response.status_code == 404 and seq > 1:
            return
        if response.status_code in (404, 405, 409, 501):
            pytest.skip(f"No ledger evidence API (GET /api/ledger/{seq}/evidence: {response.status_code}).")
        response.raise_for_status()
        yield Entry(response.json())
        seq += 1


@pytest.fixture(scope="module")
def ledger(sut: SUT) -> dict[str, Any]:
    """Evaluate a known record, then read and verify every entry through the evidence API."""
    token = sut.token()
    returned = sut.envelope(token, SO2_SUBJECT, {"so2_ppm": 85}, answer("CLEAR", [so2(85, True)]))
    entries = list(_entries(sut))
    return {"token": token, "returned": returned, "entries": entries}


def test_every_verdict_is_recorded_as_returned(ledger: dict[str, Any]) -> None:
    """§5.5: the entry holds the envelope the caller received, verdict line included."""
    mine = [e for e in ledger["entries"] if e.entry["telemetry_id"] == ledger["token"]]
    assert len(mine) == 1
    entry = mine[0]
    assert entry.envelope is not None
    assert canonicalize(entry.envelope) == canonicalize(ledger["returned"])
    assert entry.entry["verdict"] == ledger["returned"]["verdict"]
    assert entry.entry["kg_version_hash"] == ledger["returned"]["model_provenance"]["kg_version_hash"]
    assert entry.entry["envelope_hash"] == sha256_prefixed(canonicalize(entry.envelope)), (
        "§7.1: envelope hash"
    )


def test_entries_are_hash_chained(ledger: dict[str, Any]) -> None:
    """§7.1: each entry's previous_hash is the entry_hash before it; the first is the zero hash."""
    entries = ledger["entries"]
    assert _hex(entries[0].entry["previous_hash"]) == "0" * 64
    for before, after in itertools.pairwise(entries):
        assert after.entry["sequence_number"] == before.entry["sequence_number"] + 1
        assert after.entry["previous_hash"] == before.entry["entry_hash"]
    for e in entries:
        assert re.fullmatch(r"(sha256:)?[0-9a-f]{64}", e.entry["entry_hash"])


def test_statements_are_signed_by_the_deployment_key(ledger: dict[str, Any]) -> None:
    """§7.1 verdict signature / SCITT: one deployment key, named by kid and CWT issuer, signs every statement."""
    for e in ledger["entries"]:
        assert e.statement.protected[_HEADER_KID].decode("utf-8") == e.key_id
        claims = e.statement.protected[_HEADER_CWT]
        assert claims[1] == f"ski:key:{e.key_id}"
        assert claims[2].endswith(f":{int(e.entry['sequence_number'])}")


def test_receipts_prove_inclusion(ledger: dict[str, Any]) -> None:
    """§7.1 checkpoints: a receipt's inclusion proof leads to a root the deployment key signed."""
    with_receipt = [e for e in ledger["entries"] if e.receipt is not None]
    if not with_receipt:
        pytest.skip("No checkpoint covers any entry yet (checkpoints are SHOULD, §7.1).")
    for e in with_receipt:
        receipt = e.receipt
        assert receipt is not None
        assert receipt.protected.get(_HEADER_VDS) == 1  # RFC9162_SHA256
        (proof_bytes,) = receipt.unprotected[_HEADER_VDP][-1]
        tree_size, leaf_index, path = cbor2.loads(proof_bytes)
        assert leaf_index == e.entry["sequence_number"] - 1
        root = root_from_inclusion_proof(
            bytes.fromhex(_hex(e.entry["entry_hash"])), leaf_index, tree_size, path
        )
        assert receipt.verify(e.public_key, detached_payload=root), "receipt signature over the proven root"


def test_ledger_is_append_only_at_the_storage_layer(ledger_dsn: Optional[str], ledger_table: str) -> None:
    """§7.2: UPDATE, DELETE and TRUNCATE are refused by the storage layer itself."""
    if not ledger_dsn:
        pytest.skip("Ledger DSN not provided (--ledger-dsn).")
    psycopg = pytest.importorskip("psycopg")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", ledger_table):
        pytest.fail(f"--ledger-table {ledger_table!r} is not a plain identifier")
    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", ledger_dsn)
    statements = [
        f"UPDATE {ledger_table} SET verdict = verdict",
        f"DELETE FROM {ledger_table}",
        f"TRUNCATE {ledger_table}",
    ]
    with psycopg.connect(dsn) as conn:
        if conn.execute(f"SELECT count(*) FROM {ledger_table}").fetchone()[0] == 0:
            pytest.skip("Ledger is empty; run the evaluation tests first.")
        conn.rollback()
        for sql in statements:
            with pytest.raises(psycopg.Error):
                conn.execute(sql)
            conn.rollback()
