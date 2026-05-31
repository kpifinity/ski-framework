"""KG-grounded LLM evaluator — produces V3VerdictEnvelope per spec v3.0 §5.

This is the primary inference path in the v3 architecture. The LLM consumes
a measurement record and a KG snapshot scoped to the measurement's
jurisdictional context, and emits a structured verdict envelope.

Citations are validated against the KG snapshot before the envelope is
returned: citing a node that is not in the snapshot forces verdict to
NULL_UNMAPPED with verifier status UNVERIFIABLE. This is the anti-
hallucination floor of the architecture — the LLM cannot invent obligations.

PR 10b ships the evaluator and a deterministic FakeLLM backend. PR 10c
wires the Symbolic Verifier so VerifierResult is populated with real
agreement / divergence data. Until then the evaluator stamps
``VerifierResult(status=UNVERIFIABLE, checked_assertions=0)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from .envelope import (
    FormalizableAssertion,
    KGCitation,
    ModelProvenance,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)

logger = logging.getLogger(__name__)


# ---- Prompt template + grammar -------------------------------------------------

PROMPT_TEMPLATE_ID = "ski.v3.evaluate.1"
"""Stable identifier for the v3 evaluation prompt. Bump on every prompt edit."""


PROMPT_TEMPLATE = """\
You are a regulatory compliance evaluator for the SKI Framework v3.

You receive:
  1. A measurement record (the data being evaluated).
  2. A Knowledge Graph snapshot of applicable regulatory obligations,
     scoped to the measurement's jurisdiction and effective date.

Produce a structured verdict envelope per the schema below.

RULES (non-negotiable):
  * Cite ONLY KG nodes that appear in the snapshot. Citing a node not in
    the snapshot causes your verdict to be discarded.
  * Every formalizable_assertion you emit must reference a specific
    KG obligation by ID. The Symbolic Verifier mechanically checks them.
  * Verdict MUST be one of: CLEAR, FLAG, NULL_UNMAPPED, NULL_STALE,
    DISCRETIONARY.
  * No obligation maps to the measurement: NULL_UNMAPPED.
  * Obligation maps but its effective_date has passed: NULL_STALE.
  * Clear breach of an applicable obligation: FLAG.
  * Clearly compliant: CLEAR.
  * Obligation requires qualified human judgment: DISCRETIONARY.

OUTPUT (strict JSON, no other prose):
  {{
    "verdict": "<one of the five>",
    "reasoning": "<one paragraph>",
    "kg_citations": [
      {{"node_id": "...", "version": "...",
        "role": "obligation|definition_resolved|exemption_considered|precedent_referenced|jurisdiction_matched"}}
    ],
    "formalizable_assertions": [
      {{"predicate": "...", "metric": "...", "value": ...,
        "observed": ..., "satisfied": true|false, "obligation_id": "..."}}
    ]
  }}

MEASUREMENT:
{measurement_json}

