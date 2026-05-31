# Changelog

All notable changes to this repository are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **specification** version (currently v3.0) is tracked separately and
referenced from each release entry.

## [Unreleased]

### Added (runtime, v3 — PR 11, audit trail expansion)
- **`ski_model.v3.signing.TranscriptSigner`** — ed25519 signing keypair
  for LLM transcripts per spec §6.3. `auto_provision()` generates a fresh
  keypair on first run (default at `$SKI_TRANSCRIPT_KEY_PATH` →
  `/app/keys/transcript.ed25519`), persists it with mode `0600` on POSIX
  and writes the matching `.pub` PEM alongside. `signing_key_id` is the
  sha256 of the public-key bytes, prefixed `sha256:`, so an auditor can
  look up the right key during rotation.
- **`ski_model.v3.signing.verify_signature`** — standalone helper for
  independent auditors. Does not require a `TranscriptSigner`; just a PEM
  public key.
- **`ski_model.v3.transcript.LLMTranscript`** — provider-neutral signed
  record of one LLM evaluation call (spec §6.2). Captures the canonical
  prompt, canonical structured-output dict, both sha256 hashes, ed25519
  signature, `signing_key_id`, opaque `backend_name` / `backend_metadata`
  tags, and timestamps. **No vendor wire-format leaks** — Anthropic
  Messages blobs, OpenAI ChatCompletion shapes, Ollama responses, etc.
  do not reach the ledger. `extra="forbid"` enforces this.
- **`ski_model.v3.evaluator.EvaluationResult`** — `(envelope, transcript)`
  pair returned by the new `V3Evaluator.aevaluate_with_transcript(...)`.
  The simpler `aevaluate(...)` still returns just `V3VerdictEnvelope` so
  existing callers and tests don't break.
- **`V3Evaluator.signer`** — optional `TranscriptSigner` field. When
  supplied, every evaluation produces a signed `LLMTranscript`. When
  `None`, the envelope is still produced but no transcript is emitted.
- **`LedgerClient.append_v3(envelope, transcript, ...)`** — writes the
  full envelope and the signed transcript into the new ledger columns.
  Preserves the existing hash chain.
- **`reference-implementation/src/ledger/migrations/0002_transcript_columns.sql`**
  — adds `envelope_json`, `envelope_hash`, `transcript_json`,
  `transcript_signature`, `signing_key_id`, `verifier_status` columns
  and indices. Relaxes the legacy `track` CHECK so v3 entries
  (`'v3-evaluator'`) are accepted, and adds a new CHECK constraining
  `verifier_status` to the four spec-normative values.
- **`v3/tests/test_signing.py`** (9 tests) and
  **`v3/tests/test_transcript.py`** (12 tests).

### Changed (runtime, v3 — PR 11)
- **`/api/evaluate`** now calls `aevaluate_with_transcript(...)` and
  persists via `ledger.append_v3(...)`. Every verdict is recorded with
  its envelope + signed transcript; an auditor can independently replay
  the LLM call from the ledger.
- **`V3Evaluator`** renders the *canonical* prompt from `PROMPT_TEMPLATE`
  with the measurement and KG snapshot bound to it. This is the
  framework's view of what was asked; real backends may format
  internally (chat templates, system messages, etc.), but the
  audit-trail prompt is the framework's canonical form. This is the
  **LLM-agnostic** part — every backend signs against the same prompt.
- **`V3Evaluator.aevaluate(...)`** kept as a backward-compatible
  envelope-only return; production callers use
  `aevaluate_with_transcript(...)` to get the transcript.
- **`server.py`** lifespan provisions a `TranscriptSigner` and injects
  it into `V3Evaluator`.
- **Bug fix:** the ledger `track` CHECK constraint previously rejected
  `'v3-evaluator'` (only `'symbolic'` and `'llm'` were allowed). PR
  10b/10c wrote `'v3-evaluator'` but this only mattered for real
  Postgres — the `FakeLedger` in tests didn't enforce the CHECK. The
  0002 migration replaces the CHECK with a permissive non-empty-string
  rule.

### Conformance impact (PR 11)
- Real Postgres deployments need migration `0002_transcript_columns.sql`
  applied before upgrading. The migration is forward-only.
