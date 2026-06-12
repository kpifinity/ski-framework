# SKI conformance methodology

> **License:** CC BY 4.0. See [LICENSE-docs.md](../LICENSE-docs.md).
> **Status:** Provenance + Durability runnable today. Sovereignty: all six
> checks runnable — the tamper-resistance rig needs a throwaway Postgres
> (`SKI_L3_LEDGER_DSN`), and the air-gapped boot rig needs Docker plus the
> `SKI_L3_AIRGAP=1` opt-in. Both skip cleanly when their infrastructure
> is absent.

This document defines what it means for an implementation to claim SKI
Framework v3.0 conformance. It complements the runnable test suite
under [`conformance/`](../conformance/).

## Why conformance matters

The SKI Framework's business model depends on the conformance levels
being *operationally meaningful*. Without an executable, third-party
verifiable test suite, "Provenance conformant" is marketing copy. With
one, it is a contract: a regulator, a procurement officer, or an
auditor can run `pytest conformance -q -m provenance` against a
deployment and get a binary answer.

The W3C uses conformance test suites for every spec. Khronos uses one
for OpenGL. The Apache Foundation uses one for Cassandra. SKI uses one
for the same reason: it is the only way to keep the spec honest.

## Three levels of verifiable provenance

v3 reorganises the conformance levels around what the audit trail
actually *proves*. The three levels are cumulative — Durability
requires Provenance, Sovereignty requires both.

### Level 1 — Provenance

Every verdict carries a complete, verifier-checked provenance record.
The envelope shape matches the spec contract, the Symbolic Verifier
ran and emitted one of the four canonical statuses, the LLM's
formalizable assertions are tied to KG citations, and the agreement
monitor is mounted.

| Requirement | Spec | Test |
|---|---|---|
| `V3VerdictEnvelope` declares all seven required fields | §4.2 | `provenance/test_v3_envelope_shape.py` |
| `ModelProvenance` declares all six required hash fields | §4.6 | `provenance/test_v3_envelope_shape.py` |
| `VerifierStatus` enum has all four spec values | §4.5 | `provenance/test_v3_envelope_shape.py` |
| `KGCitationRole` lists the five spec roles | §4.3 | `provenance/test_v3_envelope_shape.py` |
| `SymbolicVerifier` module exists and handles the minimum predicates | §5.3 | `provenance/test_v3_verifier_contract.py` |
| Risk-tier policy module exists with the three tiers | §5.4 | `provenance/test_v3_verifier_contract.py` |
| Five-verdict taxonomy in schema + V3Verdict enum | §4.1 | `provenance/test_verdict_taxonomy.py` |
| No `confidence_level` column anywhere | Axiom 2 | `provenance/test_no_confidence.py` |
| Agreement monitor is mounted and exposes the snapshot keys | §7.2 | `provenance/test_agreement_monitor.py` |
| `NULL_STALE` is produced when the freshness gate fails | §4.1 | `provenance/test_null_stale_routing.py` |
| Window predicates (count / sum / avg) produce correct verdicts | §5.3 | `provenance/test_window_predicates.py` |

### Level 2 — Durability

Provenance is signed, replayable, and audit-chained. The KG carries an
ed25519 signature that the loader requires; the risk-tier governor
reads tiers from the KG (strict, no caller influence); the audit
ledger is append-only at the DB layer; the hash chain verifies via
entry recomputation, not just linkage; and the replay primitive can
reproduce historical verdicts.

| Requirement | Spec | Test |
|---|---|---|
| KG loader refuses unsigned KGs (no escape hatch) | §3 | `durability/test_signed_kg_required.py` |
| Tag Registry package is a pure dict lookup (no fuzzy/LLM) | §5.4 | `durability/test_risk_tier_governor.py` |
| `RiskTierGovernor` is the authoritative tier source | §5.4 | `durability/test_risk_tier_governor.py` |
| `MeasurementRecord` has NO caller-settable `risk_tier` | §5.4 | `durability/test_risk_tier_governor.py` |
| Demo KGs route every subject via `applies_to` edges; telemetry has no `rule_id` | B4.3 (v3 form) | `durability/test_risk_tier_governor.py` |
| Append-only DB triggers (UPDATE / DELETE / TRUNCATE) | §6 | `durability/test_append_only.py` |
| Hash-chain integrity recomputes entry hash from canonical payload | §6 | `durability/test_ledger_integrity.py` |
| Replay primitive ships with strict mode + CLI flags | §6 | `durability/test_replay_determinism.py` |
| Three identical evaluations against a live runtime match | Axiom 2 | `durability/test_replay_three_evaluations.py` |
| `coverage_register` view scopes to NULL verdicts only | §6 | `durability/test_coverage_register.py` |

