"""Run the black-box suite against the reference implementation.

This adapter is the only part of the black-box run that knows the reference
implementation: it starts the scripted LLM, prepares an EMPTY Postgres
database as a ledger, boots ``ski_model.server`` configured to use them, runs
``pytest conformance/blackbox`` against it over HTTP, and stops everything.
An adapter for another implementation does the same with that
implementation's start-up.

    python conformance/blackbox/adapters/reference.py \\
        --ledger-dsn postgresql://postgres:pw@127.0.0.1:5432/ski_bb [-- PYTEST_ARGS...]

The database must be empty and disposable (the ledger is append-only, so the
run cannot clean up after itself). ``--python`` is an interpreter with the
reference implementation installed (default: this one).
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SUITE = HERE.parent
REPO = SUITE.parents[1]
LEDGER_SQL = REPO / "reference-implementation" / "src" / "ledger"
_SCHEMA_FILES = [
    LEDGER_SQL / "schema.sql",
    LEDGER_SQL / "append_only.sql",
    LEDGER_SQL / "migrations" / "0002_transcript_columns.sql",
    LEDGER_SQL / "migrations" / "0003_ledger_v5.sql",
    LEDGER_SQL / "telemetry_buffer.sql",
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def _wait(url: str, what: str, proc: subprocess.Popen[bytes], timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"{what} exited with {proc.returncode} before it was ready")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{what} not ready at {url} after {timeout}s")


def _apply_schema(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute("SELECT to_regclass('ledger_entries')").fetchone()
        if row is not None and row[0] is not None:
            raise SystemExit("The ledger database is not empty; give the adapter a fresh database.")
        for path in _SCHEMA_FILES:
            conn.execute(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ledger-dsn", required=True, help="An EMPTY, disposable Postgres database.")
    parser.add_argument("--python", default=sys.executable, help="Interpreter with ski_model installed.")
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args()

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", args.ledger_dsn)
    _apply_schema(dsn)

    work = Path(tempfile.mkdtemp(prefix="ski-blackbox-"))
    subprocess.run([sys.executable, str(SUITE / "prepare.py"), str(work)], check=True)
    api_key = secrets.token_hex(24)
    llm_port, sut_port = _free_port(), _free_port()
    llm_url, sut_url = f"http://127.0.0.1:{llm_port}", f"http://127.0.0.1:{sut_port}"
    log = open(work / "sut.log", "wb")  # noqa: SIM115 (kept open for the subprocesses)

    llm = subprocess.Popen(
        [sys.executable, str(SUITE / "scripted_llm.py"), "blackbox-model", str(llm_port)], stderr=log
    )
    pythonpath = os.pathsep.join(
        [str(REPO / "reference-implementation" / "src"), str(REPO / "tools" / "ski-schemas" / "src")]
        + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])
    )
    env = {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "HOST": "127.0.0.1",
        "PORT": str(sut_port),
        "TLS_ENABLED": "false",
        "API_KEY": api_key,
        "LEDGER_DSN": "postgresql+psycopg://" + dsn.split("://", 1)[1],
        "KG_PATH": str(work / "kg.json"),
        "KG_REQUIRE_SIGNATURE": "true",
        "SKI_KG_TRUST_ANCHORS": str(work / "kg-trust-anchor.pem"),
        "SKI_TRANSCRIPT_KEY_PATH": str(work / "transcript.ed25519"),
        "SKI_ALLOW_KEY_GENERATION": "true",
        "SKI_V3_LLM_BACKEND": "vllm",
        "VLLM_BASE_URL": llm_url,
        "SKI_MODEL_NAME": "blackbox-model",
        "SKI_SOVEREIGNTY": "advisory",
        "SKI_LEDGER_CHECKPOINT_EVERY": "2",
    }
    sut = None
    try:
        _wait(f"{llm_url}/v1/models", "scripted LLM", llm)
        sut = subprocess.Popen([args.python, "-m", "ski_model.server"], env=env, stdout=log, stderr=log)
        _wait(f"{sut_url}/api/health", "reference implementation", sut)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(SUITE),
                "-p",
                "no:cacheprovider",
                f"--ski-endpoint={sut_url}",
                f"--api-key={api_key}",
                f"--scripted-llm={llm_url}",
                f"--kg-fixture={work / 'kg.json'}",
                f"--ledger-dsn={dsn}",
                *args.pytest_args,
            ],
            cwd=REPO,
        )
        return result.returncode
    finally:
        for proc in (sut, llm):
            if proc is not None:
                proc.terminate()
                proc.wait(timeout=30)
        log.close()
        print(f"implementation log: {work / 'sut.log'}")


if __name__ == "__main__":
    raise SystemExit(main())
