# Finance — DEMO ONLY

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** The KG and telemetry here are
> illustrative artefacts for the SKI Framework reference implementation.
> They are not a validated AML / BSA compliance KG and must not be
> deployed against real transaction monitoring systems. The production
> Finance KG library is proprietary — see [KpiFinity](https://kpifinity.com).

## What's in here

```
finance/
├── README.md
├── knowledge-graphs/
│   └── kg-finance-demo.json    # 3 illustrative rules, DEMO_UNSIGNED
└── telemetry/
    └── sample-aml-alerts.jsonl # No `rule_id` — Tag Registry routes
```

## The three demo rules

| Rule id | Subject | Predicate | Track |
|---|---|---|---|
| `finance.wire.large_no_purpose` | `transaction.wire.large` | `has_business_purpose == true` | symbolic |
| `finance.cip.completion_within_30d` | `transaction.account_opening.cip` | `days_to_cip_completion ≤ 30` | symbolic |
| `finance.sar.discretionary` | `transaction.suspicious_activity.review` | discretionary, human review | llm |

The source_clause values are placeholders (`demo-BSA-...`) — any
resemblance to current BSA/AML obligations is coincidental.

## Sample telemetry

`sample-aml-alerts.jsonl` exercises CLEAR, FLAG, DISCRETIONARY, and
NULL_UNMAPPED paths. Crucially, **no record contains `rule_id`** — the
previous version's pre-routing was an architectural bug.

## Path to a real Finance KG

See the matching note in [examples/energy/README.md](../energy/README.md).
The production Finance KG library is available via
[KpiFinity](https://kpifinity.com).
