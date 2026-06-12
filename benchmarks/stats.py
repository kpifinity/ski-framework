"""Latency statistics for benchmark runs. Stdlib only — no numpy."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class LatencyStats:
    """Summary statistics over a list of per-operation latencies (ms)."""

    n: int
    mean_ms: float
    stdev_ms: float
    min_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    throughput_per_s: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n": self.n,
            "mean_ms": round(self.mean_ms, 3),
            "stdev_ms": round(self.stdev_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "p50_ms": round(self.p50_ms, 3),
            "p90_ms": round(self.p90_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "throughput_per_s": round(self.throughput_per_s, 1),
        }


def percentile(sorted_values: List[float], q: float) -> float:
    """Nearest-rank percentile on a pre-sorted list (q in [0, 100])."""
    if not sorted_values:
        raise ValueError("percentile of empty list")
    if not 0 <= q <= 100:
        raise ValueError(f"q must be in [0, 100], got {q}")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(1, -(-q * len(sorted_values) // 100))  # ceil without math
    return sorted_values[int(rank) - 1]


def summarize(latencies_ms: List[float]) -> LatencyStats:
    if not latencies_ms:
        raise ValueError("no samples to summarize")
    ordered = sorted(latencies_ms)
    total_s = sum(latencies_ms) / 1000.0
    return LatencyStats(
        n=len(ordered),
        mean_ms=statistics.fmean(ordered),
        stdev_ms=statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
        min_ms=ordered[0],
        p50_ms=percentile(ordered, 50),
        p90_ms=percentile(ordered, 90),
        p95_ms=percentile(ordered, 95),
        p99_ms=percentile(ordered, 99),
        max_ms=ordered[-1],
        throughput_per_s=(len(ordered) / total_s) if total_s > 0 else 0.0,
    )
