"""The flat-shape Knowledge Graph obligation — the wire object the runtime loads.

The reference runtime does not load the rich node/edge KG of spec v3.0 §3;
it loads a *flat* shape in which ``kg["rules"]`` is a list of obligation
objects and :meth:`ski_model.kg_loader.KnowledgeGraph.scope_to` emits those
same objects under ``snapshot["obligations"]`` (see spec §5.1 and the C5
finding in the gold-standard review). The runtime reads these objects as
plain ``dict``s and never had a schema; this model is that missing contract,
written from the field accesses in ``ski_model.v3.evaluator`` and
``ski_model.kg_loader``.

It is additive and used only to *generate* the published JSON Schema
(``spec/contracts/schemas/kg_obligation.schema.json``). The runtime is not
changed to validate against it in this slice.

Field provenance (where the runtime reads each field):

* ``id``, ``metric``, ``predicate``, ``value`` — ``evaluator._missing_telemetry``
  and the LLM-grammar fragment ``evaluator.V3_ENVELOPE_SCHEMA``.
* ``unit`` — carried on unit-bearing obligations and readings.
* ``window_seconds`` / ``requires_recent_within_seconds`` — stateful
  (windowed / recency) predicates.
* ``risk_tier`` — consumed by ``v3.policies.risk_tier.RiskTierGovernor``;
  an unknown or missing tier resolves to ``tier-1`` (strictest) at runtime.
* ``effective_date`` / ``sunset_date`` / ``jurisdiction`` — consumed by
  ``kg_loader._rule_is_in_scope`` when scoping the KG to a measurement.

The runtime tolerates obligations that omit ``metric`` or ``predicate``
(it reads them with ``.get(...)`` and defaults ``predicate`` to
``"must_not_exceed"``). This contract requires them, because an obligation
the Symbolic Verifier can mechanically check must name both. That gap is a
spec/model divergence recorded for RFC 0004.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["KGObligation"]


class KGObligation(BaseModel):
    """One obligation in the flat KG the reference runtime loads.

    ``predicate`` is left an open string, exactly as the runtime's own
    structured-output grammar declares it (``{"type": "string"}``), so a
    KG carrying an implementation-extension predicate (e.g.
    ``must_average_within``) is still valid. The closed base enumeration is
    spec §3.3 (``ObligationType`` in ``kg_validator.models``).

    Unknown members are permitted (``additionalProperties`` stays open): the
    KG format is extensible and the runtime ignores members it does not read.
    """

    # Permissive, matching the runtime (it reads obligations as dicts and
    # ignores unknown keys). extra="ignore" is pydantic's default; stated
    # here so the generated schema's open additionalProperties is intentional.
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Stable obligation identifier, unique within the KG.")
    metric: str = Field(
        ...,
        description="Dotted-path identifier into the measurement record's measurement object.",
    )
    predicate: str = Field(
        ...,
        description=(
            "The obligation type, drawn from spec §3.3's closed enumeration plus the "
            "runtime extensions (e.g. 'must_not_exceed', 'must_be_at_least', "
            "'must_average_within'). Left an open string to match the runtime grammar."
        ),
    )
    value: Union[float, int, str, List[Any], None] = Field(
        default=None,
        description="The operand the predicate is evaluated against (scalar, list, or null).",
    )
    unit: Optional[str] = Field(
        default=None,
        description="Unit of 'value' and of the measured reading, when the obligation is unit-bearing.",
    )
    window_seconds: Optional[int] = Field(
        default=None,
        ge=1,
        description="Window length in seconds for a windowed predicate (e.g. a 24h rolling average).",
    )
    requires_recent_within_seconds: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum age in seconds of an acceptable reading for a recency obligation.",
    )
    risk_tier: Optional[str] = Field(
        default=None,
        description=(
            "Declared risk tier ('tier-1' strictest .. 'tier-3'). A missing or unrecognised "
            "tier resolves to 'tier-1' at runtime (fail-safe). Never a trust input the LLM controls."
        ),
    )
    effective_date: Optional[str] = Field(
        default=None,
        description="ISO-8601 date or datetime; the obligation is out of scope before this instant.",
    )
    sunset_date: Optional[str] = Field(
        default=None,
        description="ISO-8601 date or datetime; the obligation is out of scope after this instant.",
    )
    jurisdiction: Optional[str] = Field(
        default=None,
        description=(
            "Jurisdiction the obligation applies to, or a universal sentinel "
            "('global', '*', ''). Absent means universal."
        ),
    )
    summary: Optional[str] = Field(
        default=None,
        description="Human-readable summary of the obligation, for transcripts and review UIs.",
    )
