"""Spec §4, §5.1-§5.4: verdicts over HTTP, with the language model's answers scripted.

Every test scripts the model's answer for one telemetry record, sends the
record to ``/api/evaluate``, and checks the envelope the implementation
returns against the specification. The fixture KG's Rules are
``medium`` risk (spec §5.4), so the outcome of a verifier disagreement is
fixed: ``DISCRETIONARY``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from .answers import VERDICTS, answer, ph, so2
from .conftest import SUT
from .prepare import IDLE_SUBJECT, PH_OBLIGATION, PH_SUBJECT, SO2_OBLIGATION, SO2_SUBJECT

pytestmark = [pytest.mark.blackbox, pytest.mark.requires_live_deployment]

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2] / "spec/contracts/schemas/v3_verdict_envelope.schema.json"
    ).read_text(encoding="utf-8")
)
_HASH = r"^sha256:[0-9a-f]{64}$"


def _check_envelope(sut: SUT, envelope: dict[str, Any]) -> None:
    """Shape rules every envelope meets, whatever its verdict (spec §4.1-§4.6)."""
    jsonschema.validate(envelope, _SCHEMA)
    assert envelope["verdict"] in VERDICTS  # §4.1: the five values only
    for forbidden in ("confidence", "score", "probability"):
        assert forbidden not in envelope, f"§4.1: no {forbidden!r} beside the verdict"
    for citation in envelope["kg_citations"]:
        assert citation["node_id"] in sut.node_ids, f"§4.3: cites {citation['node_id']!r}, not a KG node"
    result = envelope["verifier_result"]
    if result["status"] == "UNVERIFIABLE":
        assert result["divergences"], "§4.5: an UNVERIFIABLE result records its reason"
    provenance = envelope["model_provenance"]
    assert provenance["kg_version_hash"] == sut.kg_version_hash, "§4.6/§7.3: kg_version_hash of the loaded KG"
    for field in ("model_weight_hash", "prompt_template_hash", "structured_grammar_hash"):
        assert provenance[field].startswith("sha256:") and provenance[field] == provenance[field].lower()
    assert provenance["prompt_template_id"]
    assert isinstance(provenance["decoder_seed"], int)


def test_honest_clear_is_honoured(sut: SUT) -> None:
    """§5.3/§5.4: the verifier agrees with a correct CLEAR, and a medium Rule honours it."""
    token = sut.token()
    env = sut.envelope(token, SO2_SUBJECT, {"so2_ppm": 85}, answer("CLEAR", [so2(85, True)]))
    _check_envelope(sut, env)
    assert env["verdict"] == "CLEAR"
    assert env["verifier_result"]["status"] == "AGREED"
    assert env["verifier_result"]["checked_assertions"] >= 1


def test_honest_flag_is_honoured(sut: SUT) -> None:
    """§4.1/§5.3: a breach the model reports correctly is FLAG, verifier AGREED."""
    token = sut.token()
    env = sut.envelope(token, SO2_SUBJECT, {"so2_ppm": 142}, answer("FLAG", [so2(142, False)]))
    _check_envelope(sut, env)
    assert env["verdict"] == "FLAG"
    assert env["verifier_result"]["status"] == "AGREED"


def test_range_predicate(sut: SUT) -> None:
    """§3.3 ``must_be_within``: a reading inside the range agrees, one outside does not pass as CLEAR."""
    inside = sut.envelope(sut.token(), PH_SUBJECT, {"ph": 7.1}, answer("CLEAR", [ph(7.1, True)]))
    _check_envelope(sut, inside)
    assert (inside["verdict"], inside["verifier_result"]["status"]) == ("CLEAR", "AGREED")
    outside = sut.envelope(sut.token(), PH_SUBJECT, {"ph": 9.2}, answer("CLEAR", [ph(9.2, True)]))
    _check_envelope(sut, outside)
    assert outside["verdict"] == "DISCRETIONARY"
    assert outside["verifier_result"]["status"] in {"LLM_CONTRADICTION", "NEURO_SYMBOLIC_DIVERGENCE"}


def test_self_contradicting_clear_goes_to_human_review(sut: SUT) -> None:
    """§4.5 LLM_CONTRADICTION (observed 142 > 100 yet "satisfied"), §5.4 medium: DISCRETIONARY."""
    env = sut.envelope(sut.token(), SO2_SUBJECT, {"so2_ppm": 142}, answer("CLEAR", [so2(142, True)]))
    _check_envelope(sut, env)
    assert env["verifier_result"]["status"] == "LLM_CONTRADICTION"
    assert env["verifier_result"]["divergences"]
    assert env["verdict"] == "DISCRETIONARY"


def test_self_contradicting_flag_goes_to_human_review(sut: SUT) -> None:
    """§4.5/§5.4 medium: a FLAG on a reading within the limit is not honoured; it goes to DISCRETIONARY.

    §4.5's wording makes this ``LLM_CONTRADICTION``. An implementation that
    first corrects ``satisfied`` from the reading reports
    ``NEURO_SYMBOLIC_DIVERGENCE`` (a FLAG whose assertions all hold); both
    reach the same verdict and both are accepted here until RFC 0004 settles
    the status (unresolved questions).
    """
    env = sut.envelope(sut.token(), SO2_SUBJECT, {"so2_ppm": 85}, answer("FLAG", [so2(85, False)]))
    _check_envelope(sut, env)
    assert env["verifier_result"]["status"] in {"LLM_CONTRADICTION", "NEURO_SYMBOLIC_DIVERGENCE"}
    assert env["verdict"] == "DISCRETIONARY"


@pytest.mark.parametrize(
    ("reading", "claimed", "verdict"),
    [
        pytest.param(142, 85, "CLEAR", id="breach-reported-as-clear"),
        pytest.param(85, 142, "FLAG", id="clean-reading-reported-as-breach"),
    ],
)
def test_misreported_reading_is_caught(sut: SUT, reading: int, claimed: int, verdict: str) -> None:
    """§5.3 step 1: the verifier reads the metric from the telemetry, not from the model's ``observed``."""
    assertion = so2(claimed, claimed <= 100)
    env = sut.envelope(sut.token(), SO2_SUBJECT, {"so2_ppm": reading}, answer(verdict, [assertion]))
    _check_envelope(sut, env)
    assert env["verifier_result"]["status"] in {"LLM_CONTRADICTION", "NEURO_SYMBOLIC_DIVERGENCE"}
    assert env["verdict"] == "DISCRETIONARY"


