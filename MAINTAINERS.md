# Maintainers

This file lists the people and teams responsible for the SKI Framework
repository, together with their areas of ownership and how to reach them.

The authoritative machine-readable mapping of paths to reviewers lives in
[.github/CODEOWNERS](./.github/CODEOWNERS); this file explains the human
side: who the teams are, what they decide, and how new maintainers are
added.

## Governance model

SKI follows a **lazy-consensus** model with a small set of named
maintainer teams. Day-to-day code and documentation changes ship by
approval from one CODEOWNERS reviewer. Decisions that change the
specification, the on-disk schemas, the wire format, the license, or the
governance model itself follow the RFC process in
[docs/governance.md](./docs/governance.md).

KpiFinity Inc. is the steward organization. Maintainership is a role,
not a title — maintainers act on behalf of the project's users, not on
behalf of KpiFinity's commercial interests. Where the two conflict, the
project's open governance prevails for everything in this repository.

## Teams

The GitHub team handles below correspond one-to-one with the groups
referenced from `.github/CODEOWNERS`.

### `@kpifinity/owners`

Final authority on licensing, the project's open/proprietary boundary,
and changes to this file or to the governance documents. Owners sign off
on every release tag and on any change to `LICENSE`, `LICENSE.md`,
`LICENSE-docs.md`, or `NOTICE`.

Current owners:

- KpiFinity Inc. (organizational owner)

### `@kpifinity/maintainers`

General repository maintainers. Catch-all reviewers for any path not
otherwise claimed. Triages issues, merges contributor PRs, and cuts
releases following [RELEASING.md](./RELEASING.md).

Responsibilities:

- Triage incoming issues within 5 business days.
- Review and merge PRs that have at least one CODEOWNERS approval and a
  green CI run.
- Cut tagged releases.
- Maintain the project board and milestones.

### `@kpifinity/spec-stewards`

Owns the specification under `/docs/` and the conformance test suite
under `/conformance/`. Spec stewards approve all RFCs that touch
normative behavior. They are the authority on what counts as a Level 1,
Level 2, or Level 3 conforming implementation.

Responsibilities:

- Review and shepherd RFCs (see [docs/RFCs/0000-template.md](./docs/RFCs/0000-template.md)).
- Approve specification text changes for normative content (`MUST`,
  `SHOULD`, `MAY`).
- Sign off on additions to the conformance suite.
- Maintain the [glossary](./docs/glossary.md) so terminology stays
  consistent across the spec, the reference implementation, and the
  tooling.

### `@kpifinity/runtime-maintainers`

Owns the reference implementation under `/reference-implementation/` and
the four CLI tools under `/tools/`. Pairs with `@kpifinity/security` on
anything touching the audit ledger or the SKI Model wrapper.

Responsibilities:

- Review changes to the Symbolic Evaluator, Tag Registry, telemetry
  buffer, SKI Model wrapper, and audit ledger.
- Keep the conformance suite green against the reference implementation.
- Maintain the `kg-extractor`, `kg-validator`, `ski-model-deploy`, and
  `audit-ledger` CLIs.

### `@kpifinity/security`

Owns the security workflow, the threat model, and the vulnerability
disclosure process described in [SECURITY.md](./SECURITY.md). Required
reviewer for changes to `/reference-implementation/src/ledger/`,
`/tools/audit-ledger/`, and `/.github/`.

Responsibilities:

- Handle vulnerability reports sent to **security@kpifinity.com** per
  the disclosure policy in `SECURITY.md`.
- Review changes to the audit ledger, signing flows, and CI security
  workflows.
- Maintain the [threat model](./docs/threat-model.md) and the
  release-artifact verification recipes.
- Run the post-release verification of cosign signatures and SLSA
  provenance for each tagged release.

## How to contact the maintainers

| Purpose                                        | Where                                                                 |
| ---------------------------------------------- | --------------------------------------------------------------------- |
| Bug reports, feature requests, spec proposals  | [GitHub Issues](https://github.com/kpifinity/ski-framework/issues)    |
| Security vulnerability disclosure              | **security@kpifinity.com** (see [SECURITY.md](./SECURITY.md))         |
| Code of Conduct concerns                       | **conduct@kpifinity.com** (see [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)) |
| Commercial / partnership inquiries             | **hello@kpifinity.com**                                               |
| General discussion                             | [GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions) |

Please do **not** open public GitHub issues for security vulnerabilities.

## Becoming a maintainer

Maintainership is granted by invitation from `@kpifinity/owners` after
sustained, high-quality contribution. There is no fixed contribution
threshold; in practice we look for:

- A track record of merged PRs in the area you would maintain (typically
  10+ over 3+ months, but quality is weighted over quantity).
- Reviews that catch real problems, not just stylistic ones.
- Demonstrated judgment about scope, backwards compatibility, and the
  project's intended audience (regulated industries; audit-defensibility
  over ergonomics where the two conflict).
- Willingness to be on the hook for the response-time expectations
  listed under each team above.

Existing maintainers may nominate a candidate by opening an issue with
the `governance: maintainer-nomination` label. The nomination is
discussed in the open for at least seven days; an owner makes the final
call. Stepping down is similarly informal — open an issue (or email
hello@kpifinity.com) and your access is rotated within one business day.

## Emeritus

When a maintainer steps down, they are listed here in recognition of
their contributions. (No emeritus maintainers yet — the project is
young.)

## Updating this file

Adding or removing a maintainer requires:

1. An owner-approved PR updating this file and `.github/CODEOWNERS`.
2. A corresponding GitHub team membership change in the `kpifinity`
   organization.
3. A note in the next [CHANGELOG.md](./CHANGELOG.md) entry under
   "Governance".

The PR-template footer for governance changes is enforced by CODEOWNERS;
see [.github/CODEOWNERS](./.github/CODEOWNERS) for the matching rule.
