# SKI Framework conformance test suite

> **License:** Apache 2.0. See [../LICENSE](../LICENSE).

This directory contains the **runnable conformance test suite** for the
SKI Framework v2.1. Each test cites the specification section it
validates. The suite is divided into Level 1 (Foundational), Level 2
(Managed), and Level 3 (Assured) — see
[`docs/CONFORMANCE.md`](../docs/CONFORMANCE.md) for the methodology.

## Layout

```
conformance/
├── README.md             ← you are here
├── CHANGELOG.md          spec-version ↔ suite-revision pairing
├── conftest.py           pytest fixtures: ski-endpoint, api-key, etc.
├── pytest.ini            marker registration (level1, level2, level3)
├── level1/               Foundational (runnable today)
│   ├── test_verdict_taxonomy.py
│   ├── test_determinism.py
│   ├── test_signature_required.py
│   ├── test_tag_registry.py
│   ├── test_no_confidence.py
│   ├── test_canary_active.py
│   ├── test_ledger_integrity.py
│   └── test_append_only.py
├── level2/               Managed (in progress)
└── level3/               Assured (planned)
```

## Quick start

```bash
pip install -r ../requirements-dev.txt

# Static tests (no live deployment needed):
pytest conformance/ -q -m level1

# Against a live deployment:
pytest conformance/ -q -m level1 \
  --ski-endpoint https://localhost:8000 \
  --api-key "$SKI_API_KEY" \
  --ledger-dsn "$LEDGER_DSN"
```

`--ski-endpoint` / `--api-key` / `--ledger-dsn` can also be supplied via
`SKI_ENDPOINT`, `SKI_API_KEY`, `LEDGER_DSN`. Tests requiring a live
deployment will be skipped (not failed) if these aren't supplied; the
output report makes the distinction visible.

## Conventions

A conformance test:

1. **Cites the spec.** First line of the docstring quotes the section.
2. **Is black-box.** No imports from `reference-implementation/*`. The
   tests should pass against any implementation of the spec, not just
   ours.
3. **Has a single hard claim.** One spec assertion per test function.
4. **Skips, doesn't fail, on missing prerequisites.** Use
   `pytest.skip()` if the fixture isn't supplied.
5. **Avoids fixtures that mutate persistent ledger state.** When state
   is required, use the per-test ephemeral fixtures in `conftest.py`.

## Result badge

CI publishes a JUnit XML and a JSON summary. The release tooling renders
a badge:

```
![SKI Level 1 conformance](https://img.shields.io/endpoint?url=...)
```

For paid certification (Level 3 Assured), engage KpiFinity. See
[`docs/CONFORMANCE.md`](../docs/CONFORMANCE.md).
