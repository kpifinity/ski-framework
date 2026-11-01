# Black-box conformance suite

Tests an implementation of the SKI specification **from the outside**: its
HTTP API (`spec/contracts/openapi.yaml`), its ledger (SQL, for the §7.2
storage-layer checks only), and the language-neutral vectors in
`spec/test-vectors/`. Nothing in this directory imports the reference
implementation (`test_static.py` enforces it), so a verifier written in
Rust, Go or anything else is judged by exactly the same tests.

## What it checks

| File | Spec | What |
|---|---|---|
| `test_evaluate.py` | §4.1-§4.6, §5.1-§5.4 | Envelope shape (JSON Schema), the five-verdict taxonomy, no confidence scores, citations only into the slice, `kg_version_hash` of the loaded KG, verifier statuses, risk-tier outcomes, fail-closed parsing, subject routing |
| `test_ledger.py` | §5.5, §7.1, §7.2 | Every verdict is recorded as returned; hash chain; envelope hash; SCITT statements and TRACE records signed by the deployment key; COSE Receipts prove Merkle inclusion; UPDATE / DELETE / TRUNCATE refused by the storage layer |
| `test_static.py` | §7.3, §7.1 | The suite's own canonicalizer and Merkle checker reproduce `spec/test-vectors/`; the scripted LLM works; no reference imports |

The checkers (`checkers.py`: RFC 8785, RFC 6962/9162, COSE_Sign1) are
written from the RFCs and verified against the vectors, so a pass means the
implementation agrees with the specification, not with the reference code.

## The LLM hook

A conformance run cannot depend on what a real model happens to say. The
implementation under test is pointed at `scripted_llm.py`, an
OpenAI-compatible chat-completions server (`GET /v1/models`,
`POST /v1/chat/completions`). Before each evaluation a test scripts the
model's raw output: a correct answer, a self-contradicting one, one that
misreports the reading, one that cites a node outside the slice, prose,
truncated JSON, or nothing at all (HTTP 503). The answer is matched by a
unique token the test adds to the measurement object
(`conformance_token`, a field no obligation maps).

An implementation is conformance-testable if it can use an
OpenAI-compatible endpoint as its language model and pass the
measurement object to it.

## Running it

1. `python conformance/blackbox/prepare.py OUT` writes `OUT/kg.json`, the
   fixture KG signed with a fresh key (§3.5), and `OUT/kg-trust-anchor.pem`.
2. `python conformance/blackbox/scripted_llm.py MODEL PORT` starts the hook.
3. Start the implementation with that KG, that trust anchor as its only KG
   anchor, the hook as its model, and an empty ledger.
4. Run the suite:

```bash
pytest conformance/blackbox \
  --ski-endpoint http://127.0.0.1:8000 --api-key "$KEY" \
  --scripted-llm http://127.0.0.1:9000 --kg-fixture OUT/kg.json \
  --ledger-dsn postgresql://... [--ledger-table ledger_entries]
```

`adapters/reference.py` does all four steps for the reference
implementation (it is what CI runs):

```bash
python conformance/blackbox/adapters/reference.py \
  --ledger-dsn postgresql://postgres:pw@127.0.0.1:5432/ski_blackbox
```

An adapter for another implementation follows the same pattern. Tests whose
options are missing skip rather than fail; the ledger-evidence tests skip if
the implementation has no `GET /api/ledger/{n}/evidence`.

## Where the reference and the text differ

Writing this suite surfaced places where the specification's wording and
the reference implementation disagree, and both are defensible. The suite
accepts either behaviour there and RFC 0004 records them for the Spec
Editor: the verifier status of a FLAG whose assertions all hold, the verdict
for a subject absent from the KG, and the `high` / `low` risk-tier rules.
