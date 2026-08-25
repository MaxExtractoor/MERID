"""
Comprehensive tests for ExitPolicy evaluation logic.

Tests all policy-layer exit reasons with precedence validation:
- RISK (kill switch)
- STALE_DATA (market data staleness)
- CANDLE_REVERSAL (momentum reversal)
- ADAPTIVE_TIMING (historical performance-based)
- TIME_STOP (volatility-adjusted time-based)
- EDGE_DECAY (edge threshold)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from merid.position_management.position import Position, PositionSide, RiskParamsState
from merid.position_management.exit_policy import (
    ExitPolicy,
    ExitAction,
    ExitReason,
)
from merid.position_management.exit_decision import ExitDecision, ExitSourceLayer, get_priority_for_reason
from merid.position_management.exit_policy_resolver import (
    ExitPolicyResolver,
    get_exit_policy_resolver,
)


class TestExitPolicy:
    """Test ExitPolicy evaluation logic."""
    
    def test_evaluate_risk_kill_switch(self):
        """Test risk kill switch triggers exit."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=10.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=True,
        )
        
        exit_decision = policy.evaluate()
        
        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.RISK
        assert exit_decision.source_layer == ExitSourceLayer.POLICY_LAYER
        assert policy.action == ExitAction.EXIT_MARKET  # Backward compatibility
        assert policy.reason == ExitReason.RISK
    
    def test_evaluate_time_stop_losing(self):
        """Test time stop does NOT trigger on losing position (< 0.5R) at max hold.

        CRITICAL FIX (2026-07-31): Time stop now only exits stalled winners (>= 0.5R),
        preventing systematic loss exits. Losers are left for the stop-loss path.
        """
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=45,
            unrealized_pnl_cents=-50,
            r_multiple=-5.0,  # < 0.5R
            time_since_entry_seconds=900.0,  # At max hold
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )

        exit_decision = policy.evaluate()

        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_evaluate_time_stop_no_progress(self):
        """Test time stop does NOT trigger on no progress (< 0.5R) at max hold."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=52,
            unrealized_pnl_cents=20,
            r_multiple=0.2,  # < 0.5R (no meaningful progress)
            time_since_entry_seconds=900.0,
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )

        exit_decision = policy.evaluate()

        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_evaluate_time_stop_profitable(self):
        """Test time stop DOES trigger on profitable position (>= 0.5R) at max hold."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=10.0,  # >= 0.5R (profitable)
            time_since_entry_seconds=900.0,
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )

        exit_decision = policy.evaluate()

        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.TIME_STOP
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.TIME_STOP
    
    def test_evaluate_time_stop_before_max_hold(self):
        """Test time stop does NOT trigger before max hold (even if losing)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=45,
            unrealized_pnl_cents=-50,
            r_multiple=-5.0,
            time_since_entry_seconds=500.0,  # Before max hold
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )
        
        exit_decision = policy.evaluate()
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None

    def test_evaluate_time_stop_at_threshold(self):
        """Test time stop at exactly 0.5R threshold (should exit at max hold)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=55,
            unrealized_pnl_cents=50,
            r_multiple=0.5,  # Exactly at threshold
            time_since_entry_seconds=900.0,
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )

        exit_decision = policy.evaluate()

        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.TIME_STOP
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.TIME_STOP
    
    def test_evaluate_edge_decay(self):
        """Test edge decay triggers exit."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,  # 3% minimum edge
        )

        exit_decision = policy.evaluate(current_edge_pct=0.02)  # Below threshold
        
        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.EDGE_DECAY
        assert exit_decision.source_layer == ExitSourceLayer.POLICY_LAYER
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.EDGE_DECAY
    
    def test_evaluate_edge_decay_sufficient(self):
        """Test edge decay does NOT trigger when edge sufficient."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
        )
        
        exit_decision = policy.evaluate(current_edge_pct=0.05)  # Above threshold
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    
    def test_get_effective_max_hold_volatility_adjustment(self):
        """Test volatility-adjusted max hold time."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # HIGH volatility: 50% of base
        policy_high = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            max_hold_seconds=900.0,
            volatility_regime="HIGH",
        )
        
        assert policy_high.get_effective_max_hold() == 450.0  # 900 * 0.5
        
        # LOW volatility: 100% of base
        policy_low = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            max_hold_seconds=900.0,
            volatility_regime="LOW",
        )
        
        assert policy_low.get_effective_max_hold() == 900.0  # 900 * 1.0
        
        # No volatility regime: use base
        policy_none = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            max_hold_seconds=900.0,
            volatility_regime=None,
        )
        
        assert policy_none.get_effective_max_hold() == 900.0


class TestExitPolicyRisk:
    """Test RISK exit reason (kill switch precedence)."""
    
    def test_risk_kill_switch_trumps_all(self):
        """Test risk kill switch beats all other exit signals."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=10.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=True,  # Kill switch ON
        )
        
        # Even with stale data, candle reversal, etc., RISK wins
        policy.evaluate(
            current_edge_pct=0.01,  # Would trigger EDGE_DECAY
            candles=[{'open': 50, 'high': 60, 'low': 40, 'close': 45, 'timestamp': 0}],
            md_age_ms=10000,
            max_age_ms=5000,  # Would trigger STALE_DATA
        )
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.RISK
    
    def test_risk_kill_switch_no_other_signals(self):
        """Test risk kill switch exits even with no other signals."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=True,
        )
        
        exit_decision = policy.evaluate()
        
        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.RISK
        assert exit_decision.source_layer == ExitSourceLayer.POLICY_LAYER
        assert policy.action == ExitAction.EXIT_MARKET  # Backward compatibility
        assert policy.reason == ExitReason.RISK
    
    def test_risk_kill_switch_off_hold(self):
        """Test with kill switch off and neutral inputs, should hold."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate()
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None


