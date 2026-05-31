"""Symbolic Verifier — mechanically cross-checks the LLM's formalizable assertions.

The verifier closes the neuro-symbolic loop per spec v3.0 §4.5. For each
:class:`FormalizableAssertion` the LLM emits, the verifier re-evaluates the
predicate **without** invoking the LLM, then compares its mechanical result
to the LLM's ``satisfied`` flag.

Outcomes (:class:`VerifierStatus`):

* ``AGREED`` — every assertion the verifier could check matches the LLM.
* ``LLM_CONTRADICTION`` — the LLM said ``satisfied`` (or ``not satisfied``)
  but the verifier disagrees. The mechanical truth wins.
* ``NEURO_SYMBOLIC_DIVERGENCE`` — the verifier's per-assertion view agrees
  with each ``satisfied`` flag in isolation, but the LLM's overall verdict
  doesn't match what those assertions imply (e.g. all satisfied but the
  LLM still emitted FLAG, or vice versa).
* ``UNVERIFIABLE`` — at least one assertion uses a predicate the verifier
  cannot mechanically evaluate (e.g. predicates that require qualified
  human judgment). The envelope is forwarded as-is for human attestation.

Stateless predicates handled in PR 10c:

* ``must_not_exceed`` — ``observed <= value``
* ``must_be_at_least`` — ``observed >= value``
* ``must_be_within`` — ``value[0] <= observed <= value[1]``
* ``must_equal`` — ``observed == value``
* ``must_not_equal`` — ``observed != value``

Stateful predicates (window queries, time-bounded checks) require the
telemetry buffer and a database fixture; deferred to a follow-up PR.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from .envelope import (
    FormalizableAssertion,
    V3Verdict,
    VerifierResult,
    VerifierStatus,
)

logger = logging.getLogger(__name__)


# ---- Predicate handlers -------------------------------------------------------


@dataclass(frozen=True)
class _CheckOutcome:
    """Result of mechanically evaluating a single :class:`FormalizableAssertion`.

    ``mechanically_satisfied`` is the verifier's own computation; ``None`` when
    the predicate is one the verifier cannot evaluate (UNVERIFIABLE). The
    ``reason`` string records why the verifier reached this outcome — it goes
    into :attr:`VerifierResult.divergences` when there is a disagreement.
    """

    mechanically_satisfied: Optional[bool]
    reason: str


_STATELESS_PREDICATES = frozenset(
    {
        "must_not_exceed",
        "must_be_at_least",
        "must_be_within",
        "must_equal",
        "must_not_equal",
    }
)


def _check_must_not_exceed(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)) or not isinstance(value, (int, float)):
        return _CheckOutcome(
            None,
            f"must_not_exceed requires numeric operands; got observed={observed!r} value={value!r}.",
        )
    ok = observed <= value
    return _CheckOutcome(ok, f"observed={observed} <= value={value}: {ok}")


def _check_must_be_at_least(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)) or not isinstance(value, (int, float)):
        return _CheckOutcome(
            None,
            f"must_be_at_least requires numeric operands; got observed={observed!r} value={value!r}.",
        )
    ok = observed >= value
    return _CheckOutcome(ok, f"observed={observed} >= value={value}: {ok}")


def _check_must_be_within(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)):
        return _CheckOutcome(
            None,
            f"must_be_within requires a numeric observed; got {observed!r}.",
        )
    if not (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(b, (int, float)) for b in value)
    ):
        return _CheckOutcome(
            None,
            f"must_be_within requires value=[lo, hi] of two numbers; got {value!r}.",
        )
    lo, hi = value[0], value[1]
    ok = lo <= observed <= hi
    return _CheckOutcome(ok, f"{lo} <= observed={observed} <= {hi}: {ok}")


def _check_must_equal(observed: Any, value: Any) -> _CheckOutcome:
    ok = observed == value
    return _CheckOutcome(ok, f"observed={observed!r} == value={value!r}: {ok}")


def _check_must_not_equal(observed: Any, value: Any) -> _CheckOutcome:
    ok = observed != value
    return _CheckOutcome(ok, f"observed={observed!r} != value={value!r}: {ok}")


_PREDICATE_HANDLERS = {
    "must_not_exceed": _check_must_not_exceed,
    "must_be_at_least": _check_must_be_at_least,
    "must_be_within": _check_must_be_within,
    "must_equal": _check_must_equal,
    "must_not_equal": _check_must_not_equal,
}


# ---- SymbolicVerifier ---------------------------------------------------------


@dataclass
class SymbolicVerifier:
    """Mechanically cross-checks :class:`FormalizableAssertion` instances.

    Stateless: instances can be reused across requests. No I/O.

    Stateful predicates (window queries, time-bounded checks) require the
    telemetry buffer and will be added in a follow-up. Until then, an
    assertion that uses an unknown or stateful predicate yields
    ``UNVERIFIABLE`` for the whole envelope.
    """

    def check_assertion(self, assertion: FormalizableAssertion) -> _CheckOutcome:
        """Mechanically evaluate one assertion without consulting the LLM.

        Returns ``mechanically_satisfied=None`` when the predicate cannot be
        evaluated; the caller maps that to ``UNVERIFIABLE``.
        """
        handler = _PREDICATE_HANDLERS.get(assertion.predicate)
        if handler is None:
            return _CheckOutcome(
                None,
                f"Predicate {assertion.predicate!r} is not mechanically verifiable in PR 10c.",
            )
        return handler(assertion.observed, assertion.value)

    def verify(
        self,
        assertions: Sequence[FormalizableAssertion],
        *,
        llm_verdict: V3Verdict,
    ) -> VerifierResult:
        """Aggregate per-assertion checks into a :class:`VerifierResult`.

        Decision rules:

          * Any UNVERIFIABLE assertion → status is UNVERIFIABLE.
          * Any per-assertion disagreement (mechanical != LLM's ``satisfied``)
            → LLM_CONTRADICTION.
          * All per-assertion outcomes agree, but the LLM verdict is
            inconsistent with what the satisfied flags imply
            (e.g. all satisfied yet verdict=FLAG, or any unsatisfied yet
            verdict=CLEAR) → NEURO_SYMBOLIC_DIVERGENCE.
          * Otherwise → AGREED.
        """
        if not assertions:
            # No formalizable assertions to check; verifier is silent.
            # Whether that is a problem is the risk-tier policy's call.
            return VerifierResult(
                status=VerifierStatus.UNVERIFIABLE,
                checked_assertions=0,
                divergences=["No formalizable assertions to verify."],
            )

        divergences: List[str] = []
        unverifiable_count = 0
        contradictions: List[Tuple[FormalizableAssertion, _CheckOutcome]] = []
        checked = 0

        for assertion in assertions:
            outcome = self.check_assertion(assertion)
            if outcome.mechanically_satisfied is None:
                unverifiable_count += 1
                divergences.append(f"[{assertion.obligation_id}] {outcome.reason}")
                continue
            checked += 1
            if outcome.mechanically_satisfied != assertion.satisfied:
                contradictions.append((assertion, outcome))
                divergences.append(
                    f"[{assertion.obligation_id}] LLM said satisfied={assertion.satisfied}, "
                    f"verifier says {outcome.mechanically_satisfied}. {outcome.reason}"
                )

        if unverifiable_count > 0:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIABLE,
                checked_assertions=checked,
                divergences=divergences,
            )

        if contradictions:
            return VerifierResult(
                status=VerifierStatus.LLM_CONTRADICTION,
                checked_assertions=checked,
                divergences=divergences,
            )

        # Per-assertion agreement is total. Now sanity-check the LLM's
        # overall verdict against what the satisfied flags imply.
        all_satisfied = all(a.satisfied for a in assertions)
        any_unsatisfied = any(not a.satisfied for a in assertions)

        expected_verdict_consistent_with_clear = all_satisfied
        expected_verdict_consistent_with_flag = any_unsatisfied

        verdict_inconsistent = (
            llm_verdict == V3Verdict.CLEAR and not expected_verdict_consistent_with_clear
        ) or (llm_verdict == V3Verdict.FLAG and not expected_verdict_consistent_with_flag)

        if verdict_inconsistent:
            return VerifierResult(
                status=VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE,
                checked_assertions=checked,
                divergences=[
                    f"Per-assertion checks agree, but LLM verdict {llm_verdict.value!r} "
                    f"is not consistent with the satisfied flags "
                    f"(all_satisfied={all_satisfied}, any_unsatisfied={any_unsatisfied})."
                ],
            )

        return VerifierResult(
            status=VerifierStatus.AGREED,
            checked_assertions=checked,
            divergences=[],
        )


__all__ = ["SymbolicVerifier"]
