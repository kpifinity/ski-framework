"""Fixtures for the black-box suite: the implementation under test, its scripted LLM, its KG and its ledger.

Options (each also read from the environment):

* ``--ski-endpoint`` / ``--api-key`` (``SKI_ENDPOINT`` / ``SKI_API_KEY``):
  the implementation's HTTP API (``spec/contracts/openapi.yaml``);
* ``--scripted-llm`` (``SKI_SCRIPTED_LLM``): base URL of the
  ``scripted_llm.py`` server the implementation uses as its language model;
* ``--kg-fixture`` (``SKI_KG_FIXTURE``): the ``kg.json`` written by
  ``prepare.py`` that the implementation loaded;
* ``--ledger-dsn`` / ``--ledger-table`` (``LEDGER_DSN`` /
  ``SKI_LEDGER_TABLE``): the ledger, for the storage-layer append-only
  checks (spec §7.2) only.

Live tests skip, not fail, when their options are missing.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest

from .checkers import kg_version_hash

TOKEN_FIELD = "conformance_token"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SUT:
    """The implementation under test, driven over HTTP, with its LLM answers scripted."""

    def __init__(self, endpoint: str, api_key: str, llm: str, kg: dict[str, Any], verify: bool) -> None:
        self.http = httpx.Client(
            base_url=endpoint.rstrip("/"), headers={"x-api-key": api_key}, verify=verify, timeout=60
        )
        self.llm = httpx.Client(base_url=llm.rstrip("/"), timeout=10)
        self.kg = kg
        self.kg_version_hash = kg_version_hash(kg)
        self.node_ids = {n["id"] for nodes in kg["nodes"].values() for n in nodes}

    @staticmethod
    def token() -> str:
        return f"bb-{uuid.uuid4().hex}"

    def script(self, token: str, content: str | dict[str, Any]) -> None:
        text = content if isinstance(content, str) else json.dumps(content)
        self.llm.post("/__script", json={"token": token, "content": text}).raise_for_status()

    def llm_requests(self, token: str) -> list[str]:
        response = self.llm.get("/__requests", params={"token": token})
        response.raise_for_status()
        requests: list[str] = response.json()
        return requests

    def evaluate(self, token: str, subject: str, measurement: dict[str, Any]) -> httpx.Response:
        # The token rides in the measurement object, which every prompt carries (spec §5.2), as a
        # field no obligation maps; it is also the record's id, so the ledger entry can be found.
        values = {**measurement, TOKEN_FIELD: token}
        record = {"measurement_id": token, "timestamp": _now(), "subject": subject, "measurement": values}
        return self.http.post("/api/evaluate", json=record)

    def envelope(self, token: str, subject: str, measurement: dict[str, Any], answer: Any) -> dict[str, Any]:
        """Script ``answer`` (None = leave unscripted), evaluate, and return the 200 envelope."""
        if answer is not None:
            self.script(token, answer)
        response = self.evaluate(token, subject, measurement)
        assert response.status_code == 200, f"/api/evaluate returned {response.status_code}: {response.text}"
        envelope: dict[str, Any] = response.json()
        return envelope


@pytest.fixture(scope="session")
def kg_fixture(pytestconfig: pytest.Config) -> Optional[dict[str, Any]]:
    path = pytestconfig.getoption("--kg-fixture")
    if not path:
        return None
    kg: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return kg


@pytest.fixture(scope="session")
def sut(pytestconfig: pytest.Config, kg_fixture: Optional[dict[str, Any]]) -> SUT:
    endpoint = pytestconfig.getoption("--ski-endpoint")
    api_key = pytestconfig.getoption("--api-key")
    llm = pytestconfig.getoption("--scripted-llm")
    if not (endpoint and api_key and llm and kg_fixture):
        pytest.skip("Black-box run not configured (--ski-endpoint, --api-key, --scripted-llm, --kg-fixture).")
    return SUT(endpoint, api_key, llm, kg_fixture, verify=not pytestconfig.getoption("--insecure"))


@pytest.fixture(scope="session")
def ledger_table(pytestconfig: pytest.Config) -> str:
    table: str = pytestconfig.getoption("--ledger-table")
    return table
