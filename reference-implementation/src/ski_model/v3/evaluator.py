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

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from pydantic import ValidationError as PydanticValidationError

from .envelope import (
    FormalizableAssertion,
    KGCitation,
    ModelProvenance,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)
from .policies import apply_risk_policy
from .signing import TranscriptSigner
from .transcript import LLMTranscript, hash_pair, signing_message
from .verifier import BufferLike, SymbolicVerifier

logger = logging.getLogger(__name__)


# ---- Prompt template + grammar -------------------------------------------------

PROMPT_TEMPLATE_ID = "ski.v3.evaluate.5"
"""Stable identifier for the v3 evaluation prompt. Bump on every prompt edit."""


PROMPT_TEMPLATE = """\
You are a regulatory compliance evaluator for the SKI Framework v3.

You receive:
  1. A measurement record (the data being evaluated).
  2. A Knowledge Graph snapshot of applicable regulatory obligations,
     scoped to the measurement's jurisdiction and effective date.

Produce a structured verdict envelope per the schema below.

RULES (non-negotiable):
  * Cite ONLY node ids from this exact list - any other id voids your
    verdict: {valid_node_ids}
  * Copy node ids character-for-character. Do not invent, shorten, or
    rename them.
  * Every formalizable_assertion you emit must reference a specific
    KG obligation by ID. The Symbolic Verifier mechanically checks them.
  * In assertions, "value" and "observed" are BARE scalars (or, for
    range obligations like must_be_within, "value" is the two-element
    array [min, max]). NEVER objects: write 7.2, not {{"value": 7.2}};
    write [6.5, 8.5], not {{"min": 6.5, "max": 8.5}}.
  * The KG snapshot is ALREADY scoped: every obligation in it is in
    force for this measurement's jurisdiction and date. Do NOT re-check
    jurisdictions or effective dates - the framework did that. A past
    effective_date means the rule IS in force.
  * An obligation MAPS to the measurement when its "metric" field
    equals a key in MEASUREMENT. If it maps, you MUST evaluate it and
    emit a formalizable_assertion - never NULL_UNMAPPED.
  * Verdict MUST be one of: CLEAR, FLAG, NULL_UNMAPPED, NULL_STALE,
    DISCRETIONARY.
  * NULL_UNMAPPED: NO obligation's "metric" matches ANY measurement key.
  * NULL_STALE: the telemetry itself is stale or missing (silent
    sensor). It is NEVER about rule dates.
  * FLAG: a mapped obligation is breached. Compute carefully, digit by
    digit, before setting "satisfied":
      - must_not_exceed: satisfied iff observed <= value. EQUAL IS
        SATISFIED: observed 100 against value 100 is CLEAR, not FLAG.
      - must_be_at_least: satisfied iff observed >= value.
      - must_be_within [lo, hi]: satisfied iff lo <= observed AND
        observed <= hi. Boundaries are inclusive. 5.4 is NOT within
        [6.0, 8.5]; 8.6 is NOT within [6.0, 8.5].
  * "observed" MUST be copied exactly from MEASUREMENT - the verifier
    cross-checks it against the record and rejects invented readings.
  * CLEAR: every mapped obligation is satisfied.
  * DISCRETIONARY: a mapped obligation requires qualified human
    judgment that numbers alone cannot settle.

  Worked example: MEASUREMENT {{"so2_ppm": 85}}; obligation
  {{"id": "x.so2", "metric": "so2_ppm", "predicate": "must_not_exceed",
  "value": 100}} -> metric matches, 85 <= 100 -> verdict CLEAR, one
  assertion: {{"predicate": "must_not_exceed", "metric": "so2_ppm",
  "value": 100, "observed": 85, "satisfied": true,
  "obligation_id": "x.so2"}}.

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
                    "value": {"type": ["number", "string", "array", "null"]},
                    "observed": {"type": ["number", "string", "null"]},
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
        if (
            predicate == "must_not_exceed"
            and isinstance(observed, (int, float))
            and isinstance(limit, (int, float))
        ):
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
class EvaluationResult:
    """Output of :meth:`V3Evaluator.aevaluate` — envelope + signed transcript.

    The envelope is what the API returns to the caller; the transcript is
    what the audit ledger records. They share a ``transcript_ref`` so an
    auditor can join them.

    ``transcript`` is ``Optional`` so deployments without an audit ledger
    (e.g. integration tests) can still exercise the evaluator. When the
    evaluator is constructed without a :class:`TranscriptSigner` no
    transcript is produced.
    """

    envelope: V3VerdictEnvelope
    transcript: Optional[LLMTranscript]


@dataclass
class V3Evaluator:
    """KG-grounded LLM evaluator producing :class:`EvaluationResult`.

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
    verifier:
        The :class:`SymbolicVerifier` used to mechanically cross-check
        the LLM's formalizable assertions. Default: a fresh stateless
        :class:`SymbolicVerifier` instance.
    signer:
        Optional :class:`TranscriptSigner` for producing signed
        :class:`LLMTranscript` records. When ``None``, the evaluator
        still produces an envelope but :attr:`EvaluationResult.transcript`
        is ``None``. Production deployments MUST configure a signer per
        spec §6.3.
    """

    llm: V3LLMBackend
    kg_version_hash: str
    decoder_seed: int = 0
    verifier: SymbolicVerifier = field(default_factory=SymbolicVerifier)
    signer: Optional[TranscriptSigner] = None

    async def aevaluate(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        transcript_ref: Optional[str] = None,
        risk_tier: str = "standard",
        subject: Optional[str] = None,
        as_of: Optional[datetime] = None,
        buffer: Optional[BufferLike] = None,
    ) -> V3VerdictEnvelope:
        """Produce just the verdict envelope.

        Convenience wrapper around :meth:`aevaluate_with_transcript` for
        callers that don't need the signed transcript (tests, simple
        clients). Production callers that write to the audit ledger
        should use :meth:`aevaluate_with_transcript` and persist both
        sides per spec §6.
        """
        result = await self.aevaluate_with_transcript(
            measurement=measurement,
            kg_snapshot=kg_snapshot,
            transcript_ref=transcript_ref,
            risk_tier=risk_tier,
            subject=subject,
            as_of=as_of,
            buffer=buffer,
        )
        return result.envelope

    async def aevaluate_with_transcript(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        transcript_ref: Optional[str] = None,
        risk_tier: str = "standard",
        subject: Optional[str] = None,
        as_of: Optional[datetime] = None,
        buffer: Optional[BufferLike] = None,
    ) -> EvaluationResult:
        """Produce an :class:`EvaluationResult` from a measurement + KG snapshot.

        Flow:
          1. Render the canonical prompt from the spec PROMPT_TEMPLATE.
          2. Call the LLM backend.
          3. Validate citations against the snapshot. Citing a node not in
             the snapshot forces verdict to ``NULL_UNMAPPED`` and verifier
             status ``UNVERIFIABLE``.
          4. Mechanically verify each formalizable assertion via
             :class:`SymbolicVerifier`; stamp the real
             :class:`VerifierResult` on the envelope.
          5. Apply the risk-tier policy per spec §5.4.
          6. If a signer is configured, sign the (canonical prompt,
             canonical response) pair and emit an :class:`LLMTranscript`.
        """
        started_at = datetime.now(timezone.utc)
        canonical_prompt = self._render_canonical_prompt(measurement, kg_snapshot)
        raw = await self.llm.evaluate(
            measurement=measurement,
            kg_snapshot=kg_snapshot,
            seed=self.decoder_seed,
        )
        completed_at = datetime.now(timezone.utc)

        # Build the transcript first so its id is available for transcript_ref.
        transcript = self._build_transcript(
            canonical_prompt=canonical_prompt,
            response=raw,
            started_at=started_at,
            completed_at=completed_at,
        )
        effective_transcript_ref = (
            transcript_ref
            if transcript_ref is not None
            else f"transcript:{transcript.transcript_id}"
            if transcript is not None
            else "transcript:unsigned"
        )

        # Citation enforcement: every cited node MUST exist in the snapshot.
        valid_node_ids = {
            ob["id"] for ob in kg_snapshot.get("obligations", []) if isinstance(ob, dict) and "id" in ob
        }
        valid_node_ids.update(
            d["id"] for d in kg_snapshot.get("definitions", []) if isinstance(d, dict) and "id" in d
        )

        cited_node_ids = [c.get("node_id") for c in raw.get("kg_citations", [])]
        invalid = [n for n in cited_node_ids if n not in valid_node_ids]

        if invalid:
            logger.warning(
                "Citation enforcement violation: LLM cited nonexistent nodes %r. "
                "Forcing verdict to NULL_UNMAPPED.",
                invalid,
            )
            envelope = V3VerdictEnvelope(
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
                transcript_ref=effective_transcript_ref,
            )
            return EvaluationResult(envelope=envelope, transcript=transcript)

        # Build envelope from LLM output, then have the Symbolic Verifier
        # mechanically cross-check the formalizable assertions and stamp the
        # real VerifierResult. Async averify handles stateful predicates
        # against the optional telemetry buffer; falls back to identical
        # behaviour to verify() when no buffer / subject / as_of provided.
        # Output-contract guard: a response that parsed as JSON can still
        # violate the envelope schema (e.g. a model emitting
        # {"min": 6.5, "max": 8.5} where the grammar wants [6.5, 8.5], or
        # {"value": 7.2} where it wants 7.2 — found by the first real-model
        # eval runs). A misbehaving model must NEVER crash the evaluator:
        # contract violations degrade to DISCRETIONARY with zero checkable
        # assertions, the same way malformed JSON does at the backend, and
        # the violation is recorded for the auditor.
        try:
            llm_verdict = V3Verdict(raw["verdict"])
            reasoning_text: str = raw["reasoning"]
            assertions = [FormalizableAssertion(**a) for a in raw.get("formalizable_assertions", [])]
            parsed_citations = [KGCitation(**c) for c in raw.get("kg_citations", [])]
        except (PydanticValidationError, KeyError, TypeError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Output-contract violation from backend %s: %s. Degrading to DISCRETIONARY.",
                self.llm.name,
                detail[:300],
            )
            envelope = V3VerdictEnvelope(
                verdict=V3Verdict.DISCRETIONARY,
                reasoning=(
                    "Output-contract violation: the model's response parsed as JSON "
                    "but did not conform to the verdict-envelope schema. The verdict "
                    "is routed to human review; no assertions were checkable. "
                    f"Violation: {detail[:300]}"
                ),
                kg_citations=[],
                formalizable_assertions=[],
                verifier_result=VerifierResult(
                    status=VerifierStatus.UNVERIFIABLE,
                    checked_assertions=0,
                    divergences=[f"output_contract: {detail[:300]}"],
                ),
                model_provenance=self._build_provenance(),
                transcript_ref=effective_transcript_ref,
            )
            return EvaluationResult(envelope=envelope, transcript=transcript)

        # Taxonomy guard (spec §4.1): CLEAR asserts *verified* satisfaction.
        # A CLEAR with zero formalizable assertions is an unverifiable
        # compliance claim — the exact "trust me" verdict the framework
        # forbids. Found by eval run 5: the model reasoned "nothing maps"
        # and then said CLEAR anyway. Deterministic remap, recorded in
        # envelope.notes for the auditor:
        #   - no citations either  -> the model itself claims nothing
        #     applies: NULL_UNMAPPED (coverage gap, never silent green).
        #   - citations but no assertions -> something applies but nothing
        #     is checkable: DISCRETIONARY (human review).
        taxonomy_notes: List[str] = []
        if llm_verdict == V3Verdict.CLEAR and not assertions:
            remapped = V3Verdict.NULL_UNMAPPED if not parsed_citations else V3Verdict.DISCRETIONARY
            taxonomy_notes.append(
                f"taxonomy_guard: LLM verdict CLEAR carried no formalizable assertions "
                f"({'no citations' if not parsed_citations else 'citations present'}); "
                f"remapped to {remapped.value} per spec §4.1 — CLEAR requires verified satisfaction."
            )
            logger.warning(taxonomy_notes[-1])
            llm_verdict = remapped

        obligations_index = {
            ob["id"]: ob for ob in kg_snapshot.get("obligations", []) if isinstance(ob, dict) and "id" in ob
        }
        verifier_result = await self.verifier.averify(
            assertions,
            llm_verdict=llm_verdict,
            subject=subject,
            as_of=as_of,
            buffer=buffer,
            measurement=measurement,
            obligations=obligations_index,
        )

        envelope = V3VerdictEnvelope(
            verdict=llm_verdict,
            reasoning=reasoning_text,
            kg_citations=parsed_citations,
            formalizable_assertions=assertions,
            verifier_result=verifier_result,
            model_provenance=self._build_provenance(),
            transcript_ref=effective_transcript_ref,
            notes=taxonomy_notes,
        )

        # Risk-tier policy may downgrade verdict to DISCRETIONARY and / or
        # flag human attestation as required, per spec §5.4.
        final_envelope = apply_risk_policy(envelope, risk_tier=risk_tier)
        return EvaluationResult(envelope=final_envelope, transcript=transcript)

    def _build_provenance(self) -> ModelProvenance:
        return ModelProvenance(
            model_weight_hash=self.llm.model_weight_hash,
            kg_version_hash=self.kg_version_hash,
            prompt_template_id=self.llm.prompt_template_id,
            prompt_template_hash=self.llm.prompt_template_hash,
            decoder_seed=self.decoder_seed,
            structured_grammar_hash=self.llm.structured_grammar_hash,
        )

    def _render_canonical_prompt(self, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any]) -> str:
        """Render PROMPT_TEMPLATE with canonical JSON bindings.

        The result is the *framework-defined* canonical prompt for this
        evaluation. Real LLM backends may format the prompt differently
        internally (chat templates, system messages, etc.) — that is their
        observability concern, not the audit contract. What we record is
        the framework's view of what was asked.
        """
        valid_ids = sorted(
            {
                n["id"]
                for key in ("obligations", "definitions")
                for n in kg_snapshot.get(key, [])
                if isinstance(n, dict) and "id" in n
            }
        )
        return PROMPT_TEMPLATE.format(
            valid_node_ids=json.dumps(valid_ids, ensure_ascii=False),
            measurement_json=json.dumps(
                measurement, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
            kg_snapshot_json=json.dumps(
                kg_snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        )

    def _build_transcript(
        self,
        *,
        canonical_prompt: str,
        response: Dict[str, Any],
        started_at: datetime,
        completed_at: datetime,
    ) -> Optional[LLMTranscript]:
        """Build and sign an :class:`LLMTranscript` if a signer is configured.

        Returns ``None`` when no :class:`TranscriptSigner` is attached;
        the evaluator still produces an envelope but transcripts cannot
        be audited.
        """
        if self.signer is None:
            return None

        req_hash, resp_hash = hash_pair(request_text=canonical_prompt, response=response)
        message = signing_message(request_hash=req_hash, response_hash=resp_hash)
        signature_hex = self.signer.sign(message)

        return LLMTranscript(
            transcript_id=str(uuid.uuid4()),
            request_canonical=canonical_prompt,
            request_hash=req_hash,
            response_canonical=response,
            response_hash=resp_hash,
            signature_hex=signature_hex,
            signing_key_id=self.signer.key_id,
            backend_name=self.llm.name,
            backend_metadata={},
            started_at=started_at,
            completed_at=completed_at,
        )


__all__ = [
    "PROMPT_TEMPLATE",
    "PROMPT_TEMPLATE_ID",
    "RESPONSE_GRAMMAR",
    "FakeLLM",
    "V3Evaluator",
    "V3LLMBackend",
]
