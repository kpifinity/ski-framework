# Standards-native evidence

SKI proves its verdicts in its own formats (the verdict envelope, the
signed transcript, the hash-chained ledger and its checkpoints). Since
v3.3.0 it also emits the same evidence in the formats the standards
around it are converging on, so a generic tool can verify it without SKI
code. Every item below is signed with the runtime's deployment key: the
transcript key whose id is on every ledger entry and attested at
`/api/sovereignty`.

| What | Standard | Where |
|---|---|---|
| Each verdict as a signed statement | IETF SCITT ([RFC 9943](https://datatracker.ietf.org/wg/scitt/)), COSE_Sign1 (RFC 9052) | `GET /api/ledger/{sequence}/evidence` → `scitt.signed_statement` |
| Proof the verdict is in the ledger | COSE Receipts (`RFC9162_SHA256` inclusion proof, IETF draft) | same → `scitt.receipt`, `scitt.transparent_statement` |
| Each verdict as an AI runtime record | TRACE v0.2 (CoSAI / Linux Foundation, developer preview) | same → `trace_record` |
| Who produced the model | OpenSSF Model Signing (OMS) v1.0, verified at boot | `SKI_MODEL_SIGNATURE`; attested at `/api/sovereignty` |
| What the deployment is running | CycloneDX 1.6 ML-BOM | `GET /api/mlbom` |
| Assessment results for GRC tooling | NIST OSCAL 1.1.3 Assessment Results | `audit-ledger export-oscal` |
| AI system logging | ISO/IEC 24970 (FDIS) | [crosswalk](crosswalks/iso-iec-24970.md) (provisional) |

## SCITT signed statements and receipts

`GET /api/ledger/{sequence}/evidence` (API key, ledger format 5) returns,
base64-encoded:

- **`signed_statement`**: a COSE_Sign1 (EdDSA) whose payload is the §7.3
  canonical JSON of the entry's verdict line (with its `entry_hash`) and its
  envelope. Protected header: `alg` -8, `content_type`
  `application/vnd.ski.ledger-entry+json`, `kid` (the key id), and CWT claims
  (label 15) `iss` = `ski:key:<key id>`, `sub` = `ski:ledger:<tenant>:<sequence>`,
  `iat`.
- **`receipt`**, once a ledger checkpoint covers the entry: a COSE_Sign1 with
  `vds` (395) = 1 (`RFC9162_SHA256`) and, in `vdp` (396), the inclusion proof
  `[tree_size, leaf_index, path]` for the entry's `entry_hash` (the leaf) in
  the tree of the first `tree_size` entries. The payload is detached: it is the
  Merkle root, which equals the root of the signed checkpoint `audit-ledger
  checkpoint export` writes out.
- **`transparent_statement`**: the statement with the receipt in its
  `receipts` header (394).

Any COSE library verifies them with the runtime's Ed25519 public key; the
tests use `pycose`. Labels 394-396 are the values the COSE Receipts draft
requests and may change on registration.

## TRACE Trust Records

The same response carries a TRACE v0.2 Trust Record
(`eat_profile: tag:agentrust-io.com,2026:trace-v0.2`) in the
embedded-signature profile: `signature` is Ed25519 over the RFC 8785 JCS of
the record without it, by the key in `cnf.jwk`. The field mapping is in
`tools/ski-schemas/src/ski_schemas/trace.py`. Two honest limits: SKI runs
without a TEE, so `runtime.platform` is `software-only`; and TRACE v0.2 is a
developer preview, so the profile will follow its changes.

## OpenSSF Model Signing at boot

Sign the model with the OpenSSF tool, then point the runtime at it:

```bash
model_signing sign key /models/qwen --private_key origin.key --signature qwen.sig
```

| Variable | Meaning |
|---|---|
| `SKI_MODEL_SIGNATURE` | the OMS signature file |
| `SKI_MODEL_DIR` | the signed model directory (default: the directory of `SKI_MODEL_FILE_PATH`) |
| `SKI_MODEL_ORIGINS` | PEM bundle of the public keys (or certificates) whose models this deployment accepts |

With a signature configured the runtime refuses to start, in any
sovereignty mode, unless the signature verifies with an origin key, the
directory holds exactly the signed files with their digests, and the pinned
weights file (`SKI_MODEL_FILE_PATH`) is one of them. The OMS `key` method is
supported (ECDSA P-256/P-384, Ed25519), which works offline; Sigstore's
public transparency log is not reachable from an air gap. The signer and
the model's root digest are attested at `/api/sovereignty` and in the ML-BOM.

## CycloneDX ML-BOM

`GET /api/mlbom` returns a CycloneDX 1.6 document: the model as a
`machine-learning-model` component (weight digest, whether the runtime
verified it, the OMS signer), the signed KG as a `data` component (its
version hash and trust), and the runtime image as the subject. It
validates against the CycloneDX 1.6 schema.

## OSCAL Assessment Results

```bash
audit-ledger export-oscal --ledger-db "$LEDGER_DSN" --out ar.json \
    --trusted-key-id sha256:<runtime key id> \
    --checkpoint /mnt/worm/ski-checkpoints/checkpoint-default-000000001000.json \
    --replay-report replay-report.json
```

writes one OSCAL 1.1.3 result with an observation per integrity check and
a finding per spec requirement (`satisfied` / `not-satisfied`): chain
linkage (§7.2), entry hashes (§7.1), verdict signatures, checkpoints and
time-stamps, timestamp order, and, with a replay report, replay (§8.1).
Each failing finding links the integrity issues behind it. The document
validates against NIST's published schema.
