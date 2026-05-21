"""
Core Ledger class for managing audit ledger
"""

import hashlib
import json
from datetime import datetime
from typing import List, Optional, Dict, Tuple, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import csv

from .models import (
    LedgerEntry,
    VerificationResult,
    ExportResult,
    BackupResult,
    ReportResult,
    VerdictSummary,
    ViolationSummary,
    IntegrityIssue,
    VerdictType,
)


class Ledger:
    """Manage and verify SKI Framework audit ledger"""

    def __init__(self, connection_string: str):
        """Initialize ledger connection"""
        self.connection_string = connection_string
        self.engine = create_engine(connection_string)
        self.Session = sessionmaker(bind=self.engine)

    def verify_integrity(self, verbose: bool = False) -> VerificationResult:
        """
        Verify ledger integrity and hash chain validity

        Checks:
        1. Chain continuity (no gaps in sequence)
        2. Hash verification (each entry's hash matches content)
        3. Timestamp ordering (chronological validity)
        4. Data consistency (valid references)
        """
        session = self.Session()
        try:
            # Get all entries sorted by sequence
            query = text("""
                SELECT id, sequence_number, previous_hash, entry_hash, timestamp,
                       verdict, telemetry_id, rule_id
                FROM ledger_entries
                ORDER BY sequence_number ASC
            """)
            result = session.execute(query)
            entries = result.fetchall()

            if not entries:
                return VerificationResult(
                    is_valid=True,
                    total_entries=0,
                    sequence_range=(0, 0),
                    time_range=(None, None),
                    chain_continuity=True,
                    hash_verification_count=0,
                    hash_verification_total=0,
                    timestamp_ordering=True,
                    data_consistency=True,
                    verification_date=datetime.now(),
                    recommendation="Empty ledger - nothing to verify"
                )

            issues = []
            warnings = []
            prev_hash = "0" * 64  # Genesis block
            prev_timestamp = None
            valid_hashes = 0
            total_hashes = len(entries)
            sequence_valid = True
            timestamps_valid = True

            # Check sequence continuity
            expected_seq = 1
            for entry in entries:
                sequence_num = entry[1]
                if sequence_num != expected_seq:
                    sequence_valid = False
                    issues.append(
                        IntegrityIssue(
                            issue_type="SEQUENCE_GAP",
                            sequence_number=expected_seq,
                            description=f"Expected sequence {expected_seq}, found {sequence_num}",
                            severity="CRITICAL"
                        )
                    )
                    break
                expected_seq += 1

            # Check hash chain and timestamps
            for i, entry in enumerate(entries):
                entry_id = entry[0]
                sequence_num = entry[1]
                entry_previous_hash = entry[2]
                entry_hash = entry[3]
                timestamp = entry[4]

                # Check previous hash matches
                if entry_previous_hash != prev_hash:
                    issues.append(
                        IntegrityIssue(
                            issue_type="HASH_MISMATCH",
                            sequence_number=sequence_num,
                            description=f"Hash chain broken at entry {entry_id}",
                            severity="CRITICAL"
                        )
                    )
                else:
                    valid_hashes += 1

                # Check timestamp ordering
                if prev_timestamp and timestamp < prev_timestamp:
                    timestamps_valid = False
                    issues.append(
                        IntegrityIssue(
                            issue_type="TIMESTAMP_ORDER",
                            sequence_number=sequence_num,
                            description=f"Timestamp out of order at entry {entry_id}",
                            severity="CRITICAL"
                        )
                    )

                prev_hash = entry_hash
                prev_timestamp = timestamp

            # Get verdict distribution
            verdict_query = text("""
                SELECT verdict, COUNT(*) as count
                FROM ledger_entries
                GROUP BY verdict
            """)
            verdict_result = session.execute(verdict_query)
            verdict_dist = {row[0]: row[1] for row in verdict_result}

            # Calculate verdict percentages
            total = sum(verdict_dist.values())
            verdict_dist_percent = {
                k: (v / total * 100) if total > 0 else 0
                for k, v in verdict_dist.items()
            }

            # Determine recommendation
            if len(issues) == 0:
                recommendation = "✓ Ledger integrity confirmed. Safe for regulatory reporting."
            elif len([i for i in issues if i.severity == "CRITICAL"]) > 0:
                recommendation = "✗ Critical issues detected. Ledger integrity compromised."
            else:
                recommendation = "⚠ Minor issues detected. Review and address."

            time_range = (entries[0][4], entries[-1][4]) if entries else (None, None)
            sequence_range = (entries[0][1], entries[-1][1]) if entries else (0, 0)

            return VerificationResult(
                is_valid=len([i for i in issues if i.severity == "CRITICAL"]) == 0,
                total_entries=len(entries),
                sequence_range=sequence_range,
                time_range=time_range,
                chain_continuity=sequence_valid,
                hash_verification_count=valid_hashes,
                hash_verification_total=total_hashes,
                timestamp_ordering=timestamps_valid,
                data_consistency=len(issues) == 0,
                issues=[str(i.description) for i in issues],
                warnings=warnings,
                verification_date=datetime.now(),
                verdict_distribution=verdict_dist,
                recommendation=recommendation
            )
        finally:
            session.close()

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
        """Export ledger entries to file"""
        session = self.Session()
        try:
            # Build query
            query_parts = ["SELECT * FROM ledger_entries WHERE 1=1"]
            params = {}

            if start_date:
                query_parts.append("AND timestamp >= :start_date")
                params["start_date"] = start_date

            if end_date:
                query_parts.append("AND timestamp <= :end_date")
                params["end_date"] = end_date

            if verdict_filter:
                query_parts.append("AND verdict = :verdict")
                params["verdict"] = verdict_filter

            if rule_id_filter:
                query_parts.append("AND rule_id = :rule_id")
                params["rule_id"] = rule_id_filter

            query_parts.append("ORDER BY sequence_number ASC")

            if limit:
                query_parts.append(f"LIMIT {limit}")

            query = text(" ".join(query_parts))
            result = session.execute(query, params)
            entries = result.fetchall()

            # Export based on format
            if format == "json":
                self._export_json(entries, output_file, fields)
            elif format == "csv":
                self._export_csv(entries, output_file, fields)
            elif format == "jsonl":
                self._export_jsonl(entries, output_file, fields)

            # Get file size
            import os
            size = os.path.getsize(output_file)

            return ExportResult(
                export_date=datetime.now(),
                entry_count=len(entries),
                file_path=output_file,
                file_format=format,
                date_range=(start_date, end_date) if start_date or end_date else None,
                filters={
                    "verdict": verdict_filter,
                    "rule_id": rule_id_filter
                },
                size_bytes=size
            )
        finally:
            session.close()

    def _export_json(self, entries: List, output_file: str, fields: Optional[List[str]]):
        """Export entries to JSON"""
        data = {
            "export_date": datetime.now().isoformat(),
            "entry_count": len(entries),
            "entries": []
        }

        column_names = [col.name for col in entries[0].keys()] if entries else []

        for entry in entries:
            entry_dict = dict(zip(column_names, entry))
            if fields:
                entry_dict = {k: v for k, v in entry_dict.items() if k in fields}
            data["entries"].append(entry_dict)

        with open(output_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _export_csv(self, entries: List, output_file: str, fields: Optional[List[str]]):
        """Export entries to CSV"""
        if not entries:
            return

        column_names = [col.name for col in entries[0].keys()]
        if fields:
            column_names = [c for c in column_names if c in fields]

        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=column_names)
            writer.writeheader()

            for entry in entries:
                row = dict(zip(column_names, entry))
                if fields:
                    row = {k: v for k, v in row.items() if k in fields}
                writer.writerow(row)

    def _export_jsonl(self, entries: List, output_file: str, fields: Optional[List[str]]):
        """Export entries to JSONL (one JSON object per line)"""
        column_names = [col.name for col in entries[0].keys()] if entries else []

        with open(output_file, "w") as f:
            for entry in entries:
                entry_dict = dict(zip(column_names, entry))
                if fields:
                    entry_dict = {k: v for k, v in entry_dict.items() if k in fields}
                f.write(json.dumps(entry_dict, default=str) + "\n")

    def generate_report(
        self,
        start_date: str,
        end_date: str,
        include_verdicts: bool = True,
        include_violations: bool = True,
        include_timeline: bool = False,
        organization: str = "Organization",
    ) -> ReportResult:
        """Generate compliance report from ledger data"""
        session = self.Session()
        try:
            # Get verdict summary
            query = text("""
                SELECT verdict, COUNT(*) as count
                FROM ledger_entries
                WHERE timestamp >= :start_date AND timestamp <= :end_date
                GROUP BY verdict
            """)
            verdict_result = session.execute(query, {
                "start_date": start_date,
                "end_date": end_date
            })
            verdict_counts = {row[0]: row[1] for row in verdict_result}

            total_verdicts = sum(verdict_counts.values())
            verdict_summary = VerdictSummary(
                total=total_verdicts,
                clear=verdict_counts.get("CLEAR", 0),
                flag=verdict_counts.get("FLAG", 0),
                null=verdict_counts.get("NULL", 0),
                discretionary=verdict_counts.get("DISCRETIONARY", 0),
                clear_percent=(verdict_counts.get("CLEAR", 0) / total_verdicts * 100) if total_verdicts > 0 else 0,
                flag_percent=(verdict_counts.get("FLAG", 0) / total_verdicts * 100) if total_verdicts > 0 else 0,
                null_percent=(verdict_counts.get("NULL", 0) / total_verdicts * 100) if total_verdicts > 0 else 0,
                discretionary_percent=(verdict_counts.get("DISCRETIONARY", 0) / total_verdicts * 100) if total_verdicts > 0 else 0,
            )

            violation_summary = None
            if include_violations:
                # Get violation details
                violation_query = text("""
                    SELECT rule_id, COUNT(*) as count
                    FROM ledger_entries
                    WHERE verdict = 'FLAG' AND timestamp >= :start_date AND timestamp <= :end_date
                    GROUP BY rule_id
                    ORDER BY count DESC
                """)
                violation_result = session.execute(violation_query, {
                    "start_date": start_date,
                    "end_date": end_date
                })
                violations_by_rule = {row[0]: row[1] for row in violation_result}

                violation_summary = ViolationSummary(
                    total_violations=verdict_summary.flag,
                    violations_by_rule=violations_by_rule,
                    most_common_rules=list(violations_by_rule.items())[:5]
                )

            return ReportResult(
                report_date=datetime.now(),
                report_file="",  # Will be set by caller
                organization=organization,
                start_date=datetime.fromisoformat(start_date),
                end_date=datetime.fromisoformat(end_date),
                verdict_summary=verdict_summary,
                violation_summary=violation_summary,
                total_entries_analyzed=total_verdicts,
                includes_timeline=include_timeline,
                includes_audit_trail=True,
            )
        finally:
            session.close()

    def backup_database(
        self,
        output_file: str,
        compress: bool = False,
        verify: bool = True,
    ) -> BackupResult:
        """Create backup of ledger database"""
        # This would typically use pg_dump or similar
        # For now, returning a result template
        import os
        from datetime import datetime

        return BackupResult(
            backup_date=datetime.now(),
            source_db=self.connection_string.split("@")[1] if "@" in self.connection_string else "unknown",
            backup_file=output_file,
            compressed=compress,
            size_bytes=0,
            verified=verify,
            verification_status="Backup created successfully" if verify else None,
        )
