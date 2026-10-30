"""Tests for the published contracts: the KGObligation model and the
committed JSON Schemas / envelope vectors stay valid and mutually consistent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema.validators import Draft202012Validator
from pydantic import ValidationError
from ski_schemas.kg import KGObligation

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMAS = _REPO_ROOT / "spec" / "contracts" / "schemas"
_ENVELOPES = _REPO_ROOT / "spec" / "test-vectors" / "envelopes"


def test_kg_obligation_minimal() -> None:
    ob = KGObligation(id="energy.so2.cap", metric="so2_ppm", predicate="must_not_exceed", value=100)
    dumped = ob.model_dump(exclude_none=True)
    assert dumped == {
        "id": "energy.so2.cap",
        "metric": "so2_ppm",
        "predicate": "must_not_exceed",
        "value": 100,
    }


def test_kg_obligation_requires_core_fields() -> None:
    with pytest.raises(ValidationError):
        KGObligation(id="x")  # type: ignore[call-arg]  # missing metric, predicate


def test_kg_obligation_allows_extension_predicate_and_extra_keys() -> None:
    ob = KGObligation(
        id="x",
        metric="avg_flow",
        predicate="must_average_within",
        value=[10, 20],
        window_seconds=86400,
        provenance_note="extensible",  # type: ignore[call-arg]  # extra key ignored
    )
    assert ob.window_seconds == 86400
    assert "provenance_note" not in ob.model_dump()


@pytest.mark.parametrize("path", sorted(_SCHEMAS.glob("*.schema.json")), ids=lambda p: p.stem)
def test_committed_schema_is_valid_draft_2020_12(path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("path", sorted(_ENVELOPES.glob("*.json")), ids=lambda p: p.stem)
def test_committed_envelope_validates_against_schema(path: Path) -> None:
    schema = json.loads((_SCHEMAS / "v3_verdict_envelope.schema.json").read_text(encoding="utf-8"))
    envelope = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(envelope)
