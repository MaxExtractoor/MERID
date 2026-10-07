"""Regression tests for the 2026-10-07 SUBMISSION_UNKNOWN exit deadlock and the
catastrophic tail-loss floor.

Live incident: KXXRP15M-26OCT071800-00 bought NO@68c.  The take-profit IOC at
88c was firewall-rejected (limit_not_executable), the retry went
SUBMISSION_UNKNOWN, and the in-flight lock then deadlocked ~25 salvage intents
for five minutes while the bid fell 84c -> 15c.  Settlement paid 0 (-70c).

Fixes under test:

1. Reconcile scheduling works from the sync monitor poll — the previous
   ``asyncio.get_running_loop().create_task(...)`` raised RuntimeError that was
   silently swallowed, so reconcile attempts logged but never ran.  The new
   ``_schedule_exit_reconcile`` falls back to ``run_coroutine_threadsafe`` on
   the monitor's own loop.

2. A stale SUBMISSION_UNKNOWN in-flight lock becomes force-reconcilable by ANY
   exit class after ``MERID_EXIT_INFLIGHT_STALE_FORCE_S`` (default 30s).

3. The tail-loss floor emits a HARD_STOP-class StopCandidate on the
   reduce-only IOC submission channel — independent of the intent lock — when
   the executable own-side bid drops >= ``MERID_TAIL_LOSS_DROP_CENTS`` below
   entry or sits <= ``MERID_TAIL_LOSS_FLOOR_CENTS``.

4. ``loss_cap`` is a first-class canonical emergency exit reason end-to-end
   (canonical map, emergency class, allowed-reason set, hard-risk set, and the
   winning-side hold-veto exemption).
"""

import asyncio
import threading
import time
from decimal import Decimal

import pytest

import merid.position_management.position_monitor as pm_mod
from merid.event_venues.kalshi.settlement_aligned_exit import (
    EXIT_REASON_CANONICAL_MAP,
    ExitClass,
    canonicalize_exit_reason,
    classify_canonical_reason,
    classify_trigger_reason,
)
from merid.loop_15m import MERID_EXIT_ALLOWED_REASONS, MERID_HARD_RISK_EXIT_REASONS
from merid.position_management.exit_audit import ExitPriceSnapshot
from merid.position_management.exit_policy import ExitReason
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import (
    PositionMonitor,
    _exit_inflight_stale_force_seconds,
    _get_tail_loss_floor_config,
    _inflight_reconcile_slow_seconds,
    _is_forced_exit_reason,
)


# ── 1. Reconcile scheduling survives the no-running-loop context ─────────────

class TestReconcileScheduling:
    def test_falls_back_to_monitor_loop(self, monkeypatch):
        """From a thread with no running loop, reconcile must be scheduled on
        self._loop via run_coroutine_threadsafe — not silently dropped."""
        monitor = PositionMonitor()
        calls = []

        async def _fake_reconcile(position_id, client_order_id):
            calls.append((position_id, client_order_id))

        monkeypatch.setattr(monitor, "_reconcile_exit_intent", _fake_reconcile)

        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _run():
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        ready.wait(timeout=2)
        monitor._loop = loop
        try:
            # Called from this thread: no running loop here.
            monitor._schedule_exit_reconcile("pos-abcdef12", "exit_coid1234")
            deadline = time.time() + 3.0
            while not calls and time.time() < deadline:
                time.sleep(0.02)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=2)
            monitor._loop = None

        assert calls == [("pos-abcdef12", "exit_coid1234")]

    def test_no_loop_does_not_raise(self, monkeypatch):
        """With neither a running loop nor a monitor loop, scheduling fails
        soft (logged) rather than raising into the exit path."""
        monitor = PositionMonitor()
        monitor._loop = None

        async def _fake_reconcile(position_id, client_order_id):
            pass

        monkeypatch.setattr(monitor, "_reconcile_exit_intent", _fake_reconcile)
        # Must not raise from a context with no running loop.
        monitor._schedule_exit_reconcile("pos-abcdef12", "exit_coid1234")


