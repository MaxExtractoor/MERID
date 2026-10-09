"""Stop replay for the StopCandidate event path.

Feeds synthetic market/position snapshots through the stop pipeline and
verifies that a legacy stop trigger is converted to a ``StopCandidate`` event,
never to an ``ExitReason.STOP_LOSS`` exit, and that automatic submission is
gated until replay tests pass.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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

    @pytest.mark.asyncio
    async def test_unverifiable_position_fails_closed(self, monkeypatch):
        """2026-10-09 BTC audit: a failed REST+cache position fetch returns
        ``None`` — unknown is NOT flat.  The candidate must be recorded and the
        submission blocked with an explicit diagnostic reason; silently
        treating ``None`` as 0 cancelled live protective stops."""
        from merid.event_venues.kalshi import stop_candidate as sc

        recorded = []
        monkeypatch.setattr(sc, "record_stop_candidate", lambda c: recorded.append(c))

        async def _no_exposure(*a, **kw):
            return None, None, None

        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_intent_contract.fetch_fresh_signed_yes_exposure",
            _no_exposure,
        )
        candidate = StopCandidate(
            market_ticker="KXBTC15M-TEST",
            trigger_reason="HARD_STOP",
            position_from_exchange_cc=-100,
            candidate_id="sc-unknown-pos",
        )
        result = await sc.maybe_submit_stop_candidate(candidate, force=True)
        assert result is not None
        assert result.status == "rejected"
        assert result.reason == "stop_candidate_exchange_position_unknown"
        assert recorded and recorded[0].candidate_id == "sc-unknown-pos"

    @pytest.mark.asyncio
    async def test_verified_flat_position_still_short_circuits(self, monkeypatch):
        """A successful exchange snapshot with the ticker absent returns an
        explicit 0 — verified flat keeps the flat branch (residual cleanup),
        distinct from the fail-closed unknown path."""
        from merid.event_venues.kalshi import stop_candidate as sc

        recorded = []
        monkeypatch.setattr(sc, "record_stop_candidate", lambda c: recorded.append(c))

        async def _flat_exposure(*a, **kw):
            return 0, None, None

        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_intent_contract.fetch_fresh_signed_yes_exposure",
            _flat_exposure,
        )
        # Keep the residual tracker off the production artifact.
        import merid.event_venues.kalshi.residual_exit as _residual_mod
        _closed = []
        monkeypatch.setattr(
            _residual_mod,
            "get_residual_exit_tracker",
            lambda *a, **kw: SimpleNamespace(
                close_for_ticker=lambda t: _closed.append(t) or 1
            ),
        )
        candidate = StopCandidate(
            market_ticker="KXBTC15M-TEST",
            trigger_reason="HARD_STOP",
            position_from_exchange_cc=-100,
            candidate_id="sc-flat-pos",
        )
        result = await sc.maybe_submit_stop_candidate(candidate, force=True)
        assert result is not None
        assert result.status == "rejected"
        assert result.reason == "stop_candidate_exchange_position_flat"

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

        from datetime import datetime, timedelta
        from merid.position_management.position import RiskParamsState
        opened_at = datetime.utcnow() - timedelta(seconds=100)
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=49,
            risk_params_state=RiskParamsState.ORIGINAL_PERSISTED,
            risk_params_schema_version=2,
            entry_fill_id="test-fill-001",
            entry_fill_timestamp=opened_at,
            entry_book_capture_quality="AT_FILL",
            entry_executable_bid_cents=49,
            entry_executable_ask_cents=50,
            opened_at=opened_at,
        )
        position.soft_stop_observations = 1
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


class TestStopCandidateSubmissionIntent:
    """A submitted stop-candidate must produce an exit OrderIntent with safety provenance."""

    @pytest.mark.asyncio
    async def test_hard_stop_builds_safety_exit_intent(
        self, monkeypatch, tmp_path
    ):
        """A HARD_STOP candidate produces a reduce-only IOC close with parent linkage."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from merid.event_venues.kalshi import stop_candidate
        from merid.event_venues.kalshi.order_router import (
            OrderResult,
            TradingMode,
        )

        stop_candidate._STOP_CANDIDATE_LEDGER_PATH = tmp_path / "stop_candidates.jsonl"
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "true")
        # 2026-09: discretionary triggers additionally require the EV exit
        # gate; enable it here so the test still exercises intent building.
        monkeypatch.setattr(
            "merid.event_venues.kalshi.settlement_aligned_exit.ev_exit_gate_enabled",
            lambda: True,
        )

        cached_position = SimpleNamespace(
            exit_policy_id="ep_test_001",
            entry_fill_id="fill_test_001",
            entry_order_id="order_test_001",
            client_order_id="coid_test_001",
            entry_signal_id="signal_test_001",
            _yes_exposure=lambda: 200,
            avg_price_cents=45,
            side="yes",
        )
        fake_cache = SimpleNamespace(get_position=lambda _t: cached_position)

        # No live REST position fetch in tests — exercise the cache fallback.
        async def _no_positions_result():
            return SimpleNamespace(success=False, error="test_no_rest", data=None)

        _no_client = SimpleNamespace(get_positions_result=_no_positions_result)
        monkeypatch.setattr(
            "merid.event_venues.kalshi.client.get_kalshi_client",
            lambda: _no_client,
        )

        candidate = StopCandidate(
            market_ticker="KXBTC15M-TEST",
            trigger_reason="HARD_STOP",
            position_from_exchange_cc=200,
            executable_exit_cents=30,
            seconds_to_expiry=600.0,
            quote_age_ms=0,
        )

        expected_result = OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason="test_paper",
        )

        with patch(
            "merid.event_venues.kalshi.position_cache.get_position_cache",
            return_value=fake_cache,
        ), patch(
            "merid.event_venues.kalshi.order_router.route_order_async",
            new=AsyncMock(return_value=expected_result),
        ) as mock_route:
            result = await maybe_submit_stop_candidate(candidate, force=False)

        assert result is expected_result
        assert mock_route.called, "route_order_async should be called"
        intent = mock_route.call_args[0][0]
        assert intent.source == "stop_candidate"
        assert intent.agent_id == "stop_candidate"
        assert intent.exit_reason == "HARD_STOP"
        assert intent.exit_policy_id == "ep_test_001"
        assert intent.parentage_status == "CANONICAL_FILL"
        assert intent.parent_entry_fill_id == "fill_test_001"
        assert intent.parent_entry_order_id == "order_test_001"
        assert intent.parent_entry_signal_id == "signal_test_001"
        assert intent.reduce_only is True
        assert intent.time_in_force == "ioc"
        assert intent.entry_or_exit == "exit"


