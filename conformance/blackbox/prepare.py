"""Write the black-box suite's signed Knowledge Graph and its trust anchor.

``python conformance/blackbox/prepare.py OUTDIR`` writes:

* ``OUTDIR/kg.json``: the fixture KG (graph shape, spec §3), signed per
  spec §3.5 (Ed25519 over the §7.3 canonical ``{metadata, nodes, edges}``)
  with a key generated for this run;
* ``OUTDIR/kg-trust-anchor.pem``: that key's public half, which the
  implementation under test must pin as its only KG trust anchor.

Start the implementation with this KG and anchor, then run the suite with
``--kg-fixture OUTDIR/kg.json``. The suite computes the expected
``kg_version_hash`` from the file itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

try:
    from .checkers import canonicalize  # the suite's own canonicalizer
except ImportError:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from checkers import canonicalize  # type: ignore[no-redef]

VERSION = "blackbox-1"
SO2_SUBJECT, PH_SUBJECT, IDLE_SUBJECT = "plant.stack", "plant.outfall", "plant.idle"
SO2_OBLIGATION, PH_OBLIGATION = "bb.so2.lte_100", "bb.ph.within"
SO2_LIMIT, PH_RANGE = 100, [6.5, 8.5]


def _node(kind: str, node_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": node_id, "type": kind, "version": VERSION, **fields}


def fixture_kg() -> dict[str, Any]:
    """The unsigned fixture graph: two medium-risk Rules, each routed to its own subject, and one idle subject."""
    nodes = {
        "subjects": [
            _node("Subject", SO2_SUBJECT, name="Stack SO2 analyser"),
            _node("Subject", PH_SUBJECT, name="Outfall pH probe"),
            _node("Subject", IDLE_SUBJECT, name="A subject no Rule applies to"),
        ],
        "rules": [
            _node("Rule", "bb.so2.cap", name="SO2 cap", risk_tier="medium"),
            _node("Rule", "bb.ph.band", name="pH band", risk_tier="medium"),
        ],
        "obligations": [
            _node(
                "Obligation",
                SO2_OBLIGATION,
                obligation_type="must_not_exceed",
                metric="so2_ppm",
                value=SO2_LIMIT,
                unit="ppm",
                effective_date_start="2026-01-01T00:00:00Z",
            ),
            _node(
                "Obligation",
                PH_OBLIGATION,
                obligation_type="must_be_within",
                metric="ph",
                value=PH_RANGE,
                unit="pH",
                effective_date_start="2026-01-01T00:00:00Z",
            ),
        ],
        "citations": [
            _node("Citation", "cite.bb", source_document="Conformance fixture (not a real legal citation)")
        ],
    }
    edges = [
        {"type": "applies_to", "from": "bb.so2.cap", "to": SO2_SUBJECT},
        {"type": "consists_of", "from": "bb.so2.cap", "to": SO2_OBLIGATION},
        {"type": "applies_to", "from": "bb.ph.band", "to": PH_SUBJECT},
        {"type": "consists_of", "from": "bb.ph.band", "to": PH_OBLIGATION},
        {"type": "cited_by", "from": SO2_OBLIGATION, "to": "cite.bb"},
        {"type": "cited_by", "from": PH_OBLIGATION, "to": "cite.bb"},
    ]
    metadata = {
        "name": "SKI black-box conformance KG",
        "schema_version": "3.0",
        "version": VERSION,
        "compiled_at": "2026-06-01T00:00:00Z",
        "description": "Fixture for conformance/blackbox. Not a real regulation.",
    }
    return {"metadata": metadata, "nodes": nodes, "edges": edges}


def write(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    kg = fixture_kg()
    key = Ed25519PrivateKey.generate()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )
    kg["signature"] = {
        "algorithm": "ed25519",
        "public_key_pem": public_pem,
        "value_hex": key.sign(canonicalize({k: kg[k] for k in ("metadata", "nodes", "edges")})).hex(),
    }
    (outdir / "kg.json").write_text(json.dumps(kg, indent=2), encoding="utf-8")
    (outdir / "kg-trust-anchor.pem").write_text(public_pem, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    write(Path(sys.argv[1]))
