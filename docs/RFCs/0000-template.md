# RFC 0000 — <Title>

| | |
|---|---|
| **Status** | Draft / Accepted / Rejected / Superseded |
| **Author(s)** | <name> |
| **Created** | YYYY-MM-DD |
| **Last updated** | YYYY-MM-DD |
| **Supersedes** | <RFC number, if any> |
| **Superseded by** | <RFC number, if any> |

## Summary

One paragraph. What is being proposed, in plain language.

## Motivation

Why does this RFC exist? What problem are we solving? Who is hurt today
by the absence of this change?

Reference the specific section of the specification (e.g. B3.4) and / or
the relevant code paths.

## Proposal

The actual proposal, in enough detail that an implementer could build
it without further input. Include:

- Data model / schema changes (with migrations if applicable)
- API surface changes (with deprecation strategy if breaking)
- Diagrams (Mermaid preferred)
- Pseudocode for non-obvious algorithms

## Alternatives considered

What else was on the table? Why was each alternative rejected?

A blank "Alternatives considered" section is a sign the proposal hasn't
been pressure-tested. Include at least two genuine alternatives, even
if both are weaker than the chosen path.

## Backwards compatibility

- Does this change the wire format, schema, or API in a way that
  existing deployments must care about?
- What's the upgrade path?
- Are there feature flags or runtime checks involved?

## Security implications

Map this proposal against the [threat model](../threat-model.md). Does
it strengthen, weaken, or leave unchanged each in-scope threat? If it
introduces a new threat, document it.

## Conformance implications

Does this proposal change what Level 1 / 2 / 3 conformance requires?
If yes, list the test additions or modifications.

## Rollout plan

1. Land RFC as draft, solicit feedback (14-day minimum).
2. Implement behind a feature flag if disruptive.
3. Update conformance suite.
4. Update specification document.
5. Cut a release.

## Open questions

Bullet list of things the author is uncertain about. Will be resolved
before the RFC is accepted.

## References

- Specification section(s) touched
- Prior RFCs
- External standards
