"""Tests for kg-extractor."""

import pytest
from kg_extractor import emit_v3_kg
from kg_extractor.models import (
    ComplianceRule,
    ExtractionMetadata,
    ExtractionQuality,
    ExtractionResult,
)
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
            extraction_quality=ExtractionQuality.EXPLICIT,
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
            extraction_quality=ExtractionQuality.EXPLICIT,
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
            extraction_quality=ExtractionQuality.EXPLICIT,
            reasoning="Rule clearly stated",
        )
        assert validate_rule(rule) is False


def _sample_metadata(quality_counts):
    return ExtractionMetadata(
        document_name="test.txt",
        document_type="regulation",
        sector="energy",
        extraction_timestamp="2026-05-21T00:00:00Z",
        total_rules_extracted=sum(quality_counts.values()),
        rules_by_quality=quality_counts,
        extraction_duration_seconds=1.0,
        backend="anthropic",
        model_used="claude-opus",
        temperature=0.0,
    )


class TestExtractionResult:
    """Test extraction result utilities"""

    def test_get_explicit_rules(self):
        """Should filter rules by extraction quality"""
        rule1 = ComplianceRule(
            id="1",
            subject="A",
            relation="B",
            object="C",
            source_document="Doc",
            source_clause="Clause",
            extraction_quality=ExtractionQuality.EXPLICIT,
            reasoning="Test",
        )
        rule2 = ComplianceRule(
            id="2",
            subject="D",
            relation="E",
            object="F",
            source_document="Doc",
            source_clause="Clause",
            extraction_quality=ExtractionQuality.DISCRETIONARY,
            reasoning="Test",
        )

        metadata = _sample_metadata({"EXPLICIT": 1, "DISCRETIONARY": 1})
        result = ExtractionResult(rules=[rule1, rule2], metadata=metadata)

        explicit_rules = result.get_explicit_rules()
        assert len(explicit_rules) == 1
        assert explicit_rules[0].id == "1"

        discretionary_rules = result.get_discretionary_rules()
        assert len(discretionary_rules) == 1
        assert discretionary_rules[0].id == "2"


class TestV3Emitter:
    """PR 10e: extraction result wraps into a v3 KG dict."""

    def _result_with_one_explicit_rule(self):
        rule = ComplianceRule(
            id="r1",
            subject="Facility SO2 discharge",
            relation="must_not_exceed",
            object="100 ppm",
            source_document="Clean Air Act",
            source_clause="Section 112",
            extraction_quality=ExtractionQuality.EXPLICIT,
            reasoning="Section 112: facilities must not exceed 100 ppm SO2",
        )
        return ExtractionResult(rules=[rule], metadata=_sample_metadata({"EXPLICIT": 1}))

    def test_emit_v3_kg_basic_shape(self):
        result = self._result_with_one_explicit_rule()
        kg = emit_v3_kg(result, jurisdiction="us.federal", sector="energy")

        assert kg["metadata"]["schema_version"] == "3.0"
        assert kg["metadata"]["sector"] == "energy"
        assert len(kg["nodes"]["rules"]) == 1
        assert len(kg["nodes"]["obligations"]) == 1
        assert len(kg["nodes"]["subjects"]) == 1
        assert len(kg["nodes"]["jurisdictions"]) == 1
        assert len(kg["nodes"]["citations"]) == 1

    def test_emit_v3_kg_obligation_type_guess(self):
        result = self._result_with_one_explicit_rule()
        kg = emit_v3_kg(result)
        obligation = kg["nodes"]["obligations"][0]
        assert obligation["obligation_type"] == "must_not_exceed"
        assert obligation["value"] == 100
        assert obligation["unit"] == "ppm"

    def test_emit_v3_kg_edges_form_complete_graph(self):
        result = self._result_with_one_explicit_rule()
        kg = emit_v3_kg(result, jurisdiction="us.federal")
        edge_types = sorted(e["type"] for e in kg["edges"])
        assert edge_types == [
            "applies_to",
            "cited_by",
            "consists_of",
            "scoped_to",
        ]

    def test_emit_v3_kg_unknown_relation_falls_to_discretionary(self):
        rule = ComplianceRule(
            id="r2",
            subject="X",
            relation="ought_to_be_purple",  # not in the mapping
            object="purple",
            source_document="Doc",
            source_clause="Cl",
            extraction_quality=ExtractionQuality.DISCRETIONARY,
            reasoning="Edge case",
        )
        result = ExtractionResult(rules=[rule], metadata=_sample_metadata({"DISCRETIONARY": 1}))
        kg = emit_v3_kg(result)
        assert kg["nodes"]["obligations"][0]["obligation_type"] == "discretionary"


class TestChunkingTermination:
    """Regression tests for the chunk_text sliding-window terminator.

    chunk_text used to loop forever once the window reached end-of-text
    with a non-zero overlap (``start = end - overlap`` never advanced past
    ``len(text)``). These tests pin the terminator and the argument guards.
    """

    def test_long_text_with_overlap_terminates_and_covers_bounds(self):
        body = "".join(f"Sentence number {i}. " for i in range(200))
        assert len(body) > 100

        chunks = chunk_text(body, max_chunk_size=100, overlap=10)

        assert len(chunks) > 1
        assert all(chunks)  # no empty chunks
        assert body.startswith(chunks[0])  # first chunk is a prefix
        assert body.endswith(chunks[-1])  # last chunk reaches end-of-text

    def test_overlap_not_smaller_than_chunk_size_is_rejected(self):
        with pytest.raises(ValueError):
            chunk_text("x" * 500, max_chunk_size=100, overlap=100)

    def test_non_positive_chunk_size_is_rejected(self):
        with pytest.raises(ValueError):
            chunk_text("x" * 500, max_chunk_size=0)


if __name__ == "__main__":
    pytest.main([__file__])
