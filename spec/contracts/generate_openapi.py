#!/usr/bin/env python3
"""Generate the public OpenAPI 3.1 contract for the SKI Model API.

Derived from FastAPI's ``app.openapi()`` so it cannot drift from the live
server, then pruned to the three public paths and the components they
reference. Run this to (re)write ``spec/contracts/openapi.yaml``.

Public paths: ``POST /api/evaluate``, ``GET /api/health``,
``POST /api/kg/load``. The operational endpoints (``/api/verdicts``,
``/api/canary``, ``/metrics``) are intentionally excluded from the public
contract.

Importing the server requires the v3.2.0 fail-closed startup escape hatches
``SKI_ALLOW_FAKE_LLM`` and ``SKI_ALLOW_KEY_GENERATION``; this script sets
them in-process before import. They affect only this generator process and
never a running server.

Usage::

    python spec/contracts/generate_openapi.py           # write the file
    python spec/contracts/generate_openapi.py --check     # exit 1 if stale
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_SRCS = [
    _REPO_ROOT / "reference-implementation" / "src",
    _REPO_ROOT / "tools" / "ski-schemas" / "src",
    _REPO_ROOT / "tools" / "audit-ledger" / "src",
    _REPO_ROOT / "tools" / "ski-model-deploy" / "src",
    _REPO_ROOT / "tools" / "kg-validator" / "src",
    _REPO_ROOT / "tools" / "kg-extractor" / "src",
    _REPO_ROOT / "tools" / "ski-sdk" / "src",
]
for _src in _TOOL_SRCS:
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# The v3.2.0 runtime refuses to import some paths without these set.
os.environ.setdefault("SKI_ALLOW_FAKE_LLM", "true")
os.environ.setdefault("SKI_ALLOW_KEY_GENERATION", "true")

PUBLIC_PATHS = ("/api/evaluate", "/api/health", "/api/kg/load")

OPENAPI_PATH = Path(__file__).resolve().parent / "openapi.yaml"


def _collect_refs(node: Any, acc: set[str]) -> None:
    """Walk ``node`` collecting every ``#/components/schemas/<name>`` ref."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            acc.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _collect_refs(value, acc)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, acc)


def _transitive_schemas(paths: dict[str, Any], all_schemas: dict[str, Any]) -> dict[str, Any]:
    """Return only the component schemas reachable from ``paths`` (transitively)."""
    seen: set[str] = set()
    frontier: set[str] = set()
    _collect_refs(paths, frontier)
    while frontier:
        name = frontier.pop()
        if name in seen or name not in all_schemas:
            continue
        seen.add(name)
        nxt: set[str] = set()
        _collect_refs(all_schemas[name], nxt)
        frontier |= nxt - seen
    return {name: all_schemas[name] for name in sorted(seen)}


def build_openapi() -> dict[str, Any]:
    """Return the pruned OpenAPI 3.1 document for the public API."""
    from ski_model.server import app  # noqa: PLC0415 — import after sys.path/env setup

    full = app.openapi()
    all_paths = full.get("paths", {})
    kept_paths = {p: all_paths[p] for p in PUBLIC_PATHS if p in all_paths}
    missing = [p for p in PUBLIC_PATHS if p not in all_paths]
    if missing:
        raise SystemExit(f"public paths missing from app.openapi(): {missing}")

    all_schemas = full.get("components", {}).get("schemas", {})
    kept_schemas = _transitive_schemas(kept_paths, all_schemas)

    doc: dict[str, Any] = {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": full.get("info", {}).get("title", "SKI Model Inference Engine"),
            "version": full.get("info", {}).get("version", "unknown"),
            "description": (
                "Public contract for the SKI Model API, pruned to the three public paths. "
                "Generated from the FastAPI app by spec/contracts/generate_openapi.py; do not edit by hand."
            ),
        },
        "paths": kept_paths,
    }
    if kept_schemas:
        doc["components"] = {"schemas": kept_schemas}
    return doc


def _serialize(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc, sort_keys=True, allow_unicode=True, default_flow_style=False, width=100)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)

    text = _serialize(build_openapi())
    if args.check:
        current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.exists() else None
        if current != text:
            print(
                "STALE openapi.yaml (run spec/contracts/generate_openapi.py)",
                file=sys.stderr,
            )
            return 1
        return 0

    OPENAPI_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OPENAPI_PATH.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
