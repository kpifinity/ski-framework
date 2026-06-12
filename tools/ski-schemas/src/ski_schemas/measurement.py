"""Measurement record — the input shape of ``POST /api/evaluate`` (RFC 0003)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MeasurementRecord(BaseModel):
    """Measurement input for /api/evaluate.

    The v3 evaluator consumes the full measurement; the LLM scopes the KG
    snapshot to the measurement's jurisdiction and effective date. PR 10b
    passes the full KG as the snapshot. Jurisdiction-scoped snapshots are a
    follow-up.
    """

    measurement_id: str = Field(..., description="Stable id for replay correlation.")
    timestamp: str = Field(..., description="ISO-8601 UTC.")
    subject: str = Field(..., description="Subject token (e.g. data source identifier).")
    measurement: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured measurement values keyed by metric name.",
    )
    jurisdiction: Optional[str] = Field(
        default=None,
        description=(
            "Tenant-declared jurisdiction (e.g. 'us-ca', 'eu', 'global'). When set, "
            "the KG is scoped to obligations whose jurisdiction matches or is "
            "universal ('global', '*'). None means 'no restriction' — all rules "
            "effective at the measurement's timestamp are sent to the LLM."
        ),
    )


__all__ = ["MeasurementRecord"]
