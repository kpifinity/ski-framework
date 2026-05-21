"""
Tests for KG Extractor
"""

import json
import pytest
from kg_extractor import Extractor
from kg_extractor.models import ComplianceRule, ConfidenceLevel
from kg_extractor.utils import chunk_text, validate_rule


class TestChunking:
    """Test text chunking"""

    def test_small_text_no_chunking(self):
        """Small text should not be chunked"""
        text = "This is a small piece of text."
        chunks = chunk_text(text, max_chunk_size=1000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_large_text_chunked(self):
        """Large text should be chunked"""
        text = "word " * 1000  # Create large text
        chunks = chunk_text(text, max_chunk_size=100, overlap=10)
        assert len(chunks) > 1

    def test_chunk_overlap(self):
        """Chunks should overlap"""
        text = "word " * 100
        chunks = chunk_text(text, max_chunk_size=100, overlap=20)
        # Check that second chunk overlaps with first
        if len(chunks) > 1:
            assert text.find(chunks[1]) < text.find(chunks[0]) + len(chunks[0])


class TestRuleValidation:
    """Test rule validation"""

    def test_valid_rule(self):
        """Valid rule should pass validation"""
        rule = ComplianceRule(
            id="test_1",
            subject="Facility discharge",
            relation="must_be_within",
            object="100 ppm",
            source_document="Clean Air Act",
            source_clause="Section 112",
            confidence=ConfidenceLevel.EXPLICIT,
            reasoning="Rule clearly stated",
        )
        assert validate_rule(rule) is True

    def test_missing_subject(self):
        """Rule without subject should fail validation"""
        rule = ComplianceRule(
            id="test_2",
            subject="",
            relation="must_be_within",
            object="100 ppm",
            source_document="Clean Air Act",
            source_clause="Section 112",
            confidence=ConfidenceLevel.EXPLICIT,
            reasoning="Rule clearly stated",
        )
        assert validate_rule(rule) is False

    def test_missing_relation(self):
        """Rule without relation should fail validation"""
        rule = ComplianceRule(
            id="test_3",
            subject="Facility discharge",
            relation="",
            object="100 ppm",
            source_document="Clean Air Act",
            source_clause="Section 112",
            confidence=ConfidenceLevel.EXPLICIT,
            reasoning="Rule clearly stated",
        )
        assert validate_rule(rule) is False


class TestExtractionResult:
    """Test extraction result utilities"""

    def test_get_explicit_rules(self):
        """Should filter rules by confidence level"""
        rule1 = ComplianceRule(
            id="1",
            subject="A",
            relation="B",
            object="C",
            source_document="Doc",
            source_clause="Clause",
            confidence=ConfidenceLevel.EXPLICIT,
            reasoning="Test",
        )
        rule2 = ComplianceRule(
            id="2",
            subject="D",
            relation="E",
            object="F",
            source_document="Doc",
            source_clause="Clause",
            confidence=ConfidenceLevel.DISCRETIONARY,
            reasoning="Test",
        )

        from kg_extractor.models import ExtractionMetadata, ExtractionResult

        metadata = ExtractionMetadata(
            document_name="test.txt",
            document_type="regulation",
            sector="energy",
            extraction_timestamp="2026-05-21T00:00:00Z",
            total_rules_extracted=2,
            rules_by_confidence={"EXPLICIT": 1, "DISCRETIONARY": 1},
            extraction_duration_seconds=1.0,
        )

        result = ExtractionResult(rules=[rule1, rule2], metadata=metadata)

        explicit_rules = result.get_explicit_rules()
        assert len(explicit_rules) == 1
        assert explicit_rules[0].id == "1"

        discretionary_rules = result.get_discretionary_rules()
        assert len(discretionary_rules) == 1
        assert discretionary_rules[0].id == "2"


if __name__ == "__main__":
    pytest.main([__file__])
