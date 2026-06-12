"""Tests for the v3 KG schema, loader, and validator.

These tests exercise spec v3.0 sections 3.1 through 3.6 against synthetic
v3 KGs constructed in-test. The bundled demo KG at
``examples/energy/knowledge-graphs/kg-energy-v3-demo.json`` is also
loaded as a smoke test so any breaking schema change shows up here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from kg_validator import (
    EdgeType,
    KnowledgeGraphV3,
    ObligationType,
    RiskTier,
    V3IssueType,
    V3Validator,
    load_v3_kg,
)
from pydantic import ValidationError

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_KG_PATH = REPO_ROOT / "examples" / "energy" / "knowledge-graphs" / "kg-energy-v3-demo.json"


def _minimal_kg_payload() -> Dict[str, Any]:
    """A small but spec-clean v3 KG used as the base for negative-case tests."""
    return {
        "metadata": {"name": "Test KG", "schema_version": "3.0"},
        "nodes": {
            "subjects": [
                {
                    "id": "subj.x",
                    "type": "Subject",
                    "version": "v1",
                    "name": "Subject X",
                }
            ],
            "rules": [
                {
                    "id": "rule.x",
                    "type": "Rule",
                    "version": "v1",
                    "name": "Rule X",
                    "risk_tier": "medium",
                }
            ],
            "obligations": [
                {
                    "id": "ob.x",
                    "type": "Obligation",
                    "version": "v1",
                    "obligation_type": "must_not_exceed",
                    "metric": "x",
                    "value": 10,
                    "effective_date_start": "2026-01-01T00:00:00Z",
                }
            ],
            "definitions": [],
            "exemptions": [],
            "precedents": [],
            "jurisdictions": [],
            "citations": [],
        },
        "edges": [
            {"type": "applies_to", "from": "rule.x", "to": "subj.x"},
            {"type": "consists_of", "from": "rule.x", "to": "ob.x"},
        ],
    }


# --------------------------------------------------------------------------- #
# Schema-level (Pydantic) tests                                               #
# --------------------------------------------------------------------------- #


class TestSchema:
    def test_demo_kg_loads(self) -> None:
        kg = load_v3_kg(str(DEMO_KG_PATH))
        assert isinstance(kg, KnowledgeGraphV3)
        assert kg.metadata.schema_version == "3.0"
        assert len(kg.nodes.rules) == 2
        assert len(kg.nodes.obligations) == 2
        assert len(kg.edges) == 8

    def test_obligation_type_is_a_closed_enum(self) -> None:
        payload = _minimal_kg_payload()
        payload["nodes"]["obligations"][0]["obligation_type"] = "must_be_purple"
        with pytest.raises(ValidationError):
            KnowledgeGraphV3.model_validate(payload)

    def test_missing_effective_date_start_is_rejected(self) -> None:
        payload = _minimal_kg_payload()
        del payload["nodes"]["obligations"][0]["effective_date_start"]
        with pytest.raises(ValidationError):
            KnowledgeGraphV3.model_validate(payload)

    def test_unknown_risk_tier_is_rejected(self) -> None:
        payload = _minimal_kg_payload()
        payload["nodes"]["rules"][0]["risk_tier"] = "extreme"
        with pytest.raises(ValidationError):
            KnowledgeGraphV3.model_validate(payload)

    def test_unknown_edge_type_is_rejected(self) -> None:
        payload = _minimal_kg_payload()
        payload["edges"].append({"type": "ouroboros", "from": "rule.x", "to": "ob.x"})
        with pytest.raises(ValidationError):
            KnowledgeGraphV3.model_validate(payload)

    def test_extra_keys_on_nodes_are_rejected(self) -> None:
        payload = _minimal_kg_payload()
        payload["nodes"]["subjects"][0]["secret_field"] = "abc"
        with pytest.raises(ValidationError):
            KnowledgeGraphV3.model_validate(payload)


# --------------------------------------------------------------------------- #
# Validator tests                                                             #
# --------------------------------------------------------------------------- #


class TestValidatorClean:
    """The clean-KG case must surface zero issues."""

    def test_demo_kg_validates_clean(self) -> None:
        kg = load_v3_kg(str(DEMO_KG_PATH))
        result = V3Validator(kg).run()
        assert result.total_issues == 0, [i.model_dump() for i in result.issues]
        assert result.is_clean is True

    def test_minimal_kg_validates_clean(self) -> None:
        kg = KnowledgeGraphV3.model_validate(_minimal_kg_payload())
        result = V3Validator(kg).run()
        assert result.total_issues == 0
        assert result.total_nodes == 3
        assert result.total_edges == 2


class TestValidatorDanglingEdges:
    def test_dangling_source_is_flagged(self) -> None:
        payload = _minimal_kg_payload()
        payload["edges"].append({"type": "applies_to", "from": "rule.ghost", "to": "subj.x"})
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        issue_types = {i.issue_type for i in result.issues}
        assert V3IssueType.DANGLING_EDGE.value in issue_types

    def test_dangling_target_is_flagged(self) -> None:
        payload = _minimal_kg_payload()
        payload["edges"].append({"type": "applies_to", "from": "rule.x", "to": "subj.ghost"})
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        issue_types = {i.issue_type for i in result.issues}
        assert V3IssueType.DANGLING_EDGE.value in issue_types


class TestValidatorEdgeTargetTypes:
    def test_applies_to_must_target_subject(self) -> None:
        payload = _minimal_kg_payload()
        # Repoint applies_to at an obligation instead of a subject.
        for edge in payload["edges"]:
            if edge["type"] == "applies_to":
                edge["to"] = "ob.x"
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        assert any(i.issue_type == V3IssueType.INVALID_EDGE_TARGET_TYPE.value for i in result.issues)

    def test_consists_of_must_target_obligation(self) -> None:
        payload = _minimal_kg_payload()
        for edge in payload["edges"]:
            if edge["type"] == "consists_of":
                edge["to"] = "subj.x"
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        assert any(i.issue_type == V3IssueType.INVALID_EDGE_TARGET_TYPE.value for i in result.issues)

    def test_scoped_to_must_target_jurisdiction(self) -> None:
        payload = _minimal_kg_payload()
        payload["edges"].append({"type": "scoped_to", "from": "ob.x", "to": "subj.x"})
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        assert any(i.issue_type == V3IssueType.INVALID_EDGE_TARGET_TYPE.value for i in result.issues)


class TestValidatorCoverage:
    def test_rule_without_obligation_is_flagged(self) -> None:
        payload = _minimal_kg_payload()
        # Drop the consists_of edge from the only rule.
        payload["edges"] = [e for e in payload["edges"] if e["type"] != "consists_of"]
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        assert any(i.issue_type == V3IssueType.RULE_WITHOUT_OBLIGATION.value for i in result.issues)

    def test_orphan_obligation_is_flagged(self) -> None:
        payload = _minimal_kg_payload()
        payload["nodes"]["obligations"].append(
            {
                "id": "ob.orphan",
                "type": "Obligation",
                "version": "v1",
                "obligation_type": "must_not_exceed",
                "metric": "y",
                "value": 5,
                "effective_date_start": "2026-01-01T00:00:00Z",
            }
        )
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        assert any(
            i.issue_type == V3IssueType.OBLIGATION_WITHOUT_RULE.value and i.node_id == "ob.orphan"
            for i in result.issues
        )


class TestValidatorDuplicateIds:
    def test_duplicate_within_same_array_is_flagged(self) -> None:
        payload = _minimal_kg_payload()
        payload["nodes"]["subjects"].append(
            {
                "id": "subj.x",
                "type": "Subject",
                "version": "v1b",
                "name": "Subject X duplicate",
            }
        )
        kg = KnowledgeGraphV3.model_validate(payload)
        result = V3Validator(kg).run()
        assert any(i.issue_type == V3IssueType.DUPLICATE_NODE_ID.value for i in result.issues)

    def test_clean_kg_has_no_duplicate_findings(self) -> None:
        kg = KnowledgeGraphV3.model_validate(_minimal_kg_payload())
        result = V3Validator(kg).run()
        assert not any(i.issue_type == V3IssueType.DUPLICATE_NODE_ID.value for i in result.issues)


# --------------------------------------------------------------------------- #
# Enumerations smoke tests                                                    #
# --------------------------------------------------------------------------- #


class TestEnumerations:
    def test_obligation_type_enumeration_covers_spec_3_3(self) -> None:
        expected = {
            "must",
            "must_not",
            "must_not_exceed",
            "must_be_at_least",
            "must_be_below",
            "must_be_above",
            "must_be_within",
            "must_be_one_of",
            "must_not_be_one_of",
            "must_be_recorded_within",
            "should",
            "discretionary",
        }
        extensions = {
            # Runtime-checkable implementation extensions, pending formal
            # adoption into spec §3.3 (tracked for the v3.1 spec revision).
            "must_equal",
            "must_not_equal",
            "must_average_within",
            "must_not_exceed_in_window",
        }
        assert {member.value for member in ObligationType} == expected | extensions

    def test_edge_type_enumeration_covers_spec_3_2(self) -> None:
        expected = {
            "applies_to",
            "consists_of",
            "defined_by",
            "exempted_by",
            "amended_by",
            "interpreted_by",
            "scoped_to",
            "cited_by",
        }
        assert {member.value for member in EdgeType} == expected

    def test_risk_tier_enumeration_covers_spec_5_4(self) -> None:
        assert {member.value for member in RiskTier} == {"low", "medium", "high"}


# --------------------------------------------------------------------------- #
# Round-trip & serialization                                                  #
# --------------------------------------------------------------------------- #


class TestRoundTrip:
    def test_demo_kg_serializes_back_to_json(self) -> None:
        kg = load_v3_kg(str(DEMO_KG_PATH))
        round_tripped = kg.model_dump(mode="json", by_alias=True)
        # Sanity: round-tripping preserves the rule and obligation counts.
        assert len(round_tripped["nodes"]["rules"]) == 2
        assert len(round_tripped["nodes"]["obligations"]) == 2
        assert len(round_tripped["edges"]) == 8
        # And the model can be re-parsed from its own dump.
        re_parsed = KnowledgeGraphV3.model_validate(round_tripped)
        re_result = V3Validator(re_parsed).run()
        assert re_result.total_issues == 0


# --------------------------------------------------------------------------- #
# CLI integration: ensure the file loads without invoking the full CLI loop.  #
# --------------------------------------------------------------------------- #


def test_demo_kg_file_is_valid_json() -> None:
    raw = json.loads(DEMO_KG_PATH.read_text(encoding="utf-8"))
    assert raw["metadata"]["schema_version"] == "3.0"
    assert "nodes" in raw
    assert "edges" in raw
