"""Stop replay for the StopCandidate event path.

Feeds synthetic market/position snapshots through the stop pipeline and
verifies that a legacy stop trigger is converted to a ``StopCandidate`` event,
never to an ``ExitReason.STOP_LOSS`` exit, and that automatic submission is
gated until replay tests pass.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from merid.event_venues.kalshi.binary_price_space import to_signed_yes_exposure
from merid.event_venues.kalshi.stop_candidate import (
    STOP_EDGE_HYSTERESIS_CENTS,
    STOP_EDGE_MIN_CONSECUTIVE,
    STOP_EDGE_TOTAL_EXIT_COST_CENTS,
    StopCandidate,
    StopOrderInvariantError,
    build_stop_candidate,
    evaluate_edge_stop,
    maybe_submit_stop_candidate,
    record_stop_candidate,
    settlement_phase_allows_stop,
    validate_stop_order_invariants,
)
from merid.event_venues.kalshi.order_intent_contract import CanonicalOrderIntent


class TestStopCandidateReplay:
    """Replay-style tests for the stop-candidate lifecycle."""

    def _kalshi_state(self, yes_bid: int, yes_ask: int, no_bid: int, no_ask: int, seconds_to_expiry: float = 600.0):
        return SimpleNamespace(
            best_bid_cents=yes_bid,
            best_ask_cents=yes_ask,
            no_bid_cents=no_bid,
            no_ask_cents=no_ask,
            book=SimpleNamespace(
                best_yes_bid=yes_bid,
                best_yes_ask=yes_ask,
                yes_bids=[SimpleNamespace(price_cents=yes_bid)],
                no_bids=[SimpleNamespace(price_cents=no_bid)],
            ),
            book_sequence=123,
            book_updated_ts=0.0,
            seconds_to_expiry=seconds_to_expiry,
        )

    def _unified_state(self, fair_yes: float, seconds_to_expiry: float = 600.0):
        return SimpleNamespace(
            external_fair_value=fair_yes,
            book=SimpleNamespace(
                best_yes_bid=50,
                best_yes_ask=51,
                yes_bids=[SimpleNamespace(price_cents=50)],
                no_bids=[SimpleNamespace(price_cents=49)],
            ),
            seconds_to_expiry=seconds_to_expiry,
        )

    def test_build_stop_candidate_from_live_state(self, tmp_path):
        """A StopCandidate carries fair value, executable exit, and expiry from market state."""
        # Override the ledger path so the test does not write to the repo.
        from merid.event_venues.kalshi import stop_candidate
        stop_candidate._STOP_CANDIDATE_LEDGER_PATH = tmp_path / "stop_candidates.jsonl"

        kalshi = self._kalshi_state(yes_bid=48, yes_ask=51, no_bid=49, no_ask=52)
        unified = self._unified_state(fair_yes=0.45)

        position_cc = to_signed_yes_exposure("yes", 10) * 100
        candidate = build_stop_candidate(
            market_ticker="KXBTC15M-TEST",
            exchange_position_cc=position_cc,
            trigger_reason="EDGE_STOP",
            entry_price_cents=50,
            kalshi_state=kalshi,
            unified_state=unified,
            quote_age_ms=25,
        )

        assert candidate.market_ticker == "KXBTC15M-TEST"
        assert candidate.position_from_exchange_cc == position_cc
        assert candidate.held_contract == "yes"
        assert candidate.held_contracts_cc == position_cc
        assert candidate.fair_value_cents == 45
        assert candidate.model_fair_value_cents == 45
        assert candidate.executable_exit_cents == 48
        assert candidate.entry_price_cents == 50
        assert candidate.quote_age_ms == 25
        assert candidate.total_exit_cost_cents == STOP_EDGE_TOTAL_EXIT_COST_CENTS
        assert candidate.hysteresis_cents == STOP_EDGE_HYSTERESIS_CENTS

    def test_edge_stop_fires_when_fair_below_executable_minus_costs(self):
        """Edge stop fires when the model fair value is below the executable bid + costs."""
        fair = 40
        executable = 48
        assert evaluate_edge_stop(fair, executable, total_exit_cost_cents=2, hysteresis_cents=1) is True

    def test_edge_stop_hysteresis_blocks_noise(self):
        """A fair value just inside the buffer does not fire."""
        fair = 46
        executable = 48
        # close_long_yes iff fair + total_exit_cost + hysteresis <= executable
        # 46 + 2 + 1 = 49 > 48, so no fire
        assert evaluate_edge_stop(fair, executable, total_exit_cost_cents=2, hysteresis_cents=1) is False

    def test_settlement_phase_gates_late_stops(self):
        """Far from expiry an edge stop is allowed; in the close window any stop is blocked."""
        allowed, reason = settlement_phase_allows_stop(600.0, "EDGE_STOP", consecutive_edge_below=5)
        assert allowed is True

        allowed, reason = settlement_phase_allows_stop(30.0, "EDGE_STOP", consecutive_edge_below=5)
        assert allowed is False
        assert "close_window" in reason

    @pytest.mark.asyncio
    async def test_submission_gated_until_replay_tests_pass(self, tmp_path, monkeypatch):
        """Automatic StopCandidate submission is disabled by default."""
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "false")
        # Ensure module reads the env at call time.
        from merid.event_venues.kalshi import stop_candidate
        stop_candidate.ENABLE_STOP_CANDIDATE_SUBMISSION = stop_candidate._env_bool("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", False)

        candidate = StopCandidate(
            market_ticker="KXBTC15M-TEST",
            trigger_reason="EDGE_STOP",
            position_from_exchange_cc=1000,
            held_contract="yes",
            fair_value_cents=45,
            executable_exit_cents=48,
            quote_age_ms=0,
        )
        result = await maybe_submit_stop_candidate(candidate)
        assert result is not None
        assert result.status == "rejected"
        assert "stop_candidate_submission_disabled" in result.reason

    def test_validate_stop_order_invariants_rejects_non_reduce_only(self):
        """A stop-generated close must be reduce-only."""
        canonical = CanonicalOrderIntent(
            market_ticker="KXBTC15M-TEST",
            contract="yes",
            action="sell",
            purpose="close",
            qty_cc=1000,
            limit_cents=48,
            strategy_signal="down",
            expected_position_before=1000,
            expected_position_after=0,
            expected_realized_pnl_cents=None,
            reason="test",
            reduce_only=False,
            time_in_force="ioc",
        )
        with pytest.raises(StopOrderInvariantError):
            validate_stop_order_invariants(
                canonical,
                exchange_position_cc=1000,
                quote_age_ms=0,
                position_snapshot_age_ms=0,
            )

    def test_validate_stop_order_invariants_rejects_gtc_stop(self):
        """A stop-generated close must be IOC or FOK."""
        canonical = CanonicalOrderIntent(
            market_ticker="KXBTC15M-TEST",
            contract="yes",
            action="sell",
            purpose="close",
            qty_cc=1000,
            limit_cents=48,
            strategy_signal="down",
            expected_position_before=1000,
            expected_position_after=0,
            expected_realized_pnl_cents=None,
            reason="test",
            reduce_only=True,
            time_in_force="gtc",
        )
        with pytest.raises(StopOrderInvariantError):
            validate_stop_order_invariants(
                canonical,
                exchange_position_cc=1000,
                quote_age_ms=0,
                position_snapshot_age_ms=0,
            )

    def test_validate_stop_order_invariants_enforces_full_close(self):
        """A stop-generated close must reduce the full position."""
        canonical = CanonicalOrderIntent(
            market_ticker="KXBTC15M-TEST",
            contract="yes",
            action="sell",
            purpose="close",
            qty_cc=500,  # does not match the full 1000 position
            limit_cents=48,
            strategy_signal="down",
            expected_position_before=1000,
            expected_position_after=0,  # claims full close but qty is partial
            expected_realized_pnl_cents=None,
            reason="test",
            reduce_only=True,
            time_in_force="ioc",
        )
        with pytest.raises(StopOrderInvariantError):
            validate_stop_order_invariants(
                canonical,
                exchange_position_cc=1000,
                quote_age_ms=0,
                position_snapshot_age_ms=0,
            )

    @pytest.mark.asyncio
    @patch("merid.position_management.position_monitor.record_stop_candidate")
    @patch("merid.position_management.position_monitor.maybe_submit_stop_candidate_sync")
    async def test_position_monitor_replay_emits_stop_candidate_not_exit(
        self, mock_submit, mock_record, tmp_path
    ):
        """A market replay that hits the SL records a StopCandidate and does not emit EXIT."""
        from merid.position_management.position import Position, PositionSide
        from merid.position_management.position_monitor import PositionMonitor

        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=49,
        )
        monitor.add_position(position)

        from merid.position_management.exit_audit import ExitPriceSnapshot
        snapshot = ExitPriceSnapshot(
            market_id=position.market_id,
            position_side=position.side,
            mid_cents=50,
            own_side_bid_cents=48,
            own_side_ask_cents=51,
            opposite_bid_cents=None,
            opposite_ask_cents=None,
            book_age_ms=0,
            data_source="ws_live",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id="replay-1",
            timestamp=0.0,
            min_depth_own_side=10,
        )

        await monitor._check_position(position, snapshot)

        callback.assert_not_called()
        mock_record.assert_called_once()
        candidate = mock_record.call_args[0][0]
        assert isinstance(candidate, StopCandidate)
        assert candidate.market_ticker == position.market_id
        assert candidate.held_contract == "yes"
        assert candidate.position_from_exchange_cc == 1000
