"""Fail-closed Symbolic Verifier — adversarial conformance cases (framework v3.2.0).

Spec §4.1 / §4.5 / §5.3 / §5.4, finding C1 of the 2026-10-09 review. The
invariant: **if any mapped, formalizable obligation is mechanically
breached, the verdict is never CLEAR -- at any risk tier.**

Each case scripts an adversarial model output through the
``adversarial_rig`` fixture (see ``conftest.py``) and inspects only the
returned ``V3VerdictEnvelope``. No implementation source is read.

* MASKING -- a junk (out-of-enum) predicate beside a breached obligation
  must not turn the contradiction into an accepted UNVERIFIABLE.
* OMISSION -- a model that asserts only a passing obligation while another
  mapped obligation is breached must not get CLEAR (the verifier enumerates
  mapped obligations independently).
* A CLEAR resting on an asserted breach, a NULL_UNMAPPED or a bogus citation
  must not hide a mapped breach.
* An unknown or missing risk tier resolves to the strictest tier.
* Non-finite numbers, booleans where a number is expected, and malformed or
  timezone-less timestamps are rejected (HTTP 422), never evaluated.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pytest

from .conftest import AdversarialRig

pytestmark = pytest.mark.provenance

TIERS = ("tier-1", "tier-2", "tier-3")


def _so2(tier: Optional[str]) -> Dict[str, Any]:
    ob: Dict[str, Any] = {"id": "so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
    if tier is not None:
        ob["risk_tier"] = tier
    return ob


def _nox(tier: Optional[str]) -> Dict[str, Any]:
    ob: Dict[str, Any] = {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50}
    if tier is not None:
        ob["risk_tier"] = tier
    return ob


def _assertion(predicate: str, metric: str, value: Any, observed: Any, ob_id: str) -> Dict[str, Any]:
    return {
        "predicate": predicate,
        "metric": metric,
        "value": value,
        "observed": observed,
        "satisfied": True,
        "obligation_id": ob_id,
    }


def _output(verdict: str, cited: List[str], assertions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "verdict": verdict,
        "reasoning": "scripted adversarial output",
        "kg_citations": [{"node_id": i, "version": "v1", "role": "obligation"} for i in cited],
        "formalizable_assertions": assertions,
    }


def _ok(rig: AdversarialRig, **kwargs: Any) -> Dict[str, Any]:
    status, body = rig.evaluate(**kwargs)
    assert status == 200, (status, body)
    assert isinstance(body, dict)
    return body


@pytest.mark.parametrize("tier", TIERS)
def test_masking_junk_predicate_cannot_hide_a_breach(adversarial_rig: AdversarialRig, tier: str) -> None:
    env = _ok(
        adversarial_rig,
        obligations=[_so2(tier)],
        measurement={"so2_ppm": 150},
        llm_output=_output(
            "CLEAR",
            ["so2.cap"],
            [
                _assertion("must_not_exceed", "so2_ppm", 100, 150, "so2.cap"),
                _assertion("must_be_reasonable", "so2_ppm", None, 150, "so2.cap"),
            ],
        ),
    )
    assert env["verdict"] != "CLEAR"
    # Contradictions take precedence over UNVERIFIABLE.
    assert env["verifier_result"]["status"] == "LLM_CONTRADICTION"


@pytest.mark.parametrize("tier", TIERS)
def test_junk_predicate_alone_is_never_clear(adversarial_rig: AdversarialRig, tier: str) -> None:
    """No breach: an out-of-enum predicate is a schema violation (spec §3.3),
    routed to human review rather than accepted as merely unverifiable."""
    env = _ok(
        adversarial_rig,
        obligations=[_so2(tier)],
        measurement={"so2_ppm": 50},
        llm_output=_output(
            "CLEAR",
            ["so2.cap"],
            [
                _assertion("must_not_exceed", "so2_ppm", 100, 50, "so2.cap"),
                _assertion("must_be_reasonable", "so2_ppm", None, 50, "so2.cap"),
            ],
        ),
    )
    assert env["verdict"] == "DISCRETIONARY"


@pytest.mark.parametrize("tier", TIERS)
def test_omitted_breach_is_never_clear(adversarial_rig: AdversarialRig, tier: str) -> None:
    env = _ok(
        adversarial_rig,
        obligations=[_so2(tier), _nox(tier)],
        measurement={"so2_ppm": 150, "nox_ppm": 10},
        llm_output=_output(
            "CLEAR",
            ["nox.cap"],
            [_assertion("must_not_exceed", "nox_ppm", 50, 10, "nox.cap")],
        ),
    )
    assert env["verdict"] != "CLEAR"
    result = env["verifier_result"]
    assert result["status"] == "LLM_CONTRADICTION"
    assert any("OMITTED_OBLIGATION" in d and "so2.cap" in d for d in result["divergences"]), result


@pytest.mark.parametrize("tier", TIERS)
def test_omitted_satisfied_obligation_does_not_block_clear(
    adversarial_rig: AdversarialRig, tier: str
) -> None:
    """Control: independent enumeration of a *satisfied* omitted obligation
    leaves an honest CLEAR alone."""
    env = _ok(
        adversarial_rig,
        obligations=[_so2(tier), _nox(tier)],
        measurement={"so2_ppm": 90, "nox_ppm": 10},
        llm_output=_output(
            "CLEAR",
            ["nox.cap"],
            [_assertion("must_not_exceed", "nox_ppm", 50, 10, "nox.cap")],
        ),
    )
    assert env["verdict"] == "CLEAR"
    assert env["verifier_result"]["status"] == "AGREED"


@pytest.mark.parametrize("tier", TIERS)
def test_clear_resting_on_an_asserted_breach_is_never_clear(
    adversarial_rig: AdversarialRig, tier: str
) -> None:
    env = _ok(
        adversarial_rig,
        obligations=[_so2(tier)],
        measurement={"so2_ppm": 150},
        llm_output=_output(
            "CLEAR", ["so2.cap"], [_assertion("must_not_exceed", "so2_ppm", 100, 150, "so2.cap")]
        ),
    )
    assert env["verdict"] != "CLEAR"


@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.parametrize(
    "llm_output",
    [
        _output("NULL_UNMAPPED", [], []),
        _output("CLEAR", ["no.such.node"], []),
    ],
    ids=["null-unmapped", "bogus-citation"],
)
def test_a_mapped_breach_cannot_be_reported_unmapped(
    adversarial_rig: AdversarialRig, tier: str, llm_output: Dict[str, Any]
) -> None:
    env = _ok(adversarial_rig, obligations=[_so2(tier)], measurement={"so2_ppm": 150}, llm_output=llm_output)
    assert env["verdict"] not in ("CLEAR", "NULL_UNMAPPED")


def _qualitative_case(tier: Any) -> Dict[str, Any]:
    review: Dict[str, Any] = {"id": "so2.review", "metric": "so2_ppm", "predicate": "discretionary"}
    obligations = [_so2(None), review]
    for ob in obligations:
        if tier is not None:
            ob["risk_tier"] = tier
    return {
        "obligations": obligations,
        "measurement": {"so2_ppm": 50},
        "llm_output": _output(
            "CLEAR",
            ["so2.cap", "so2.review"],
            [
                _assertion("must_not_exceed", "so2_ppm", 100, 50, "so2.cap"),
                _assertion("discretionary", "so2_ppm", None, 50, "so2.review"),
            ],
        ),
    }


@pytest.mark.parametrize("tier", [None, "critical", "tier-99", 7])
def test_missing_or_unknown_tier_is_the_strictest(adversarial_rig: AdversarialRig, tier: Any) -> None:
    """An UNVERIFIABLE (qualitative) CLEAR is accepted at tier-2/3 but not at
    tier-1; a missing or unrecognised tier must get the tier-1 treatment."""
    env = _ok(adversarial_rig, **_qualitative_case(tier))
    assert env["verifier_result"]["status"] == "UNVERIFIABLE"
    assert env["verdict"] == "DISCRETIONARY"


def test_declared_lower_tier_still_honoured(adversarial_rig: AdversarialRig) -> None:
    """Control for the case above: the same output at a declared tier-2."""
    env = _ok(adversarial_rig, **_qualitative_case("tier-2"))
    assert env["verifier_result"]["status"] == "UNVERIFIABLE"
    assert env["verdict"] == "CLEAR"


@pytest.mark.parametrize(
    "measurement",
    [{"so2_ppm": -math.inf}, {"so2_ppm": math.inf}, {"so2_ppm": math.nan}, {"so2_ppm": True}],
    ids=["-Infinity", "Infinity", "NaN", "bool"],
)
def test_unusable_readings_are_rejected(adversarial_rig: AdversarialRig, measurement: Dict[str, Any]) -> None:
    status, body = adversarial_rig.evaluate(
        obligations=[_so2("tier-3")],
        measurement=measurement,
        llm_output=_output(
            "CLEAR", ["so2.cap"], [_assertion("must_not_exceed", "so2_ppm", 100, 0, "so2.cap")]
        ),
    )
    assert status == 422, (status, body)


@pytest.mark.parametrize(
    "timestamp", ["not-a-timestamp", "2026-01-15T12:00:00"], ids=["malformed", "no-timezone"]
)
def test_unusable_timestamps_are_rejected(adversarial_rig: AdversarialRig, timestamp: str) -> None:
    status, body = adversarial_rig.evaluate(
        obligations=[_so2("tier-3")],
        measurement={"so2_ppm": 50},
        llm_output=_output(
            "CLEAR", ["so2.cap"], [_assertion("must_not_exceed", "so2_ppm", 100, 50, "so2.cap")]
        ),
        timestamp=timestamp,
    )
    assert status == 422, (status, body)