- Production deployments MUST provision a transcript signing key.
  Auto-provisioning at first start writes the key to disk; deployments
  with stricter key-management policies override
  `SKI_TRANSCRIPT_KEY_PATH` and pre-place the key.

### Added (conformance, v3 — PR 10d)
- **`conformance/level1/test_v3_envelope_shape.py`** (7 tests) — asserts
  every spec v3.0 §4.2 required `V3VerdictEnvelope` field, the §4.6
  `ModelProvenance` required fields, the §4.5 four-status
  `VerifierStatus` taxonomy, the §4.3 citation roles, and the `extra=
  "forbid"` envelope config.
- **`conformance/level1/test_v3_verifier_contract.py`** (7 tests) — asserts
  the runtime ships a `SymbolicVerifier` and a risk-tier policy module
  per spec §5.3 / §5.4, that the verifier names all four
  `VerifierStatus` values, that it handles the five minimum stateless
  predicates, and that `RiskTier` lists all three tiers.

### Changed (conformance, v3 — PR 10d)
- **`conformance/level1/test_verdict_taxonomy.py`** rewritten to read
  `ski_model/v3/envelope.py` instead of the removed
  `ski_model/verdicts.py`. Added an explicit guard
  (`test_legacy_verdicts_module_is_removed`) that fails if the legacy
  module reappears.
- Docstring updated from `v2.1 § B3 + Axiom 2` to `v3.0 §4.1`.

### Added (runtime, v3 — PR 10c of 3, closes the neuro-symbolic loop)
- **`ski_model.v3.verifier.SymbolicVerifier`** — mechanically cross-checks
  every `FormalizableAssertion` the LLM emits against the rule engine,
  per spec v3.0 §4.5. Returns a `VerifierResult` whose `status` is one
  of `AGREED` / `LLM_CONTRADICTION` / `NEURO_SYMBOLIC_DIVERGENCE` /
  `UNVERIFIABLE`. Stateless predicates supported in this PR:
  `must_not_exceed`, `must_be_at_least`, `must_be_within`, `must_equal`,
  `must_not_equal`. Stateful predicates (window queries, time-bounded
  checks) are deferred to a follow-up PR.
- **`ski_model.v3.policies.apply_risk_policy`** — implements spec v3.0
  §5.4 risk-tier policy. tier-1 obligations require `AGREED`; tier-2
  tolerates `LLM_CONTRADICTION` with `human_attestation`; tier-3 is
  permissive. Verdict downgrades to `DISCRETIONARY` are recorded in
  `V3VerdictEnvelope.notes` so the audit ledger captures the rationale.
- **`ski_model.v3.policies.RiskTier`** enum and case-insensitive alias
  resolution (`"high"`, `"standard"`, `"low"`, etc.) for tenant-facing
  tier strings.
- **`v3/tests/test_verifier.py`** (20 tests across AGREED, LLM_CONTRADICTION,
  NEURO_SYMBOLIC_DIVERGENCE, UNVERIFIABLE) and
  **`v3/tests/test_risk_policy.py`** (14 tests covering all three tiers
  and alias resolution).

### Changed (runtime, v3 — PR 10c of 3)
- **`V3Evaluator`** now constructs a `SymbolicVerifier` by default
  (override via the new `verifier` field) and applies the risk-tier
  policy after the LLM returns. The `UNVERIFIABLE` placeholder
  `VerifierResult` from PR 10b is gone; every envelope now carries the
  real verifier outcome.
- **`v3/tests/test_evaluator.py`** — happy-path expectations updated
  from `UNVERIFIABLE` to `AGREED`; the `TestVerifierPlaceholder`
  tripwire class replaced with `TestVerifierWired`.

### Added (runtime, v3 cutover — PR 10b of 3)
- **`ski_model.v3.evaluator.V3Evaluator`** — the KG-grounded LLM evaluator
  that produces a `V3VerdictEnvelope` from a measurement and a KG snapshot
  per spec v3.0 §5. Citations are validated against the snapshot; an LLM
  that cites a node not in the snapshot has its verdict discarded and
  replaced with `NULL_UNMAPPED` + verifier status `UNVERIFIABLE`. This is
  the anti-hallucination floor of the architecture.
- **`ski_model.v3.evaluator.FakeLLM`** — deterministic backend used by
  tests and CI. Pattern-matches on the measurement so the evaluator can
  be exercised end-to-end without secrets or network. Honours the full
  provenance contract (sha256-prefixed hashes for every field).
