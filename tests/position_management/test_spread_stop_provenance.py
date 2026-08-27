"""
Provenance and entry-book invariants for spread-stop protection.

These tests verify that:
- A legacy position with unknown provenance can never become trusted.
- A post-fill / later book cannot be recorded as the entry executable book.
- A production hard stop requires an executable, fresh, AT_FILL book,
  multiple confirmations, and an adverse move beyond the entry spread.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from merid.position_management.position import (
    Position,
    PositionSide,
    RiskParamsState,
)
from merid.position_management.position_monitor import (
    PositionMonitor,
    HARD_STOP_EXTRA_BUFFER_CENTS,
    SOFT_STOP_MIN_OBSERVATIONS,
)
from merid.position_management.exit_audit import ExitPriceSnapshot


@pytest.fixture(autouse=True)
def _patch_stop_submission_sync(monkeypatch):
    """Stop-candidate submission is not under test here; suppress the
    fire-and-forget async task so the event loop does not leave pending
    ``KalshiVenueClient.get_positions`` / ``maybe_submit_stop_candidate``
    tasks to be destroyed at teardown.
    """
    monkeypatch.setattr(
        "merid.position_management.position_monitor.maybe_submit_stop_candidate_sync",
        Mock(),
    )


def _untrusted_position(**kwargs) -> Position:
    """Legacy / unknown-provenance position used for laundering tests."""
    return Position(
        risk_params_state="unknown",
        risk_params_schema_version=1,
        fill_source="rest_sync",
        **kwargs,
    )


def _trusted_position(**kwargs) -> Position:
    """Version-2, AT_FILL provenance position used for production-path tests."""
    entry_price = kwargs.get("avg_entry_price_cents", 50)
    defaults = {
        "risk_params_state": "original_persisted",
        "risk_params_schema_version": 2,
        "client_order_id": "test-client",
        "entry_fill_id": "test-fill",
        "fill_source": "ws",
        "entry_book_capture_quality": "AT_FILL",
        "entry_executable_bid_cents": entry_price - 1,
        "entry_executable_ask_cents": entry_price + 1,
        "entry_fill_price_cents": entry_price,
        "entry_fill_timestamp": datetime.now(timezone.utc) - timedelta(seconds=10),
        "entry_book_timestamp": datetime.now(timezone.utc) - timedelta(seconds=10),
    }
    defaults.update(kwargs)
    return Position(**defaults)


def _snapshot(position: Position, bid: int, ask: int) -> ExitPriceSnapshot:
    return ExitPriceSnapshot(
        market_id=position.market_id,
        position_side=position.side,
        mid_cents=(bid + ask) // 2,
        own_side_bid_cents=bid,
        own_side_ask_cents=ask,
        opposite_bid_cents=None,
        opposite_ask_cents=None,
        book_age_ms=0,
        data_source="ws_live",
        data_quality="GOOD",
        executable=True,
        has_bid_size=True,
        snapshot_id=f"{position.market_id}:test",
        timestamp=0.0,
        min_depth_own_side=10,
        book_sequence=123,
    )


class TestFallbackTakeProfitSafety:
    """A fallback TP must be based on a trusted fill price and clear the fee buffer."""

    def test_fallback_tp_uses_entry_fill_price(self):
        # CRITICAL FIX (2026-08-12): A fallback TP is only set when the entry model
        # is present. It uses the trusted fill price as the entry and is capped at
        # the model fair value minus estimated exit fee and a 1c buffer.
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            entry_fill_price_cents=49,
            entry_market_probability=0.49,
            entry_model_probability=0.60,
            stop_loss_price_cents=40,
            take_profit_price_cents=None,
            risk_params_state="original_persisted",
            risk_params_schema_version=2,
        )
        assert position.take_profit_price_cents is not None
        # fair 60c - fee 2c - 1c buffer = 57c; 75% of 11c edge = 8.25c; TP = 49 + 8 = 57c
        assert position.take_profit_price_cents == 57

    def test_unknown_position_with_no_fill_price_gets_no_tp(self):
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=0,
            entry_fill_price_cents=None,
            take_profit_price_cents=None,
            risk_params_state="unknown",
            risk_params_schema_version=1,
        )
        assert position.take_profit_price_cents is None


class TestProvenanceLaundering:
    """A legacy position with unknown risk provenance must stay disabled."""

    def test_position_post_init_does_not_promote_unknown_sl(self):
        position = _untrusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=49,
            take_profit_price_cents=60,
        )
        assert position.risk_params_state == RiskParamsState.UNKNOWN
        assert position.risk_params_schema_version == 1
        assert position.stop_loss_enabled is False
        assert position.stop_loss_price_cents is None
        assert position.hard_stop_price_cents is None

    def test_position_downgrades_original_without_linkage(self):
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=49,
            take_profit_price_cents=60,
            risk_params_state="original_persisted",
            risk_params_schema_version=2,
            # No client_order_id, entry_intent_id, or entry_fill_id
        )
        assert position.risk_params_state == RiskParamsState.UNKNOWN
        assert position.stop_loss_enabled is False
        assert position.stop_loss_price_cents is None

    @pytest.mark.asyncio
    async def test_monitor_blocks_unknown_stop(self):
        monitor = PositionMonitor()
        position = _untrusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        monitor.add_position(position)

        triggered, kind = monitor._evaluate_stop_loss(
            position, 30, _snapshot(position, 30, 32)
        )
        assert triggered is False
        assert kind in ("none", "risk_params_not_original", "untrusted_entry_book")


class TestBookTimestampContamination:
    """Only an AT_FILL entry book may be used for spread-only invariants."""

    def test_post_fill_book_is_not_trusted(self):
        # Position pretending a later book was the entry book.
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=54,  # SELL YES 46c -> long NO at 54c
            stop_loss_price_cents=57,
            take_profit_price_cents=60,
            risk_params_state="original_persisted",
            risk_params_schema_version=2,
            client_order_id="test-client",
            entry_fill_id="test-fill",
            fill_source="ws",
            # Claim a later book (YES ask 53c -> NO bid 47c) as the entry book.
            entry_executable_bid_cents=47,
            entry_executable_ask_cents=54,
            entry_book_capture_quality="POST_FILL",
        )
        # __post_init__ must discard an untrusted entry book.
        assert position.entry_executable_bid_cents is None
        assert position.entry_executable_ask_cents is None
        assert position.entry_book_capture_quality == "POST_FILL"

    @pytest.mark.asyncio
    async def test_untrusted_book_blocks_spread_only_stop(self):
        # Long NO at 54c, current NO bid 47c (adverse 7c equals the spread).
        # The stop is set at 57c, so current 47c is far below it; without the
        # AT_FILL book guard this would be a catastrophic stop, but the entry
        # book quality must block it.
        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=54,
            stop_loss_price_cents=57,
            take_profit_price_cents=60,
            entry_executable_bid_cents=47,
            entry_executable_ask_cents=54,
            entry_book_capture_quality="POST_FILL",
        )
        position.opened_at = datetime.utcnow() - timedelta(seconds=10)
        position.time_since_entry_seconds = 10.0

        monitor = PositionMonitor()
        monitor.add_position(position)

        triggered, kind = monitor._evaluate_stop_loss(
            position, 47, _snapshot(position, 47, 48)
        )
        assert triggered is False
        assert "untrusted_entry_book" in kind


class TestProductionHardStop:
    """A production hard stop requires confirmation and adverse-move proof."""

    @pytest.mark.asyncio
    @patch("merid.position_management.position_monitor.record_stop_candidate")
    async def test_hard_stop_requires_confirmation_and_adverse_move(self, mock_record):
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        # Long YES at 50c, entry book bid=49 ask=51 (spread 2c), stop at 40c.
        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            entry_executable_bid_cents=49,
            entry_executable_ask_cents=51,
        )
        position.opened_at = datetime.utcnow() - timedelta(seconds=10)
        position.time_since_entry_seconds = 10.0
        monitor.add_position(position)

        snapshot = _snapshot(position, 35, 36)
        # First observation is not enough.
        triggered, kind = monitor._evaluate_stop_loss(position, 35, snapshot)
        assert triggered is False
        assert "hard_stop_pending_confirmation" in kind
        assert position.soft_stop_observations == 1
        assert mock_record.called is False

        # Second observation: still below hard stop (40 - 1 = 39).
        triggered, kind = monitor._evaluate_stop_loss(position, 35, snapshot)
        assert triggered is False  # Stop is converted to a StopCandidate, not a direct exit
        assert kind == "hard-candidate"
        assert mock_record.called is True
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_profit_exit_below_round_trip_buffer_blocked(self):
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        # Long YES filled at 50c.  A take-profit at 51c is below the 2c fee buffer.
        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            entry_fill_price_cents=50,
            take_profit_price_cents=51,
        )
        position.opened_at = datetime.utcnow() - timedelta(seconds=10)
        position.time_since_entry_seconds = 10.0
        monitor.add_position(position)

        # Price 51 is at the TP but not above entry + buffer.
        await monitor._legacy_check_position(position, 51)
        callback.assert_not_called()

    def test_spread_only_hard_stop_rejected(self):
        # Long YES at 50c, entry book bid=49 ask=50 (spread 1c), stop at 40c.
        # Price drops to 49c, which is below hard stop 39c? No.  Hard=39, 49 > 39.
        # Use a stop just below the entry ask to make it a spread-only scenario:
        # stop at 48c, hard=47, price 47 triggers, adverse move 50-47=3 < spread+1=2?
        # Wait 3 >= 2, so it would pass.  Make entry ask=50, bid=49, stop=48.
        # Hard=47, price=47, adverse=3, spread=1, need >=2, passes.  Not spread-only.
        # Use stop at 49 so hard=48; price 48 triggers, adverse=2, spread=1, need >=2,
        # borderline.  Use bid=49, ask=50, stop=49, current=48 (below hard 48?).
        # Hard = 49 - 1 = 48.  Current 48 <= 48.  Adverse = 50 - 48 = 2.  Spread = 1.
        # Need adverse >= 1 + 1 = 2.  2 >= 2 -> passes.  This is the edge case.
        # To force a rejection, set bid=49, ask=50, stop=49, current=49.
        # Hard = 48, current 49 > 48, no trigger.  Set current=48.
        # We want adverse < spread + buffer.  If entry ask=50, bid=49, current=49:
        # hard=48, no trigger.  If stop=50, hard=49, current=49 triggers, adverse=1,
        # spread=1, need 2, 1<2 -> rejected (spread only).  But stop at entry is not
        # a real stop.  This still proves the spread-only guard.
        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=50,
            entry_executable_bid_cents=49,
            entry_executable_ask_cents=50,
        )
        position.opened_at = datetime.utcnow() - timedelta(seconds=10)
        position.time_since_entry_seconds = 10.0
        position.soft_stop_observations = SOFT_STOP_MIN_OBSERVATIONS

        monitor = PositionMonitor()
        monitor.add_position(position)

        # Current 49 is at the stop; hard threshold is 49, so it is a hard stop
        # but the adverse move (50-49=1) is not larger than the 1c spread + buffer.
        triggered, kind = monitor._evaluate_stop_loss(position, 49, _snapshot(position, 49, 50))
        assert triggered is False
        assert "hard_stop_rejected_spread_only" in kind


class TestFallbackRiskParamsState:
    """REST-reconciled and fallback positions must not fabricate or act on stop-losses."""

    def test_fallback_position_preserves_cached_tp_sl(self):
        """A fallback state preserves cached TP/SL fields but the monitor blocks the SL."""
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=55,
            stop_loss_price_cents=40,
            stop_loss_enabled=True,
            risk_params_state="fallback",
            risk_params_schema_version=1,
            fill_source="rest_sync",
        )
        assert position.risk_params_state == RiskParamsState.FALLBACK
        # Cached TP/SL are retained as a fallback policy.
        assert position.stop_loss_enabled is True
        assert position.stop_loss_price_cents == 40
        assert position.take_profit_price_cents == 55

    def test_unknown_rest_position_does_not_invent_risk_params(self):
        """A REST-reconciled position with no cached TP/SL remains unknown and unmonitored for stops."""
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=None,
            stop_loss_price_cents=None,
            stop_loss_enabled=True,
            risk_params_state="unknown",
            risk_params_schema_version=1,
            fill_source="rest_sync",
        )
        assert position.risk_params_state == RiskParamsState.UNKNOWN
        assert position.stop_loss_enabled is False
        assert position.stop_loss_price_cents is None
        assert position.take_profit_price_cents is None

    @pytest.mark.asyncio
    async def test_monitor_blocks_fallback_stop_loss(self):
        """A fallback position with an SL field must not trigger a stop exit."""
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            stop_loss_enabled=True,
            risk_params_state="fallback",
            risk_params_schema_version=1,
            fill_source="rest_sync",
        )
        monitor = PositionMonitor()
        monitor.add_position(position)

        triggered, kind = monitor._evaluate_stop_loss(
            position, 30, _snapshot(position, 30, 32)
        )
        assert triggered is False
        assert "risk_params_not_original" in kind
