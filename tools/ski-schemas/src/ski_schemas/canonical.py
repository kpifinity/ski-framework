"""SKI canonical JSON: RFC 8785 (JCS) plus the NFC rule of spec v3.0 §7.3.

This module is the one canonicalizer the framework's contracts are
defined against. It is additive: no existing hash or signature in the
reference implementation is computed with it yet (the ledger-v4 work
switches call sites). The language-neutral test vectors that pin its
behaviour live in ``spec/test-vectors/canonical/``.

Two byte-level functions are provided:

* :func:`jcs_canonicalize` is RFC 8785 exactly, with no Unicode
  normalization. It reproduces the published RFC 8785 test data.
* :func:`canonicalize` is the SKI profile of spec v3.0 §7.3. It applies
  Unicode NFC to string values and then serializes with RFC 8785.

The NFC scope is taken verbatim from spec v3.0 §7.3, rule 3:

    "String values are UTF-8 NFC-normalized."

The spec says *string values*, so NFC is applied to every JSON string
that appears as a value (object member values and array elements, at any
depth). Object member *names* (keys) are not normalized: §7.3 does not
say they are, and normalizing them could merge two distinct keys. That
reading is recorded as an open question for RFC 0004.

RFC 8785 rules implemented here:

* Object members are sorted by the UTF-16 code units of their names
  (RFC 8785 §3.2.3), not by Unicode code point and not by locale.
* Strings are emitted as UTF-8. Only ``"``, ``\\`` and the C0 controls
  U+0000 to U+001F are escaped; the controls use ``\\b \\t \\n \\f \\r``
  where they exist and lowercase ``\\u00xx`` otherwise (RFC 8785
  §3.2.2.2). Everything else, including ``/``, U+007F and U+2028, is
  written literally.
* Numbers are IEEE-754 doubles printed with the ECMAScript
  Number-to-String algorithm (ECMA-262 §7.1.12.1, called
  ``Number::toString`` in current editions): the shortest digit string
  that round-trips, plain notation for decimal exponents in [-6, 21),
  exponent notation otherwise, and ``-0`` printed as ``0``. Integral
  values carry no ``.0``.
* NaN and the infinities are rejected (RFC 8785 §3.2.2.3).
* Strings containing lone surrogates are rejected (RFC 8785 §3.2.2.2
  requires valid Unicode).
* When parsing JSON text, duplicate member names are rejected
  (RFC 8785 §3.1 requires I-JSON, RFC 7493 §2.3).

Python-specific input rules:

* ``bool`` is checked before ``int`` (``bool`` subclasses ``int``).
* An ``int`` that a double cannot hold exactly (for example
  ``2**53 + 1``) is rejected rather than rounded, so two distinct
  integers can never canonicalize to the same bytes. JSON *text* is
  parsed the way ``JSON.parse`` does it (see :func:`parse_json`), so an
  over-long integer literal is rounded to the nearest double there, as
  every RFC 8785 implementation does.
* Member names must be ``str``. Python's ``json`` silently turns ``int``
  keys into strings; this module refuses them instead.
* Arrays are ``list`` or ``tuple``; objects are any ``Mapping`` with
  ``str`` keys. Every other type (``bytes``, ``Decimal``, ``datetime``,
  ``set`` and so on) is rejected.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Dict, List, Union

__all__ = [
    "SUPPORTED_DIGEST_ALGORITHMS",
    "UNICODE_VERSION",
    "CanonicalizationError",
    "JsonInput",
    "JsonValue",
    "canonicalize",
    "canonicalize_json_text",
    "digest",
    "jcs_canonicalize",
    "jcs_canonicalize_json_text",
    "nfc_normalize_values",
    "parse_json",
    "serialize_number",
    "sha256_canonical",
]

#: The Unicode Character Database version this interpreter's NFC uses.
#: NFC output is stable for assigned characters across versions (the
#: Unicode normalization stability policy), but a string containing a code
#: point unassigned in an older version can normalize differently.
UNICODE_VERSION: str = unicodedata.unidata_version

#: A JSON value as returned by :func:`parse_json`.
JsonValue = Union[None, bool, int, float, str, List["JsonValue"], Dict[str, "JsonValue"]]

#: What the canonicalizer accepts. ``Mapping`` and ``Sequence`` keep the
#: alias covariant, so ``dict[str, int]`` and ``list[str]`` type-check.
JsonInput = Union[None, bool, int, float, str, Sequence["JsonInput"], Mapping[str, "JsonInput"]]

#: Digest algorithms :func:`digest` accepts. Spec §4.6 makes SHA-256 the
#: minimum; stronger hashes MAY be used in addition.
SUPPORTED_DIGEST_ALGORITHMS: Dict[str, Callable[[bytes], Any]] = {
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
}

# 2**53: every integer with magnitude up to this is exactly representable.
_EXACT_INT_LIMIT = 9007199254740992

_SHORT_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


class CanonicalizationError(ValueError):
    """The input cannot be canonicalized under RFC 8785 / spec §7.3."""


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def _int_to_double(value: int) -> float:
    """Return ``value`` as a double, refusing any value a double cannot hold exactly."""
    if -_EXACT_INT_LIMIT <= value <= _EXACT_INT_LIMIT:
        return float(value)
    try:
        as_float = float(value)
    except OverflowError:
        raise CanonicalizationError(f"integer {value} is outside the IEEE-754 double range") from None
    if int(as_float) != value:
        raise CanonicalizationError(
            f"integer {value} is not exactly representable as an IEEE-754 double; "
            "encode it as a string (RFC 8785 §3.2.2.3, RFC 7493 §2.2)"
        )
    return as_float


def _shortest_digits(value: float) -> tuple[str, int]:
    """Return ``(digits, n)`` with ``value == 0.<digits> * 10**n`` for a finite positive double.

    ``digits`` has no leading or trailing zeros. Python's ``repr`` gives
    the shortest string that round-trips (David Gay's algorithm, ties
    broken toward the closer and then the even candidate), which is the
    digit string ECMA-262 Number::toString requires.
    """
    text = repr(value)
    mantissa, _, exponent_text = text.partition("e")
    exponent = int(exponent_text) if exponent_text else 0
    int_part, _, frac_part = mantissa.partition(".")
    raw = int_part + frac_part
    stripped = raw.lstrip("0")
    leading_zeros = len(raw) - len(stripped)
    digits = stripped.rstrip("0")
    n = len(int_part) + exponent - leading_zeros
    return digits, n


def serialize_number(value: Union[int, float]) -> str:
    """Serialize a number as ECMAScript ``Number::toString`` does (RFC 8785 §3.2.2.3).

    Raises :class:`CanonicalizationError` for NaN, the infinities, ``bool``
    and integers that a double cannot represent exactly.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalizationError(f"not a JSON number: {value!r}")
    number = _int_to_double(value) if isinstance(value, int) else value
    if math.isnan(number) or math.isinf(number):
        raise CanonicalizationError(f"{number!r} is not a valid JSON number (RFC 8785 §3.2.2.3)")
    if number == 0:
        return "0"  # covers -0.0 as well
    sign = "-" if number < 0 else ""
    digits, n = _shortest_digits(abs(number))
    k = len(digits)
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        exp = n - 1
        exp_text = ("+" if exp >= 0 else "-") + str(abs(exp))
        body = digits + "e" + exp_text if k == 1 else digits[0] + "." + digits[1:] + "e" + exp_text
    return sign + body


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------