- **`ski_model.v3.evaluator.PROMPT_TEMPLATE`**,
  **`PROMPT_TEMPLATE_ID="ski.v3.evaluate.1"`**, and
  **`RESPONSE_GRAMMAR`** — the normative v3 prompt and structured-output
  schema. Real backends ingest the grammar to enforce envelope shape.
- **`v3/tests/test_evaluator.py`** (12 tests) and **`v3/tests/test_endpoint.py`**
  (5 tests) covering happy-path verdicts, provenance population,
  citation enforcement, unmapped snapshots, ledger persistence, and
  JSON round-trip.

### Changed (runtime, v3 cutover — PR 10b of 3)
- **`POST /api/evaluate`** now returns `V3VerdictEnvelope` per spec
  v3.0 §4. The request model is renamed `MeasurementRecord` and accepts
  an additional `risk_tier` field (consumed by the symbolic verifier in
  PR 10c).
- **`/api/health`** now reports `runtime_version: "v3"`.
- **`ski_model.__version__`** bumped from `0.1.0-alpha` to `3.0.0-alpha`.
- **`ski_model.backends`**, **`ski_model.ledger_client`**, and
  **`symbolic_evaluator.evaluator`** now import the verdict taxonomy from
  `ski_model.v3.envelope` (`V3Verdict as Verdict`). The taxonomy values
  are identical to v2.1 — five verdicts, no behavioural change. PR 10c
  rewrites `symbolic_evaluator` as a true Symbolic Verifier.

### Removed (runtime, v3 cutover — PR 10b of 3)
- **`ski_model/verdicts.py`** — the v2 `Verdict` enum module. Replaced
  by `ski_model.v3.envelope.V3Verdict`. The five-verdict taxonomy is
  preserved at the type level (`V3Verdict as Verdict` aliases).
- **`ski_model.server.VerdictResponse`** — the v2 envelope wrapper. Its
  replacement is the spec-normative `V3VerdictEnvelope`.
- **`ski_model.server.TelemetryRecord`** — renamed `MeasurementRecord`
  to align with v3 terminology.

### Tagged
- **`v2.1-final`** — the final commit on the v2.1 architecture before
  the v3 cutover. Recoverable via `git checkout v2.1-final`.

### Added (docs)
- **MkDocs Material documentation site.** Published to GitHub Pages on
  every push to `main`. Replaces the scattered Markdown files in
  `docs/` with a browsable, searchable site. Configuration in
  `mkdocs.yml`; build dependencies pinned in `requirements-docs.txt`.
- **Architecture diagrams.** [docs/architecture.md](./docs/architecture.md)
  now uses Mermaid for the two-phase dataflow, the runtime sequence
  diagram, the KG class diagram, and the conformance-level ladder.
- **Glossary** ([docs/glossary.md](./docs/glossary.md)) - every domain
  term defined once, with cross-references.
- **Governance** ([docs/governance.md](./docs/governance.md)) - roles,
  lazy-consensus decision-making, RFC process, release cadence,
  conformance authority.
- **Threat model** ([docs/threat-model.md](./docs/threat-model.md)) -
  eight in-scope threats with controls and residual risk; out-of-scope
  concerns explicitly listed; re-verification recipes for every control.
- **RFC template** ([docs/RFCs/0000-template.md](./docs/RFCs/0000-template.md))
  and RFC index page.
- **Newcomer tutorial** ([docs/tutorials/first-rule.md](./docs/tutorials/first-rule.md))
  - 10-minute walkthrough from `git clone` to verified replay.
- **GitHub Pages deployment workflow**
  ([.github/workflows/docs.yml](./.github/workflows/docs.yml)) - builds
  the site on every PR and deploys on push to `main`.

### Added (code modernization)
- **Unified packaging.** All four tools (`audit-ledger`, `kg-extractor`,
  `kg-validator`, `ski-model-deploy`) migrated from legacy `setup.py`
  to PEP 621 `pyproject.toml`. Each tool now declares its name,
  version (`0.2.1`), dependencies, entry points, classifiers, and
  package data in a single TOML file consistent with modern Python
  packaging.
- **`py.typed` markers** in every tool package, so downstream type
  checkers know these packages ship type information (PEP 561).
