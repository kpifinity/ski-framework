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
from typing import Any, Iterable, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .canonical import canonical_entry_payload
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


class Ledger:
    """Manage and verify the SKI Framework audit ledger."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine: Engine = create_engine(connection_string)
        self.Session = sessionmaker(bind=self.engine)

    # ------------------------------------------------------------------
    # verify_integrity — REAL hash recomputation, not chain-linkage only.
    # ------------------------------------------------------------------

    def verify_integrity(self, verbose: bool = False) -> VerificationResult:
        """Verify ledger integrity.

        For every entry, this method recomputes the entry hash from the
        canonical payload and compares against the stored entry_hash. This
        catches tampering with any field, not just the previous_hash.
        """
        session = self.Session()
        try:
            rows = session.execute(
                text(
                    """
                    SELECT id, sequence_number, previous_hash, entry_hash, timestamp,
                           verdict, telemetry_id, telemetry_hash, rule_id,
                           knowledge_graph_version, ski_model_version, reasoning, track
                    FROM ledger_entries
                    ORDER BY sequence_number ASC
                    """
                )
            ).all()

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
                timestamp_iso = (
                    timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
                )
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
                if recomputed == stored_hash:
                    entry_hash_verified += 1
                else:
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
            # `pg_restore --list` parses the dump's table of contents; it
            # fails on a corrupt archive.
            try:
                subprocess.run(
                    ["pg_restore", "--list", output_file] if not compress
                    else ["pg_restore", "--list", output_file],
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
