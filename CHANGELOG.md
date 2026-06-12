# Changelog

All notable changes to this repository are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **specification** version (currently v3.0) is tracked separately and
referenced from each release entry.

## [Unreleased]

### Added
- **`/metrics` — the observability contract, implemented.** The
  Prometheus + Grafana stack and `monitoring/rules/ski-alerts.yml` have
  shipped since v2.1, but the runtime never exported the series the
  alert rules fire on. The SKI Model now exposes `/metrics`
  (`ski_agreement_rate`, `ski_kg_signature_verified`,
  `ski_ledger_sequence_gaps_total`, verdict counters by type, evaluation
  latency histogram, runtime info), the sidecar exports
  `ski_sidecar_last_telemetry_timestamp`, and the ledger client trips
  the sequence-gap counter when the single-writer invariant is violated
  (rows appearing/vanishing underneath the writer — a tamper/ops
  signal). A regression test parses the alert rules and asserts every
  referenced series is exported, so the contract can't silently drift
  again. `/metrics` is unauthenticated by design (scrape endpoint;
  aggregates only) and contained by the sovereign-boundary
  NetworkPolicy.

### Added
- **`ski-schemas` — the wire contract, defined once** (RFC 0003 PR 1).
  The verdict envelope, signed LLM transcript, and measurement record
  now live in `tools/ski-schemas` (deps: pydantic only); the server,
  `ski-sdk`, and the conformance suite import the same objects.
  `ski_model.v3.envelope` / `ski_model.v3.transcript` remain as
  re-export shims, so existing imports keep working. The SDK's vendored
  models and the field-parity drift test are gone — replaced by an
  identity test (drift is structurally impossible). The runtime image
  now builds from the repo root so it carries the shared package;
  compose, CI, the L3 air-gap rig, and the release workflow build
  contexts updated. Sixth PyPI package: `ski-schemas` 0.1.0.

### Added
- **Helm chart** (`deploy/helm/ski`) — Kubernetes deployment that
  *enforces* the framework's constraints instead of documenting them:
  the render fails on `replicas`/`replicaCount` (single writer by
  design; shard by release), fails without an operator-supplied Secret
  (no default credentials anywhere), and fails without a signed-KG
  ConfigMap. The sovereign boundary ships as a NetworkPolicy (egress
  only to ledger + LLM backend; `networkPolicy.airgap=true` drops DNS
  too). Bundled evaluation Postgres (ledger SQL byte-identical to the
  reference implementation, CI-enforced) and Ollama; vLLM via external
  GPU endpoint. CI lints, renders three permutations, and asserts the
  constraint failures fail.

### Added
- **vLLM backend** (`SKI_V3_LLM_BACKEND=vllm`) — the production GPU
  inference path. OpenAI-compatible `/v1/chat/completions` with vLLM's
  `guided_json` decoder-level grammar enforcement (token masking against
  `RESPONSE_GRAMMAR` — stronger than post-hoc validation), temperature 0
  and per-request seed, and the same malformed-output -> DISCRETIONARY
  degradation contract as every backend. Provenance: set
  `$SKI_MODEL_FILE_SHA256` to anchor the served-weights digest; the
  vendor-commitment fallback is logged as a weaker signal. The backend
  verifies the configured model is actually served via `/v1/models`.
  `python -m evals.run --backend vllm` wires it into the eval suite.

### Fixed
- **Verifier observation grounding — fabricated observations no longer
  pass verification.** Eval run 4 produced a false FLAG: the model
  fuzzy-matched a deliberately unmapped measurement key onto a KG
  metric and invented the reading; the arithmetic was internally
  consistent, so the arithmetic-only Symbolic Verifier agreed. The
  verifier now cross-checks every stateless assertion against the
  actual measurement record: a metric the measurement doesn't contain,
  or an `observed` differing from what it records, is a fabricated
  observation → LLM_CONTRADICTION → DISCRETIONARY. Stateful (windowed)
  assertions are exempt (their observation is an aggregate, grounded
  against the telemetry buffer). Prompt pins per-predicate comparison
  semantics (inclusive boundaries) and warns that observations are
  cross-checked; template bumped to `ski.v3.evaluate.5`.

### Added
- **EU AI Act crosswalk** (`docs/crosswalks/eu-ai-act.md`). Article-level
  mapping of SKI controls to Regulation (EU) 2024/1689 ahead of the
  2 August 2026 applicability date for high-risk AI system obligations.
  Covers provider requirements (Articles 9-19, 72) and deployer
  obligations (Article 26) with explicit coverage levels, an
  element-by-element Article 12(3) record-keeping mapping onto the audit
  ledger, and a stated out-of-scope boundary (classification, FRIA,
  conformity assessment, GPAI). Informative, not legal advice.

