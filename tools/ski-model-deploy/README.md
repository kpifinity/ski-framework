# ski-model-deploy

> **⚠ STATUS: EARLY ALPHA (v0.1.0a0).** Alpha-quality tooling. See the
> repo root `README.md` for the project-wide status.

Deploy and configure the SKI Model inference engine on-premise.

`ski-model-deploy` is the deployment toolkit for the SKI Framework v2.1
runtime. (In pre-v2.1 docs this tool was called `milm-deploy`.)

## What it does

1. Generate a deployment configuration for a sector deployment.
2. **Verify the Ed25519 signature of a Knowledge Graph and register it
   with the deployment.** Signature verification is mandatory — there is
   no `--no-verify` escape hatch.
3. Stand up the SKI Model stack via Docker (Kubernetes manifests planned
   for v0.2).
4. Surface deployment status and a basic health view.

## Installation

```bash
pip install -e tools/ski-model-deploy
```

## Quick start

```bash
# 1. Initialise a deployment config (writes deployment-config.yaml).
ski-model-deploy init --name energy-prod --sector energy

# 2. Load a SIGNED Knowledge Graph (this will refuse to load an unsigned KG).
ski-model-deploy load-kg \
  --config deployment-config.yaml \
  --kg /path/to/signed-kg.json

# 3. Start the stack.
ski-model-deploy start --config deployment-config.yaml

# 4. Status.
ski-model-deploy status --config deployment-config.yaml
```

## Commands

| Command | Purpose |
|---|---|
| `init`      | Create a new deployment configuration. |
| `load-kg`   | Verify a signed KG and register it. Signature verification is mandatory. |
| `start`     | Bring up the stack (docker compose for the alpha; k8s planned). |
| `stop`      | Tear down the stack. |
| `status`    | Report deployment status as JSON. |

`--help` is supported on every command.

## Environment variables

The runtime (the SKI Model service itself) reads its own environment
variables documented in
`reference-implementation/.env.example`. The deployer cares about a
small subset relevant to its own operation:

| Variable | Default | Notes |
|---|---|---|
| `SKI_API_KEY` | required | Used for `--api-key` on `status` health probes. |
| `LEDGER_DSN` | required | Audit ledger DSN. |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Default inference backend URL. |
| `SKI_MODEL_NAME` | `qwen2.5:7b-instruct` | Model the runtime should use. |
| `SKI_MODEL_FILE_SHA256` | optional | If set, the runtime refuses to start unless the pulled model artefact matches. |

A non-conformant `anthropic` demo backend exists in the runtime. The
deployer does not encourage or wire it in. It is intentionally
inconvenient to enable.

## Signature verification — mandatory

This tool will REFUSE to load a Knowledge Graph that:

- has no `signature` block, or
- has `algorithm: "DEMO_UNSIGNED"`, or
- has a signature that does not verify under the embedded public key.

There is no `--no-verify`, no `verify_signature=False`, no override flag.
If you absolutely need to load an unsigned KG (for local prototyping
only), you must set `KG_REQUIRE_SIGNATURE=false` on the runtime, which
makes the deployment non-conformant and is reported as such by the
conformance test suite.

## Licensing

Apache 2.0. See [`../../LICENSE`](../../LICENSE).
