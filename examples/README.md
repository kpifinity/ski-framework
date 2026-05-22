# SKI Framework — DEMO examples

> **⚠ DEMO ONLY — NOT FOR PRODUCTION.** The Knowledge Graphs and telemetry
> records in this directory are deliberately tiny, illustrative artefacts
> built only to exercise the reference implementation end-to-end. They do
> **not** reflect actual regulatory obligations and must **not** be
> deployed against real operational systems. The production-grade,
> regulator-mapped Knowledge Graph libraries for each sector are
> proprietary and available via [KpiFinity](https://kpifinity.com).

## What's in here

Each subdirectory holds the same skeleton:

```
<sector>/
├── README.md                              Demo context + DEMO ONLY banner
├── knowledge-graphs/
│   └── kg-<sector>-demo.json              ≤ 5 illustrative rules,
│                                          structured predicates,
│                                          `track` field, signed (or
│                                          marked DEMO_UNSIGNED)
└── telemetry/
    └── sample.jsonl                       Telemetry without rule_id
                                           (Tag Registry resolves it)
```

We intentionally keep the demos under **five rules each** so they cannot
be confused with a production KG. If your scenario requires more than five
rules, you have left demo territory and should be talking to KpiFinity.

## Structural rules

The demos all satisfy the v2.1 spec requirements the conformance suite
checks for:

1. **No `rule_id` in telemetry records.** The producer must not pre-route.
   The Tag Registry compiled with the KG resolves `subject` → `rule_id`.
2. **Structured predicates.** Rule `object` is a structured
   `{operator, metric, value, unit}` block, not a free-text string.
3. **`track` field on every rule** — `"symbolic"` for Track 1 (the demos
   default to this) or `"llm"` for Track 2.
4. **No `confidence: "IMPLIED"` rules.** The Anchor Constraint (B2.1)
   forbids inference beyond source text.
5. **`tag_registry` mapping subject string → rule id** in the KG itself.
6. **Effective and sunset dates** in ISO-8601 where applicable.
7. **`source_document_version`** to bind each rule to a specific version
   of its source.

The demo KGs are shipped with `signature.algorithm = "DEMO_UNSIGNED"` —
they will be rejected by the SKI Model unless `KG_REQUIRE_SIGNATURE=false`
is set, which disqualifies the deployment from any conformance level.
This is intentional: it makes the demos visibly non-conformant so they
are never mistaken for production.

## Running a demo

```bash
# 1. Bring up the stack (one-time)
./scripts/setup.sh
./scripts/deploy.sh

# 2. (DEMO ONLY) allow the unsigned demo KG and load it
docker compose -f reference-implementation/docker-compose.yml \
  exec ski-model bash -c 'KG_REQUIRE_SIGNATURE=false python -c "..."'   # see DEPLOYMENT.md

# 3. Replay sample telemetry
python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl --insecure
```

## Going from a demo to a real deployment

The path to production:

1. Use `kg-extractor` to extract rules from your authoritative regulatory
   sources, with `temperature=0` and a recorded seed for reproducibility.
2. Use `kg-validator` to require human review of every extracted rule.
3. Sign the validated KG with your Ed25519 production key.
4. Deploy via `ski-model-deploy` (signature verification is mandatory).
5. Run the conformance suite against your live deployment.

Or contract with [KpiFinity](https://kpifinity.com) for a production-grade
sector KG library with regulator-mapped rules and ongoing maintenance.

## Adding a new demo

If you contribute a new sector demo, please:

1. Cap it at five rules.
2. Put a `DEMO ONLY` banner at the top of the sector `README.md`.
3. Use structured predicates and a `track` field on every rule.
4. Strip any `rule_id` from telemetry records.
5. Run `python scripts/validate-kg.py --allow-unsigned path/to/kg.json` and
   include the output in your PR.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the broader contribution flow.
