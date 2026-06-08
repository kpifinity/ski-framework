"""Functional sovereignty proof — a CLEAR-path evaluation makes no network egress.

Pairs with ``conformance/sovereignty/test_no_outbound_calls.py`` (which
asserts the boundary structurally, black-box). Here we block every
outbound TCP connect and prove a full evaluation still completes on the
default ``FakeLLM`` backend — i.e. the sovereign path touches no network.
"""

from __future__ import annotations

import socket

import pytest

from ski_model.v3 import FakeLLM, V3Evaluator

_SNAPSHOT = {
    "version": "demo",
    "obligations": [
        {"id": "energy.so2.lte_100ppm", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
    ],
}


async def test_clear_path_makes_no_network_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("outbound network egress attempted during a CLEAR-path evaluation")

    monkeypatch.setattr(socket.socket, "connect", _blocked, raising=False)
    monkeypatch.setattr(socket, "create_connection", _blocked, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked, raising=False)

    evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash="sha256:" + "0" * 64, decoder_seed=0)
    env = await evaluator.aevaluate(measurement={"so2_ppm": 50}, kg_snapshot=_SNAPSHOT)

    assert env.verdict == "CLEAR"
    assert [c.node_id for c in env.kg_citations] == ["energy.so2.lte_100ppm"]
