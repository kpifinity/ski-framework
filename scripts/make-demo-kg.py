#!/usr/bin/env python3
"""Generate and SIGN the demo Knowledge Graph the quickstart boots with.

Produces ``reference-implementation/examples/knowledge-graphs/kg.json``
in the runtime flat-rule shape, signed with a locally generated ed25519
demo key, so the quickstart boots CONFORMANTLY (KG_REQUIRE_SIGNATURE=true)
without anyone committing a private key to the repository.

The rules are the SKI Evals energy golden-dataset KG — ten obligations
with jurisdiction and effective-date scoping, every one mechanically
checkable by the Symbolic Verifier.

The demo signing key is written next to the TLS material in
``reference-implementation/tls/`` (gitignored). It attests nothing
beyond "this machine generated this demo KG" — production keys belong
to your Knowledge Graph Owner, per docs/governance.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (REPO / "reference-implementation" / "src", REPO / "tools" / "ski-schemas" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SOURCE = REPO / "evals" / "datasets" / "energy" / "eval-kg.json"
OUT = REPO / "reference-implementation" / "examples" / "knowledge-graphs" / "kg.json"
KEY_DIR = REPO / "reference-implementation" / "tls"


def main() -> int:
    src = json.loads(SOURCE.read_text(encoding="utf-8"))
    metadata = dict(src["metadata"])
    metadata["description"] = (
        "DEMO Knowledge Graph (energy) — generated and signed locally by "
        "scripts/make-demo-kg.py for the quickstart. Not regulatory advice."
    )
    rules, tag_registry = src["rules"], src["tag_registry"]

    canonical = json.dumps(
        {"metadata": metadata, "rules": rules, "tag_registry": tag_registry},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    KEY_DIR.mkdir(parents=True, exist_ok=True)
    key_path = KEY_DIR / "demo-kg-signing.key"
    if key_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        assert isinstance(key, Ed25519PrivateKey)
    else:
        key = Ed25519PrivateKey.generate()
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)

    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (KEY_DIR / "demo-kg-signing.pub").write_bytes(public_pem)

    kg = {
        "metadata": metadata,
        "rules": rules,
        "tag_registry": tag_registry,
        "signature": {
            "algorithm": "ed25519",
            "public_key_pem": public_pem.decode("ascii"),
            "value_hex": key.sign(canonical).hex(),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(kg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Round-trip: refuse to emit a KG the runtime would refuse to load.
    from ski_model.kg_loader import load_signed_kg

    loaded = load_signed_kg(OUT, require_signature=True)
    assert loaded.signature_verified
    print(f"Signed demo KG written to {OUT.relative_to(REPO)} ({len(rules)} rules, signature verified).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
