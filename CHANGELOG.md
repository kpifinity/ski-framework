# Changelog

All notable changes to this repository are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **specification** version (currently v2.1) is tracked separately and
referenced from each release entry.

## [Unreleased]

### Added
- Stateful evaluation buffer with NULL_STALE routing (planned).
- Conformance suite Level 2 tests (planned).
- Additional LLM backends behind a uniform interface: vLLM, llama.cpp,
  Bedrock, Vertex (planned).
- Kubernetes deployment manifests (planned).

## [0.1.0-alpha] — 2026-05-22

Specification: **v2.1**.

This is the first published alpha. It establishes the structure of the
open repository and aligns every file with the v2.1 specification.

### Added
- **Sovereignty by default.** The reference implementation runs entirely
  on-premise using a local LLM runtime (Ollama). The optional Anthropic
  backend is labelled non-conformant demo mode and is never required.
- **Symbolic Evaluator (Track 1).** Deterministic predicate evaluator for
  rules expressible as structured `{operator, metric, value, unit}` tuples.
- **SKI Model wrapper (Track 2).** Bounded local-LLM evaluator with
  temperature=0, seeded decoding, structured output enforcement, and the
  determinism canary required by B3.4.
- **Tag Registry (B4.3).** First-class governed mapping from telemetry
  subject to KG rule. Runtime tag inference is no longer possible.
- **Knowledge Graph signature verification.** Ed25519 signatures verified
  on load; the service refuses to evaluate against an unsigned KG.
- **Append-only audit ledger.** Database-level triggers prevent
  UPDATE/DELETE on `ledger_entries`. `verify_integrity()` recomputes the
  entry hash from a documented canonical serialization. `backup_database()`
  invokes `pg_dump` and verifies the dump with `pg_restore --list`.
- **Determinism canary.** Periodic self-check on a fixed input that
  exports `ski_canary_status` to Prometheus.
- **Five-verdict taxonomy.** `CLEAR`, `FLAG`, `NULL_UNMAPPED`,
  `NULL_STALE`, `DISCRETIONARY`. Replaces the previous four.
- **Conformance test suite.** Level 1 tests are runnable today; each test
  cites the spec section it validates.
- **Project hygiene.** `SECURITY.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`,
  `CITATION.cff`, `CODEOWNERS`, `FUNDING.yml`, issue templates, PR
  template, `dependabot.yml`, `requirements-dev.txt`.
- **CI/CD.** `pytest`, `ruff`, `mypy`, `bandit`, `pip-audit`, CycloneDX
  SBOM generation, Trivy container scan, conformance-suite run.
- **Apache 2.0 / CC BY 4.0 split.** Software is Apache 2.0; specification
  documents remain CC BY 4.0. Patent grant now explicit. `NOTICE` added.
- **Security defaults.** TLS on by default; no `admin`/`admin`; Postgres
  uses SCRAM-SHA-256; ledger has an `ski_audit_reader` read-only role;
  Kafka uses SASL/SCRAM when enabled.

### Changed
- **MiLM → SKI Model.** Every occurrence in source, schema, Docker files,
  configuration, and documentation has been renamed.
  - `Dockerfile.milm` → `Dockerfile.ski-model`
  - `src/milm/` → `src/ski_model/`
  - `tools/milm-deploy/` → `tools/ski-model-deploy/`
  - `milm_version` ledger column → `ski_model_version`
  - `MILM_*` environment variables → `SKI_MODEL_*`
- **Reference implementation is now a real implementation.** The previous
  `server.py` was a substring-matching stub that hardcoded `CLEAR`. The
  rewritten service routes via the Tag Registry, evaluates via the
  Symbolic Evaluator or the SKI Model wrapper, and writes signed,
  hash-chained ledger entries.
- **kg-extractor** now refuses to emit rules with `confidence: IMPLIED`
  per B2.1 (Anchor Constraint). Extraction temperature is 0 with a fixed
  seed; the prompt, seed, and model file SHA-256 are recorded in
  extraction metadata for reproducibility audits.
- **kg-validator** no longer ships `auto_approve_explicit`. Per B2.3
  (Universal Coverage), every rule must be human-reviewed.
- **ski-model-deploy** no longer exposes `verify_signature` as a
  parameter. Signature verification is mandatory.

### Removed
- **`confidence_level` column** from the ledger schema and `ConfidenceLevel`
  enum from `audit_ledger.models`. Confidence scores are prohibited
  (Axiom 2, B3.1).
- **`auto_approve_explicit`** option from `kg-validator`.
- **Default passwords.** `ski_password`, `admin`/`admin`, etc. are gone;
  the stack refuses to start without operator-supplied secrets.
- **Anthropic API requirement** from `docker-compose.yml`, `.env.example`,
  `setup.sh`, `deploy.sh`, and the QuickStart guide.

### Security
- CVE-2023-36464 and CVE-2022-24859: replaced `PyPDF2` with `pypdf` in
  `kg-extractor`.
- Pinned every dependency to exact versions across all `requirements.txt`
  files. `pip-audit` runs in CI on every PR.

### Deprecated
- `LICENSE.md` (single-file CC BY 4.0) is replaced by the split:
  `LICENSE` (Apache 2.0, code), `LICENSE-docs.md` (CC BY 4.0, spec). The
  `LICENSE.md` file is retained as a summary pointer.

### Fixed
- **Concurrency bug:** the SKI Model service now enforces
  `SKI_MODEL_WORKERS=1` and refuses to start with `workers != 1`. Module
  globals are no longer the source of truth across workers; horizontal
  scaling is via additional containers behind a deterministic load
  balancer.
- **Sync/async mix:** `requests` calls inside async FastAPI handlers
  replaced by `httpx.AsyncClient` with retries.
- **Deprecated FastAPI patterns:** `@app.on_event` handlers replaced by
  the lifespan context manager.
- **`audit-ledger verify_integrity`:** was chain-linkage only; now
  recomputes every entry hash from the canonical payload.
- **`audit-ledger backup_database`:** was a stub returning a fake success;
  now actually invokes `pg_dump` and verifies the dump.
- **Prometheus Postgres scrape:** Postgres does not expose `/metrics`
  natively; a `postgres_exporter` sidecar is now part of the compose
  stack. SKI-specific alert rules are shipped under
  `monitoring/rules/ski-alerts.yml`.

[Unreleased]: https://github.com/kpifinity/ski-framework/compare/v0.1.0-alpha...HEAD
[0.1.0-alpha]: https://github.com/kpifinity/ski-framework/releases/tag/v0.1.0-alpha
