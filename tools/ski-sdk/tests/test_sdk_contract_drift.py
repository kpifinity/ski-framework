"""Contract-drift guard: SDK models must match the server's field-for-field.

Skips when the reference implementation is not importable (so the SDK package
stays independently testable); runs in the repo CI where `ski_model` is on the
path. If the server changes a model, this test fails and the SDK must follow.
"""

from __future__ import annotations

import pytest

pytest.importorskip("ski_model.v3.envelope")

from ski_model.v3 import envelope as srv
from ski_model.v3 import transcript as srv_t
from ski_sdk import models as sdk


def _fields(model: object) -> set:
    return set(model.model_fields)  # type: ignore[attr-defined]


def test_envelope_and_nested_models_match() -> None:
    pairs = [
        (srv.V3VerdictEnvelope, sdk.V3VerdictEnvelope),
        (srv.KGCitation, sdk.KGCitation),
        (srv.FormalizableAssertion, sdk.FormalizableAssertion),
        (srv.VerifierResult, sdk.VerifierResult),
        (srv.ModelProvenance, sdk.ModelProvenance),
        (srv_t.LLMTranscript, sdk.LLMTranscript),
    ]
    for server_model, sdk_model in pairs:
        sf, df = _fields(server_model), _fields(sdk_model)
        assert sf == df, f"{server_model.__name__} drift: only-server={sf - df} only-sdk={df - sf}"


def test_measurement_record_matches() -> None:
    srv_server = pytest.importorskip("ski_model.server")
    sf = set(srv_server.MeasurementRecord.model_fields)
    df = set(sdk.MeasurementRecord.model_fields)
    assert sf == df, f"MeasurementRecord drift: only-server={sf - df} only-sdk={df - sf}"
