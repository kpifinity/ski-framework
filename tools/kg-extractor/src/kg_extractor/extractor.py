"""Compliance-rule extraction from regulatory documents (v0.1.0-alpha).

Phase 1 extractor for the SKI Framework. Key v2.1 changes:

  * Uses an abstract LLM backend (default Ollama). Anthropic and OpenAI
    are available for compilation-phase use only.
  * Temperature is 0 with a recorded seed (B3.4 reproducibility).
  * Refuses to emit rules with `confidence: "IMPLIED"` (B2.1 Anchor
    Constraint). The prompt asks the model not to produce them and the
    parser drops any that slip through, with a warning.
  * Records the prompt SHA-256, seed, model name, and backend in
    extraction metadata so a reproducibility audit can reconstruct the
    run.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

from .backends import ExtractorBackend, build_backend
from .models import ComplianceRule, ConfidenceLevel, ExtractionMetadata, ExtractionResult
from .utils import chunk_text, extract_text_from_document, validate_rule


_PROHIBITED_IMPLIED = "IMPLIED"


class Extractor:
    """Extract compliance rules from regulatory documents."""

    def __init__(
        self,
        backend: Optional[ExtractorBackend] = None,
        sector_default: str = "general",
    ):
        self.backend = backend or build_backend()
        self.sector_default = sector_default

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_from_file(
        self,
        file_path: str,
        sector: Optional[str] = None,
        document_type: str = "regulation",
        source_document_version: Optional[str] = None,
    ) -> ExtractionResult:
        text = extract_text_from_document(file_path)
        document_name = os.path.basename(file_path)
        return self.extract_from_text(
            text=text,
            sector=sector or self.sector_default,
            document_type=document_type,
            source_document=document_name,
            source_document_version=source_document_version,
        )

    def extract_from_text(
        self,
        text: str,
        sector: str = "general",
        document_type: str = "regulation",
        source_document: str = "unknown",
        source_document_version: Optional[str] = None,
    ) -> ExtractionResult:
        start = time.monotonic()
        chunks = chunk_text(text, max_chunk_size=4000, overlap=200)

        rules: List[ComplianceRule] = []
        warnings: List[str] = []
        last_call = None

        for i, chunk in enumerate(chunks):
            try:
                chunk_rules, call_info = self._extract_from_chunk(
                    chunk=chunk,
                    sector=sector,
                    document_type=document_type,
                    source_document=source_document,
                    source_document_version=source_document_version,
                    chunk_index=i,
                )
                rules.extend(chunk_rules)
                last_call = call_info
            except Exception as exc:
                warnings.append(f"Chunk {i} failed: {exc!r}")

        rules = self._deduplicate(rules)

        confidence_counts: dict[str, int] = {}
        for r in rules:
            confidence_counts[r.confidence] = confidence_counts.get(r.confidence, 0) + 1

        metadata = ExtractionMetadata(
            document_name=source_document,
            document_type=document_type,
            sector=sector,
            extraction_timestamp=datetime.now(timezone.utc).isoformat(),
            total_rules_extracted=len(rules),
            rules_by_confidence=confidence_counts,
            extraction_duration_seconds=time.monotonic() - start,
            backend=self.backend.name,
            model_used=self.backend.model,
            model_file_sha256=os.getenv("KG_EXTRACTOR_MODEL_FILE_SHA256"),
            temperature=last_call.temperature if last_call else 0.0,
            seed=last_call.seed if last_call else None,
            prompt_sha256=last_call.prompt_sha256 if last_call else None,
        )

        return ExtractionResult(rules=rules, metadata=metadata, warnings=warnings)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_from_chunk(
        self,
        *,
        chunk: str,
        sector: str,
        document_type: str,
        source_document: str,
        source_document_version: Optional[str],
        chunk_index: int,
    ) -> tuple[List[ComplianceRule], "object"]:
        prompt = self._build_prompt(chunk, sector, document_type, source_document, source_document_version)

        call = self.backend.extract_json(prompt=prompt, max_tokens=2000)

        try:
            extracted = json.loads(call.text)
            if not isinstance(extracted, list):
                # Some backends wrap in an object — accept {"rules": [...]} too.
                if isinstance(extracted, dict) and isinstance(extracted.get("rules"), list):
                    extracted = extracted["rules"]
                else:
                    raise ValueError("expected a JSON array of rules")
        except json.JSONDecodeError as exc:
            raise ValueError(f"backend returned non-JSON: {exc}; first 200 chars: {call.text[:200]!r}")

        rules: List[ComplianceRule] = []
        for i, rule_data in enumerate(extracted):
            confidence_raw = (rule_data.get("confidence") or "").upper()
            if confidence_raw == _PROHIBITED_IMPLIED:
                # Drop the rule; surface as a warning.
                rules.append(
                    ComplianceRule(
                        id=f"rule_{chunk_index}_{i}_REJECTED",
                        subject=rule_data.get("subject", ""),
                        relation=rule_data.get("relation", ""),
                        object=rule_data.get("object", ""),
                        source_document=source_document,
                        source_clause=rule_data.get("source_clause", "general"),
                        source_document_version=source_document_version,
                        confidence=ConfidenceLevel.DISCRETIONARY,
                        reasoning=(
                            "Originally extracted as IMPLIED. The Anchor Constraint "
                            "(B2.1) prohibits IMPLIED rules; downgraded to DISCRETIONARY "
                            "and flagged for human review. "
                            f"Original reasoning: {rule_data.get('reasoning', '')!r}"
                        ),
                    )
                )
                continue

            try:
                rule = ComplianceRule(
                    id=rule_data.get("id") or f"rule_{chunk_index}_{i}",
                    subject=rule_data.get("subject", ""),
                    relation=rule_data.get("relation", ""),
                    object=rule_data.get("object", ""),
                    source_document=source_document,
                    source_clause=rule_data.get("source_clause", "general"),
                    source_document_version=source_document_version,
                    confidence=ConfidenceLevel(confidence_raw or "DISCRETIONARY"),
                    reasoning=rule_data.get("reasoning", ""),
                    effective_date=rule_data.get("effective_date"),
                    sunset_date=rule_data.get("sunset_date"),
                )
            except ValueError as exc:
                # Pydantic / enum coercion failure → skip with a warning.
                continue
            if validate_rule(rule):
                rules.append(rule)

        return rules, call

    def _build_prompt(
        self,
        chunk: str,
        sector: str,
        document_type: str,
        source_document: str,
        source_document_version: Optional[str],
    ) -> str:
        return (
            "You are extracting compliance obligations from a regulatory document.\n"
            "Return STRICT JSON ONLY — a single JSON ARRAY of rule objects, no prose.\n"
            "\n"
            "Each rule object has these keys:\n"
            '  subject (string), relation (string), object (string),\n'
            '  confidence ("EXPLICIT" or "DISCRETIONARY" or "CONFLICTING"),\n'
            '  reasoning (string), source_clause (string).\n'
            "\n"
            "ABSOLUTE RULES (will be enforced by post-processing):\n"
            "  1. Do NOT emit `confidence: \"IMPLIED\"`. The Anchor Constraint (B2.1) "
            "     prohibits inference beyond source text. Rules that require inference "
            "     must be marked DISCRETIONARY so a human can decide.\n"
            "  2. For EXPLICIT rules, include a verbatim quote from the source in `reasoning`.\n"
            "  3. If the chunk does not contain any compliance obligations, return [].\n"
            "\n"
            f"Sector: {sector}\n"
            f"Document type: {document_type}\n"
            f"Source: {source_document}\n"
            f"Source version: {source_document_version or 'unknown'}\n"
            "\n"
            "Document chunk:\n"
            f"{chunk}\n"
        )

    @staticmethod
    def _deduplicate(rules: List[ComplianceRule]) -> List[ComplianceRule]:
        seen: set[tuple[str, str, str]] = set()
        out: List[ComplianceRule] = []
        for r in rules:
            sig = (r.subject.lower(), r.relation.lower(), r.object.lower())
            if sig in seen:
                continue
            seen.add(sig)
            out.append(r)
        return out