# ── 2. Stale in-flight lock knobs ────────────────────────────────────────────

class TestStaleInflightKnobs:
    def test_stale_force_seconds_default(self, monkeypatch):
        monkeypatch.delenv("MERID_EXIT_INFLIGHT_STALE_FORCE_S", raising=False)
        assert _exit_inflight_stale_force_seconds() == 30.0

    def test_stale_force_seconds_override(self, monkeypatch):
        monkeypatch.setenv("MERID_EXIT_INFLIGHT_STALE_FORCE_S", "45")
        assert _exit_inflight_stale_force_seconds() == 45.0

    def test_reconcile_slow_seconds_default(self, monkeypatch):
        monkeypatch.delenv("MERID_INFLIGHT_RECONCILE_SLOW_S", raising=False)
        assert _inflight_reconcile_slow_seconds() == 30.0


# ── 3. Tail-loss floor ───────────────────────────────────────────────────────

class TestTailLossFloor:
    def test_config_defaults(self, monkeypatch):
        for var in ("MERID_TAIL_LOSS_ENABLED", "MERID_TAIL_LOSS_DROP_CENTS", "MERID_TAIL_LOSS_FLOOR_CENTS"):
            monkeypatch.delenv(var, raising=False)
        cfg = _get_tail_loss_floor_config()
        assert cfg == {"enabled": True, "drop_cents": 30, "floor_cents": 18}

    def test_config_overrides(self, monkeypatch):
        monkeypatch.setenv("MERID_TAIL_LOSS_ENABLED", "0")
        monkeypatch.setenv("MERID_TAIL_LOSS_DROP_CENTS", "25")
        monkeypatch.setenv("MERID_TAIL_LOSS_FLOOR_CENTS", "22")
        cfg = _get_tail_loss_floor_config()
        assert cfg == {"enabled": False, "drop_cents": 25, "floor_cents": 22}

    def _position(self, **kwargs) -> Position:
        defaults = dict(
            market_id="KXXRP15M-TESTTAIL",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=Decimal("1"),
            avg_entry_price_cents=68,
            stop_loss_enabled=False,          # profit_only_v1 posture
            take_profit_price_cents=None,
            fill_source="TEST",
        )
        defaults.update(kwargs)
        return Position(**defaults)

    def _snapshot(self, bid: int, side: PositionSide = PositionSide.NO) -> ExitPriceSnapshot:
        return ExitPriceSnapshot(
            market_id="KXXRP15M-TESTTAIL",
            position_side=side,
            mid_cents=bid,
            own_side_bid_cents=bid,
            own_side_ask_cents=min(99, bid + 2),
            opposite_bid_cents=100 - bid - 2,
            opposite_ask_cents=100 - bid,
            book_age_ms=50,
            data_source="test",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id="snap-tail-1",
            seconds_to_expiry=300.0,
        )

    def test_floor_fires_hard_stop_candidate(self, monkeypatch):
        """Entry 68c, bid 38c -> drop 30c hits the floor; a HARD_STOP-class
        StopCandidate is submitted on the reduce-only channel."""
        monkeypatch.setenv("MERID_TAIL_LOSS_ENABLED", "1")
        monitor = PositionMonitor()
        monitor._loop = None
        monkeypatch.setattr(monitor, "_is_expired_market", lambda *a, **k: False)

        submitted = []
        monkeypatch.setattr(
            monitor, "_submit_stop_candidate", lambda c: submitted.append(c)
        )
        recorded = []
        monkeypatch.setattr(pm_mod, "record_stop_candidate", lambda c: recorded.append(c))

        emitted = []

        async def _capture(*a, **k):
            emitted.append(a)

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)

        position = self._position()
        monitor.add_position(position)
        asyncio.run(monitor._check_position(position, self._snapshot(38)))

        assert position.tail_loss_floor_fired is True
        assert len(recorded) == 1
        assert len(submitted) == 1
        assert submitted[0].trigger_reason == "HARD_STOP"

    def test_floor_does_not_fire_above_drop(self, monkeypatch):
        """Entry 68c, bid 50c -> only -18c, above the 30c drop and 18c floor."""
        monkeypatch.setenv("MERID_TAIL_LOSS_ENABLED", "1")
        monitor = PositionMonitor()
        monitor._loop = None
        monkeypatch.setattr(monitor, "_is_expired_market", lambda *a, **k: False)

        submitted = []
        monkeypatch.setattr(
            monitor, "_submit_stop_candidate", lambda c: submitted.append(c)
        )
        monkeypatch.setattr(pm_mod, "record_stop_candidate", lambda c: None)
        emitted = []

        async def _capture(*a, **k):
            emitted.append(a)

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)

        position = self._position()
        monitor.add_position(position)
        asyncio.run(monitor._check_position(position, self._snapshot(50)))

        assert position.tail_loss_floor_fired is False
        assert submitted == []

    def test_floor_is_one_shot(self, monkeypatch):
        """The fired flag prevents re-emission on subsequent polls."""
        monkeypatch.setenv("MERID_TAIL_LOSS_ENABLED", "1")
        monitor = PositionMonitor()
        monitor._loop = None
        monkeypatch.setattr(monitor, "_is_expired_market", lambda *a, **k: False)
        submitted = []
        monkeypatch.setattr(
            monitor, "_submit_stop_candidate", lambda c: submitted.append(c)
        )
        monkeypatch.setattr(pm_mod, "record_stop_candidate", lambda c: None)

        async def _capture(*a, **k):
            pass

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)

        position = self._position()
        monitor.add_position(position)
        asyncio.run(monitor._check_position(position, self._snapshot(38)))
        asyncio.run(monitor._check_position(position, self._snapshot(35)))
        assert len(submitted) == 1

    def test_floor_absolute_trigger(self, monkeypatch):
        """Bid <= floor_cents fires even when the entry drop is smaller
        (e.g. a cheap entry that has gone nearly worthless)."""
        monkeypatch.setenv("MERID_TAIL_LOSS_ENABLED", "1")
        monkeypatch.setenv("MERID_TAIL_LOSS_FLOOR_CENTS", "18")
        monitor = PositionMonitor()
        monitor._loop = None
        monkeypatch.setattr(monitor, "_is_expired_market", lambda *a, **k: False)
        submitted = []
        monkeypatch.setattr(
            monitor, "_submit_stop_candidate", lambda c: submitted.append(c)
        )
        monkeypatch.setattr(pm_mod, "record_stop_candidate", lambda c: None)

        async def _capture(*a, **k):
            pass

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)

        position = self._position(avg_entry_price_cents=40)
        monitor.add_position(position)
        # 40 - 15 = 25 < 30 drop, but bid 15 <= 18 floor -> fires.
        asyncio.run(monitor._check_position(position, self._snapshot(15)))
        assert position.tail_loss_floor_fired is True
        assert len(submitted) == 1


# ── 4. loss_cap canonical wiring ─────────────────────────────────────────────

class TestLossCapWiring:
    def test_canonicalizes_to_itself(self):
        assert EXIT_REASON_CANONICAL_MAP["loss_cap"] == "loss_cap"
        assert canonicalize_exit_reason("loss_cap") == ("loss_cap", "loss_cap")

    def test_canonical_class_is_emergency(self):
        assert classify_canonical_reason("loss_cap") == ExitClass.EMERGENCY

    def test_trigger_reason_classified_operational(self):
        assert classify_trigger_reason("LOSS_CAP") == ExitClass.OPERATIONAL

    def test_allowed_and_hard_risk_sets(self):
        assert "loss_cap" in MERID_EXIT_ALLOWED_REASONS
        assert "loss_cap" in MERID_HARD_RISK_EXIT_REASONS

    def test_loss_cap_is_force_reconcile_reason(self):
        assert _is_forced_exit_reason(ExitReason.LOSS_CAP) is True

    def test_profit_reasons_not_force_reconcile(self):
        """take_profit/ratchet_floor stay non-forced for FRESH in-flight
        locks; only stale locks may be force-reconciled by any class."""
        assert _is_forced_exit_reason(ExitReason.TAKE_PROFIT) is False