@pytest.mark.parametrize(
    "cited",
    [
        pytest.param("bb.not.in.kg", id="unknown-node"),
        pytest.param(PH_OBLIGATION, id="node-outside-the-slice"),
    ],
)
def test_citation_outside_the_slice_never_passes(sut: SUT, cited: str) -> None:
    """§4.3: no citation to a node outside the slice; such an answer is not CLEAR or FLAG."""
    env = sut.envelope(
        sut.token(),
        SO2_SUBJECT,
        {"so2_ppm": 85},
        answer("CLEAR", [so2(85, True)], citations=[SO2_OBLIGATION, cited]),
    )
    _check_envelope(sut, env)
    assert cited not in {c["node_id"] for c in env["kg_citations"]}
    assert env["verdict"] not in {"CLEAR", "FLAG"}


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("The emissions look fine to me.", id="prose"),
        pytest.param('{"verdict": "CLEAR", "reasoning": ', id="truncated-json"),
        pytest.param(json.dumps(answer("PROBABLY_CLEAR", [so2(85, True)])), id="verdict-outside-taxonomy"),
    ],
)
def test_unparseable_answer_is_discretionary(sut: SUT, content: str) -> None:
    """§5.2: output that does not parse as the envelope is DISCRETIONARY, with the error recorded."""
    env = sut.envelope(sut.token(), SO2_SUBJECT, {"so2_ppm": 85}, content)
    _check_envelope(sut, env)
    assert env["verdict"] == "DISCRETIONARY"
    assert env["verifier_result"]["divergences"]


def test_model_unavailable_fails_closed(sut: SUT) -> None:
    """§5.2: no model output (the scripted LLM answers 503) is DISCRETIONARY, never a verdict."""
    env = sut.envelope(sut.token(), SO2_SUBJECT, {"so2_ppm": 85}, None)
    _check_envelope(sut, env)
    assert env["verdict"] == "DISCRETIONARY"


def test_confidence_from_the_model_is_not_a_verdict(sut: SUT) -> None:
    """§4.1: a numeric confidence the model volunteers never appears beside the verdict."""
    env = sut.envelope(
        sut.token(), SO2_SUBJECT, {"so2_ppm": 85}, answer("CLEAR", [so2(85, True)], confidence=0.97)
    )
    _check_envelope(sut, env)


def test_slice_holds_only_the_subjects_rules(sut: SUT) -> None:
    """§5.1: the model sees the obligations of Rules that apply to the subject, and no others."""
    token = sut.token()
    sut.envelope(token, SO2_SUBJECT, {"so2_ppm": 85}, answer("CLEAR", [so2(85, True)]))
    requests = sut.llm_requests(token)
    assert requests, "§5.2: the language model is invoked for a routed subject"
    assert all(SO2_OBLIGATION in r for r in requests), "§5.1: the subject's obligation is in the slice"
    assert not any(PH_OBLIGATION in r for r in requests), "§5.1: another subject's obligation is not"


@pytest.mark.parametrize(
    "subject",
    [
        pytest.param(IDLE_SUBJECT, id="subject-no-rule-applies-to"),
        pytest.param("plant.unknown", id="subject-not-in-kg"),
    ],
)
def test_unrouted_subject_never_passes(sut: SUT, subject: str) -> None:
    """§5.1: a subject no Rule applies to has an empty slice, so nothing can establish CLEAR or FLAG.

    Spec §4.1 names ``NULL_UNMAPPED`` for a subject absent from the KG; an
    implementation that routes it to human review (``DISCRETIONARY``)
    instead is also accepted here (RFC 0004, unresolved questions).
    """
    token = sut.token()
    env = sut.envelope(token, subject, {"so2_ppm": 85}, answer("CLEAR", [so2(85, True)]))
    _check_envelope(sut, env)
    assert env["verdict"] in {"NULL_UNMAPPED", "DISCRETIONARY"}
    assert not any(SO2_OBLIGATION in r for r in sut.llm_requests(token)), (
        "§5.1: no unrouted obligation is sent"
    )


def test_malformed_record_is_rejected(sut: SUT) -> None:
    """OpenAPI ``MeasurementRecord``: a record without ``subject`` is a 422, not a verdict."""
    response = sut.http.post(
        "/api/evaluate", json={"measurement_id": sut.token(), "measurement": {"so2_ppm": 1}}
    )
    assert response.status_code == 422
