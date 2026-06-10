# Manufacturing — DEMO ONLY

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** Two illustrative v3 rules for
> the SKI Framework reference implementation. Not a OSHA general-industry
> compliance KG. The production Manufacturing KG library is proprietary — see
> [KpiFinity](https://kpifinity.com).

## What's in here

```
manufacturing/
├── README.md
├── knowledge-graphs/
│   └── kg-manufacturing-v3-demo.json   # v3 typed graph, 2 rules, unsigned
└── telemetry/
    └── sample-safety-incidents.jsonl
```

## The two demo rules

| Rule id | Obligation |
|---|---|
| `mfg.noise.lte_85dba_8h_twa` | `dba_8h_twa must_not_exceed 85 dBA` |
| `mfg.machine_guard.required` | `guard_disengaged_events must_not_exceed 0` |

The telemetry sample produces one CLEAR and one FLAG per rule, plus one
NULL_UNMAPPED record (unknown subject) for the Coverage Register.

See [examples/README.md](../README.md) for the v3 KG shape, the
structural rules every demo follows, and how to run it.
