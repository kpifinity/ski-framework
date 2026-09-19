# ski-sdk

> Install from PyPI: `pip install ski-sdk` (publishing starts with the first release after June 2026).

Typed Python client for the [SKI Framework](https://github.com/kpifinity/ski-framework)
SKI Model, with one-call verification of a verdict's signed provenance.

> **Status: GA (v3.1.0).** As of the v3.1.0 GA release the SDK is versioned
> together with the framework (see [RFC 0003](../../docs/RFCs/0003-client-sdk-and-shared-schemas.md));
> the earlier independent alpha/beta versioning no longer applies.

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
