"""Tests for the v3 verdict envelope.

Enforces spec v3.0 §4 constraints: closed five-verdict taxonomy,
required fields, sha256: hash prefix pattern, JSON round-trip,
verifier status enumeration.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from ski_model.v3 import (
    FormalizableAssertion,
    KGCitation,
    KGCitationRole,
    ModelProvenance,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)

_VALID_HASH = "sha256:" + "a" * 64


def _minimal_envelope_payload() -> Dict[str, Any]:
    return {
        "verdict": "CLEAR",
        "reasoning": "All applicable obligations evaluated; no breach detected.",
        "kg_citations": [
            {"node_id": "energy.so2.lte_100ppm", "version": "v3demo-0005", "role": "obligation"}
        ],
        "formalizable_assertions": [
            {
                "predicate": "must_not_exceed",
                "metric": "so2_ppm",
                "value": 100,
                "observed": 87,
                "satisfied": True,
                "obligation_id": "energy.so2.lte_100ppm",
            }
        ],
        "verifier_result": {"status": "AGREED", "checked_assertions": 1, "divergences": []},
        "model_provenance": {
            "model_weight_hash": _VALID_HASH,
            "kg_version_hash": _VALID_HASH,
            "prompt_template_id": "ski.v3.evaluate.1",
            "prompt_template_hash": _VALID_HASH,
            "decoder_seed": 0,
            "structured_grammar_hash": _VALID_HASH,
        },
        "transcript_ref": "ledger:tenant.demo/seq:1",
    }


# ---- Verdict taxonomy (§4.1) ----


class TestVerdictTaxonomy:
    def test_five_and_only_five_verdicts(self) -> None:
        assert {v.value for v in V3Verdict} == {
            "CLEAR",
            "FLAG",
            "NULL_UNMAPPED",
            "NULL_STALE",
            "DISCRETIONARY",
        }

    def test_unknown_verdict_is_rejected(self) -> None:
        payload = _minimal_envelope_payload()
        payload["verdict"] = "MAYBE"
        with pytest.raises(ValidationError):
            V3VerdictEnvelope.model_validate(payload)


# ---- Verifier status (§4.5) ----


class TestVerifierStatus:
    def test_four_status_values_per_spec(self) -> None:
        assert {s.value for s in VerifierStatus} == {
            "AGREED",
            "LLM_CONTRADICTION",
            "NEURO_SYMBOLIC_DIVERGENCE",
            "UNVERIFIABLE",
        }

    def test_unknown_status_is_rejected(self) -> None:
        payload = _minimal_envelope_payload()
        payload["verifier_result"]["status"] = "INDECISIVE"
        with pytest.raises(ValidationError):
            V3VerdictEnvelope.model_validate(payload)


# ---- KG citation roles (§4.3) ----


class TestKGCitationRole:
    def test_five_roles_per_spec(self) -> None:
        assert {r.value for r in KGCitationRole} == {
            "obligation",
            "definition_resolved",
            "exemption_considered",
            "precedent_referenced",
            "jurisdiction_matched",
        }

    def test_unknown_role_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            KGCitation.model_validate({"node_id": "x", "version": "v1", "role": "irrelevant"})


# ---- Model provenance (§4.6) ----


class TestModelProvenance:
    def test_all_six_required_fields_present(self) -> None:
        ModelProvenance.model_validate(
            {
                "model_weight_hash": _VALID_HASH,
                "kg_version_hash": _VALID_HASH,
                "prompt_template_id": "ski.v3.evaluate.1",
                "prompt_template_hash": _VALID_HASH,
                "decoder_seed": 0,
                "structured_grammar_hash": _VALID_HASH,
            }
        )

    @pytest.mark.parametrize(
        "field",
        [
            "model_weight_hash",
            "kg_version_hash",
            "prompt_template_id",
            "prompt_template_hash",
            "decoder_seed",
            "structured_grammar_hash",
        ],
    )
    def test_each_field_is_required(self, field: str) -> None:
        payload = {
            "model_weight_hash": _VALID_HASH,
            "kg_version_hash": _VALID_HASH,
            "prompt_template_id": "ski.v3.evaluate.1",
            "prompt_template_hash": _VALID_HASH,
            "decoder_seed": 0,
            "structured_grammar_hash": _VALID_HASH,
        }
        payload.pop(field)
        with pytest.raises(ValidationError):
            ModelProvenance.model_validate(payload)

    def test_hash_must_have_sha256_prefix(self) -> None:
        payload = {
            "model_weight_hash": "md5:abc",
            "kg_version_hash": _VALID_HASH,
            "prompt_template_id": "ski.v3.evaluate.1",
            "prompt_template_hash": _VALID_HASH,
            "decoder_seed": 0,
            "structured_grammar_hash": _VALID_HASH,
        }
        with pytest.raises(ValidationError):
            ModelProvenance.model_validate(payload)

    def test_negative_decoder_seed_is_rejected(self) -> None:
        payload = {
            "model_weight_hash": _VALID_HASH,
            "kg_version_hash": _VALID_HASH,
            "prompt_template_id": "ski.v3.evaluate.1",
            "prompt_template_hash": _VALID_HASH,
            "decoder_seed": -1,
            "structured_grammar_hash": _VALID_HASH,
        }
        with pytest.raises(ValidationError):
            ModelProvenance.model_validate(payload)


# ---- Envelope shape (§4.2) ----


class TestEnvelopeShape:
    def test_minimal_envelope_validates(self) -> None:
        env = V3VerdictEnvelope.model_validate(_minimal_envelope_payload())
        assert env.verdict == "CLEAR"
        assert env.reasoning.startswith("All applicable")
        assert len(env.kg_citations) == 1
        assert len(env.formalizable_assertions) == 1
        assert env.verifier_result.status == "AGREED"
        assert env.transcript_ref.startswith("ledger:")

    def test_missing_required_field_is_rejected(self) -> None:
        payload = _minimal_envelope_payload()
        del payload["transcript_ref"]
        with pytest.raises(ValidationError):
            V3VerdictEnvelope.model_validate(payload)

    def test_extra_field_at_top_level_is_rejected(self) -> None:
        payload = _minimal_envelope_payload()
        payload["confidence_score"] = 0.95
        with pytest.raises(ValidationError):
            V3VerdictEnvelope.model_validate(payload)

    def test_empty_assertions_array_is_permitted(self) -> None:
        payload = _minimal_envelope_payload()
        payload["formalizable_assertions"] = []
        payload["verifier_result"] = {
            "status": "UNVERIFIABLE",
            "checked_assertions": 0,
            "divergences": ["Rule has no formalizable subset."],
        }
        env = V3VerdictEnvelope.model_validate(payload)
        assert env.formalizable_assertions == []
        assert env.verifier_result.status == "UNVERIFIABLE"

    def test_fast_path_marker_is_optional(self) -> None:
        env = V3VerdictEnvelope.model_validate(_minimal_envelope_payload())
        assert env.verdict_path is None

        payload = _minimal_envelope_payload()
        payload["verdict_path"] = "fast"
        fast = V3VerdictEnvelope.model_validate(payload)
        assert fast.verdict_path == "fast"


# ---- JSON round-trip ----


class TestRoundTrip:
    def test_envelope_round_trips_through_json(self) -> None:
        original = V3VerdictEnvelope.model_validate(_minimal_envelope_payload())
        dumped = original.model_dump(mode="json")
        text = json.dumps(dumped, sort_keys=True)
        reparsed = V3VerdictEnvelope.model_validate(json.loads(text))
        assert reparsed.model_dump(mode="json") == dumped

    def test_unverifiable_envelope_round_trips(self) -> None:
        payload = _minimal_envelope_payload()
        payload["verdict"] = "DISCRETIONARY"
        payload["formalizable_assertions"] = []
        payload["verifier_result"] = {
            "status": "UNVERIFIABLE",
            "checked_assertions": 0,
            "divergences": ["This rule requires qualified human judgment."],
        }
        env = V3VerdictEnvelope.model_validate(payload)
        text = env.model_dump_json()
        reparsed = V3VerdictEnvelope.model_validate(json.loads(text))
        assert reparsed.verdict == "DISCRETIONARY"
        assert reparsed.verifier_result.status == "UNVERIFIABLE"


# ---- Formalizable assertion shape (§4.4) ----


class TestFormalizableAssertion:
    def test_minimal_assertion_validates(self) -> None:
        FormalizableAssertion.model_validate(
            {
                "predicate": "must_not_exceed",
                "metric": "so2_ppm",
                "value": 100,
                "observed": 87,
                "satisfied": True,
                "obligation_id": "ob.x",
            }
        )

    def test_obligation_id_is_required(self) -> None:
        with pytest.raises(ValidationError):
            FormalizableAssertion.model_validate(
                {
                    "predicate": "must_not_exceed",
                    "metric": "so2_ppm",
                    "value": 100,
                    "observed": 87,
                    "satisfied": True,
                }
            )

    def test_range_operand_is_permitted(self) -> None:
        env = FormalizableAssertion.model_validate(
            {
                "predicate": "must_be_within",
                "metric": "ph",
                "value": [6.0, 8.5],
                "observed": 7.2,
                "satisfied": True,
                "obligation_id": "ob.ph",
            }
        )
        assert env.value == [6.0, 8.5]
