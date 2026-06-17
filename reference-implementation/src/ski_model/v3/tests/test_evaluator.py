"""Tests for the v3 KG-grounded LLM evaluator.

These tests use :class:`FakeLLM` so they run without secrets, without
network, and deterministically. They cover:

* Happy-path CLEAR + FLAG verdicts with valid citations.
* Citation enforcement: bogus node ids force NULL_UNMAPPED.
* Deterministic provenance: ModelProvenance is fully populated.
* JSON round-trip from the produced envelope.
* Empty / unmapped KG snapshots.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from ski_model.v3 import (
    PROMPT_TEMPLATE_ID,
    FakeLLM,
    V3Evaluator,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierStatus,
)

_KG_HASH = "sha256:" + "a" * 64


def _kg_snapshot() -> Dict[str, Any]:
    return {
        "version": "v3demo-0007",
        "obligations": [
            {
                "id": "energy.so2.lte_100ppm",
                "metric": "so2_ppm",
                "predicate": "must_not_exceed",
                "value": 100,
            },
            {
                "id": "water.ph.within_6_to_85",
                "metric": "ph",
                "predicate": "must_be_within",
                "value": [6.0, 8.5],
            },
        ],
        "definitions": [{"id": "def.units.ppm"}],
    }


def _evaluator(seed: int = 0) -> V3Evaluator:
    return V3Evaluator(
        llm=FakeLLM(),
        kg_version_hash=_KG_HASH,
        decoder_seed=seed,
    )


# ---- Happy paths --------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_clear_verdict_when_within_limit(self) -> None:
        evaluator = _evaluator()
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 87},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:1",
        )
        assert env.verdict == V3Verdict.CLEAR.value
        assert len(env.kg_citations) == 1
        assert env.kg_citations[0].node_id == "energy.so2.lte_100ppm"
        assert env.kg_citations[0].role == "obligation"
        assert len(env.formalizable_assertions) == 1
        assert env.formalizable_assertions[0].satisfied is True
        assert env.formalizable_assertions[0].obligation_id == "energy.so2.lte_100ppm"

    @pytest.mark.asyncio
    async def test_flag_verdict_when_over_limit(self) -> None:
        evaluator = _evaluator()
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 150},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:2",
        )
        assert env.verdict == V3Verdict.FLAG.value
        assert env.formalizable_assertions[0].satisfied is False
        assert env.formalizable_assertions[0].observed == 150

    @pytest.mark.asyncio
    async def test_within_range_predicate_works(self) -> None:
        evaluator = _evaluator()
        env = await evaluator.aevaluate(
            measurement={"ph": 7.2},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:3",
        )
        assert env.verdict == V3Verdict.CLEAR.value
        assert env.formalizable_assertions[0].obligation_id == "water.ph.within_6_to_85"


# ---- Provenance ---------------------------------------------------------------


class TestProvenance:
    @pytest.mark.asyncio
    async def test_all_provenance_fields_populated(self) -> None:
        evaluator = _evaluator(seed=42)
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:4",
        )
        prov = env.model_provenance
        assert prov.model_weight_hash.startswith("sha256:")
        assert prov.kg_version_hash == _KG_HASH
        assert prov.prompt_template_id == PROMPT_TEMPLATE_ID
        assert prov.prompt_template_hash.startswith("sha256:")
        assert prov.decoder_seed == 42
        assert prov.structured_grammar_hash.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_kg_version_hash_propagates(self) -> None:
        unique_hash = "sha256:" + "b" * 64
        evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash=unique_hash, decoder_seed=0)
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:5",
        )
        assert env.model_provenance.kg_version_hash == unique_hash


# ---- Citation enforcement -----------------------------------------------------


class _CitingFakeLLM(FakeLLM):
    """A fake that always cites a fixed node_id, regardless of what is in the KG."""

    def __init__(self, fake_node_id: str) -> None:
        super().__init__()
        self._fake_node_id = fake_node_id

    async def evaluate(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        seed: int,
    ) -> Dict[str, Any]:
        return {
            "verdict": "CLEAR",
            "reasoning": "Citing a node that isn't in the snapshot.",
            "kg_citations": [
                {
                    "node_id": self._fake_node_id,
                    "version": kg_snapshot.get("version", "x"),
                    "role": "obligation",
                }
            ],
            "formalizable_assertions": [],
        }


class TestCitationEnforcement:
    @pytest.mark.asyncio
    async def test_bogus_citation_forces_null_unmapped(self) -> None:
        evaluator = V3Evaluator(
            llm=_CitingFakeLLM(fake_node_id="hallucinated.obligation.999"),
            kg_version_hash=_KG_HASH,
            decoder_seed=0,
        )
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:6",
        )
        assert env.verdict == V3Verdict.NULL_UNMAPPED.value
        assert env.verifier_result.status == VerifierStatus.UNVERIFIABLE.value
        assert any("hallucinated.obligation.999" in d for d in env.verifier_result.divergences)
        assert env.kg_citations == []
        assert env.formalizable_assertions == []

    @pytest.mark.asyncio
    async def test_definitions_count_as_valid_citation_targets(self) -> None:
        evaluator = V3Evaluator(
            llm=_CitingFakeLLM(fake_node_id="def.units.ppm"),
            kg_version_hash=_KG_HASH,
            decoder_seed=0,
        )
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:7",
        )
        # def.units.ppm is in the snapshot's definitions, so the citation is
        # VALID: enforcement must not force NULL_UNMAPPED. (The verdict is
        # DISCRETIONARY rather than CLEAR because this scripted response
        # carries no formalizable assertions - the taxonomy guard forbids
        # unverified CLEARs since eval run 5; see test_taxonomy_guard.py.)
        assert env.verdict != V3Verdict.NULL_UNMAPPED.value, "valid citation rejected"
        assert env.verdict == V3Verdict.DISCRETIONARY.value
        assert any("taxonomy_guard" in n for n in env.notes)


# ---- Empty / unmapped KG ------------------------------------------------------


class TestUnmappedKG:
    @pytest.mark.asyncio
    async def test_empty_snapshot_returns_null_unmapped(self) -> None:
        evaluator = _evaluator()
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot={"version": "empty", "obligations": []},
            transcript_ref="ledger:t1/seq:8",
        )
        assert env.verdict == V3Verdict.NULL_UNMAPPED.value
        assert env.kg_citations == []
        assert env.formalizable_assertions == []

    @pytest.mark.asyncio
    async def test_measurement_without_matching_metric_returns_null_unmapped(self) -> None:
        evaluator = _evaluator()
        env = await evaluator.aevaluate(
            measurement={"unrelated_metric": 999},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:9",
        )
        assert env.verdict == V3Verdict.NULL_UNMAPPED.value


# ---- Verifier integration (real wiring as of PR 10c) -------------------------


class TestVerifierWired:
    @pytest.mark.asyncio
    async def test_happy_path_yields_agreed(self) -> None:
        evaluator = _evaluator()
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:10",
        )
        assert env.verifier_result.status == VerifierStatus.AGREED.value
        assert env.verifier_result.checked_assertions == 1
        assert env.verifier_result.divergences == []

    @pytest.mark.asyncio
    async def test_flag_path_yields_agreed_when_llm_and_verifier_agree(self) -> None:
        evaluator = _evaluator()
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 150},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:10b",
        )
        assert env.verdict == V3Verdict.FLAG.value
        assert env.verifier_result.status == VerifierStatus.AGREED.value


# ---- JSON round-trip ----------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_envelope_round_trips(self) -> None:
        evaluator = _evaluator()
        original = await evaluator.aevaluate(
            measurement={"so2_ppm": 87},
            kg_snapshot=_kg_snapshot(),
            transcript_ref="ledger:t1/seq:11",
        )
        text = original.model_dump_json()
        reparsed = V3VerdictEnvelope.model_validate(json.loads(text))
        assert reparsed.model_dump(mode="json") == original.model_dump(mode="json")


# ---- Normalization integration ------------------------------------------------


class _WrongSatisfiedLLM:
    """Test backend that emits the right verdict but inverts ``satisfied``
    for every assertion -- exactly the failure mode seen in Run 6.
    """

    name = "wrong-satisfied-llm"

    @property
    def model_weight_hash(self) -> str:
        return "sha256:" + "e" * 64

    @property
    def prompt_template_id(self) -> str:
        return "ski.v3.evaluate.test"

    @property
    def prompt_template_hash(self) -> str:
        return "sha256:" + "f" * 64

    @property
    def structured_grammar_hash(self) -> str:
        return "sha256:" + "0" * 64

    async def evaluate(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        seed: int,
    ) -> Dict[str, Any]:
        """Emit CLEAR for so2_ppm<=100 but with satisfied=False (wrong boolean)."""
        return {
            "verdict": "CLEAR",
            "reasoning": "SO2 is within limit, but I inverted the boolean.",
            "kg_citations": [
                {
                    "node_id": "energy.so2.lte_100ppm",
                    "version": kg_snapshot.get("version", "unknown"),
                    "role": "obligation",
                }
            ],
            "formalizable_assertions": [
                {
                    "predicate": "must_not_exceed",
                    "metric": "so2_ppm",
                    "value": 100,
                    "observed": 50,
                    "satisfied": False,  # deliberately wrong
                    "obligation_id": "energy.so2.lte_100ppm",
                }
            ],
        }


class TestNormalizationIntegration:
    """Verifier normalization wired into the evaluator: a model that emits the
    right verdict but wrong ``satisfied`` flag should produce AGREED (not
    LLM_CONTRADICTION / DISCRETIONARY) because the verifier corrects the flag
    before the aggregate check runs."""

    @pytest.mark.asyncio
    async def test_wrong_satisfied_corrected_yields_agreed_and_clear(self) -> None:
        evaluator = V3Evaluator(
            llm=_WrongSatisfiedLLM(),
            kg_version_hash=_KG_HASH,
        )
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        # Verdict must remain CLEAR (model was right about the verdict)
        assert env.verdict == V3Verdict.CLEAR.value
        # Verifier must agree (normalization corrected satisfied=False -> True)
        assert env.verifier_result.status == VerifierStatus.AGREED.value
        # The corrected assertion in the envelope must now show satisfied=True
        assert len(env.formalizable_assertions) == 1
        assert env.formalizable_assertions[0].satisfied is True
        # A normalization note must be present in the envelope
        assert any("satisfied normalised" in note for note in env.notes)

    @pytest.mark.asyncio
    async def test_normalization_note_records_correction(self) -> None:
        evaluator = V3Evaluator(
            llm=_WrongSatisfiedLLM(),
            kg_version_hash=_KG_HASH,
        )
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        # The note must cite the obligation and both boolean values
        norm_notes = [n for n in env.notes if "satisfied normalised" in n]
        assert len(norm_notes) == 1
        assert "energy.so2.lte_100ppm" in norm_notes[0]
        assert "False" in norm_notes[0]
        assert "True" in norm_notes[0]

    @pytest.mark.asyncio
    async def test_grounding_failure_still_contradicts_after_normalization(self) -> None:
        """If the model invents an observed value, normalization must NOT rescue it."""

        class FabricatedObservationLLM(_WrongSatisfiedLLM):
            async def evaluate(self, *, measurement, kg_snapshot, seed):
                return {
                    "verdict": "CLEAR",
                    "reasoning": "I fabricated the observed value.",
                    "kg_citations": [
                        {
                            "node_id": "energy.so2.lte_100ppm",
                            "version": kg_snapshot.get("version", "unknown"),
                            "role": "obligation",
                        }
                    ],
                    "formalizable_assertions": [
                        {
                            "predicate": "must_not_exceed",
                            "metric": "so2_ppm",
                            "value": 100,
                            "observed": 999,  # fabricated -- measurement has 50
                            "satisfied": True,
                            "obligation_id": "energy.so2.lte_100ppm",
                        }
                    ],
                }

        evaluator = V3Evaluator(
            llm=FabricatedObservationLLM(),
            kg_version_hash=_KG_HASH,
        )
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        # Fabricated observation is a grounding failure -- must NOT be papered over
        assert env.verifier_result.status == VerifierStatus.LLM_CONTRADICTION.value