class TestExitPolicyStaleData:
    """Test STALE_DATA exit reason (market data staleness)."""
    
    def test_stale_no_data(self):
        """Test positive stale MD age treated as no data, must exit."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )

        exit_decision = policy.evaluate(md_age_ms=10000, max_age_ms=5000)

        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.STALE_DATA
        assert exit_decision.source_layer == ExitSourceLayer.POLICY_LAYER
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.STALE_DATA
    
    def test_stale_age_exceeds_max(self):
        """Test md_age_ms > max_age_ms triggers stale exit."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate(md_age_ms=10000, max_age_ms=5000)
        
        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.STALE_DATA
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.STALE_DATA
    
    def test_stale_age_equals_max(self):
        """Test md_age_ms == max_age_ms does NOT exit (strict > check)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate(md_age_ms=5000, max_age_ms=5000)
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_stale_age_within_limit(self):
        """Test md_age_ms < max_age_ms does not exit."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate(md_age_ms=3000, max_age_ms=5000)
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_stale_no_params_provided(self):
        """Test stale check skipped when params not provided."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        # No md_age_ms/max_age_ms provided
        exit_decision = policy.evaluate()
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None


class TestExitPolicyCandleReversal:
    """Test CANDLE_REVERSAL exit reason with mocked detector."""
    
    @patch('merid.position_management.candle_patterns.get_candle_pattern_detector')
    def test_candle_reversal_exit(self, mock_get_detector):
        """Test candle reversal triggers exit when detector says so."""
        # Setup mock detector
        mock_detector = Mock()
        mock_detector.should_exit_on_reversal.return_value = (True, 'bearish_engulfing')
        mock_get_detector.return_value = mock_detector
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        candles = [
            {'open': 50, 'high': 60, 'low': 40, 'close': 45, 'timestamp': 0},
            {'open': 45, 'high': 50, 'low': 30, 'close': 35, 'timestamp': 60},
        ]
        
        exit_decision = policy.evaluate(candles=candles)
        
        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.CANDLE_REVERSAL
        assert exit_decision.source_layer == ExitSourceLayer.POLICY_LAYER
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.CANDLE_REVERSAL
        mock_detector.should_exit_on_reversal.assert_called_once()
    
    @patch('merid.position_management.candle_patterns.get_candle_pattern_detector')
    def test_candle_reversal_no_exit(self, mock_get_detector):
        """Test candle reversal does not exit when detector says no."""
        mock_detector = Mock()
        mock_detector.should_exit_on_reversal.return_value = (False, None)
        mock_get_detector.return_value = mock_detector
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        candles = [
            {'open': 50, 'high': 60, 'low': 40, 'close': 55, 'timestamp': 0},
            {'open': 55, 'high': 65, 'low': 50, 'close': 60, 'timestamp': 60},
        ]
        
        exit_decision = policy.evaluate(candles=candles)
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_candle_reversal_no_candles(self):
        """Test candle reversal skipped when candles=None."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate(candles=None)
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_candle_reversal_insufficient_candles(self):
        """Test candle reversal skipped when len(candles) < 2."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate(candles=[{'open': 50, 'high': 60, 'low': 40, 'close': 55, 'timestamp': 0}])
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    @patch('merid.position_management.candle_patterns.get_candle_pattern_detector')
    def test_candle_reversal_exception_handling(self, mock_get_detector):
        """Test candle reversal handles detector exceptions gracefully."""
        mock_get_detector.side_effect = ImportError("candle_patterns module not found")
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        candles = [
            {'open': 50, 'high': 60, 'low': 40, 'close': 45, 'timestamp': 0},
            {'open': 45, 'high': 50, 'low': 30, 'close': 35, 'timestamp': 60},
        ]
        
        exit_decision = policy.evaluate(candles=candles)
        
        # Should not exit on exception
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None


class TestExitPolicyAdaptiveTiming:
    """Test ADAPTIVE_TIMING exit reason with mocked timing module."""
    
    @patch('merid.position_management.adaptive_exit_timing.get_adaptive_exit_timing')
    def test_adaptive_timing_exit(self, mock_get_timing):
        """Test adaptive timing triggers exit when module says so."""
        mock_timing = Mock()
        mock_timing.should_exit_early.return_value = True
        mock_get_timing.return_value = mock_timing
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate()
        
        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.ADAPTIVE_TIMING
        assert exit_decision.source_layer == ExitSourceLayer.POLICY_LAYER
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.ADAPTIVE_TIMING
        mock_timing.should_exit_early.assert_called_once()
    
    @patch('merid.position_management.adaptive_exit_timing.get_adaptive_exit_timing')
    def test_adaptive_timing_no_exit(self, mock_get_timing):
        """Test adaptive timing does not exit when module says no."""
        mock_timing = Mock()
        mock_timing.should_exit_early.return_value = False
        mock_get_timing.return_value = mock_timing
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate()
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    @patch('merid.position_management.adaptive_exit_timing.get_adaptive_exit_timing')
    def test_adaptive_timing_exception_handling(self, mock_get_timing):
        """Test adaptive timing handles exceptions gracefully."""
        mock_get_timing.side_effect = ImportError("adaptive_exit_timing module not found")
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate()
        
        # Should not exit on exception
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None


class TestExitPolicyEdgeDecay:
    """Test EDGE_DECAY exit reason (edge threshold logic)."""
    
    def test_edge_decay_below_threshold(self):
        """Test edge decay triggers when edge below threshold."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
            risk_kill_switch=False,
        )

        exit_decision = policy.evaluate(current_edge_pct=0.02)  # Below threshold
        
        assert exit_decision is not None
        assert exit_decision.reason == ExitReason.EDGE_DECAY
        assert exit_decision.source_layer == ExitSourceLayer.POLICY_LAYER
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.EDGE_DECAY
    
    def test_edge_decay_at_threshold(self):
        """Test edge decay does NOT trigger at exact threshold."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate(current_edge_pct=0.03)  # At threshold
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_edge_decay_above_threshold(self):
        """Test edge decay does NOT trigger when edge sufficient."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate(current_edge_pct=0.05)  # Above threshold
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_edge_decay_no_edge_provided(self):
        """Test edge decay skipped when current_edge_pct not provided."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
            risk_kill_switch=False,
        )
        
        exit_decision = policy.evaluate()  # No current_edge_pct provided
        
        assert exit_decision is None
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None


class TestExitPolicyPrecedence:
    """Test exit policy precedence (combined signal stacking)."""
    
    @patch('merid.position_management.candle_patterns.get_candle_pattern_detector')
    @patch('merid.position_management.adaptive_exit_timing.get_adaptive_exit_timing')
    def test_risk_beats_all(self, mock_get_timing, mock_get_detector):
        """Test RISK beats all other signals."""
        mock_detector = Mock()
        mock_detector.should_exit_on_reversal.return_value = (True, 'pattern')
        mock_get_detector.return_value = mock_detector
        
        mock_timing = Mock()
        mock_timing.should_exit_early.return_value = True
        mock_get_timing.return_value = mock_timing
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=True,  # RISK ON
        )
        
        policy.evaluate(
            current_edge_pct=0.01,
            candles=[{'open': 50, 'high': 60, 'low': 40, 'close': 45, 'timestamp': 0},
                     {'open': 45, 'high': 50, 'low': 30, 'close': 35, 'timestamp': 60}],
            md_age_ms=10000,
            max_age_ms=5000,
        )
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.RISK
    
    def test_stale_data_beats_candle_reversal(self):
        """Test STALE_DATA beats CANDLE_REVERSAL."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        # STALE_DATA should win even with candle reversal signal
        policy.evaluate(
            candles=[{'open': 50, 'high': 60, 'low': 40, 'close': 45, 'timestamp': 0},
                     {'open': 45, 'high': 50, 'low': 30, 'close': 35, 'timestamp': 60}],
            md_age_ms=10000,
            max_age_ms=5000,
        )
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.STALE_DATA
    
    @patch('merid.position_management.candle_patterns.get_candle_pattern_detector')
    @patch('merid.position_management.adaptive_exit_timing.get_adaptive_exit_timing')
    def test_candle_reversal_beats_adaptive_timing(self, mock_get_timing, mock_get_detector):
        """Test CANDLE_REVERSAL beats ADAPTIVE_TIMING."""
        mock_detector = Mock()
        mock_detector.should_exit_on_reversal.return_value = (True, 'pattern')
        mock_get_detector.return_value = mock_detector
        
        mock_timing = Mock()
        mock_timing.should_exit_early.return_value = True
        mock_get_timing.return_value = mock_timing
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=False,
        )
        
        policy.evaluate(
            candles=[{'open': 50, 'high': 60, 'low': 40, 'close': 45, 'timestamp': 0},
                     {'open': 45, 'high': 50, 'low': 30, 'close': 35, 'timestamp': 60}],
        )
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.CANDLE_REVERSAL
    
    @patch('merid.position_management.adaptive_exit_timing.get_adaptive_exit_timing')
    def test_adaptive_timing_beats_time_stop(self, mock_get_timing):
        """Test ADAPTIVE_TIMING beats TIME_STOP."""
        mock_timing = Mock()
        mock_timing.should_exit_early.return_value = True
        mock_get_timing.return_value = mock_timing
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=45,
            unrealized_pnl_cents=-50,
            r_multiple=-5.0,  # Would trigger TIME_STOP
            time_since_entry_seconds=900.0,  # At max hold
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
            risk_kill_switch=False,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.ADAPTIVE_TIMING
    
    def test_time_stop_beats_edge_decay(self):
        """Test TIME_STOP beats EDGE_DECAY."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=1.0,  # >= 0.5R so TIME_STOP can trigger at max hold
            time_since_entry_seconds=900.0,
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
            min_edge_threshold=0.03,
            risk_kill_switch=False,
        )

        policy.evaluate(current_edge_pct=0.01)  # Would trigger EDGE_DECAY

        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.TIME_STOP
    
    def test_only_edge_decay_active(self):
        """Test EDGE_DECAY fires when only signal active."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,  # Before time stop
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
            risk_kill_switch=False,
        )

        policy.evaluate(current_edge_pct=0.01)
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.EDGE_DECAY


