# Manufacturing — DEMO ONLY

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** Three illustrative safety
> rules for exercising the SKI Framework reference implementation.
> The production Manufacturing KG library is proprietary — see
> [KpiFinity](https://kpifinity.com).

## What's in here

```
manufacturing/
├── README.md
├── knowledge-graphs/
│   └── kg-manufacturing-demo.json   # 3 illustrative rules, DEMO_UNSIGNED
└── telemetry/
    └── sample-safety-incidents.jsonl
```

## The three demo rules

| Rule id | Subject | Predicate | Track |
|---|---|---|---|
| `mfg.machine_guard.required` | `equipment.machine_guard.status` | `guard_engaged == true` | symbolic |
| `mfg.noise.lte_85dba_8h_twa` | `workplace.noise.dba_8h_twa` | `dba_8h_twa ≤ 85 dBA` | symbolic |
| `mfg.lockout.tagout_required` | `maintenance.lockout_tagout` | `loto_applied == true` | symbolic |

See [examples/README.md](../README.md) for the structural rules every
demo follows.
