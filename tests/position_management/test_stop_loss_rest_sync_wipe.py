"""
Regression tests for the 2026-10-02 XRP stop-loss wipe.

Live incident (KXXRP15M-26OCT021500-00): a NO@64c position was registered with
SL=59c.  Eleven seconds later a periodic REST sync re-upserted the position
with SL=None / stop_loss_enabled=False (REST cannot see intent risk params).
Because the provenance copy-back in ``upsert_position`` was dead code
(``source == "new" and old_rank > new_rank`` is unreachable — source=="new"
requires new_rank >= old_rank), the equal-trust record wholesale-replaced the
live one and silently disarmed the stop.  The position rode to ~1c expiry
liquidation instead of exiting at the 59c stop.

Fixes covered:
- ``PositionMonitor.upsert_position`` inherits missing provenance fields from
  the existing record on equal-trust ("new" base) merges, including the
  SL price + enabled flag and TP price + R-multiple pairs.
- The position_cache REST-sync builder passes the cached ``stop_loss_enabled``
  flag instead of ``sl_price is not None``, so ``__post_init__`` fallback SL
  derivation still runs for positions whose SL was never persisted.
- A missing bid-depth annotation must not suppress the catastrophic hard-stop
  floor evaluation.
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from merid.position_management.position import Position, PositionSide, RiskParamsState
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.exit_audit import ExitPriceSnapshot

# Future-dated ticker so _is_expired_market() never trips on wall clock.
_MARKET = "KXXRP15M-27DEC312359-00"


def _monitor() -> PositionMonitor:
    return PositionMonitor()


def _live_no_position(**kwargs) -> Position:
    """Position as created by the fill path for the XRP incident."""
    defaults = dict(
        position_id=_MARKET,
        market_id=_MARKET,
        series_ticker="KXXRP15M",
        side=PositionSide.NO,
        size=Decimal("1"),
        avg_entry_price_cents=64,
        opened_at=datetime.now(timezone.utc) - timedelta(seconds=20),
        time_since_entry_seconds=20.0,
        take_profit_price_cents=71,
        stop_loss_enabled=True,
        stop_loss_price_cents=59,
        risk_params_state=RiskParamsState.ORIGINAL_PERSISTED,
        risk_params_schema_version=2,
        client_order_id="merid_3fc003e30f6a489b8e45",
        entry_intent_id="intent_e70acf8d8cc2436c831abd32de45b280",
        entry_fill_id="07230a26-cd89-9e5f-ee33-4127fddea1d7",
        entry_fill_price_cents=64,
        fill_source="http_poller",
        thesis_side="no",
        outcome_side="no",
    )
    defaults.update(kwargs)
    return Position(**defaults)


def _rest_sync_position(**kwargs) -> Position:
    """Position as built by the pre-fix REST-sync path (the wipe).

    stop_loss_enabled=False + sl=None reproduces the buggy construction
    (``stop_loss_enabled=sl_price is not None``) so the merge behaviour is
    exercised in isolation.
    """
    defaults = dict(
        position_id=_MARKET,
        market_id=_MARKET,
        series_ticker="KXXRP15M",
        side=PositionSide.NO,
        size=Decimal("1"),
        avg_entry_price_cents=64,
        opened_at=datetime.now(timezone.utc) - timedelta(seconds=20),
        take_profit_price_cents=71,
        stop_loss_enabled=False,
        stop_loss_price_cents=None,
        risk_params_state="original_persisted",
        risk_params_schema_version=2,
        client_order_id="merid_3fc003e30f6a489b8e45",
        entry_intent_id="intent_e70acf8d8cc2436c831abd32de45b280",
        entry_fill_id="07230a26-cd89-9e5f-ee33-4127fddea1d7",
        entry_fill_price_cents=64,
        fill_source="http_poller",
        thesis_side="no",
        outcome_side="no",
    )
    defaults.update(kwargs)
    return Position(**defaults)


def _snapshot(bid: int, ask: int, *, has_bid_size: bool = True, executable: bool = True) -> ExitPriceSnapshot:
    return ExitPriceSnapshot(
        market_id=_MARKET,
        position_side=PositionSide.NO,
        mid_cents=(bid + ask) // 2,
        own_side_bid_cents=bid,
        own_side_ask_cents=ask,
        opposite_bid_cents=100 - ask,
        opposite_ask_cents=100 - bid,
        book_age_ms=50,
        data_source="WS_ORDERBOOK_DELTA_LIVE",
        data_quality="GOOD",
        executable=executable,
        has_bid_size=has_bid_size,
        snapshot_id="test-snap",
        min_depth_own_side=5 if has_bid_size else 0,
    )


class TestRestSyncStopLossWipe:
    def test_equal_trust_upsert_preserves_stop_loss(self):
        """A REST-synced record with sl=None/enabled=False must not wipe SL."""
        monitor = _monitor()
        monitor.upsert_position(_live_no_position(), caller="position_cache")

        monitor.upsert_position(_rest_sync_position(), caller="rest_sync")

        merged = monitor._open_positions[_MARKET]
        assert merged.stop_loss_price_cents == 59
        assert merged.stop_loss_enabled is True

    def test_equal_trust_upsert_preserves_take_profit(self):
        monitor = _monitor()
        monitor.upsert_position(_live_no_position(), caller="position_cache")

        monitor.upsert_position(_rest_sync_position(take_profit_price_cents=None), caller="rest_sync")

        merged = monitor._open_positions[_MARKET]
        assert merged.take_profit_price_cents == 71

    def test_new_fill_with_own_sl_wins(self):
        """A fresh fill carrying its own SL must not be overwritten by the old."""
        monitor = _monitor()
        monitor.upsert_position(_live_no_position(), caller="position_cache")

        monitor.upsert_position(_live_no_position(stop_loss_price_cents=55), caller="position_cache")

        merged = monitor._open_positions[_MARKET]
        assert merged.stop_loss_price_cents == 55


class TestRestSyncedPositionFallback:
    def test_enabled_flag_true_allows_post_init_fallback_sl(self):
        """Fixed REST-sync construction (enabled flag preserved) still derives
        the protective fallback stop when the cache lacks an explicit SL."""
        p = Position(
            position_id="T-1",
            market_id=_MARKET,
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=Decimal("1"),
            avg_entry_price_cents=64,
            stop_loss_enabled=True,          # cached flag, not sl-derived
            stop_loss_price_cents=None,
            risk_params_state="original_persisted",
            risk_params_schema_version=2,
            client_order_id="c-1",
            entry_fill_price_cents=64,
            all_in_entry_basis_cents=64,
            thesis_side="no",
            outcome_side="no",
        )
        assert p.stop_loss_price_cents == 59  # 64 - FALLBACK_STOP_LOSS_BUFFER_CENTS(5)

    def test_untrusted_rest_only_position_still_disarmed(self):
        """A genuinely untrusted REST-only record must keep SL disabled."""
        p = Position(
            position_id="T-2",
            market_id=_MARKET,
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=Decimal("1"),
            avg_entry_price_cents=64,
            stop_loss_enabled=True,
            stop_loss_price_cents=None,
            risk_params_state="unknown",
            risk_params_schema_version=1,
            thesis_side="no",
            outcome_side="no",
        )
        assert p.stop_loss_price_cents is None
        assert p.stop_loss_enabled is False


class TestHardStopFloor:
    def test_hard_stop_fires_after_confirmations(self, monkeypatch):
        """Two executable observations below the hard floor emit a candidate."""
        import merid.position_management.position_monitor as pm

        recorded = []
        submitted = []
        monkeypatch.setattr(pm, "record_stop_candidate", lambda c: recorded.append(c))
        monkeypatch.setattr(pm, "maybe_submit_stop_candidate_sync", lambda c: submitted.append(c))

        monitor = _monitor()
        position = _live_no_position()
        snap = _snapshot(bid=45, ask=47)

        kind1 = monitor._evaluate_stop_loss(position, 45, snap)
        assert kind1 == (False, "hard_stop_pending_confirmation")
        kind2 = monitor._evaluate_stop_loss(position, 45, snap)
        assert kind2 == (False, "hard-candidate")
        assert len(recorded) == 1
        assert recorded[0].trigger_reason == "HARD_STOP"

    def test_missing_bid_size_does_not_block_hard_floor(self, monkeypatch):
        """A snapshot lacking depth annotation must still evaluate the
        catastrophic floor (observed at poll 40 of the incident)."""
        import merid.position_management.position_monitor as pm

        recorded = []
        monkeypatch.setattr(pm, "record_stop_candidate", lambda c: recorded.append(c))
        monkeypatch.setattr(pm, "maybe_submit_stop_candidate_sync", lambda c: None)

        monitor = _monitor()
        position = _live_no_position()

        # First confirmation with full depth.
        snap_full = _snapshot(bid=45, ask=47)
        monitor._evaluate_stop_loss(position, 45, snap_full)
        assert position.soft_stop_observations == 1

        # Second poll: bid present, depth annotation missing -> must still
        # reach the hard-stop block (previously returned "no-bid-size").
        snap_thin = _snapshot(bid=42, ask=43, has_bid_size=False)
        kind = monitor._evaluate_stop_loss(position, 42, snap_thin)
        assert kind == (False, "hard-candidate")
        assert len(recorded) == 1

    def test_missing_bid_size_still_blocks_soft_path(self):
        """When price is NOT through the hard floor, no-bid-size still defers."""
        monitor = _monitor()
        position = _live_no_position()
        snap = _snapshot(bid=62, ask=63, has_bid_size=False)  # above hard floor 58
        triggered, kind = monitor._evaluate_stop_loss(position, 62, snap)
        assert kind == "no-bid-size"
