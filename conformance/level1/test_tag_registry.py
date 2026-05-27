"""SKI Framework v2.1 § B4.3 — Tag Registry.

A SKI implementation must route telemetry subjects to KG rules via a
governed Tag Registry compiled in Phase 1. Runtime tag inference
(substring matching, embedding similarity, LLM disambiguation) is
prohibited.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.level1
def test_tag_registry_exists_in_reference_implementation(repo_root: Path) -> None:
    registry_dir = repo_root / "reference-implementation" / "src" / "tag_registry"
    assert registry_dir.is_dir(), "Reference implementation must ship a tag_registry/ package."
    assert (registry_dir / "registry.py").exists(), "tag_registry/registry.py missing."


@pytest.mark.level1
def test_tag_registry_resolve_is_pure_lookup(repo_root: Path) -> None:
    """The resolve() method must not invoke any LLM or fuzzy-match library."""
    src = (repo_root / "reference-implementation" / "src" / "tag_registry" / "registry.py").read_text()
    # Crude but effective: no imports of typical fuzzy/inference libs.
    for forbidden in ("rapidfuzz", "difflib", "anthropic", "openai", "ollama", "embeddings"):
        assert forbidden not in src.lower(), (
            f"tag_registry/registry.py imports or references {forbidden!r} — "
            "the registry must be a pure dict lookup (B4.3)."
        )


@pytest.mark.level1
def test_demo_kgs_have_tag_registry(repo_root: Path) -> None:
    import json

    for sector in ("energy", "finance", "manufacturing", "defense"):
        kg_files = list((repo_root / "examples" / sector / "knowledge-graphs").glob(f"kg-{sector}-demo.json"))
        assert kg_files, f"Missing demo KG for {sector}."
        for f in kg_files:
            kg = json.loads(f.read_text())
            assert kg.get("tag_registry"), f"{f} has no tag_registry — required by B4.3."


@pytest.mark.level1
def test_demo_telemetry_has_no_rule_id(repo_root: Path) -> None:
    """B4.3 — producers must not pre-route to a rule."""
    import json

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
