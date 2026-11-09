"""Regression tests for the 2026-11-09 post-partial residual-stranding fixes.

Forensic basis (live, XRP 091200 + 091030 markets): a ratchet_trim partial
exit closed 3 of 4 contracts; the residual runner then (a) carried stale
exit_triggered/exit_reason flags that disabled auto_exit_99c and every
other trigger, (b) had its follow-up exit attempt wedge in
RESOLVING_ON_EXCHANGE forever, and (c) had no dedicated floor, so it
watched profitable bids pass and rode to a 0 settlement.
"""

import os
import time
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("MERID_DATA_DIR", "data_test_residual_runner")
os.environ.setdefault("MERID_DISABLE_EXIT_POLICY", "0")

from merid.position_management.position_monitor import (
    PositionMonitor,
    _residual_runner_floor_price,
)
from merid.position_management.position import Position, PositionSide


def _pos(size=1.0, entry=67, side=PositionSide.NO):
    p = Position(
        position_id="pos-resid-0001",
        market_id="KXXRP15M-26NOV091200-00",
        side=side,
        size=size,
        avg_entry_price_cents=entry,
    )
    return p


# ── residual-runner floor predicate ────────────────────────────────────────

class TestResidualRunnerFloor:
    def test_arms_only_after_partial(self):
        p = _pos()
        p.ratchet_trimmed = False
        p.scale_out_triggered = False
        assert _residual_runner_floor_price(p, 20) is None

    def test_fires_at_breakeven_floor(self):
        p = _pos(entry=67)
        p.ratchet_trimmed = True
        # Peak 84 -> floor = max(67, 84-8) = 76.  Bid 70 <= 76 -> fire.
        p._residual_runner_peak_cents = 84
        assert _residual_runner_floor_price(p, 70) == 76

    def test_no_fire_above_floor(self):
        p = _pos(entry=67)
        p.ratchet_trimmed = True
        p._residual_runner_peak_cents = 84
        assert _residual_runner_floor_price(p, 80) is None

    def test_floor_never_below_entry(self):
        p = _pos(entry=67)
        p.ratchet_trimmed = True
        p._residual_runner_peak_cents = 70  # 70-8=62 < 67 -> floor = 67
        assert _residual_runner_floor_price(p, 63) == 67

    def test_peak_tracks_upward(self):
        p = _pos(entry=67)
        p.scale_out_triggered = True
        assert _residual_runner_floor_price(p, 90) is None
        assert p._residual_runner_peak_cents == 90
        # floor = max(67, 90-8)=82; bid 80 breaches
        assert _residual_runner_floor_price(p, 80) == 82

    def test_env_kill(self, monkeypatch):
        monkeypatch.setenv("MERID_RESIDUAL_RUNNER_FLOOR", "0")
        p = _pos(entry=67)
        p.ratchet_trimmed = True
        p._residual_runner_peak_cents = 90
        assert _residual_runner_floor_price(p, 40) is None

    def test_trail_env(self, monkeypatch):
        monkeypatch.setenv("MERID_RESIDUAL_RUNNER_TRAIL_CENTS", "20")
        p = _pos(entry=67)
        p.ratchet_trimmed = True
        p._residual_runner_peak_cents = 84
        # floor = max(67, 84-20)=67
        assert _residual_runner_floor_price(p, 66) == 67


# ── reconcile: partial-fill residual release + dead-attempt terminalize ────

def _monitor():
    mon = object.__new__(PositionMonitor)
    import threading
    mon._lock = threading.RLock()
    mon._exit_intent_in_flight = {}
    mon._position_to_client_order = {}
    mon._recent_exit_submissions = {}
    mon._submission_cache_ttl = 0
    mon._open_positions = {}
    mon._loop = None
    mon._save_exit_intent_in_flight = lambda: None
    return mon


