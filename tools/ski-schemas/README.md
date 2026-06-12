# ski-schemas

> Install from PyPI: `pip install ski-schemas`

The [SKI Framework](https://github.com/kpifinity/ski-framework) wire
models — the v3 verdict envelope, the signed LLM transcript, and the
measurement record — extracted into one dependency-light package per
RFC 0003. The server, the `ski-sdk` client, and the conformance suite
all import these models, so the wire contract has exactly one
definition.

```python
from ski_schemas import V3VerdictEnvelope

envelope = V3VerdictEnvelope.model_validate_json(raw)
print(envelope.verdict, envelope.model_provenance.kg_version_hash)
```

Versioned independently of the framework (it carries a wire contract,
not a runtime). Dependencies: `pydantic` only.
