# Contributing to the SKI Framework

> **Status reminder:** SKI is in **early alpha**. The specification is stable at v2.1; the reference implementation and tooling are evolving rapidly. Expect breaking changes before v1.0.

Thank you for your interest in contributing. SKI is an open-core project: the framework specification and the reference tooling live here; the proprietary Knowledge Graph libraries live in a private KpiFinity repository and are not accessible from this one. See [Open / proprietary boundary](#open--proprietary-boundary) below.

## Ways to contribute

- **Report bugs** or suggest improvements via [GitHub Issues](https://github.com/kpifinity/ski-framework/issues). Use the issue templates so reports include the information we need.
- **Improve the specification** under `docs/`. Spec changes go through a longer review than code changes — see [Specification changes](#specification-changes).
- **Strengthen the reference implementation.** The Symbolic Evaluator, SKI Model wrapper, Tag Registry, and audit ledger all benefit from additional test coverage and adversarial scenarios.
- **Add conformance tests.** New Level 1 / Level 2 / Level 3 tests are some of the highest-leverage contributions you can make. See [conformance/README.md](./conformance/README.md).
- **Build MCP connectors** or telemetry adapters for new data sources.

## Open / proprietary boundary

This repository contains:
- The SKI Framework specification.
- The reference implementation (Symbolic Evaluator, SKI Model wrapper, Tag Registry, audit ledger, sidecar).
- Four CLI tools (`kg-extractor`, `kg-validator`, `ski-model-deploy`, `audit-ledger`).
- A conformance test suite.
- **Demo-only** example KGs and telemetry data — illustrative, never production-grade.

This repository does **not** contain:
- The commercial Knowledge Graph libraries (energy, finance, manufacturing, defense).
- Sector-specific MCP connectors with KpiFinity support contracts attached.
- Implementation playbooks delivered as part of KpiFinity engagements.

If you propose adding a production-grade sector KG to this repo, we will redirect you to either (a) trim it to ≤5 illustrative rules with a `DEMO ONLY` banner, or (b) publish it in a community-maintained `ski-framework-examples` repository under your own attribution. The commercial-grade KGs deliberately stay out of this repository.

## Getting started

```bash
git clone https://github.com/YOUR_USERNAME/ski-framework.git
cd ski-framework

python -m venv .venv && source .venv/bin/activate     # or `.venv\Scripts\activate` on Windows
pip install -r requirements-dev.txt

pre-commit install                                     # optional but recommended
pytest                                                  # unit tests
pytest conformance/                                     # conformance suite
```

The reference implementation expects a local Ollama instance. The fastest path is `docker compose -f reference-implementation/docker-compose.yml up -d ollama` and `docker exec ski-ollama ollama pull qwen2.5:7b-instruct`.

## Code style

- **Python** — PEP 8 enforced by `ruff` (see `pyproject.toml`). Type hints required on new code; `mypy --strict` is the CI target. Public functions get docstrings.
- **SQL** — uppercase keywords; one statement per line; explicit column lists.
- **Shell** — `#!/bin/bash` + `set -euo pipefail`. Pass `shellcheck` cleanly.
- **YAML / TOML** — two-space indent; lowercase keys.

## Commit messages

Format: `[type] short subject (≤72 chars)` followed by a blank line and a body that explains what and why.

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `chore`, `security`.

```
[feat] add NULL_STALE handling in Symbolic Evaluator

Wires the freshness predicate to the telemetry buffer so rules with
`requires_recent_within_seconds` return NULL_STALE when the buffer
has no fresh sample. Closes #142.
```

## Pull request process

1. Fork and create a feature branch off `main`.
2. Run `ruff check`, `mypy`, and `pytest` locally before opening the PR.
3. Open the PR using the [template](./.github/PULL_REQUEST_TEMPLATE.md).
4. CI must be green and the change must be reviewed by a CODEOWNER.
5. Squash-merge is the default. Merge commits are reserved for spec-version bumps.

PRs that change runtime behaviour are required to add or update a conformance test. PRs that change the audit ledger schema or the canonical serialization require sign-off from a CODEOWNER and a release-note entry.

## Specification changes

Edits to `docs/` are licensed under CC BY 4.0; edits to code are licensed under Apache 2.0. A single PR may touch both. For substantive spec changes:

1. Open an issue first to discuss intent.
2. Open the PR with a `[spec]` prefix.
3. Provide a one-paragraph migration note (what changes for adopters between v2.x and v2.y).
4. Update `CHANGELOG.md` under the next planned version.

## Security

Do **not** open public issues for security vulnerabilities. Follow the disclosure process in [SECURITY.md](./SECURITY.md). Security PRs go through a private branch.

## Licensing of contributions

By submitting a contribution you agree to license it under:
- **Apache License 2.0** for software (Python, Dockerfiles, shell scripts, SQL, YAML, the conformance suite).
- **Creative Commons Attribution 4.0 International** for specification documents (`docs/`, framework PDF, diagrams).

This is the same dual license already applied to the existing content of the repository. See [LICENSE](./LICENSE), [LICENSE-docs.md](./LICENSE-docs.md), and [NOTICE](./NOTICE).

## Code of conduct

This project follows the Contributor Covenant 2.1. See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md). Violations may be reported to <conduct@kpifinity.com>.

## Getting help

- Specification questions → [skiframework.org](https://skiframework.org) and [GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions).
- Implementation questions → [GitHub Issues](https://github.com/kpifinity/ski-framework/issues).
- Commercial support → [KpiFinity](https://kpifinity.com).

Thank you for helping make SKI better.
