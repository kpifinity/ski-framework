"""
Conflict and duplicate detection logic.

v0.2.1: ``_is_contradictory`` now considers the shared ``relation`` field
when deciding whether two same-subject rules disagree on a numeric
threshold. Pre-v0.2.1, conflict detection only fired when the object
string itself contained keywords like "max"/"below"/"not exceed", which
missed objects like "100 ppm sulfur dioxide" under "must_not_exceed".
"""

from typing import List, Tuple

from rapidfuzz import fuzz

from .models import ComplianceRule, ConflictPair, DuplicatePair


class ConflictDetector:
    """Detect conflicts between rules"""

    @staticmethod
    def detect_conflicts(rules: List[ComplianceRule]) -> List[ConflictPair]:
        conflicts = []
        for i, rule1 in enumerate(rules):
            for rule2 in rules[i + 1 :]:
                conflict = ConflictDetector._check_conflict(rule1, rule2)
                if conflict:
                    conflicts.append(conflict)
        return conflicts

    @staticmethod
    def _check_conflict(rule1: ComplianceRule, rule2: ComplianceRule) -> Tuple[bool, dict]:
        if rule1.subject.lower() != rule2.subject.lower() or rule1.relation.lower() != rule2.relation.lower():
            return None
        obj1 = rule1.object.lower()
        obj2 = rule2.object.lower()
        if _is_contradictory(obj1, obj2, relation=rule1.relation):
            return ConflictPair(
                rule_id_1=rule1.id,
                rule_id_2=rule2.id,
                conflict_type="CONTRADICTORY",
                explanation=f"Rules specify conflicting limits: '{rule1.object}' vs '{rule2.object}'",
                similarity_score=1.0,
            )
        conflict_dates = _check_date_conflict(rule1, rule2)
        if conflict_dates:
            return conflict_dates
        return None

    @staticmethod
    def detect_duplicates(rules: List[ComplianceRule], threshold: float = 0.85) -> List[DuplicatePair]:
        duplicates = []
        for i, rule1 in enumerate(rules):
            for rule2 in rules[i + 1 :]:
                duplicate = ConflictDetector._check_duplicate(rule1, rule2, threshold)
                if duplicate:
                    duplicates.append(duplicate)
        return duplicates

    @staticmethod
    def _check_duplicate(rule1: ComplianceRule, rule2: ComplianceRule, threshold: float) -> DuplicatePair:
        sig1 = f"{rule1.subject} {rule1.relation} {rule1.object}".lower()
        sig2 = f"{rule2.subject} {rule2.relation} {rule2.object}".lower()
        if sig1 == sig2:
            return DuplicatePair(
                rule_id_1=rule1.id, rule_id_2=rule2.id, similarity_score=1.0, duplicate_type="EXACT"
            )
        similarity = fuzz.ratio(sig1, sig2) / 100.0
        if similarity >= threshold:
            dup_type = "SEMANTIC" if similarity > 0.95 else "NEAR_DUPLICATE"
            return DuplicatePair(
                rule_id_1=rule1.id, rule_id_2=rule2.id, similarity_score=similarity, duplicate_type=dup_type
            )
        return None


_BOUND_RELATION_KEYWORDS = (
    "exceed",
    "below",
    "above",
    "under",
    "over",
    "at_most",
    "at_least",
    "no_more_than",
    "no_less_than",
    "not_to_exceed",
    "not_exceed",
    "must_be",
    "must_equal",
)
_OBJECT_BOUND_KEYWORDS = ("max", "below", "above", "not exceed", "at most", "at least")


def _is_contradictory(obj1: str, obj2: str, relation: str = "") -> bool:
    """Detect contradictory objects given the shared relation.

    Case 1 - relation-driven bound: ``must_not_exceed``, ``must_be_below``,
    ``must_be_at_least``, etc. Different numeric thresholds = conflict.

    Case 2 - object-driven bound (legacy): both object strings mention
    max/below/not-exceed and differ by more than 30%.
    """
    import re

    nums1 = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", obj1)]
    nums2 = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", obj2)]
    if not (nums1 and nums2):
        return False

    relation_norm = (relation or "").lower().replace(" ", "_")
    relation_is_bound = any(kw in relation_norm for kw in _BOUND_RELATION_KEYWORDS)

    if relation_is_bound and max(nums1) != max(nums2):
        return True

    if any(kw in obj1 for kw in _OBJECT_BOUND_KEYWORDS) and any(kw in obj2 for kw in _OBJECT_BOUND_KEYWORDS):
        max1, max2 = max(nums1), max(nums2)
        if max1 > 0 and max2 > 0 and abs(max1 - max2) / max(max1, max2) > 0.3:
            return True

    return False


def _check_date_conflict(rule1: ComplianceRule, rule2: ComplianceRule) -> ConflictPair:
    if not (rule1.effective_date and rule2.effective_date):
        return None
    try:
        from datetime import datetime

        date1_eff = datetime.fromisoformat(rule1.effective_date)
        date2_eff = datetime.fromisoformat(rule2.effective_date)
        if date1_eff != date2_eff:
            exp1 = datetime.fromisoformat(rule1.expiration_date) if rule1.expiration_date else None
            exp2 = datetime.fromisoformat(rule2.expiration_date) if rule2.expiration_date else None
            if _dates_overlap(date1_eff, exp1, date2_eff, exp2):
                return ConflictPair(
                    rule_id_1=rule1.id,
                    rule_id_2=rule2.id,
                    conflict_type="DATE_OVERLAP",
                    explanation=f"Rules have overlapping effective dates: "
                    f"{rule1.effective_date} to {rule1.expiration_date or 'ongoing'} "
                    f"and {rule2.effective_date} to {rule2.expiration_date or 'ongoing'}",
                    similarity_score=1.0,
                )
    except (ValueError, AttributeError):
        pass
    return None


def _dates_overlap(start1, end1, start2, end2) -> bool:
    if end1 and start2 > end1:
        return False
    return not (end2 and start1 > end2)