- **Pre-commit configuration** ([`.pre-commit-config.yaml`](./.pre-commit-config.yaml))
  with ruff (auto-fix + format), mypy strict on runtime packages,
  gitleaks secret scanning, and standard hygiene hooks
  (trailing-whitespace, end-of-file-fixer, large-file detection,
  private-key detection, line-ending normalization).

### Changed (code modernization)
- **Pydantic v2 idiom throughout.** Replaced the legacy `class Config:`
  pattern with `model_config = ConfigDict(...)` in
  `audit_ledger/models.py`, `kg_extractor/models.py`, and
  `kg_validator/models.py`. Eliminates three deprecation warnings the
  test suite emitted under Pydantic v2 and prepares the codebase for
  Pydantic v3.
- **mypy in strict mode** on the deterministic core
  (`symbolic_evaluator`, `tag_registry`, `telemetry_buffer`,
  `audit_ledger.canonical`). Type errors now block CI for these
  packages. Other packages still use the relaxed settings.
- **Ruff lint rule set expanded** to include `S` (bandit-equivalent
  security checks), `C4` (comprehensions), `PIE` (idiom), `RET` (return
  hygiene), `SIM` (simplification), `ASYNC` (async best practices),
  and `RUF` (ruff-specific). Ignored rules are explicitly enumerated
  with rationale.

### Removed (code modernization)
- Legacy `setup.py` files in `tools/*/`. The build system is now
  PEP 621 (`pyproject.toml`) exclusively.

