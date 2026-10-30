"""The quickstart walkthrough's Knowledge Graph overview renders the in-scope rules.

Regression: it iterated the scoped obligations (dicts) as if they were ids
and crashed with ``TypeError: unhashable type: 'dict'`` before the
walkthrough began.
"""

from __future__ import annotations

import pytest
from rich.console import Console

import quickstart


def test_kg_overview_lists_every_rule_in_force(monkeypatch: pytest.MonkeyPatch) -> None:
    console = Console(record=True, width=200)
    monkeypatch.setattr(quickstart, "CONSOLE", console)
    kg = quickstart._load_kg()
    quickstart._show_kg_overview(kg)
    text = console.export_text()

    in_force = kg.scope_to(jurisdiction=quickstart.JURISDICTION, as_of=quickstart.AS_OF)["obligations"]
    assert in_force, "the demo KG has rules in force at the quickstart date"
    for ob in in_force:
        assert ob["id"] in text
    assert "≤ 100 ppm" in text  # energy.so2.cap, from the KG's own predicate / value / unit
    assert "6.0 - 8.5 pH" in text  # energy.ph.range
    assert f"{len(in_force)} rules currently in force" in text


@pytest.mark.parametrize(
    "ob, expected",
    [
        ({"predicate": "must_not_exceed", "value": 100, "unit": "ppm"}, "≤ 100 ppm"),
        ({"predicate": "must_be_at_least", "value": 10, "unit": "m3/h"}, "≥ 10 m3/h"),
        ({"predicate": "must_be_within", "value": [5, 40], "unit": "C"}, "5 - 40 C"),
        ({"predicate": "must", "value": None}, ""),
    ],
)
def test_limit_text(ob: dict, expected: str) -> None:
    assert quickstart._limit_text(ob) == expected
