"""
Data models for Audit Ledger Tool
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class VerdictType(str, Enum):
    """Verdict categories"""
    CLEAR = "CLEAR"
    FLAG = "FLAG"
    NULL = "NULL"
    DISCRETIONARY = "DISCRETIONARY"


class ConfidenceLevel(str, Enum):
    """Confidence levels for verdicts"""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class LedgerEntry(BaseModel):
    """Individual ledger entry"""
    id: int
    sequence_number: int
    previous_hash: str
    entry_hash: str
    timestamp: datetime
    verdict: VerdictType
    telemetry_id: str
    telemetry_hash: str
    rule_id: str
    knowledge_graph_version: str
    milm_version: str
    confidence_level: ConfidenceLevel
    reasoning: Optional[str] = None
    escalation_status: Optional[str] = None
    escalation_notes: Optional[str] = None

    class Config:
        use_enum_values = True


class VerificationResult(BaseModel):
    """Result of ledger verification"""
    is_valid: bool
    total_entries: int
    sequence_range: tuple
    time_range: tuple
    chain_continuity: bool
    hash_verification_count: int
    hash_verification_total: int
    timestamp_ordering: bool
    data_consistency: bool
    issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    verification_date: datetime
    verdict_distribution: Dict[str, int] = Field(default_factory=dict)
    recommendation: str = ""


class ExportResult(BaseModel):
    """Result of export operation"""
    export_date: datetime
    entry_count: int
    file_path: str
    file_format: str
    date_range: Optional[tuple] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    size_bytes: int = 0
    checksum: Optional[str] = None


class BackupResult(BaseModel):
    """Result of backup operation"""
    backup_date: datetime
    source_db: str
    backup_file: str
    compressed: bool
    size_bytes: int
    verified: bool
    verification_status: Optional[str] = None
    checksum: Optional[str] = None
    encryption_used: bool = False


class ReportMetadata(BaseModel):
    """Metadata for compliance report"""
    report_date: datetime
    organization: str
    title: str
    start_date: datetime
    end_date: datetime
    generated_by: str = "Audit Ledger Tool"


class VerdictSummary(BaseModel):
    """Summary of verdicts"""
    total: int
    clear: int
    flag: int
    null: int
    discretionary: int
    clear_percent: float = 0.0
    flag_percent: float = 0.0
    null_percent: float = 0.0
    discretionary_percent: float = 0.0


class ViolationSummary(BaseModel):
    """Summary of violations (FLAG verdicts)"""
    total_violations: int
    violations_by_rule: Dict[str, int] = Field(default_factory=dict)
    violations_by_date: Dict[str, int] = Field(default_factory=dict)
    most_common_rules: List[tuple] = Field(default_factory=list)


class ReportResult(BaseModel):
    """Result of report generation"""
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


class IntegrityIssue(BaseModel):
    """Issue found during integrity verification"""
    issue_type: str  # HASH_MISMATCH, SEQUENCE_GAP, TIMESTAMP_ORDER, etc.
    sequence_number: Optional[int] = None
    description: str
    severity: str  # CRITICAL, WARNING, INFO
    suggested_action: Optional[str] = None
