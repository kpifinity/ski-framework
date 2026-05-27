"""Data models for the audit-ledger tool.

v2.1 changes:
  * `ConfidenceLevel` enum removed — confidence scores are prohibited (B3.1).
  * Verdict taxonomy expanded from 4 to 5 (NULL split into NULL_UNMAPPED
    and NULL_STALE).
  * `LedgerEntry.confidence_level` field removed.
  * `LedgerEntry.track` field added ("symbolic" | "llm" | None).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


class VerdictType(str, Enum):
    """The five canonical SKI verdicts (v2.1)."""

    CLEAR = "CLEAR"
    FLAG = "FLAG"
    NULL_UNMAPPED = "NULL_UNMAPPED"
    NULL_STALE = "NULL_STALE"
    DISCRETIONARY = "DISCRETIONARY"


class LedgerEntry(BaseModel):
    """Individual ledger entry."""

    id: int
    sequence_number: int
    previous_hash: str
    entry_hash: str
    timestamp: datetime
    verdict: VerdictType
    telemetry_id: str
    telemetry_hash: str
    rule_id: Optional[str] = None
    knowledge_graph_version: Optional[str] = None
    ski_model_version: str
    reasoning: Optional[str] = None
    track: Optional[str] = None
    escalation_status: Optional[str] = None
    escalation_notes: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


class IntegrityIssue(BaseModel):
    """Issue found during integrity verification."""

    issue_type: str  # HASH_MISMATCH, ENTRY_HASH_MISMATCH, SEQUENCE_GAP, TIMESTAMP_ORDER
    sequence_number: Optional[int] = None
    description: str
    severity: str  # CRITICAL, WARNING, INFO
    suggested_action: Optional[str] = None


class VerificationResult(BaseModel):
    """Result of ledger verification."""

    is_valid: bool
    total_entries: int
    sequence_range: Tuple[int, int]
    time_range: Tuple[Optional[datetime], Optional[datetime]]
    chain_continuity: bool
    chain_link_verified_count: int
    entry_hash_verified_count: int
    hash_verification_total: int
    timestamp_ordering: bool
    data_consistency: bool
    issues: List[IntegrityIssue] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    verification_date: datetime
    verdict_distribution: Dict[str, int] = Field(default_factory=dict)
    recommendation: str = ""


class ExportResult(BaseModel):
    export_date: datetime
    entry_count: int
    file_path: str
    file_format: str
    date_range: Optional[Tuple[Optional[str], Optional[str]]] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    size_bytes: int = 0
    checksum: Optional[str] = None


class BackupResult(BaseModel):
    backup_date: datetime
    source_db: str
    backup_file: str
    compressed: bool
    size_bytes: int
    verified: bool
    verification_status: Optional[str] = None
    checksum: Optional[str] = None
    encryption_used: bool = False


class VerdictSummary(BaseModel):
    total: int
    clear: int
    flag: int
    null_unmapped: int
    null_stale: int
    discretionary: int
    clear_percent: float = 0.0
    flag_percent: float = 0.0
    null_unmapped_percent: float = 0.0
    null_stale_percent: float = 0.0
    discretionary_percent: float = 0.0


class ViolationSummary(BaseModel):
    total_violations: int
    violations_by_rule: Dict[str, int] = Field(default_factory=dict)
    violations_by_date: Dict[str, int] = Field(default_factory=dict)
    most_common_rules: List[Tuple[str, int]] = Field(default_factory=list)


class ReportMetadata(BaseModel):
    report_date: datetime
    organization: str
    title: str
    start_date: datetime
    end_date: datetime
    generated_by: str = "Audit Ledger Tool"


class ReportResult(BaseModel):
    report_date: datetime
    report_file: str
    organization: str
    start_date: datetime
    end_date: datetime
    verdict_summary: VerdictSummary
    violation_summary: Optional[ViolationSummary] = None
    total_entries_analyzed: int
    report_format: str = "HTML"
    includes_timeline: bool = False
    includes_audit_trail: bool = False
