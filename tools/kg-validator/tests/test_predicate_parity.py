"""Validator ↔ verifier predicate parity.

A customer authoring a KG must never hit the gap eval-era audits found:
predicates the validator accepts but the verifier silently cannot check
(degrading every verdict to UNVERIFIABLE), or predicates the runtime
checks that the validator rejects. This pins both directions.
"""

from __future__ import annotations

import pytest
from kg_validator.models import ObligationType

pytest.importorskip("ski_model.v3.verifier")

from ski_model.v3 import verifier as v

# Spec §3.3 types that are deliberately NOT mechanically checkable:
# judgment / routing semantics, or temporal-evidence checks that need
# the recording pipeline rather than a measurement.
_INTENTIONALLY_NON_MECHANICAL = {
    "must",
    "must_not",
    "must_be_recorded_within",
    "should",
    "discretionary",
}


def test_every_other_obligation_type_is_verifier_checkable() -> None:
    checkable = set(v._STATELESS_PREDICATES) | set(v._STATEFUL_PREDICATES)
    for t in ObligationType:
        if t.value in _INTENTIONALLY_NON_MECHANICAL:
            continue
        assert t.value in checkable, (
            f"validator accepts {t.value!r} but the Symbolic Verifier cannot check it - "
            "customers would author obligations that silently verify nothing."
        )


def test_every_verifier_predicate_is_a_valid_obligation_type() -> None:
    valid = {t.value for t in ObligationType}
    for name in set(v._STATELESS_PREDICATES) | set(v._STATEFUL_PREDICATES):
        assert name in valid, (
            f"the verifier checks {name!r} but the validator rejects it - "
            "customers could not validate KGs the runtime supports."
        )


def test_stateless_predicates_all_have_handlers() -> None:
    assert set(v._PREDICATE_HANDLERS) == set(v._STATELESS_PREDICATES)
