"""SKI Framework v3.0 §5.4 — Risk-tier governor.

The Tag Registry package now houses the *Risk-Tier Governor* (PR 13).
The package retains the B4.3 deterministic-routing invariant — no
runtime fuzzy matching, no LLM disambiguation, no embedding lookup —
and adds a strict, KG-driven risk-tier verdict that the caller cannot
influence.

This test pins three durability-level claims:

  1. The package ships and contains no fuzzy/LLM/embeddings dependency.
  2. The ``RiskTierGovernor`` class is exposed at package root.
  3. The strict-governor contract is enforced: ``MeasurementRecord``
     does not expose a caller-settable ``risk_tier`` field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.durability
def test_tag_registry_package_exists(repo_root: Path) -> None:
    registry_dir = repo_root / "reference-implementation" / "src" / "tag_registry"
    assert registry_dir.is_dir(), "Reference implementation must ship a tag_registry/ package."
    assert (registry_dir / "registry.py").exists(), "tag_registry/registry.py missing."


@pytest.mark.durability
def test_registry_is_pure_lookup_no_fuzzy_inference(repo_root: Path) -> None:
    """The registry must not invoke an LLM, fuzzy matcher, or embedding lookup."""
    src = (repo_root / "reference-implementation" / "src" / "tag_registry" / "registry.py").read_text()
    for forbidden in ("rapidfuzz", "difflib", "anthropic", "openai", "ollama", "embeddings"):
        assert forbidden not in src.lower(), (
            f"tag_registry/registry.py imports or references {forbidden!r} — "
            "the registry must be a pure dict lookup (B4.3 invariant carried over)."
        )


@pytest.mark.durability
def test_risk_tier_governor_class_exported(repo_root: Path) -> None:
    """``RiskTierGovernor`` must be importable from ``tag_registry``."""
    init_src = (repo_root / "reference-implementation" / "src" / "tag_registry" / "__init__.py").read_text()
    assert "RiskTierGovernor" in init_src, (
        "tag_registry/__init__.py must export RiskTierGovernor (spec v3.0 §5.4)."
    )
    registry_src = (
        repo_root / "reference-implementation" / "src" / "tag_registry" / "registry.py"
    ).read_text()
    assert "class RiskTierGovernor" in registry_src, (
        "RiskTierGovernor class must be defined in tag_registry/registry.py."
    )


@pytest.mark.durability
def test_strict_governor_no_caller_settable_risk_tier(repo_root: Path) -> None:
    """``MeasurementRecord`` must NOT expose a caller-settable risk_tier field.

    Strict-governor invariant (PR 13): the caller cannot self-declare a
    risk tier. The server derives it from the KG via
    ``RiskTierGovernor.tier_for_snapshot``.
    """
    server_src = (repo_root / "reference-implementation" / "src" / "ski_model" / "server.py").read_text()
    # Find the MeasurementRecord class block and assert no risk_tier field.
    marker = "class MeasurementRecord"
    assert marker in server_src, "MeasurementRecord class must exist."
    after = server_src[server_src.index(marker) :]
    # Cut at the next class definition or end of file.
    next_class = after.find("\nclass ", 1)
    block = after if next_class == -1 else after[:next_class]
    assert "risk_tier:" not in block, (
        "MeasurementRecord still declares a risk_tier field. PR 13 removed it; "
        "the strict-governor design forbids caller-settable tier."
    )


@pytest.mark.durability
def test_demo_kgs_route_subjects_via_typed_edges(repo_root: Path) -> None:
    """Every sector demo KG is a v3 typed graph whose applies_to edges
    resolve subject routing (B4.3's governed subject->rule mapping,
    carried into v3 as graph edges instead of a tag_registry dict)."""
    for sector in ("energy", "finance", "manufacturing", "defense"):
        f = repo_root / "examples" / sector / "knowledge-graphs" / f"kg-{sector}-v3-demo.json"
        assert f.exists(), f"Missing v3 demo KG for {sector}."
        kg = json.loads(f.read_text())
        assert kg["metadata"]["schema_version"] == "3.0", f"{f} is not schema 3.0."
        subjects = {n["id"] for n in kg["nodes"]["subjects"]}
        rules = {n["id"] for n in kg["nodes"]["rules"]}
        applies = [e for e in kg["edges"] if e["type"] == "applies_to"]
        assert applies, f"{f} has no applies_to edges — subjects would be unroutable."
        for e in applies:
            assert e["from"] in rules, f"{f}: applies_to from unknown rule {e['from']!r}."
            assert e["to"] in subjects, f"{f}: applies_to to unknown subject {e['to']!r}."
        unrouted = subjects - {e["to"] for e in applies}
        assert not unrouted, f"{f}: subjects with no governing rule: {sorted(unrouted)}."


@pytest.mark.durability
def test_demo_telemetry_has_no_rule_id(repo_root: Path) -> None:
    """B4.3 — producers must not pre-route to a rule."""
    for sector in ("energy", "finance", "manufacturing", "defense"):
        for jsonl in (repo_root / "examples" / sector / "telemetry").glob("*.jsonl"):
            for lineno, line in enumerate(jsonl.read_text().splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                assert "rule_id" not in rec, (
                    f"{jsonl}:{lineno} contains a `rule_id` — the Tag Registry resolves subject→rule. (B4.3)"
                )
