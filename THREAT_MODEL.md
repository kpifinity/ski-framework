# Threat model

This file is the canonical entry point for security researchers. The
full rendered version with cross-references lives at
[`docs/threat-model.md`](./docs/threat-model.md) and on the published
docs site at <https://kpifinity.github.io/ski-framework/threat-model/>.

## Quick reference

| Threat                                | Defence                                                                   | Re-verification recipe                                                                 |
|---------------------------------------|---------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| T-1 Tampering with recorded verdicts  | Postgres append-only triggers on `ledger_entries` and `telemetry_buffer`  | `UPDATE ledger_entries SET verdict = 'CLEAR' WHERE sequence_number = 1` must error     |
| T-2 Loading a tampered KG             | Ed25519 signature verification by the SKI Model service                   | Corrupt one byte of `kg.json`; service must refuse to start                            |
| T-3 Non-deterministic inference       | Model SHA-256 pin, fixed seed/temperature, structured output, canary      | `audit-ledger replay --strict`; canary metric must report PASS                         |
| T-4 Producer claiming a `rule_id`     | Sidecar + send-telemetry.py reject; server ignores client-provided rule_id| Conformance test `test_demo_telemetry_has_no_rule_id`                                  |
| T-5 Data exfiltration via cloud LLM   | Default backend `ollama`; air-gapped network in production                | `docker network inspect` of `ski-internal` shows `Internal: true` in production        |
| T-6 Ledger replay attack              | `sequence_number` uniqueness + hash chain                                 | `audit-ledger verify` reports `chain_link_verified = N / N`                            |
| T-7 Secrets leakage                   | `setup.sh` generates `.env` mode 0600; no defaults; compose `${VAR:?error}`| `ls -la reference-implementation/.env` shows `-rw-------`                              |
| T-8 Supply-chain compromise           | Pinned deps, Dependabot, pip-audit, Trivy, CycloneDX SBOM, cosign signing, SLSA Level 3 provenance | `cosign verify-blob` against any release artifact's `.sig`/`.pem`; verify provenance on GitHub releases |

## How to verify a release artifact

Every wheel, sdist, and SBOM published to GitHub Releases is signed
with sigstore/cosign keyless (OIDC), and ships with SLSA Level 3
provenance.

```bash
# Install cosign if you don't already have it
brew install cosign            # or see https://docs.sigstore.dev/cosign/installation/

# Verify a wheel's signature
cosign verify-blob \
  --certificate-identity-regexp '^https://github.com/kpifinity/ski-framework/.github/workflows/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  --signature audit_ledger-0.2.1-py3-none-any.whl.sig \
  --certificate audit_ledger-0.2.1-py3-none-any.whl.pem \
  audit_ledger-0.2.1-py3-none-any.whl

# Verify a container image signature
cosign verify ghcr.io/kpifinity/ski-model:0.2.1 \
  --certificate-identity-regexp '^https://github.com/kpifinity/ski-framework/.github/workflows/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com'
```

If verification fails, the artifact is not authentic. Do not run it.

## Reporting a vulnerability

See [SECURITY.md](./SECURITY.md) for the formal disclosure process. In
short: do not open a public issue; email <security@kpifinity.com> or
use GitHub's private vulnerability reporting.