class TestTakeProfitRetryObligation:
    """2026-10-09 BTC-090445 replay: a take-profit exit that fired and was
    rejected by the execution firewall (``limit_not_executable``) re-arms the
    position with ``exit_retry_count > 0``.  While the configured TP condition
    still holds, the discretionary overpay floor must not cancel the
    outstanding obligation — the retry emits at the executable own-side bid.
    """

    def _position(self):
        import time as _t
        from datetime import datetime, timedelta
        from merid.position_management.position import (
            Position,
            PositionSide,
            RiskParamsState,
        )

        opened_at = datetime.utcnow() - timedelta(seconds=120)
        position = Position(
            market_id="KXBTC15M-TPRETRY-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=70,
            entry_fill_price_cents=70,
            take_profit_price_cents=78,
            stop_loss_price_cents=None,
            stop_loss_enabled=False,
            risk_params_state=RiskParamsState.ORIGINAL_PERSISTED,
            risk_params_schema_version=2,
            entry_fill_id="btc-fill-001",
            entry_fill_timestamp=opened_at,
            entry_book_capture_quality="AT_FILL",
            entry_executable_bid_cents=69,
            entry_executable_ask_cents=71,
            entry_model_probability=0.82,
            opened_at=opened_at,
        )
        # TP debounce already satisfied — the trigger condition holds.
        position.tp_debounce_first_seen_at = _t.monotonic() - 60.0
        return position

    def _snapshot(self, position, bid=79):
        from merid.position_management.exit_audit import ExitPriceSnapshot
        return ExitPriceSnapshot(
            market_id=position.market_id,
            position_side=position.side,
            mid_cents=bid,
            own_side_bid_cents=bid,
            own_side_ask_cents=bid + 2,
            opposite_bid_cents=None,
            opposite_ask_cents=None,
            book_age_ms=0,
            data_source="ws_live",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id="replay-btc",
            timestamp=0.0,
            min_depth_own_side=10,
        )

    @pytest.mark.asyncio
    async def test_rejected_tp_retry_bypasses_overpay_floor(self):
        """First eval (no outstanding attempt): floor may hold.  After a
        rejected attempt re-arms (exit_retry_count=1), the same eval must
        emit TAKE_PROFIT repriced to the executable bid."""
        from unittest.mock import Mock
        from merid.position_management.position_monitor import PositionMonitor
        from merid.position_management.exit_policy import ExitReason

        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = self._position()
        monitor.add_position(position)
        snapshot = self._snapshot(position, bid=79)

        # Baseline: fair=82 + cost > 79 — a fresh TP opportunity is suppressed.
        await monitor._check_position(position, snapshot)
        fresh_calls = [
            c for c in callback.call_args_list
            if len(c.args) > 1 and c.args[1] == ExitReason.TAKE_PROFIT
        ]

        # Simulate the firewall rejection + re-arm (BTC: limit=81 vs vwap=79).
        position.exit_retry_count = 1
        monitor._clear_exit_intent_in_flight(position.position_id)

        await monitor._check_position(position, snapshot)

        retry_calls = [
            c for c in callback.call_args_list
            if len(c.args) > 1 and c.args[1] == ExitReason.TAKE_PROFIT
        ]
        assert len(retry_calls) > len(fresh_calls), (
            "outstanding TP obligation must re-emit despite the overpay floor"
        )
        # The emitted price must be the executable own-side bid, not the stale
        # TP level (repriced inside _emit_exit_intent).
        assert retry_calls[-1].args[2] == 79


