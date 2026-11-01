"""OSCAL 1.1.3 Assessment Results from a ledger verification (and, optionally, a replay).

NIST OSCAL is how assessors exchange assessment results with GRC tooling
(FedRAMP, CSAM, Trestle, RegScale). ``audit-ledger export-oscal`` turns the
evidence SKI already proves into that format: one OSCAL *result* per run,
with an *observation* per integrity check (method ``TEST``) and a *finding*
per check whose target objective is the spec requirement it tests
(``satisfied`` / ``not-satisfied``). Integrity issues become additional
observations of type ``finding`` linked from the failing check.

Identifiers are UUIDv5 over the content, so exporting the same verification
twice gives the same document. The document validates against NIST's
published ``oscal_assessment-results_schema.json`` (1.1.3); see
``tools/audit-ledger/tests/test_oscal.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .models import VerificationResult

OSCAL_VERSION = "1.1.3"
_NS = uuid.UUID("2b6c3c0e-8f1d-5b6e-9a3c-5c1f0a7e0001")
_SKI_NS = "https://skiframework.org/ns/oscal"


def _uuid(*parts: object) -> str:
    return str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


def _ts(value: Optional[datetime]) -> str:
    moment = (value or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _prop(name: str, value: object) -> dict[str, str]:
    return {"name": name, "ns": _SKI_NS, "value": str(value)}


# Which integrity issues (audit_ledger.ledger / .evidence) evidence a failing objective.
_ISSUES_BY_OBJECTIVE: dict[str, set[str]] = {
    "ski-spec-7.2-append-only-chain": {"HASH_MISMATCH", "SEQUENCE_GAP"},
    "ski-spec-7.1-entry-hash": {"ENTRY_HASH_MISMATCH", "EVIDENCE_HASH_MISMATCH", "FORMAT_DOWNGRADE"},
    "ski-spec-7.1-verdict-signature": {
        "VERDICT_SIGNATURE_INVALID",
        "UNTRUSTED_SIGNING_KEY",
        "SIGNING_KEY_MISMATCH",
    },
    "ski-spec-7.1-checkpoints": {
        "CHECKPOINT_MISMATCH",
        "CHECKPOINT_SIGNATURE_INVALID",
        "CHECKPOINT_BEYOND_LEDGER",
        "CHECKPOINT_TIMESTAMP_INVALID",
        "CHECKPOINT_FILE_INVALID",
    },
    "ski-spec-7.2-timestamp-order": {"TIMESTAMP_ORDER"},
}


def _checks(result: VerificationResult, replay: Optional[dict[str, Any]]) -> list[tuple[str, str, str, bool]]:
    """``(objective id, title, what was observed, satisfied)`` for each check that ran."""
    total = result.hash_verification_total
    issues = {i.issue_type for i in result.issues}
    checks = [
        (
            "ski-spec-7.2-append-only-chain",
            "Hash chain links every entry to its predecessor (spec §7.2)",
            f"{result.chain_link_verified_count} of {total} chain links verified; sequence continuity "
            f"{'intact' if result.chain_continuity else 'broken'}.",
            result.chain_link_verified_count == total and result.chain_continuity,
        ),
        (
            "ski-spec-7.1-entry-hash",
            "Every entry hash recomputes from its stored columns and evidence (spec §7.1)",
            f"{result.entry_hash_verified_count} of {total} entry hashes recomputed.",
            result.entry_hash_verified_count == total
            and not issues & _ISSUES_BY_OBJECTIVE["ski-spec-7.1-entry-hash"],
        ),
        (
            "ski-spec-7.1-verdict-signature",
            "Each format-5 entry carries a valid verdict signature by a pinned key (spec §7.1)",
            f"{result.verdict_signatures_verified} verdict signature(s) verified.",
            not issues & _ISSUES_BY_OBJECTIVE["ski-spec-7.1-verdict-signature"],
        ),
        (
            "ski-spec-7.1-checkpoints",
            "Signed Merkle checkpoints still match the ledger (spec §7.1)",
            f"{result.checkpoints_verified} checkpoint(s) verified, {result.timestamps_verified} RFC 3161 "
            "time-stamp(s) verified.",
            not issues & _ISSUES_BY_OBJECTIVE["ski-spec-7.1-checkpoints"],
        ),
        (
            "ski-spec-7.2-timestamp-order",
            "Entry timestamps are monotonic (spec §7.2)",
            "Timestamps are " + ("monotonic." if result.timestamp_ordering else "out of order."),
            result.timestamp_ordering,
        ),
    ]
    if replay is not None:
        checks.append(
            (
                "ski-spec-8.1-replay",
                "Recorded verdicts replay from their signed transcripts (spec §8.1)",
                f"{replay.get('replayed_entries', 0)} of {replay.get('total_entries', 0)} entries replayed, "
                f"{replay.get('matched_entries', 0)} matched, {len(replay.get('mismatches') or [])} diverged.",
                bool(replay.get("is_clean")),
            )
        )
    return checks


def assessment_results(
    result: VerificationResult,
    *,
    ledger_label: str,
    replay: Optional[dict[str, Any]] = None,
    assessment_plan_href: str = "https://skiframework.org/ns/oscal/assessment-plan/ledger-integrity",
) -> dict[str, Any]:
    """The OSCAL Assessment Results document for ``result`` (and a replay report, as JSON)."""
    when = _ts(result.verification_date)
    run = _uuid("result", ledger_label, when, result.sequence_range)
    observations: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    issue_obs: dict[str, list[str]] = {}
    for issue in result.issues:
        obs_id = _uuid(run, "issue", issue.issue_type, issue.sequence_number, issue.description)
        issue_obs.setdefault(issue.issue_type, []).append(obs_id)
        observations.append(
            {
                "uuid": obs_id,
                "title": f"{issue.issue_type} at sequence {issue.sequence_number}",
                "description": issue.description,
                "props": [
                    _prop("severity", issue.severity.lower()),
                    _prop("sequence-number", issue.sequence_number),
                ],
                "methods": ["TEST"],
                "types": ["finding"],
                "collected": when,
            }
        )
    for objective, title, observed, satisfied in _checks(result, replay):
        obs_id = _uuid(run, "check", objective)
        observations.append(
            {
                "uuid": obs_id,
                "title": title,
                "description": observed,
                "methods": ["TEST"],
                "types": ["control-objective"],
                "collected": when,
            }
        )
        kinds = _ISSUES_BY_OBJECTIVE.get(objective, set())
        related = [obs_id] + [o for kind, ids in issue_obs.items() if kind in kinds for o in ids]
        findings.append(
            {
                "uuid": _uuid(run, "finding", objective),
                "title": title,
                "description": observed,
                "target": {
                    "type": "objective-id",
                    "target-id": objective,
                    "status": {"state": "satisfied" if satisfied else "not-satisfied"},
                },
                "related-observations": [{"observation-uuid": o} for o in dict.fromkeys(related)],
            }
        )
    return {
        "assessment-results": {
            "uuid": _uuid("assessment-results", run),
            "metadata": {
                "title": f"SKI ledger integrity assessment: {ledger_label}",
                "last-modified": when,
                "version": "1",
                "oscal-version": OSCAL_VERSION,
                "props": [_prop("ledger-entries", result.total_entries)],
            },
            "import-ap": {"href": assessment_plan_href},
            "results": [
                {
                    "uuid": run,
                    "title": "audit-ledger verify" + (" and replay" if replay is not None else ""),
                    "description": result.recommendation or "SKI ledger verification.",
                    "start": when,
                    "end": when,
                    "props": [
                        _prop("sequence-range", f"{result.sequence_range[0]}-{result.sequence_range[1]}"),
                        _prop("overall", "pass" if result.is_valid else "fail"),
                    ],
                    "reviewed-controls": {"control-selections": [{"include-all": {}}]},
                    "observations": observations,
                    "findings": findings,
                }
            ],
        }
    }
