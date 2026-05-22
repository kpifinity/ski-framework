# SKI Framework — tools

> **⚠ STATUS: EARLY ALPHA.** All four tools are at v0.1.0-alpha. See the
> repo root `README.md` for the project-wide status banner.

Open-source tooling for implementing the SKI Framework. All four tools
are Apache 2.0 licensed and run on-premise without any required cloud
API key. (The kg-extractor's optional `anthropic` and `openai` backends
are for Phase 1 compilation only and must not be used at runtime.)

## What lives here

| Tool | Phase | Purpose |
|---|---|---|
| [`kg-extractor/`](./kg-extractor/) | Phase 1 (compilation) | Extract structured compliance rules from regulatory documents. Refuses to emit `IMPLIED` rules. Records seed + prompt SHA-256 for reproducibility audits. |
| [`kg-validator/`](./kg-validator/) | Phase 1 (compilation) | Run automated checks over extracted rules. No auto-approval — every rule still requires human review (B2.3). |
| [`ski-model-deploy/`](./ski-model-deploy/) | Phase 2 (runtime) | Verify a signed Knowledge Graph and deploy the SKI Model stack. Signature verification is mandatory; there is no override. |
| [`audit-ledger/`](./audit-ledger/) | Phase 2 (runtime) | Verify, export, report on, and back up the append-only audit ledger. Real `pg_dump` backup; real entry-hash recomputation in `verify`. |

(Pre-v2.1 docs referred to `milm-deploy`; the renamed `ski-model-deploy`
is its successor.)

## Tool structure

Every tool follows the same skeleton:

```
tool-name/
├── README.md            Usage guide
├── requirements.txt     Pinned dependencies
├── setup.py             Apache-2.0 classifier
├── src/<package>/       Source code
└── tests/               Pytest suite
```

## Installation

```bash
pip install -e tools/kg-extractor \
              -e tools/kg-validator \
              -e tools/ski-model-deploy \
              -e tools/audit-ledger
```

All four expose console scripts: `kg-extractor`, `kg-validator`,
`ski-model-deploy`, `audit-ledger`. Each accepts `--help`.

## Contributing a new tool

Follow the structure above. The skeleton must include:

1. A README that includes the EARLY ALPHA banner and an open/proprietary
   note.
2. Pinned `requirements.txt` and `setup.py` with the Apache-2.0
   classifier.
3. Tests under `tests/` runnable via `pytest`.
4. A docstring on every public entry point that cites the spec section
   it serves.

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the broader flow.

## Licensing

Apache 2.0 — see [`../LICENSE`](../LICENSE) and [`../NOTICE`](../NOTICE).
The pre-built Knowledge Graph libraries (Energy, Finance, Manufacturing,
Defense) are proprietary and not in this repo; see
[KpiFinity](https://kpifinity.com).
