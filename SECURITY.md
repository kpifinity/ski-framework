# Security Policy

The SKI Framework is intended for use in regulated industries where audit
defensibility is non-negotiable. We take security and vulnerability
disclosure seriously and ask the community to do the same.

## Supported versions

The reference implementation is currently in early alpha. Until v1.0, only
the **latest tagged release** receives security fixes.

| Version | Status | Security fixes |
|---|---|---|
| `0.2.x` | active development | yes |
| `0.1.x-alpha` | unsupported (superseded by 0.2.x) | no |
| pre-`0.1` | unsupported | no |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report privately by either:

1. Opening a [private security advisory](https://github.com/kpifinity/ski-framework/security/advisories/new) on GitHub. This is the preferred path.
2. Emailing **<security@kpifinity.com>** with the subject line `SKI vuln:`. PGP key fingerprint and public key are published at <https://kpifinity.com/.well-known/security.txt>.

Please include:

- A clear description of the issue and the affected component(s)
- Reproduction steps or a proof-of-concept
- The commit hash or release version you tested against
- Your assessment of impact
- Whether you intend to publish a write-up after disclosure

## What you can expect from us

| Time | Action |
|---|---|
| ≤ 2 business days | Acknowledgement of receipt and a tracking ID |
| ≤ 7 business days | Triage decision (accepted / needs-info / out-of-scope) |
| ≤ 30 days | Fix or mitigation in `main` for accepted reports |
| ≤ 90 days from acknowledgement | Coordinated public disclosure |

We will credit reporters in the security advisory unless you ask us not to. We do not currently run a paid bug bounty, but we are happy to provide a public credit and a letter for your portfolio.

## Scope

In scope:

- The reference implementation (`reference-implementation/`)
- The four tools under `tools/`
- The conformance test suite (`conformance/`)
- The scripts under `scripts/`
- Sample CI workflows under `.github/`

Out of scope (please do not test):

- KpiFinity's production infrastructure
- Third-party services referenced from documentation
- Denial-of-service against demo or community deployments

## Hardening guidance

Operator-facing hardening guidance is consolidated in
[`reference-implementation/SECURITY_DEFAULTS.md`](./reference-implementation/SECURITY_DEFAULTS.md).
The reference implementation is configured to refuse to start without
operator-supplied secrets and with TLS enabled by default.

## Verifying release artifacts

Every wheel, sdist, SBOM, and container image published to GitHub
Releases / GHCR is signed with [sigstore/cosign](https://docs.sigstore.dev/)
keyless (OIDC-based, no long-lived signing keys), and ships with SLSA
Level 3 provenance attestations.

### Verifying a Python distribution

```bash
cosign verify-blob \
  --certificate-identity-regexp '^https://github.com/kpifinity/ski-framework/\.github/workflows/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  --signature <artifact>.sig \
  --certificate <artifact>.pem \
  <artifact>
```

### Verifying a container image

```bash
cosign verify ghcr.io/kpifinity/ski-model:<tag> \
  --certificate-identity-regexp '^https://github.com/kpifinity/ski-framework/\.github/workflows/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com'
```

If verification fails, the artifact is not authentic. Do not run it.

### Verifying SLSA provenance

```bash
# Using slsa-verifier (https://github.com/slsa-framework/slsa-verifier)
slsa-verifier verify-artifact \
  --provenance-path ski-framework-provenance.intoto.jsonl \
  --source-uri github.com/kpifinity/ski-framework \
  --source-tag <version> \
  <artifact>
```

## Cryptographic primitives

- KG signatures: **Ed25519** (RFC 8032).
- Audit ledger hashes: **SHA-256** over the canonical serialization
  documented in
  [`tools/audit-ledger/src/audit_ledger/canonical.py`](./tools/audit-ledger/src/audit_ledger/canonical.py).
- TLS: at least TLS 1.2, prefer TLS 1.3. Stack ships with self-signed certs
  for local use; replace with certs from your own CA for any non-local
  deployment.

If a flaw in any of these primitives is discovered (algorithm break, weak
implementation, etc.), report it as a vulnerability.