class TestTrailingActivationBlindSpot:
    """Reproduces KXBTC15M-26OCT090445-45 (2026-10-09): the trail armed at
    +6c, but activation required a further 30s elapsed delay while the whole
    profitable window lasted ~40s — the position collapsed before the trail
    could activate and settled at a full loss.

    Fixed behavior: activation fires the first tick the validated executable
    own-side bid covers entry+min_profit; no elapsed delay.  Armed state
    persists across a pullback below the threshold.
    """

    def _position(self):
        from datetime import datetime, timedelta
        from merid.position_management.position import (
            Position,
            PositionSide,
            RiskParamsState,
            TrailingType,
        )

        opened_at = datetime.utcnow() - timedelta(seconds=120)
        position = Position(
            market_id="KXBTC15M-TRAIL-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=70,
            entry_fill_price_cents=70,
            take_profit_price_cents=None,
            stop_loss_price_cents=None,
            stop_loss_enabled=False,
            trailing_type=TrailingType.FIXED_CENTS,
            trailing_param=5.0,
            risk_params_state=RiskParamsState.ORIGINAL_PERSISTED,
            risk_params_schema_version=2,
            entry_fill_id="btc-fill-trail",
            entry_fill_timestamp=opened_at,
            entry_book_capture_quality="AT_FILL",
            entry_executable_bid_cents=69,
            entry_executable_ask_cents=71,
            entry_model_probability=0.82,
            opened_at=opened_at,
        )
        return position

    def _snapshot(self, position, bid):
        from merid.position_management.exit_audit import ExitPriceSnapshot
        return ExitPriceSnapshot(
            market_id=position.market_id,
            position_side=position.side,
            mid_cents=bid,
            own_side_bid_cents=bid,
            own_side_ask_cents=bid + 2,
            opposite_bid_cents=None,
            opposite_ask_cents=None,
            book_age_ms=0,
            data_source="ws_live",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id="replay-trail",
            timestamp=0.0,
            min_depth_own_side=10,
        )

    @pytest.mark.asyncio
    async def test_trail_activates_without_delay_and_fires_on_retrace(self):
        """BTC window: bid 82 (+12 >= min_profit) -> pullback to 77.
        Old code: armed at +12 but needed +30s elapsed -> never activated.
        New code: activates the same tick, then a 5c retrace fires TRAIL."""
        from unittest.mock import Mock
        from merid.position_management.position_monitor import PositionMonitor
        from merid.position_management.exit_policy import ExitReason

        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = self._position()
        monitor.add_position(position)

        # Tick 1: executable bid covers entry + min_profit (12c default).
        await monitor._check_position(position, self._snapshot(position, bid=82))
        assert position.trailing_activated, (
            "trail must activate on the first tick the executable bid covers "
            "entry+min_profit — no elapsed-delay dead zone"
        )

        # Tick 2: 5c retrace from the 82 high-watermark hits the trail level.
        await monitor._check_position(position, self._snapshot(position, bid=77))
        trail_calls = [
            c for c in callback.call_args_list
            if len(c.args) > 1 and c.args[1] == ExitReason.TRAIL
        ]
        assert trail_calls, (
            "armed trail must fire on retrace below the trail level "
            "(max_favorable=82, distance=5 -> trail=77)"
        )

    @pytest.mark.asyncio
    async def test_armed_state_survives_pullback_below_threshold(self):
        """Pullback below min_profit must not disarm: an armed trail retains
        its state and can activate when the executable profit returns."""
        from unittest.mock import Mock
        from merid.position_management.position_monitor import PositionMonitor

        monitor = PositionMonitor()
        monitor.register_exit_intent_callback(Mock())

        position = self._position()
        monitor.add_position(position)

        # Arm + activate at +12.
        await monitor._check_position(position, self._snapshot(position, bid=82))
        assert position.trailing_activated

        # Pullback to +4 (below min_profit) — still inside trail level (77).
        # The trail stays engaged; a fresh dip below 77 would still fire.
        await monitor._check_position(position, self._snapshot(position, bid=80))
        assert position.trailing_activated
        assert position.max_favorable_price_cents == 82


