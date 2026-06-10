# Knowledge Graph schema (v3.0)

> **License:** CC BY 4.0. See [LICENSE-docs.md](../LICENSE-docs.md).
> The **authoritative** schema reference is the v3 specification
> ([`specification-v3.md`](specification-v3.md), §3) and the Pydantic
> models in
> [`tools/kg-validator/src/kg_validator/models.py`](https://github.com/kpifinity/ski-framework/blob/main/tools/kg-validator/src/kg_validator/models.py).
> This page is the orientation guide.

A SKI Knowledge Graph is a single signed JSON document containing a
**typed graph**: typed nodes, typed edges between them, and metadata.
It is the framework's brain — every obligation the runtime evaluates,
every citation a verdict carries, and every jurisdiction scope comes
from this artifact. It is compiled offline in Phase 1, human-reviewed,
signed, and only then loaded by the runtime.

## Top-level shape

```json
{
  "metadata": { "name": "...", "schema_version": "3.0", "sector": "...", "compiled_at": "..." },
  "nodes": {
    "subjects":      [ ... ],
    "rules":         [ ... ],
    "obligations":   [ ... ],
    "definitions":   [ ... ],
    "exemptions":    [ ... ],
    "precedents":    [ ... ],
    "jurisdictions": [ ... ],
    "citations":     [ ... ]
  },
  "edges": [ ... ]
}
```

A validated, runnable example:
[`examples/energy/knowledge-graphs/kg-energy-v3-demo.json`](https://github.com/kpifinity/ski-framework/blob/main/examples/energy/knowledge-graphs/kg-energy-v3-demo.json).

## Node kinds

Every node carries `id`, `type`, and `version`. The load-bearing kinds:

| Kind | What it is |
|---|---|
| `Subject` | What telemetry is about (`facility.so2.discharge`). Telemetry records reference subjects; a record whose subject is absent from the scoped KG produces `NULL_UNMAPPED`. |
| `Rule` | A named rule with a declared `risk_tier` (consumed by the Risk-Tier Governor — the caller can never self-declare a tier). |
| `Obligation` | The typed, machine-checkable core — see below. |
| `Definition` | Resolvable term definitions the LLM can be grounded on. |
| `Exemption` | First-class exemption nodes (not free-text caveats). |
| `Precedent` | Links to prior decisions/interpretations. |
| `Jurisdiction` | Scope anchor (`us.federal`, `eu`, `ca.alberta`, ...). |
| `Citation` | `source_document` + `source_clause` — every obligation must trace to one. |

## Typed obligations (spec §3.3)

```json
{
  "id": "energy.so2.lte_100ppm",
  "type": "Obligation",
  "version": "v3demo-0005",
  "obligation_type": "must_not_exceed",
  "metric": "so2_ppm",
  "value": 100,
  "unit": "ppm",
  "effective_date_start": "2026-01-01T00:00:00Z",
  "summary": "SO2 concentration must not exceed 100 ppm."
}
```

`obligation_type` is a **closed enumeration** — `must`, `must_not`,
`must_not_exceed`, `must_be_at_least`, `must_be_below`,
`must_be_above`, `must_be_within`, `must_be_one_of`,
`must_not_be_one_of`, `must_be_recorded_within`. The Symbolic Verifier
mechanically cross-checks the numerically formalizable subset; anything
else is honestly reported `UNVERIFIABLE` in the verdict envelope.

`effective_date_start` (and optional `effective_date_end`) drive
effective-date scoping: the runtime evaluates each measurement against
the obligations in force **at the measurement's timestamp**, not at
arrival time.

## Edges

```json
{ "type": "applies_to",  "from": "<rule id>",       "to": "<subject id>" }
{ "type": "consists_of", "from": "<rule id>",       "to": "<obligation id>" }
{ "type": "scoped_to",   "from": "<obligation id>", "to": "<jurisdiction id>" }
{ "type": "cited_by",    "from": "<obligation id>", "to": "<citation id>" }
```

Edges replace the v2 `tag_registry` routing table: subject resolution
is graph traversal (`applies_to`), and obligations reach jurisdictions
and citations through explicit, validatable edges. `kg-validator`'s
§3.6 passes enforce referential integrity — every edge endpoint must
resolve to a declared node, every obligation must be cited and scoped.

## Jurisdiction + effective-date scoping at runtime

`KnowledgeGraph.scope_to(jurisdiction, as_of)` returns the slice of
obligations applicable to a tenant's jurisdiction and in force at the
measurement's timestamp. Only that slice is shown to the LLM (so
real-sized KGs don't blow the context window), and the scope block
travels inside the signed transcript so an auditor can confirm exactly
what the model saw.

## Signing

The KG is signed with Ed25519 by a designated Phase-1 signing key
(`ski-model-deploy sign`). Signature verification at load time is
**mandatory** — there is no `verify_signature=False` escape hatch in
the deploy tool. The reference runtime's `KG_REQUIRE_SIGNATURE=false`
knob exists only so the unsigned demo KGs can load; it is
non-conformant by definition (the Durability conformance suite asserts
signed-KG-required).

## Lifecycle

1. **Extract** — `kg-extractor` reads regulatory documents and emits
   candidates. Never trusted directly.
2. **Validate** — `kg-validator validate -i <kg.json>`: schema +
   referential integrity + human expert review. No auto-approval.
3. **Sign** — Ed25519, designated signing key.
4. **Deploy** — `ski-model-deploy`, which refuses unsigned graphs.
5. **Evolve** — regulations change; the KG is a versioned, living
   artifact. The ledger records `knowledge_graph_version` on every
   verdict, so any historical verdict can be tied to the exact graph
   that produced it.

## Related

- [Architecture](architecture.md) — where the KG sits in the dataflow
- [Conformance](conformance.md) — what the suites assert about KGs
- [Replay](replay.md) — re-verification against historical graphs
