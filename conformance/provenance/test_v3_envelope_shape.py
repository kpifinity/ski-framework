"""SKI Framework v3.0 §4 — V3VerdictEnvelope contract conformance.

The verdict envelope is the audit-grade contract every conformant runtime
must produce. This test reads the reference implementation's envelope
module statically (so it works without a live deployment) and asserts the
spec §4.2 required fields, the §4.6 ModelProvenance required fields, and
the §4.5 VerifierStatus taxonomy are all present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REQUIRED_ENVELOPE_FIELDS = {
    "verdict",
    "reasoning",
    "kg_citations",
    "formalizable_assertions",
    "verifier_result",
    "model_provenance",
    "transcript_ref",
}

_REQUIRED_PROVENANCE_FIELDS = {
    "model_weight_hash",
    "kg_version_hash",
    "prompt_template_id",
    "prompt_template_hash",
    "decoder_seed",
    "structured_grammar_hash",
}

_REQUIRED_VERIFIER_STATUSES = {
    "AGREED",
    "LLM_CONTRADICTION",
    "NEURO_SYMBOLIC_DIVERGENCE",
    "UNVERIFIABLE",
}

_REQUIRED_CITATION_ROLES = {
    "obligation",
    "definition_resolved",
    "exemption_considered",
    "precedent_referenced",
    "jurisdiction_matched",
}


def _envelope_source(repo_root: Path) -> str:
    return (repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "envelope.py").read_text()


@pytest.mark.provenance
def test_envelope_has_all_required_fields(repo_root: Path) -> None:
    """Every spec §4.2 required envelope field is declared on V3VerdictEnvelope."""
    src = _envelope_source(repo_root)
    for field in _REQUIRED_ENVELOPE_FIELDS:
        assert f"{field}:" in src, f"V3VerdictEnvelope is missing required field {field!r} per spec §4.2."


@pytest.mark.provenance
def test_envelope_forbids_extra_fields(repo_root: Path) -> None:
    """The envelope's ConfigDict must set ``extra=\"forbid\"`` (spec §4.2)."""
    src = _envelope_source(repo_root)
    assert 'extra="forbid"' in src, "V3VerdictEnvelope must reject unknown fields with extra='forbid'."


@pytest.mark.provenance
def test_provenance_has_all_six_required_fields(repo_root: Path) -> None:
    """Every spec §4.6 required ModelProvenance field is declared."""
    src = _envelope_source(repo_root)
    for field in _REQUIRED_PROVENANCE_FIELDS:
        assert f"{field}:" in src, f"ModelProvenance is missing required field {field!r} per spec §4.6."


@pytest.mark.provenance
def test_provenance_hashes_enforce_sha256_prefix(repo_root: Path) -> None:
    """ModelProvenance hash fields must be regex-constrained to ``sha256:<hex>``."""
    src = _envelope_source(repo_root)
    assert "^sha256:[0-9a-f]+$" in src, "ModelProvenance must enforce the sha256: prefix on every hash field."


@pytest.mark.provenance
def test_verifier_status_has_all_four_values(repo_root: Path) -> None:
    """VerifierStatus enum lists the four spec §4.5 values and only those."""
    src = _envelope_source(repo_root)
    for status in _REQUIRED_VERIFIER_STATUSES:
        assert f'{status} = "{status}"' in src, f"VerifierStatus is missing {status!r} per spec §4.5."


@pytest.mark.provenance
def test_citation_roles_match_spec(repo_root: Path) -> None:
    """KGCitationRole lists the five spec §4.3 roles."""
    src = _envelope_source(repo_root)
    for role in _REQUIRED_CITATION_ROLES:
        assert f'"{role}"' in src, f"KGCitationRole is missing the role {role!r} per spec §4.3."


@pytest.mark.provenance
def test_formalizable_assertion_requires_obligation_id(repo_root: Path) -> None:
    """FormalizableAssertion.obligation_id is REQUIRED per spec §4.4."""
    src = _envelope_source(repo_root)
    assert "obligation_id: str = Field(..., " in src, (
        "FormalizableAssertion.obligation_id must be a required Field (no default)."
    )
