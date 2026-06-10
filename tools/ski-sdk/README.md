# ski-sdk

Typed Python client for the [SKI Framework](https://github.com/kpifinity/ski-framework)
SKI Model, with one-call verification of a verdict's signed provenance.

> **Status: early alpha.** This wraps an alpha HTTP API; pin your versions. The
> SDK is versioned independently of the framework — see the compatibility note
> in the docs.

```python
from ski_sdk import SKIClient

client = SKIClient(endpoint="https://ski.internal:8000", api_key="…")
env = client.evaluate(
    measurement_id="m-001",
    timestamp="2026-06-05T12:00:00Z",
    subject="stack-7",
    measurement={"so2_ppm": 150},
)
print(env.verdict, [c.node_id for c in env.kg_citations])  # FLAG ['energy.so2.lte_100ppm']
```

Verify a verdict's signed transcript (tamper-evident provenance):

```python
from ski_sdk import verify_transcript

report = verify_transcript(transcript, public_key_pem)
assert report.ok  # signature valid AND recorded hashes match the canonical pair
```
