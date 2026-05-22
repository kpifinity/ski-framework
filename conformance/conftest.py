"""Conformance-suite pytest fixtures.

The suite is intentionally black-box. Tests that need a live deployment
talk to it over HTTPS using the `ski-endpoint` and `api-key` options.
Tests that need to inspect the audit ledger talk to it via SQL using
`ledger-dsn`. Tests that exercise only static artefacts (e.g. the demo
KGs or the SQL schema) do not need any of these.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def pytest_addoption(parser: "pytest.Parser") -> None:
    parser.addoption("--ski-endpoint", default=os.getenv("SKI_ENDPOINT"), help="Live SKI Model endpoint (e.g. https://localhost:8000)")
    parser.addoption("--api-key", default=os.getenv("SKI_API_KEY"), help="API key for the live SKI Model.")
    parser.addoption("--ledger-dsn", default=os.getenv("LEDGER_DSN"), help="PostgreSQL DSN for the audit ledger.")
    parser.addoption("--insecure", action="store_true", default=True, help="Skip TLS verification (self-signed certs).")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def ski_endpoint(pytestconfig: "pytest.Config") -> Optional[str]:
    return pytestconfig.getoption("--ski-endpoint")


@pytest.fixture(scope="session")
def api_key(pytestconfig: "pytest.Config") -> Optional[str]:
    return pytestconfig.getoption("--api-key")


@pytest.fixture(scope="session")
def ledger_dsn(pytestconfig: "pytest.Config") -> Optional[str]:
    return pytestconfig.getoption("--ledger-dsn")


@pytest.fixture(scope="session")
def insecure(pytestconfig: "pytest.Config") -> bool:
    return pytestconfig.getoption("--insecure")


@pytest.fixture
def require_live(ski_endpoint: Optional[str], api_key: Optional[str]) -> tuple[str, str]:
    if not ski_endpoint or not api_key:
        pytest.skip("Live deployment fixtures not provided (--ski-endpoint, --api-key).")
    return ski_endpoint, api_key


@pytest.fixture
def require_ledger(ledger_dsn: Optional[str]) -> str:
    if not ledger_dsn:
        pytest.skip("Ledger DSN not provided (--ledger-dsn).")
    return ledger_dsn
