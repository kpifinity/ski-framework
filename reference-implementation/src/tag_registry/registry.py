"""Tag Registry implementation."""

from __future__ import annotations

import re
from typing import Any, Optional


_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(subject: str) -> str:
    return _WHITESPACE_RE.sub(" ", subject.strip().lower())


class TagRegistry:
    """Immutable subject → rule lookup compiled from a signed KG.

    The constructor is private-ish; use `TagRegistry.from_knowledge_graph(kg)`
    or `TagRegistry.from_dict(kg.tag_registry, kg.rules)`.
    """

    def __init__(self, mapping: dict[str, dict[str, Any]]):
        # Copy and freeze the mapping to discourage runtime mutation.
        self._mapping = dict(mapping)

    @classmethod
    def from_knowledge_graph(cls, kg: Any) -> "TagRegistry":
        return cls.from_dict(kg.tag_registry, kg.rules)

    @classmethod
    def from_dict(
        cls, tag_registry: dict[str, str], rules: list[dict[str, Any]]
    ) -> "TagRegistry":
        rule_index = {r.get("id"): r for r in rules if r.get("id")}
        compiled: dict[str, dict[str, Any]] = {}
        for raw_subject, rule_id in tag_registry.items():
            rule = rule_index.get(rule_id)
            if rule is None:
                # KG validators should have caught this. Refuse to silently
                # ignore — a missing rule binding is a KG compilation bug.
                raise ValueError(
                    f"Tag Registry references rule_id {rule_id!r} which is "
                    f"not present in the KG's rule set."
                )
            compiled[_normalise(raw_subject)] = rule
        return cls(compiled)

    def resolve(self, subject: str) -> Optional[dict[str, Any]]:
        """Pure lookup. Returns the rule dict, or None if unmapped."""
        return self._mapping.get(_normalise(subject))

    def __contains__(self, subject: str) -> bool:
        return _normalise(subject) in self._mapping

    def __len__(self) -> int:
        return len(self._mapping)

    def subjects(self) -> list[str]:
        return list(self._mapping.keys())
