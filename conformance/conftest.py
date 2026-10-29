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


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--ski-endpoint",
        default=os.getenv("SKI_ENDPOINT"),
        help="Live SKI Model endpoint (e.g. https://localhost:8000)",
    )
    parser.addoption("--api-key", default=os.getenv("SKI_API_KEY"), help="API key for the live SKI Model.")
    parser.addoption(
        "--ledger-dsn", default=os.getenv("LEDGER_DSN"), help="PostgreSQL DSN for the audit ledger."
    )
    # TLS verification is ON by default (it was stuck on "skip" up to v3.1.x:
    # store_true with default=True could never be turned off). Trust a private
    # CA with SSL_CERT_FILE=/path/to/ca.crt; --insecure is the explicit opt-out.
    parser.addoption(
        "--insecure",
        action="store_true",
        default=False,
        help="Skip TLS certificate verification (explicit opt-in, local testing only). "
        "Prefer SSL_CERT_FILE=<ca.crt> to trust a self-signed CA.",
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def ski_endpoint(pytestconfig: pytest.Config) -> Optional[str]:
    value: Optional[str] = pytestconfig.getoption("--ski-endpoint")
    return value


@pytest.fixture(scope="session")
def api_key(pytestconfig: pytest.Config) -> Optional[str]:
    value: Optional[str] = pytestconfig.getoption("--api-key")
    return value


@pytest.fixture(scope="session")
def ledger_dsn(pytestconfig: pytest.Config) -> Optional[str]:
    value: Optional[str] = pytestconfig.getoption("--ledger-dsn")
    return value


@pytest.fixture(scope="session")
def insecure(pytestconfig: pytest.Config) -> bool:
    value: bool = pytestconfig.getoption("--insecure")
    return value


@pytest.fixture
def require_live(ski_endpoint: Optional[str], api_key: Optional[str]) -> tuple[str, str]:
    if not ski_endpoint or not api_key:
        pytest.skip("Live deployment fixtures not provided (--ski-endpoint, --api-key).")
    # pytest.skip raises; mypy doesn't always recognize the NoReturn,
    # so narrow explicitly here.
    assert ski_endpoint is not None
    assert api_key is not None
    return ski_endpoint, api_key


@pytest.fixture
def require_ledger(ledger_dsn: Optional[str]) -> str:
    if not ledger_dsn:
        pytest.skip("Ledger DSN not provided (--ledger-dsn).")
    assert ledger_dsn is not None
    return ledger_dsn
