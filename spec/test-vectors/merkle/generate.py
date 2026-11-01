#!/usr/bin/env python3
"""Regenerate the ledger-checkpoint Merkle test vectors (RFC 6962 hashing).

Each vector gives ``entry_hashes`` (hex, sequence order) and pins:

* ``root_hash``: the RFC 6962 Merkle tree head over the raw 32-byte hashes;
* ``proofs``: for each zero-based index, the audit path (leaf to root);
* ``checkpoint_statement``: the canonical bytes a checkpoint over all of
  them signs (``ski_schemas.merkle.checkpoint_statement``).

Any implementation claiming conformance MUST reproduce all of them. Run
``python generate.py`` to rewrite the files; the drift check re-derives them.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "tools" / "ski-schemas" / "src"))

from ski_schemas.merkle import checkpoint_statement, inclusion_proof, merkle_root  # noqa: E402

_OUT = Path(__file__).resolve().parent


def derive(entry_hashes: List[str]) -> Dict[str, Any]:
    """The values a conformant implementation computes from ``entry_hashes``."""
    root = merkle_root(entry_hashes)
    return {
        "root_hash": root,
        "proofs": [inclusion_proof(entry_hashes, i) for i in range(len(entry_hashes))],
        "checkpoint_statement": checkpoint_statement(
            tenant_id="default",
            tree_size=len(entry_hashes),
            root_hash=root,
            last_entry_hash=entry_hashes[-1],
            created_at="2026-11-01T00:00:00+00:00",
        ).decode("utf-8"),
    }


def _hashes(n: int) -> List[str]:
    return [hashlib.sha256(f"entry-{i}".encode()).hexdigest() for i in range(1, n + 1)]


VECTORS = {
    f"tree_size_{n}": (f"A checkpoint over the first {n} ledger entries.", _hashes(n))
    for n in (1, 2, 3, 5, 8)
}


def main() -> int:
    for name, (description, entry_hashes) in VECTORS.items():
        vector = {
            "name": name,
            "description": description,
            "entry_hashes": entry_hashes,
            **derive(entry_hashes),
        }
        (_OUT / f"{name}.json").write_text(json.dumps(vector, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {name}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
