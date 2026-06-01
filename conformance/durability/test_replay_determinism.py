"""SKI Framework v3.0 §6 — Deterministic replay primitive.

The audit-ledger CLI must expose a ``replay`` subcommand that re-runs
ledger entries against the recorded buffer state and refuses to claim
success when verdicts diverge. Replay is the prerequisite for Level 3
tamper-resistance testing.

These tests are static (assert the surface exists, with the right flags
and exit semantics). Live-DB replay is covered by integration tests
that require ``--ledger-dsn``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.durability
def test_replay_module_exists() -> None:
    p = REPO_ROOT / "tools" / "audit-ledger" / "src" / "audit_ledger" / "replay.py"
    assert p.exists(), "audit-ledger must ship a replay module for durability-level conformance."
    src = p.read_text()
    assert "telemetry_hash" in src
    assert "aevaluate" in src
    assert "ReplayMismatch" in src
    assert "ReplayReport" in src


@pytest.mark.durability
def test_replay_cli_command_registered() -> None:
    cli = (REPO_ROOT / "tools" / "audit-ledger" / "src" / "audit_ledger" / "cli.py").read_text()
    assert "def replay(" in cli, "CLI must expose a `replay` subcommand."
    assert "--strict" in cli
    assert "default=True" in cli
    for flag in ("--from-sequence", "--to-sequence", "--kg-path"):
        assert flag in cli, f"replay must accept {flag}."


@pytest.mark.durability
def test_replay_skips_v01_entries_safely() -> None:
    """v0.1 entries pre-date the buffer; replay should skip them with a note,
    not invent state."""
    src = (REPO_ROOT / "tools" / "audit-ledger" / "src" / "audit_ledger" / "replay.py").read_text()
    assert "0.1.0" in src
    assert "schema_version" in src
    assert "pre-buffer" in src.lower() or "skipped" in src.lower()
