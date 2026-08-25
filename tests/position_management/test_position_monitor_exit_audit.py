"""
Exit audit, executable-bid pricing, hard/soft stop, trailing state machine,
and edge-decay guards for PositionMonitor.

These tests verify the 2026-08-09 changes that prevent immediate exits from
stale/fallback prices and provide an immutable EXIT-DECISION record per trigger.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from merid.position_management.exit_audit import ExitPriceSnapshot, ExitDecisionRecord
from merid.position_management.exit_policy import ExitAction, ExitReason
from merid.position_management.position import Position, PositionSide, TrailingState, TrailingType
from merid.position_management.position_monitor import (
    PositionMonitor,
    EXIT_PRICE_MAX_AGE_MS,
    SOFT_STOP_MIN_OBSERVATIONS,
)


def _trusted_position(**kwargs) -> Position:
    """Build a Position with version-2 provenance for test fixtures."""
    entry_price = kwargs.get("avg_entry_price_cents", 50)
    defaults = {
        "risk_params_state": "original_persisted",
        "risk_params_schema_version": 2,
        "client_order_id": "test-client",
        "entry_fill_id": "test-fill",
        "fill_source": "test",
        "entry_book_capture_quality": "AT_FILL",
        "entry_executable_bid_cents": entry_price - 1,
        "entry_executable_ask_cents": entry_price + 1,
        "entry_fill_price_cents": entry_price,
    }
    defaults.update(kwargs)
    return Position(**defaults)


class TestPositionMonitorExitPriceSnapshot:
    """Exit pricing must use the executable same-side bid, not mid or stale data."""

    def _snapshot(self, market_id, side, bid, ask, mid, age_ms=0, executable=True, has_bid_size=True):
        return ExitPriceSnapshot(
            market_id=market_id,
            position_side=side,
            mid_cents=mid,
            own_side_bid_cents=bid,
            own_side_ask_cents=ask,
            opposite_bid_cents=None,
            opposite_ask_cents=None,
            book_age_ms=age_ms,
            data_source="ws_live",
            data_quality="GOOD",
            executable=executable,
            has_bid_size=has_bid_size,
            snapshot_id=f"{market_id}:test",
            timestamp=0.0,
            min_depth_own_side=10,
        )

    @pytest.mark.asyncio
    @patch("merid.position_management.position_monitor.record_stop_candidate")
    @patch("merid.position_management.position_monitor.maybe_submit_stop_candidate_sync")
    async def test_stop_loss_converted_to_stop_candidate(self, mock_submit, mock_record):
        """Stop-loss is converted to a StopCandidate; direct callback is suppressed."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=49,
            entry_executable_bid_cents=49,
            entry_executable_ask_cents=50,
        )
        monitor.add_position(position)

        # mid=50, bid=48 (the price we can actually sell at) is below SL
        snapshot = self._snapshot(
            position.market_id, position.side, bid=48, ask=51, mid=50
        )

        # Age the position so the 5s arming guard does not suppress the stop, then
        # provide the two confirmations required for a production hard stop.
        position.opened_at = datetime.utcnow() - timedelta(seconds=5)
        position.time_since_entry_seconds = 5.0
        await monitor._check_position(position, snapshot)
        await monitor._check_position(position, snapshot)

        # Direct exit callback must NOT fire while replay tests are in progress.
        callback.assert_not_called()
        # A StopCandidate event must be recorded.
        mock_record.assert_called_once()
        candidate = mock_record.call_args[0][0]
        assert candidate.market_ticker == position.market_id
        assert candidate.position_from_exchange_cc == 1000
        assert candidate.held_contract == "yes"

    @pytest.mark.asyncio
    async def test_stop_loss_skips_stale_book(self):
        """Stop-loss must not fire from a stale market-data snapshot."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=49,
        )
        monitor.add_position(position)

        snapshot = self._snapshot(
            position.market_id, position.side, bid=1, ask=2, mid=1,
            age_ms=EXIT_PRICE_MAX_AGE_MS + 1,
        )

        await monitor._check_position(position, snapshot)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_loss_skips_missing_bid_size(self):
        """Stop-loss must not fire if there is no executable bid size."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=49,
        )
        monitor.add_position(position)

        snapshot = self._snapshot(
            position.market_id, position.side, bid=48, ask=51, mid=50,
            has_bid_size=False,
        )

        await monitor._check_position(position, snapshot)

        callback.assert_not_called()


