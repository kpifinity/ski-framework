"""Loader for v3 KG JSON files.

The on-disk v3 KG format is:

    {
      "metadata": {"name": "...", "schema_version": "3.0", ...},
      "nodes": {
        "subjects": [...], "rules": [...], "obligations": [...],
        "definitions": [...], "exemptions": [...], "precedents": [...],
        "jurisdictions": [...], "citations": [...]
      },
      "edges": [
        {"type": "applies_to", "from": "...", "to": "..."},
        ...
      ]
    }

Each node array contains objects matching the corresponding Pydantic
model in :mod:`.models`. Edges use ``from`` / ``to`` keys; the
:class:`Edge` model declares aliases so the keys can be used directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    Citation,
    Definition,
    Edge,
    Exemption,
    Jurisdiction,
    Obligation,
    Precedent,
    Rule,
    Subject,
)


class KGV3Metadata(BaseModel):
    """KG-level metadata (informative; not used in validation passes)."""

    name: str
    schema_version: str = "3.0"
    sector: Optional[str] = None
    description: Optional[str] = None
    compiled_at: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class KGV3Nodes(BaseModel):
    """Container for all node arrays. All keys default to empty lists."""

    subjects: List[Subject] = Field(default_factory=list)
    rules: List[Rule] = Field(default_factory=list)
    obligations: List[Obligation] = Field(default_factory=list)
    definitions: List[Definition] = Field(default_factory=list)
    exemptions: List[Exemption] = Field(default_factory=list)
    precedents: List[Precedent] = Field(default_factory=list)
    jurisdictions: List[Jurisdiction] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class KnowledgeGraphV3(BaseModel):
    """Top-level v3 KG container."""

    metadata: KGV3Metadata
    nodes: KGV3Nodes = Field(default_factory=KGV3Nodes)
    edges: List[Edge] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def all_node_ids(self) -> Dict[str, str]:
        """Map every node id to its type name. Useful for edge validation."""
        out: Dict[str, str] = {}
        for n in self.nodes.subjects:
            out[n.id] = "Subject"
        for n in self.nodes.rules:
            out[n.id] = "Rule"
        for n in self.nodes.obligations:
            out[n.id] = "Obligation"
        for n in self.nodes.definitions:
            out[n.id] = "Definition"
        for n in self.nodes.exemptions:
            out[n.id] = "Exemption"
        for n in self.nodes.precedents:
            out[n.id] = "Precedent"
        for n in self.nodes.jurisdictions:
            out[n.id] = "Jurisdiction"
        for n in self.nodes.citations:
            out[n.id] = "Citation"
        return out


def load_v3_kg(path: str) -> KnowledgeGraphV3:
    """Load and validate the Pydantic shape of a v3 KG JSON file.

    Raises :class:`pydantic.ValidationError` if the file does not
    conform to the schema. Returns the parsed :class:`KnowledgeGraphV3`
    on success.

    Schema-level validity is necessary but not sufficient. Run
    :class:`kg_validator.v3.V3Validator` against the loaded KG to
    surface the cross-cutting issues from spec §3.6.
    """
    text = Path(path).read_text(encoding="utf-8")
    raw: Any = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError(f"Top-level JSON in {path} must be an object, got {type(raw).__name__}")
    return KnowledgeGraphV3.model_validate(raw)
