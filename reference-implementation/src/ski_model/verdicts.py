"""Verdict taxonomy — five verdicts per SKI Framework v2.1.

The previous specification (v2.0) defined four verdicts: CLEAR, FLAG, NULL,
DISCRETIONARY. v2.1 splits NULL into two semantically distinct verdicts:

  NULL_UNMAPPED — Telemetry was received but no Knowledge Graph rule was
                  mapped to its tag via the Tag Registry. This is a coverage
                  gap and must be logged in the Coverage Register.

  NULL_STALE    — A rule was matched, but the most recent telemetry required
                  by the rule's time-window predicate has expired. This is
                  a freshness gap.

Confidence levels and probabilistic scores are PROHIBITED (B3.1).
"""

from enum import Enum


class Verdict(str, Enum):
    """The five canonical SKI verdicts (v2.1)."""

    CLEAR = "CLEAR"
    FLAG = "FLAG"
    NULL_UNMAPPED = "NULL_UNMAPPED"
    NULL_STALE = "NULL_STALE"
    DISCRETIONARY = "DISCRETIONARY"


# Set of verdicts considered "null-like" for reporting aggregation.
NULL_VERDICTS = frozenset({Verdict.NULL_UNMAPPED, Verdict.NULL_STALE})

# Verdicts requiring human review/escalation.
ESCALATING_VERDICTS = frozenset({Verdict.FLAG, Verdict.DISCRETIONARY})
