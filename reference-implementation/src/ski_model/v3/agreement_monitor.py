"""Neuro-symbolic agreement monitor — rolling LLM↔verifier health signal.

Replaces the v2 determinism canary. Every time the runtime produces a
:class:`V3VerdictEnvelope`, the verifier's :class:`VerifierStatus` is
recorded here. The monitor maintains a rolling window of the last N
statuses and exposes:

  * Per-status counts (AGREED, LLM_CONTRADICTION,
    NEURO_SYMBOLIC_DIVERGENCE, UNVERIFIABLE).
  * ``agreement_rate`` — ``AGREED / total`` over the window.
  * ``is_healthy()`` — true iff ``agreement_rate >= threshold``.

Why this matters: in production an operator wants a continuous,
low-cost signal that the LLM and the symbolic verifier still agree on
what the data means. A sustained drop in agreement rate is a strong
indicator that the LLM has drifted, the KG has shifted under it, or
the prompt template no longer fits the model. Pages on the threshold
crossing route to the on-call.

Storage is process-local (an in-memory ``deque``). That is enough for
"how is this worker doing right now." A cross-process / cross-restart
view comes from the ledger — operators who need it can compute the
agreement rate from ``verifier_status`` directly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any, Deque, Dict, Union

from .envelope import VerifierStatus

_StatusInput = Union[VerifierStatus, str]


def _normalise_status(value: _StatusInput) -> str:
    """Accept either a VerifierStatus enum or its string value."""
    if isinstance(value, VerifierStatus):
        return value.value
    if isinstance(value, str):
        # Validate against the enum so we never silently bucket garbage.
        return VerifierStatus(value).value
    raise TypeError(
        f"AgreementMonitor.record() expects VerifierStatus or its string "
        f"value, got {type(value).__name__}: {value!r}."
    )


@dataclass
class AgreementMonitor:
    """Rolling-window tracker of :class:`VerifierStatus` over evaluations.

    Parameters
    ----------
    window_size:
        How many recent statuses to keep. Older entries roll off.
        Default 1000 — large enough to smooth noise, small enough to
        react to drift in minutes for a moderately busy deployment.
    threshold:
        Minimum acceptable agreement rate, in ``[0.0, 1.0]``.
        Default ``0.95`` — informed by spec §7.2 guidance that
        agreement below 95% should page.

    Instances are safe to call from multiple async tasks because the
    underlying state is guarded by a :class:`~threading.Lock`. The lock
    is contended only during ``record`` and ``snapshot``; both are O(1)
    so the cost is negligible.
    """

    window_size: int = 1000
    threshold: float = 0.95

    def __post_init__(self) -> None:
        if self.window_size <= 0:
            raise ValueError(f"window_size must be > 0, got {self.window_size}")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be in [0.0, 1.0], got {self.threshold}")
        self._statuses: Deque[str] = deque(maxlen=self.window_size)
        self._lock = Lock()

    def record(self, status: _StatusInput) -> None:
        """Record one evaluation's verifier status."""
        normalised = _normalise_status(status)
        with self._lock:
            self._statuses.append(normalised)

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable view of the rolling window."""
        with self._lock:
            statuses = list(self._statuses)
        counts = {s.value: 0 for s in VerifierStatus}
        for s in statuses:
            counts[s] = counts.get(s, 0) + 1
        total = len(statuses)
        agreed = counts.get(VerifierStatus.AGREED.value, 0)
        rate = (agreed / total) if total > 0 else None
        healthy = True if rate is None else rate >= self.threshold
        return {
            "window_size": self.window_size,
            "threshold": self.threshold,
            "observed": total,
            "counts": counts,
            "agreement_rate": rate,
            "is_healthy": healthy,
        }

    def is_healthy(self) -> bool:
        """True iff the rolling agreement rate meets the threshold.

        Empty windows are considered healthy — we don't page before any
        evaluations have run. Threshold is a strict ``>=``.
        """
        with self._lock:
            total = len(self._statuses)
            if total == 0:
                return True
            agreed = sum(1 for s in self._statuses if s == VerifierStatus.AGREED.value)
            rate = agreed / total
        return rate >= self.threshold


__all__ = ["AgreementMonitor"]
