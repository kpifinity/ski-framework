<!--
Thanks for contributing to SKI! Please complete this template so reviewers
have what they need. PRs missing required information may be closed.
-->

## Summary

<!-- One paragraph: what changes and why. -->

## Type of change

- [ ] `[feat]` New feature
- [ ] `[fix]` Bug fix
- [ ] `[docs]` Documentation only
- [ ] `[spec]` Specification change (CC BY 4.0 content)
- [ ] `[refactor]` Refactor with no behaviour change
- [ ] `[test]` Tests only
- [ ] `[security]` Security fix
- [ ] `[ci]` CI / tooling
- [ ] `[chore]` Dependency bumps, formatting, etc.

## Specification linkage

<!-- Which sections of the SKI Framework v3.0 specification this PR touches.
Use spec section IDs (e.g. B3.4, B4.3). If none, write "N/A". -->

## Conformance impact

<!-- Does this PR change observable behaviour the conformance suite cares
about? If yes, link to the new/updated test under conformance/. -->

- [ ] No conformance-suite impact
- [ ] New conformance test added: `conformance/<path>`
- [ ] Existing conformance test updated: `conformance/<path>`

## Audit ledger impact

<!-- Touches `ledger_entries` schema, canonical serialization, or hash
algorithm? If yes, this requires CODEOWNER sign-off and a CHANGELOG
entry under the next planned version. -->

- [ ] No audit-ledger impact
- [ ] Schema change (CODEOWNER review required)
- [ ] Canonical serialization change (CODEOWNER review required)

## Checklist

- [ ] `ruff check` and `mypy` pass locally
- [ ] `pytest` passes locally
- [ ] `pytest conformance/` passes locally (or N/A)
- [ ] New behaviour has tests
- [ ] CHANGELOG.md updated
- [ ] Commits are signed (`git commit -S`)
- [ ] No `ANTHROPIC_API_KEY` (or equivalent cloud-only credential) is required at runtime

## Linked issues

<!-- e.g. Closes #123 -->
