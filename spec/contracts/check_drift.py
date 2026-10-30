#!/usr/bin/env python3
"""Fail CI if the published contracts or test vectors drift from the code.

Checks, in order:

1. **JSON Schema drift** — regenerate every ``spec/contracts/schemas/*.schema.json``
   from the live ``ski_schemas`` Pydantic models and fail if a committed file
   differs. (Run ``spec/contracts/generate_schemas.py`` to fix.)
2. **Canonical vectors** — for every ``spec/test-vectors/canonical/*.json``,
   confirm ``canonicalize(input)`` reproduces the vector's ``canonical`` bytes
   and ``sha256_canonical(input)`` reproduces its ``sha256``.
3. **Envelope vectors** — validate every ``spec/test-vectors/envelopes/*.json``
   against the committed ``v3_verdict_envelope.schema.json`` (JSON Schema
   draft 2020-12), proving the published schema accepts a real envelope.
4. **Ledger vectors** — for every ``spec/test-vectors/ledger/*.json``, re-derive
   the evidence hashes, the v4 entry payload and the entry hash from the
   vector's ``columns`` (``ski_schemas.ledger``) and compare.

Exit code 0 when everything matches, 1 otherwise. Depends only on
``ski_schemas`` (pydantic) and ``jsonschema``; it does not import the server.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tools" / "ski-schemas" / "src"))
sys.path.insert(0, str(_REPO_ROOT / "spec" / "contracts"))
sys.path.insert(0, str(_REPO_ROOT / "spec" / "test-vectors" / "ledger"))

from generate import derive as derive_ledger_vector  # noqa: E402  (spec/test-vectors/ledger on path)
from generate_schemas import SCHEMAS_DIR, build_schemas  # noqa: E402  (spec/contracts on path)
from jsonschema.validators import Draft202012Validator  # noqa: E402
from ski_schemas.canonical import canonicalize, sha256_canonical  # noqa: E402

CANONICAL_DIR = _REPO_ROOT / "spec" / "test-vectors" / "canonical"
ENVELOPES_DIR = _REPO_ROOT / "spec" / "test-vectors" / "envelopes"
ENVELOPE_SCHEMA = SCHEMAS_DIR / "v3_verdict_envelope.schema.json"
LEDGER_DIR = _REPO_ROOT / "spec" / "test-vectors" / "ledger"


def _rel(path: Path) -> str:
    return str(path.relative_to(_REPO_ROOT))


def check_schema_drift(failures: list[str]) -> None:
    expected = build_schemas()
    for name, text in expected.items():
        path = SCHEMAS_DIR / name
        if not path.exists():
            failures.append(f"missing JSON Schema: {_rel(path)} (run generate_schemas.py)")
        elif path.read_text(encoding="utf-8") != text:
            failures.append(f"stale JSON Schema: {_rel(path)} (run generate_schemas.py)")
        else:
            print(f"ok   schema {name}")


def check_canonical_vectors(failures: list[str]) -> None:
    files = sorted(CANONICAL_DIR.glob("*.json"))
    if not files:
        failures.append(f"no canonical vectors found under {_rel(CANONICAL_DIR)}")
    for path in files:
        vec: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        got = canonicalize(vec["input"]).decode("utf-8")
        if got != vec["canonical"]:
            failures.append(
                f"canonical mismatch {_rel(path)}:\n  got      {got!r}\n  expected {vec['canonical']!r}"
            )
            continue
        digest = sha256_canonical(vec["input"])
        if digest != vec["sha256"]:
            failures.append(f"sha256 mismatch {_rel(path)}: got {digest} expected {vec['sha256']}")
            continue
        print(f"ok   canonical {path.name}")


def check_envelope_vectors(failures: list[str]) -> None:
    if not ENVELOPE_SCHEMA.exists():
        failures.append(f"missing schema {_rel(ENVELOPE_SCHEMA)}")
        return
    schema = json.loads(ENVELOPE_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    files = sorted(ENVELOPES_DIR.glob("*.json"))
    if not files:
        failures.append(f"no envelope vectors found under {_rel(ENVELOPES_DIR)}")
    for path in files:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(envelope), key=lambda e: e.path)
        if errors:
            detail = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
            failures.append(f"envelope does not validate {_rel(path)}: {detail}")
        else:
            print(f"ok   envelope {path.name}")


def check_ledger_vectors(failures: list[str]) -> None:
    paths = sorted(LEDGER_DIR.glob("*.json"))
    if not paths:
        failures.append(f"no ledger vectors found under {_rel(LEDGER_DIR)}")
    for path in paths:
        vec = json.loads(path.read_text(encoding="utf-8"))
        derived = derive_ledger_vector(vec["columns"])
        mismatched = [key for key, value in derived.items() if vec.get(key) != value]
        if mismatched:
            failures.append(f"ledger vector {_rel(path)} does not reproduce: {', '.join(mismatched)}")
        else:
            print(f"ok   ledger {path.name}")


def main() -> int:
    failures: list[str] = []
    check_schema_drift(failures)
    check_canonical_vectors(failures)
    check_envelope_vectors(failures)
    check_ledger_vectors(failures)

    print()
    if failures:
        print("DRIFT CHECK FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("drift check passed: schemas, canonical, envelope and ledger vectors all consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
