"""Tests for ``ski_model.ledger_client.LedgerClient``.

The real client talks to Postgres; these tests never open a socket. Two
techniques keep it hermetic:

  * ``LedgerClient.__init__`` / ``initialize`` / ``close`` only *build*
    a SQLAlchemy ``AsyncEngine`` -- engine construction and disposal are
    lazy and don't connect (SQLAlchemy connects on first use), so they
    are safe to exercise against a bogus DSN.
  * ``append`` / ``append_v3`` / ``list`` are exercised against a
    hand-rolled fake async session (``_FakeSession``) that mimics the
    ``async with session_factory() as session, session.begin(): ...``
    protocol the client uses, with canned ``execute()`` results. This
    is the same "swap the collaborator for a double" approach
    ``test_endpoint.py`` uses for the whole :class:`LedgerClient`.

Before this file, ``ledger_client.py`` had 27% line coverage from the
suite (essentially only ``canonical_entry_payload`` reachable via
import) -- everything else was exercised solely by the conformance
suite's live-Postgres tests, which are skipped without a DSN.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import pytest

from ski_model import metrics
from ski_model.ledger_client import LedgerClient, canonical_entry_payload
from ski_model.v3.envelope import (
    FormalizableAssertion,
    KGCitation,
    KGCitationRole,
    ModelProvenance,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)
from ski_model.v3.transcript import LLMTranscript

_HASH = "sha256:" + "a" * 64


# ---- Fake async session/engine plumbing ----------------------------------------


class _FakeResult:
    def __init__(self, *, first_row: Optional[Sequence[Any]] = None, all_rows: Optional[List[Any]] = None):
        self._first_row = first_row
        self._all_rows = all_rows or []

    def first(self) -> Optional[Sequence[Any]]:
        return self._first_row

    def all(self) -> List[Any]:
        return self._all_rows


class _FakeTxn:
    async def __aenter__(self) -> _FakeTxn:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakeSession:
    """Returns queued ``_FakeResult`` objects in order, one per ``execute()`` call."""

    def __init__(self, results: Sequence[_FakeResult]) -> None:
        self._results = list(results)
        self.executed: List[tuple[str, Optional[Dict[str, Any]]]] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def begin(self) -> _FakeTxn:
        return _FakeTxn()

    async def execute(self, stmt: Any, params: Optional[Dict[str, Any]] = None) -> _FakeResult:
        self.executed.append((str(stmt), params))
        return self._results.pop(0)


def _client_with_session(session: _FakeSession) -> LedgerClient:
    client = LedgerClient("postgresql://user:pass@localhost/ski")
    client._session_factory = lambda: session  # type: ignore[assignment]
    return client


def _envelope(*, verdict: V3Verdict = V3Verdict.CLEAR) -> V3VerdictEnvelope:
    return V3VerdictEnvelope(
        verdict=verdict,
        reasoning="for tests",
        kg_citations=[KGCitation(node_id="ob.x", version="v1", role=KGCitationRole.OBLIGATION)],
        formalizable_assertions=[
            FormalizableAssertion(
                predicate="must_not_exceed",
                metric="x",
                value=100,
                observed=50,
                satisfied=True,
                obligation_id="ob.x",
            )
        ],
        verifier_result=VerifierResult(status=VerifierStatus.AGREED, checked_assertions=1, divergences=[]),
        model_provenance=ModelProvenance(
            model_weight_hash=_HASH,
            kg_version_hash=_HASH,
            prompt_template_id="ski.v3.evaluate.1",
            prompt_template_hash=_HASH,
            decoder_seed=0,
            structured_grammar_hash=_HASH,
        ),
        transcript_ref="transcript:t1",
    )


def _transcript() -> LLMTranscript:
    now = datetime.now(timezone.utc)
    return LLMTranscript(
        transcript_id="t1",
        request_canonical="prompt",
        request_hash=_HASH,
        response_canonical={"verdict": "CLEAR"},
        response_hash=_HASH,
        signature_hex="ab" * 32,
        signing_key_id=_HASH,
        backend_name="fake-llm",
        started_at=now,
        completed_at=now,
    )


# ---- Construction ---------------------------------------------------------------


class TestConstruction:
    def test_empty_dsn_raises(self) -> None:
        with pytest.raises(RuntimeError, match="LEDGER_DSN is required"):
            LedgerClient("")

    def test_plain_postgresql_scheme_is_rewritten_for_psycopg(self) -> None:
        client = LedgerClient("postgresql://user:pass@host/db")
        assert client._dsn == "postgresql+psycopg://user:pass@host/db"

    def test_already_psycopg_scheme_is_left_untouched(self) -> None:
        client = LedgerClient("postgresql+psycopg://user:pass@host/db")
        assert client._dsn == "postgresql+psycopg://user:pass@host/db"

    def test_non_postgresql_scheme_is_left_untouched(self) -> None:
        client = LedgerClient("sqlite+aiosqlite:///:memory:")
        assert client._dsn == "sqlite+aiosqlite:///:memory:"


# ---- initialize / close (lazy engine — no live DB needed) ----------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_builds_engine_and_session_factory(self) -> None:
        client = LedgerClient("postgresql://user:pass@localhost:1/nonexistent")
        await client.initialize()
        assert client._engine is not None
        assert client._session_factory is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_close_disposes_engine_without_connecting(self) -> None:
        client = LedgerClient("postgresql://user:pass@localhost:1/nonexistent")
        await client.initialize()
        await client.close()  # must not raise even though nothing ever connected


# ---- canonical_entry_payload — pure function -----------------------------------


class TestCanonicalEntryPayload:
    def test_deterministic_for_identical_inputs(self) -> None:
        kwargs: Dict[str, Any] = {
            "sequence_number": 1,
            "previous_hash": "0" * 64,
            "timestamp_iso": "2026-01-01T00:00:00+00:00",
            "verdict": "CLEAR",
            "telemetry_id": "t1",
            "telemetry_hash": "h1",
            "rule_id": "r1",
            "kg_version": "v1",
            "ski_model_version": "3.1.0",
            "reasoning": "ok",
            "track": "v3-evaluator",
        }
        assert canonical_entry_payload(**kwargs) == canonical_entry_payload(**kwargs)

    def test_field_change_changes_payload(self) -> None:
        base: Dict[str, Any] = {
            "sequence_number": 1,
            "previous_hash": "0" * 64,
            "timestamp_iso": "2026-01-01T00:00:00+00:00",
            "verdict": "CLEAR",
            "telemetry_id": "t1",
            "telemetry_hash": "h1",
            "rule_id": "r1",
            "kg_version": "v1",
            "ski_model_version": "3.1.0",
            "reasoning": "ok",
            "track": "v3-evaluator",
        }
        changed = {**base, "verdict": "FLAG"}
        assert canonical_entry_payload(**base) != canonical_entry_payload(**changed)

    def test_none_optional_fields_serialise_as_json_null(self) -> None:
        payload = canonical_entry_payload(
            sequence_number=1,
            previous_hash="0" * 64,
            timestamp_iso="2026-01-01T00:00:00+00:00",
            verdict="NULL_UNMAPPED",
            telemetry_id="t1",
            telemetry_hash="h1",
            rule_id=None,
            kg_version=None,
            ski_model_version="3.1.0",
            reasoning=None,
            track=None,
        )
        assert b'"rule_id":null' in payload
        assert b'"track":null' in payload


# ---- append() — v2-shape ledger entries ----------------------------------------


class TestAppend:
    @pytest.mark.asyncio
    async def test_first_append_to_empty_ledger_uses_genesis_hash(self) -> None:
        session = _FakeSession([_FakeResult(first_row=None), _FakeResult()])
        client = _client_with_session(session)
        await client.append(
            verdict=V3Verdict.CLEAR,
            telemetry_id="t1",
            telemetry_hash="h1",
            rule_id="r1",
            kg_version="v1",
            ski_model_version="3.1.0",
            reasoning="ok",
            track="v3-evaluator",
        )
        # Two statements: the SELECT for the current head, then the INSERT.
        assert len(session.executed) == 2
        insert_params = session.executed[1][1]
        assert insert_params is not None
        assert insert_params["seq"] == 1
        assert insert_params["prev"] == "0" * 64

    @pytest.mark.asyncio
    async def test_second_append_chains_off_the_existing_head(self) -> None:
        prev_hash = "f" * 64
        session = _FakeSession([_FakeResult(first_row=(5, prev_hash)), _FakeResult()])
        client = _client_with_session(session)
        await client.append(
            verdict=V3Verdict.FLAG,
            telemetry_id="t2",
            telemetry_hash="h2",
            rule_id="r1",
            kg_version="v1",
            ski_model_version="3.1.0",
            reasoning="breach",
            track="v3-evaluator",
        )
        insert_params = session.executed[1][1]
        assert insert_params is not None
        assert insert_params["seq"] == 6
        assert insert_params["prev"] == prev_hash

    @pytest.mark.asyncio
    async def test_sequence_gap_is_detected_and_counted(self) -> None:
        """This process is the single writer; once it knows the expected next
        sequence, any other head means rows appeared/vanished underneath it."""
        before = metrics.LEDGER_SEQUENCE_GAPS._value.get()

        # First append: empty ledger -> seq=1, expected_next becomes 2.
        session1 = _FakeSession([_FakeResult(first_row=None), _FakeResult()])
        client = _client_with_session(session1)
        await client.append(
            verdict=V3Verdict.CLEAR,
            telemetry_id="t1",
            telemetry_hash="h1",
            rule_id="r1",
            kg_version="v1",
            ski_model_version="3.1.0",
            reasoning="ok",
            track="v3-evaluator",
        )
        assert client._expected_next_seq == 2

        # Second append: ledger head jumped to seq=9 underneath us (tamper /
        # concurrent writer) instead of the expected seq=2.
        session2 = _FakeSession([_FakeResult(first_row=(9, "b" * 64)), _FakeResult()])
        client._session_factory = lambda: session2  # type: ignore[assignment]
        await client.append(
            verdict=V3Verdict.CLEAR,
            telemetry_id="t2",
            telemetry_hash="h2",
            rule_id="r1",
            kg_version="v1",
            ski_model_version="3.1.0",
            reasoning="ok",
            track="v3-evaluator",
        )
        after = metrics.LEDGER_SEQUENCE_GAPS._value.get()
        assert after == before + 1


# ---- append_v3() — envelope + transcript ledger entries ------------------------


class TestAppendV3:
    @pytest.mark.asyncio
    async def test_appends_envelope_with_transcript(self) -> None:
        session = _FakeSession([_FakeResult(first_row=None), _FakeResult()])
        client = _client_with_session(session)
        await client.append_v3(
            envelope=_envelope(),
            transcript=_transcript(),
            telemetry_id="t1",
            telemetry_hash="h1",
            rule_id="ob.x",
            kg_version="v1",
            ski_model_version="3.1.0",
        )
        insert_params = session.executed[1][1]
        assert insert_params is not None
        assert insert_params["verdict"] == "CLEAR"
        assert insert_params["envelope_hash"].startswith("sha256:")
        assert insert_params["transcript_json"] is not None
        assert insert_params["signing_key_id"] == _HASH
        assert insert_params["verifier_status"] == "AGREED"

    @pytest.mark.asyncio
    async def test_appends_envelope_without_transcript(self) -> None:
        """Deployments without a signer still produce a valid ledger entry --
        transcript-shaped columns are simply NULL, not a crash."""
        session = _FakeSession([_FakeResult(first_row=None), _FakeResult()])
        client = _client_with_session(session)
        await client.append_v3(
            envelope=_envelope(verdict=V3Verdict.DISCRETIONARY),
            transcript=None,
            telemetry_id="t1",
            telemetry_hash="h1",
            rule_id=None,
            kg_version="v1",
            ski_model_version="3.1.0",
        )
        insert_params = session.executed[1][1]
        assert insert_params is not None
        assert insert_params["transcript_json"] is None
        assert insert_params["transcript_signature"] is None
        assert insert_params["signing_key_id"] is None

    @pytest.mark.asyncio
    async def test_chains_off_existing_ledger_head(self) -> None:
        prev_hash = "c" * 64
        session = _FakeSession([_FakeResult(first_row=(3, prev_hash)), _FakeResult()])
        client = _client_with_session(session)
        await client.append_v3(
            envelope=_envelope(),
            transcript=None,
            telemetry_id="t1",
            telemetry_hash="h1",
            rule_id="ob.x",
            kg_version="v1",
            ski_model_version="3.1.0",
        )
        insert_params = session.executed[1][1]
        assert insert_params is not None
        assert insert_params["seq"] == 4
        assert insert_params["prev"] == prev_hash

    @pytest.mark.asyncio
    async def test_default_track_label(self) -> None:
        session = _FakeSession([_FakeResult(first_row=None), _FakeResult()])
        client = _client_with_session(session)
        await client.append_v3(
            envelope=_envelope(),
            transcript=None,
            telemetry_id="t1",
            telemetry_hash="h1",
            rule_id=None,
            kg_version="v1",
            ski_model_version="3.1.0",
        )
        insert_params = session.executed[1][1]
        assert insert_params is not None
        assert insert_params["track"] == "v3-evaluator"


# ---- list() — paginated read path ------------------------------------------------


class TestList:
    @pytest.mark.asyncio
    async def test_maps_rows_with_datetime_timestamp(self) -> None:
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        row = (1, ts, "CLEAR", "t1", "r1", "v1", "3.1.0", "ok", "v3-evaluator", "hash1", "0" * 64)
        session = _FakeSession([_FakeResult(all_rows=[row])])
        client = _client_with_session(session)
        entries = await client.list(limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0]["sequence_number"] == 1
        assert entries[0]["timestamp"] == ts.isoformat()
        assert entries[0]["verdict"] == "CLEAR"

    @pytest.mark.asyncio
    async def test_maps_rows_with_string_timestamp(self) -> None:
        """Some drivers hand back the raw column value rather than a
        datetime; the mapper must not assume ``.isoformat()`` exists."""
        row = (2, "2026-01-15T12:00:00+00:00", "FLAG", "t2", "r1", "v1", "3.1.0", "breach", "v3", "h2", "h1")
        session = _FakeSession([_FakeResult(all_rows=[row])])
        client = _client_with_session(session)
        entries = await client.list(limit=10, offset=0)
        assert entries[0]["timestamp"] == "2026-01-15T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_empty_ledger_returns_empty_list(self) -> None:
        session = _FakeSession([_FakeResult(all_rows=[])])
        client = _client_with_session(session)
        entries = await client.list(limit=10, offset=0)
        assert entries == []
