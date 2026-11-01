#!/usr/bin/env python3
"""Convert a flat Knowledge Graph (``rules`` + ``tag_registry``) to the spec §3 graph shape.

The flat shape still loads in compatibility mode (spec §11.2, opt-in with
``SKI_KG_ALLOW_FLAT=true`` since v3.3.0); this script moves a KG to the graph
shape the spec, kg-validator and the runtime share. The conversion itself is
``ski_schemas.kg_graph.flat_to_graph``; the runtime applies the same one in memory.
Each flat rule becomes one Obligation (same id, so recorded citations still
resolve) owned by one Rule (``rule.<id>``):

* ``predicate`` -> ``obligation_type``; ``effective_date`` / ``sunset_date``
  -> ``effective_date_start`` / ``effective_date_end``; ``name`` -> ``summary``;
  ``metric``, ``value``, ``unit``, ``window_seconds`` and
  ``requires_recent_within_seconds`` are kept;
* ``jurisdiction`` (a string or a list) becomes Jurisdiction nodes and
  ``scoped_to`` edges from the Obligation; ``global`` / ``*`` / empty means
  no edge (applies everywhere);
* ``risk_tier`` moves to the Rule, mapped to spec §5.4's ``high`` /
  ``medium`` / ``low``; no tier stays no tier (the runtime applies tier-1);
* each ``tag_registry`` subject becomes a Subject with an ``applies_to``
  edge from the rules it routed to.

Node versions are the SHA-256 of each node's §7.3 canonical content (spec
§3.1). The output is unsigned: sign it with ``ski-model-deploy sign``.

Usage:
    python scripts/flat-kg-to-graph.py IN.json OUT.json [--default-effective-date 2026-01-01T00:00:00Z]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "ski-schemas" / "src"))

from ski_schemas.kg_graph import flat_to_graph

# Kept as ``convert`` for callers of the script module.
convert = flat_to_graph


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--default-effective-date",
        help="effective_date_start for rules that have no effective_date (spec §3.4 requires one).",
    )
    args = parser.parse_args(argv)
    flat = json.loads(args.input.read_text(encoding="utf-8"))
    if "nodes" in flat:
        parser.error(f"{args.input} is already a graph KG.")
    graph = convert(flat, args.default_effective_date)
    args.output.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {len(graph['nodes']['obligations'])} obligations (unsigned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