class TestExitPolicyResolver:
    """Test ExitPolicyResolver singleton and resolution."""
    
    def test_get_exit_policy_resolver_singleton(self):
        """Test singleton pattern."""
        resolver1 = get_exit_policy_resolver()
        resolver2 = get_exit_policy_resolver()
        
        assert resolver1 is resolver2
    
    def test_resolve_basic(self):
        """Test basic policy resolution."""
        resolver = ExitPolicyResolver(max_hold_seconds=900.0)
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        
        assert policy.position is position
        assert policy.current_price_cents == 50
        assert policy.max_hold_seconds == 900.0
        assert policy.action == ExitAction.HOLD
    
    def test_set_risk_kill_switch(self):
        """Test risk kill switch setting."""
        resolver = ExitPolicyResolver()
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # Kill switch off
        policy1 = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        assert policy1.action == ExitAction.HOLD
        
        # Enable kill switch
        resolver.set_risk_kill_switch(True)
        
        policy2 = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        assert policy2.action == ExitAction.EXIT_MARKET
        assert policy2.reason == ExitReason.RISK
        
        # Disable kill switch
        resolver.set_risk_kill_switch(False)
        
        policy3 = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        assert policy3.action == ExitAction.HOLD


class TestExitPolicyModelInvalidationProvenance:
    """Test the 2026-08-12 provenance gate for model-invalidation loss exits."""

    def _trusted_position(self) -> Position:
        return Position(
            market_id="KXBTC15M-TRUSTED",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=53,
            current_price_cents=45,
            unrealized_pnl_cents=-8,
            entry_signal_id="signal-1",
            entry_model_probability=0.55,
            entry_market_probability=0.50,
            entry_edge=0.05,
            entry_fill_id="fill-1",
            entry_order_id="order-1",
            client_order_id="client-1",
            fill_source="ws",
            risk_params_state=RiskParamsState.ORIGINAL_PERSISTED,
            risk_params_schema_version=2,
            entry_book_capture_quality="AT_FILL",
            edge_decay_confirmations=2,
        )

    def test_model_invalidation_blocked_without_provenance(self):
        """A position with no provenance must not realize a model-invalidation loss."""
        position = Position(
            market_id="KXBTC15M-UNTRUSTED",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            current_price_cents=50,
            unrealized_pnl_cents=-20,
            edge_decay_confirmations=2,
        )

        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=-20,
            r_multiple=-1.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
            min_edge_decay_confirmations=2,
            risk_kill_switch=False,
        )

        decision = policy.evaluate(current_edge_pct=0.01)
        assert decision is None, f"Expected no exit for untrusted provenance, got {decision}"

    def test_model_invalidation_allowed_with_trusted_provenance(self):
        """A fully-provenanced position may realize a model-invalidation loss."""
        position = self._trusted_position()

        policy = ExitPolicy(
            position=position,
            current_price_cents=45,
            unrealized_pnl_cents=-8,
            r_multiple=-1.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
            min_edge_decay_confirmations=2,
            risk_kill_switch=False,
        )

        decision = policy.evaluate(current_edge_pct=0.01)
        assert decision is not None, "Expected model-invalidation loss exit"
        assert decision.reason == ExitReason.MODEL_INVALIDATION_LOSS_EXIT