### Fixed
- **Evaluator crash on schema-violating model output.** The first
  nightly real-model eval run found that a response which parses as
  JSON but violates the envelope schema (qwen2.5:7b emitted
  `"value": {"min": 6.0, "max": 8.5}` and `"observed": {"value": 7.2}`)
  raised `pydantic.ValidationError` out of
  `aevaluate_with_transcript` — a 500 on `/api/evaluate` in production.
  Contract violations now degrade to DISCRETIONARY with zero checkable
  assertions and the violation recorded in the envelope, the same way
  malformed JSON degrades at the backend. Hardened at all three layers:
  output-contract guard in the evaluator, `RESPONSE_GRAMMAR` now types
  `value`/`observed` (objects forbidden), and the prompt pins the
  scalar/array shapes (template bumped to `ski.v3.evaluate.3`).

### Added
- **Performance benchmark suite** (`benchmarks/`). Measures the
  production evaluation path with the latency decomposition the spec's
  claims actually rest on: `pipeline` mode isolates **framework
  overhead** (scoping, citation validation, symbolic verification,
  risk-tier policy, ed25519 transcript signing — everything except LLM
  inference) and `http` mode measures end-to-end against a live
  deployment. Reference numbers: framework overhead is **sub-millisecond
  at p99** (0.36 ms on 2 vCPUs) — ~250× inside the 100 ms budget. CI
  gates every build on `framework_total` p99 ≤ 100 ms and uploads the
  full report as an artifact. Methodology and caveats: `docs/benchmarks.md`.
- **L3 air-gapped boot rig — Sovereignty conformance is now 6/6 runnable**
  (`conformance/sovereignty/test_air_gapped.py`). The rig boots the audit
  ledger with `--network=none` and joins the SKI Model runtime to the same
  loopback-only network namespace (`--network=container:`), so neither
  process has an interface, route, or resolver beyond `lo`. It then proves
  the namespace is loopback-only, replays a fixed five-measurement workload
  against a **signed** KG from inside the gap, and verifies hash-chained
  ledger persistence via `psql` from inside the same namespace. Opt-in via
  `SKI_L3_AIRGAP=1` (Docker required; `SKI_L3_IMAGE` overrides the image);
  skips cleanly otherwise. CI runs it as a gating job. Conformance suite
  revision bumped to 0.5.0.
- **SKI Evals — the verdict-accuracy evaluation suite** (`evals/`). A
  50-case human-labeled energy golden dataset (boundary values,
  jurisdiction scoping, effective-date scoping) evaluated through the
  real production path (`kg_loader.scope_to` -> `V3Evaluator`), with
  published metrics: verdict accuracy, FLAG recall/precision,
  **breaches-silently-CLEARed** (must be 0), NULL_UNMAPPED recall,
  assertion correctness, and the LLM-verifier agreement rate. The
  deterministic FakeLLM baseline is pinned in CI and demonstrates the
  architecture's safety property: on the model's deliberate blind spots
  the Symbolic Verifier records LLM_CONTRADICTION and the verdict
  routes to DISCRETIONARY - zero breaches silently cleared. Real-model
  numbers run nightly via `.github/workflows/evals.yml` (Ollama,
  qwen2.5:7b-instruct). Methodology: `docs/evals.md`.

## [3.1.0-alpha.2] — 2026-06-10

> **Why alpha.2 and no alpha.1 on PyPI:** the `v3.1.0-alpha.1` tag was
> cut before this version-bump PR merged, so its workflow built
> 3.0.3-versioned artifacts under the new tag. No packages reached
> PyPI. Per RELEASING.md the tag is not deleted; its GitHub release is
> marked superseded, and alpha.2 is the first published cut of the
> v3.1 line.

### Added
- **PyPI distribution via trusted publishing.** The release workflow now
  publishes every wheel/sdist to PyPI using OIDC trusted publishing (no
  stored tokens), through the `pypi` GitHub environment. `ski-sdk` is
  included in the release build for the first time.
- **Governance and policy documents:** `ROADMAP.md` (single public
  roadmap), `TRADEMARKS.md` (trademark + conformance-mark policy),
  `SUPPORT.md`, and RFC 0003 (`ski-sdk` / `ski-schemas`), which the
  shipped SDK referenced but which had never been filed.

### Changed
- **CLI tool distribution names are now namespaced** for PyPI:
  `kg-extractor` → `ski-kg-extractor`, `kg-validator` →
  `ski-kg-validator`, `audit-ledger` → `ski-audit-ledger`
  (`ski-model-deploy` and `ski-sdk` unchanged). The installed CLI
  command names and import paths are unchanged.
- **Published packages declare dependency ranges instead of exact
  pins.** Exact pins in a published library force resolver conflicts on
  every consumer. The pinned versions move to each tool's
  `requirements.txt` (which still drives SBOMs and reproducible dev
  installs). This also resolves the latent `httpx==0.27.0` (tools) vs
  `httpx==0.28.1` (requirements-dev) conflict in the editable-install
  path used by CI.
- **CI advisory jobs now gate.** Lint (ruff + mypy), unit tests
  (3.10–3.12), bandit, pip-audit, SBOM, and the Trivy container scan
  block merges; a coverage floor of 70% is enforced (measured 72% at
  the time of the change). `commit-signatures` remains advisory by
  design.