KG SNAPSHOT:
{kg_snapshot_json}
"""


RESPONSE_GRAMMAR: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reasoning", "kg_citations", "formalizable_assertions"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [
                "CLEAR",
                "FLAG",
                "NULL_UNMAPPED",
                "NULL_STALE",
                "DISCRETIONARY",
            ],
        },
        "reasoning": {"type": "string"},
        "kg_citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node_id", "version", "role"],
                "properties": {
                    "node_id": {"type": "string"},
                    "version": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": [
                            "obligation",
                            "definition_resolved",
                            "exemption_considered",
                            "precedent_referenced",
                            "jurisdiction_matched",
                        ],
                    },
                },
            },
        },
        "formalizable_assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "predicate",
                    "metric",
                    "satisfied",
                    "obligation_id",
                ],
                "properties": {
                    "predicate": {"type": "string"},
                    "metric": {"type": "string"},
                    "value": {},
                    "observed": {},
                    "satisfied": {"type": "boolean"},
                    "obligation_id": {"type": "string"},
                },
            },
        },
    },
}
"""JSON schema fragment that real LLM backends pass to their structured-output guards."""


# ---- LLM backend protocol -----------------------------------------------------


class V3LLMBackend(Protocol):
    """Every v3 LLM backend implements this protocol.

    PR 10b ships only :class:`FakeLLM`. Real backends (Ollama, vLLM, etc.)
    land in a follow-up PR with their own secret-handling and rate-limit
    stories.
    """

    name: str

    @property
    def model_weight_hash(self) -> str: ...
    @property
    def prompt_template_id(self) -> str: ...
    @property
    def prompt_template_hash(self) -> str: ...
    @property
    def structured_grammar_hash(self) -> str: ...

    async def evaluate(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        seed: int,
    ) -> Dict[str, Any]:
        """Return raw structured output matching :data:`RESPONSE_GRAMMAR`."""
        ...


# ---- FakeLLM backend (deterministic; used by tests + CI) ----------------------


class FakeLLM:
    """Deterministic backend for tests and CI.

    Pattern-matches the measurement against the KG snapshot's obligations.
    No network. No secrets. Useful as a CI default so the evaluator's
    plumbing can be exercised end-to-end without a real model.

    The fake honours the same provenance contract as a real backend:
    callers receive valid sha256-prefixed hashes for every provenance
    field, so the envelope round-trips through validation cleanly.
    """

    name = "fake-llm"

    def __init__(
        self,
        *,
        model_weight_hash: str = "sha256:" + "f" * 64,
        prompt_template_hash: str = "sha256:" + "1" * 64,
        structured_grammar_hash: str = "sha256:" + "2" * 64,
    ) -> None:
        self._model_weight_hash = model_weight_hash
        self._prompt_template_hash = prompt_template_hash
        self._structured_grammar_hash = structured_grammar_hash

    @property
    def model_weight_hash(self) -> str:
        return self._model_weight_hash

    @property
    def prompt_template_id(self) -> str:
        return PROMPT_TEMPLATE_ID

    @property
    def prompt_template_hash(self) -> str:
        return self._prompt_template_hash

    @property
    def structured_grammar_hash(self) -> str:
        return self._structured_grammar_hash

    async def evaluate(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        seed: int,
    ) -> Dict[str, Any]:
        obligations: List[Dict[str, Any]] = kg_snapshot.get("obligations", [])
        if not obligations:
            return {
                "verdict": "NULL_UNMAPPED",
                "reasoning": "No applicable obligation in the provided KG snapshot.",
                "kg_citations": [],
                "formalizable_assertions": [],
            }

        # Pick the first obligation whose metric is present in the measurement.
        matched: Optional[Dict[str, Any]] = None
        for ob in obligations:
            metric = ob.get("metric")
            if metric and metric in measurement:
                matched = ob
                break

        if matched is None:
            return {
                "verdict": "NULL_UNMAPPED",
                "reasoning": "No obligation metric matches the measurement keys.",
                "kg_citations": [],
                "formalizable_assertions": [],
            }

        metric_name: str = matched["metric"]
        observed: Any = measurement[metric_name]
        predicate: str = matched.get("predicate", "must_not_exceed")
        limit: Any = matched.get("value")

        satisfied = True
        if predicate == "must_not_exceed" and isinstance(observed, (int, float)) and isinstance(limit, (int, float)):
            satisfied = observed <= limit
        elif (
            predicate == "must_be_within"
            and isinstance(limit, list)
            and len(limit) == 2
            and isinstance(observed, (int, float))
            and all(isinstance(b, (int, float)) for b in limit)
        ):
            satisfied = limit[0] <= observed <= limit[1]

        verdict = "CLEAR" if satisfied else "FLAG"
        reasoning = (
            f"Obligation {matched['id']} requires {predicate} {limit!r}. "
            f"Observed {metric_name}={observed!r}. "
            f"{'Within limit.' if satisfied else 'Breach.'}"
        )

        return {
            "verdict": verdict,
            "reasoning": reasoning,
            "kg_citations": [
                {
                    "node_id": matched["id"],
                    "version": kg_snapshot.get("version", "unknown"),
                    "role": "obligation",
                }
            ],
            "formalizable_assertions": [
                {
                    "predicate": predicate,
                    "metric": metric_name,
                    "value": limit,
                    "observed": observed,
                    "satisfied": satisfied,
                    "obligation_id": matched["id"],
                }
            ],
        }


# ---- Evaluator ----------------------------------------------------------------


@dataclass
class V3Evaluator:
    """KG-grounded LLM evaluator producing :class:`V3VerdictEnvelope`.

    Parameters
    ----------
    llm:
        A :class:`V3LLMBackend` implementation. PR 10b ships only
        :class:`FakeLLM`; real backends land in a follow-up PR.
    kg_version_hash:
        sha256-prefixed hash of the KG snapshot version this evaluator is
        bound to. Recorded in :class:`ModelProvenance` for replay.
    decoder_seed:
        Deterministic decoding seed. Default 0.
    """

    llm: V3LLMBackend
    kg_version_hash: str
    decoder_seed: int = 0

    async def aevaluate(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        transcript_ref: str,
        risk_tier: str = "standard",
    ) -> V3VerdictEnvelope:
        """Produce a :class:`V3VerdictEnvelope` from a measurement + KG snapshot.

        Flow:
          1. Call the LLM with the measurement and KG snapshot.
          2. Validate citations against the snapshot.
          3. If any citation references a node not in the snapshot, force
             verdict to ``NULL_UNMAPPED`` and verifier status
             ``UNVERIFIABLE``.
          4. Build the envelope with full :class:`ModelProvenance`.

        PR 10b emits ``VerifierResult(status=UNVERIFIABLE, checked_assertions=0)``
        because the Symbolic Verifier wrapper is not wired yet — that is
        PR 10c.
        """
        raw = await self.llm.evaluate(
            measurement=measurement,
            kg_snapshot=kg_snapshot,
            seed=self.decoder_seed,
        )

        # Citation enforcement: every cited node MUST exist in the snapshot.
        valid_node_ids = {
            ob["id"]
            for ob in kg_snapshot.get("obligations", [])
            if isinstance(ob, dict) and "id" in ob
        }
        valid_node_ids.update(
            d["id"]
            for d in kg_snapshot.get("definitions", [])
            if isinstance(d, dict) and "id" in d
        )

        cited_node_ids = [c.get("node_id") for c in raw.get("kg_citations", [])]
        invalid = [n for n in cited_node_ids if n not in valid_node_ids]

        if invalid:
            logger.warning(
                "Citation enforcement violation: LLM cited nonexistent nodes %r. "
                "Forcing verdict to NULL_UNMAPPED.",
                invalid,
            )
            return V3VerdictEnvelope(
                verdict=V3Verdict.NULL_UNMAPPED,
                reasoning=(
                    f"Citation enforcement: LLM cited nodes {invalid!r} that are not "
                    "present in the provided KG snapshot. Original verdict discarded; "
                    "coverage gap logged."
                ),
                kg_citations=[],
                formalizable_assertions=[],
                verifier_result=VerifierResult(
                    status=VerifierStatus.UNVERIFIABLE,
                    checked_assertions=0,
                    divergences=[f"Invalid citation: {n}" for n in invalid],
                ),
                model_provenance=self._build_provenance(),
                transcript_ref=transcript_ref,
            )

        # Build envelope from LLM output.
        envelope = V3VerdictEnvelope(
            verdict=V3Verdict(raw["verdict"]),
            reasoning=raw["reasoning"],
            kg_citations=[KGCitation(**c) for c in raw.get("kg_citations", [])],
            formalizable_assertions=[
                FormalizableAssertion(**a) for a in raw.get("formalizable_assertions", [])
            ],
            verifier_result=VerifierResult(
                status=VerifierStatus.UNVERIFIABLE,
                checked_assertions=0,
                divergences=["PR 10b: Symbolic Verifier not wired (lands in PR 10c)."],
            ),
            model_provenance=self._build_provenance(),
            transcript_ref=transcript_ref,
        )
        return envelope

    def _build_provenance(self) -> ModelProvenance:
        return ModelProvenance(
            model_weight_hash=self.llm.model_weight_hash,
            kg_version_hash=self.kg_version_hash,
            prompt_template_id=self.llm.prompt_template_id,
            prompt_template_hash=self.llm.prompt_template_hash,
            decoder_seed=self.decoder_seed,
            structured_grammar_hash=self.llm.structured_grammar_hash,
        )


__all__ = [
    "FakeLLM",
    "PROMPT_TEMPLATE",
    "PROMPT_TEMPLATE_ID",
    "RESPONSE_GRAMMAR",
    "V3Evaluator",
    "V3LLMBackend",
]
