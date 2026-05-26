# Governance

## Mission

The SKI Framework exists to give regulated industries an **open,
deterministic, auditable** option for AI compliance monitoring. Its
specification is permissively licensed and its reference implementation
is Apache 2.0; both are intended to outlive any single organisation.

## Roles

### Maintainers

Maintainers have commit and release rights on the
[`kpifinity/ski-framework`](https://github.com/kpifinity/ski-framework)
repository. Their responsibility is to:

- review and merge contributions,
- cut releases following the process below,
- enforce the licensing and conformance boundaries,
- triage security disclosures.

Current maintainers are listed in [CODEOWNERS](https://github.com/kpifinity/ski-framework/blob/main/.github/CODEOWNERS).
KpiFinity Inc. (the project's primary sponsor) appoints the initial
maintainer set; future maintainers are nominated by existing maintainers
and added after a 14-day public comment window.

### Contributors

Anyone who opens an issue, comments on a discussion, or submits a pull
request. No prior agreement is required. By contributing, you agree to
the Developer Certificate of Origin (`Signed-off-by:` trailer on each
commit) — see [CONTRIBUTING.md](contributing.md).

### Spec Editor

A single maintainer is designated **Spec Editor**. Their role is to
shepherd specification changes (v2.1 → v2.2 → ...) through the RFC
process. The Spec Editor does not have final authority — see "Decision
making" below.

## Decision making

Most decisions are made by **lazy consensus** on pull requests and
discussions: if no maintainer objects within 7 days, the change lands.

The following decisions require **explicit consensus** from at least
three maintainers (or all maintainers, whichever is smaller):

1. Changes to the published specification (versioned in `docs/`).
2. Adding or removing a maintainer.
3. Changes to the verdict taxonomy, the predicate grammar, the audit
   ledger schema, or the conformance level definitions.
4. License changes.
5. Releasing a major version (e.g. v1.0).

Routine bug fixes, documentation improvements, dependency bumps,
non-breaking API additions, and reference-implementation refactors do
**not** require explicit consensus — lazy consensus is sufficient.

## RFC process

Architectural changes use the RFC process. The template lives at
[`docs/RFCs/0000-template.md`](RFCs/0000-template.md). To propose one:

1. Copy the template to `docs/RFCs/NNNN-short-title.md` with the next
   sequential number.
2. Open a draft pull request titled `[RFC] <Title>`.
3. Solicit feedback for at least 14 days.
4. The Spec Editor closes the RFC either as **accepted** (merged) or
   **rejected** (closed with rationale).

The single existing RFC is
[0001 — Stateful evaluation](RFCs/0001-stateful-evaluation.md).

## Release cadence

- **Patch (`0.2.x`)** — bug fixes, no API or spec changes. Released as
  soon as a fix is ready; tagged from `main`.
- **Minor (`0.x.0`)** — new features, no breaking changes. Roughly
  every 4–8 weeks. Cuts a release-candidate (`-rc1`) first; promoted to
  GA after at least 14 days without a regression.
- **Major (`x.0.0`)** — breaking changes, spec major-version bumps.
  Driven by explicit-consensus decision.

See [CHANGELOG.md](CHANGELOG.md) for the actual release history.

## Conformance authority

The SKI conformance test suite at `conformance/` is the
**executable specification** — if there's a disagreement between
`docs/CONFORMANCE.md` and the tests, the tests win, and the docs are
corrected.

Conformance claims (Level 1 / Level 2 / Level 3) may be self-issued or
issued by KpiFinity. KpiFinity-issued conformance certificates are a
commercial offering and do not constrain the open-source project's
governance.

## Security

Security disclosure follows [SECURITY.md](security.md): private
disclosure to the maintainers, 90-day default embargo, coordinated
release with the reporter.

## Communication

- **Bug reports / feature requests**: [GitHub Issues](https://github.com/kpifinity/ski-framework/issues).
- **Architectural discussions**: [GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions).
- **Security**: see [SECURITY.md](security.md).
- **General questions**: <hello@kpifinity.com>.

## Amendments

This governance document can be amended by explicit consensus of the
maintainers, following the same process as a spec change.
