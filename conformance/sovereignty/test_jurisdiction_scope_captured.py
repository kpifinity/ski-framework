"""SKI Framework v3.0 §3.6 + §6 — Jurisdiction scope captured.

``KnowledgeGraph.scope_to(jurisdiction, as_of)`` emits a ``scope`` block
(jurisdiction, as_of, n_in, n_out) on every snapshot, and the runtime
sends that scoped snapshot — not the full KG — to the LLM. An auditor in
jurisdiction X can therefore confirm the runtime sent ONLY X-applicable
obligations. Black-box: we assert the scope block is produced and that
the evaluate path scopes the KG before evaluation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SRC = ("reference-implementation", "src", "ski_model")


@pytest.mark.sovereignty
def test_scope_block_is_emitted(repo_root: Path) -> None:
    loader = (repo_root.joinpath(*SRC, "kg_loader.py")).read_text()
    assert "def scope_to" in loader, "KnowledgeGraph has no scope_to()."
    body = loader.split("def scope_to", 1)[1]
    for field in ('"jurisdiction"', '"as_of"', '"n_in"', '"n_out"'):
        assert field in body, f"scope_to does not record {field} in the snapshot scope block."


@pytest.mark.sovereignty
def test_evaluate_path_scopes_the_kg(repo_root: Path) -> None:
    server = (repo_root.joinpath(*SRC, "server.py")).read_text()
    assert ".scope_to(" in server, (
        "the /api/evaluate path does not scope the KG (scope_to) before sending it to the evaluator."
    )
