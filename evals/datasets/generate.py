"""Generate the finance and manufacturing eval datasets (KG + golden cases).

``python -m evals.datasets.generate`` rewrites ``evals/datasets/{finance,manufacturing}/``;
``--check`` fails if the committed files differ from what it would write
(CI runs that, so the files and this script cannot drift).

How the labels are made, stated plainly: each sector is a table of
obligations (below). For every obligation the generator emits readings on
both sides of its threshold, at the threshold itself, and silent-sensor
readings; each label follows from the predicate's definition in spec §3.3
(``must_not_exceed`` is inclusive, ``must_be_at_least`` is inclusive,
``must_be_within`` is closed) and the scoping rules of spec §3.4 / §5.1
(jurisdiction, effective-date interval). Labels are computed by this
script's own small predicate table, never by the reference implementation.
The energy dataset is hand-labelled and is not touched here.

All thresholds are illustrative, not regulatory citations.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
NOW = "2026-06-15T12:00:00Z"
FUTURE_START, AFTER_FUTURE = "2026-09-01T00:00:00Z", "2026-10-01T12:00:00Z"
SUNSET_END, BEFORE_SUNSET = "2026-03-31T00:00:00Z", "2026-02-15T12:00:00Z"
HOME, ABROAD = "us.federal", "eu"


@dataclass(frozen=True)
class Ob:
    id: str
    kind: str  # must_not_exceed | must_be_at_least | must_be_within
    metric: str
    value: Any
    unit: str
    summary: str
    integer: bool = False
    jurisdiction: Optional[str] = HOME
    start: str = "2026-01-01T00:00:00Z"
    end: Optional[str] = None
    cap: Optional[float] = None  # largest meaningful reading (e.g. 100 for a percentage)


@dataclass
class Sector:
    name: str
    obligations: list[Ob]
    unmapped: list[tuple[str, Any, str]] = field(default_factory=list)  # (metric, reading, note)


FINANCE = Sector(
    "finance",
    [
        Ob(
            "finance.cip.days",
            "must_not_exceed",
            "days_to_cip_completion",
            30,
            "days",
            "Customer identification completed within 30 days",
            integer=True,
        ),
        Ob(
            "finance.ctr.days",
            "must_not_exceed",
            "days_to_ctr_filing",
            15,
            "days",
            "Currency transaction report filed within 15 days",
            integer=True,
        ),
        Ob(
            "finance.wire.purpose",
            "must_be_at_least",
            "purpose_documented_pct",
            100,
            "%",
            "Every wire transfer has a documented purpose",
            cap=100,
        ),
        Ob(
            "finance.cet1.min",
            "must_be_at_least",
            "cet1_ratio_pct",
            4.5,
            "%",
            "Common equity tier 1 ratio at least 4.5%",
        ),
        Ob(
            "finance.lcr.min",
            "must_be_at_least",
            "liquidity_coverage_pct",
            100,
            "%",
            "Liquidity coverage ratio at least 100%",
        ),
        Ob(
            "finance.ltv.band",
            "must_be_within",
            "loan_to_value_pct",
            [20, 80],
            "%",
            "Loan-to-value within the 20-80% underwriting band",
        ),
        Ob(
            "finance.breach.notice",
            "must_not_exceed",
            "breach_notice_hours",
            72,
            "h",
            "Personal-data breach notified within 72 hours (EU only)",
            integer=True,
            jurisdiction=ABROAD,
        ),
        Ob(
            "finance.settlement.t1",
            "must_not_exceed",
            "settlement_days",
            1,
            "days",
            "Securities settle T+1 (future rule)",
            integer=True,
            start=FUTURE_START,
        ),
        Ob(
            "finance.libor.exposure",
            "must_not_exceed",
            "libor_linked_exposure_pct",
            0,
            "%",
            "No LIBOR-linked exposure (sunset rule)",
            start="2025-07-01T00:00:00Z",
            end=SUNSET_END,
        ),
    ],
    unmapped=[
        ("branch_footfall", 1200, "metric not in any rule"),
        ("days_to_cip", 45, "near-miss metric name; must NOT fuzzy-match days_to_cip_completion"),
        ("tier1_ratio_pct", 3.0, "related-sounding metric with no rule"),
        ("atm_uptime_pct", 99.1, "metric not in any rule"),
        ("complaints_open", 17, "metric not in any rule"),
        ("cet1_ratio", 3.9, "near-miss metric name; must NOT fuzzy-match cet1_ratio_pct"),
        ("ltv_pct", 95, "near-miss metric name; must NOT fuzzy-match loan_to_value_pct"),
        ("staff_training_hours", 6, "metric not in any rule"),
    ],
)

MANUFACTURING = Sector(
    "manufacturing",
    [
        Ob(
            "mfg.noise.twa",
            "must_not_exceed",
            "dba_8h_twa",
            85,
            "dBA",
            "8-hour noise exposure at most 85 dBA",
        ),
        Ob(
            "mfg.guard.disengaged",
            "must_not_exceed",
            "guard_disengaged_events",
            0,
            "events",
            "No machine-guard disengagement events",
            integer=True,
        ),
        Ob(
            "mfg.lockout.verified",
            "must_be_at_least",
            "lockout_verified_pct",
            100,
            "%",
            "Every lockout/tagout verified",
            cap=100,
        ),
        Ob(
            "mfg.forklift.cert",
            "must_not_exceed",
            "forklift_cert_days_overdue",
            0,
            "days",
            "No forklift operator certification overdue",
            integer=True,
        ),
        Ob("mfg.voc.cap", "must_not_exceed", "voc_ppm", 100, "ppm", "Solvent VOC at most 100 ppm"),
        Ob(
            "mfg.cleanroom.humidity",
            "must_be_within",
            "relative_humidity_pct",
            [30, 60],
            "%",
            "Clean-room relative humidity 30-60%",
        ),
        Ob(
            "mfg.workstation.lux",
            "must_be_at_least",
            "workstation_lux",
            300,
            "lx",
            "Workstation lighting at least 300 lx (EU only)",
            integer=True,
            jurisdiction=ABROAD,
        ),
        Ob(
            "mfg.silica.cap",
            "must_not_exceed",
            "silica_ug_m3",
            25,
            "ug/m3",
            "Respirable silica at most 25 ug/m3 (future rule)",
            start=FUTURE_START,
        ),
        Ob(
            "mfg.r22.charge",
            "must_not_exceed",
            "r22_charge_kg",
            0,
            "kg",
            "No R-22 refrigerant charge (sunset rule)",
            start="2025-07-01T00:00:00Z",
            end=SUNSET_END,
        ),
    ],
    unmapped=[
        ("conveyor_speed_mps", 1.4, "metric not in any rule"),
        ("noise_dba", 92, "near-miss metric name; must NOT fuzzy-match dba_8h_twa"),
        ("guard_events", 3, "near-miss metric name; must NOT fuzzy-match guard_disengaged_events"),
        ("shift_headcount", 48, "metric not in any rule"),
        ("scrap_rate_pct", 4.2, "metric not in any rule"),
        ("voc", 180, "near-miss metric name; must NOT fuzzy-match voc_ppm"),
        ("humidity_pct", 75, "near-miss metric name; must NOT fuzzy-match relative_humidity_pct"),
        ("ambient_temp_c", 31, "metric not in any rule"),
    ],
)


def satisfied(ob: Ob, reading: float) -> bool:
    """Spec §3.3 predicate, independently of the reference implementation."""
    if ob.kind == "must_not_exceed":
        return bool(reading <= ob.value)
    if ob.kind == "must_be_at_least":
        return bool(reading >= ob.value)
    lo, hi = ob.value
    return bool(lo <= reading <= hi)


def _num(ob: Ob, x: float) -> float | int:
    return round(x) if ob.integer else round(x, 2)


def readings(ob: Ob) -> list[tuple[float | int, str]]:
    """(reading, category) pairs on both sides of the threshold and on it."""
    step = 1 if ob.integer else 0.1
    if ob.kind == "must_not_exceed":
        limit = ob.value
        if limit == 0:
            raw = [
                (0, "boundary"),
                (step, "flag"),
                (2 * step if ob.integer else 0.5, "flag"),
                (5, "flag"),
                (20, "flag"),
            ]
        else:
            raw = [
                (0, "clear"),
                (0.25 * limit, "clear"),
                (0.5 * limit, "clear"),
                (0.8 * limit, "clear"),
                (0.95 * limit, "clear"),
                (limit - step, "boundary"),
                (limit, "boundary"),
                (limit + step, "boundary"),
                (1.1 * limit, "flag"),
                (1.5 * limit, "flag"),
                (3 * limit, "flag"),
            ]
    elif ob.kind == "must_be_at_least":
        limit = ob.value
        above = (
            []
            if ob.cap is not None and limit >= ob.cap
            else [
                (limit + step, "boundary"),
                (1.05 * limit, "clear"),
                (1.2 * limit, "clear"),
                (2 * limit, "clear"),
            ]
        )
        raw = [
            (limit, "boundary"),
            *above,
            (limit - step, "boundary"),
            (0.9 * limit, "flag"),
            (0.5 * limit, "flag"),
            (0, "flag"),
        ]
    else:
        lo, hi = ob.value
        raw = [
            ((lo + hi) / 2, "clear"),
            (lo + (hi - lo) / 4, "clear"),
            (hi - (hi - lo) / 4, "clear"),
            (lo, "boundary"),
            (hi, "boundary"),
            (lo + step, "boundary"),
            (hi - step, "boundary"),
            (lo - step, "boundary"),
            (hi + step, "boundary"),
            (0.5 * lo, "flag"),
            (1.5 * hi, "flag"),
        ]
    seen: set[float] = set()
    out = []
    for x, cat in raw:
        v = _num(ob, x)
        if v not in seen:
            seen.add(v)
            out.append((v, cat))
    return out


def _case(
    case_id: str,
    ob_metric: str,
    reading: Any,
    jurisdiction: str,
    ts: str,
    verdict: str,
    category: str,
    assertions: list[dict[str, Any]],
    notes: str = "",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "subject": f"site.{ob_metric}",
        "jurisdiction": jurisdiction,
        "timestamp": ts,
        "measurement": {ob_metric: reading},
        "expected": {"verdict": verdict, "assertions": assertions},
        "category": category,
        "notes": notes,
    }


def _slug(v: Any) -> str:
    return str(v).replace(".", "p").replace("-", "m")


def evaluated(
    ob: Ob, reading: Any, ts: str, category: Optional[str] = None, prefix: str = ""
) -> dict[str, Any]:
    ok = satisfied(ob, reading)
    name = ob.id.split(".", 1)[1].replace(".", "-")
    return _case(
        f"{prefix}{'clear' if ok else 'flag'}-{name}-{_slug(reading)}",
        ob.metric,
        reading,
        ob.jurisdiction or HOME,
        ts,
        "CLEAR" if ok else "FLAG",
        category or ("clear" if ok else "flag"),
        [{"obligation_id": ob.id, "satisfied": ok}],
    )


def cases(sector: Sector) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ob in sector.obligations:
        name = ob.id.split(".", 1)[1].replace(".", "-")
        lifecycle = ob.start == FUTURE_START or ob.end is not None
        if lifecycle:
            # In force at another time: evaluated there; at NOW it scopes out.
            when = AFTER_FUTURE if ob.start == FUTURE_START else BEFORE_SUNSET
            for reading, _ in readings(ob):
                out.append(evaluated(ob, reading, when, category="effective-date", prefix="dated-"))
            for reading, _ in (readings(ob)[0], readings(ob)[-1]):
                out.append(
                    _case(
                        f"unmapped-{name}-out-of-force-{_slug(reading)}",
                        ob.metric,
                        reading,
                        ob.jurisdiction or HOME,
                        NOW,
                        "NULL_UNMAPPED",
                        "effective-date",
                        [],
                        "obligation not in force at this timestamp",
                    )
                )
            continue
        for reading, cat in readings(ob):
            case = evaluated(ob, reading, NOW, category=None if cat != "boundary" else "boundary")
            if ob.jurisdiction != HOME:
                case["category"] = "jurisdiction"
            out.append(case)
        # The scoping works both ways: a home obligation must not bind a record from abroad.
        other = HOME if ob.jurisdiction != HOME else ABROAD
        for reading, _ in (readings(ob)[0], readings(ob)[-1]):
            out.append(
                _case(
                    f"unmapped-{name}-{other.replace('.', '-')}-{_slug(reading)}",
                    ob.metric,
                    reading,
                    other,
                    NOW,
                    "NULL_UNMAPPED",
                    "jurisdiction",
                    [],
                    f"obligation scoped to {ob.jurisdiction}; a {other} record must scope it out",
                )
            )
        for reading, label in ((None, "null"), ("n/a", "nonnumeric")):
            out.append(
                _case(
                    f"stale-{name}-{label}",
                    ob.metric,
                    reading,
                    ob.jurisdiction or HOME,
                    NOW,
                    "NULL_STALE",
                    "null_stale",
                    [],
                    "silent sensor on a mapped metric",
                )
            )
    out += multi_metric(sector)
    for metric, reading, note in sector.unmapped:
        out.append(
            _case(
                f"unmapped-{metric.replace('_', '-')}",
                metric,
                reading,
                HOME,
                NOW,
                "NULL_UNMAPPED",
                "null_unmapped",
                [],
                note,
            )
        )
    ids = [c["case_id"] for c in out]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    return out


def multi_metric(sector: Sector) -> list[dict[str, Any]]:
    """Records carrying two mapped readings: every obligation in the record must hold for CLEAR."""
    home = [
        ob for ob in sector.obligations if ob.jurisdiction == HOME and ob.start != FUTURE_START and not ob.end
    ]
    out: list[dict[str, Any]] = []
    for a, b in itertools.pairwise(home):
        good_a, good_b = readings(a)[0][0], readings(b)[0][0]
        bad_b = readings(b)[-1][0]
        pair = f"{a.id.split('.')[1]}-{b.id.split('.')[1]}"
        for label, rb, verdict in (("both-ok", good_b, "CLEAR"), ("one-breach", bad_b, "FLAG")):
            out.append(
                {
                    "case_id": f"multi-{pair}-{label}",
                    "subject": "site.multi",
                    "jurisdiction": HOME,
                    "timestamp": NOW,
                    "measurement": {a.metric: good_a, b.metric: rb},
                    "expected": {
                        "verdict": verdict,
                        "assertions": [
                            {"obligation_id": a.id, "satisfied": satisfied(a, good_a)},
                            {"obligation_id": b.id, "satisfied": satisfied(b, rb)},
                        ],
                    },
                    "category": "multi-metric",
                    "notes": "every obligation the record maps must hold for CLEAR",
                }
            )
        out.append(
            {
                "case_id": f"multi-{pair}-one-silent",
                "subject": "site.multi",
                "jurisdiction": HOME,
                "timestamp": NOW,
                "measurement": {a.metric: good_a, b.metric: None},
                "expected": {"verdict": "NULL_STALE", "assertions": []},
                "category": "null_stale",
                "notes": "one healthy reading does not clear a record with a silent sensor",
            }
        )
    return out


def _version(node: dict[str, Any]) -> str:
    body = json.dumps(
        {k: v for k, v in node.items() if k != "version"}, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def kg(sector: Sector) -> dict[str, Any]:
    rules, obligations, edges = [], [], []
    for ob in sector.obligations:
        node: dict[str, Any] = {
            "id": ob.id,
            "type": "Obligation",
            "obligation_type": ob.kind,
            "metric": ob.metric,
            "value": ob.value,
            "unit": ob.unit,
            "effective_date_start": ob.start,
            "summary": ob.summary,
        }
        if ob.end:
            node["effective_date_end"] = ob.end
        node["version"] = _version(node)
        obligations.append(node)
        rule: dict[str, Any] = {"id": f"rule.{ob.id}", "type": "Rule", "name": ob.summary}
        rule["version"] = _version(rule)
        rules.append(rule)
        edges.append({"type": "consists_of", "from": rule["id"], "to": ob.id})
        if ob.jurisdiction:
            edges.append({"type": "scoped_to", "from": ob.id, "to": ob.jurisdiction})
    jurisdictions = []
    for jid in sorted({ob.jurisdiction for ob in sector.obligations if ob.jurisdiction}):
        j: dict[str, Any] = {"id": jid, "type": "Jurisdiction", "name": jid}
        j["version"] = _version(j)
        jurisdictions.append(j)
    return {
        "metadata": {
            "version": f"ski-evals-{sector.name}-1.0.0",
            "name": f"SKI Evals - {sector.name} dataset KG",
            "description": "Evaluation KG generated by evals/datasets/generate.py. Unsigned: evals load it "
            "with require_signature=False. All thresholds are illustrative, not regulatory citations.",
            "schema_version": "3.0",
        },
        "nodes": {"rules": rules, "obligations": obligations, "jurisdictions": jurisdictions},
        "edges": edges,
    }


def render(sector: Sector) -> dict[str, str]:
    return {
        "eval-kg.json": json.dumps(kg(sector), indent=2) + "\n",
        "cases.jsonl": "".join(json.dumps(c) + "\n" for c in cases(sector)),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="Fail if the committed files are out of date.")
    args = parser.parse_args(argv)
    stale = []
    for sector in (FINANCE, MANUFACTURING):
        for name, text in render(sector).items():
            path = HERE / sector.name / name
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    stale.append(str(path))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    if stale:
        print(
            "out of date (run python -m evals.datasets.generate):\n  " + "\n  ".join(stale), file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
