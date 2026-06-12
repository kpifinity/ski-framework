# Conformance suite changelog

| Spec version | Suite revision | Notes |
|---|---|---|
| v3.0 | 0.5.0 | Sovereignty (L3): all six checks runnable. The ledger tamper-resistance rig seeds and attacks a throwaway Postgres (`SKI_L3_LEDGER_DSN`). The air-gapped boot rig runs runtime + ledger in one loopback-only `--network=none` namespace, replays a fixed workload, and verifies hash-chained ledger persistence from inside (Docker + `SKI_L3_AIRGAP=1`). |
| v3.0 | 0.4.0 | Sovereignty (L3): four of six checks now runnable as black-box structural checks (single-worker, no-egress boundary, jurisdiction scope, signed transcript), plus a functional no-egress test in the runtime suite. Tamper-resistance and air-gapped boot remain pending their Postgres / container fixtures. |
| v3.0 | 0.3.0 | Reorganised around verifiable provenance. Provenance (L1) and Durability (L2) tests runnable. Sovereignty (L3) scaffolded; harness pending. |
| v2.1 | 0.1.0-alpha | Level 1 tests runnable. Level 2 in progress. Level 3 planned. |

The conformance suite is versioned with the spec. To claim
"SKI v3.0 Provenance / Durability conformant", the implementation must
pass this suite at the corresponding revision.