class TestLockedWsDivergentExitQuote:
    """A locked WS top diverging from fresh REST is a phantom bid — exits must
    price off REST or the IOC asks for prices that no longer exist.

    Reproduces KXBTC15M-26SEP251115-15 (2026-09-25): WS book frozen at 62-64
    while the exchange traded 43/44; the trail exit priced SELL_YES@57c, could
    never fill, and the position rode to settlement for -45c.
    """

    def _state(self, ws_bid, ws_ask, rest_bid, rest_ask, rest_age_s=0.2):
        import time as _t
        return SimpleNamespace(
            best_bid_cents=ws_bid,
            best_ask_cents=ws_ask,
            no_bid_cents=None,
            book=None,
            last_ws_bid_cents=ws_bid,
            last_ws_ask_cents=ws_ask,
            last_rest_bid_cents=rest_bid,
            last_rest_ask_cents=rest_ask,
            last_rest_quote_update_ts=_t.monotonic() - rest_age_s,
        )

    def test_locked_ws_divergent_rest_uses_rest_bid_yes(self):
        from merid.event_venues.kalshi.stop_candidate import _get_executable_exit_cents
        st = self._state(ws_bid=62, ws_ask=62, rest_bid=43, rest_ask=44)
        assert _get_executable_exit_cents(st, "yes") == 43

    def test_locked_ws_divergent_rest_uses_rest_bid_no(self):
        from merid.event_venues.kalshi.stop_candidate import _get_executable_exit_cents
        # held no: REST-derived no-bid = 100 - rest_yes_ask
        st = self._state(ws_bid=55, ws_ask=55, rest_bid=66, rest_ask=67)
        # ws no-bid = 100-55 = 45; rest no-bid = 100-67 = 33; divergence 12 > 3
        assert _get_executable_exit_cents(st, "no") == 33

    def test_unlocked_ws_keeps_ws_bid(self):
        from merid.event_venues.kalshi.stop_candidate import _get_executable_exit_cents
        st = self._state(ws_bid=62, ws_ask=63, rest_bid=43, rest_ask=44)
        assert _get_executable_exit_cents(st, "yes") == 62

    def test_locked_ws_stale_rest_keeps_ws_bid(self):
        from merid.event_venues.kalshi.stop_candidate import _get_executable_exit_cents
        st = self._state(ws_bid=62, ws_ask=62, rest_bid=43, rest_ask=44, rest_age_s=30.0)
        assert _get_executable_exit_cents(st, "yes") == 62

    def test_locked_ws_coherent_rest_keeps_ws_bid(self):
        from merid.event_venues.kalshi.stop_candidate import _get_executable_exit_cents
        st = self._state(ws_bid=62, ws_ask=62, rest_bid=61, rest_ask=63)
        assert _get_executable_exit_cents(st, "yes") == 62
