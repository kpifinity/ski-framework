"""Fuzzing the §7.3 canonicalizer: any JSON value either canonicalizes consistently or is refused cleanly.

Every hash in SKI (ledger entries, KG versions, envelopes, transcripts) runs
through ``ski_schemas.canonical``, so it must never crash on odd input, never
emit two forms for one value, and never emit bytes that do not parse back to
the same value. ``SKI_FUZZ_EXAMPLES`` raises the example count (the nightly
quality job runs it high).
"""

from __future__ import annotations

import contextlib
import json
import math
import os
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from ski_schemas.canonical import CanonicalizationError, canonicalize, canonicalize_json_text

_EXAMPLES = int(os.environ.get("SKI_FUZZ_EXAMPLES", "300"))
_SETTINGS = settings(max_examples=_EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])

_scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**60), max_value=2**60)
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.text()
)
_json = st.recursive(
    _scalars,
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=8), children, max_size=5)
    ),
    max_leaves=25,
)


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    return True


@_SETTINGS
@given(_json)
def test_canonical_form_round_trips_and_is_idempotent(value: Any) -> None:
    try:
        out = canonicalize(value)
    except CanonicalizationError:
        return  # refused cleanly (non-finite numbers, lone surrogates, unsafe integers)
    assert _finite(value), "a non-finite number must be refused, not encoded"
    # Re-read as RFC 8785 consumers do (numbers are doubles, as JSON.parse
    # reads them): a large float's shortest form, e.g. 57615084498456540, is
    # not an exactly representable *integer* for Python's json.loads.
    assert canonicalize_json_text(out) == out  # one value, one form
    json.loads(out)  # and it is plain JSON
    assert out == out.decode("utf-8").encode("utf-8")


@_SETTINGS
@given(st.text(max_size=200))
def test_arbitrary_text_is_parsed_or_refused_cleanly(text: str) -> None:
    try:
        out = canonicalize_json_text(text)
    except (CanonicalizationError, ValueError):
        return
    assert canonicalize_json_text(out) == out


@_SETTINGS
@given(_json)
def test_key_order_never_changes_the_form(value: Any) -> None:
    if not isinstance(value, dict) or len(value) < 2:
        return
    reordered = dict(reversed(list(value.items())))
    with contextlib.suppress(CanonicalizationError):
        assert canonicalize(value) == canonicalize(reordered)
