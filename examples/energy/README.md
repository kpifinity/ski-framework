# Energy — DEMO ONLY

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** This is an illustrative
> five-rule Knowledge Graph for exercising the SKI Framework reference
> implementation. It is not a regulator-mapped, validated compliance
> KG and must not be deployed against real operations. The production
> Energy KG library is proprietary — see [KpiFinity](https://kpifinity.com).

## What's in here

```
energy/
├── README.md
├── knowledge-graphs/
│   └── kg-energy-demo.json     # 5 rules, structured predicates, DEMO_UNSIGNED
└── telemetry/
    └── sample.jsonl            # No `rule_id` — Tag Registry routes by subject
```

## The five demo rules

| Rule id | Subject | Predicate | Track |
|---|---|---|---|
| `energy.so2.lte_100ppm` | `facility.so2.discharge_ppm` | `so2_ppm ≤ 100 ppm` | symbolic |
| `energy.nox.lte_75ppm` | `facility.nox.discharge_ppm` | `nox_ppm ≤ 75 ppm` | symbolic |
| `energy.wastewater.ph_range` | `facility.wastewater.ph` | `ph ∈ [6.0, 8.5]` | symbolic |
| `energy.pm.lte_50` | `facility.pm.mg_per_m3` | `pm_mg_per_m3 ≤ 50 mg/m³` | symbolic |
| `energy.spill.disclosure_required` | `facility.spill.event` | discretionary, human review | llm |

The source_clause values in `kg-energy-demo.json` are placeholders
(`demo-CAA-...`) — they are illustrative, not citations to current
regulatory text. Treat any resemblance to a real obligation as
coincidental.

## Sample telemetry

`telemetry/sample.jsonl` includes a mix of:

- conforming measurements (CLEAR),
- breaches (FLAG),
- an unmapped subject (NULL_UNMAPPED) — to demonstrate Coverage Register behaviour,
- a spill event routed to Track 2 / DISCRETIONARY.

## Run it

```bash
# Stack already up via ./scripts/setup.sh && ./scripts/deploy.sh
# Allow loading the unsigned demo KG (non-conformant; demo only):
docker compose -f reference-implementation/docker-compose.yml \
  exec -e KG_REQUIRE_SIGNATURE=false ski-model \
  python -c "from ski_model.kg_loader import load_signed_kg; import os; load_signed_kg('/app/kg/kg-energy-demo.json', require_signature=False)"

# Replay the telemetry
python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl --insecure

# Inspect verdicts
python scripts/check-verdicts.py --insecure --limit 20
```

## Path to a real Energy KG

1. Identify the authoritative source(s) for each obligation. Bind each
   rule to a specific `source_document_version`.
2. Run `kg-extractor` with `temperature=0` and a recorded seed.
3. Have every rule reviewed by a qualified expert via `kg-validator`.
4. Express every rule as a structured predicate (no free-text `object`).
5. Sign the KG with your production Ed25519 key.
6. Deploy via `ski-model-deploy` (signature verification is mandatory).
7. Run the SKI conformance suite against the deployment.

Or contract with [KpiFinity](https://kpifinity.com) for the production
Energy KG library, regulator updates, and certification support.
