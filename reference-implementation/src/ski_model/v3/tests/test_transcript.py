"""Tests for the v3 LLM transcript record (spec §6.2).

End-to-end: build a transcript via the evaluator, verify its signature,
round-trip through JSON, and confirm canonicalisation is provider-neutral.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from ski_model.v3 import (
    FakeLLM,
    LLMTranscript,
    TranscriptSigner,
    V3Evaluator,
    V3Verdict,
    verify_signature,
)
from ski_model.v3.transcript import (
    canonical_request,
    canonical_response,
    hash_pair,
    signing_message,
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
            }
        ],
    }


class TestCanonicalisation:
    def test_canonical_request_is_utf8(self) -> None:
        assert canonical_request("hello § world") == "hello § world".encode()

    def test_canonical_response_sorts_keys(self) -> None:
        a = canonical_response({"b": 2, "a": 1})
        b = canonical_response({"a": 1, "b": 2})
        assert a == b

    def test_canonical_response_compact_separators(self) -> None:
        # No spaces after , or : — bit-for-bit reproducibility under different json libs.
        out = canonical_response({"a": 1, "b": 2})
        assert b", " not in out
        assert b": " not in out

    def test_hash_pair_is_deterministic(self) -> None:
        h1 = hash_pair(request_text="prompt", response={"k": 1})
        h2 = hash_pair(request_text="prompt", response={"k": 1})
        assert h1 == h2
        assert h1[0].startswith("sha256:")
        assert h1[1].startswith("sha256:")


class TestEvaluatorEmitsSignedTranscript:
    @pytest.mark.asyncio
    async def test_evaluator_with_signer_emits_transcript(self, tmp_path: Path) -> None:
        signer = TranscriptSigner.auto_provision(tmp_path / "k.ed25519")
        evaluator = V3Evaluator(
            llm=FakeLLM(),
            kg_version_hash=_KG_HASH,
            decoder_seed=0,
            signer=signer,
        )
        result = await evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        assert result.transcript is not None
        t = result.transcript
        assert t.signing_key_id == signer.key_id
        assert t.backend_name == "fake-llm"
        assert t.request_hash.startswith("sha256:")
        assert t.response_hash.startswith("sha256:")
        # The envelope's transcript_ref points to the transcript id.
        assert result.envelope.transcript_ref == f"transcript:{t.transcript_id}"

    @pytest.mark.asyncio
    async def test_evaluator_without_signer_emits_no_transcript(self) -> None:
        evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash=_KG_HASH, decoder_seed=0)
        result = await evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        assert result.transcript is None

    @pytest.mark.asyncio
    async def test_transcript_signature_verifies(self, tmp_path: Path) -> None:
        signer = TranscriptSigner.auto_provision(tmp_path / "k.ed25519")
        evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash=_KG_HASH, decoder_seed=0, signer=signer)
        result = await evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": 87},
            kg_snapshot=_kg_snapshot(),
        )
        t = result.transcript
        assert t is not None
        ok = verify_signature(
            public_key_pem=signer.public_key_pem,
            message=signing_message(request_hash=t.request_hash, response_hash=t.response_hash),
            signature_hex=t.signature_hex,
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_transcript_round_trips_through_json(self, tmp_path: Path) -> None:
        signer = TranscriptSigner.auto_provision(tmp_path / "k.ed25519")
        evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash=_KG_HASH, decoder_seed=0, signer=signer)
        result = await evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        t = result.transcript
        assert t is not None
        text = t.model_dump_json()
        reparsed = LLMTranscript.model_validate(json.loads(text))
        assert reparsed.transcript_id == t.transcript_id
        assert reparsed.signature_hex == t.signature_hex


class TestAevaluateBackwardsCompat:
    @pytest.mark.asyncio
    async def test_aevaluate_returns_envelope_directly(self) -> None:
        evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash=_KG_HASH, decoder_seed=0)
        env = await evaluator.aevaluate(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        # aevaluate still returns V3VerdictEnvelope (not EvaluationResult).
        assert env.verdict == V3Verdict.CLEAR.value
        assert env.transcript_ref.startswith("transcript:")


class TestProviderNeutralBackendMetadata:
    @pytest.mark.asyncio
    async def test_backend_metadata_is_opaque_dict(self, tmp_path: Path) -> None:
        """backend_metadata accepts arbitrary backend-specific data."""
        signer = TranscriptSigner.auto_provision(tmp_path / "k.ed25519")
        evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash=_KG_HASH, decoder_seed=0, signer=signer)
        result = await evaluator.aevaluate_with_transcript(
            measurement={"so2_ppm": 50},
            kg_snapshot=_kg_snapshot(),
        )
        t = result.transcript
        assert t is not None
        # FakeLLM ships with empty backend_metadata. Real backends populate it.
        assert isinstance(t.backend_metadata, dict)

    def test_transcript_rejects_unknown_top_level_fields(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LLMTranscript.model_validate(
                {
                    "transcript_id": "x",
                    "request_canonical": "x",
                    "request_hash": "sha256:" + "a" * 64,
                    "response_canonical": {},
                    "response_hash": "sha256:" + "b" * 64,
                    "signature_hex": "deadbeef",
                    "signing_key_id": "sha256:" + "c" * 64,
                    "backend_name": "x",
                    "backend_metadata": {},
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    # extra field — should be rejected
                    "provider_blob": "anthropic-specific",
                }
            )
