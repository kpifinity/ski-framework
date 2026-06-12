"""RFC 0003 PR 1: the SDK and the server share ONE set of wire models.

The old version of this test guarded field-for-field parity between the
SDK's vendored models and the server's. The vendoring is gone — both
import ``ski-schemas`` — so the guard is now an identity check: if these
ever stop being the same objects, someone has re-introduced a copy.
"""

from __future__ import annotations

import pytest

pytest.importorskip("ski_model.v3.envelope")

from ski_model.v3 import envelope as srv
from ski_model.v3 import transcript as srv_t
from ski_sdk import models as sdk


def test_sdk_and_server_models_are_the_same_objects() -> None:
    assert srv.V3VerdictEnvelope is sdk.V3VerdictEnvelope
    assert srv.KGCitation is sdk.KGCitation
    assert srv.FormalizableAssertion is sdk.FormalizableAssertion
    assert srv.VerifierResult is sdk.VerifierResult
    assert srv.ModelProvenance is sdk.ModelProvenance
    assert srv.V3Verdict is sdk.V3Verdict
    assert srv.VerifierStatus is sdk.VerifierStatus
    assert srv_t.LLMTranscript is sdk.LLMTranscript


def test_shared_models_come_from_ski_schemas() -> None:
    assert sdk.V3VerdictEnvelope.__module__ == "ski_schemas.envelope"
    assert sdk.LLMTranscript.__module__ == "ski_schemas.transcript"
    assert sdk.MeasurementRecord.__module__ == "ski_schemas.measurement"
