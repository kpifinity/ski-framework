"""Audit Ledger — read, verify, export, report, back up.

v2.1 changes:
  * `verify_integrity()` now recomputes the entry hash from the canonical
    payload — it is no longer a chain-linkage-only check.
  * `backup_database()` actually invokes `pg_dump`; no more stubs.
  * `ConfidenceLevel` removed from data model (B3.1).
  * Five-verdict taxonomy.
  * Canonical serialization documented in
    `audit_ledger.canonical.canonical_entry_payload` so third parties can
    re-verify without our code.

Ledger v4: new entries hash `ski_schemas.ledger.entry_payload_v4`, which
also commits to the stored envelope and transcript. `verify_integrity`
tells v3 and v4 entries apart by which payload reproduces the stored hash,
re-derives the evidence digests from the stored JSON, and flags a v3-format
entry that follows a v4 one.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, Optional

from ski_schemas.canonical import CanonicalizationError
from ski_schemas.ledger import entry_payload_v4, entry_payload_v5, evidence_hash, verdict_signing_bytes
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .canonical import canonical_entry_payload
from .evidence import KeyRing, signature_valid, verify_checkpoints
from .models import (
    BackupResult,
    ExportResult,
    IntegrityIssue,
    ReportResult,
    VerdictSummary,
    VerificationResult,
    ViolationSummary,
)

GENESIS_HASH = "0" * 64


_ENTRIES_COLUMNS = """
    SELECT id, sequence_number, previous_hash, entry_hash, timestamp,
           verdict, telemetry_id, telemetry_hash, rule_id,
           knowledge_graph_version, ski_model_version, reasoning, track,
           envelope_json::text, envelope_hash, transcript_json::text,
           transcript_signature, signing_key_id, verifier_status,
"""
_ENTRIES_QUERY_V5 = (
    _ENTRIES_COLUMNS
    + """
           tenant_id, kg_version_hash, model_weight_hash, schema_version,
           verdict_signature, verdict_signing_key_id, transcript_json->>'transcript_id'
    FROM ledger_entries ORDER BY sequence_number ASC
"""
)
# A ledger not yet migrated to format 5 (0003_ledger_v5.sql) has no such columns.
_ENTRIES_QUERY_PRE_V5 = (
    _ENTRIES_COLUMNS
    + """
           NULL, NULL, NULL, NULL, NULL, NULL, transcript_json->>'transcript_id'
    FROM ledger_entries ORDER BY sequence_number ASC
