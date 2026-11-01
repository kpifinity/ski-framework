"""``audit-ledger export-oscal``: valid OSCAL 1.1.3 Assessment Results that say what the verifier found.

``schemas/oscal_assessment-results_schema-1.1.3.json`` is NIST's published schema
(release v1.1.3, public domain), unmodified. Its patterns use ``\\p{L}`` /
``\\p{N}`` Unicode classes that Python's ``re`` lacks; they are translated to
the equivalent ``[^\\W\\d_]`` / ``\\d`` before validating.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from audit_ledger.models import IntegrityIssue, VerificationResult
from audit_ledger.oscal import assessment_results

jsonschema = pytest.importorskip("jsonschema")

_SCHEMA = Path(__file__).parent / "schemas" / "oscal_assessment-results_schema-1.1.3.json"


@pytest.fixture(scope="module")
def validator() -> Any:
    raw = _SCHEMA.read_text(encoding="utf-8")
    schema = json.loads(raw.replace("\\\\p{L}", "[^\\\\W\\\\d_]").replace("\\\\p{N}", "\\\\d"))
    jsonschema.Draft7Validator.check_schema(schema)
    return jsonschema.Draft7Validator(schema)


def _result(issues: Optional[list[IntegrityIssue]] = None, **overrides: Any) -> VerificationResult:
    fields: dict[str, Any] = {
        "is_valid": not issues,
        "total_entries": 4,
        "sequence_range": (1, 4),
        "time_range": (None, None),
        "chain_continuity": True,
        "chain_link_verified_count": 4,
        "entry_hash_verified_count": 4,
        "hash_verification_total": 4,
        "timestamp_ordering": True,
        "data_consistency": not issues,
        "issues": issues or [],
        "verification_date": datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
        "verdict_signatures_verified": 4,
        "checkpoints_verified": 1,
        "recommendation": "All integrity checks passed.",
    }
    fields.update(overrides)
    return VerificationResult(**fields)


def _states(document: dict[str, Any]) -> dict[str, str]:
    findings = document["assessment-results"]["results"][0]["findings"]
    return {f["target"]["target-id"]: f["target"]["status"]["state"] for f in findings}


def test_clean_verification_is_valid_oscal_with_every_objective_satisfied(validator: Any) -> None:
    document = assessment_results(_result(), ledger_label="plant-7")
    errors = list(validator.iter_errors(document))
    assert errors == [], [e.message for e in errors[:5]]
    assert set(_states(document).values()) == {"satisfied"}
    assert len(_states(document)) == 5


def test_a_forward_rewrite_is_a_not_satisfied_checkpoint_finding(validator: Any) -> None:
    issue = IntegrityIssue(
        issue_type="CHECKPOINT_MISMATCH",
        sequence_number=4,
        description="checkpoint at tree_size 4 no longer matches",
        severity="CRITICAL",
    )
    document = assessment_results(_result([issue], checkpoints_verified=0), ledger_label="plant-7")
    assert list(validator.iter_errors(document)) == []
    states = _states(document)
    assert states["ski-spec-7.1-checkpoints"] == "not-satisfied"
    assert states["ski-spec-7.1-entry-hash"] == "satisfied"
    result = document["assessment-results"]["results"][0]
    finding = next(f for f in result["findings"] if f["target"]["target-id"] == "ski-spec-7.1-checkpoints")
    linked = {r["observation-uuid"] for r in finding["related-observations"]}
    issue_obs = next(o for o in result["observations"] if o["title"].startswith("CHECKPOINT_MISMATCH"))
    assert issue_obs["uuid"] in linked and issue_obs["types"] == ["finding"]


def test_a_replay_report_adds_the_section_8_1_finding(validator: Any) -> None:
    replay = {
        "total_entries": 4,
        "replayed_entries": 3,
        "matched_entries": 3,
        "mismatches": [],
        "is_clean": True,
    }
    document = assessment_results(_result(), ledger_label="plant-7", replay=replay)
    assert list(validator.iter_errors(document)) == []
    assert _states(document)["ski-spec-8.1-replay"] == "satisfied"
    replay["is_clean"] = False
    assert _states(assessment_results(_result(), ledger_label="plant-7", replay=replay))[
        "ski-spec-8.1-replay"
    ] == ("not-satisfied")


def test_export_is_deterministic() -> None:
    assert assessment_results(_result(), ledger_label="x") == assessment_results(_result(), ledger_label="x")
