"""Tests for :class:`tag_registry.TagRegistry` (subject -> rule lookup).

``RiskTierGovernor`` (same module) already has full coverage via
``test_risk_tier_governor.py``; this file covers ``TagRegistry`` itself,
which had none.
"""

from __future__ import annotations

import pytest
from tag_registry import TagRegistry


class _FakeKG:
    def __init__(self, tag_registry: dict[str, str], rules: list[dict[str, object]]) -> None:
        self.tag_registry = tag_registry
        self.rules = rules


class TestFromDict:
    def test_compiles_subject_to_rule_mapping(self) -> None:
        rules = [{"id": "r.a", "metric": "so2_ppm"}]
        reg = TagRegistry.from_dict({"emissions": "r.a"}, rules)
        assert reg.resolve("emissions") == rules[0]

    def test_unknown_rule_id_raises(self) -> None:
        """A tag registry entry pointing at a rule id absent from the KG's
        own rule set is a KG compilation bug -- refuse to load silently."""
        with pytest.raises(ValueError, match="r\\.missing"):
            TagRegistry.from_dict({"emissions": "r.missing"}, rules=[{"id": "r.a"}])

    def test_rules_without_id_are_ignored_in_the_index(self) -> None:
        rules = [{"id": "r.a"}, {"no_id": "stray"}]
        reg = TagRegistry.from_dict({"emissions": "r.a"}, rules)
        assert reg.resolve("emissions") == rules[0]

    def test_from_knowledge_graph_delegates_to_from_dict(self) -> None:
        kg = _FakeKG(tag_registry={"emissions": "r.a"}, rules=[{"id": "r.a"}])
        reg = TagRegistry.from_knowledge_graph(kg)
        assert reg.resolve("emissions") == {"id": "r.a"}


class TestResolve:
    def test_unmapped_subject_returns_none(self) -> None:
        reg = TagRegistry.from_dict({}, rules=[])
        assert reg.resolve("nonexistent") is None

    def test_resolve_is_case_and_whitespace_insensitive(self) -> None:
        reg = TagRegistry.from_dict({"  Emissions   Line ": "r.a"}, rules=[{"id": "r.a"}])
        assert reg.resolve("emissions line") == {"id": "r.a"}
        assert reg.resolve("EMISSIONS LINE") == {"id": "r.a"}


class TestContainerProtocol:
    def test_contains(self) -> None:
        reg = TagRegistry.from_dict({"emissions": "r.a"}, rules=[{"id": "r.a"}])
        assert "emissions" in reg
        assert "EMISSIONS" in reg
        assert "unrelated" not in reg

    def test_len(self) -> None:
        reg = TagRegistry.from_dict({"a": "r.a", "b": "r.b"}, rules=[{"id": "r.a"}, {"id": "r.b"}])
        assert len(reg) == 2

    def test_empty_registry_has_zero_length(self) -> None:
        reg = TagRegistry.from_dict({}, rules=[])
        assert len(reg) == 0

    def test_subjects_lists_normalised_keys(self) -> None:
        reg = TagRegistry.from_dict({"  Emissions ": "r.a"}, rules=[{"id": "r.a"}])
        assert reg.subjects() == ["emissions"]
