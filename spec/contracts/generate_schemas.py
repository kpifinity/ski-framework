#!/usr/bin/env python3
"""Generate JSON Schema (draft 2020-12) for the SKI core wire objects.

The schemas are generated FROM the Pydantic models in ``ski_schemas`` so
they cannot drift from what the runtime actually emits and accepts. Run
this script to (re)write ``spec/contracts/schemas/*.schema.json``; the
drift check (``spec/contracts/check_drift.py``) regenerates in memory and
fails CI if the committed files differ.

Covered objects:

* ``MeasurementRecord``    — the input shape of ``POST /api/evaluate``.
* ``V3VerdictEnvelope``    — the verdict envelope (spec §4.2).
* ``ModelProvenance``      — inference provenance (spec §4.6).
* ``KGObligation``         — the flat-shape KG obligation the runtime loads.

Usage::

    python spec/contracts/generate_schemas.py          # write the files
    python spec/contracts/generate_schemas.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Run without an editable install: put the tool sources on the path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKI_SCHEMAS_SRC = _REPO_ROOT / "tools" / "ski-schemas" / "src"
if str(_SKI_SCHEMAS_SRC) not in sys.path:
    sys.path.insert(0, str(_SKI_SCHEMAS_SRC))

from ski_schemas.envelope import ModelProvenance, V3VerdictEnvelope  # noqa: E402
from ski_schemas.kg import KGObligation  # noqa: E402
from ski_schemas.measurement import MeasurementRecord  # noqa: E402

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_ID_BASE = "https://kpifinity.github.io/ski-framework/contracts/schemas"

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

# filename stem -> pydantic model. Order is irrelevant (each file is standalone).
_MODELS = {
    "measurement_record": MeasurementRecord,
    "v3_verdict_envelope": V3VerdictEnvelope,
    "model_provenance": ModelProvenance,
    "kg_obligation": KGObligation,
}


def _build_one(stem: str, model: type[Any]) -> dict[str, Any]:
    """Return the draft 2020-12 schema for one model, with dialect and id injected."""
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    # Prepend the dialect and a stable id so the published file is a
    # self-describing draft 2020-12 document.
    ordered: dict[str, Any] = {
        "$schema": SCHEMA_DIALECT,
        "$id": f"{_ID_BASE}/{stem}.schema.json",
    }
    ordered.update(schema)
    return ordered


def _serialize(schema: dict[str, Any]) -> str:
    """Deterministic serialization: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_schemas() -> dict[str, str]:
    """Return ``{filename: serialized schema text}`` for every covered model."""
    return {f"{stem}.schema.json": _serialize(_build_one(stem, model)) for stem, model in _MODELS.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if committed files are stale")
    args = parser.parse_args(argv)

    schemas = build_schemas()
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)

    stale: list[str] = []
    for name, text in schemas.items():
        path = SCHEMAS_DIR / name
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if args.check:
            if current != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(_REPO_ROOT)}")

    if args.check and stale:
        print("STALE JSON Schemas (run spec/contracts/generate_schemas.py):", file=sys.stderr)
        for name in stale:
            print(f"  - {name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
