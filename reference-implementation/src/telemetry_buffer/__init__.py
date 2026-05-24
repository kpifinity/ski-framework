"""Telemetry buffer — append-only, time-window-queryable store.

The buffer holds recent telemetry records so the Symbolic Evaluator
(Track 1) can answer stateful predicates: window_count, window_sum,
window_avg, since_last, debounce, requires_recent_within_seconds.

Design choices live in docs/RFCs/0001-stateful-evaluation.md. Key
invariants:

  * The telemetry record's own timestamp is the authoritative clock.
    Never wall-clock at arrival.
  * Append-only at the database layer (Postgres triggers).
  * Per-tenant retention; no default value baked in.
  * Single-writer per shard, matching the SKI Model service's
    single-worker invariant.

This package exposes two classes:

  * `TelemetryBuffer` — write + query handle used by the SKI Model.
  * `WindowQueryResult` — typed result returned by window queries.
"""

from .buffer import TelemetryBuffer, WindowQueryResult, BufferError

__all__ = ["TelemetryBuffer", "WindowQueryResult", "BufferError"]
