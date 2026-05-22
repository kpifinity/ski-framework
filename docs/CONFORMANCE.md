# SKI conformance methodology

> **License:** CC BY 4.0. See [LICENSE-docs.md](../LICENSE-docs.md).
> **Status:** Level 1 tests runnable today; Level 2 in progress; Level 3
> planned.

This document defines what it means for an implementation to claim SKI
Framework conformance. It complements the runnable test suite under
[`conformance/`](../conformance/).

## Why conformance matters

The SKI Framework's business model depends on the conformance levels
being *operationally meaningful*. Without an executable, third-party
verifiable test suite, "Level 1 Foundational" is marketing copy. With
one, it is a contract: a regulator, a procurement officer, or an
auditor can run `pytest conformance -q` against a deployment and get a
binary answer.

The W3C uses conformance test suites for every spec. Khronos uses one
for OpenGL. The Apache Foundation uses one for Cassandra. SKI uses one
for the same reason: it is the only way to keep the spec honest.

## Three levels

### Level 1 — Foundational

The implementation correctly performs deterministic runtime evaluation
against a signed Knowledge Graph and writes an integrity-checkable
audit ledger.

| Requirement | Spec | Test |
|---|---|---|
| Five-verdict taxonomy with `NULL_UNMAPPED` / `NULL_STALE` split | B3, v2.1 | `test_verdict_taxonomy.py` |
| Determinism: identical input → identical verdict across N runs | Axiom 2, B3.4 | `test_determinism.py` |
| Refuses to load an unsigned KG | B2 boundary | `test_signature_required.py` |
| Tag Registry resolves subjects; runtime tag inference is impossible | B4.3 | `test_tag_registry.py` |
| Audit ledger is append-only at the DB layer | B5.2 | `test_append_only.py` |
| Audit ledger hash chain verifies (linkage + entry recomputation) | B5.2 | `test_ledger_integrity.py` |
| No `confidence_level` column in the ledger schema | B3.1 | `test_no_confidence.py` |
| Determinism canary mechanism is active | B3.4 | `test_canary_active.py` |

### Level 2 — Managed

Adds multi-KG and stateful-evaluation coverage.

| Requirement | Spec | Test (planned) |
|---|---|---|
| Coverage Register populated when subjects are unmapped | B4.3 | `test_coverage_register.py` |
| `NULL_STALE` produced when freshness predicate fails | B4.4 | `test_stale_freshness.py` |
| KG hot-reload preserves ledger continuity | B5.2 | `test_hot_reload.py` |
| Conflict precedence resolves deterministically | B2.2 | `test_conflict_precedence.py` |
| Operator-supplied secrets required at startup | B6 | `test_no_default_secrets.py` |

### Level 3 — Assured

Adds tamper-resistance and adversarial input coverage.

| Requirement | Spec | Test (planned) |
|---|---|---|
| Sovereignty: no outbound network calls during inference (default backend) | Pillar S | `test_sovereign_boundary.py` |
| Reject modified ledger row even when chain forward is recomputed | B5.2 | `test_tamper_resistance.py` |
| Refuse `SKI_MODEL_WORKERS != 1` | concurrency | `test_single_worker.py` |
| Canary FAIL fires Prometheus alert | B3.4 | `test_canary_alert.py` |
| Air-gapped operation possible end-to-end | Pillar S | `test_air_gapped.py` |

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest conformance/ -m level1
```

Against a live deployment:

```bash
pytest conformance/ -m level1 \
  --ski-endpoint https://localhost:8000 \
  --api-key "$SKI_API_KEY" \
  --ledger-dsn "$LEDGER_DSN"
```

Each test prints the spec section it validates on failure. Run results
can be exported as a JUnit XML and rendered into a conformance badge in
your project's README.

## Certification flow

For self-asserted conformance:

1. Run `pytest conformance -q -m level1` (or level2 / level3).
2. Publish the JUnit XML alongside your release.
3. Include a `Conformance: SKI Level X (self-asserted)` line in the
   release notes.

For attested conformance (Level 3 Assured), engage KpiFinity for a
third-party audit. KpiFinity's audit process replays the conformance
suite against your deployment under controlled conditions and issues a
signed certificate referencing the spec version, the test suite
revision, and the deployment artefacts. The certificate is the asset
regulators recognise.

## Versioning

The conformance suite is versioned with the spec. The mapping between
spec version and test suite revision is documented in
[`conformance/CHANGELOG.md`](../conformance/CHANGELOG.md). An
implementation claiming "SKI v2.1 Level 1 conformant" must pass the
test suite at the revision matching the spec.

## Contributing tests

New tests are some of the highest-leverage contributions you can make.
See [`conformance/README.md`](../conformance/README.md) for the
conventions (one spec citation per test; black-box only; no dependency
on the reference implementation's internals).