def _check_unicode(text: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError(
            f"string contains a lone surrogate at index {exc.start} (RFC 8785 §3.2.2.2)"
        ) from None


def _serialize_string(text: str) -> str:
    _check_unicode(text)
    out: List[str] = ['"']
    for char in text:
        code = ord(char)
        short = _SHORT_ESCAPES.get(code)
        if short is not None:
            out.append(short)
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _utf16_sort_key(name: str) -> bytes:
    # Big-endian UTF-16 compares bytewise in the same order as the
    # sequence of 16-bit code units, which is what RFC 8785 §3.2.3 sorts by.
    return name.encode("utf-16-be")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize(value: object, out: List[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, (int, float)):
        out.append(serialize_number(value))
    elif isinstance(value, str):
        out.append(_serialize_string(value))
    elif isinstance(value, Mapping):
        names: List[str] = []
        for name in value:
            if not isinstance(name, str):
                raise CanonicalizationError(f"object member name must be a string, got {type(name).__name__}")
            _check_unicode(name)
            names.append(name)
        names.sort(key=_utf16_sort_key)
        out.append("{")
        for index, name in enumerate(names):
            if index:
                out.append(",")
            out.append(_serialize_string(name))
            out.append(":")
            _serialize(value[name], out)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _serialize(item, out)
        out.append("]")
    else:
        raise CanonicalizationError(f"type {type(value).__name__} has no JSON representation")


def jcs_canonicalize(obj: JsonInput) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of ``obj``, with no Unicode normalization."""
    out: List[str] = []
    _serialize(obj, out)
    return "".join(out).encode("utf-8")


def nfc_normalize_values(obj: JsonInput) -> JsonInput:
    """Return a copy of ``obj`` with every string *value* NFC-normalized (spec v3.0 §7.3, rule 3).

    Member names are left exactly as they are; see the module docstring.
    Values of non-JSON types are passed through unchanged, so the
    serializer still rejects them.
    """
    if isinstance(obj, str):
        _check_unicode(obj)
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, Mapping):
        return {name: nfc_normalize_values(item) for name, item in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [nfc_normalize_values(item) for item in obj]
    return obj


def canonicalize(obj: JsonInput) -> bytes:
    """Return the SKI canonical bytes of ``obj`` (spec v3.0 §7.3): NFC string values, then RFC 8785."""
    return jcs_canonicalize(nfc_normalize_values(obj))


def digest(obj: JsonInput, alg: str = "sha256") -> str:
    """Return the algorithm-tagged digest of :func:`canonicalize` of ``obj``, e.g. ``"sha256:<hex>"``.

    The tag and the hex are lowercase, as spec §4.6 requires for every hash.
    """
    hasher = SUPPORTED_DIGEST_ALGORITHMS.get(alg)
    if hasher is None:
        supported = ", ".join(sorted(SUPPORTED_DIGEST_ALGORITHMS))
        raise CanonicalizationError(f"unsupported digest algorithm {alg!r}; supported: {supported}")
    return f"{alg}:{hasher(canonicalize(obj)).hexdigest()}"


def sha256_canonical(obj: JsonInput) -> str:
    """Return ``"sha256:<hex>"`` — the SHA-256 of :func:`canonicalize` of ``obj``.

    The canonical convenience helper for the common case: it is exactly
    ``digest(obj, "sha256")``. Spec §4.6 makes SHA-256 the minimum every
    conforming implementation MUST support, so this is the digest the
    published contracts and test vectors are pinned to.
    """
    return digest(obj, "sha256")


# ---------------------------------------------------------------------------
# Strict JSON text parsing (I-JSON, RFC 7493)
# ---------------------------------------------------------------------------


def _reject_constant(name: str) -> JsonValue:
    raise CanonicalizationError(f"{name} is not valid JSON (RFC 8259 §6); NaN and Infinity are rejected")


def _parse_float(literal: str) -> float:
    value = float(literal)
    if math.isinf(value):
        raise CanonicalizationError(f"number {literal} overflows an IEEE-754 double")
    return value


def _parse_int(literal: str) -> Union[int, float]:
    try:
        value = int(literal)
    except ValueError:  # longer than sys.get_int_max_str_digits(); far beyond a double
        raise CanonicalizationError(f"integer literal of {len(literal)} digits overflows a double") from None
    if -_EXACT_INT_LIMIT <= value <= _EXACT_INT_LIMIT:
        return value
    # JSON.parse semantics: round to the nearest double.
    try:
        as_float = float(value)
    except OverflowError:
        raise CanonicalizationError(f"number {literal} overflows an IEEE-754 double") from None
    return int(as_float) if int(as_float) == value else as_float


def _no_duplicates(pairs: List[tuple[str, JsonValue]]) -> Dict[str, JsonValue]:
    result: Dict[str, JsonValue] = {}
    for name, value in pairs:
        if name in result:
            raise CanonicalizationError(f"duplicate object member name {name!r} (RFC 7493 §2.3)")
        result[name] = value
    return result


def _check_tree(value: JsonValue) -> None:
    if isinstance(value, str):
        _check_unicode(value)
    elif isinstance(value, dict):
        for name, item in value.items():
            _check_unicode(name)
            _check_tree(item)
    elif isinstance(value, list):
        for item in value:
            _check_tree(item)


def parse_json(text: Union[str, bytes]) -> JsonValue:
    """Parse JSON text strictly enough to canonicalize it.

    * ``bytes`` must be valid UTF-8 with no byte-order mark.
    * ``NaN``, ``Infinity`` and ``-Infinity`` are rejected, as are numbers
      that overflow a double.
    * Duplicate member names are rejected.
    * Escaped lone surrogates (for example ``"\\ud800"``) are rejected.
    * Integer literals that a double cannot hold exactly are rounded to
      the nearest double, as ``JSON.parse`` does. Other integers stay
      ``int``; fractional or exponent literals become ``float``.

    Raises :class:`CanonicalizationError` for every rejection, including
    malformed JSON.
    """
    if isinstance(text, bytes):
        if text.startswith(b"\xef\xbb\xbf"):
            raise CanonicalizationError("JSON text must not start with a byte-order mark (RFC 8259 §8.1)")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalizationError(f"JSON text is not valid UTF-8: {exc.reason}") from None
    try:
        value: JsonValue = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
            parse_int=_parse_int,
        )
    except json.JSONDecodeError as exc:
        raise CanonicalizationError(f"malformed JSON: {exc}") from None
    except RecursionError:
        raise CanonicalizationError("JSON text is nested too deeply") from None
    _check_tree(value)
    return value


def jcs_canonicalize_json_text(text: Union[str, bytes]) -> bytes:
    """Parse ``text`` with :func:`parse_json` and return its RFC 8785 bytes."""
    return jcs_canonicalize(parse_json(text))


def canonicalize_json_text(text: Union[str, bytes]) -> bytes:
    """Parse ``text`` with :func:`parse_json` and return its SKI canonical (§7.3) bytes."""
    return canonicalize(parse_json(text))