class TestPositionMonitorHardSoftStop:
    """Hard stop fires immediately; soft stop requires confirmation."""

    @pytest.mark.asyncio
    @patch("merid.position_management.position_monitor.record_stop_candidate")
    @patch("merid.position_management.position_monitor.maybe_submit_stop_candidate_sync")
    async def test_hard_stop_converted_to_stop_candidate(self, mock_submit, mock_record):
        """A bid far below the SL records a hard-stop StopCandidate; no direct exit."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        monitor.add_position(position)

        # 35 is below 40 - HARD_STOP_EXTRA_BUFFER_CENTS, so this is a hard stop.
        # Hard stops now require executable book + confirmation; two observations needed.
        await monitor._legacy_check_position(position, 35)
        await monitor._legacy_check_position(position, 35)

        callback.assert_not_called()
        mock_record.assert_called_once()
        candidate = mock_record.call_args[0][0]
        assert candidate.market_ticker == position.market_id
        assert candidate.trigger_reason == "HARD_STOP"

    @pytest.mark.asyncio
    @patch("merid.position_management.position_monitor.record_stop_candidate")
    @patch("merid.position_management.position_monitor.maybe_submit_stop_candidate_sync")
    async def test_soft_stop_converted_to_stop_candidate_after_confirmation(self, mock_submit, mock_record):
        """A bid at the SL builds consecutive observations then records a StopCandidate."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        monitor.add_position(position)

        # 40 is at the SL but not below the hard threshold (40 - 1 = 39)
        await monitor._legacy_check_position(position, 40)
        callback.assert_not_called()
        mock_record.assert_not_called()

        # Second consecutive poll at the SL records a soft-stop StopCandidate.
        await monitor._legacy_check_position(position, 40)
        callback.assert_not_called()
        mock_record.assert_called_once()
        candidate = mock_record.call_args[0][0]
        assert candidate.market_ticker == position.market_id
        assert candidate.trigger_reason == "SOFT_STOP"

    @pytest.mark.asyncio
    async def test_soft_stop_resets_on_recovery(self):
        """If the bid recovers above the SL, the soft observation count resets."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        monitor.add_position(position)

        await monitor._legacy_check_position(position, 40)
        await monitor._legacy_check_position(position, 41)
        await monitor._legacy_check_position(position, 40)

        callback.assert_not_called()


class TestPositionMonitorTrailingStateMachine:
    """Trailing stop transitions UNARMED -> ARMED -> TRAILING -> EXIT."""

    @pytest.mark.asyncio
    async def test_trailing_state_transitions(self):
        """Trailing state machine follows the expected sequence."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            take_profit_price_cents=99,  # disable regular TP so we can reach trailing
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        monitor.add_position(position)

        # UNARMED -> ARMED when profit >= min_profit_cents (delay not elapsed yet)
        assert position.trailing_state == TrailingState.UNARMED
        await monitor._legacy_check_position(position, 65)
        assert position.trailing_state == TrailingState.ARMED

        # ARMED -> TRAILING after activation delay is bypassed
        position.trailing_profit_threshold_reached_at = 0.0
        await monitor._legacy_check_position(position, 65)
        assert position.trailing_state == TrailingState.TRAILING

        # TRAILING -> EXIT when bid drops below trail level
        # entry 50, risk 10, trail distance 5c, max_fav 65 -> trail at 60
        await monitor._legacy_check_position(position, 58)
        assert position.trailing_state == TrailingState.EXIT
        callback.assert_called_once()
        assert callback.call_args[0][1] == ExitReason.TRAIL


