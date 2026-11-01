"""Ledger format 5 evidence: signing keys, verdict signatures and checkpoints (spec §7).

Everything here is checked from the ledger alone plus what the auditor pins:

* **Signing keys.** ``ledger_signing_keys`` maps a key id to its public key.
  A row whose key id is not the SHA-256 of its own key is rejected, so a
  substituted PEM cannot pass under a pinned id. The auditor pins key ids
  out of band (``--trusted-key-id``; the runtime attests its id at
  ``/api/sovereignty``); without a pin the keys are reported, not trusted.
* **Verdict signatures.** Every format-5 entry carries an Ed25519 signature
  over :func:`ski_schemas.ledger.verdict_signing_bytes`, binding its
  sequence number, entry hash, telemetry id and transcript id.
* **Checkpoints.** Each ``ledger_checkpoints`` row signs the RFC 6962 root
  of entries ``1..tree_size`` (:mod:`ski_schemas.merkle`). A row whose root
  no longer matches the entries means the ledger was rewritten after it was
  signed. Exported checkpoint files (``audit-ledger checkpoint export``,
  kept on WORM storage) catch a rewrite that also replaced the rows.
* **Time-stamps.** A checkpoint's RFC 3161 response is checked with
  ``openssl ts -verify`` against the TSA's CA when the auditor supplies it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from ski_schemas.merkle import checkpoint_statement, merkle_root
from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import IntegrityIssue

CHECKPOINT_FILE_FORMAT = "ski-ledger-checkpoint/1"


def key_id_of(key: Ed25519PublicKey) -> str:
    return "sha256:" + hashlib.sha256(key.public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()


def load_key(pem: str) -> Optional[Ed25519PublicKey]:
    try:
        key = load_pem_public_key(pem.encode("ascii"))
    except (ValueError, TypeError):
        return None
    return key if isinstance(key, Ed25519PublicKey) else None


def signature_valid(key: Ed25519PublicKey, message: bytes, signature_hex: Optional[str]) -> bool:
    if not signature_hex:
        return False
    try:
        key.verify(bytes.fromhex(signature_hex), message)
    except (InvalidSignature, ValueError):
        return False
    return True


def has_table(session: Session, table: str) -> bool:
    return session.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None


@dataclass
class KeyRing:
    """The ledger's signing keys, those that failed their own key id, and the auditor's pins."""

    keys: dict[str, Ed25519PublicKey] = field(default_factory=dict)
    bad_rows: list[str] = field(default_factory=list)
    trusted: Optional[frozenset[str]] = None

    @classmethod
    def load(cls, session: Session, trusted: Optional[Iterable[str]] = None) -> KeyRing:
        ring = cls(trusted=frozenset(trusted) if trusted else None)
        if not has_table(session, "ledger_signing_keys"):
            return ring
        for key_id, pem in session.execute(
            text("SELECT key_id, public_key_pem FROM ledger_signing_keys")
        ).all():
            key = load_key(str(pem))
            if key is None or key_id_of(key) != str(key_id).strip():
                ring.bad_rows.append(str(key_id).strip())
            else:
                ring.keys[key_id_of(key)] = key
        return ring

    def get(self, key_id: Optional[str]) -> Optional[Ed25519PublicKey]:
        return self.keys.get((key_id or "").strip())

    def is_trusted(self, key_id: Optional[str]) -> bool:
        return self.trusted is None or (key_id or "").strip() in self.trusted

    def issues(self) -> list[IntegrityIssue]:
        return [
            IntegrityIssue(
                issue_type="SIGNING_KEY_MISMATCH",
                sequence_number=0,
                description=f"ledger_signing_keys row {key_id} does not hold the key that id names.",
                severity="CRITICAL",
                suggested_action="Treat as tampering: the key table is append-only.",
            )
            for key_id in self.bad_rows
        ]


@dataclass
class CheckpointReport:
    verified: int = 0
    timestamped: int = 0
    timestamps_verified: int = 0
    issues: list[IntegrityIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _checkpoint_issue(kind: str, tree_size: int, description: str) -> IntegrityIssue:
    return IntegrityIssue(
        issue_type=kind,
        sequence_number=tree_size,
        description=description,
        severity="CRITICAL",
        suggested_action="Treat as a confirmed integrity incident: the ledger changed after it was checkpointed.",
    )


def _check_one(
    cp: dict[str, Any], entry_hashes: list[str], ring: KeyRing, source: str, report: CheckpointReport
) -> bool:
    size = int(cp["tree_size"])
    statement = checkpoint_statement(
        tenant_id=str(cp["tenant_id"]),
        tree_size=size,
        root_hash=str(cp["root_hash"]),
        last_entry_hash=str(cp["last_entry_hash"]),
        created_at=str(cp["created_at"]),
    )
    key_id = str(cp["signing_key_id"]).strip()
    key = load_key(cp["public_key_pem"]) if cp.get("public_key_pem") else ring.get(key_id)
    if key is None or key_id_of(key) != key_id or not signature_valid(key, statement, cp["signature"]):
        report.issues.append(
            _checkpoint_issue(
                "CHECKPOINT_SIGNATURE_INVALID",
                size,
                f"{source} checkpoint at tree_size {size} is not validly signed.",
            )
        )
        return False
    if not ring.is_trusted(key_id):
        report.issues.append(
            _checkpoint_issue(
                "UNTRUSTED_SIGNING_KEY", size, f"{source} checkpoint signed by unpinned key {key_id}."
            )
        )
        return False
    if size > len(entry_hashes):
        report.issues.append(
            _checkpoint_issue(
                "CHECKPOINT_BEYOND_LEDGER",
                size,
                f"{source} checkpoint covers {size} entries but the ledger holds {len(entry_hashes)}: "
                "entries were removed.",
            )
        )
        return False
    covered = entry_hashes[:size]
    if merkle_root(covered) != str(cp["root_hash"]) or covered[-1] != str(cp["last_entry_hash"]):
        report.issues.append(
            _checkpoint_issue(
                "CHECKPOINT_MISMATCH",
                size,
                f"{source} checkpoint at tree_size {size} signs root {str(cp['root_hash'])[:12]}…, but entries "
                f"1..{size} now hash to {merkle_root(covered)[:12]}…: the ledger was rewritten.",
            )
        )
        return False
    report.verified += 1
    return True


def verify_checkpoints(
    session: Session,
    entry_hashes: list[str],
    ring: KeyRing,
    *,
    exported: Iterable[Path] = (),
    tsa_ca: Optional[Path] = None,
) -> CheckpointReport:
    """Check every checkpoint in the ledger, and every exported checkpoint file, against the entries."""
    report = CheckpointReport()
    if has_table(session, "ledger_checkpoints"):
        rows = session.execute(
            text(
                "SELECT tenant_id, tree_size, root_hash, last_entry_hash, created_at, signing_key_id, "
                "signature, tsa_response FROM ledger_checkpoints ORDER BY tree_size"
            )
        ).mappings()
        for row in rows:
            cp = dict(row)
            if _check_one(cp, entry_hashes, ring, "ledger", report) and cp["tsa_response"] is not None:
                report.timestamped += 1
                if tsa_ca is not None:
                    _verify_timestamp(cp, bytes(cp["tsa_response"]), tsa_ca, report)
    for path in exported:
        cp = json.loads(Path(path).read_text(encoding="utf-8"))
        if cp.get("format") != CHECKPOINT_FILE_FORMAT:
            report.issues.append(
                _checkpoint_issue(
                    "CHECKPOINT_FILE_INVALID", 0, f"{path} is not a {CHECKPOINT_FILE_FORMAT} file."
                )
            )
            continue
        if _check_one(cp, entry_hashes, ring, f"exported ({Path(path).name})", report) and cp.get(
            "tsa_response"
        ):
            report.timestamped += 1
            if tsa_ca is not None:
                _verify_timestamp(cp, base64.b64decode(cp["tsa_response"]), tsa_ca, report)
    if report.timestamped and tsa_ca is None:
        report.warnings.append(
            f"{report.timestamped} checkpoint time-stamp(s) present but not verified: pass --tsa-ca."
        )
    return report


def _verify_timestamp(cp: dict[str, Any], response: bytes, tsa_ca: Path, report: CheckpointReport) -> None:
    """``openssl ts -verify`` the RFC 3161 response over the checkpoint statement."""
    size = int(cp["tree_size"])
    if shutil.which("openssl") is None:
        report.warnings.append("openssl not found: RFC 3161 time-stamps not verified.")
        return
    statement = checkpoint_statement(
        tenant_id=str(cp["tenant_id"]),
        tree_size=size,
        root_hash=str(cp["root_hash"]),
        last_entry_hash=str(cp["last_entry_hash"]),
        created_at=str(cp["created_at"]),
    )
    with tempfile.TemporaryDirectory() as tmp:
        data, resp = Path(tmp) / "statement", Path(tmp) / "response.der"
        data.write_bytes(statement)
        resp.write_bytes(response)
        proc = subprocess.run(
            ["openssl", "ts", "-verify", "-data", str(data), "-in", str(resp), "-CAfile", str(tsa_ca)],
            capture_output=True,
            text=True,
            check=False,
        )
    if proc.returncode == 0 and "Verification: OK" in proc.stdout:
        report.timestamps_verified += 1
    else:
        report.issues.append(
            _checkpoint_issue(
                "CHECKPOINT_TIMESTAMP_INVALID",
                size,
                f"RFC 3161 time-stamp on checkpoint {size} does not verify: {(proc.stdout + proc.stderr).strip()[-200:]}",
            )
        )


def export_checkpoints(session: Session, out_dir: Path) -> list[Path]:
    """Write each checkpoint as a self-contained JSON file (statement, signature, key, time-stamp).

    The files are meant for write-once storage (S3 Object Lock, a WORM
    volume): ``audit-ledger verify --checkpoint FILE`` later proves the
    ledger still matches what was exported, even if the ledger's own
    checkpoint rows were rewritten. Existing files are never overwritten.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if not has_table(session, "ledger_checkpoints"):
        return written
    rows = session.execute(
        text(
            "SELECT c.tenant_id, c.tree_size, c.root_hash, c.last_entry_hash, c.created_at, c.signing_key_id, "
            "c.signature, c.tsa_url, c.tsa_response, k.public_key_pem FROM ledger_checkpoints c "
            "LEFT JOIN ledger_signing_keys k ON k.key_id = c.signing_key_id ORDER BY c.tenant_id, c.tree_size"
        )
    ).mappings()
    for row in rows:
        path = out_dir / f"checkpoint-{row['tenant_id']}-{int(row['tree_size']):012d}.json"
        if path.exists():
            continue
        body = {
            "format": CHECKPOINT_FILE_FORMAT,
            "tenant_id": row["tenant_id"],
            "tree_size": int(row["tree_size"]),
            "root_hash": str(row["root_hash"]),
            "last_entry_hash": str(row["last_entry_hash"]),
            "created_at": row["created_at"],
            "signing_key_id": str(row["signing_key_id"]).strip(),
            "signature": row["signature"],
            "public_key_pem": row["public_key_pem"],
            "tsa_url": row["tsa_url"],
            "tsa_response": base64.b64encode(bytes(row["tsa_response"])).decode("ascii")
            if row["tsa_response"] is not None
            else None,
        }
        path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written
