"""Prometheus metrics — the observability contract, implemented.

``monitoring/rules/ski-alerts.yml`` has shipped alert rules since v2.1;
this module makes the runtime actually export the series those rules
fire on. The rule expressions are the CONTRACT — the metric names here
must never drift from them:

  * ``ski_agreement_rate``            — rolling LLM↔verifier agreement.
  * ``ski_kg_signature_verified``     — 1 iff the loaded KG's signature verified.
  * ``ski_ledger_sequence_gaps_total``— ledger sequence discontinuities observed
                                        by this process (tamper/ops signal).

Plus operational basics: verdict counters by type, evaluation latency,
and a runtime info gauge. The ``/metrics`` endpoint is intentionally
unauthenticated (Prometheus scrape); it exposes aggregate counters
only — no payloads, no verdicts, no tenant data — and is contained by
the sovereign-boundary NetworkPolicy like every other port.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

AGREEMENT_RATE = Gauge(
    "ski_agreement_rate",
    "Rolling neuro-symbolic agreement rate over the configured window (0-1).",
    registry=REGISTRY,
)
KG_SIGNATURE_VERIFIED = Gauge(
    "ski_kg_signature_verified",
    "1 if the currently loaded Knowledge Graph's ed25519 signature verified, else 0.",
    registry=REGISTRY,
)
LEDGER_SEQUENCE_GAPS = Counter(
    "ski_ledger_sequence_gaps",
    "Ledger sequence discontinuities observed by this writer process. "
    "Any increase is a page: it means rows appeared or vanished outside "
    "this single writer — tampering or an operational fault.",
    registry=REGISTRY,
)
VERDICTS = Counter(
    "ski_verdicts",
    "Verdicts produced, by taxonomy type.",
    ["verdict"],
    registry=REGISTRY,
)
EVALUATION_SECONDS = Histogram(
    "ski_evaluation_duration_seconds",
    "End-to-end /api/evaluate handler latency (scoping, inference, verification, signing, ledger append).",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 60.0),
    registry=REGISTRY,
)
LAST_TELEMETRY_TS = Gauge(
    "ski_model_last_telemetry_timestamp",
    "Unix time of the last measurement accepted by /api/evaluate. "
    "(The sidecar exports ski_sidecar_last_telemetry_timestamp for "
    "intake-side freshness; this is the evaluation-side twin.)",
    registry=REGISTRY,
)
RUNTIME_INFO = Gauge(
    "ski_runtime_info",
    "Constant 1; labels carry runtime version and LLM backend.",
    ["version", "backend"],
    registry=REGISTRY,
)


def render() -> tuple[bytes, str]:
    """Serialized exposition payload + content type for the /metrics route."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "AGREEMENT_RATE",
    "EVALUATION_SECONDS",
    "KG_SIGNATURE_VERIFIED",
    "LAST_TELEMETRY_TS",
    "LEDGER_SEQUENCE_GAPS",
    "REGISTRY",
    "RUNTIME_INFO",
    "VERDICTS",
    "render",
]