"""
)


def _strip(value: Optional[str]) -> Optional[str]:
    """CHAR(n) columns come back as stored; normalise without turning None into a string."""
    return value.strip() if isinstance(value, str) else value


class Ledger:
    """Manage and verify the SKI Framework audit ledger."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine: Engine = create_engine(connection_string)
        self.Session = sessionmaker(bind=self.engine)

    # ------------------------------------------------------------------
    # verify_integrity — REAL hash recomputation, not chain-linkage only.
    # ------------------------------------------------------------------

    def verify_integrity(
        self,
        verbose: bool = False,
        *,
        trusted_key_ids: Optional[Iterable[str]] = None,
        checkpoints: Iterable[Path] = (),
        tsa_ca: Optional[Path] = None,
    ) -> VerificationResult:
        """Verify ledger integrity.

        For every entry, this method recomputes the entry hash from the
        canonical payload and compares against the stored entry_hash. This
        catches tampering with any field, not just the previous_hash. For a
        ledger-v4 entry that includes the stored envelope and transcript:
        their digests are re-derived from the stored JSON and are part of
        the recomputed payload. A format-5 entry also chains the spec §7.1
        columns, and its verdict signature is verified against the ledger's
        signing keys (``trusted_key_ids`` pins which keys count). Every
        checkpoint in the ledger, and every exported checkpoint file in
        ``checkpoints``, is checked against the entries (:mod:`.evidence`).
        """
        session = self.Session()
        try:
            columns = {
                c
                for (c,) in session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns WHERE table_name = 'ledger_entries'"
                    )
                ).all()
            }
            rows = session.execute(
                text(_ENTRIES_QUERY_V5 if "verdict_signature" in columns else _ENTRIES_QUERY_PRE_V5)
            ).all()
            ring = KeyRing.load(session, trusted_key_ids)

            if not rows:
                return VerificationResult(
                    is_valid=True,
                    total_entries=0,
                    sequence_range=(0, 0),
                    time_range=(None, None),
                    chain_continuity=True,
                    chain_link_verified_count=0,
                    entry_hash_verified_count=0,
                    hash_verification_total=0,
                    timestamp_ordering=True,
                    data_consistency=True,
                    verification_date=datetime.now(),
                    recommendation="Ledger is empty — nothing to verify.",
                )

            issues: List[IntegrityIssue] = []
            warnings: List[str] = []
            prev_hash = GENESIS_HASH
            prev_timestamp = None
            expected_seq = 1
            chain_link_verified = 0
            entry_hash_verified = 0
            timestamps_valid = True
            sequence_valid = True
            max_format = 3
            unchained_evidence = 0
            verdict_signatures_verified = 0
            v5_entries = 0

            for row in rows:
                (
                    entry_id,
                    seq,
                    stored_prev,
                    stored_hash,
                    timestamp,
                    verdict,
                    tid,
                    thash,
                    rule_id,
                    kg_version,
                    ski_model_version,
                    reasoning,
                    track,
                    envelope_text,
                    stored_envelope_hash,
                    transcript_text,
                    transcript_signature,
                    signing_key_id,
                    verifier_status,
                    tenant_id,
                    kg_version_hash,
                    model_weight_hash,
                    schema_version,
                    verdict_signature,
                    verdict_signing_key_id,
                    transcript_id,
                ) = row

                # 1. Sequence continuity
                if seq != expected_seq:
                    sequence_valid = False
                    issues.append(
                        IntegrityIssue(
                            issue_type="SEQUENCE_GAP",
                            sequence_number=expected_seq,
                            description=f"Expected sequence {expected_seq}, found {seq}",
                            severity="CRITICAL",
                            suggested_action="Investigate ingestion path; this should be impossible with append-only triggers active.",
                        )
                    )
                expected_seq = seq + 1

                # 2. Chain linkage (previous_hash matches prior entry_hash)
                if stored_prev == prev_hash:
                    chain_link_verified += 1
                else:
                    issues.append(
                        IntegrityIssue(
                            issue_type="HASH_MISMATCH",
                            sequence_number=seq,
                            description=(
                                f"previous_hash mismatch at entry {entry_id} "
                                f"(stored={stored_prev[:12]}…, expected={prev_hash[:12]}…)"
                            ),
                            severity="CRITICAL",
                        )
                    )

                # 3. Entry hash recomputation — the real integrity check.
                timestamp_iso = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)

                # 3a. Ledger v4/v5: the payload also commits to the stored evidence
                # (and, in v5, to the spec §7.1 columns).
                entry_format = 3
                recomputed_envelope_hash: Optional[str] = None
                try:
                    recomputed_envelope_hash = evidence_hash(envelope_text)
                    line: dict[str, Any] = {
                        "sequence_number": int(seq),
                        "previous_hash": str(stored_prev),
                        "timestamp_iso": timestamp_iso,
                        "verdict": str(verdict),
                        "telemetry_id": str(tid),
                        "telemetry_hash": str(thash),
                        "rule_id": rule_id,
                        "kg_version": kg_version,
                        "ski_model_version": str(ski_model_version),
                        "reasoning": reasoning,
                        "track": track,
                        "envelope_hash": recomputed_envelope_hash,
                        "transcript_hash": evidence_hash(transcript_text),
                        "transcript_signature": transcript_signature,
                        "signing_key_id": signing_key_id,
                        "verifier_status": verifier_status,
                    }
                    if tenant_id is not None and schema_version is not None:
                        v5_payload = entry_payload_v5(
                            **line,
                            tenant_id=str(tenant_id),
                            kg_version_hash=_strip(kg_version_hash),
                            model_weight_hash=_strip(model_weight_hash),
                            schema_version=str(schema_version),
                        )
                        if hashlib.sha256(v5_payload).hexdigest() == stored_hash:
                            entry_format = 5
                    if (
                        entry_format == 3
                        and hashlib.sha256(entry_payload_v4(**line)).hexdigest() == stored_hash
                    ):
                        entry_format = 4
                except CanonicalizationError:
                    pass  # stored evidence has no canonical form: not a valid v4/v5 entry

                if entry_format == 3:
                    payload = canonical_entry_payload(
                        sequence_number=int(seq),
                        previous_hash=str(stored_prev),
                        timestamp_iso=timestamp_iso,
                        verdict=str(verdict),
                        telemetry_id=str(tid),
                        telemetry_hash=str(thash),
                        rule_id=rule_id,
                        kg_version=kg_version,
                        ski_model_version=str(ski_model_version),
                        reasoning=reasoning,
                        track=track,
                    )
                    recomputed = hashlib.sha256(payload).hexdigest()
                    if recomputed != stored_hash:
                        issues.append(
                            IntegrityIssue(
                                issue_type="ENTRY_HASH_MISMATCH",
                                sequence_number=seq,
                                description=(
                                    f"Recomputed entry hash does not match stored hash at "
                                    f"sequence {seq} (stored={stored_hash[:12]}…, "
                                    f"recomputed={recomputed[:12]}…). Entry content has been tampered with."
                                ),
                                severity="CRITICAL",
                                suggested_action="Treat as a confirmed integrity incident; do not use this ledger for regulatory reporting.",
                            )
                        )
                        entry_format = 0  # unverified: no format applies
                if entry_format and entry_format < max_format:
                    # Every writer since a format commits to at least what it
                    # chained; an older-format entry after a newer one did not.
                    issues.append(
                        IntegrityIssue(
                            issue_type="FORMAT_DOWNGRADE",
                            sequence_number=seq,
                            description=(
                                f"Entry {seq} uses ledger format {entry_format} after a format-{max_format} "
                                "entry, so it chains less of its evidence than the writer before it did."
                            ),
                            severity="CRITICAL",
                            suggested_action="Find the writer that produced it; only an older runtime writes this format.",
                        )
                    )
                elif entry_format:
                    entry_hash_verified += 1
                    max_format = max(max_format, entry_format)
                    if entry_format == 3 and envelope_text is not None:
                        unchained_evidence += 1
                if entry_format >= 4 and stored_envelope_hash != recomputed_envelope_hash:
                    # The payload carries the digest of the stored JSON, not
                    # this column, so a rewritten column alone shows up here.
                    issues.append(
                        IntegrityIssue(
                            issue_type="EVIDENCE_HASH_MISMATCH",
                            sequence_number=seq,
                            description=(
                                f"Stored envelope_hash at sequence {seq} does not match the "
                                "digest of the stored envelope_json."
                            ),
                            severity="CRITICAL",
                            suggested_action="Treat as a confirmed integrity incident.",
                        )
                    )

                # 3b. Format 5: the runtime signed this row at this position.
                if entry_format == 5:
                    v5_entries += 1
                    key = ring.get(verdict_signing_key_id)
                    message = verdict_signing_bytes(
                        sequence_number=int(seq),
                        entry_hash=str(stored_hash),
                        telemetry_id=str(tid),
                        transcript_id=transcript_id,
                    )
                    if key is None or not signature_valid(key, message, verdict_signature):
                        issues.append(
                            IntegrityIssue(
                                issue_type="VERDICT_SIGNATURE_INVALID",
                                sequence_number=seq,
                                description=(
                                    f"Entry {seq}'s verdict signature does not verify for this row "
                                    f"(key {_strip(verdict_signing_key_id) or 'missing'}): it was altered, "
                                    "moved from another row, or the key is not in ledger_signing_keys."
                                ),
                                severity="CRITICAL",
                                suggested_action="Treat as a confirmed integrity incident.",
                            )
                        )
                    elif not ring.is_trusted(verdict_signing_key_id):
                        issues.append(
                            IntegrityIssue(
                                issue_type="UNTRUSTED_SIGNING_KEY",
                                sequence_number=seq,
                                description=f"Entry {seq} is signed by {_strip(verdict_signing_key_id)}, "
                                "which is not a pinned key (--trusted-key-id).",
                                severity="CRITICAL",
                                suggested_action="A ledger re-signed with another key: confirm the runtime's key id.",
                            )
                        )
                    else:
                        verdict_signatures_verified += 1

                # 4. Timestamp ordering
                if prev_timestamp is not None and timestamp < prev_timestamp:
                    timestamps_valid = False
                    issues.append(
                        IntegrityIssue(
                            issue_type="TIMESTAMP_ORDER",
                            sequence_number=seq,
                            description=f"Timestamp non-monotonic at entry {entry_id}",
                            severity="CRITICAL",
                        )
                    )

                prev_hash = stored_hash
                prev_timestamp = timestamp

            issues.extend(ring.issues())
            checkpoint_report = verify_checkpoints(
                session, [str(r[3]) for r in rows], ring, exported=checkpoints, tsa_ca=tsa_ca
            )
            issues.extend(checkpoint_report.issues)
            warnings.extend(checkpoint_report.warnings)
            if v5_entries and ring.trusted is None:
                warnings.append(
                    "Verdict signatures verify against the ledger's own key table, but no key is pinned: "
                    f"pass --trusted-key-id (keys seen: {', '.join(sorted(ring.keys)) or 'none'})."
                )
            if v5_entries and checkpoint_report.verified == 0:
                warnings.append(
                    "No checkpoint covers this ledger yet: a forward rewrite would not be detected."
                )

            if unchained_evidence:
                warnings.append(
                    f"{unchained_evidence} entr{'y' if unchained_evidence == 1 else 'ies'} predate ledger v4: "
                    "their stored envelope and transcript are not covered by the hash chain."
                )

            # Verdict distribution
            verdict_rows = session.execute(
                text("SELECT verdict, COUNT(*) FROM ledger_entries GROUP BY verdict")
            ).all()
            verdict_dist = {r[0]: int(r[1]) for r in verdict_rows}

            critical_count = sum(1 for i in issues if i.severity == "CRITICAL")
            if critical_count == 0:
                recommendation = (
                    "All integrity checks passed: chain linkage, entry hash recomputation, "
                    "sequence continuity, and timestamp ordering. Safe for regulatory reporting."
                )
            else:
                recommendation = (
                    f"{critical_count} CRITICAL integrity issue(s) detected. "
                    "DO NOT use this ledger for regulatory reporting until investigated."
                )

            return VerificationResult(
                is_valid=critical_count == 0,
                total_entries=len(rows),
                sequence_range=(int(rows[0][1]), int(rows[-1][1])),
                time_range=(rows[0][4], rows[-1][4]),
                chain_continuity=sequence_valid,
                chain_link_verified_count=chain_link_verified,
                entry_hash_verified_count=entry_hash_verified,
                hash_verification_total=len(rows),
                timestamp_ordering=timestamps_valid,
                data_consistency=len(issues) == 0,
                issues=issues,
                warnings=warnings,
                verification_date=datetime.now(),
                verdict_distribution=verdict_dist,
                recommendation=recommendation,
                verdict_signatures_verified=verdict_signatures_verified,
                checkpoints_verified=checkpoint_report.verified,
                timestamps_verified=checkpoint_report.timestamps_verified,
            )
        finally:
            session.close()

    # ------------------------------------------------------------------
    # backup_database — REAL pg_dump invocation, no more stub.
    # ------------------------------------------------------------------

    def backup_database(
        self,
        output_file: str,
        compress: bool = False,
        verify: bool = True,
    ) -> BackupResult:
        """Create a real backup using pg_dump."""
        if not self.connection_string.startswith(("postgresql://", "postgresql+")):
            raise RuntimeError(
                "backup_database currently only supports PostgreSQL "
                f"(connection_string starts with {self.connection_string[:20]!r})"
            )
        if shutil.which("pg_dump") is None:
            raise RuntimeError(
                "`pg_dump` is not on PATH. Install postgresql-client (or use the "
                "ski-postgres image which bundles it) before running backups."
            )

        # Translate to libpq DSN for pg_dump.
        dsn = self.connection_string.replace("postgresql+psycopg://", "postgresql://", 1)
        cmd = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", output_file, dsn]
        subprocess.run(cmd, check=True)

        if compress:
            with open(output_file, "rb") as src, gzip.open(output_file + ".gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.remove(output_file)
            output_file = output_file + ".gz"

        size = os.path.getsize(output_file)
        checksum = _sha256_file(output_file)

        verification_status: Optional[str] = None
        if verify:
            if compress:
                # `pg_restore --list` cannot read a .gz file directly.
                # Until a gunzip-to-pipe step is added here, compressed
                # backups are checksummed (above) but not archive-parsed.
                # The previous code claimed to verify both branches but
                # ran the same uncompressed command in each, silently a
                # no-op on compressed dumps.
                verification_status = "skipped (compressed dump; checksum verified, archive parse not run)"
            else:
                # `pg_restore --list` parses the dump's table of contents;
                # it fails on a corrupt archive.
                try:
                    subprocess.run(
                        ["pg_restore", "--list", output_file],
                        check=True,
                        stdout=subprocess.DEVNULL,
                    )
                    verification_status = "pg_restore --list succeeded"
                except subprocess.CalledProcessError as exc:
                    verification_status = f"verification FAILED: {exc}"

        return BackupResult(
            backup_date=datetime.now(),
            source_db=_redact(self.connection_string),
            backup_file=output_file,
            compressed=compress,
            size_bytes=size,
            verified=verify,
            verification_status=verification_status,
            checksum=checksum,
            encryption_used=False,
        )

    # ------------------------------------------------------------------
    # export_entries
    # ------------------------------------------------------------------

    def export_entries(
        self,
        output_file: str,
        format: str = "json",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        verdict_filter: Optional[str] = None,
        rule_id_filter: Optional[str] = None,
        fields: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> ExportResult:
        session = self.Session()
        try:
            parts = ["SELECT * FROM ledger_entries WHERE 1=1"]
            params: dict[str, Any] = {}
            if start_date:
                parts.append("AND timestamp >= :start_date")
                params["start_date"] = start_date
            if end_date:
                parts.append("AND timestamp <= :end_date")
                params["end_date"] = end_date
            if verdict_filter:
                parts.append("AND verdict = :verdict")
                params["verdict"] = verdict_filter
            if rule_id_filter:
                parts.append("AND rule_id = :rule_id")
                params["rule_id"] = rule_id_filter
            parts.append("ORDER BY sequence_number ASC")
            if limit:
                parts.append(f"LIMIT {int(limit)}")
            result = session.execute(text(" ".join(parts)), params)
            rows = result.mappings().all()

            if format == "json":
                _write_json(rows, output_file, fields)
            elif format == "jsonl":
                _write_jsonl(rows, output_file, fields)
            elif format == "csv":
                _write_csv(rows, output_file, fields)
            else:
                raise ValueError(f"Unknown export format: {format}")

            return ExportResult(
                export_date=datetime.now(),
                entry_count=len(rows),
                file_path=output_file,
                file_format=format,
                date_range=(start_date, end_date) if (start_date or end_date) else None,
                filters={"verdict": verdict_filter, "rule_id": rule_id_filter},
                size_bytes=os.path.getsize(output_file),
                checksum=_sha256_file(output_file),
            )
        finally:
            session.close()

    # ------------------------------------------------------------------
    # generate_report — uses 5-verdict summary.
    # ------------------------------------------------------------------

    def generate_report(
        self,
        start_date: str,
        end_date: str,
        include_verdicts: bool = True,
        include_violations: bool = True,
        include_timeline: bool = False,
        organization: str = "Organization",
    ) -> ReportResult:
        session = self.Session()
        try:
            verdict_counts = {
                r[0]: int(r[1])
                for r in session.execute(
                    text(
                        """
                        SELECT verdict, COUNT(*)
                        FROM ledger_entries
                        WHERE timestamp >= :start AND timestamp <= :end
                        GROUP BY verdict
                        """
                    ),
                    {"start": start_date, "end": end_date},
                ).all()
            }
            total = sum(verdict_counts.values())

            def pct(key: str) -> float:
                return ((verdict_counts.get(key, 0) / total) * 100) if total else 0.0

            verdict_summary = VerdictSummary(
                total=total,
                clear=verdict_counts.get("CLEAR", 0),
                flag=verdict_counts.get("FLAG", 0),
                null_unmapped=verdict_counts.get("NULL_UNMAPPED", 0),
                null_stale=verdict_counts.get("NULL_STALE", 0),
                discretionary=verdict_counts.get("DISCRETIONARY", 0),
                clear_percent=pct("CLEAR"),
                flag_percent=pct("FLAG"),
                null_unmapped_percent=pct("NULL_UNMAPPED"),
                null_stale_percent=pct("NULL_STALE"),
                discretionary_percent=pct("DISCRETIONARY"),
            )

            violation_summary: Optional[ViolationSummary] = None
            if include_violations:
                vio_rows = session.execute(
                    text(
                        """
                        SELECT rule_id, COUNT(*) AS c
                        FROM ledger_entries
                        WHERE verdict = 'FLAG' AND timestamp >= :start AND timestamp <= :end
                        GROUP BY rule_id
                        ORDER BY c DESC
                        """
                    ),
                    {"start": start_date, "end": end_date},
                ).all()
                violations_by_rule = {r[0]: int(r[1]) for r in vio_rows}
                violation_summary = ViolationSummary(
                    total_violations=verdict_summary.flag,
                    violations_by_rule=violations_by_rule,
                    most_common_rules=list(violations_by_rule.items())[:5],
                )

            return ReportResult(
                report_date=datetime.now(),
                report_file="",
                organization=organization,
                start_date=datetime.fromisoformat(start_date),
                end_date=datetime.fromisoformat(end_date),
                verdict_summary=verdict_summary,
                violation_summary=violation_summary,
                total_entries_analyzed=total,
                includes_timeline=include_timeline,
                includes_audit_trail=True,
            )
        finally:
            session.close()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _write_json(rows: Iterable[dict[str, Any]], path: str, fields: Optional[List[str]]) -> None:
    out = {
        "export_date": datetime.now().isoformat(),
        "entries": [_project(row, fields) for row in rows],
    }
    out["entry_count"] = len(out["entries"])
    with open(path, "w") as f:
        json.dump(out, f, indent=2, default=str)


def _write_jsonl(rows: Iterable[dict[str, Any]], path: str, fields: Optional[List[str]]) -> None:
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(_project(row, fields), default=str) + "\n")


def _write_csv(rows: List[dict[str, Any]], path: str, fields: Optional[List[str]]) -> None:
    if not rows:
        open(path, "w").close()
        return
    columns = list(fields) if fields else list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) for c in columns})


def _project(row: dict[str, Any], fields: Optional[List[str]]) -> dict[str, Any]:
    row = dict(row)
    if fields:
        return {k: v for k, v in row.items() if k in fields}
    return row


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _redact(dsn: str) -> str:
    # Avoid logging passwords from the DSN.
    if "@" not in dsn:
        return dsn
    head, tail = dsn.split("@", 1)
    if "://" in head and ":" in head.split("://", 1)[1]:
        scheme, rest = head.split("://", 1)
        user = rest.split(":", 1)[0]
        return f"{scheme}://{user}:***@{tail}"
    return dsn
