"""SKI Benchmarks runner — measures the production evaluation path.

Two modes, two different claims:

``pipeline``
    In-process measurement of the framework's own per-verdict cost:
    ``kg_loader.scope_to`` -> ``V3Evaluator.aevaluate_with_transcript``
    (prompt render, citation validation, Symbolic Verifier cross-check,
    risk-tier policy, ed25519 transcript signing) with the deterministic
    ``FakeLLM`` backend, so model inference time is ~0 and what remains
    is **framework overhead** — the only latency component the SKI
    Framework itself controls. No server, no database.

``http``
    End-to-end measurement against a live deployment's
    ``POST /api/evaluate``: FastAPI, auth, jurisdiction scoping, LLM
    inference (whatever backend the deployment runs), verification,
    signing, and the audit-ledger append. This is the number an
    operator validates per deployment.

The workload is the SKI Evals golden dataset (``evals/datasets/...``),
cycled deterministically — real cases through the real code path, with
the dataset hashes recorded in the run provenance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = REPO_ROOT / "reference-implementation" / "src"
_SCHEMAS_SRC = REPO_ROOT / "tools" / "ski-schemas" / "src"
for _p in (_SRC, _SCHEMAS_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ski_model.kg_loader import KnowledgeGraph  # noqa: E402
from ski_model.v3.evaluator import V3Evaluator, V3LLMBackend  # noqa: E402
from ski_model.v3.signing import TranscriptSigner  # noqa: E402

from .stats import LatencyStats, summarize  # noqa: E402


@dataclass
class BenchmarkRun:
    """Everything one benchmark run produces: stats per stage + provenance."""

    mode: str
    stages: Dict[str, LatencyStats]
    provenance: Dict[str, Any]
    verdict_counts: Dict[str, int] = dataclasses_field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "provenance": self.provenance,
            "stages": {name: s.as_dict() for name, s in self.stages.items()},
            "verdict_counts": self.verdict_counts,
        }


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def _environment() -> Dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "git_commit": _git_commit(),
    }


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_workload(dataset_dir: Path) -> tuple[KnowledgeGraph, List[Dict[str, Any]], Dict[str, str]]:
    """Load the golden dataset as a benchmark workload (KG + cases + hashes)."""
    kg_path = dataset_dir / "eval-kg.json"
    cases_path = dataset_dir / "cases.jsonl"
    kg = KnowledgeGraph.from_dict(json.loads(kg_path.read_text(encoding="utf-8")), require_signature=False)
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    hashes = {
        "kg_file_hash": _sha256_file(kg_path),
        "cases_file_hash": _sha256_file(cases_path),
    }
    return kg, cases, hashes


async def run_pipeline_benchmark(
    *,
    dataset_dir: Path,
    backend: V3LLMBackend,
    n: int,
    warmup: int,
    seed: int = 42,
) -> BenchmarkRun:
    """Measure framework overhead in-process. Model time ~0 with FakeLLM."""
    kg, cases, hashes = load_workload(dataset_dir)
    # Ephemeral signing key: the benchmark must include real ed25519
    # transcript signing in its measurement without touching a
    # deployment's key path ($SKI_TRANSCRIPT_KEY_PATH).
    keydir = tempfile.mkdtemp(prefix="ski-bench-key-")
    signer = TranscriptSigner.auto_provision(private_key_path=Path(keydir) / "transcript.ed25519")
    evaluator = V3Evaluator(
        llm=backend,
        kg_version_hash=hashes["kg_file_hash"],
        decoder_seed=seed,
        signer=signer,
    )

    scope_ms: List[float] = []
    evaluate_ms: List[float] = []
    total_ms: List[float] = []
    verdict_counts: Dict[str, int] = {}

    for i in range(warmup + n):
        case = cases[i % len(cases)]
        as_of = _parse_ts(case["timestamp"])
        measuring = i >= warmup

        t0 = time.perf_counter()
        snapshot = kg.scope_to(jurisdiction=case.get("jurisdiction"), as_of=as_of)
        t1 = time.perf_counter()
        result = await evaluator.aevaluate_with_transcript(
            measurement=case["measurement"],
            kg_snapshot=snapshot,
            subject=case.get("subject"),
            as_of=as_of,
        )
        t2 = time.perf_counter()

        if measuring:
            scope_ms.append((t1 - t0) * 1000.0)
            evaluate_ms.append((t2 - t1) * 1000.0)
            total_ms.append((t2 - t0) * 1000.0)
            verdict = getattr(result.envelope.verdict, "value", str(result.envelope.verdict))
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            assert result.transcript is not None, "signer configured; transcript must be produced"

    provenance: Dict[str, Any] = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend.name,
        "n": n,
        "warmup": warmup,
        "decoder_seed": seed,
        "dataset": str(dataset_dir.relative_to(REPO_ROOT)),
        "kg_version": kg.version,
        "transcript_signing": True,
        "environment": _environment(),
        **hashes,
    }
    return BenchmarkRun(
        mode="pipeline",
        stages={
            "scope_to": summarize(scope_ms),
            "evaluate_verify_sign": summarize(evaluate_ms),
            "framework_total": summarize(total_ms),
        },
        provenance=provenance,
        verdict_counts=verdict_counts,
    )


async def run_http_benchmark(
    *,
    dataset_dir: Path,
    endpoint: str,
    api_key: str,
    n: int,
    warmup: int,
    insecure: bool = True,
    timeout_s: float = 120.0,
) -> BenchmarkRun:
    """Measure end-to-end latency against a live deployment."""
    import httpx

    _, cases, hashes = load_workload(dataset_dir)
    request_ms: List[float] = []
    verdict_counts: Dict[str, int] = {}

    async with httpx.AsyncClient(
        base_url=endpoint,
        verify=not insecure,
        timeout=timeout_s,
        headers={"X-API-Key": api_key},
    ) as client:
        for i in range(warmup + n):
            case = cases[i % len(cases)]
            body = {
                "measurement_id": f"bench-{i:06d}",
                "timestamp": case["timestamp"],
                "subject": case.get("subject", "bench.subject"),
                "measurement": case["measurement"],
                "jurisdiction": case.get("jurisdiction"),
            }
            t0 = time.perf_counter()
            resp = await client.post("/api/evaluate", json=body)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            resp.raise_for_status()
            if i >= warmup:
                request_ms.append(elapsed_ms)
                verdict = str(resp.json().get("verdict"))
                verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

    provenance: Dict[str, Any] = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "n": n,
        "warmup": warmup,
        "dataset": str(dataset_dir.relative_to(REPO_ROOT)),
        "note": (
            "End-to-end: includes HTTP, auth, scoping, LLM inference, "
            "verification, signing, and the audit-ledger append."
        ),
        "environment": _environment(),
        **hashes,
    }
    return BenchmarkRun(
        mode="http",
        stages={"end_to_end": summarize(request_ms)},
        provenance=provenance,
        verdict_counts=verdict_counts,
    )


def run_pipeline(
    *,
    dataset_dir: Path,
    backend: V3LLMBackend,
    n: int,
    warmup: int,
    seed: int = 42,
) -> BenchmarkRun:
    """Synchronous wrapper for :func:`run_pipeline_benchmark`."""
    return asyncio.run(
        run_pipeline_benchmark(dataset_dir=dataset_dir, backend=backend, n=n, warmup=warmup, seed=seed)
    )


def run_http(
    *,
    dataset_dir: Path,
    endpoint: str,
    api_key: str,
    n: int,
    warmup: int,
    insecure: bool = True,
) -> BenchmarkRun:
    """Synchronous wrapper for :func:`run_http_benchmark`."""
    return asyncio.run(
        run_http_benchmark(
            dataset_dir=dataset_dir,
            endpoint=endpoint,
            api_key=api_key,
            n=n,
            warmup=warmup,
            insecure=insecure,
        )
    )
