# Releasing the SKI Framework

This runbook covers the end-to-end process for cutting a tagged release
of the SKI Framework reference implementation and CLI tools. It assumes
the reader is a member of `@kpifinity/maintainers` with write access to
the repository and the `kpifinity` GHCR namespace.

The specification version (currently **v3.0**) is decoupled from the
implementation version and is bumped through the RFC process in
[docs/governance.md](./docs/governance.md), not as part of a release.

## Versioning

The reference implementation, the four CLI tools, and `ski-sdk` share
a single semantic version. Releases follow [SemVer 2.0.0](https://semver.org/):

- `MAJOR` for breaking schema, wire-format, or public-API changes.
- `MINOR` for backwards-compatible feature additions (new predicate
  operators, new conformance levels, new CLI subcommands).
- `PATCH` for bug fixes that change no public surface area.

Pre-1.0 we do not guarantee strict SemVer for the public API — see the
"early alpha" caveat in `README.md` and `CONTRIBUTING.md`. The intent
is to behave as if SemVer applied; the carve-out exists so we can fix
genuine design mistakes during the v0.x line.

## Release cadence

- **Patch releases:** ad-hoc, whenever a correctness fix is ready.
  Target turnaround from "fix merged" to "tag pushed" is 3 business
  days.
- **Minor releases:** approximately every 6–8 weeks, aligned with the
  themes called out in the "Planned for vX.Y.0" sections of
  [CHANGELOG.md](./CHANGELOG.md).
- **Major releases:** only on a deliberate vote of `@kpifinity/owners`
  plus `@kpifinity/spec-stewards`.

## Pre-flight checklist

Run these checks on `main` before opening the release PR.

1. **Tests are green on `main`.** Both the Provenance and Durability
   conformance markers, plus the full unit and integration suites.
   ```powershell
   pytest -q
   pytest -q conformance/ -m "provenance or durability"
   ```
2. **Lint and types are clean.**
   ```powershell
   pre-commit run --all-files
   mypy reference-implementation/src/symbolic_evaluator `
        reference-implementation/src/tag_registry `
        reference-implementation/src/telemetry_buffer `
        tools/audit-ledger/src/audit_ledger/canonical
   ```
3. **Docs build cleanly.**
   ```powershell
   mkdocs build --strict
   ```
4. **No outstanding `Planned for vX.Y.0` items** that this release
   was supposed to deliver. If something slipped, decide explicitly
   whether to (a) hold the release, (b) move the item to the next
   planned section, or (c) ship without it and note the omission in the
   release entry.
5. **Security scan is clean.** Check the latest run of
   `.github/workflows/security.yml` on `main`. Any new high or critical
   finding blocks the release.

## Cutting the release

The version we are cutting in this example is `0.2.2`. Substitute as
needed.

### 1. Open a release PR

Create a branch from `main` named `release/0.2.2`. The PR makes three
changes and nothing else:

1. **Bump versions.** Move every version site to the new version: the
   `version` field **and** the Python classifiers in all four
   `tools/*/pyproject.toml` (including `tools/ski-sdk`); each tool's `src/<pkg>/__init__.py`
   `__version__`; `reference-implementation/src/ski_model/__init__.py`'s
   `__version__`; and `reference-implementation/src/ski_model/server.py`'s
   `_VERSION`. Also update `CITATION.cff`'s `version` and `date-released`
   fields.
2. **Promote the Unreleased section in CHANGELOG.md.** Rename
   `## [Unreleased]` to `## [0.2.2] - YYYY-MM-DD` and insert a fresh,
   empty `## [Unreleased]` block above it. Keep the
   `### Planned for vX.Y.0` subsection in `Unreleased` carrying the
   next version's plan.
3. **Update SECURITY.md's supported-versions table** if this release
   changes the supported branch.

Get one CODEOWNERS approval and merge. Do not squash — the release-PR
commit is the anchor for the tag.

### 2. Tag and push

Tag the release-PR merge commit and push. The tag triggers the release
workflow, which builds wheels, sdists, container images, SBOMs, cosign
signatures, and SLSA provenance, then attaches everything to the
GitHub release.

```powershell
git fetch origin
git checkout main
git pull --ff-only
git tag -s -a v0.2.2 -m "SKI Framework v0.2.2"
git push origin v0.2.2
```

Tags are signed (`-s`). If your local git is not configured to sign,
fix that before cutting the release rather than tagging unsigned —
unsigned tags will fail the release workflow.

### 3. Watch the release workflow

The `.github/workflows/release.yml` job:

1. Builds wheels and sdists for all four CLIs and the reference
   implementation; uploads them as release artifacts.
2. Builds and pushes the `ski-model` and `ski-sidecar` container
   images to `ghcr.io/kpifinity/`, signed with cosign keyless and with
   SLSA Level 3 provenance attached.
3. Generates SBOMs (`syft`) for every artifact and attaches them.
4. Signs each downloadable artifact with `cosign sign-blob` keyless,
   uploads the `.sig` and `.cert` files to the release.
5. Generates SLSA provenance for the downloadable artifacts via
   `slsa-framework/slsa-github-generator` and attaches it.
6. Publishes the GitHub release with the matching CHANGELOG section
   as the release body.

If any of these steps fails, do not delete the tag — fix forward in a
patch release. Deleted tags break SLSA provenance verification for
anyone who already cached the metadata.

### 4. Post-release verification

Within 24 hours of the tag, a member of `@kpifinity/security` runs the
verification recipes from [SECURITY.md](./SECURITY.md#verifying-release-artifacts)
against the published artifacts:

```powershell
# Wheel signature
cosign verify-blob `
  --certificate ski_model-0.2.2-py3-none-any.whl.pem `
  --signature ski_model-0.2.2-py3-none-any.whl.sig `
  --certificate-identity-regexp "https://github.com/kpifinity/ski-framework/.*" `
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" `
  ski_model-0.2.2-py3-none-any.whl

# Container image signature
cosign verify `
  --certificate-identity-regexp "https://github.com/kpifinity/ski-framework/.*" `
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" `
  ghcr.io/kpifinity/ski-model:0.2.2

# SLSA provenance
slsa-verifier verify-artifact `
  --provenance-path ski_model-0.2.2-py3-none-any.whl.intoto.jsonl `
  --source-uri github.com/kpifinity/ski-framework `
  --source-tag v0.2.2 `
  ski_model-0.2.2-py3-none-any.whl
```

The verifier files a follow-up issue if anything fails. Record the
result (pass / fail / mitigation) in a `release: vX.Y.Z verification`
issue and link it from the release page.

### 5. Announce

Once verification passes:

1. Post the release to GitHub Discussions in the **Releases** category.
2. Update [skiframework.org](https://skiframework.org). The marketing
   site is maintained separately (Replit) and does **not** update
   automatically — update every version string (hero badge, meta tags,
   changelog section, citation block) to the new version. The docs site
   (kpifinity.github.io/ski-framework) updates via the docs workflow on
   the next push to `main`.
3. Tag downstream integrators listed in `docs/integrations.md` (when
   that file exists — empty placeholder is fine until then).

## Patch releases

Patch releases follow the same flow with two simplifications:

- The release PR usually changes only version numbers and CHANGELOG;
  no spec or schema changes.
- Pre-flight item 4 ("Planned for" alignment) does not apply.

If a patch release fixes a security issue, the release notes link to
the corresponding GHSA advisory and SECURITY.md gets a row added to its
fixed-vulnerabilities table.

## Aborting a release

Between tag push and the workflow's `publish` step, the release can be
aborted by cancelling the workflow and force-deleting the tag from both
origin and your local clone:

```powershell
git push --delete origin v0.2.2
git tag -d v0.2.2
```

After the workflow has published artifacts and attestations, do **not**
delete — supply-chain consumers may have already pinned the tag. Fix
forward with `v0.2.3`.

## When the runbook itself changes

Material changes to this file (anything beyond typo fixes) require an
`@kpifinity/owners` approval, because release process is part of the
project's governance surface.