### Level 3 — Sovereignty

The runtime is operable air-gapped, tamper-evident, and end-to-end
signed. All six checks below are runnable. Four are black-box structural
checks (with matching functional proofs in the runtime test suite); the
remaining two carry their own infrastructure rigs: tamper-resistance
seeds and attacks a throwaway Postgres (`SKI_L3_LEDGER_DSN`), and
air-gapped boot runs the full runtime + ledger in a loopback-only
`--network=none` namespace (Docker + `SKI_L3_AIRGAP=1`).

| Requirement | Spec | Test | Status |
|---|---|---|---|
| No outbound HTTP during CLEAR-path evaluation (local LLM) | Pillar S | `sovereignty/test_no_outbound_calls.py` (+ runtime `v3/tests/test_no_egress.py`) | ✅ runnable |
| Runtime boots, serves, and persists with `--network=none` | Pillar S | `sovereignty/test_air_gapped.py` | ✅ runnable (Docker + `SKI_L3_AIRGAP=1`) |
| Modified ledger row fails `verify_integrity` even after chain forward | §6 | `sovereignty/test_tamper_resistance.py` | ✅ runnable (throwaway Postgres via `SKI_L3_LEDGER_DSN`) |
| Runtime refuses to start with `SKI_MODEL_WORKERS != 1` | Concurrency | `sovereignty/test_single_worker.py` | ✅ runnable |
| Recorded transcript carries the snapshot's `scope` block | §3.6 + §6 | `sovereignty/test_jurisdiction_scope_captured.py` | ✅ runnable |
| Recorded `LLMTranscript` ed25519 signature verifies | §4.7 | `sovereignty/test_signed_llm_transcript.py` (+ runtime `test_signing.py`, `test_transcript.py`) | ✅ runnable |

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest conformance/ -m provenance
pytest conformance/ -m durability
pytest conformance/ -m sovereignty   # all 6 checks; the two rig-backed ones
                                     # skip without their infrastructure:
                                     #   SKI_L3_LEDGER_DSN=...  tamper rig (throwaway Postgres)
                                     #   SKI_L3_AIRGAP=1        air-gap rig (Docker)
```

Against a live deployment:

```bash
pytest conformance/ -m provenance \
  --ski-endpoint https://localhost:8000 \
  --api-key "$SKI_API_KEY" \
  --ledger-dsn "$LEDGER_DSN"
```

Each test prints the spec section it validates on failure. Run results
can be exported as JUnit XML and rendered into a conformance badge in
your project's README.

## Attestation flow

For self-asserted conformance:

1. Run `pytest conformance -q -m provenance` (and `-m durability`).
2. Publish the JUnit XML alongside your release.
3. Include a `Conformance: SKI Provenance (self-asserted)` or
   `Conformance: SKI Durability (self-asserted)` line in the release
   notes.

For attested conformance (Sovereignty level), engage KpiFinity for a
third-party audit. The audit process replays the conformance suite
against your deployment under controlled conditions and issues a
signed certificate referencing the spec version, the suite revision,
and the deployment artefacts. The certificate is the asset regulators
recognise.

## Versioning

The conformance suite is versioned with the spec. The mapping between
spec version and test suite revision is documented in
[`conformance/CHANGELOG.md`](../conformance/CHANGELOG.md). An
implementation claiming "SKI v3.0 Provenance conformant" must pass the
test suite at the revision matching the spec.

## Contributing tests

New tests are among the highest-leverage contributions you can make,
especially hardening the Sovereignty rigs (tamper-resistance, air-gapped
boot) against new attack shapes. See [`conformance/README.md`](../conformance/README.md) for
the conventions (one spec citation per test; black-box only; no
dependency on the reference implementation's internals).
