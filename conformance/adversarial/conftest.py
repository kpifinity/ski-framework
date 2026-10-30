"""Adversarial-backend rig for the fail-closed verifier conformance cases.

The cases in this package are implementation-neutral. They speak only the
wire contract: a flat-shape list of KG obligations, a ``MeasurementRecord``
JSON body for ``POST /api/evaluate``, a scripted raw LLM output (the
response-grammar shape of spec §4.4) and the ``V3VerdictEnvelope`` JSON that
comes back. They never read implementation source.

What they need from an implementation is a way to put a *scripted*
(adversarial) LLM behind its evaluate endpoint -- something no live
deployment exposes. The ``adversarial_rig`` fixture provides that:

* By default it drives the reference implementation in-process: its ASGI
  app, with the LLM backend swapped for a scripted one, the given
  obligations as the loaded KG, and an in-memory ledger. This fixture is
  the only code in the package that touches the reference implementation.
* Another implementation plugs in its own rig by setting
  ``SKI_CONFORMANCE_ADVERSARIAL_RIG=package.module:factory``, where
  ``factory()`` returns an object with the :class:`AdversarialRig`
  interface.
"""

from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Protocol, Tuple

import pytest


class AdversarialRig(Protocol):
    def evaluate(
        self,
        *,
        obligations: List[Dict[str, Any]],
        measurement: Dict[str, Any],
        llm_output: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> Tuple[int, Any]:
        """POST one measurement with ``llm_output`` scripted as the model's raw
        response; return ``(http_status, parsed JSON body)``. ``timestamp``
        defaults to the current UTC time."""
        ...


class _InMemoryLedger:
    def __init__(self) -> None:
        self.appended: List[Dict[str, Any]] = []

    async def append_v3(self, **kwargs: Any) -> None:
        self.appended.append(kwargs)

    async def list(self, *, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        return self.appended[offset : offset + limit]


_STATE_FIELDS = (
    "knowledge_graph",
    "tag_registry",
    "ledger",
    "llm_backend",
    "evaluator",
    "telemetry_buffer",
    "kg_version_hash",
    "agreement_monitor",
    "verdicts_produced",
)


class _ReferenceImplementationRig:
    """In-process rig for the reference implementation (``ski_model``)."""

    def __init__(self) -> None:
        from fastapi.testclient import TestClient
        from ski_model import server
        from ski_model.kg_loader import KnowledgeGraph
        from ski_model.v3 import FakeLLM, V3Evaluator

        class _ScriptedLLM(FakeLLM):
            def __init__(self, raw: Dict[str, Any]) -> None:
                super().__init__()
                self._raw = raw

            async def evaluate(
                self, *, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any], seed: int
            ) -> Dict[str, Any]:
                copy: Dict[str, Any] = json.loads(json.dumps(self._raw))
                return copy

        self._server = server
        self._kg_cls = KnowledgeGraph
        self._evaluator_cls = V3Evaluator
        self._scripted_cls = _ScriptedLLM
        # The lifespan (key provisioning, Postgres) is deliberately not run.
        self._client = TestClient(server.app, raise_server_exceptions=False)

    def evaluate(
        self,
        *,
        obligations: List[Dict[str, Any]],
        measurement: Dict[str, Any],
        llm_output: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> Tuple[int, Any]:
        server = self._server
        state = server.state
        saved = {name: getattr(state, name) for name in _STATE_FIELDS}
        llm = self._scripted_cls(llm_output)
        evaluator = self._evaluator_cls(llm=llm, kg_version_hash="sha256:" + "0" * 64)
        app = server.app
        overrides_before = dict(app.dependency_overrides)
        try:
            state.knowledge_graph = self._kg_cls(
                version="conformance-adversarial",
                rules=obligations,
                tag_registry={},
                metadata={"version": "conformance-adversarial"},
                signature_verified=True,
            )
            state.tag_registry = None
            state.ledger = _InMemoryLedger()
            state.llm_backend = llm
            state.evaluator = evaluator
            state.telemetry_buffer = None
            state.kg_version_hash = evaluator.kg_version_hash
            state.agreement_monitor = None
            app.dependency_overrides[server.require_api_key] = lambda: None
            body = json.dumps(
                {
                    "measurement_id": "conformance-adversarial",
                    "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                    "subject": "conformance",
                    "measurement": measurement,
                },
                allow_nan=True,
            )
            resp = self._client.post(
                "/api/evaluate", content=body, headers={"content-type": "application/json"}
            )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(overrides_before)
            for name, value in saved.items():
                setattr(state, name, value)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text


def _load_rig() -> AdversarialRig:
    spec = os.getenv("SKI_CONFORMANCE_ADVERSARIAL_RIG")
    if spec:
        module_name, _, attr = spec.partition(":")
        factory = getattr(importlib.import_module(module_name), attr or "make_rig")
        rig: AdversarialRig = factory()
        return rig
    try:
        return _ReferenceImplementationRig()
    except ImportError as exc:  # pragma: no cover - depends on the environment
        pytest.skip(
            f"No adversarial rig: reference implementation not importable ({exc}); "
            "set SKI_CONFORMANCE_ADVERSARIAL_RIG=module:factory for another implementation."
        )


@pytest.fixture(scope="module")
def adversarial_rig() -> Iterator[AdversarialRig]:
    yield _load_rig()
