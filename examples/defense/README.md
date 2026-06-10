# Defense — DEMO ONLY

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** Two illustrative v3 rules for
> the SKI Framework reference implementation. Not a NIST SP 800-171 / CMMC
> compliance KG. The production Defense KG library is proprietary — see
> [KpiFinity](https://kpifinity.com).

## What's in here

```
defense/
├── README.md
├── knowledge-graphs/
│   └── kg-defense-v3-demo.json   # v3 typed graph, 2 rules, unsigned
└── telemetry/
    └── sample-security-incidents.jsonl
```

## The two demo rules

| Rule id | Obligation |
|---|---|
| `defense.cui.encryption_at_rest` | `unencrypted_cui_stores must_not_exceed 0` |
| `defense.access.mfa_required` | `mfa_coverage_pct must_be_at_least 100` |

The telemetry sample produces one CLEAR and one FLAG per rule, plus one
NULL_UNMAPPED record (unknown subject) for the Coverage Register.

See [examples/README.md](../README.md) for the v3 KG shape, the
structural rules every demo follows, and how to run it.
