# Knowledge Graph schema (v2.1)

> **License:** CC BY 4.0. See [LICENSE-docs.md](../LICENSE-docs.md).

A SKI Knowledge Graph is a single signed JSON document. This is the
authoritative description of its shape. A reference JSON Schema lives at
[`docs/schemas/knowledge-graph.schema.json`](./schemas/knowledge-graph.schema.json)
(generated from this document).

## Top-level shape

```json
{
  "metadata":      { ... },
  "rules":         [ { ... }, ... ],
  "tag_registry":  { "<subject>": "<rule_id>", ... },
  "signature":     { ... }
}
```

The four top-level keys must all be present, in any order. The
`signature` is computed over the canonical serialization of the other
three blocks (see *Signing* below).

## `metadata`

```json
{
  "version":                  "energy-v1.2",
  "sector":                   "energy",
  "compiled_at":              "2026-05-22T10:00:00Z",
  "compiler":                 "kg-extractor 0.1.0",
  "source_document":          "Clean Air Act consolidated, 2025-12-31 edition",
  "source_document_version":  "2025-12-31",
  "model_file_sha256":        "<hex>",
  "extraction_seed":          42,
  "human_validators":         ["jane.doe@example.com"],
  "notes":                    "..."
}
```

`source_document_version` is required. Rules are bound to a specific
edition of their source document so updates are traceable.

## `rules[]`

Every rule is an object with the following fields:

| Field | Required | Description |
|---|---|---|
| `id` | yes | Unique within the KG. Stable across versions. |
| `subject` | yes | Telemetry subject this rule applies to. Resolved via `tag_registry`. |
| `predicate` | yes (Track 1) | Structured predicate. See *Predicates* below. |
| `object` | yes | Human-readable summary of the predicate. **Never** a free-text obligation the runtime needs to interpret. |
| `relation` | yes | Verbal form (e.g. `must_not_exceed`). For humans. |
| `track` | yes | `"symbolic"` for Track 1, `"llm"` for Track 2. |
| `confidence` | yes | `EXPLICIT` or `DISCRETIONARY`. `IMPLIED` is **prohibited** (B2.1 Anchor Constraint). |
| `reasoning` | yes | Short rationale citing source. |
| `source_document` | yes | Authoritative source name. |
| `source_clause` | yes | Exact clause reference. |
| `source_document_version` | yes | Edition / publication date. Binds the rule to a version. |
| `effective_date` | yes | ISO-8601 date when the rule takes effect. |
| `sunset_date` | optional | ISO-8601 date after which the rule is retired, or `null`. |
| `precedence` | optional, default 100 | Integer priority for conflict resolution. Higher wins. |
| `conflicts_with` | optional | List of rule ids this rule explicitly conflicts with. |
| `requires_recent_within_seconds` | optional | Freshness window for stateful evaluation. Drives `NULL_STALE`. |

## Predicates (Track 1)

The Symbolic Evaluator operates on a small, deterministic predicate
grammar. Every Track 1 rule has a `predicate` of one of these shapes:

| Operator | Fields | Semantics |
|---|---|---|
| `lte`, `gte`, `lt`, `gt`, `eq` | `metric`, `value`, optional `unit` | numeric comparison |
| `range` (alias `between`) | `metric`, `min`, `max`, optional `unit` | `min ≤ observed ≤ max` |
| `in_set` | `metric`, `value` (list) | observed ∈ value |
| `not_in_set` | `metric`, `value` (list) | observed ∉ value |
| `exists` | `metric` | metric is present in telemetry |

`metric` is a dotted path into `telemetry.measurement`. A metric value
may be either a scalar or a `{value, unit}` pair; unit mismatches with
the predicate's expected unit produce `DISCRETIONARY` rather than a
silent coercion.

Predicates that do not fit this grammar must be Track 2 (`track: "llm"`),
in which case `predicate` is descriptive only.

## `tag_registry`

A flat object mapping the **normalised** subject string (lowercase,
whitespace-collapsed) to a `rule_id` that exists in `rules`. Every
subject mentioned in telemetry must appear here; missing subjects
produce `NULL_UNMAPPED` at runtime.

The Tag Registry is **compiled in Phase 1** by the human validators —
not inferred at runtime.

## `signature`

```json
{
  "algorithm":      "ed25519",
  "public_key_pem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n",
  "value_hex":      "<hex>"
}
```

`value_hex` is the Ed25519 signature over the SHA-256 of the canonical
serialization of `{metadata, rules, tag_registry}`. The canonical
serialization is `json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` encoded as UTF-8.

A KG with `algorithm: "DEMO_UNSIGNED"` is non-conformant and the SKI
Model refuses to load it unless `KG_REQUIRE_SIGNATURE=false`. Use only
for local demos.

## Example

A minimal, complete five-rule demo KG lives at
[`examples/energy/knowledge-graphs/kg-energy-demo.json`](../examples/energy/knowledge-graphs/kg-energy-demo.json).
A real production-grade Energy library is available from
[KpiFinity](https://kpifinity.com).

## Validating a KG

```bash
python scripts/validate-kg.py /path/to/kg.json
```

Checks the structural rules above, signature, no `IMPLIED` rules,
structured predicates on Track 1 rules, ISO-8601 dates, and Tag Registry
consistency.

## Lifecycle

A KG progresses through:

1. **Draft** — produced by `kg-extractor` from a source document.
2. **Validated** — every rule reviewed by a qualified human via
   `kg-validator`. No auto-approval.
3. **Signed** — Ed25519 signature applied by a designated signing key.
4. **Deployed** — loaded into the SKI Model via `ski-model-deploy`.
5. **Retired** — superseded by a new version. Old versions are retained
   for audit / replay.

The Knowledge Graph file is the boundary artefact between Phase 1
(probabilistic) and Phase 2 (deterministic). Everything probabilistic
must happen before signing; everything after signing is deterministic.
