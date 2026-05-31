"""Tests for stateful predicates in SymbolicVerifier (PR 11.6).

Stateful predicates query historical telemetry via a BufferLike object.
This module uses an in-memory FakeBuffer; no live database is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from ski_model.v3 import (
    BufferLike,
    FormalizableAssertion,
    SymbolicVerifier,
    V3Verdict,
    VerifierStatus,
)

# ---- Fixtures -----------------------------------------------------------------


@dataclass
class FakeBuffer:
    """In-memory BufferLike that returns pre-baked window data.

    The ``data`` field maps ``(subject, metric_path)`` to a list of
    ``(timestamp, value)`` tuples. The fake returns rows whose timestamp
    falls in ``[as_of - window_seconds, as_of]``. Sufficient for testing
    the predicate logic without a real telemetry buffer.
    """

    data: Dict[Tuple[str, str], List[Tuple[datetime, float]]] = field(default_factory=dict)

    async def window_query(
        self,
        *,
        subject: str,
        as_of: datetime,
        window_seconds: int,
        metric_path: Optional[str] = None,
    ) -> List[Tuple[datetime, float]]:
        key = (subject, metric_path or "")
        rows = self.data.get(key, [])
        cutoff_low = as_of.timestamp() - window_seconds
        cutoff_high = as_of.timestamp()
        return [(ts, v) for ts, v in rows if cutoff_low <= ts.timestamp() <= cutoff_high]


def _assertion(
    *,
    predicate: str,
    metric: str = "so2_ppm",
    value: Any = 100,
    observed: Any = None,
    satisfied: bool = True,
    obligation_id: str = "ob.x",
    window_seconds: Optional[int] = None,
) -> FormalizableAssertion:
    return FormalizableAssertion(
        predicate=predicate,
        metric=metric,
        value=value,
        observed=observed,
        satisfied=satisfied,
        obligation_id=obligation_id,
        window_seconds=window_seconds,
    )


_AS_OF = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds_ago: int) -> datetime:
    return datetime.fromtimestamp(_AS_OF.timestamp() - seconds_ago, tz=timezone.utc)


# ---- must_average_within ------------------------------------------------------


class TestMustAverageWithin:
    @pytest.mark.asyncio
    async def test_agreed_when_average_is_in_range(self) -> None:
        v = SymbolicVerifier()
        buffer = FakeBuffer(
            data={
                ("emissions", "so2_ppm"): [
                    (_ts(100), 60.0),
                    (_ts(50), 70.0),
                    (_ts(10), 80.0),
                ]
            }
        )
        result = await v.averify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[50.0, 100.0],
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=buffer,
        )
        assert result.status == VerifierStatus.AGREED.value

    @pytest.mark.asyncio
    async def test_llm_contradicts_when_average_above_range(self) -> None:
        v = SymbolicVerifier()
        buffer = FakeBuffer(
            data={
                ("emissions", "so2_ppm"): [
                    (_ts(100), 120.0),
                    (_ts(50), 130.0),
                ]
            }
        )
        # LLM said satisfied=True; mechanical average is 125 > 100 → False.
        result = await v.averify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[0.0, 100.0],
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=buffer,
        )
        assert result.status == VerifierStatus.LLM_CONTRADICTION.value

    @pytest.mark.asyncio
    async def test_unverifiable_without_buffer(self) -> None:
        v = SymbolicVerifier()
        result = await v.averify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[0.0, 100.0],
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=None,
        )
        assert result.status == VerifierStatus.UNVERIFIABLE.value
        assert any("buffer" in d for d in result.divergences)

    @pytest.mark.asyncio
    async def test_unverifiable_without_window_seconds(self) -> None:
        v = SymbolicVerifier()
        buffer = FakeBuffer()
        result = await v.averify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[0.0, 100.0],
                    satisfied=True,
                    window_seconds=None,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=buffer,
        )
        assert result.status == VerifierStatus.UNVERIFIABLE.value

    @pytest.mark.asyncio
    async def test_unverifiable_with_empty_window(self) -> None:
        v = SymbolicVerifier()
        buffer = FakeBuffer(data={("emissions", "so2_ppm"): []})
        result = await v.averify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[0.0, 100.0],
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=buffer,
        )
        assert result.status == VerifierStatus.UNVERIFIABLE.value
        assert any("No samples" in d for d in result.divergences)


# ---- must_not_exceed_in_window ------------------------------------------------


class TestMustNotExceedInWindow:
    @pytest.mark.asyncio
    async def test_agreed_when_peak_under_threshold(self) -> None:
        v = SymbolicVerifier()
        buffer = FakeBuffer(
            data={
                ("emissions", "so2_ppm"): [
                    (_ts(120), 80.0),
                    (_ts(60), 90.0),
                ]
            }
        )
        result = await v.averify(
            [
                _assertion(
                    predicate="must_not_exceed_in_window",
                    value=100,
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=buffer,
        )
        assert result.status == VerifierStatus.AGREED.value

    @pytest.mark.asyncio
    async def test_llm_contradicts_when_peak_exceeds(self) -> None:
        v = SymbolicVerifier()
        buffer = FakeBuffer(
            data={
                ("emissions", "so2_ppm"): [
                    (_ts(60), 90.0),
                    (_ts(30), 150.0),
                ]
            }
        )
        # LLM said satisfied=True; verifier sees a 150 peak > 100.
        result = await v.averify(
            [
                _assertion(
                    predicate="must_not_exceed_in_window",
                    value=100,
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=buffer,
        )
        assert result.status == VerifierStatus.LLM_CONTRADICTION.value


# ---- Buffer return-shape coercion --------------------------------------------


class TestBufferShapes:
    @pytest.mark.asyncio
    async def test_buffer_returning_dicts_with_value_key_works(self) -> None:
        v = SymbolicVerifier()

        class DictBuffer:
            async def window_query(self, **kwargs: Any) -> Any:
                return [{"value": 70.0}, {"value": 80.0}, {"value": 90.0}]

        result = await v.averify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[50.0, 100.0],
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=DictBuffer(),
        )
        assert result.status == VerifierStatus.AGREED.value

    @pytest.mark.asyncio
    async def test_buffer_returning_bare_floats_works(self) -> None:
        v = SymbolicVerifier()

        class BareFloatsBuffer:
            async def window_query(self, **kwargs: Any) -> Any:
                return [70.0, 80.0, 90.0]

        result = await v.averify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[50.0, 100.0],
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=BareFloatsBuffer(),
        )
        assert result.status == VerifierStatus.AGREED.value


# ---- Sync verify() degradation for stateful predicates ------------------------


class TestSyncVerifyDegradesStateful:
    def test_stateful_predicate_in_sync_path_yields_unverifiable(self) -> None:
        v = SymbolicVerifier()
        # Calling the sync verify() with a stateful predicate must NOT crash;
        # it must return UNVERIFIABLE so the caller knows to switch to averify().
        result = v.verify(
            [
                _assertion(
                    predicate="must_average_within",
                    value=[0.0, 100.0],
                    satisfied=True,
                    window_seconds=300,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
        )
        assert result.status == VerifierStatus.UNVERIFIABLE.value
        assert any("stateful" in d.lower() for d in result.divergences)


# ---- Mixed (stateless + stateful) assertions in one envelope ------------------


class TestMixedAssertions:
    @pytest.mark.asyncio
    async def test_one_stateless_plus_one_stateful_both_agree(self) -> None:
        v = SymbolicVerifier()
        buffer = FakeBuffer(data={("emissions", "ph"): [(_ts(60), 7.0), (_ts(30), 7.5)]})
        assertions = [
            _assertion(
                predicate="must_not_exceed",
                metric="so2_ppm",
                value=100,
                observed=50,
                satisfied=True,
                obligation_id="ob.stateless",
            ),
            _assertion(
                predicate="must_average_within",
                metric="ph",
                value=[6.0, 8.5],
                satisfied=True,
                obligation_id="ob.stateful",
                window_seconds=120,
            ),
        ]
        result = await v.averify(
            assertions,
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=buffer,
        )
        assert result.status == VerifierStatus.AGREED.value
        assert result.checked_assertions == 2


# ---- Envelope round-trip with window_seconds field ----------------------------


class TestEnvelopeWindowField:
    def test_window_seconds_round_trips(self) -> None:
        # Confirm the new envelope field round-trips through Pydantic.
        a = FormalizableAssertion(
            predicate="must_average_within",
            metric="ph",
            value=[6.0, 8.5],
            observed=None,
            satisfied=True,
            obligation_id="ob.x",
            window_seconds=86400,
        )
        text = a.model_dump_json()
        reparsed = FormalizableAssertion.model_validate_json(text)
        assert reparsed.window_seconds == 86400

    def test_window_seconds_must_be_positive(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FormalizableAssertion(
                predicate="must_average_within",
                metric="ph",
                value=[6.0, 8.5],
                observed=None,
                satisfied=True,
                obligation_id="ob.x",
                window_seconds=0,
            )


# ---- BufferLike protocol coverage ---------------------------------------------


class TestBufferLikeProtocol:
    def test_fake_buffer_satisfies_protocol(self) -> None:
        # runtime_checkable Protocols would let isinstance work, but we
        # just confirm FakeBuffer exposes the expected attribute.
        b: BufferLike = FakeBuffer()
        assert hasattr(b, "window_query")