### Added (security & compliance hardening)
- **Sigstore / cosign keyless signing** for every release artifact
  (wheels, sdists, SBOMs, container images). Verification recipes in
  [SECURITY.md](./SECURITY.md#verifying-release-artifacts).
- **SLSA Level 3 provenance** generated by
  `slsa-framework/slsa-github-generator` for the release artifacts,
  attached to each GitHub release.
- **Container images** for `ski-model` and `ski-sidecar` published to
  GHCR with `provenance: true` and `sbom: true` on
  `docker/build-push-action`; each tagged image is then signed with
  cosign and a build-provenance attestation is pushed to the registry.
- **GitHub artifact attestations** via `actions/attest-build-provenance`
  for downloadable verification of release artifacts.
- **Dedicated security workflow**
  ([.github/workflows/security.yml](./.github/workflows/security.yml))
  with gitleaks (secret scanning), `actions/dependency-review-action`
  (PR-time vulnerable-dep check, denies GPL-2.0/3.0/AGPL-3.0
  introduction), and weekly OSSF Scorecard runs (results uploaded to
  the Security tab).
- **`THREAT_MODEL.md`** at the repo root - quick-reference table for
  security researchers, plus verification recipes for every release
  control. Mirrors and links to the full
  [docs/threat-model.md](./docs/threat-model.md).

### Changed (security & compliance hardening)
- **SECURITY.md** - added "Verifying release artifacts" section with
  exact `cosign verify-blob`, `cosign verify`, and `slsa-verifier`
  commands. Updated supported-versions table to reflect 0.2.x as the
  active branch.

### Added (contributor experience)
- **Code of Conduct** ([CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)) -
  Contributor Covenant 2.1 with a regulated-industry addendum
  (deliberately misleading conformance reports, vulnerability claims,
  or benchmark numbers are treated as a CoC violation). Enforcement
  contact: **conduct@kpifinity.com**.
- **Maintainers roster** ([MAINTAINERS.md](./MAINTAINERS.md)) - human
  side of [.github/CODEOWNERS](./.github/CODEOWNERS): named teams
  (`owners`, `maintainers`, `spec-stewards`, `runtime-maintainers`,
  `security`), responsibilities, contact addresses, the path to
  becoming a maintainer, and the emeritus list.
- **Release runbook** ([RELEASING.md](./RELEASING.md)) - end-to-end
  procedure for cutting a tagged release: pre-flight checks, version
  bumps, CHANGELOG promotion, signed-tag push, cosign and
  `slsa-verifier` post-release verification, announcement, and
  abort/fix-forward rules.
- **`.editorconfig`** - baseline charset, line-ending, indent, and
  trailing-newline rules that match what ruff, black, pre-commit, and
  `.gitattributes` already enforce. Eliminates the diff-noise loop
  where Windows editors introduce CRLF and pre-commit then "fixes"
  them on every PR.
- **`.gitattributes`** - forces LF line endings for all source files
  so Windows + `git autocrlf` doesn't rewrite them on every `git add`.
  Pairs with `.editorconfig`; together they make the Cowork
  "modified externally" reminders stop firing on Windows clones.
- **Dev container** ([.devcontainer/devcontainer.json](./.devcontainer/devcontainer.json))
  - one-click reproducible environment on Python 3.11 (Debian
  bookworm) with git, GitHub CLI, Docker-in-Docker (for integration
  tests that spin up Postgres), pipx, all four CLIs installed in
  editable mode via [post-create.sh](./.devcontainer/post-create.sh),
  pre-commit hooks pre-installed, and a curated VS Code extension set
  (Ruff, Pylance, mypy, Even Better TOML, YAML, EditorConfig, GitHub
  Actions, Mermaid). Forwards ports 8000 / 8001 / 5432 / 8765.

### Added (runtime, v3 — PR 10a of 3)
- **v3 verdict envelope contract** at
  `reference-implementation/src/ski_model/v3/envelope.py`. Implements
  spec v3.0 §4.1–§4.6 as Pydantic v2 models: the five-verdict taxonomy
  (CLEAR / FLAG / NULL_UNMAPPED / NULL_STALE / DISCRETIONARY, preserved
  from v2.1), KG citations with `node_id`/`version`/`role`, formalizable
  assertions, the verifier result with status enum (AGREED /
  LLM_CONTRADICTION / NEURO_SYMBOLIC_DIVERGENCE / UNVERIFIABLE), model
  provenance with the six required hash + id fields enforcing the
  `sha256:` prefix at the Pydantic layer, the optional fast-path marker
  per §5.6, and the optional human-attestation field per §5.4. Both
  ConfigDicts that own `model_*` fields opt out of Pydantic's reserved
  namespace via `protected_namespaces=()` since the field names are
  normative per spec and cannot be renamed.
- **25 envelope unit tests** at
  `reference-implementation/src/ski_model/v3/tests/test_envelope.py`
  covering the verdict taxonomy, verifier status enum, KG citation
  roles, every `ModelProvenance` required field, the `sha256:` hash
  format, negative-case rejections, empty-assertion / UNVERIFIABLE for
  rules with no formalizable subset, the `verdict_path: "fast"`
  optional marker, and JSON round-trip for two representative envelope
  shapes. Verified passing under Python 3.10 + pydantic 2.6.3.
- **Scope note.** The `SKI_RUNTIME_VERSION` dispatch and the
  `/api/evaluate/v3` stub were originally planned for this PR but
  consistently truncated `server.py` mid-edit (the file's size, ~16KB,
  appears to trigger a write-flush bug independent of OneDrive). Both
  land in PR 10b alongside the LLM evaluator, either via a single-file
  rewrite of `server.py` or by extracting the dispatch into a
  `_v3_routes.py` module wired in with a single one-line import.

### Added (direction)
- **[RFC 0002 — SKI v3.0: Neuro-Symbolic Pivot](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md)**
  drafted. Proposes inverting the runtime so a sovereign KG-grounded
  LLM is the primary reasoner on every verdict and the existing
  Symbolic Evaluator becomes an independent verifier of the LLM's
  output. Elevates the Knowledge Graph from routing table to typed
  semantic substrate (typed obligations, jurisdictional scope,
  effective-date intervals, exemptions, precedent edges). Replaces
  *deterministic replay* with *verifiable provenance* (signed model
  weights, signed KG version, signed LLM transcript, KG citations,
  hash-chained verifier results) as the v3 defensibility story.
  Aligns the implementation with the framework's name. **Status:
  Draft (14-day feedback window open).** Subsequent PRs (rewrite of
  public-facing positioning, spec v3.0 document, KG schema upgrade,
  runtime inversion, audit-trail expansion, canary repurpose, tag
  registry repurpose, conformance reorganization) are sequenced in
  the RFC's Rollout plan.

### Changed (positioning)
- **[README.md](./README.md), [CITATION.cff](./CITATION.cff), and
  [docs/index.md](./docs/index.md) rewritten** to lead with the v3
  neuro-symbolic-sovereign framing from RFC 0002. The S/K/I pillars
  each receive a normative description, the KG is described as a typed
  semantic substrate rather than a routing table, the LLM is described
  as the primary reasoner rather than a fallback, and the symbolic
  layer is described as an independent verifier. The released code
  (v0.2.x implementing spec v2.1) is explicitly called out so visitors
  understand which framing matches main today versus which is in
  design. No engineering changes; tools and conformance docs continue
  to describe v2.1 until their respective v3 PRs land.

### Added (spec)
- **[Specification v3.0 (Draft)](./docs/specification-v3.md)** drafted
  as the normative spec implementations of v3.0 must satisfy.
  Restates the architecture in MUST/SHOULD/MAY language, defines the
  Knowledge Graph schema (typed obligations, jurisdictional scope,
  effective-date intervals, signatures, validation requirements),
  specifies the verdict envelope (the five-verdict taxonomy is
  preserved; the envelope is extended with kg_citations,
  formalizable_assertions, verifier_result, model_provenance,
  transcript_ref), defines the runtime pipeline, the risk-tier
  governor with low/medium/high policies, the symbolic verifier's
  AGREED/LLM_CONTRADICTION/NEURO_SYMBOLIC_DIVERGENCE/UNVERIFIABLE
  statuses, sovereignty strict and advisory modes, the
  /api/sovereignty attestation endpoint, the audit-ledger schema and
  append-only enforcement, the verifiable-inference receipt
  requirement at Level 3, the provenance re-verification replay
  procedure, the three conformance levels redefined for verifiable
  provenance, and the backwards-compatibility plan for v2.x ledger
  entries, v2.x KGs, and the deprecated `track` field. The
  specification supersedes v2.1 (external, at skiframework.org); it
  is published under CC BY 4.0 in line with the project's spec
  licensing policy. Added to the docs site nav under a new
  Specification section.

### Added (tools, v3)
- **`kg-validator` v3 schema support** added behind a `--schema v3`
  flag on the existing `validate` command. The v2 path (flat rule
  list) is unchanged and remains the default. The new
  `kg_validator.v3` subpackage adds Pydantic v2 models for every v3
  node and edge type per spec v3.0 §3.1–§3.2 (Subject, Rule,
  Obligation, Definition, Exemption, Precedent, Jurisdiction,
  Citation; applies_to, consists_of, defined_by, exempted_by,
  amended_by, interpreted_by, scoped_to, cited_by), the closed
  ObligationType enumeration from §3.3, the RiskTier enumeration
  from §5.4, a JSON loader (`load_v3_kg`), and a `V3Validator`
  running this first pass of the §3.6 validation suite (duplicate
  node ids, dangling edges, edge target-type mismatches, rules with
  no consists_of obligation, orphan obligations). Pydantic-layer
  rejections cover missing `effective_date_start`, unknown
  obligation types, unknown risk tiers, and unknown edge types.
  Deferred to a follow-up: contradictory-obligation detection,
  date-interval overlaps, cyclic precedent edges, definition-scope
  checking.
- **Demo v3 KG** at `examples/energy/knowledge-graphs/kg-energy-v3-demo.json`.
  Two rules (SO2 cap, wastewater pH range) with typed obligations,
  jurisdictional scope, and citations; loads and validates clean.
- **`tools/kg-validator/tests/test_v3_validator.py`** — 20+ tests
  covering schema rejection, every validation pass, the demo KG,
  the obligation/edge/risk-tier enumerations against spec, and
  JSON round-trip.

### Planned for v0.3.0
- Per-shard horizontal scaling (Theme B): shard router, per-tenant
  config wiring through the sidecar, Postgres ledger partitioning,
  Kubernetes operator + CRDs.
- Sigstore / cosign image signing and SLSA Level 3 provenance.
- Additional LLM backends behind a uniform interface: vLLM, llama.cpp,
  Bedrock, Vertex.

### Planned for v3.0.0
- The v3 pivot, per [RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md).
  v2.x ledger entries remain readable; v3.0 ships a flagged dual-runtime
  for one minor version before the v3 path becomes default.

## [0.2.1] - 2026-05-25

Specification: **v2.1** (no spec changes). Patch release closing two
correctness bugs uncovered by the v0.2.0 post-release test pass. No
schema or API changes; safe to upgrade from 0.2.0 by pulling main.

### Fixed
- **Symbolic Evaluator package now exports `Verdict`.** The v0.2 test
  module `symbolic_evaluator/tests/test_stateful.py` imports
  `from symbolic_evaluator import Verdict`, but the package's
  `__init__.py` only re-exported `SymbolicDecision` and
  `SymbolicEvaluator`, so the test file failed at collection. CI would
  have caught this if the test had ever been collected. Fix is a
  one-line `__init__.py` change; all 10 stateful tests now pass.
- **kg-validator now detects contradictory limits driven by the
  relation field.** `_is_contradictory()` previously inspected only
  the object text for keywords like "max" / "below" / "not exceed",
  so a pair of rules under `must_not_exceed` with objects like
  "100 ppm sulfur dioxide" vs "50 ppm sulfur dioxide" was missed.
  The detector now also reads the shared `relation` field, recognises
  bound-style relations (`must_not_exceed`, `must_be_at_least`,
  `must_be_below`, etc.), and flags any numeric disagreement as
  `CONTRADICTORY`. Two new unit tests lock in the behaviour and a
  third proves identical thresholds are NOT flagged.

### Backwards compatibility
- Pure bug-fix release. Same Postgres schema, same Knowledge Graph
  schema, same wire formats. No migration required.

## [0.2.0] — 2026-05-22

Specification: **v2.1** (no spec changes). Closes the `NULL_STALE` gap
and lands the deterministic-replay primitive that Level 3 conformance
depends on. Theme A of the v0.2 architectural plan.

### Added
- **Telemetry buffer (RFC 0001).** Postgres-backed, append-only at the
  database layer (same trigger pattern as `ledger_entries`), RANGE-
  partitioned by `telemetry_ts` for retention-by-partition-drop.
- **Per-tenant configuration.** New `tenants` table with explicit
  `buffer_retention_days`; no default value baked in. A `'default'`
  tenant row is inserted by migration 002 for single-tenant
  compatibility.
- **Five new predicate operators** in the Symbolic Evaluator:
  `window_count`, `window_sum`, `window_avg`, `since_last`, `debounce`.
- **`requires_recent_within_seconds` wired end-to-end** — `NULL_STALE`
  is produced when the buffer has no sample in the window.
- **Async evaluator API** — `SymbolicEvaluator.aevaluate()` is the
  async entry point used by the server. The synchronous `evaluate()`
  remains for stateless predicates.
- **Authoritative-clock semantics.** Telemetry timestamp is "now" for
  stateful evaluation; wall-clock is never consulted. Replay
  determinism depends on this.
- **`audit-ledger replay` command** — re-evaluates a ledger range
  against the recorded buffer state, exits non-zero on divergence.
  See [docs/REPLAY.md](./docs/REPLAY.md).
- **Schema versioning** on `ledger_entries`. v0.1 entries tagged
  `'0.1.0'` by migration; new entries `'0.2.0'`. Replay skips v0.1
  entries with a note.
- **Conformance Level 2 tests** under `conformance/level2/`.
- **Alembic migrations** under `reference-implementation/migrations/`.
  See [docs/MIGRATIONS.md](./docs/MIGRATIONS.md).
- **Energy demo KG** gains a stateful rule:
  `energy.so2.window_avg_60s` (60-second rolling SO₂ avg ≤ 100 ppm).
- **New docs**: RFC 0001, REPLAY.md, MIGRATIONS.md.

### Changed
- SKI Model service version → `0.2.0`.
- The server writes every accepted telemetry record to the buffer
  before evaluation so self-referential window queries see the current
  event.
- CI conformance job runs both Level 1 and Level 2 markers.

### Backwards compatibility
- v0.1 ledger entries read without change.
- Synchronous `SymbolicEvaluator.evaluate()` is retained.
- Stateful predicates evaluated on a v0.1 runtime return
  `DISCRETIONARY` rather than silently mis-evaluating.

### Migration impact
- Operators upgrading from v0.1 must:
  1. `audit-ledger backup ...`
  2. `alembic -c reference-implementation/migrations/alembic.ini upgrade head`
  3. `audit-ledger verify ...`
- The default `'default'` tenant keeps single-tenant deployments
  working with no configuration changes.

### Known limitations
- Per-shard throughput ceiling ~5k records/sec (buffer query bound).
  Horizontal scaling lands in v0.3.0.
- Track 2 (LLM) entries are skipped during replay — they remain
  best-effort deterministic until v0.3.0 TPM-attested model loading.

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
- **`audit-ledger backup_