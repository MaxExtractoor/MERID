"""Off-loop settlement-write validation (2026-10-31 stall fix).

Before the fix, ``record_settlement_proceeds`` ran sqlite connect/insert/
commit plus ``time.sleep`` retry backoff *on the uvicorn event loop* — a
contended DB blocked the whole loop for tens of seconds (cycle-hang dumps
captured it). The DB work now runs on a dedicated single-worker executor;
in-memory registration stays on the calling loop thread.

Covered lifecycle: queued -> running -> committed | failed | unresolved.
A caller timeout leaves the op tracked (durable identity reconciles it);
it never spawns a duplicate write. Acceptance per the incident plan:
"settlement persistence was intentionally slow, but the event loop
continued making progress and accounting remained correct."

Run standalone (conftest deadlocks against the live server):
    pytest --noconftest tests/event_venues/kalshi/test_settlement_offloop.py
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
    SettlementProceedsWriteError,
)
from merid.utils.stack_dump_timer import DumpBudget, StackDumpTimer

TICKER = "KXBTC15M-26031-1800"
SETTLE_ID = f"settlement:{TICKER}:yes"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_ENV", "testing")
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(tmp_path / "fills.db"))
    monkeypatch.setenv(
        "MERID_FILLS_INTENT_INDEX_PATH", str(tmp_path / "idx.json")
    )
    monkeypatch.setenv("MERID_CB_HTTP_WATERMARK_PATH", str(tmp_path / "cb.json"))
    return KalshiFillsLedger()


# ---------------------------------------------------------------------------
# 1. Slow persistence — event loop keeps making progress
# ---------------------------------------------------------------------------


async def test_slow_write_keeps_loop_responsive(ledger, monkeypatch):
    await ledger.ensure_loaded()
    real = ledger._settlement_proceeds_db_write

    def slow(*a, **k):
        time.sleep(0.4)  # simulated contended DB, on the worker thread
        return real(*a, **k)

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", slow)

    ticks = 0
    stop = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.01)

    t = asyncio.ensure_future(ticker())
    written = await ledger.record_settlement_proceeds_async(
        TICKER, "yes", yes_count=2.0, timeout_s=30
    )
    stop.set()
    await t

    assert ticks > 5  # loop progressed through the 0.4s blocked write
    assert written == 1
    assert SETTLE_ID in ledger._fills
    assert ledger._settlement_write_stats["committed"] == 1


# ---------------------------------------------------------------------------
# 2. Worker delay is visible — caller is not acked before commit
# ---------------------------------------------------------------------------


async def test_delayed_write_is_tracked_not_acked(ledger, monkeypatch):
    gate = threading.Event()

    def blocked(*a, **k):
        gate.wait(10)
        return 0

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", blocked)
    try:
        task = asyncio.ensure_future(
            ledger.record_settlement_proceeds_async(
                TICKER, "yes", yes_count=2.0, timeout_s=30
            )
        )
        await asyncio.sleep(0.1)
        assert not task.done()
        inner = ledger._settlement_inflight.get(TICKER)
        assert inner is not None and not inner.done()
        assert SETTLE_ID not in ledger._fills
    finally:
        gate.set()
    assert await task == 0


# ---------------------------------------------------------------------------
# 3. Repeated polls during the delay — coalesced, never duplicated
# ---------------------------------------------------------------------------


async def test_repeated_polls_coalesce(ledger, monkeypatch):
    gate = threading.Event()
    calls = []

    def blocked(*a, **k):
        calls.append(1)
        gate.wait(10)
        return 0

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", blocked)
    try:
        t1 = asyncio.ensure_future(
            ledger.record_settlement_proceeds_async(
                TICKER, "yes", yes_count=2.0, timeout_s=30
            )
        )
        await asyncio.sleep(0.05)
        t2 = asyncio.ensure_future(
            ledger.record_settlement_proceeds_async(
                TICKER, "yes", yes_count=2.0, timeout_s=30
            )
        )
        await asyncio.sleep(0.05)
        assert len(calls) == 1
        assert len(ledger._settlement_inflight) == 1
    finally:
        gate.set()
    await asyncio.gather(t1, t2)
    assert len(calls) == 1  # one durable op for the whole burst
    assert ledger._settlement_write_stats["coalesced"] == 1


# ---------------------------------------------------------------------------
# 4. Caller timeout — outcome unresolved, op continues, no blind retry
# ---------------------------------------------------------------------------


async def test_timeout_marks_unresolved_and_never_retries(
    ledger, monkeypatch
):
    gate = threading.Event()
    calls = []

    def blocked(*a, **k):
        calls.append(1)
        gate.wait(10)
        return 0

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", blocked)
    try:
        with pytest.raises(asyncio.TimeoutError):
            await ledger.record_settlement_proceeds_async(
                TICKER, "yes", yes_count=2.0, timeout_s=0.15
            )
        assert ledger._settlement_write_stats["unresolved"] == 1
        # The underlying op is still tracked — a poller re-delivery must
        # coalesce onto it rather than spawning a second write.
        t2 = asyncio.ensure_future(
            ledger.record_settlement_proceeds_async(
                TICKER, "yes", yes_count=2.0, timeout_s=30
            )
        )
        await asyncio.sleep(0.05)
        assert len(calls) == 1
    finally:
        gate.set()
    await t2
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# 5. Commit failure — surfaces explicitly, nothing registered
# ---------------------------------------------------------------------------


async def test_commit_failure_propagates(ledger, monkeypatch):
    def boom(*a, **k):
        raise SettlementProceedsWriteError("simulated write exhaustion")

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", boom)
    with pytest.raises(SettlementProceedsWriteError):
        await ledger.record_settlement_proceeds_async(
            TICKER, "yes", yes_count=2.0, timeout_s=30
        )
    assert ledger._settlement_write_stats["failed"] == 1
    assert SETTLE_ID not in ledger._fills


# ---------------------------------------------------------------------------
# 6. In-flight at caller abandonment — late commit still registers
# ---------------------------------------------------------------------------


async def test_late_completion_registers_on_loop(ledger, monkeypatch):
    await ledger.ensure_loaded()
    gate = threading.Event()
    real = ledger._settlement_proceeds_db_write

    def blocked(*a, **k):
        gate.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", blocked)
    try:
        with pytest.raises(asyncio.TimeoutError):
            await ledger.record_settlement_proceeds_async(
                TICKER, "yes", yes_count=2.0, timeout_s=0.15
            )
        assert SETTLE_ID not in ledger._fills
        task = ledger._settlement_inflight.get(TICKER)
        assert task is not None and not task.done()
    finally:
        gate.set()
    assert await task == 1
    # Registration rode inside the tracked task on the loop — the row is
    # visible in-memory even though the original caller already timed out.
    assert SETTLE_ID in ledger._fills


# ---------------------------------------------------------------------------
# 7. Restart after ambiguous completion — durable identity reconciles
# ---------------------------------------------------------------------------


async def test_restart_redelivery_is_idempotent(ledger, tmp_path, monkeypatch):
    await ledger.ensure_loaded()
    written = await ledger.record_settlement_proceeds_async(
        TICKER, "yes", yes_count=2.0, timeout_s=30
    )
    assert written == 1

    ledger2 = KalshiFillsLedger()
    await ledger2.ensure_loaded()  # reloads durable rows, incl. settlement leg
    written2 = await ledger2.record_settlement_proceeds_async(
        TICKER, "yes", yes_count=2.0, timeout_s=30
    )
    assert written2 == 0  # INSERT OR IGNORE — no duplicate row
    assert SETTLE_ID in ledger2._fills


# ---------------------------------------------------------------------------
# 8. Readiness enforcement — the surface the entry gate consumes
# ---------------------------------------------------------------------------


def test_health_ok_when_idle(ledger):
    health = ledger.settlement_write_health()
    assert health["ok"] is True
    assert health["reason"] is None
    assert health["pending_unresolved"] == 0


async def test_health_blocked_by_failure_then_cleared(ledger, monkeypatch):
    await ledger.ensure_loaded()

    def boom(*a, **k):
        raise SettlementProceedsWriteError("simulated write exhaustion")

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", boom)
    with pytest.raises(SettlementProceedsWriteError):
        await ledger.record_settlement_proceeds_async(
            TICKER, "yes", yes_count=2.0, timeout_s=30
        )
    health = ledger.settlement_write_health()
    assert health["ok"] is False
    assert health["reason"] == "settlement_write_failed"

    # A subsequent committed write clears the failure state — entries
    # resume only after durable accounting is demonstrated healthy again.
    monkeypatch.undo()
    written = await ledger.record_settlement_proceeds_async(
        TICKER, "yes", yes_count=2.0, timeout_s=30
    )
    assert written == 1
    health = ledger.settlement_write_health()
    assert health["ok"] is True


async def test_health_blocked_by_old_unresolved(ledger, monkeypatch):
    gate = threading.Event()
    started = threading.Event()

    def blocked(*a, **k):
        started.set()
        gate.wait(10)
        return 0

    monkeypatch.setattr(ledger, "_settlement_proceeds_db_write", blocked)
    monkeypatch.setenv("MERID_SETTLEMENT_UNRESOLVED_MAX_AGE_S", "0.2")
    try:
        task = asyncio.ensure_future(
            ledger.record_settlement_proceeds_async(
                TICKER, "yes", yes_count=2.0, timeout_s=30
            )
        )
        deadline = time.time() + 5
        while not started.is_set() and time.time() < deadline:
            await asyncio.sleep(0.02)  # yield so the task can schedule
        assert started.is_set()
        # Op is pending but young — still healthy.
        assert ledger.settlement_write_health()["ok"] is True
        await asyncio.sleep(0.3)
        health = ledger.settlement_write_health()
        assert health["ok"] is False
        assert health["reason"].startswith("settlement_unresolved_age")
        assert health["pending_unresolved"] == 1
    finally:
        gate.set()
    await task
    # Once the op drains, health recovers without manual intervention.
    assert ledger.settlement_write_health()["ok"] is True


# ---------------------------------------------------------------------------
# 9. DumpBudget — stall-episode cap, cooldown, byte and lifetime bounds
# ---------------------------------------------------------------------------


def test_dump_budget_episode_cooldown_and_totals(tmp_path, monkeypatch):
    dump_file = tmp_path / "dump.log"
    dump_file.write_bytes(b"x" * 100)
    monkeypatch.setenv("MERID_DUMP_MAX_PER_STALL", "2")
    monkeypatch.setenv("MERID_DUMP_COOLDOWN_S", "0")
    monkeypatch.setenv("MERID_DUMP_MAX_TOTAL", "50")
    monkeypatch.setenv("MERID_DUMP_MAX_BYTES", str(10**7))

    b = DumpBudget(str(dump_file))
    assert b.try_acquire() and b.try_acquire()
    assert not b.try_acquire()  # stall-episode cap reached
    assert b.episode == 2

    b.note_progress()  # demonstrated loop progress closes the episode
    assert b.try_acquire()

    monkeypatch.setenv("MERID_DUMP_COOLDOWN_S", "100000")
    assert not b.try_acquire()  # cooldown bounds capture rate
    monkeypatch.setenv("MERID_DUMP_COOLDOWN_S", "0")

    # Byte-growth cap measured over the file's size at first acquisition.
    monkeypatch.setenv("MERID_DUMP_MAX_BYTES", "4")
    b2 = DumpBudget(str(dump_file))
    assert b2.try_acquire()  # baseline just set; growth 0 < 4
    dump_file.write_bytes(b"z" * 400)
    assert not b2.try_acquire()  # +300B growth over 4B cap

    monkeypatch.setenv("MERID_DUMP_MAX_BYTES", str(10**7))
    monkeypatch.setenv("MERID_DUMP_MAX_PER_STALL", "10")
    monkeypatch.setenv("MERID_DUMP_MAX_TOTAL", "1")
    b3 = DumpBudget(str(dump_file))
    assert b3.try_acquire()
    assert not b3.try_acquire()  # per-process lifetime cap


def test_timer_permit_gates_firing(tmp_path):
    denied = StackDumpTimer(0.01, permit=lambda: False)
    denied.start()
    time.sleep(0.1)
    denied.cancel()
    assert not denied.fired

    out = open(tmp_path / "d.log", "a", encoding="utf-8")
    try:
        calls = []
        allowed = StackDumpTimer(
            0.01,
            file=out,
            permit=lambda: calls.append(1) is None or True,
        )
        allowed.start()
        deadline = time.time() + 5
        while not allowed.fired and time.time() < deadline:
            time.sleep(0.02)
        allowed.cancel()
        assert allowed.fired
        assert len(calls) == 1  # one-shot timer: permit consulted once
        out.flush()
        assert b"Current thread" in (tmp_path / "d.log").read_bytes()
    finally:
        out.close()
