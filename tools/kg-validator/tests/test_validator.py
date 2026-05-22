"""
Tests for KG Validator
"""

import pytest

from kg_validator import Validator
from kg_validator.conflict_detector import ConflictDetector
from kg_validator.models import ComplianceRule


class TestConflictDetection:
    """Test conflict detection"""

    def test_contradictory_limits(self):
        """Should detect contradictory numeric limits"""
        rule1 = ComplianceRule(
            id="1",
            subject="Facility discharge",
            relation="must_not_exceed",
            object="100 ppm sulfur dioxide",
            source_document="Clean Air Act",
            source_clause="Section 112",
            confidence="EXPLICIT",
            reasoning="Test",
        )
        rule2 = ComplianceRule(
            id="2",
            subject="Facility discharge",
            relation="must_not_exceed",
            object="50 ppm sulfur dioxide",
            source_document="State Regulation",
            source_clause="Chapter 3",
            confidence="EXPLICIT",
            reasoning="Test",
        )

        conflicts = ConflictDetector.detect_conflicts([rule1, rule2])
        assert len(conflicts) > 0

    def test_no_conflict_different_subjects(self):
        """Rules with different subjects should not conflict"""
        rule1 = ComplianceRule(
            id="1",
            subject="Facility discharge",
            relation="must_not_exceed",
            object="100 ppm",
            source_document="Doc",
            source_clause="Clause",
            confidence="EXPLICIT",
            reasoning="Test",
        )
        rule2 = ComplianceRule(
            id="2",
            subject="Equipment discharge",
            relation="must_not_exceed",
            object="100 ppm",
            source_document="Doc",
            source_clause="Clause",
            confidence="EXPLICIT",
            reasoning="Test",
        )

        conflicts = ConflictDetector.detect_conflicts([rule1, rule2])
        assert len(conflicts) == 0


class TestDuplicateDetection:
    """Test duplicate detection"""

    def test_exact_duplicate(self):
        """Should detect exact duplicates"""
        rule1 = ComplianceRule(
            id="1",
            subject="Facility discharge",
            relation="must_not_exceed",
            object="100 ppm sulfur dioxide",
            source_document="Doc1",
            source_clause="Clause",
            confidence="EXPLICIT",
            reasoning="Test",
        )
        rule2 = ComplianceRule(
            id="2",
            subject="Facility discharge",
            relation="must_not_exceed",
            object="100 ppm sulfur dioxide",
            source_document="Doc2",
            source_clause="Clause",
            confidence="EXPLICIT",
            reasoning="Test",
        )

        duplicates = ConflictDetector.detect_duplicates([rule1, rule2], threshold=0.9)
        assert len(duplicates) == 1
        assert duplicates[0].similarity_score == 1.0

    def test_no_duplicate_dissimilar(self):
        """Should not detect dissimilar rules as duplicates"""
        rule1 = ComplianceRule(
            id="1",
            subject="Facility discharge",
            relation="must_not_exceed",
            object="100 ppm",
            source_document="Doc",
            source_clause="Clause",
            confidence="EXPLICIT",
            reasoning="Test",
        )
        rule2 = ComplianceRule(
            id="2",
            subject="Equipment maintenance",
            relation="must_occur",
            object="quarterly",
            source_document="Doc",
            source_clause="Clause",
            confidence="EXPLICIT",
            reasoning="Test",
        )

        duplicates = ConflictDetector.detect_duplicates([rule1, rule2], threshold=0.8)
        assert len(duplicates) == 0


class TestValidation:
    """Test validation workflow"""

    def test_explicit_rules_auto_approve(self):
        """EXPLICIT rules should auto-approve when flag is set"""
        rule = ComplianceRule(
            id="1",
            subject="Facility",
            relation="must",
            object="comply",
            source_document="Doc",
            source_clause="Clause",
            confidence="EXPLICIT",
            reasoning="Test",
        )

        # v2.1: auto-approval has been removed. EXPLICIT rules go into
        # the pending-review pool just like every other rule (B2.3).
        validator = Validator()
        result = validator.validate([rule])

        # No rule is approved automatically; downstream interactive
        # review must approve.
        assert len(result.approved_rules) == 0

    def test_discretionary_rules_are_flagged_for_review(self):
        """DISCRETIONARY rules must be flagged for human review (no auto-approval)."""
        rule = ComplianceRule(
            id="1",
            subject="Facility",
            relation="should",
            object="consider",
            source_document="Doc",
            source_clause="Clause",
            confidence="DISCRETIONARY",
            reasoning="Test",
        )

        validator = Validator()
        result = validator.validate([rule])

        # Should be flagged via issues, not auto-approved.
        assert len(result.approved_rules) == 0
        assert len(result.issues) > 0


if __name__ == "__main__":
    pytest.main([__file__])
