"""SKI Evals runner — drives golden cases through the real evaluation path.

The runner is deliberately thin: it reuses ``kg_loader.KnowledgeGraph``
(including jurisdiction + effective-date scoping) and ``V3Evaluator``
exactly as ``server.py`` does, so the numbers it produces describe the
production code path, not a simulation of it.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = REPO_ROOT / "reference-implementation" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ski_model.kg_loader import KnowledgeGraph  # noqa: E402
from ski_model.v3.evaluator import V3Evaluator, V3LLMBackend  # noqa: E402

from .metrics import CaseResult, EvalMetrics, compute_metrics  # noqa: E402


@dataclass
class EvalRun:
    """Everything one eval run produces: metrics, raw results, provenance."""

    dataset: str
    metrics: EvalMetrics
    results: List[CaseResult]
    provenance: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "provenance": self.provenance,
            "metrics": self.metrics.as_dict(),
            "cases": [
                {
                    "case_id": r.case_id,
                    "category": r.category,
                    "expected": r.expected_verdict,
                    "predicted": r.predicted_verdict,
                    "verdict_correct": r.verdict_correct,
                    "assertions_correct": r.assertions_correct,
                    "verifier_status": r.verifier_status,
                }
                for r in self.results
            ],
        }


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen = set()
    for c in cases:
        if c["case_id"] in seen:
            raise ValueError(f"Duplicate case_id {c['case_id']!r} in {path}.")
        seen.add(c["case_id"])
    return cases


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def run_eval(*, dataset_dir: Path, backend: V3LLMBackend, seed: int = 0) -> EvalRun:
    """Run every golden case in ``dataset_dir`` through the evaluator."""
    kg_path = dataset_dir / "eval-kg.json"
    cases_path = dataset_dir / "cases.jsonl"
    kg_raw = json.loads(kg_path.read_text(encoding="utf-8"))
    kg = KnowledgeGraph.from_dict(kg_raw, require_signature=False)
    cases = load_cases(cases_path)

    evaluator = V3Evaluator(
        llm=backend,
        kg_version_hash=_sha256_file(kg_path),
        decoder_seed=seed,
    )

    results: List[CaseResult] = []
    for c in cases:
        as_of = _parse_ts(c["timestamp"])
        snapshot = kg.scope_to(jurisdiction=c.get("jurisdiction"), as_of=as_of)
        envelope = await evaluator.aevaluate(
            measurement=c["measurement"],
            kg_snapshot=snapshot,
            subject=c.get("subject"),
            as_of=as_of,
        )
        results.append(
            CaseResult(
                case_id=c["case_id"],
                category=c.get("category", "uncategorised"),
                expected_verdict=c["expected"]["verdict"],
                predicted_verdict=getattr(envelope.verdict, "value", str(envelope.verdict)),
                expected_assertions=c["expected"].get("assertions", []),
                emitted_assertions=[a.model_dump() for a in envelope.formalizable_assertions],
                verifier_status=getattr(
                    envelope.verifier_result.status, "value", str(envelope.verifier_result.status)
                ),
                checked_assertions=envelope.verifier_result.checked_assertions,
                notes=c.get("notes", ""),
            )
        )

    provenance = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend.name,
        "model_weight_hash": backend.model_weight_hash,
        "prompt_template_id": backend.prompt_template_id,
        "prompt_template_hash": backend.prompt_template_hash,
        "structured_grammar_hash": backend.structured_grammar_hash,
        "decoder_seed": seed,
        "kg_version": kg.version,
        "kg_file_hash": _sha256_file(kg_path),
        "cases_file_hash": _sha256_file(cases_path),
        "n_cases": len(cases),
    }
    return EvalRun(
        dataset=dataset_dir.name,
        metrics=compute_metrics(results),
        results=results,
        provenance=provenance,
    )