class TestPositionMonitorEdgeDecayGuard:
    """Edge-decay must not fire from a recomputed/fallback model immediately after entry."""

    @pytest.mark.asyncio
    async def test_edge_decay_uses_entry_edge_for_fresh_position(self):
        """For a freshly-opened position, use the entry edge instead of a new recomputed edge."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            entry_edge_pct=0.05,  # positive entry edge
        )
        monitor.add_position(position)

        with patch("merid.position_management.position_monitor.get_exit_policy_resolver") as mock_get_resolver:
            mock_resolver = Mock()
            mock_policy = Mock()
            mock_policy.action = ExitAction.HOLD
            mock_policy.reason = None
            mock_resolver.resolve.return_value = mock_policy
            mock_get_resolver.return_value = mock_resolver

            with patch(
                "merid.position_management.edge_based_exit_evaluator.EdgeBasedExitEvaluator.compute_current_edge",
                return_value=-0.35,  # would force an immediate exit if not guarded
            ):
                await monitor._legacy_check_position(position, 50)

            # Resolver must receive the guarded entry edge, not the negative recomputed edge
            call_kwargs = mock_resolver.resolve.call_args[1]
            assert call_kwargs["current_edge_pct"] == 0.05

        # Entry edge is above the default threshold, so no exit callback
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_edge_decay_allowed_after_hold_period(self):
        """After MIN_EDGE_DECAY_HOLD_SECONDS, the recomputed edge is allowed."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        # Opened long enough ago to pass the hold guard
        opened_at = datetime.utcnow() - timedelta(seconds=60)
        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            entry_edge_pct=0.05,
            opened_at=opened_at,
        )
        monitor.add_position(position)

        with patch("merid.position_management.position_monitor.get_exit_policy_resolver") as mock_get_resolver:
            mock_resolver = Mock()
            mock_policy = Mock()
            mock_policy.action = ExitAction.HOLD
            mock_policy.reason = None
            mock_resolver.resolve.return_value = mock_policy
            mock_get_resolver.return_value = mock_resolver

            with patch(
                "merid.position_management.edge_based_exit_evaluator.EdgeBasedExitEvaluator.compute_current_edge",
                return_value=-0.35,
            ):
                await monitor._legacy_check_position(position, 50)

            call_kwargs = mock_resolver.resolve.call_args[1]
            assert call_kwargs["current_edge_pct"] == -0.35

    @pytest.mark.asyncio
    async def test_replayed_position_does_not_exit_from_recomputed_edge(self):
        """REST-replay / startup-loaded positions must not be exited by fresh recomputed edge."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            entry_edge_pct=0.05,
            fill_source="rest_sync",
            entry_signal_id="rest_sync",
        )
        monitor.add_position(position)

        with patch("merid.position_management.position_monitor.get_exit_policy_resolver") as mock_get_resolver:
            mock_resolver = Mock()
            mock_policy = Mock()
            mock_policy.action = ExitAction.HOLD
            mock_policy.reason = None
            mock_resolver.resolve.return_value = mock_policy
            mock_get_resolver.return_value = mock_resolver

            with patch(
                "merid.position_management.edge_based_exit_evaluator.EdgeBasedExitEvaluator.compute_current_edge",
                return_value=-0.35,
            ):
                await monitor._legacy_check_position(position, 50)

            call_kwargs = mock_resolver.resolve.call_args[1]
            assert call_kwargs["current_edge_pct"] == 0.05


class TestExitConditionsEvaluator:
    """Pure evaluator returns decision-complete, side-aware condition records."""

    @pytest.fixture
    def base_position(self):
        return _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=45,
            take_profit_price_cents=60,
            trailing_type=TrailingType.FIXED_CENTS,
            trailing_param=5,
        )

    @pytest.fixture
    def snapshot(self):
        return ExitPriceSnapshot(
            market_id="KXBTC15M-TEST",
            position_side=PositionSide.YES,
            mid_cents=50,
            own_side_bid_cents=50,
            own_side_ask_cents=51,
            opposite_bid_cents=49,
            opposite_ask_cents=50,
            book_age_ms=0,
            data_source="ws_live",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id="test-snapshot",
            timestamp=0.0,
            min_depth_own_side=10,
            book_sequence=123,
            yes_bid_cents=50,
            yes_ask_cents=51,
            no_bid_cents=49,
            no_ask_cents=50,
            yes_depth=100,
            no_depth=120,
            entry_side_executable_bid_cents=50,
            entry_side_executable_ask_cents=51,
        )

    @pytest.mark.asyncio
    async def test_check_position_rejects_raw_integer(self, base_position):
        """Production _check_position must reject a raw integer price input."""
        monitor = PositionMonitor()
        monitor.add_position(base_position)
        with pytest.raises(TypeError):
            await monitor._check_position(base_position, 99)

    def test_evaluate_exit_conditions_decision_complete(self, base_position, snapshot):
        """Evaluator returns all exit conditions, not just the chosen one."""
        from merid.position_management.exit_conditions import evaluate_exit_conditions
        conditions = evaluate_exit_conditions(base_position, snapshot, 0.0)
        reasons = {c.reason for c in conditions}
        assert ExitReason.STOP_LOSS in reasons
        assert ExitReason.TAKE_PROFIT in reasons
        assert ExitReason.TRAIL in reasons
        assert ExitReason.EDGE_DECAY in reasons
        assert ExitReason.TIME_STOP in reasons

    def test_hard_stop_separation(self, base_position, snapshot):
        """Hard stop is SL minus the configured buffer; stop is converted to a StopCandidate."""
        from merid.position_management.exit_conditions import evaluate_exit_conditions
        from merid.position_management.position_monitor import HARD_STOP_EXTRA_BUFFER_CENTS
        base_position.hard_stop_price_cents = base_position.stop_loss_price_cents - HARD_STOP_EXTRA_BUFFER_CENTS
        snapshot.own_side_bid_cents = base_position.stop_loss_price_cents - 1
        conditions = evaluate_exit_conditions(base_position, snapshot, 0.0)
        stop_loss = [c for c in conditions if c.reason == ExitReason.STOP_LOSS][0]
        # Stop-loss is no longer eligible for direct exit; it is a StopCandidate event.
        assert stop_loss.eligible is False
        assert stop_loss.evidence["trigger_kind"] == "hard"
        assert stop_loss.evidence["hard_stop_price_cents"] == base_position.hard_stop_price_cents
        assert stop_loss.evidence["stop_loss_price_cents"] == base_position.stop_loss_price_cents
        assert stop_loss.evidence.get("stop_path_disabled") is True

    def test_soft_stop_requires_confirmation(self, base_position, snapshot):
        """Soft stop only becomes eligible after consecutive observations."""
        from merid.position_management.exit_conditions import evaluate_exit_conditions
        from merid.position_management.position_monitor import SOFT_STOP_MIN_OBSERVATIONS
        # Set observations so one more is still not enough.
        base_position.soft_stop_observations = max(0, SOFT_STOP_MIN_OBSERVATIONS - 2)
        snapshot.own_side_bid_cents = base_position.stop_loss_price_cents
        conditions = evaluate_exit_conditions(base_position, snapshot, 0.0)
        stop_loss = [c for c in conditions if c.reason == ExitReason.STOP_LOSS][0]
        assert stop_loss.eligible is False
        assert stop_loss.evidence["trigger_kind"] == "soft-pending"

    def test_trailing_state_machine_timestamps(self, base_position, snapshot):
        """Trailing arming and start persist as monotonic timestamps."""
        from merid.position_management.exit_conditions import evaluate_exit_conditions
        # Place the position in the trailing state with a known high watermark.
        base_position.trailing_state = TrailingState.TRAILING
        base_position.trail_started_at = 0.0
        base_position.trailing_activated = True
        base_position.max_favorable_price_cents = 65
        base_position.high_watermark_cents = 65
        # Ensure the min-exit-hold guard does not suppress the trail condition.
        base_position.time_since_entry_seconds = 10.0
        # Trail distance = 5c, so trail level is 60c.  Price at 59c breaches it.
        snapshot.own_side_bid_cents = 59
        conditions = evaluate_exit_conditions(base_position, snapshot, 1000.0)
        trail = [c for c in conditions if c.reason == ExitReason.TRAIL][0]
        assert trail.eligible is True
        assert trail.evidence["trail_distance_cents"] == 5
        assert trail.evidence["trail_level_cents"] == 60

    def test_edge_decay_provenance_guard(self, base_position, snapshot):
        """Edge decay is suppressed for replay/rest-sync/historical provenance."""
        from merid.position_management.exit_conditions import evaluate_exit_conditions
        base_position.fill_source = "replay"
        conditions = evaluate_exit_conditions(base_position, snapshot, 0.0)
        edge = [c for c in conditions if c.reason == ExitReason.EDGE_DECAY][0]
        assert edge.eligible is False
        assert "provenance_ineligible" in edge.evidence["ineligible_reason"]


class TestExitDecisionRecordProvenance:
    """Exit decision record carries entry model provenance and full book snapshot."""

    @pytest.fixture
    def position(self):
        return _trusted_position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=45,
            take_profit_price_cents=60,
            entry_signal_id="sig-123",
            entry_model="heuristic_velocity",
            entry_model_version="v2.4.0",
            entry_model_probability=0.72,
            entry_market_probability=0.68,
            entry_edge=0.05,
            entry_book_snapshot_id="book-123",
            entry_fill_id="fill-123",
            entry_order_id="order-123",
            entry_execution_mode="taker",
        )

    @pytest.fixture
    def snapshot(self):
        return ExitPriceSnapshot(
            market_id="KXBTC15M-TEST",
            position_side=PositionSide.YES,
            mid_cents=50,
            own_side_bid_cents=60,
            own_side_ask_cents=61,
            opposite_bid_cents=39,
            opposite_ask_cents=40,
            book_age_ms=0,
            data_source="ws_live",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id="snap-123",
            timestamp=0.0,
            min_depth_own_side=10,
            book_sequence=456,
            yes_bid_cents=60,
            yes_ask_cents=61,
            no_bid_cents=39,
            no_ask_cents=40,
            yes_depth=200,
            no_depth=180,
            entry_side_executable_bid_cents=60,
            entry_side_executable_ask_cents=61,
        )

    def test_decision_record_entry_provenance(self, position, snapshot):
        """ExitDecisionRecord records every entry-model provenance field."""
        from merid.position_management.position_monitor import HARD_STOP_EXTRA_BUFFER_CENTS
        # Ensure enough hold time so the min-exit-hold guard does not suppress TP.
        position.opened_at = datetime.utcnow() - timedelta(seconds=5)
        position.time_since_entry_seconds = 5.0
        monitor = PositionMonitor()
        record = monitor._build_exit_decision_record(
            position,
            ExitReason.TAKE_PROFIT,
            60,
            snapshot=snapshot,
        )
        assert record.signal_id == "sig-123"
        assert record.entry_model == "heuristic_velocity"
        assert record.model_version == "v2.4.0"
        assert record.entry_fill_id == "fill-123"
        assert record.entry_order_id == "order-123"
        assert record.hard_stop_level_cents == 45 - HARD_STOP_EXTRA_BUFFER_CENTS
        assert record.trigger_book_snapshot_id == "snap-123"
        assert record.trigger_book_sequence == 456
        assert record.trigger_yes_bid_cents == 60
        assert record.trigger_no_ask_cents == 40
        assert record.trigger_entry_side_executable_bid_cents == 60

    def test_decision_record_eligible_and_suppressed(self, position, snapshot):
        """TP is chosen; stop-loss is converted to a StopCandidate, not an eligible exit."""
        from merid.position_management.position_monitor import SOFT_STOP_MIN_OBSERVATIONS
        # Ensure enough hold time so TP can be eligible.
        position.opened_at = datetime.utcnow() - timedelta(seconds=5)
        position.time_since_entry_seconds = 5.0
        monitor = PositionMonitor()
        # Set SL=60 so both TP (>=60) and soft SL (<=60) would fire at price 60.
        position.stop_loss_price_cents = 60
        position.hard_stop_price_cents = 59
        # Pre-populate soft-stop observations so one more makes the soft stop fire.
        position.soft_stop_observations = SOFT_STOP_MIN_OBSERVATIONS
        snapshot.own_side_bid_cents = 60
        record = monitor._build_exit_decision_record(
            position,
            ExitReason.TAKE_PROFIT,
            60,
            snapshot=snapshot,
        )
        assert record.chosen_exit_reason == "take_profit"
        assert "take_profit" in record.eligible_exit_reasons
        # Stop-loss is no longer a direct eligible exit; it is a StopCandidate event.
        assert "stop_loss" not in record.eligible_exit_reasons
        assert "stop_loss" not in record.suppressed_exit_reasons
