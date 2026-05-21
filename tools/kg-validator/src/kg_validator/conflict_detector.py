"""
Conflict and duplicate detection logic
"""

from typing import List, Tuple
from rapidfuzz import fuzz
from .models import ComplianceRule, ConflictPair, DuplicatePair


class ConflictDetector:
    """Detect conflicts between rules"""

    @staticmethod
    def detect_conflicts(rules: List[ComplianceRule]) -> List[ConflictPair]:
        """
        Detect conflicting rules

        Args:
            rules: List of rules to check

        Returns:
            List of conflicting rule pairs
        """
        conflicts = []

        for i, rule1 in enumerate(rules):
            for rule2 in rules[i + 1 :]:
                conflict = ConflictDetector._check_conflict(rule1, rule2)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    @staticmethod
    def _check_conflict(rule1: ComplianceRule, rule2: ComplianceRule) -> Tuple[bool, dict]:
        """Check if two rules conflict"""

        # Only check rules with same subject-relation pair
        if (rule1.subject.lower() != rule2.subject.lower() or
            rule1.relation.lower() != rule2.relation.lower()):
            return None

        # Check for contradictory objects
        obj1 = rule1.object.lower()
        obj2 = rule2.object.lower()

        # Exact contradictions
        if _is_contradictory(obj1, obj2):
            return ConflictPair(
                rule_id_1=rule1.id,
                rule_id_2=rule2.id,
                conflict_type="CONTRADICTORY",
                explanation=f"Rules specify conflicting limits: '{rule1.object}' vs '{rule2.object}'",
                similarity_score=1.0,
            )

        # Date overlap conflicts
        conflict_dates = _check_date_conflict(rule1, rule2)
        if conflict_dates:
            return conflict_dates

        return None

    @staticmethod
    def detect_duplicates(
        rules: List[ComplianceRule], threshold: float = 0.85
    ) -> List[DuplicatePair]:
        """
        Detect duplicate or near-duplicate rules

        Args:
            rules: List of rules to check
            threshold: Similarity threshold (0-1)

        Returns:
            List of duplicate rule pairs
        """
        duplicates = []

        for i, rule1 in enumerate(rules):
            for rule2 in rules[i + 1 :]:
                duplicate = ConflictDetector._check_duplicate(rule1, rule2, threshold)
                if duplicate:
                    duplicates.append(duplicate)

        return duplicates

    @staticmethod
    def _check_duplicate(
        rule1: ComplianceRule, rule2: ComplianceRule, threshold: float
    ) -> DuplicatePair:
        """Check if two rules are duplicates"""

        # Create signatures for comparison
        sig1 = f"{rule1.subject} {rule1.relation} {rule1.object}".lower()
        sig2 = f"{rule2.subject} {rule2.relation} {rule2.object}".lower()

        # Check exact match
        if sig1 == sig2:
            return DuplicatePair(
                rule_id_1=rule1.id,
                rule_id_2=rule2.id,
                similarity_score=1.0,
                duplicate_type="EXACT",
            )

        # Check semantic similarity
        similarity = fuzz.ratio(sig1, sig2) / 100.0

        if similarity >= threshold:
            if similarity > 0.95:
                dup_type = "SEMANTIC"
            else:
                dup_type = "NEAR_DUPLICATE"

            return DuplicatePair(
                rule_id_1=rule1.id,
                rule_id_2=rule2.id,
                similarity_score=similarity,
                duplicate_type=dup_type,
            )

        return None


def _is_contradictory(obj1: str, obj2: str) -> bool:
    """Check if two objects are contradictory"""

    # Extract numeric values if present
    import re

    nums1 = re.findall(r"\d+", obj1)
    nums2 = re.findall(r"\d+", obj2)

    if nums1 and nums2:
        # Check for exclusive upper bounds
        if ("max" in obj1 or "below" in obj1 or "not exceed" in obj1) and \
           ("max" in obj2 or "below" in obj2 or "not exceed" in obj2):
            max1 = max(int(n) for n in nums1)
            max2 = max(int(n) for n in nums2)
            # If one is significantly different, it's contradictory
            if abs(max1 - max2) / max(max1, max2) > 0.3:
                return True

    return False


def _check_date_conflict(rule1: ComplianceRule, rule2: ComplianceRule) -> ConflictPair:
    """Check if rules have conflicting effective/expiration dates"""

    if not (rule1.effective_date and rule2.effective_date):
        return None

    try:
        from datetime import datetime

        date1_eff = datetime.fromisoformat(rule1.effective_date)
        date2_eff = datetime.fromisoformat(rule2.effective_date)

        # If effective dates are different but rules conflict on content
        if date1_eff != date2_eff:
            exp1 = (
                datetime.fromisoformat(rule1.expiration_date)
                if rule1.expiration_date
                else None
            )
            exp2 = (
                datetime.fromisoformat(rule2.expiration_date)
                if rule2.expiration_date
                else None
            )

            # Check if there's overlap
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
    """Check if two date ranges overlap"""
    if end1 and start2 > end1:
        return False
    if end2 and start1 > end2:
        return False
    return True
