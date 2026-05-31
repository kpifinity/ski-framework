"""Tests for AgreementMonitor (PR 12).

The monitor is a rolling-window counter of VerifierStatus outcomes. Tests
cover the obvious paths (record, snapshot, threshold) plus the boundary
conditions (empty window, window overflow, validation errors).
"""

from __future__ import annotations

import pytest

from ski_model.v3 import AgreementMonitor, VerifierStatus


class TestRecord:
    def test_accepts_verifier_status_enum(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        m.record(VerifierStatus.AGREED)
        assert m.snapshot()["observed"] == 1

    def test_accepts_string_value(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        m.record("AGREED")
        assert m.snapshot()["observed"] == 1

    def test_rejects_unknown_string(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        with pytest.raises(ValueError):
            m.record("MAYBE")

    def test_rejects_non_str_non_enum(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        with pytest.raises(TypeError):
            m.record(42)  # type: ignore[arg-type]


class TestSnapshot:
    def test_empty_window_has_no_rate(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        snap = m.snapshot()
        assert snap["observed"] == 0
        assert snap["agreement_rate"] is None
        assert snap["is_healthy"] is True
        for status in VerifierStatus:
            assert snap["counts"][status.value] == 0

    def test_all_agreed_yields_rate_1_and_healthy(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        for _ in range(5):
            m.record(VerifierStatus.AGREED)
        snap = m.snapshot()
        assert snap["observed"] == 5
        assert snap["counts"]["AGREED"] == 5
        assert snap["agreement_rate"] == 1.0
        assert snap["is_healthy"] is True

    def test_mixed_statuses_compute_correct_rate(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        for _ in range(8):
            m.record(VerifierStatus.AGREED)
        m.record(VerifierStatus.LLM_CONTRADICTION)
        m.record(VerifierStatus.UNVERIFIABLE)
        snap = m.snapshot()
        assert snap["observed"] == 10
        assert snap["counts"]["AGREED"] == 8
        assert snap["counts"]["LLM_CONTRADICTION"] == 1
        assert snap["counts"]["UNVERIFIABLE"] == 1
        assert snap["agreement_rate"] == 0.8

    def test_rate_below_threshold_is_unhealthy(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        # 90% agreed — below the default 95% threshold.
        for _ in range(9):
            m.record(VerifierStatus.AGREED)
        m.record(VerifierStatus.LLM_CONTRADICTION)
        assert m.snapshot()["is_healthy"] is False


class TestWindowRoll:
    def test_window_overflow_drops_oldest(self) -> None:
        m = AgreementMonitor(window_size=3, threshold=0.5)
        m.record(VerifierStatus.LLM_CONTRADICTION)  # will roll off
        m.record(VerifierStatus.AGREED)
        m.record(VerifierStatus.AGREED)
        m.record(VerifierStatus.AGREED)  # pushes the oldest off
        snap = m.snapshot()
        assert snap["observed"] == 3
        assert snap["counts"]["LLM_CONTRADICTION"] == 0
        assert snap["counts"]["AGREED"] == 3


class TestIsHealthy:
    def test_empty_window_is_healthy(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.95)
        assert m.is_healthy() is True

    def test_exactly_threshold_is_healthy(self) -> None:
        m = AgreementMonitor(window_size=20, threshold=0.95)
        for _ in range(19):
            m.record(VerifierStatus.AGREED)
        m.record(VerifierStatus.LLM_CONTRADICTION)
        # 19/20 = 0.95 exactly — strict >= means healthy.
        assert m.is_healthy() is True

    def test_just_below_threshold_is_unhealthy(self) -> None:
        m = AgreementMonitor(window_size=100, threshold=0.95)
        for _ in range(94):
            m.record(VerifierStatus.AGREED)
        for _ in range(6):
            m.record(VerifierStatus.LLM_CONTRADICTION)
        # 94/100 = 0.94 < 0.95 — unhealthy.
        assert m.is_healthy() is False


class TestValidation:
    def test_zero_window_rejected(self) -> None:
        with pytest.raises(ValueError):
            AgreementMonitor(window_size=0, threshold=0.95)

    def test_negative_window_rejected(self) -> None:
        with pytest.raises(ValueError):
            AgreementMonitor(window_size=-5, threshold=0.95)

    def test_threshold_above_one_rejected(self) -> None:
        with pytest.raises(ValueError):
            AgreementMonitor(window_size=10, threshold=1.5)

    def test_threshold_below_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            AgreementMonitor(window_size=10, threshold=-0.1)

    def test_threshold_zero_accepts_everything(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=0.0)
        for _ in range(5):
            m.record(VerifierStatus.LLM_CONTRADICTION)
        assert m.is_healthy() is True

    def test_threshold_one_demands_perfection(self) -> None:
        m = AgreementMonitor(window_size=10, threshold=1.0)
        for _ in range(9):
            m.record(VerifierStatus.AGREED)
        m.record(VerifierStatus.LLM_CONTRADICTION)
        assert m.is_healthy() is False
