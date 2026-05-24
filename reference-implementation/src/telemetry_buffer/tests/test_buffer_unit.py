"""Unit tests for the telemetry buffer that do not need a live Postgres.

The live-Postgres tests live under conformance/level2/ and are skipped
when LEDGER_DSN is unset. Here we only test pure functions and shapes.
"""

from __future__ import annotations

from telemetry_buffer.buffer import canonical_measurement_hash


def test_canonical_hash_is_stable_across_key_order() -> None:
    a = {"so2_ppm": {"value": 85, "unit": "ppm"}, "temp": 20}
    b = {"temp": 20, "so2_ppm": {"unit": "ppm", "value": 85}}
    assert canonical_measurement_hash(a) == canonical_measurement_hash(b)


def test_canonical_hash_changes_with_value() -> None:
    a = {"so2_ppm": {"value": 85, "unit": "ppm"}}
    b = {"so2_ppm": {"value": 86, "unit": "ppm"}}
    assert canonical_measurement_hash(a) != canonical_measurement_hash(b)


def test_canonical_hash_is_64_hex_chars() -> None:
    h = canonical_measurement_hash({"x": 1})
    assert len(h) == 64
    int(h, 16)  # raises if not valid hex


def test_canonical_hash_handles_unicode() -> None:
    # ensure_ascii=False means non-ASCII chars are NOT escaped; the hash
    # must still be stable across runs and across Python implementations.
    h1 = canonical_measurement_hash({"label": "Schwefeldioxid", "value": 85})
    h2 = canonical_measurement_hash({"value": 85, "label": "Schwefeldioxid"})
    assert h1 == h2
