"""Unit tests for the RFC 8785 (JCS) + spec v3.0 §7.3 canonicalizer.

The number known-answer tests and the NFC / UTF-16-sort / escaping checks are
hand-built independent oracles (RFC 8785 Appendix B and Section 3.2.3, built
from code points, not from the canonicalizer). The committed vectors under
``spec/test-vectors/canonical/`` are then checked against the canonicalizer so
the two cannot drift. Backslashes in expected output are written as
``chr(0x5C)`` to keep the source unambiguous.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ski_schemas.canonical import (
    CanonicalizationError,
    canonicalize,
    canonicalize_json_text,
    digest,
    parse_json,
    serialize_number,
    sha256_canonical,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CANONICAL_VECTORS = _REPO_ROOT / "spec" / "test-vectors" / "canonical"

BS = chr(0x5C)  # a single backslash


# ---------------------------------------------------------------------------
# Numbers — ECMA-262 Number::toString (RFC 8785 Appendix B), hand-verified.
# ---------------------------------------------------------------------------

NUMBER_KATS = [
    (0, "0"),
    (-0.0, "0"),
    (0.0, "0"),
    (1, "1"),
    (1.0, "1"),
    (-1, "-1"),
    (100, "100"),
    (1e20, "100000000000000000000"),
    (1e21, "1e+21"),
    (1e30, "1e+30"),
    (0.1, "0.1"),
    (0.001, "0.001"),
    (1e-6, "0.000001"),
    (1e-7, "1e-7"),
    (5e-324, "5e-324"),
    (1.7976931348623157e308, "1.7976931348623157e+308"),
    (-5e-324, "-5e-324"),
    (9007199254740992, "9007199254740992"),
    (2.9514790517935283e20, "295147905179352830000"),
    (333333333.33333329, "333333333.3333333"),
    (4.50, "4.5"),
    (2e-3, "0.002"),
    (1e-27, "1e-27"),
    (123456789012345680000.0, "123456789012345680000"),
]


@pytest.mark.parametrize(("value", "expected"), NUMBER_KATS)
def test_number_serialization(value: float, expected: str) -> None:
    assert serialize_number(value) == expected


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_rejected(bad: float) -> None:
    with pytest.raises(CanonicalizationError):
        serialize_number(bad)


def test_bool_is_not_a_number() -> None:
    with pytest.raises(CanonicalizationError):
        serialize_number(True)  # bool subclasses int; must be rejected here


def test_integer_not_exactly_representable_rejected() -> None:
    # 2**53 is exact; 2**53 + 1 is not representable as a double.
    assert serialize_number(2**53) == "9007199254740992"
    with pytest.raises(CanonicalizationError):
        serialize_number(2**53 + 1)


# ---------------------------------------------------------------------------
# Structure — object key sort (UTF-16), booleans, null.
# ---------------------------------------------------------------------------


def test_key_sort_ascii() -> None:
    got = canonicalize({"b": 2, "a": 1, "A": 3, "10": 4, "1": 5})
    assert got == b'{"1":5,"10":4,"A":3,"a":1,"b":2}'


def test_key_sort_utf16_surrogate_subtlety() -> None:
    # U+10000 is the surrogate pair D800 DC00; by UTF-16 code unit its first
    # unit 0xD800 < 0xFFFF, so U+10000 sorts BEFORE U+FFFF. A naive code-point
    # sort would put U+FFFF first and is wrong per RFC 8785 §3.2.3.
    got = canonicalize({chr(0xFFFF): 1, chr(0x10000): 2, "a": 3}).decode("utf-8")
    assert got == '{"a":3,"' + chr(0x10000) + '":2,"' + chr(0xFFFF) + '":1}'


def test_literals_and_empty_containers() -> None:
    assert canonicalize({}) == b"{}"
    assert canonicalize([]) == b"[]"
    assert canonicalize({"c": False, "a": None, "b": True}) == b'{"a":null,"b":true,"c":false}'


# ---------------------------------------------------------------------------
# Strings — NFC of values, escaping.
# ---------------------------------------------------------------------------


def test_nfc_applied_to_values() -> None:
    # "e" + combining acute (U+0301) normalizes to the precomposed U+00E9.
    got = canonicalize({"name": "e" + chr(0x0301)}).decode("utf-8")
    assert got == '{"name":"' + chr(0x00E9) + '"}'


def test_nfc_not_applied_to_member_names() -> None:
    # §7.3 rule 3 scopes NFC to values; a decomposed NAME is left as-is.
    got = canonicalize({"e" + chr(0x0301): 1}).decode("utf-8")
    assert got == '{"e' + chr(0x0301) + '":1}'


def test_short_escapes() -> None:
    expected = '{"s":"' + BS + "b" + BS + "t" + BS + "n" + BS + "f" + BS + 'r"}'
    assert canonicalize({"s": "\b\t\n\f\r"}).decode("utf-8") == expected


def test_control_chars_use_lowercase_u_escape() -> None:
    assert canonicalize({"s": chr(0x00)}).decode("utf-8") == '{"s":"' + BS + 'u0000"}'
    assert canonicalize({"s": chr(0x1F)}).decode("utf-8") == '{"s":"' + BS + 'u001f"}'


def test_quote_and_backslash_escaped() -> None:
    assert canonicalize({"s": '"'}).decode("utf-8") == '{"s":"' + BS + '""}'
    assert canonicalize({"s": BS}).decode("utf-8") == '{"s":"' + BS + BS + '"}'


def test_slash_and_del_are_literal() -> None:
    # RFC 8785 does NOT escape '/' or U+007F.
    assert canonicalize({"s": "/"}).decode("utf-8") == '{"s":"/"}'
    assert canonicalize({"s": chr(0x7F)}).decode("utf-8") == '{"s":"' + chr(0x7F) + '"}'


def test_lone_surrogate_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonicalize({"s": chr(0xD800)})


# ---------------------------------------------------------------------------
# Strict JSON text parsing (I-JSON).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"])
def test_parse_rejects_non_finite(text: str) -> None:
    with pytest.raises(CanonicalizationError):
        parse_json(text)


def test_parse_rejects_duplicate_keys() -> None:
    with pytest.raises(CanonicalizationError):
        parse_json('{"a":1,"a":2}')


def test_parse_rejects_bom() -> None:
    with pytest.raises(CanonicalizationError):
        parse_json(b"\xef\xbb\xbf{}")


def test_parse_big_integer_rounds_to_double_like_js() -> None:
    # JSON.parse rounds an over-precise integer literal to the nearest double;
    # the whole-object canonicalizer rejects the same value as a Python int.
    assert canonicalize_json_text("295147905179352830000") == b"295147905179352830000"
    with pytest.raises(CanonicalizationError):
        canonicalize(295147905179352830000)


# ---------------------------------------------------------------------------
# Digest helpers.
# ---------------------------------------------------------------------------


def test_sha256_canonical_shape_and_equivalence() -> None:
    value = {"z": 1, "a": [1, 2, 3]}
    tagged = sha256_canonical(value)
    assert tagged.startswith("sha256:")
    assert len(tagged) == len("sha256:") + 64
    assert all(c in "0123456789abcdef" for c in tagged.split(":", 1)[1])
    assert tagged == digest(value, "sha256")


def test_digest_rejects_unknown_algorithm() -> None:
    with pytest.raises(CanonicalizationError):
        digest({}, "md5")


# ---------------------------------------------------------------------------
# Committed vectors — reproduce every KAT under spec/test-vectors/canonical/.
# ---------------------------------------------------------------------------


def _vector_files() -> list[Path]:
    return sorted(_CANONICAL_VECTORS.glob("*.json"))


@pytest.mark.parametrize("path", _vector_files(), ids=lambda p: p.stem)
def test_committed_canonical_vectors(path: Path) -> None:
    vec = json.loads(path.read_text(encoding="utf-8"))
    assert canonicalize(vec["input"]).decode("utf-8") == vec["canonical"]
    assert sha256_canonical(vec["input"]) == vec["sha256"]


def test_vectors_present() -> None:
    # Guard against an empty glob silently passing the parametrized test.
    assert len(_vector_files()) >= 10
