# SKI Framework conformance test suite

> **License:** Apache 2.0. See [../LICENSE](../LICENSE).

This directory contains the **runnable conformance test suite** for the
SKI Framework v3.0. Each test cites the specification section it
validates. The suite is organised around **verifiable provenance** —
the three levels measure how *complete*, how *durable*, and how
*sovereign* the verdict-time audit story is. See
[`docs/conformance.md`](../docs/conformance.md) for the methodology.

## Layout

```
conformance/
├── README.md             ← you are here
├── CHANGELOG.md          spec-version ↔ suite-revision pairing
├── conftest.py           pytest fixtures: ski-endpoint, api-key, etc.
├── pytest.ini            marker registration (provenance, durability, sovereignty)
├── provenance/           Level 1 — verdict envelope carries verifier-checked provenance
│   ├── test_v3_envelope_shape.py
│   ├── test_v3_verifier_contract.py
│   ├── test_verdict_taxonomy.py
│   ├── test_no_confidence.py
│   ├── test_agreement_monitor.py
│   ├── test_null_stale_routing.py
│   └── test_window_predicates.py
├── durability/           Level 2 — provenance is signed, replayable, audit-chained
│   ├── test_signed_kg_required.py
│   ├── test_risk_tier_governor.py
│   ├── test_ledger_integrity.py
│   ├── test_append_only.py
│   ├── test_replay_determinism.py
│   ├── test_replay_three_evaluations.py
│   └── test_coverage_register.py
└── sovereignty/          Level 3 — runnable; two checks carry infra rigs
    ├── test_no_outbound_calls.py
    ├── test_air_gapped.py
    ├── test_tamper_resistance.py
    ├── test_single_worker.py
    ├── test_jurisdiction_scope_captured.py
    └── test_signed_llm_transcript.py
```

## Quick start

```bash
pip install -r ../requirements-dev.txt

# Static tests (no live deployment needed):
pytest conformance/ -q -m provenance

# Against a live deployment:
pytest conformance/ -q -m provenance \
  --ski-endpoint https://localhost:8000 \
  --api-key "$SKI_API_KEY" \
  --ledger-dsn "$LEDGER_DSN"

# Durability requires the ledger DSN for the live verify-integrity test:
pytest conformance/ -q -m durability --ledger-dsn "$LEDGER_DSN"

# Sovereignty: two checks bring their own infrastructure rigs and skip
# without it. The tamper rig wants a THROWAWAY Postgres; the air-gap rig
# wants Docker and is opt-in because it builds the runtime image:
SKI_L3_LEDGER_DSN="postgresql+psycopg://postgres:x@localhost:5433/postgres" \
SKI_L3_AIRGAP=1 \
  pytest conformance/sovereignty -q
```

`--ski-endpoint` / `--api-key` / `--ledger-dsn` can also be supplied via
`SKI_ENDPOINT`, `SKI_API_KEY`, `LEDGER_DSN`. Tests requiring a live
deployment will be skipped (not failed) if these aren't supplied; the
output report makes the distinction visible.

## Conventions

A conformance test:

1. **Cites the spec.** First line of the docstring quotes the section.
2. **Is black-box.** No imports from `reference-implementation/*`. The
   tests should pass against any implementation of the spec, not just
   ours. (Static tests may read source files as text.)
3. **Has a single hard claim.** One spec assertion per test function.
4. **Skips, doesn't fail, on missing prerequisites.** Use
   `pytest.skip()` if the fixture isn't supplied.
5. **Avoids fixtures that mutate persistent ledger state.** When state
   is required, use the per-test ephemeral fixtures in `conftest.py`.

## Result badge

CI publishes a JUnit XML and a JSON summary. The release tooling renders
a badge:

```
![SKI provenance conformance](https://img.shields.io/endpoint?url=...)
```

For paid attestation (sovereignty level), engage KpiFinity. See
[`docs/conformance.md`](../docs/conformance.md).
