"""
Core extraction logic for compliance rules
"""

import json
import os
import time
from typing import List, Dict, Optional
from datetime import datetime
import anthropic

from .models import ComplianceRule, ExtractionResult, ExtractionMetadata, ConfidenceLevel
from .utils import extract_text_from_document, chunk_text, validate_rule


class Extractor:
    """Extract compliance rules from regulatory documents"""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-opus-4-6"):
        """
        Initialize extractor

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment or parameters")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model

    def extract_from_file(
        self,
        file_path: str,
        sector: str = "general",
        document_type: str = "regulation",
    ) -> ExtractionResult:
        """
        Extract rules from a file

        Args:
            file_path: Path to document file
            sector: Industry sector (energy, finance, manufacturing, defense)
            document_type: Type of document (regulation, guidance, standard)

        Returns:
            ExtractionResult with extracted rules
        """
        start_time = time.time()

        # Extract text from document
        text = extract_text_from_document(file_path)
        document_name = os.path.basename(file_path)

        # Extract rules
        result = self.extract_from_text(
            text=text,
            sector=sector,
            document_type=document_type,
            source_document=document_name,
        )

        # Add duration
        result.metadata.extraction_duration_seconds = time.time() - start_time

        return result

    def extract_from_text(
        self,
        text: str,
        sector: str = "general",
        document_type: str = "regulation",
        source_document: str = "unknown",
    ) -> ExtractionResult:
        """
        Extract rules from text

        Args:
            text: Document text to extract rules from
            sector: Industry sector
            document_type: Type of document
            source_document: Name of source document

        Returns:
            ExtractionResult with extracted rules
        """
        start_time = time.time()

        # Chunk text for processing
        chunks = chunk_text(text, max_chunk_size=4000, overlap=200)

        rules = []
        warnings = []

        # Process each chunk
        for i, chunk in enumerate(chunks):
            try:
                chunk_rules = self._extract_from_chunk(
                    chunk=chunk,
                    sector=sector,
                    document_type=document_type,
                    source_document=source_document,
                    chunk_index=i,
                )
                rules.extend(chunk_rules)
            except Exception as e:
                warning = f"Failed to process chunk {i}: {str(e)}"
                warnings.append(warning)

        # Deduplicate and validate rules
        rules = self._deduplicate_rules(rules)

        # Count by confidence
        confidence_counts = {}
        for rule in rules:
            level = rule.confidence
            confidence_counts[level] = confidence_counts.get(level, 0) + 1

        # Create metadata
        metadata = ExtractionMetadata(
            document_name=source_document,
            document_type=document_type,
            sector=sector,
            extraction_timestamp=datetime.utcnow().isoformat() + "Z",
            total_rules_extracted=len(rules),
            rules_by_confidence=confidence_counts,
            extraction_duration_seconds=time.time() - start_time,
            model_used=self.model,
        )

        return ExtractionResult(
            rules=rules,
            metadata=metadata,
            warnings=warnings,
        )

    def _extract_from_chunk(
        self,
        chunk: str,
        sector: str,
        document_type: str,
        source_document: str,
        chunk_index: int,
    ) -> List[ComplianceRule]:
        """Extract rules from a text chunk using Claude"""

        prompt = f"""You are an expert at extracting compliance rules from regulatory documents.

Extract all compliance obligations from this regulatory document chunk. For each rule, identify:
1. Subject: What entity is being regulated (e.g., "Facility discharge", "Transaction", "Equipment")
2. Relation: The compliance obligation (e.g., "must_be_within", "must_report", "must_maintain")
3. Object: The specific requirement or limit (e.g., "100 ppm", "within 48 hours", "daily")

Context:
- Sector: {sector}
- Document Type: {document_type}
- Source: {source_document}
- Chunk: {chunk_index}

For EACH rule you identify:
- Determine confidence level:
  * EXPLICIT: Rule is clearly and directly stated
  * IMPLIED: Rule is inferred from multiple related statements
  * DISCRETIONARY: Rule is ambiguous or has multiple interpretations
  * CONFLICTING: Rule conflicts with other rules in the document

- If confidence is EXPLICIT: Include the exact quote from the source
- If confidence is DISCRETIONARY or CONFLICTING: Explain the ambiguity

Return ONLY a valid JSON array with no additional text. Each object should have:
- subject (string)
- relation (string)
- object (string)
- confidence (EXPLICIT|IMPLIED|DISCRETIONARY|CONFLICTING)
- reasoning (string explaining the extraction)
- source_clause (string: specific clause/section reference if available, or "general")

Example format:
[
  {{
    "subject": "Wastewater discharge",
    "relation": "must_not_exceed",
    "object": "100 ppm sulfur dioxide",
    "confidence": "EXPLICIT",
    "reasoning": "Section 112(b)(1) explicitly states: 'sulfur dioxide emissions shall not exceed 100 ppm'",
    "source_clause": "Section 112(b)(1)"
  }}
]

Document chunk:
{chunk}
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0.3,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            # Parse response
            response_text = response.content[0].text
            extracted = json.loads(response_text)

            # Convert to ComplianceRule objects
            rules = []
            for i, rule_data in enumerate(extracted):
                rule = ComplianceRule(
                    id=f"rule_{chunk_index}_{i}",
                    subject=rule_data.get("subject", ""),
                    relation=rule_data.get("relation", ""),
                    object=rule_data.get("object", ""),
                    source_document=source_document,
                    source_clause=rule_data.get("source_clause", "general"),
                    confidence=rule_data.get("confidence", "DISCRETIONARY"),
                    reasoning=rule_data.get("reasoning", ""),
                )

                # Validate rule
                if validate_rule(rule):
                    rules.append(rule)

            return rules

        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse Claude response as JSON: {str(e)}")

    def _deduplicate_rules(self, rules: List[ComplianceRule]) -> List[ComplianceRule]:
        """Remove duplicate rules"""
        seen = set()
        deduplicated = []

        for rule in rules:
            # Create a signature for comparison
            signature = (rule.subject.lower(), rule.relation.lower(), rule.object.lower())
            if signature not in seen:
                seen.add(signature)
                deduplicated.append(rule)

        return deduplicated