### Added
- **`ski-sdk` v0 — a typed Python client for the SKI Model.** `SKIClient` /
  `AsyncSKIClient` over `/api/*` returning parsed `V3VerdictEnvelope` objects,
  a typed error hierarchy, and a one-call `verify_transcript()` that checks a
  verdict's Ed25519 provenance (signature + recorded hashes). Lives under
  `tools/ski-sdk`; depends only on `httpx`, `pydantic`, `cryptography` (no
  dependency on the reference implementation). A contract-drift test asserts the
  SDK's models stay field-for-field in sync with the server's envelope,
  transcript, and measurement models. Implements PR 2 of RFC 0003; the
  `ski-schemas` extraction (PR 1) is deferred.

### Added
- **Sovereignty (L3) conformance: four of six checks now runnable.** Implemented
  `single_worker`, `no_outbound_calls`, `jurisdiction_scope_captured`, and
  `signed_llm_transcript` as black-box structural checks, plus a functional
  no-network-egress test in the runtime suite (`v3/tests/test_no_egress.py`).
  Tamper-resistance and air-gapped boot remain pending their Postgres / container
  fixtures.

### Fixed
- **CLI `version` commands now report the real version.** The four tools'
  `src/<pkg>/__init__.py` carried stale `__version__` values (`0.1.0a0` /
  `3.0.0`) that the release process never bumped — so `kg-validator version`
  and `kg-extractor version` reported `3.0.0`. Synced all four to the package
  version and extended the release runbook to cover them (plus the tool
  classifiers and `server.py`'s `_VERSION`).

### Changed
- **Docs/examples hygiene.** `QUICKSTART.md` no longer lists the dropped Python
  3.9 as a prerequisite, the four tool `pyproject.toml` classifiers drop the
  stale `Python :: 3.9` entry, and the quickstart gains a no-Docker "Quick
  check" that runs the evaluate → verify path through the `FakeLLM` backend.

### Removed
- Deleted the stale `reference-implementation/examples/knowledge-graphs/sample-energy-kg.json`
  (old v2 `rules` format; it failed v3 validation). The current examples live
  under `examples/<sector>/knowledge-graphs/`.

## [3.0.3] — 2026-06-05

### Fixed
- **kg-extractor `chunk_text` no longer loops indefinitely.** For inputs longer
  than `max_chunk_size` with `overlap > 0`, the sliding window never advanced
  past end-of-text and spun forever, hanging extraction of any real-sized
  document. The loop now terminates on the final chunk, and invalid arguments
  (`max_chunk_size <= 0` or `overlap >= max_chunk_size`) raise `ValueError`
  instead of hanging. Regression tests added.
- **Symbolic Verifier wording.** An unknown predicate is now reported as
  "not mechanically verifiable (no v3 handler)" rather than "not a known v3
  predicate", matching the verifier-contract test and auditor-facing language.

### Changed
- **pytest configuration consolidated into `pyproject.toml`.** A redundant root
  `pytest.ini` silently shadowed it, dropping `asyncio_mode` and the conformance
  markers and leaving the root `pytest` run red. The duplicate has been removed,
  the conformance markers are registered centrally, and the four tool test
  suites no longer collide on a shared `tests` package name; `pytest` now runs
  green from the repository root. `conformance/pytest.ini` is retained so the
  conformance suite can still be run standalone.
- **v3 `/api/evaluate` tests are hermetic.** They no longer require a writable
  `/app` directory or a live ledger, and the in-memory ledger double tracks the
  current `append_v3` API.

### Removed
- **Dropped support for Python 3.9** (end-of-life since 2025-10). The CI test
  matrix, the `ruff` target version, and the tools' `requires-python` now target
  Python 3.10+. This was required to adopt the security-patched dependency
  versions below, which no longer publish 3.9 wheels.

### Security
- **Upgraded dependencies to patched versions across every deployable
  requirements file**, clearing all `pip-audit` findings in the production
  runtime (SKI Model + Sidecar) and the four tools: `cryptography`
  42.0.5 → 46.0.7 (4 CVEs, including ones in the library used for transcript
  signing), `fastapi` 0.110.0 → 0.136.3 (pulls `starlette` ≥1.2, clearing 3
  CVEs), `python-dotenv` 1.0.1 → 1.2.2, `jinja2` 3.1.3 → 3.1.6, and `pypdf`
  4.2.0 → 6.12.2, with `pydantic` 2.6.3 → 2.13.4 and `uvicorn` 0.27.1 → 0.48.0
  for compatibility. The full test suite and `mypy` pass on the upgraded set.
- **Dev/CI tooling upgraded** to clear the remaining `requirements-dev.txt`
  advisories: `pytest` 8.1.1 → 9.0.3 (with `pytest-asyncio` 1.4.0,
  `pytest-httpx` 0.36.2, `pytest-cov` 7.1.0, `pytest-mock` 3.15.1, `pip-audit`
  2.10.0 and `httpx` 0.28.1 for compatibility) and `cyclonedx-bom` 4.4.3 → 7.3.0
  (which drops the transitive `lxml`). `pip-audit` now reports zero findings for
  every requirements file in the repository.
- **Transcript signing key is now created with `0600` permissions from the
  outset** rather than written and then `chmod`-ed, closing a brief window in
  which the Ed25519 private key could exist at the default umask.

## [3.0.2] — 2026-06-02

**Patch: auto-apply the v3 ledger migration on startup.** Closes the
last gap in the v3.0.0 ledger-schema saga. v3.0.1 fixed the schema for
**fresh** Postgres volumes; v3.0.2 fixes the schema for **existing**
volumes (upgrades from v3.0.0 / v3.0.1 / v0.2.x on the same data dir).
The runtime now probes ``ledger_entries`` on startup and applies the
``0002_transcript_columns`` migration in place if the v3 columns are
missing — invisible to operators who pull the new image and restart.
Same tester credit as v3.0.1 for catching it.

### Added (runtime, v3 — PR 16, startup migration runner)
- **`ski_model.ledger_migrations`** — new module. Probes
  ``ledger_entries`` on startup for the six v3 audit-trail columns;
  if any are missing, applies the ``0002_transcript_columns``
  migration in place. Idempotent. Closes the gap exposed by PR 15:
  Postgres' ``/docker-entrypoint-initdb.d/`` scripts only run on
  first init, so operators upgrading v3.0.0 / v3.0.1 / v0.2.x against
  an existing Postgres volume hit
  ``column "envelope_json" of relation "ledger_entries" does not exist``
  at evaluation time. With this PR the migration auto-applies
  invisibly on the next restart.
- **`SKI_AUTOMIGRATE` environment variable** (default ``true``).
  Hardened deployments can set ``false`` to require explicit
  DBA-driven migrations; the runtime then logs the exact ``psql``
  command and refuses to serve if the v3 columns are missing.
- **`conformance/durability/test_ledger_migrations_runner.py`** — six
  assertions pinning the runner: module exists, embedded SQL covers
  every v3 column, embedded SQL matches the canonical
  ``0002_transcript_columns.sql``, the constraint guards are
  idempotent, ``server.py`` lifespan calls the runner, and
  ``SKI_AUTOMIGRATE`` is honoured.
- **`docs/migrations.md`** — documents the auto-apply behaviour and
  the opt-out lever; preserves the manual ``psql`` procedure for
  v3.0.0 / v3.0.1 operators who can't yet upgrade to v3.0.2.

### Migration note for v3.0.0 / v3.0.1 operators

If you can wait, just upgrade to v3.0.2 — auto-apply handles the
schema gap on next restart, no manual step required.

If you need a fix today on v3.0.0 / v3.0.1, apply the migration by
hand against the running database:

```bash
docker compose exec ledger-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/03-transcript-columns.sql
```

Or `docker compose down -v && docker compose up` if you can afford to
discard the volume.

## [3.0.1] — 2026-06-02

## [3.0.1] — 2026-06-02

**Patch: ledger schema v3 baseline.** Hours after v3.0.0 shipped, a
fresh `docker compose up` deployment hit
`/api/evaluate -> 500: column "envelope_json" of relation
"ledger_entries" does not exist`. Root cause: docker-compose mounted
only the v2.1 baseline `schema.sql` into Postgres' initdb directory;
the v3 migration `0002_transcript_columns.sql` was never executed on
fresh installs. v0.2 → v3 upgrades that applied the migration manually
were fine. PR 15 (#76) fixes the fresh-deploy path. Credit to the
tester who reproduced and traced the failure cleanly.

### Fixed (runtime, v3 — PR 15, ledger schema v3 baseline)
- **`/api/evaluate` 500 on fresh deployments.** Symptom:
  ``column "envelope_json" of relation "ledger_entries" does not
  exist``. Root cause: docker-compose mounted only the v2.1
  ``schema.sql`` into Postgres' ``/docker-entrypoint-initdb.d/``; the
  v3 migration ``migrations/0002_transcript_columns.sql`` was never
  executed on first init. v0.2.x → v3 *upgrades* applied the migration
  fine; fresh ``docker compose up`` deployments did not.
- **`reference-implementation/src/ledger/schema.sql`** rewritten to the
  v3 baseline. The CREATE TABLE now declares ``envelope_json``,
  ``envelope_hash``, ``transcript_json``, ``transcript_signature``,
  ``signing_key_id``, and ``verifier_status`` inline, with the four-
  status CHECK constraint on ``verifier_status`` and the relaxed
  ``track`` CHECK. Indexes for ``verifier_status`` and ``signing_key_id``
  are baked in too. Fresh deployments now boot with the column set the
  v3 runtime requires.
- **`reference-implementation/src/ledger/migrations/0002_transcript_columns.sql`**
  hardened for idempotency. The verifier-status CHECK is now
  drop-then-add so re-running the migration against a fresh v3 schema
  (where the inline constraint already exists) is a no-op rather than a
  conflict.
- **`reference-implementation/docker-compose.yml`** also mounts
  ``0002_transcript_columns.sql`` as ``03-transcript-columns.sql`` in
  ``/docker-entrypoint-initdb.d/``. Defence-in-depth: if ``schema.sql``
  ever regresses, initdb still runs the migration. With the v3
  baseline schema this mount is a no-op on fresh deployments.
- **`conformance/durability/test_ledger_schema_v3_columns.py`** — new
  regression test, five assertions:
  1. ``schema.sql`` declares all six v3 audit-trail columns.
  2. ``verifier_status`` CHECK lists the four spec §4.5 statuses.
  3. ``schema.sql`` header reads v3.0 (not v2.1).
  4. docker-compose still mounts the 0002 migration.
  5. The 0002 migration uses ``ADD COLUMN IF NOT EXISTS`` and
     ``DROP CONSTRAINT IF EXISTS`` so it is idempotent.

### Changed (docs, v3 — PR 15)
- **`docs/migrations.md`** — replaced the misleading "v3.0 introduced
  no breaking schema changes; v0.2 ledgers upgrade in place" line with
  an accurate description: existing v0.2 ledgers MUST run the 0002
  migration explicitly; fresh v3.0.1+ deployments get the columns from
  the rewritten baseline. Added an "Upgrading v0.2 → v3.0" subsection
  with the exact ``psql`` command and the symptom of the missed step.

### Migration note for operators

If you deployed v3.0.0 from `docker compose up` against a clean volume
and hit `column "envelope_json" of relation "ledger_entries" does not
exist`, the one-time fix is to apply the migration by hand:

```bash
psql "$LEDGER_DSN" -f reference-implementation/src/ledger/migrations/0002_transcript_columns.sql
```

`docker compose down -v && docker compose up` is equivalent if you can
afford to discard the volume; the new schema baseline + the mounted
migration both create the correct column set on a clean init.

## [3.0.0] — 2026-06-01

## [3.0.0] — 2026-06-01

**The neuro-symbolic pivot ships.** RFC 0002 is Accepted and implemented
across PRs 8–14 of the v3 stream. The KG-grounded sovereign LLM is the
primary reasoner on every verdict; the Symbolic Verifier mechanically
cross-checks the formalizable subset; the strict Risk-Tier Governor
reads the tier from the KG itself (no caller self-declaration); every
verdict carries a signed LLM transcript with KG citations and the
verifier's per-assertion result. The audit story moves from
*deterministic replay* to *verifiable provenance*. Conformance is
reorganised around three levels — Provenance, Durability, Sovereignty.

The release version of the runtime is `3.0.0` (was `3.0.0-alpha`); the
tools (`audit-ledger`, `kg-extractor`, `kg-validator`,
`ski-model-deploy`) jump from `0.2.1` to `3.0.0` to align with the
framework version.

### Changed (docs, v3 — PR 10f, v3 release-ready sweep)
- **`README.md`** — flipped from "v2.1 released / v3.0 in design" to
  "v3.0 current". Quick-start section rewritten without the v2.1
  caveat. Architecture section consolidated to the single v3 path
  (no more Track 1 / Track 2 split). Conformance table now lists
  Provenance / Durability / Sovereignty. Roadmap moved v3.0 from
  "planned" to "shipped" and added v3.1 / v3.2. Legacy v2 line moved
  to a "Superseded" subsection. Citation string updated to v3.0.0.
- **`docs/index.md`** — same flip: success status block, current spec
  badge v3.0, no "in design" caveats. Quick start cleaned.
- **`docs/RFCs/index.md`** — RFC 0002 moved from Draft to "Accepted
  (implemented)" with the implementation date and PR range.
- **`docs/RFCs/0002-v3-neuro-symbolic-pivot.md`** — status table now
  reads "Accepted — implemented" with accepted/implemented dates.
- **`docs/migrations.md`** — added a v3.0 row noting no schema
  migration was required; v0.2 ledgers upgrade in place.
- **`docs/glossary.md`** — full rewrite for the v3 vocabulary.
  Added: Agreement monitor, Extraction quality, Formalizable
  assertion, Jurisdictional scope, LLM transcript, Risk-Tier
  Governor, Symbolic Verifier, Verdict envelope, Verifier status.
  Retired / renamed: Determinism canary (marked retired with a
  pointer to Agreement monitor), Track 1 / Track 2 (gone — single v3
  path), Symbolic Evaluator (entry merged into Symbolic Verifier).
- **`docs/getting-started.md`** — status banner updated; "Core
  concepts in five minutes" rewritten around the v3 vocabulary
  (Risk-Tier Governor, KG-grounded LLM evaluator, Symbolic Verifier).
- **`docs/specification-v3.md`** — status table updated from "Draft
  (pending RFC 0002 acceptance)" to "Active (RFC 0002 accepted;
  implemented in v3.0.0)".
- **`docs/knowledge-graph.md`** and **`docs/architecture.md`** — status
  banners point readers to the v3 spec / RFC 0002 as the
  authoritative references; full rewrites tracked as a follow-up.

### Changed (compilation tools, v3 — PR 10e, strip v2 paths)
- **`kg-validator` is v3-only.** The flat-rule-list (`v2`) shape is no
  longer supported. The v3 subpackage has been flattened to the top
  level: ``kg_validator.models``, ``kg_validator.loader``,
  ``kg_validator.validator`` are the entry points. The CLI exposes a
  single ``validate`` subcommand. The v2 ``review``,
  ``detect-conflicts``, ``detect-duplicates``, and HTML ``report``
  subcommands are retired — v3 conflict / duplicate detection happens
  at the typed-obligation level inside the §3.6 validation passes and
  surfaces in the issue report.
- **`kg-extractor` emits v3 KGs by default.** Each extracted rule is
  wrapped into the typed-graph shape (Rule + Obligation + Subject +
  Citation + edges) via the new ``kg_extractor.v3_emitter.emit_v3_kg``
  function. The ``extract`` CLI gains ``--jurisdiction`` and
  ``--jurisdiction-name`` flags; a ``--emit-raw`` flag preserves the
  pre-PR-10e flat-rule output for debugging.
- **`ConfidenceLevel` → `ExtractionQuality` on extracted rules.** The
  per-rule trust signal is renamed to make clear it is the
  *extractor's* authoring-time judgement, not a runtime confidence
  score (Axiom 2 still prohibits confidence in the audit trail). The
  field on ``ComplianceRule`` is now ``extraction_quality``;
  ``ExtractionMetadata.rules_by_quality`` replaces
  ``rules_by_confidence``. Backends that still emit ``confidence`` on
  the wire are accepted for compatibility — the value is mapped
  through.
- **Filter CLI**: ``kg-extractor filter --confidence`` →
  ``kg-extractor filter --quality``. Choices restricted to the three
  ``ExtractionQuality`` values via ``click.Choice``.

### Removed (compilation tools, v3 — PR 10e)
- ``tools/kg-validator/src/kg_validator/v3/`` subpackage (flattened to
  top level).
- ``tools/kg-validator/src/kg_validator/conflict_detector.py``,
  ``utils.py``, and the v2 ``models.py`` / ``validator.py``
  (overwritten by the v3 equivalents).
- ``tools/kg-validator/tests/test_validator.py`` (v2 tests; the v3
  tests at ``test_v3_validator.py`` are the only ones now).
- ``tools/kg-validator/examples/sample-extracted-rules.json`` (v2
  flat-rule sample; v3 sample lives at
  ``examples/energy/knowledge-graphs/kg-energy-v3-demo.json``).

### Changed (conformance, v3 — PR 14, verifiable-provenance reorg)
- **Conformance suite reorganised around verifiable provenance.** The
  three levels are now ``provenance/`` (L1), ``durability/`` (L2),
  ``sovereignty/`` (L3). Old ``level1/`` and ``level2/`` directories
  are removed; their tests are redistributed by what they actually
  prove (envelope completeness vs audit-chain durability).
- **`conformance/provenance/`** — every verdict carries a complete,
  verifier-checked provenance record (envelope shape, ModelProvenance
  hashes, verifier statuses, KGCitationRoles, agreement monitor,
  NULL_STALE routing, window-predicate correctness).
- **`conformance/durability/`** — provenance is signed, replayable,
  and audit-chained (signed KG required, strict risk-tier governor,
  append-only triggers, hash-chain entry recomputation, replay CLI,
  live-deployment determinism, coverage register).
- **`conformance/sovereignty/`** — scaffolded only. Six skipped tests
  with spec citations: no-outbound-calls, air-gapped boot, tamper
  resistance, single-worker enforcement, jurisdiction scope capture,
  signed LLM transcript. Harness is the v3.1 milestone.
- **`docs/conformance.md`** rewritten with the v3.0 mapping tables;
  the Level 1 / Level 2 / Level 3 framing is renamed to Provenance /
  Durability / Sovereignty throughout.
- **`pytest.ini` markers**: ``level1`` / ``level2`` / ``level3``
  retired in favour of ``provenance`` / ``durability`` /
  ``sovereignty``. CI invocations and self-asserted-conformance
  release notes need to update their marker selection.

### Added (runtime, v3 — PR 13, risk-tier governor)
- **`tag_registry.RiskTierGovernor`** — the authoritative source of
  risk tier per obligation (spec v3.0 §5.4). Reads each KG rule's
  optional ``risk_tier`` field and returns the strictest tier across
  the applicable obligations (``tier-1`` ≻ ``tier-2`` ≻ ``tier-3``).
  Rules with no ``risk_tier`` default to ``tier-2``. Aliases
  (``high``, ``standard``, ``low``, ``tier1``, etc.) canonicalise to
  the three-tier vocabulary.
- **`v3/tests/test_risk_tier_governor.py`** — covers canonicalisation,
  strictest-rank semantics, empty / missing-field defaults, snapshot
  convenience, and the strict-governor contract (caller cannot
  influence tier via extra keys on the obligation payload).

### Changed (runtime, v3 — PR 13)
- **`MeasurementRecord.risk_tier` removed.** The caller can no longer
  declare a risk tier on the request. The server derives the tier from
  the KG snapshot via ``RiskTierGovernor.tier_for_snapshot(snapshot)``
  and passes it to ``V3Evaluator.aevaluate_with_transcript``. For
  backward compatibility, v2-shape payloads that still send
  ``risk_tier`` parse without error — Pydantic silently drops the
  unknown field. A regression test
  (``test_strict_governor_ignores_caller_risk_tier``) pins the
  behavior.
- **`tag_registry` package** now exports both ``TagRegistry`` (kept
  for KG-validator parity) and the new ``RiskTierGovernor``.

### Added (runtime, v3 — PR 12, agreement monitor)
- **`ski_model.v3.agreement_monitor.AgreementMonitor`** — rolling-window
  tracker of LLM↔verifier agreement. Every produced
  `V3VerdictEnvelope` feeds its `verifier_result.status` into the
  monitor; `agreement_rate = AGREED / total` is recomputed on demand.
  `is_healthy()` returns `True` iff the rate ≥ `threshold`. Default
  window is the last 1000 evaluations; default threshold is `0.95`.
  Both are configurable via `$SKI_AGREEMENT_WINDOW` and
  `$SKI_AGREEMENT_THRESHOLD`. Thread-safe via an internal lock.
- **`v3/tests/test_agreement_monitor.py`** (16 tests covering record /
  snapshot / window-roll / threshold edge cases and validation).

### Changed (runtime, v3 — PR 12)
- **`/api/canary`** now returns the agreement-monitor snapshot instead
  of the v2 determinism canary. Endpoint path preserved for operator
  continuity; payload shape is new (`window_size`, `threshold`,
  `observed`, `counts` per `VerifierStatus`, `agreement_rate`,
  `is_healthy`, `status`).
- **`/api/health`** ``canary_status`` field now reports
  ``"healthy"`` / ``"degraded"`` / ``"not_started"`` based on the
  agreement monitor.
- **`server.py`** wires every evaluation through
  ``state.agreement_monitor.record(envelope.verifier_result.status)``
  after producing the envelope.

### Removed (runtime, v3 — PR 12)
- **`ski_model/canary.py`** — the v2 ``DeterminismCanary`` background
  task. Replaced by the on-evaluation ``AgreementMonitor``.
- **`ski_model/backends.py`** — the v2 ``InferenceBackend`` /
  ``OllamaBackend`` / ``AnthropicDemoBackend`` abstraction. It was
  only used by the v2 canary; v3 inference goes through
  ``ski_model.v3.backends`` exclusively.

### Added (runtime, v3 — PR 11.7, jurisdiction-scoped KG snapshots)
- **`KnowledgeGraph.scope_to(jurisdiction, as_of)`** — returns a v3
  snapshot dict containing only obligations applicable to the tenant's
  jurisdiction *and* effective at the measurement's timestamp. The
  returned snapshot carries a ``scope`` block (``jurisdiction``,
  ``as_of``, ``n_in``, ``n_out``) so the LLM transcript records *what
  was sent* — auditors can replay the same scope and confirm.
- **Effective-date scoping** filters on each rule's optional
  ``effective_date`` and ``sunset_date`` (ISO-8601). Rules with no
  effective date are treated as always-effective.
- **Jurisdiction scoping** accepts the rule's ``jurisdiction`` as a
  string or a list of strings. Universal sentinels (``"global"``,
  ``"*"``, empty string) match any tenant. Comparison is
  case-insensitive. Rules with no ``jurisdiction`` field pass any
  tenant (treated as universal).
- **`MeasurementRecord.jurisdiction`** (optional) — tenant-declared
  jurisdiction (e.g. ``"us-ca"``, ``"eu"``). ``None`` means no
  jurisdiction filter; all rules effective at the measurement's
  timestamp are sent.
- **`v3/tests/test_kg_scoping.py`** (16 tests) covering effective-date
  scoping, jurisdiction scoping (string + list shapes), universal
  sentinels, case-insensitivity, combined filters, and snapshot shape.

### Changed (runtime, v3 — PR 11.7)
- **`server.py`** now calls ``state.knowledge_graph.scope_to(...)``
  instead of the unconditional ``_kg_to_v3_snapshot`` adapter.
  Real-sized KGs no longer blow the LLM context window — the prompt
  carries only the obligations applicable to the measurement.

### Added (verifier, v3 — PR 11.6, stateful predicates)
- **Stateful predicate handlers** in `SymbolicVerifier`:
  - `must_average_within` — rolling-window arithmetic mean must fall
    inside `value=[lo, hi]` over the last `window_seconds`.
  - `must_not_exceed_in_window` — *no* observation in the last
    `window_seconds` may exceed `value`.
  Real obligations like "rolling 24h pH average within 6.0–8.5" and
  "SO₂ peak in the last hour ≤ 100 ppm" are now mechanically
  verifiable.
- **`ski_model.v3.verifier.BufferLike`** — minimal Protocol describing
  the telemetry-buffer interface the verifier needs (`window_query`).
  The production `telemetry_buffer.TelemetryBuffer` already satisfies
  this; tests use an in-memory `FakeBuffer`. Re-exported from
  `ski_model.v3`.
- **`SymbolicVerifier.acheck_assertion(...)`** and
  **`SymbolicVerifier.averify(...)`** — async siblings of the sync
  methods that handle stateful predicates. Accept optional `subject`,
  `as_of`, and `buffer` kwargs; degrade to `UNVERIFIABLE` when any are
  missing for a stateful predicate.
- **`FormalizableAssertion.window_seconds`** — optional positive
  integer field (envelope schema additive change, safe). Required for
  stateful predicates.
- **`v3/tests/test_verifier_stateful.py`** (~15 tests) covering AGREED,
  LLM_CONTRADICTION, UNVERIFIABLE paths, multiple buffer return shapes,
  mixed stateless+stateful envelopes, envelope round-trip, and sync
  fallback degradation.

### Changed (runtime, v3 — PR 11.6)
- **`V3Evaluator.aevaluate`** and **`aevaluate_with_transcript`** now
  forward optional `subject`, `as_of`, and `buffer` kwargs to
  `SymbolicVerifier.averify(...)`. Stateless-only callers (most tests)
  see no API change.
- **`server.py`** passes `measurement.subject`, parsed
  `measurement.timestamp`, and `state.telemetry_buffer` to the
  evaluator. Stateful predicates emitted by future LLM backends
  immediately become verifiable end-to-end. Without a wired buffer
  they degrade to `UNVERIFIABLE` (operability issue, not correctness).

### Added (runtime, v3 — PR 11.5, real LLM backend)
- **`ski_model.v3.backends.OllamaV3Backend`** — calls a local Ollama
  runtime over HTTP. Weights stay on the operator's hardware (satisfies
  the "Sovereign" requirement). Sends `temperature=0`, fixed seed,
  `top_p=1.0`, `top_k=1`, `format="json"` for deterministic
  structured output. `model_weight_hash` is the actual digest from
  Ollama's `/api/show` endpoint; falls back to
  `sha256("ollama:" + model_name)` (vendor commitment) when Ollama is
  unreachable. Malformed structured output is mapped to `DISCRETIONARY`
  per spec §5.2 — never guessed at.
- **`ski_model.v3.backends.build_backend()`** — factory that reads
  `$SKI_V3_LLM_BACKEND` (`"fake"` default, `"ollama"`) and returns a
  configured `V3LLMBackend`. Unknown names raise so a misconfigured
  deployment cannot silently fall through to a default.
- **`ski_model.v3.backends.PROMPT_TEMPLATE_HASH`** and
  **`STRUCTURED_GRAMMAR_HASH`** — sha256 over the canonical framework
  prompt and structured-output grammar. Every conformant backend
  reports these in `ModelProvenance`. Replaces the PR 10b
  `FakeLLM` placeholder hashes (`sha256:1*64`, `sha256:2*64`) with
  real values — even tests now produce real provenance.
- **`v3/tests/test_backends_hashes.py`** (4 tests),
  **`v3/tests/test_backends_factory.py`** (5 tests),
  **`v3/tests/test_backends_ollama.py`** (9 tests using
  `pytest-httpx` to mock Ollama).

### Changed (runtime, v3 — PR 11.5)
- **`server.py`** delegates LLM backend construction to
  `v3.build_backend()`. Setting `SKI_V3_LLM_BACKEND=ollama` (plus
  `OLLAMA_BASE_URL`, `SKI_MODEL_NAME`, etc.) now wires real KG-grounded
  inference end-to-end with the same audit-trail, verifier, and
  risk-tier infrastructure as the FakeLLM path.

### Conformance impact (PR 11.5)
- `SKI_V3_LLM_BACKEND=fake` is the default — CI remains hermetic.
- `SKI_V3_LLM_BACKEND=ollama` requires a reachable Ollama instance with
  the named model pulled. Auditors who want to verify a verdict need
  the same model weights (digest matches the
  `model_provenance.model_weight_hash` recorded in the envelope).

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
  See [docs/replay.md](./docs/replay.md).
- **Schema versioning** on `ledger_entries`. v0.1 entries tagged
  `'0.1.0'` by migration; new entries `'0.2.0'`. Replay skips v0.1
  entries with a note.
- **Conformance Level 2 tests** under `conformance/level2/`.
- **Alembic migrations** under `reference-implementation/migrations/`.
  See [docs/migrations.md](./docs/migrations.md).
- **Energy demo KG** gains a stateful rule:
  `energy.so2.window_avg_60s` (60-second rolling SO₂ avg ≤ 100 ppm).
- **New docs**: RFC 0001, replay.md, migrations.md.

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