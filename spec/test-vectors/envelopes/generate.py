#!/usr/bin/env python3
"""Regenerate the V3VerdictEnvelope example vectors.

Each example is built through the ``ski_schemas`` Pydantic models (so it is
by construction a valid runtime envelope) and written as formatted JSON.
The drift check additionally validates every file here against the
committed ``spec/contracts/schemas/v3_verdict_envelope.schema.json``, so the
examples prove the published JSON Schema accepts a real envelope.

Hashes are real SHA-256 digests of descriptive labels (not of any secret);
they exist only to exercise the ``sha256:<hex>`` field patterns.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "tools" / "ski-schemas" / "src"))

from ski_schemas.envelope import V3VerdictEnvelope  # noqa: E402

HERE = Path(__file__).resolve().parent


def _h(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


# A full, realistic CLEAR verdict with every provenance field populated,
# including the optional framework v3.2.0 trust/backend fields.
CLEAR_ENVELOPE: dict[str, Any] = {
    "verdict": "CLEAR",
    "reasoning": (
        "The scoped KG carried one obligation mapped to the measurement (energy.so2.cap, "
        "must_not_exceed 100 ppm). The observed SO2 reading was 98.6 ppm, below the cap, and "
        "the symbolic verifier independently confirmed the single formalizable assertion."
    ),
    "kg_citations": [
        {"node_id": "energy.so2.cap", "version": "3", "role": "obligation"},
    ],
    "formalizable_assertions": [
        {
            "predicate": "must_not_exceed",
            "metric": "so2_ppm",
            "value": 100,
            "observed": 98.6,
            "satisfied": True,
            "obligation_id": "energy.so2.cap",
        },
    ],
    "verifier_result": {"status": "AGREED", "checked_assertions": 1, "divergences": []},
    "model_provenance": {
        "model_weight_hash": _h("demo-model-weights"),
        "kg_version_hash": _h("demo-kg-version"),
        "prompt_template_id": "ski.v3.evaluate.1",
        "prompt_template_hash": _h("demo-prompt-template"),
        "decoder_seed": 0,
        "structured_grammar_hash": _h("demo-grammar"),
        "model_hash_verified": True,
        "inference_backend": "ollama-v3",
        "kg_signer_key_id": "sha256:" + "ab" * 32,
        "kg_trust": "anchored",
    },
    "transcript_ref": _h("demo-transcript"),
    "notes": [],
    "verdict_path": None,
}


EXAMPLES = {"clear_full_provenance.json": CLEAR_ENVELOPE}


def build() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, raw in EXAMPLES.items():
        # Round-trip through the model to guarantee validity and canonical field order.
        env = V3VerdictEnvelope.model_validate(raw)
        out[name] = json.dumps(env.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    return out


def main() -> int:
    for name, text in build().items():
        (HERE / name).write_text(text, encoding="utf-8")
        print(f"wrote {(HERE / name).relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
