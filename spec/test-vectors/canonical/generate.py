#!/usr/bin/env python3
"""Regenerate the canonicalization known-answer test vectors.

Each vector file pins ``input`` (a JSON value) to its expected canonical
UTF-8 serialization (``canonical``) and that serialization's digest
(``sha256``), under the SKI profile of RFC 8785 + spec v3.0 §7.3 NFC
(``ski_schemas.canonical.canonicalize`` / ``sha256_canonical``).

Any implementation claiming conformance MUST reproduce ``canonical`` and
``sha256`` byte-for-byte from ``input``.

To guard against a regressed canonicalizer silently rewriting the vectors,
the headline cases carry an independently-known ``expected`` string
(from RFC 8785 Appendix B / Section 3.2.3, hand-derived) that this
generator asserts before writing. Run ``python generate.py`` to rewrite the
files; the drift check re-validates every committed vector.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "tools" / "ski-schemas" / "src"))

from ski_schemas.canonical import canonicalize, sha256_canonical  # noqa: E402

HERE = Path(__file__).resolve().parent

# Characters built from code points so the source file carries no raw
# control characters or ambiguous escapes.
NUL, US, BS, HT, LF, FF, CR = (chr(c) for c in (0x00, 0x1F, 0x08, 0x09, 0x0A, 0x0C, 0x0D))
SI = chr(0x0F)  # U+000F, the control char in the RFC 8785 §3.2.3 example
DEL = chr(0x7F)
EURO = chr(0x20AC)
COMBINING_ACUTE = chr(0x0301)
E_ACUTE = chr(0x00E9)  # precomposed NFC form of "e" + combining acute
BMP_MAX = chr(0xFFFF)
ASTRAL = chr(0x10000)  # surrogate pair D800 DC00 in UTF-16


class Vector(NamedTuple):
    name: str
    description: str
    value: Any
    expected: Optional[str]  # independently-known canonical form, or None


VECTORS: list[Vector] = [
    Vector("empty_object", "The empty object.", {}, "{}"),
    Vector("empty_array", "The empty array.", [], "[]"),
    Vector(
        "literals",
        "null/true/false as member values; keys already sorted.",
        {"a": None, "b": True, "c": False},
        '{"a":null,"b":true,"c":false}',
    ),
    Vector(
        "numbers_rfc8785",
        "ECMA-262 Number::toString serialization of the RFC 8785 Appendix B representative values.",
        [
            0,
            1,
            -1,
            100,
            1e20,
            1e21,
            1e30,
            0.1,
            0.001,
            1e-6,
            1e-7,
            5e-324,
            1.7976931348623157e308,
            9007199254740992,
            2.9514790517935283e20,
            333333333.33333329,
            4.50,
            2e-3,
            0.000000000000000000000000001,
        ],
        "[0,1,-1,100,100000000000000000000,1e+21,1e+30,0.1,0.001,0.000001,1e-7,"
        "5e-324,1.7976931348623157e+308,9007199254740992,295147905179352830000,"
        "333333333.3333333,4.5,0.002,1e-27]",
    ),
    Vector(
        "key_sort_ascii",
        "Keys sorted by UTF-16 code unit: digits before uppercase before lowercase.",
        {"b": 2, "a": 1, "A": 3, "10": 4, "1": 5},
        '{"1":5,"10":4,"A":3,"a":1,"b":2}',
    ),
    Vector(
        "key_sort_utf16_surrogate",
        "The JCS subtlety: U+10000 (high surrogate 0xD800) sorts BEFORE U+FFFF by UTF-16 code unit.",
        {BMP_MAX: 1, ASTRAL: 2, "a": 3},
        '{"a":3,"' + ASTRAL + '":2,"' + BMP_MAX + '":1}',
    ),
    Vector(
        "nfc_value_normalized",
        "A string VALUE in NFC-decomposed form ('e' + U+0301) normalizes to the precomposed U+00E9.",
        {"name": "e" + COMBINING_ACUTE},
        '{"name":"' + E_ACUTE + '"}',
    ),
    Vector(
        "nfc_key_not_normalized",
        "A member NAME is NOT NFC-normalized (spec §7.3 rule 3 scopes NFC to values); recorded for RFC 0004.",
        {"e" + COMBINING_ACUTE: 1},
        '{"e' + COMBINING_ACUTE + '":1}',
    ),
    Vector(
        "control_and_escape",
        "RFC 8785 §3.2.2.2 string escaping: short escapes, lowercase \\u00xx, literal '/' and U+007F.",
        {"s": BS + HT + LF + FF + CR + NUL + US + "/" + DEL + '"' + "\\"},
        '{"s":"\\b\\t\\n\\f\\r\\u0000\\u001f/' + DEL + '\\"\\\\"}',
    ),
    Vector(
        "nested_measurement",
        "A realistic nested object (unsorted keys, mixed types) exercising recursion.",
        {
            "timestamp": "2026-05-01T12:00:00Z",
            "measurement": {"so2_ppm": 98.6, "nox_ppm": 12, "online": True, "notes": None},
            "measurement_id": "m-42",
            "subject": "stack-7",
        },
        None,
    ),
    Vector(
        "rfc8785_section_3_2_3",
        "The full worked example from RFC 8785 Section 3.2.3; 'canonical' is the RFC's published output.json.",
        {
            "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
            "string": EURO + "$" + SI + LF + "A'" + "B" + '"' + "\\" + "\\" + '"' + "/",
            "literals": [None, True, False],
        },
        '{"literals":[null,true,false],'
        '"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"' + EURO + "$" + "\\u000f" + "\\n" + "A'" + "B" + '\\"' + "\\\\\\\\" + '\\"' + '/"}',
    ),
]


def build() -> dict[str, str]:
    """Return ``{filename: serialized vector text}`` for every KAT."""
    out: dict[str, str] = {}
    for vec in VECTORS:
        canonical = canonicalize(vec.value).decode("utf-8")
        if vec.expected is not None and canonical != vec.expected:
            raise SystemExit(
                f"vector {vec.name!r}: canonicalizer output does not match the "
                f"independently-known expected value.\n  got:      {canonical!r}\n  expected: {vec.expected!r}"
            )
        doc = {
            "name": vec.name,
            "description": vec.description,
            "input": vec.value,
            "canonical": canonical,
            "sha256": sha256_canonical(vec.value),
        }
        out[f"{vec.name}.json"] = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    return out


def main() -> int:
    for name, text in build().items():
        (HERE / name).write_text(text, encoding="utf-8")
        print(f"wrote {(HERE / name).relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