class _Att:
    def __init__(self, confirmed=0, requested=300, created=None):
        self.confirmed_quantity = confirmed
        self.requested_quantity = requested
        self.created_at = created if created is not None else time.time() - 600
        self.attempt_id = "att-0001"


class TestPartialResidualReconciled:
    def test_release_when_residual_posted(self):
        mon = _monitor()
        pos = _pos(size=1.0)
        mon._exit_intent_in_flight["pos-resid-0001"] = {
            "state": "SUBMISSION_UNKNOWN",
            "client_order_id": "exit_abc",
            "pre_exit_size_cc": 400,
        }
        store = MagicMock()
        store.get_exit_attempt_by_client_order_id.return_value = _Att(confirmed=300)
        with patch(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
            return_value=store,
        ):
            assert mon._partial_exit_residual_reconciled(
                "pos-resid-0001", pos, "exit_abc"
            ) is True

    def test_retain_when_fills_unposted(self):
        mon = _monitor()
        pos = _pos(size=4.0)  # stale pre-fill size
        mon._exit_intent_in_flight["pos-resid-0001"] = {
            "state": "SUBMISSION_UNKNOWN",
            "client_order_id": "exit_abc",
            "pre_exit_size_cc": 400,
        }
        store = MagicMock()
        store.get_exit_attempt_by_client_order_id.return_value = _Att(confirmed=300)
        with patch(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
            return_value=store,
        ):
            assert mon._partial_exit_residual_reconciled(
                "pos-resid-0001", pos, "exit_abc"
            ) is False

    def test_retain_when_full_close(self):
        mon = _monitor()
        pos = _pos(size=0.0)
        mon._exit_intent_in_flight["pos-resid-0001"] = {
            "state": "SUBMISSION_UNKNOWN",
            "client_order_id": "exit_abc",
            "pre_exit_size_cc": 400,
        }
        store = MagicMock()
        store.get_exit_attempt_by_client_order_id.return_value = _Att(confirmed=400)
        with patch(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
            return_value=store,
        ):
            assert mon._partial_exit_residual_reconciled(
                "pos-resid-0001", pos, "exit_abc"
            ) is False

    def test_retain_without_snapshot(self):
        mon = _monitor()
        pos = _pos(size=1.0)
        mon._exit_intent_in_flight["pos-resid-0001"] = {
            "state": "SUBMISSION_UNKNOWN",
            "client_order_id": "exit_abc",
        }
        assert mon._partial_exit_residual_reconciled(
            "pos-resid-0001", pos, "exit_abc"
        ) is False


class TestDeadAttemptRelease:
    def test_dead_no_fill_releases(self):
        mon = _monitor()
        released = []
        mon._release_stale_exit_flags = lambda pid, r, c, **k: released.append((pid, r, c)) or True
        store = MagicMock()
        store.get_exit_attempt_by_client_order_id.return_value = _Att(confirmed=0)
        with patch(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
            return_value=store,
        ):
            assert mon._exit_attempt_dead_release("pos-resid-0001", "exit_abc") is True
        assert released == [("pos-resid-0001", "not_accepted_confirmed", "exit_abc")]

    def test_fresh_attempt_retained(self):
        mon = _monitor()
        mon._release_stale_exit_flags = MagicMock()
        store = MagicMock()
        store.get_exit_attempt_by_client_order_id.return_value = _Att(
            confirmed=0, created=time.time()
        )
        with patch(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
            return_value=store,
        ):
            assert mon._exit_attempt_dead_release("pos-resid-0001", "exit_abc") is False
        mon._release_stale_exit_flags.assert_not_called()

    def test_filled_attempt_retained(self):
        mon = _monitor()
        mon._release_stale_exit_flags = MagicMock()
        store = MagicMock()
        store.get_exit_attempt_by_client_order_id.return_value = _Att(confirmed=100)
        with patch(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
            return_value=store,
        ):
            assert mon._exit_attempt_dead_release("pos-resid-0001", "exit_abc") is False
        mon._release_stale_exit_flags.assert_not_called()
