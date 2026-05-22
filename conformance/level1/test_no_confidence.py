"""SKI Framework v2.1 § B3.1 + Axiom 2 — No confidence scores.

Confidence scores and probabilistic outputs are not permitted. The
ledger schema must NOT carry a `confidence_level` column, and the
audit-ledger data model must NOT expose a `ConfidenceLevel` enum.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.level1
def test_schema_has_no_confidence_level_column(repo_root: Path) -> None:
    schema = (repo_root / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    assert "confidence_level" not in schema, (
        "schema.sql still has a confidence_level column — "
        "B3.1 prohibits confidence scores in the ledger."
    )


@pytest.mark.level1
def test_audit_ledger_models_has_no_confidence_enum(repo_root: Path) -> None:
    models = (repo_root / "tools" / "audit-ledger" / "src" / "audit_ledger" / "models.py").read_text()
    assert "class ConfidenceLevel" not in models, (
        "audit_ledger.models still defines ConfidenceLevel — "
        "remove the enum and the field per B3.1."
    )
    assert "confidence_level:" not in models and "confidence_level=" not in models, (
        "audit_ledger.models still references confidence_level."
    )


@pytest.mark.level1
def test_kg_extractor_rejects_implied(repo_root: Path) -> None:
    """B2.1 Anchor Constraint: `IMPLIED` is prohibited."""
    models = (repo_root / "tools" / "kg-extractor" / "src" / "kg_extractor" / "models.py").read_text()
    assert 'IMPLIED = "IMPLIED"' not in models, (
        "kg-extractor still exposes IMPLIED as a confidence level — "
        "B2.1 Anchor Constraint prohibits it."
    )
