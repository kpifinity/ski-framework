# Defense — DEMO ONLY

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** Three illustrative rules for
> the SKI Framework reference implementation. Not a NIST 800-171 / CMMC
> compliance KG. The production Defense KG library is proprietary — see
> [KpiFinity](https://kpifinity.com).

## What's in here

```
defense/
├── README.md
├── knowledge-graphs/
│   └── kg-defense-demo.json
└── telemetry/
    └── sample-security-incidents.jsonl
```

## The three demo rules

| Rule id | Subject | Predicate | Track |
|---|---|---|---|
| `defense.cui.encryption_at_rest` | `data.cui.storage` | `encrypted_at_rest == true` | symbolic |
| `defense.access.mfa_required` | `access.privileged` | `mfa_present == true` | symbolic |
| `defense.incident.review` | `incident.security.candidate` | discretionary, human review | llm |

See [examples/README.md](../README.md) for the structural rules every
demo follows.
