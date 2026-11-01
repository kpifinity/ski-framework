# OMS conformance fixture

`model/` is a three-file stand-in model. `model.sig` was produced by the
OpenSSF reference tool, `model-signing` 1.1.1:

    model_signing sign key model --private_key key.priv --signature model.sig

with an ECDSA P-256 key whose public half is `origin.pub` (the private key is
not kept). The runtime's verifier (`ski_model/model_signature.py`) must accept
it, which pins interoperability with the reference implementation.
