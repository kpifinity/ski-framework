"""Wrap an :class:`ExtractionResult` into a v3 KG dict.

The extractor's flat rule list (subject / relation / object plus a
verbatim source quote) maps cleanly into the v3 typed-graph shape
defined by spec v3.0 §3. Each flat rule produces:

* one ``Rule`` node carrying the risk tier;
* one ``Obligation`` node carrying the typed relation and operand;
* one ``Subject`` node (deduplicated across rules in the same run);
* a ``Citation`` node anchored at the source quote;
* one ``Jurisdiction`` node (shared by every rule in the run);
* the edges ``rule → subject (applies_to)``, ``rule → obligation
  (consists_of)``, ``rule → jurisdiction (scoped_to)``, and
  ``rule → citation (cited_by)``.

This is a deliberate, low-fidelity wrap (PR 10e). It gets the tool
producing v3 KGs *today*. A follow-up PR will improve fidelity by
asking the LLM to emit typed obligations directly so we no longer
have to guess the ``ObligationType`` from a string ``relation``.

Defaults applied when the extractor cannot determine the value:

* ``risk_tier`` — ``medium`` (the strict-governor's default tier).
* ``effective_date_start`` — the rule's own ``effective_date`` if
  present, otherwise the run's extraction timestamp.
* ``ObligationType`` — guessed from ``relation`` via the lookup
  table below; unknown relations fall back to ``DISCRETIONARY`` so
  the runtime routes them to human review rather than silently
  approving.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import ExtractionQuality, ExtractionResult

# Map the extractor's free-text ``relation`` to a spec §3.3 obligation
# type. Keys are lowercase substrings; the first match wins.
_RELATION_TO_OBLIGATION_TYPE: List[tuple[str, str]] = [
    ("must_not_exceed", "must_not_exceed"),
    ("not_to_exceed", "must_not_exceed"),
    ("cannot_exceed", "must_not_exceed"),
    ("must_be_at_least", "must_be_at_least"),
    ("at_least", "must_be_at_least"),
    ("must_be_below", "must_be_below"),
    ("must_be_above", "must_be_above"),
    ("must_be_within", "must_be_within"),
    ("within", "must_be_within"),
    ("must_be_one_of", "must_be_one_of"),
    ("must_not_be_one_of", "must_not_be_one_of"),
    ("must_be_recorded_within", "must_be_recorded_within"),
    ("must_not", "must_not"),
    ("must", "must"),
    ("should", "should"),
]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _node_version(payload: Dict[str, Any]) -> str:
    """Content-address a node by SHA-256 of its canonical body."""
    body = {k: v for k, v in payload.items() if k != "version"}
    canonical = repr(sorted(body.items()))
    return f"sha256:{_sha(canonical)}"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", ".", s.lower()).strip(".") or "unknown"


def _guess_obligation_type(relation: str) -> str:
    rel = relation.lower().strip()
    for needle, ob_type in _RELATION_TO_OBLIGATION_TYPE:
        if needle in rel:
            return ob_type
    # Unknown relation → push to a discretionary obligation so the
    # runtime emits DISCRETIONARY rather than silently approving.
    return "discretionary"


def _value_from_object(obj: str) -> Any:
    """Try to lift a numeric payload out of an ``object`` string.

    Examples:
      ``"100 ppm"`` → ``100`` (the unit moves to the obligation's
      ``unit`` field via :func:`_unit_from_object`).
      ``"two business days"`` → ``"two business days"`` (no lift).
    """
    m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)\s*[a-zA-Z%/]*\s*$", obj)
    if not m:
        return obj
    raw = m.group(1)
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return obj


def _unit_from_object(obj: str) -> str | None:
    m = re.match(r"\s*[-+]?\d+(?:\.\d+)?\s*([a-zA-Z%/]+)\s*$", obj)
    return m.group(1) if m else None


def emit_v3_kg(
    result: ExtractionResult,
    *,
    jurisdiction: str = "global",
    jurisdiction_name: str | None = None,
    sector: str | None = None,
) -> Dict[str, Any]:
    """Build a v3 KG dict from an extraction run.

    The returned dict matches the on-disk v3 KG shape (see
    ``kg_validator.loader``); pass it straight to
    ``kg-validator validate`` to lint.
    """
    juris_id = _slug(jurisdiction)
    juris_name = jurisdiction_name or jurisdiction or "global"
    eff_ts = result.metadata.extraction_timestamp or datetime.now(timezone.utc).isoformat()

    jurisdiction_node = {
        "id": juris_id,
        "type": "Jurisdiction",
        "version": "",
        "name": juris_name,
    }
    jurisdiction_node["version"] = _node_version(jurisdiction_node)

    subjects: Dict[str, Dict[str, Any]] = {}
    rules_out: List[Dict[str, Any]] = []
    obligations_out: List[Dict[str, Any]] = []
    citations_out: List[Dict[str, Any]] = []
    edges_out: List[Dict[str, Any]] = []

    for rule in result.rules:
        subj_id = f"subj.{_slug(rule.subject)}"
        if subj_id not in subjects:
            subj = {
                "id": subj_id,
                "type": "Subject",
                "version": "",
                "name": rule.subject,
            }
            subj["version"] = _node_version(subj)
            subjects[subj_id] = subj

        rule_id = f"rule.{_slug(rule.id)}"
        obligation_id = f"ob.{_slug(rule.id)}"
        citation_id = f"cite.{_slug(rule.id)}"

        rule_node = {
            "id": rule_id,
            "type": "Rule",
            "version": "",
            "name": f"{rule.subject} {rule.relation} {rule.object}",
            "risk_tier": "medium",
            "description": rule.reasoning or None,
        }
        rule_node["version"] = _node_version(rule_node)
        rules_out.append(rule_node)

        obligation_node = {
            "id": obligation_id,
            "type": "Obligation",
            "version": "",
            "obligation_type": _guess_obligation_type(rule.relation),
            "metric": _slug(rule.subject),
            "value": _value_from_object(rule.object),
            "unit": _unit_from_object(rule.object),
            "effective_date_start": rule.effective_date or eff_ts,
            "effective_date_end": rule.sunset_date,
            "summary": f"{rule.relation} {rule.object}",
        }
        obligation_node["version"] = _node_version(obligation_node)
        obligations_out.append(obligation_node)

        citation_node = {
            "id": citation_id,
            "type": "Citation",
            "version": "",
            "source_document": rule.source_document,
            "source_clause": rule.source_clause,
            "url": None,
        }
        citation_node["version"] = _node_version(citation_node)
        citations_out.append(citation_node)

        edges_out.extend(
            [
                {"type": "applies_to", "from": rule_id, "to": subj_id},
                {"type": "consists_of", "from": rule_id, "to": obligation_id},
                {"type": "scoped_to", "from": rule_id, "to": juris_id},
                {"type": "cited_by", "from": rule_id, "to": citation_id},
            ]
        )

    metadata = {
        "name": result.metadata.document_name or "extracted-kg",
        "schema_version": "3.0",
        "sector": sector or result.metadata.sector or None,
        "description": (
            f"Extracted from {result.metadata.document_name} by kg-extractor "
            f"{result.metadata.extractor_version} via {result.metadata.backend}."
        ),
        "compiled_at": eff_ts,
        "extraction_quality_summary": {
            q.value: result.metadata.rules_by_quality.get(q.value, 0) for q in ExtractionQuality
        },
        "warnings": result.warnings,
    }

    return {
        "metadata": metadata,
        "nodes": {
            "subjects": list(subjects.values()),
            "rules": rules_out,
            "obligations": obligations_out,
            "definitions": [],
            "exemptions": [],
            "precedents": [],
            "jurisdictions": [jurisdiction_node],
            "citations": citations_out,
        },
        "edges": edges_out,
    }
