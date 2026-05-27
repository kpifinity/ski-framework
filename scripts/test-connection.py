#!/usr/bin/env python3
"""test-connection.py — verify the stack's components can talk to each other.

Checks:
  * SKI Model /api/health
  * Sidecar /health
  * Postgres reachability via LEDGER_DSN
  * Ollama backend reachability if SKI_INFERENCE_BACKEND=ollama
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Tuple

import httpx


def check_http(name: str, url: str, *, verify: bool, api_key: str | None) -> Tuple[bool, str]:
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        resp = httpx.get(url, headers=headers, timeout=5.0, verify=verify)
        return resp.status_code == 200, f"{resp.status_code} {resp.reason_phrase}"
    except Exception as exc:
        return False, str(exc)


def check_postgres(dsn: str) -> Tuple[bool, str]:
    if not dsn:
        return False, "LEDGER_DSN not set"
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(dsn.replace("postgresql+psycopg://", "postgresql://", 1))
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "OK"
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ski-model", default=os.getenv("SKI_MODEL_ENDPOINT", "https://localhost:8000"))
    p.add_argument("--sidecar", default=os.getenv("SIDECAR_ENDPOINT", "http://localhost:8001"))
    p.add_argument("--ollama", default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--api-key", default=os.getenv("SKI_API_KEY", ""))
    args = p.parse_args()

    verify = not args.insecure
    checks = [
        ("SKI Model", args.ski_model.rstrip("/") + "/api/health", verify),
        ("Sidecar", args.sidecar.rstrip("/") + "/health", True),
        ("Ollama", args.ollama.rstrip("/") + "/api/tags", True),
    ]
    ok = True
    for name, url, v in checks:
        passed, info = check_http(name, url, verify=v, api_key=args.api_key if name == "SKI Model" else None)
        print(f"  {'OK ' if passed else 'FAIL'}  {name:<10} {url}  ({info})")
        ok = ok and passed

    pg_ok, pg_info = check_postgres(os.getenv("LEDGER_DSN", ""))
    print(f"  {'OK ' if pg_ok else 'FAIL'}  Postgres   LEDGER_DSN  ({pg_info})")
    ok = ok and pg_ok

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
