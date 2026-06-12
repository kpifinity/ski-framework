"""The /metrics endpoint honours the alert-rules contract.

monitoring/rules/ski-alerts.yml has been a shipped contract since v2.1;
these tests pin that the runtime actually exports every series the
rules fire on, and that the interesting ones move.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from ski_model import metrics, server

REPO = Path(__file__).resolve().parents[5]
ALERT_RULES = REPO / "reference-implementation" / "monitoring" / "rules" / "ski-alerts.yml"


def _scrape() -> str:
    # No context manager: /metrics must work without the lifespan (no KG,
    # no ledger, no signer) — Prometheus scrapes whatever is up.
    response = TestClient(server.app).get("/metrics")
    assert response.status_code == 200
    return str(response.text)


def test_alert_rule_series_are_exported() -> None:
    """Every ski_* series referenced by the alert rules exists at /metrics."""
    text = _scrape()
    rules = ALERT_RULES.read_text(encoding="utf-8")
    wanted = set(re.findall(r"\b(ski_[a-z_]+)\b", rules))
    # the sidecar exports its own freshness series from its own process
    wanted.discard("ski_sidecar_last_telemetry_timestamp")
    assert wanted, "alert rules should reference ski_* series"
    for series in wanted:
        base = series.removesuffix("_total")
        assert base in text, f"alert rules page on {series!r} but /metrics does not export it"


def test_kg_signature_gauge_moves() -> None:
    metrics.KG_SIGNATURE_VERIFIED.set(1)
    assert "ski_kg_signature_verified 1.0" in _scrape()
    metrics.KG_SIGNATURE_VERIFIED.set(0)
    assert "ski_kg_signature_verified 0.0" in _scrape()


def test_verdict_counter_increments() -> None:
    metrics.VERDICTS.labels(verdict="FLAG").inc()
    text = _scrape()
    m = re.search(r'ski_verdicts_total\{verdict="FLAG"\} (\d+)', text)
    assert m and int(float(m.group(1))) >= 1


def test_ledger_gap_counter_present_and_monotonic() -> None:
    before = metrics.LEDGER_SEQUENCE_GAPS._value.get()
    metrics.LEDGER_SEQUENCE_GAPS.inc()
    text = _scrape()
    m = re.search(r"ski_ledger_sequence_gaps_total (\d+)", text)
    assert m and float(m.group(1)) == before + 1


def test_metrics_endpoint_requires_no_auth() -> None:
    """Scrape endpoints can't carry API keys; the route must be open."""
    client = TestClient(server.app)
    assert client.get("/metrics").status_code == 200
