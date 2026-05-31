"""Tests for KnowledgeGraph.scope_to() — jurisdiction + effective-date scoping.

This is the framework's mechanism for preventing prompt-window blow-up on
real-sized KGs (PR 11.7). Each test builds a hand-rolled KnowledgeGraph
with rules of varying ``jurisdiction``, ``effective_date``, and
``sunset_date``, then asserts that only the applicable subset survives.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from ski_model.kg_loader import KnowledgeGraph


def _kg(rules: List[Dict[str, Any]]) -> KnowledgeGraph:
    return KnowledgeGraph(
        version="v3test-0001",
        rules=rules,
        tag_registry={},
        metadata={"version": "v3test-0001"},
        signature_verified=True,
    )


_AS_OF = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---- Effective-date scoping ---------------------------------------------------


class TestEffectiveDate:
    def test_future_effective_date_excluded(self) -> None:
        kg = _kg([{"id": "r.a", "effective_date": "2027-01-01"}])
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        assert out["obligations"] == []
        assert out["scope"]["n_in"] == 1
        assert out["scope"]["n_out"] == 0

    def test_past_effective_date_included(self) -> None:
        kg = _kg([{"id": "r.a", "effective_date": "2025-01-01"}])
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        assert len(out["obligations"]) == 1

    def test_missing_effective_date_treated_as_always_effective(self) -> None:
        kg = _kg([{"id": "r.a"}])
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        assert len(out["obligations"]) == 1

    def test_sunset_in_the_past_excluded(self) -> None:
        kg = _kg([{"id": "r.a", "effective_date": "2024-01-01", "sunset_date": "2025-01-01"}])
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        assert out["obligations"] == []

    def test_sunset_null_treated_as_open(self) -> None:
        kg = _kg([{"id": "r.a", "effective_date": "2024-01-01", "sunset_date": None}])
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        assert len(out["obligations"]) == 1


# ---- Jurisdiction scoping -----------------------------------------------------


class TestJurisdiction:
    def test_no_tenant_jurisdiction_keeps_everything(self) -> None:
        kg = _kg(
            [
                {"id": "r.a", "jurisdiction": "us-ca"},
                {"id": "r.b", "jurisdiction": "eu"},
                {"id": "r.c"},  # no jurisdiction
            ]
        )
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        assert {r["id"] for r in out["obligations"]} == {"r.a", "r.b", "r.c"}

    def test_tenant_jurisdiction_filters_exact_matches(self) -> None:
        kg = _kg(
            [
                {"id": "r.a", "jurisdiction": "us-ca"},
                {"id": "r.b", "jurisdiction": "eu"},
            ]
        )
        out = kg.scope_to(jurisdiction="us-ca", as_of=_AS_OF)
        assert {r["id"] for r in out["obligations"]} == {"r.a"}

    def test_rule_without_jurisdiction_passes_any_tenant(self) -> None:
        kg = _kg(
            [
                {"id": "r.a"},
                {"id": "r.b", "jurisdiction": "us-ca"},
            ]
        )
        out = kg.scope_to(jurisdiction="eu", as_of=_AS_OF)
        # r.a has no jurisdiction → universal; r.b is wrong jurisdiction.
        assert {r["id"] for r in out["obligations"]} == {"r.a"}

    def test_universal_sentinels_match_any_tenant(self) -> None:
        kg = _kg(
            [
                {"id": "r.global", "jurisdiction": "global"},
                {"id": "r.star", "jurisdiction": "*"},
                {"id": "r.empty", "jurisdiction": ""},
                {"id": "r.uk", "jurisdiction": "uk"},
            ]
        )
        out = kg.scope_to(jurisdiction="us-ca", as_of=_AS_OF)
        assert {r["id"] for r in out["obligations"]} == {"r.global", "r.star", "r.empty"}

    def test_jurisdiction_match_is_case_insensitive(self) -> None:
        kg = _kg([{"id": "r.a", "jurisdiction": "US-CA"}])
        out = kg.scope_to(jurisdiction="us-ca", as_of=_AS_OF)
        assert len(out["obligations"]) == 1

    def test_jurisdiction_list_any_match(self) -> None:
        kg = _kg([{"id": "r.a", "jurisdiction": ["us-ca", "us-ny"]}])
        out = kg.scope_to(jurisdiction="us-ny", as_of=_AS_OF)
        assert len(out["obligations"]) == 1

    def test_jurisdiction_list_no_match(self) -> None:
        kg = _kg([{"id": "r.a", "jurisdiction": ["us-ca", "us-ny"]}])
        out = kg.scope_to(jurisdiction="eu", as_of=_AS_OF)
        assert out["obligations"] == []

    def test_jurisdiction_list_with_universal_matches_anything(self) -> None:
        kg = _kg([{"id": "r.a", "jurisdiction": ["us-ca", "global"]}])
        out = kg.scope_to(jurisdiction="eu", as_of=_AS_OF)
        assert len(out["obligations"]) == 1


# ---- Combined scoping ---------------------------------------------------------


class TestCombined:
    def test_both_filters_must_pass(self) -> None:
        kg = _kg(
            [
                {"id": "r.a", "jurisdiction": "us-ca", "effective_date": "2025-01-01"},
                {"id": "r.b", "jurisdiction": "us-ca", "effective_date": "2027-01-01"},
                {"id": "r.c", "jurisdiction": "eu", "effective_date": "2025-01-01"},
            ]
        )
        out = kg.scope_to(jurisdiction="us-ca", as_of=_AS_OF)
        assert {r["id"] for r in out["obligations"]} == {"r.a"}


# ---- Snapshot shape -----------------------------------------------------------


class TestSnapshotShape:
    def test_snapshot_carries_scope_block(self) -> None:
        kg = _kg([{"id": "r.a"}])
        out = kg.scope_to(jurisdiction="us-ca", as_of=_AS_OF)
        scope = out["scope"]
        assert scope["jurisdiction"] == "us-ca"
        assert scope["as_of"] == _AS_OF.isoformat()
        assert scope["n_in"] == 1
        assert scope["n_out"] == 1

    def test_snapshot_keys_match_evaluator_expectation(self) -> None:
        kg = _kg([{"id": "r.a"}])
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        # The v3 evaluator reads these keys from the snapshot.
        assert "version" in out
        assert "obligations" in out
        assert "definitions" in out

    def test_definitions_come_from_metadata(self) -> None:
        kg = KnowledgeGraph(
            version="v3test-0001",
            rules=[{"id": "r.a"}],
            tag_registry={},
            metadata={
                "version": "v3test-0001",
                "definitions": [{"id": "def.units.ppm"}],
            },
            signature_verified=True,
        )
        out = kg.scope_to(jurisdiction=None, as_of=_AS_OF)
        assert out["definitions"] == [{"id": "def.units.ppm"}]
