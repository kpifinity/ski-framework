"""Telemetry buffer implementation.

Wraps the Postgres ``telemetry_buffer`` table with a small, typed Python
API. The SKI Model writes every accepted telemetry record here before
evaluation; the Symbolic Evaluator queries here when a rule has a
stateful predicate.

All queries pass the telemetry's own timestamp as the "now" — wall-clock
is never consulted. This is what makes deterministic replay possible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class BufferError(RuntimeError):
    """Raised on buffer write/query failures."""


@dataclass(frozen=True)
class WindowQueryResult:
    """Result of a window query over the buffer.

    Fields:
      * count: number of records in the window
      * sum_value: sum of ``measurement.<metric>.value`` over the window
                   (None if no records or metric missing)
      * avg_value: arithmetic mean (None if no records or metric missing)
      * oldest_ts / newest_ts: bounds of records actually found
      * last_ts: timestamp of the most recent record for the subject
                 (may equal newest_ts; included for since_last queries)
    """

    count: int
    sum_value: Optional[float]
    avg_value: Optional[float]
    oldest_ts: Optional[datetime]
    newest_ts: Optional[datetime]
    last_ts: Optional[datetime]


def canonical_measurement_hash(measurement: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the measurement object.

    Matches the canonicalisation used elsewhere in the codebase
    (sort_keys, no whitespace, ensure_ascii=False, UTF-8). This is the
    same value stored in ``ledger_entries.telemetry_hash``, which lets
    operators cross-reference buffer rows against ledger entries.
    """
    return hashlib.sha256(
        json.dumps(measurement, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class TelemetryBuffer:
    """Async handle around the ``telemetry_buffer`` table.

    Instances are cheap; one is held by the SKI Model service for its
    lifetime. The underlying connection pool is managed by the
    SQLAlchemy ``AsyncEngine`` shared with the LedgerClient.
    """

    def __init__(self, engine: AsyncEngine, *, tenant_id: str = "default") -> None:
        self._engine = engine
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def append(
        self,
        *,
        subject: str,
        telemetry_id: str,
        telemetry_ts: datetime,
        measurement: dict[str, Any],
    ) -> None:
        """Append one telemetry record to the buffer.

        Called by the SKI Model service after the record is accepted but
        before evaluation runs. Idempotency is not enforced here — if
        the producer retries with the same telemetry_id, we accept both
        copies. (The ledger entry hash will catch the duplicate at the
        verdict layer.)
        """
        measurement_hash = canonical_measurement_hash(measurement)
        async with self._sessions() as session, session.begin():
            await session.execute(
                text(
                    """
                        INSERT INTO telemetry_buffer (
                            tenant_id, subject, telemetry_id, telemetry_ts,
                            measurement, measurement_hash
                        ) VALUES (
                            :tenant_id, :subject, :telemetry_id, :telemetry_ts,
                            CAST(:measurement AS JSONB), :measurement_hash
                        )
                        """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "subject": subject,
                    "telemetry_id": telemetry_id,
                    "telemetry_ts": telemetry_ts,
                    "measurement": json.dumps(measurement),
                    "measurement_hash": measurement_hash,
                },
            )

    # ------------------------------------------------------------------
    # Query path — window predicates
    # ------------------------------------------------------------------

    async def window_query(
        self,
        *,
        subject: str,
        as_of: datetime,
        window_seconds: int,
        metric_path: Optional[str] = None,
    ) -> WindowQueryResult:
        """Aggregate records for ``subject`` over the last ``window_seconds`` ending at ``as_of``.

        ``as_of`` is the telemetry timestamp of the *current* evaluation;
        we look back ``window_seconds`` from there. Records strictly
        younger than ``as_of`` are included to match a typical
        "last N seconds" intuition; this is documented in the predicate
        grammar (see docs/KNOWLEDGE_GRAPH.md).

        ``metric_path`` is a dotted path into the JSON measurement
        (e.g. "so2_ppm.value"). When provided, sum_value and avg_value
        are computed over numeric values found at that path; rows where
        the path resolves to null are ignored.
        """
        if window_seconds <= 0:
            raise BufferError(f"window_seconds must be positive, got {window_seconds}")
        window_start = as_of - timedelta(seconds=window_seconds)

        # Always compute count + ts bounds.
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                            COUNT(*)                       AS cnt,
                            MIN(telemetry_ts)              AS oldest_ts,
                            MAX(telemetry_ts)              AS newest_ts
                        FROM telemetry_buffer
                        WHERE tenant_id = :tenant_id
                          AND subject = :subject
                          AND telemetry_ts > :window_start
                          AND telemetry_ts <= :as_of
                        """
                    ),
                    {
                        "tenant_id": self._tenant_id,
                        "subject": subject,
                        "window_start": window_start,
                        "as_of": as_of,
                    },
                )
            ).one()
            count = int(row[0])
            oldest_ts: Optional[datetime] = row[1]
            newest_ts: Optional[datetime] = row[2]

            sum_value: Optional[float] = None
            avg_value: Optional[float] = None
            if metric_path and count > 0:
                # The metric path is dotted; build a #>'{a,b,c}' Postgres
                # JSON access expression. We split on '.' and parameterise
                # as a text array to avoid SQL injection.
                path_parts = metric_path.split(".")
                # Postgres JSONB extraction: measurement #> ARRAY['a','b','c']
                # cast to numeric — non-numeric values become NULL via NULLIF.
                agg_row = (
                    await session.execute(
                        text(
                            """
                            SELECT
                                SUM((measurement #> :path)::text::numeric) AS s,
                                AVG((measurement #> :path)::text::numeric) AS a
                            FROM telemetry_buffer
                            WHERE tenant_id = :tenant_id
                              AND subject = :subject
                              AND telemetry_ts > :window_start
                              AND telemetry_ts <= :as_of
                              AND (measurement #> :path) IS NOT NULL
                              AND jsonb_typeof(measurement #> :path) = 'number'
                            """
                        ),
                        {
                            "tenant_id": self._tenant_id,
                            "subject": subject,
                            "window_start": window_start,
                            "as_of": as_of,
                            "path": "{" + ",".join(path_parts) + "}",
                        },
                    )
                ).one()
                sum_value = float(agg_row[0]) if agg_row[0] is not None else None
                avg_value = float(agg_row[1]) if agg_row[1] is not None else None

        return WindowQueryResult(
            count=count,
            sum_value=sum_value,
            avg_value=avg_value,
            oldest_ts=oldest_ts,
            newest_ts=newest_ts,
            last_ts=newest_ts,
        )

    async def last_record_ts(
        self,
        *,
        subject: str,
        as_of: datetime,
    ) -> Optional[datetime]:
        """Return the timestamp of the most recent record at-or-before ``as_of``.

        Used by ``since_last`` and ``debounce`` predicates. Returns None
        when the subject has no records on or before ``as_of`` (a stale /
        unseen subject).
        """
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT MAX(telemetry_ts)
                        FROM telemetry_buffer
                        WHERE tenant_id = :tenant_id
                          AND subject = :subject
                          AND telemetry_ts <= :as_of
                        """
                    ),
                    {
                        "tenant_id": self._tenant_id,
                        "subject": subject,
                        "as_of": as_of,
                    },
                )
            ).one()
        result: Optional[datetime] = row[0]
        return result

    async def has_fresh_sample(
        self,
        *,
        subject: str,
        as_of: datetime,
        within_seconds: int,
    ) -> bool:
        """True if at least one record exists in the last ``within_seconds``.

        Used by the ``requires_recent_within_seconds`` rule property to
        decide between NULL_STALE and continuing to evaluate.
        """
        if within_seconds <= 0:
            raise BufferError(f"within_seconds must be positive, got {within_seconds}")
        last_ts = await self.last_record_ts(subject=subject, as_of=as_of)
        if last_ts is None:
            return False
        return (as_of - last_ts).total_seconds() <= within_seconds

    # ------------------------------------------------------------------
    # Replay helper
    # ------------------------------------------------------------------

    async def fetch_at(
        self,
        *,
        telemetry_hash: str,
    ) -> Optional[dict[str, Any]]:
        """Return the buffer row matching a given measurement_hash, if any.

        Used during deterministic replay: the ledger entry references
        ``telemetry_hash``; we look up the corresponding buffer row to
        re-run evaluation.
        """
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT subject, telemetry_id, telemetry_ts, measurement
                        FROM telemetry_buffer
                        WHERE tenant_id = :tenant_id
                          AND measurement_hash = :measurement_hash
                        ORDER BY telemetry_ts DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": self._tenant_id,
                        "measurement_hash": telemetry_hash,
                    },
                )
            ).first()
        if row is None:
            return None
        return {
            "subject": row[0],
            "telemetry_id": row[1],
            "telemetry_ts": row[2],
            "measurement": row[3],
        }
