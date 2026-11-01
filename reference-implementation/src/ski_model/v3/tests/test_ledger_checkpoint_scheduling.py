"""The runtime checkpoints the ledger every SKI_LEDGER_CHECKPOINT_EVERY entries (ledger format 5)."""

from __future__ import annotations

import asyncio
from typing import Any, Iterator, Optional

import pytest

from ski_model import metrics, server
from ski_model.timestamping import TimestampError


class _Ledger:
    format5 = True
    tenant_id = "default"
    signer: Any = object()

    def __init__(self, uncovered: int, tsa_fails: bool = False) -> None:
        self.uncovered = uncovered
        self.tsa_fails = tsa_fails
        self.checkpoints: list[Optional[Any]] = []

    async def entries_since_checkpoint(self) -> int:
        return self.uncovered

    async def checkpoint(self, tsa: Optional[Any] = None) -> Optional[dict[str, Any]]:
        if tsa is not None and self.tsa_fails:
            raise TimestampError("TSA refused")
        self.checkpoints.append(tsa)
        return {"tree_size": self.uncovered}


@pytest.fixture
def restore_state() -> Iterator[None]:
    saved = (
        server.state.ledger,
        server.state.checkpoint_every,
        server.state.tsa,
        server.state.checkpoint_task,
    )
    yield
    server.state.ledger, server.state.checkpoint_every, server.state.tsa, server.state.checkpoint_task = saved


async def _run(ledger: _Ledger, every: int, tsa: Any = None) -> None:
    server.state.ledger = ledger  # type: ignore[assignment]
    server.state.checkpoint_every = every
    server.state.tsa = tsa
    server.state.checkpoint_task = None
    server._maybe_checkpoint()
    task = _started_task()
    if task is not None:
        await task


def _started_task() -> Optional[asyncio.Task[None]]:
    """The task _maybe_checkpoint started, read after the call (not narrowed by the reset above)."""
    return server.state.checkpoint_task


@pytest.mark.parametrize("uncovered, every, made", [(999, 1000, 0), (1000, 1000, 1), (5, 0, 0)])
async def test_checkpoints_every_n_entries(
    restore_state: None, uncovered: int, every: int, made: int
) -> None:
    ledger = _Ledger(uncovered)
    await _run(ledger, every)
    assert len(ledger.checkpoints) == made


async def test_format4_ledger_makes_no_checkpoints(restore_state: None) -> None:
    ledger = _Ledger(5000)
    ledger.format5 = False
    await _run(ledger, 1)
    assert ledger.checkpoints == []


async def test_a_failing_tsa_still_leaves_a_signed_checkpoint(restore_state: None) -> None:
    before = metrics.LEDGER_CHECKPOINTS.labels(timestamped="false")._value.get()
    ledger = _Ledger(10, tsa_fails=True)
    await _run(ledger, 10, tsa=object())
    assert ledger.checkpoints == [None]  # signed, not time-stamped
    assert metrics.LEDGER_CHECKPOINTS.labels(timestamped="false")._value.get() == before + 1


async def test_one_checkpoint_at_a_time(restore_state: None) -> None:
    ledger = _Ledger(10)
    server.state.ledger = ledger  # type: ignore[assignment]
    server.state.checkpoint_every = 10
    server.state.tsa = None
    blocker = asyncio.get_running_loop().create_future()
    server.state.checkpoint_task = asyncio.ensure_future(blocker)
    server._maybe_checkpoint()  # one is still running: no second task
    assert server.state.checkpoint_task is not None and not server.state.checkpoint_task.done()
    blocker.set_result(None)
    await server.state.checkpoint_task
    assert ledger.checkpoints == []
