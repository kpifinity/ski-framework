"""Fuzzing the KG loader: any document is either loaded or refused with a ValueError, never crashes.

The KG is operator input and the trust boundary of every verdict, so a
malformed KG must fail closed with a clear error, not an ``AttributeError``
or ``KeyError`` from deep inside the compiler. Documents are drawn half from
graph-shaped and half from flat-shaped skeletons with arbitrary values, so
the fuzzer reaches the compiler rather than stopping at the top-level shape
check. ``KGTrustError`` is a ``ValueError``. ``SKI_FUZZ_EXAMPLES`` raises the
example count (the nightly quality job runs it high).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ski_model.kg_loader import KGTrustPolicy, KnowledgeGraph

_EXAMPLES = int(os.environ.get("SKI_FUZZ_EXAMPLES", "300"))
_SETTINGS = settings(max_examples=_EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
_POLICY = KGTrustPolicy(allow_unanchored=True)

_scalar = st.none() | st.booleans() | st.integers(-5, 5) | st.floats(allow_nan=False) | st.text(max_size=6)
_value = st.recursive(
    _scalar,
    lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=6), c, max_size=3),
    max_leaves=8,
)
_ids = st.sampled_from(["a", "b", "r", "ob", "s", "us", ""])
_node = st.fixed_dictionaries(
    {"id": _ids | _value},
    optional={
        "type": st.text(max_size=8),
        "obligation_type": st.sampled_from(["must_not_exceed", "must_be_within", "x"]) | _value,
        "metric": st.sampled_from(["so2_ppm", ""]) | _value,
        "value": _value,
        "risk_tier": st.sampled_from(["high", "low", "tier-1"]) | _value,
        "effective_date_start": st.sampled_from(["2026-01-01T00:00:00Z", "bad"]) | _value,
        "parent": _ids | _value,
    },
)
_edge = st.fixed_dictionaries(
    {
        "type": st.sampled_from(["applies_to", "consists_of", "scoped_to", "cited_by"]) | _value,
        "from": _ids | _value,
        "to": _ids | _value,
    }
)
_graph = st.fixed_dictionaries(
    {
        "metadata": st.dictionaries(st.sampled_from(["name", "version"]), _value, max_size=2) | _value,
        "nodes": st.dictionaries(
            st.sampled_from(["subjects", "rules", "obligations", "definitions", "jurisdictions", "widgets"]),
            st.lists(_node, max_size=3) | _value,
            max_size=4,
        )
        | _value,
        "edges": st.lists(_edge | _value, max_size=5) | _value,
    }
)
_flat = st.fixed_dictionaries(
    {
        "metadata": st.dictionaries(st.sampled_from(["version"]), _value, max_size=1) | _value,
        "rules": st.lists(_node, max_size=3) | _value,
        "tag_registry": st.dictionaries(st.text(max_size=4), _ids | _value, max_size=3) | _value,
    }
)


@_SETTINGS
@given(_graph | _flat | st.dictionaries(st.text(max_size=8), _value, max_size=4))
def test_any_kg_document_is_loaded_or_refused_with_a_value_error(document: Any) -> None:
    try:
        kg = KnowledgeGraph.from_dict(document, require_signature=False, trust=_POLICY)
    except ValueError:
        return  # refused cleanly (KGTrustError, malformed graph, bad shape)
    # Whatever loads must also scope without crashing.
    kg.scope_to(jurisdiction=None, as_of=datetime(2026, 6, 1, tzinfo=timezone.utc), subject="s")
    assert kg.version_hash is None or kg.version_hash.startswith("sha256:")
