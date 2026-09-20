"""SKI Framework v3.0 — telemetry clock-skew enforcement.

docs/threat-model.md "Assumption 2" documented ``max_clock_skew_seconds``
as an unenforced column: the schema declared it, but no runtime code path
read or checked it, so a forged or drifted telemetry ``timestamp`` could
make stale/fabricated data appear current -- defeating ``NULL_STALE``
routing, freshness gates, and window predicates, all of which trust the
telemetry timestamp as ground truth. This is a provenance-level concern
for the same reason NULL_STALE routing is (see
``test_null_stale_routing.py``): the runtime must be able to tell "this
data is honestly current" from "this data claims to be current".

Full end-to-end coverage (the /api/evaluate short-circuit, ledgering,
reject mode, the metric) lives in
``reference-implementation/src/ski_model/v3/tests/test_clock_skew_guard.py``
via FastAPI's TestClient. This conformance test pins the black-box
contract: the guard exists, is documented as enforced, and its core
comparison is correct.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_server() -> object:
    src = REPO_ROOT / "reference-implementation" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from ski_model import server

    return server


@pytest.mark.provenance
def test_clock_skew_delta_is_correct() -> None:
    server = _import_server()
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    within = t0 + timedelta(seconds=30)
    over = t0 + timedelta(seconds=90)
    assert server._clock_skew_delta_seconds(t0, within) == pytest.approx(30.0)
    assert server._clock_skew_delta_seconds(t0, over) == pytest.approx(90.0)


@pytest.mark.provenance
def test_over_skew_envelope_is_discretionary_and_ledgerable() -> None:
    """The short-circuit envelope must be a non-CLEAR, auditable verdict --
    never a silent drop of the suspicious record."""
    server = _import_server()
    envelope = server._build_clock_skew_envelope(
        skew_note="clock_skew: telemetry Δ3600.0s exceeds max_clock_skew_seconds=60",
        kg_version_hash="sha256:" + "b" * 64,
    )
    assert envelope.verdict == "DISCRETIONARY"
    assert envelope.verifier_result.status == "UNVERIFIABLE"
    assert envelope.human_attestation is not None
    assert envelope.human_attestation["required"] is True
    assert any("clock_skew" in n for n in envelope.notes)


@pytest.mark.provenance
def test_max_clock_skew_seconds_has_a_safe_default() -> None:
    server = _import_server()
    assert server._DEFAULT_MAX_CLOCK_SKEW_SECONDS == 60


@pytest.mark.provenance
def test_clock_skew_metric_is_registered() -> None:
    server = _import_server()
    assert server.metrics.TELEMETRY_CLOCK_SKEW is not None


@pytest.mark.provenance
def test_threat_model_documents_enforcement(repo_root: Path) -> None:
    """The residual-risk gap this closes must be documented as closed, not
    still described as open (docs/threat-model.md "Assumption 2")."""
    threat_model = (repo_root / "docs" / "threat-model.md").read_text(encoding="utf-8")
    assert "ski_telemetry_clock_skew_total" in threat_model
    assert "no runtime code path reads or enforces it" not in threat_model


@pytest.mark.provenance
def test_rfc_0001_documents_the_shipped_knob(repo_root: Path) -> None:
    """RFC 0001's residual note described a `--max-clock-skew-seconds` CLI
    flag that was never built; it must describe what actually shipped."""
    rfc = (repo_root / "docs" / "RFCs" / "0001-stateful-evaluation.md").read_text(encoding="utf-8")
    assert "SKI_MAX_CLOCK_SKEW_SECONDS" in rfc
