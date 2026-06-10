# Finance — DEMO ONLY

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** Two illustrative v3 rules for
> the SKI Framework reference implementation. Not a BSA/AML
> compliance KG. The production Finance KG library is proprietary — see
> [KpiFinity](https://kpifinity.com).

## What's in here

```
finance/
├── README.md
├── knowledge-graphs/
│   └── kg-finance-v3-demo.json   # v3 typed graph, 2 rules, unsigned
└── telemetry/
    └── sample-aml-alerts.jsonl
```

## The two demo rules

| Rule id | Obligation |
|---|---|
| `finance.cip.completion_within_30d` | `days_to_cip_completion must_not_exceed 30` |
| `finance.wire.purpose_documented` | `purpose_documented_pct must_be_at_least 100` |

The telemetry sample produces one CLEAR and one FLAG per rule, plus one
NULL_UNMAPPED record (unknown subject) for the Coverage Register.

See [examples/README.md](../README.md) for the v3 KG shape, the
structural rules every demo follows, and how to run it.
