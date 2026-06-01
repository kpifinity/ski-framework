"""Tag Registry + Risk-Tier Governor.

The Tag Registry compiled subjects → rule IDs in v2. In v3 the same
package houses the :class:`RiskTierGovernor` (spec §5.4) — the
authoritative source for *which risk tier applies to each
obligation*. The server consults the governor at evaluation time so
callers can never self-downgrade their compliance posture.

The strict-governor rule is enforced at the API boundary: the
``MeasurementRecord`` shape no longer carries a caller-declared
``risk_tier``. The tier is derived from the obligations themselves.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Iterable, Optional

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
    def from_knowledge_graph(cls, kg: Any) -> TagRegistry:
        return cls.from_dict(kg.tag_registry, kg.rules)

    @classmethod
    def from_dict(cls, tag_registry: dict[str, str], rules: list[dict[str, Any]]) -> TagRegistry:
        rule_index = {r.get("id"): r for r in rules if r.get("id")}
        compiled: dict[str, dict[str, Any]] = {}
        for raw_subject, rule_id in tag_registry.items():
            rule = rule_index.get(rule_id)
            if rule is None:
                # KG validators should have caught this. Refuse to silently
                # ignore — a missing rule binding is a KG compilation bug.
                raise ValueError(
                    f"Tag Registry references rule_id {rule_id!r} which is not present in the KG's rule set."
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


# ============================================================================
# Risk-Tier Governor (spec v3.0 §5.4)
# ============================================================================


class RiskTierGovernor:
    """The authoritative source of risk tier per obligation.

    The governor reads each KG rule's optional ``risk_tier`` field and
    answers: *"given this set of obligations applicable to a measurement,
    what is the strictest tier among them?"*

    The strictest tier wins. ``tier-1`` is strictest; ``tier-3`` is the
    most permissive. Rules with no ``risk_tier`` field default to
    ``tier-2`` (the standard tier).

    Strictness:

      tier-1  ≻  tier-2  ≻  tier-3

    Callers cannot influence the governor's verdict — that is the whole
    point of the strict-governor design. A tenant in a tier-1
    jurisdiction cannot send ``risk_tier=tier-3`` to evade the policy.
    """

    DEFAULT_TIER: ClassVar[str] = "tier-2"
    _TIER_RANK: ClassVar[dict[str, int]] = {"tier-1": 1, "tier-2": 2, "tier-3": 3}
    _ALIASES: ClassVar[dict[str, str]] = {
        "tier-1": "tier-1",
        "tier1": "tier-1",
        "high": "tier-1",
        "high-risk": "tier-1",
        "tier-2": "tier-2",
        "tier2": "tier-2",
        "standard": "tier-2",
        "default": "tier-2",
        "tier-3": "tier-3",
        "tier3": "tier-3",
        "low": "tier-3",
        "low-risk": "tier-3",
    }

    @classmethod
    def canonicalise(cls, raw: Any) -> str:
        """Normalise a tier string to ``tier-1`` / ``tier-2`` / ``tier-3``.

        Unknown / missing / non-string inputs collapse to
        :attr:`DEFAULT_TIER`. The aliases ``"high"``, ``"standard"``,
        ``"low"``, etc. are recognised.
        """
        if not isinstance(raw, str):
            return cls.DEFAULT_TIER
        key = raw.strip().lower()
        return cls._ALIASES.get(key, cls.DEFAULT_TIER)

    @classmethod
    def strictest_tier(cls, rules: Iterable[dict[str, Any]]) -> str:
        """The strictest tier across ``rules``; ``DEFAULT_TIER`` when empty.

        Each rule's ``risk_tier`` field (if any) is canonicalised; the
        minimum rank (i.e. the strictest tier) wins. Empty input yields
        the default tier so a runtime with zero applicable obligations
        defaults to the standard policy rather than the permissive one.
        """
        ranks = [cls._TIER_RANK[cls.canonicalise(r.get("risk_tier"))] for r in rules]
        if not ranks:
            return cls.DEFAULT_TIER
        best = min(ranks)
        for tier, rank in cls._TIER_RANK.items():
            if rank == best:
                return tier
        return cls.DEFAULT_TIER  # unreachable

    @classmethod
    def tier_for_snapshot(cls, kg_snapshot: dict[str, Any]) -> str:
        """Convenience: strictest tier across a scoped-KG snapshot's obligations.

        Reads ``kg_snapshot["obligations"]`` (the shape produced by
        :meth:`ski_model.kg_loader.KnowledgeGraph.scope_to`).
        """
        return cls.strictest_tier(kg_snapshot.get("obligations", []))
