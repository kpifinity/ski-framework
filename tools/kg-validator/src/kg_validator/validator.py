"""
Core validation logic
"""

import json
import time
from typing import List, Dict, Optional
from datetime import datetime

from .models import (
    ComplianceRule,
    ValidationIssue,
    IssueType,
    ApprovedRule,
    ValidationMetadata,
    ValidationResult,
    ValidationStatus,
)
from .conflict_detector import ConflictDetector
from .utils import load_rules, validate_rule_fields


class Validator:
    """Validate extracted compliance rules"""

    def __init__(self):
        self.approved_rules: List[ApprovedRule] = []
        self.rejected_rules: List[str] = []
        self.flagged_rules: List[str] = []
        self.issues: List[ValidationIssue] = []
        self.current_session_start = None

    def validate(
        self,
        rules: List[ComplianceRule],
    ) -> ValidationResult:
        """
        Perform automated validation of rules.

        v2.1: the `auto_approve_explicit` flag was REMOVED. Per spec B2.3
        (Universal Coverage), every rule must be human-reviewed. Even an
        opt-in auto-approval defaults the operator toward non-conformance,
        so the option is gone.
        """
        start_time = time.time()
        self.current_session_start = start_time

        # Run all checks
        self._check_rule_quality(rules)
        conflicts = ConflictDetector.detect_conflicts(rules)
        duplicates = ConflictDetector.detect_duplicates(rules)

        # Process rules — every rule goes into the pending-review pool.
        # Human approval happens via interactive_review() or a downstream
        # workflow tool; nothing in this codepath auto-approves.
        for rule in rules:
            self._add_pending_rule(rule)

        # Create validation result
        metadata = ValidationMetadata(
            total_rules_reviewed=len(rules),
            total_approved=len(self.approved_rules),
            total_rejected=len(self.rejected_rules),
            total_flagged=len(self.flagged_rules),
            total_issues_found=len(self.issues),
            validation_duration_seconds=time.time() - start_time,
            validators=["automated"],
            validation_timestamp=datetime.utcnow().isoformat() + "Z",
        )

        return ValidationResult(
            approved_rules=self.approved_rules,
            issues=self.issues,
            conflicts=conflicts,
            duplicates=duplicates,
            metadata=metadata,
        )

    def _check_rule_quality(self, rules: List[ComplianceRule]) -> None:
        """Check quality of each rule"""

        for rule in rules:
            # Check required fields
            missing_fields = validate_rule_fields(rule)
            for field in missing_fields:
                self.issues.append(
                    ValidationIssue(
                        rule_id=rule.id,
                        issue_type=IssueType.MISSING_FIELD,
                        severity="HIGH",
                        message=f"Missing required field: {field}",
                    )
                )

            # Check for vague language
            vague_terms = self._check_vague_language(rule)
            if vague_terms:
                self.issues.append(
                    ValidationIssue(
                        rule_id=rule.id,
                        issue_type=IssueType.VAGUE_RULE,
                        severity="MEDIUM",
                        message=f"Rule contains vague terms: {', '.join(vague_terms)}",
                        suggested_action="Review and clarify language with domain expert",
                    )
                )

            # Check for ambiguous confidence
            if rule.confidence == "DISCRETIONARY":
                self.issues.append(
                    ValidationIssue(
                        rule_id=rule.id,
                        issue_type=IssueType.AMBIGUOUS,
                        severity="MEDIUM",
                        message="Rule marked as DISCRETIONARY - requires expert review",
                    )
                )

    def _check_vague_language(self, rule: ComplianceRule) -> List[str]:
        """Identify vague terms in a rule"""
        vague_terms = ["may", "should", "could", "might", "possibly", "apparently"]
        found_terms = []

        combined_text = f"{rule.subject} {rule.relation} {rule.object}".lower()
        for term in vague_terms:
            if term in combined_text:
                found_terms.append(term)

        return found_terms

    def _approve_rule(
        self, rule: ComplianceRule, validator_notes: Optional[str] = None
    ) -> None:
        """Approve a rule"""
        approved = ApprovedRule(
            id=rule.id,
            subject=rule.subject,
            relation=rule.relation,
            object=rule.object,
            source_document=rule.source_document,
            source_clause=rule.source_clause,
            confidence=rule.confidence,
            reasoning=rule.reasoning,
            validation_status=ValidationStatus.APPROVED,
            validation_timestamp=datetime.utcnow().isoformat() + "Z",
            validator_notes=validator_notes,
            effective_date=rule.effective_date,
            expiration_date=rule.expiration_date,
        )
        self.approved_rules.append(approved)

    def _reject_rule(self, rule_id: str) -> None:
        """Mark a rule as rejected"""
        self.rejected_rules.append(rule_id)

    def _flag_rule(self, rule_id: str) -> None:
        """Mark a rule as flagged for review"""
        self.flagged_rules.append(rule_id)

    def _add_pending_rule(self, rule: ComplianceRule) -> None:
        """Add a rule as pending review"""
        pass  # In interactive mode, will be reviewed separately

    def get_approved_rules(self) -> List[ApprovedRule]:
        """Get all approved rules"""
        return self.approved_rules

    def get_issues_by_severity(self, severity: str) -> List[ValidationIssue]:
        """Get issues filtered by severity"""
        return [i for i in self.issues if i.severity == severity]

    def get_issues_for_rule(self, rule_id: str) -> List[ValidationIssue]:
        """Get all issues for a specific rule"""
        return [i for i in self.issues if i.rule_id == rule_id]

    def interactive_review(self, rules: List[ComplianceRule]) -> ValidationResult:
        """
        Perform interactive review (in real scenario would be interactive CLI)
        For now, auto-approve all rules without critical issues

        Args:
            rules: Rules to review

        Returns:
            ValidationResult
        """
        start_time = time.time()

        # Run automated checks first. v2.1: no auto-approval — `validate`
        # itself just records issues and leaves the approval decision to
        # the human reviewer. This method represents the (CLI-mediated)
        # human review pass.
        result = self.validate(rules)

        # For DISCRETIONARY rules, flag them
        for rule in rules:
            if rule.confidence == "DISCRETIONARY":
                self._flag_rule(rule.id)

        # For rules with critical issues, reject them
        critical_issues = self.get_issues_by_severity("CRITICAL")
        for issue in critical_issues:
            self._reject_rule(issue.rule_id)

        # Create final result
        metadata = ValidationMetadata(
            total_rules_reviewed=len(rules),
            total_approved=len(self.approved_rules),
            total_rejected=len(self.rejected_rules),
            total_flagged=len(self.flagged_rules),
            total_issues_found=len(self.issues),
            validation_duration_seconds=time.time() - start_time,
            validators=["interactive_review"],
            validation_timestamp=datetime.utcnow().isoformat() + "Z",
        )

        return ValidationResult(
            approved_rules=self.approved_rules,
            issues=self.issues,
            conflicts=result.conflicts,
            duplicates=result.duplicates,
            metadata=metadata,
        )
