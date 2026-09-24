"""Regression tests for the 2026-09-24 XRP double-loss incident.

Live failure chain that these tests lock out:

1. An exit order was registered in ``_exit_registry`` *after* the position was
   removed (flat-confirmation reconcile raced the WS fill handler).  The orphan
   entry poisoned the asset-keyed ``position_id`` so every settlement-guard
   exit for the NEXT position was dropped as ``EXIT-ORDER-DUPLICATE``.

2. A retry of a dead exit reused the same ``client_order_id``; Kalshi rejects
   a reused id for a new order with HTTP 409.

3. Re-entry on the same market (and same asset immediately after a loss) was
   unrestricted — the re-entry guard must lock the ticker and cool the asset.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.risk.reentry_guard import ReentryGuard


def _position(**kwargs) -> Position:
    defaults = {
        "position_id": "KXXRP15M",
        "market_id": "KXXRP15M-26SEP241600-00",
        "side": PositionSide.YES,
        "size": 1,
        "avg_entry_price_cents": 58,
        "current_price_cents": 58,
        "fill_source": "ws",
        "entry_fill_id": "fill-1",
        "risk_params_state": "original_persisted",
        "risk_params_schema_version": 2,
        "entry_book_capture_quality": "AT_FILL",
        "entry_fill_price_cents": 58,
    }
    defaults.update(kwargs)
    return Position(**defaults)


@pytest.fixture(autouse=True)
def _patch_stop_submission_sync(monkeypatch):
    monkeypatch.setattr(
        "merid.position_management.position_monitor.maybe_submit_stop_candidate_sync",
        Mock(),
    )
    # Test tickers encode a past window; keep the expiry gate from rejecting them.
    monkeypatch.setattr(
        "merid.position_management.position_monitor.PositionMonitor._is_expired_market",
        lambda self, market_id: False,
    )


# --------------------------------------------------------------------------
# Exit-registry orphan protection
# --------------------------------------------------------------------------


class TestExitRegistryOrphan:
    def test_register_refused_for_removed_position(self):
        """A late registration for an already-removed position must be skipped
        — otherwise the entry can never be unregistered and poisons the next
        position recycling the same asset-keyed position_id."""
        monitor = PositionMonitor()
        monitor._register_exit_order("KXXRP15M", "order-orphan-1", 1)
        assert monitor._get_exit_orders_for_position("KXXRP15M") == []
        assert not monitor._has_exit_order("KXXRP15M")

    def test_register_accepted_while_position_open(self):
        monitor = PositionMonitor()
        monitor.add_position(_position())
        monitor._register_exit_order("KXXRP15M", "order-live-1", 1)
        assert monitor._get_exit_orders_for_position("KXXRP15M") == ["order-live-1"]

    def test_new_position_sweeps_orphan_registry(self):
        """If a stale entry somehow survives, adding the next position under
        the recycled position_id must clear it."""
        monitor = PositionMonitor()
        # Simulate the leaked entry: registry entry exists but position is gone.
        with monitor._lock_registry_lock:
            monitor._exit_registry["KXXRP15M"] = ["order-stale-1"]
            monitor._exit_quantities["KXXRP15M"] = {"order-stale-1": 1}
        monitor.add_position(_position())
        assert monitor._get_exit_orders_for_position("KXXRP15M") == []
        # A genuinely new exit for the live position must be registrable.
        monitor._register_exit_order("KXXRP15M", "order-live-2", 1)
        assert monitor._get_exit_orders_for_position("KXXRP15M") == ["order-live-2"]


# --------------------------------------------------------------------------
# Dead exit-order pruning (reconcile_exit_registry)
# --------------------------------------------------------------------------


class TestExitRegistryReconcile:
    def test_dead_ioc_registration_is_pruned(self):
        """A registered order not resting on the exchange and past the grace
        window is dead (IOC expired unfilled) and must not suppress retries —
        the exact mechanism that swallowed 14 settlement-guard exits live."""
        monitor = PositionMonitor()
        monitor.add_position(_position())
        monitor._register_exit_order("KXXRP15M", "order-dead-ioc", 1)
        # Age the registration past the grace window.
        monitor._exit_registry_ts["KXXRP15M"]["order-dead-ioc"] = (
            time.monotonic() - 60.0
        )
        survivors = monitor._reconcile_exit_registry(
            "KXXRP15M", live_order_ids=set()
        )
        assert survivors == []
        assert not monitor._has_exit_order("KXXRP15M")

    def test_live_resting_order_survives(self):
        monitor = PositionMonitor()
        monitor.add_position(_position())
        monitor._register_exit_order("KXXRP15M", "order-resting", 1)
        monitor._exit_registry_ts["KXXRP15M"]["order-resting"] = (
            time.monotonic() - 60.0
        )
        survivors = monitor._reconcile_exit_registry(
            "KXXRP15M", live_order_ids={"order-resting"}
        )
        assert survivors == ["order-resting"]
        assert monitor._has_exit_order("KXXRP15M")

    def test_fresh_unrested_order_kept_within_grace(self):
        """A just-registered order may not have reached the resting monitor
        yet — keep suppressing duplicates during the grace window."""
        monitor = PositionMonitor()
        monitor.add_position(_position())
        monitor._register_exit_order("KXXRP15M", "order-inflight", 1)
        survivors = monitor._reconcile_exit_registry(
            "KXXRP15M", live_order_ids=set()
        )
        assert survivors == ["order-inflight"]

    def test_unknown_live_set_prunes_nothing(self):
        """When the resting-order probe fails, live vs dead cannot be told
        apart — pruning could drop a genuinely resting order and cause a
        double exit, so everything is kept."""
        monitor = PositionMonitor()
        monitor.add_position(_position())
        monitor._register_exit_order("KXXRP15M", "order-maybe-live", 1)
        monitor._exit_registry_ts["KXXRP15M"]["order-maybe-live"] = (
            time.monotonic() - 3600.0
        )
        survivors = monitor._reconcile_exit_registry(
            "KXXRP15M", live_order_ids=None
        )
        assert survivors == ["order-maybe-live"]


# --------------------------------------------------------------------------
# Exit client_order_id reuse
# --------------------------------------------------------------------------


class TestExitClientOrderId:
    def test_no_flight_returns_none(self):
        """No in-flight record => no unresolved outcome => caller must mint a
        fresh id (a stale _position_to_client_order mapping must not leak)."""
        monitor = PositionMonitor()
        monitor._position_to_client_order["KXXRP15M"] = "exit_deadbeefdeadbeef"
        assert monitor._get_unresolved_exit_client_order_id("KXXRP15M") is None

    def test_terminal_flight_state_returns_none(self):
        monitor = PositionMonitor()
        monitor._exit_intent_in_flight["KXXRP15M"] = {
            "state": "RECONCILED",
            "client_order_id": "exit_deadbeefdeadbeef",
            "timestamp": time.time(),
        }
        assert monitor._get_unresolved_exit_client_order_id("KXXRP15M") is None

    def test_unresolved_flight_returns_id(self):
        monitor = PositionMonitor()
        monitor._exit_intent_in_flight["KXXRP15M"] = {
            "state": "SUBMISSION_UNKNOWN",
            "client_order_id": "exit_unresolved00123",
            "timestamp": time.time(),
        }
        assert (
            monitor._get_unresolved_exit_client_order_id("KXXRP15M")
            == "exit_unresolved00123"
        )


# --------------------------------------------------------------------------
# Re-entry guard
# --------------------------------------------------------------------------


class TestReentryGuard:
    def test_same_market_lock_after_close(self):
        guard = ReentryGuard()
        guard.record_close("KXXRP15M-26SEP241600-00", "yes", -3.0)
        allowed, reason = guard.check_entry("KXXRP15M-26SEP241600-00")
        assert not allowed
        assert "same_market_reentry" in reason

    def test_same_market_lock_applies_even_on_win(self):
        """One-trade-per-market: even a profitable close locks the ticker —
        a second entry is economically the same trade with worse information."""
        guard = ReentryGuard()
        guard.record_close("KXBTC15M-26SEP241600-00", "no", 40.0)
        allowed, _ = guard.check_entry("KXBTC15M-26SEP241600-00")
        assert not allowed

    def test_unknown_pnl_still_locks_market(self):
        guard = ReentryGuard()
        guard.record_close("KXETH15M-26SEP241600-00", "yes", None)
        allowed, _ = guard.check_entry("KXETH15M-26SEP241600-00")
        assert not allowed

    def test_asset_cooldown_after_loss_blocks_next_window(self, monkeypatch):
        monkeypatch.setenv("MERID_POST_LOSS_COOLDOWN_S", "300")
        guard = ReentryGuard()
        guard.record_close("KXXRP15M-26SEP241600-00", "yes", -55.0)
        # Next window's ticker on the same asset must cool down too.
        allowed, reason = guard.check_entry("KXXRP15M-26SEP241615-15")
        assert not allowed
        assert "post_loss_cooldown" in reason

    def test_asset_cooldown_expires(self, monkeypatch):
        monkeypatch.setenv("MERID_POST_LOSS_COOLDOWN_S", "120")
        guard = ReentryGuard()
        guard.record_close(
            "KXXRP15M-26SEP241600-00", "yes", -55.0,
            closed_ts=time.time() - 121.0,
        )
        allowed, _ = guard.check_entry("KXXRP15M-26SEP241615-15")
        assert allowed

    def test_winning_close_does_not_cool_asset(self):
        guard = ReentryGuard()
        guard.record_close("KXBTC15M-26SEP241600-00", "yes", 40.0)
        allowed, _ = guard.check_entry("KXBTC15M-26SEP241615-15")
        assert allowed

    def test_unknown_pnl_close_does_not_trigger_cooldown(self):
        guard = ReentryGuard()
        guard.record_close("KXSOL15M-26SEP241600-00", "no", None)
        allowed, _ = guard.check_entry("KXSOL15M-26SEP241615-15")
        assert allowed

    def test_none_pnl_write_does_not_clobber_known_loss(self):
        """Settlement cleanup (pnl=None) arriving after the authoritative
        settlement record must not erase the loss — the cooldown must stand."""
        guard = ReentryGuard()
        guard.record_close("KXXRP15M-26SEP241600-00", "no", -61.0)
        guard.record_close("KXXRP15M-26SEP241600-00", "no", None)
        allowed, reason = guard.check_entry("KXXRP15M-26SEP241615-15")
        assert not allowed
        assert "post_loss_cooldown" in reason

    def test_other_asset_unaffected(self):
        guard = ReentryGuard()
        guard.record_close("KXXRP15M-26SEP241600-00", "yes", -55.0)
        allowed, _ = guard.check_entry("KXBTC15M-26SEP241600-00")
        assert allowed

    def test_rerecorded_close_does_not_reset_cooldown(self, monkeypatch):
        """2026-09-24 bug: settlement re-sweeps re-recorded the same ticker's
        close with a fresh timestamp, so the 120s cooldown never expired and
        the asset was permanently blocked.  Re-records must preserve the
        original closed_ts."""
        monkeypatch.setenv("MERID_POST_LOSS_COOLDOWN_S", "120")
        guard = ReentryGuard()
        close_ts = time.time() - 119.0
        guard.record_close(
            "KXETH15M-26SEP241600-00", "yes", -58.0, closed_ts=close_ts
        )
        # Settlement cleanup re-records the same close 119s later.
        guard.record_close("KXETH15M-26SEP241600-00", "yes", -58.0)
        guard.record_close("KXETH15M-26SEP241600-00", "yes", None)
        # 1s later the cooldown lapses — the re-record must not have
        # refreshed the clock.
        allowed, reason = guard.check_entry(
            "KXETH15M-26SEP241615-15", now=close_ts + 121.0
        )
        assert allowed, reason

    def test_rerecorded_close_does_not_regress_asset_marker(self, monkeypatch):
        """An old ticker's re-record must not overwrite a fresher close's
        timestamp/PnL at the asset level."""
        monkeypatch.setenv("MERID_POST_LOSS_COOLDOWN_S", "120")
        guard = ReentryGuard()
        old_ts = time.time() - 200.0
        guard.record_close("KXETH15M-26SEP241600-00", "yes", -10.0, closed_ts=old_ts)
        guard.record_close("KXETH15M-26SEP241615-15", "yes", -55.0)
        # Re-record the OLD ticker now — asset marker must stay on the new close.
        guard.record_close("KXETH15M-26SEP241600-00", "yes", -10.0)
        allowed, reason = guard.check_entry("KXETH15M-26SEP241630-30")
        assert not allowed
        assert "pnl=-55" in reason

    def test_authoritative_settlement_ts_backdates_cleanup_record(self, monkeypatch):
        """If monitor cleanup records a settled ticker first (closed_ts=now),
        the settlement sweep's authoritative settlement_ts (minutes older) must
        still apply — min() merge — so the cooldown ages from the true close,
        not from discovery time."""
        monkeypatch.setenv("MERID_POST_LOSS_COOLDOWN_S", "120")
        guard = ReentryGuard()
        # Cleanup path stamps now() with no pnl.
        guard.record_close("KXSOL15M-26SEP241600-00", "yes", None)
        # Settlement sweep arrives later carrying the true (old) settlement time.
        guard.record_close(
            "KXSOL15M-26SEP241600-00", "yes", -36.0,
            closed_ts=time.time() - 300.0,
        )
        allowed, reason = guard.check_entry("KXSOL15M-26SEP241615-15")
        assert allowed, reason  # true close was 300s ago — cooldown long expired

    def test_future_closed_ts_clamped_to_now(self, monkeypatch):
        """Clock skew / bad parse producing a future closed_ts must not zero
        the cooldown — clamp to now."""
        monkeypatch.setenv("MERID_POST_LOSS_COOLDOWN_S", "120")
        guard = ReentryGuard()
        guard.record_close(
            "KXBTC15M-26SEP241600-00", "yes", -44.0,
            closed_ts=time.time() + 600.0,
        )
        allowed, reason = guard.check_entry("KXBTC15M-26SEP241615-15")
        assert not allowed
        assert "post_loss_cooldown" in reason


# --------------------------------------------------------------------------
# Stop-loss POST_FILL provenance
# --------------------------------------------------------------------------


class TestStopLossPostFill:
    def test_post_fill_stop_not_blocked_by_book_quality(self):
        """A hard price stop must fire when entry price is fill-derived even
        if the entry book snapshot arrived post-fill — the entry book only
        feeds spread/adverse-move invariants, not the price-level check."""
        monitor = PositionMonitor()
        pos = _position(
            entry_book_capture_quality="POST_FILL",
            entry_executable_bid_cents=None,
            entry_executable_ask_cents=None,
            entry_book_timestamp=None,
            stop_loss_price_cents=31,
            stop_loss_enabled=True,
            opened_at=datetime.now(timezone.utc) - timedelta(seconds=120),
        )
        # _evaluate_stop_loss returns (triggered, kind); we only care that the
        # provenance gate no longer returns 'untrusted_entry_book'.
        _, reason = monitor._evaluate_stop_loss(pos, 30, snapshot=None)
        assert reason != "untrusted_entry_book"
