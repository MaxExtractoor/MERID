"""
Minimal automated regression suite for 15m crypto path.

Tests exercise the full 15m decision path in a controlled way:
- Test 1: BTC 15m trade passes all guards
- Test 2: DOGE 15m trade blocked by distance
- Test 3: Kill-switch blocks trades

These tests protect the critical 15m pipeline from regressions.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass


@dataclass
class MockMarket:
    market_id: str
    ticker: str
    title: str
    price_cents: int


class Test15mRegression:
    """Regression tests for 15m crypto trading path."""

    def test_btc_15m_trade_passes_all_guards(self):
        """Test: BTC 15m trade with high edge and valid distance passes all guards."""
        from merid.prediction.trading_agent import check_execution_guards, ExecutionGuardResult
        
        # Setup: BTC 15m, high edge, valid distance
        asset = "BTC"
        timeframe = "15m"
        delta_pct = 0.002  # 0.2% - within limits
        z_score = 0.5  # within sigma limits
        edge = 0.06  # 6% edge - above minimum
        
        # Mock log function
        log_calls = []
        def mock_log(msg, *args):
            log_calls.append(msg % args if args else msg)
        
        # Execute guards
        result = check_execution_guards(
            asset=asset,
            timeframe=timeframe,
            delta_pct=delta_pct,
            z_score=z_score,
            edge=edge,
            log_fn=mock_log
        )
        
        # Assert: trade allowed
        assert result.allowed is True, f"Trade should be allowed, got reason: {result.reason}"
        assert result.asset == asset
        assert result.timeframe == timeframe

    def test_doge_15m_trade_blocked_by_distance(self):
        """Test: DOGE 15m trade with excessive distance is blocked."""
        from merid.prediction.trading_agent import check_execution_guards, ExecutionGuardResult
        
        # Setup: DOGE 15m, excessive distance
        asset = "DOGE"
        timeframe = "15m"
        delta_pct = 0.015  # 1.5% - exceeds typical max_distance_pct
        z_score = 2.0  # exceeds sigma limit
        edge = 0.08  # High edge but distance too far
        
        # Mock log function
        log_calls = []
        def mock_log(msg, *args):
            log_calls.append(msg % args if args else msg)
        
        # Execute guards
        result = check_execution_guards(
            asset=asset,
            timeframe=timeframe,
            delta_pct=delta_pct,
            z_score=z_score,
            edge=edge,
            log_fn=mock_log
        )
        
        # Assert: trade blocked by distance
        assert result.allowed is False, "Trade should be blocked due to distance"
        assert result.reason in ["distance_too_far", "distance_too_far_z"], \
            f"Expected distance-related reason, got: {result.reason}"
        assert result.asset == asset
        assert result.timeframe == timeframe
        
        # Assert: log contains distance block message
        assert any("distance" in log.lower() for log in log_calls), \
            "Log should mention distance blocking"

    def test_kill_switch_blocks_trades(self):
        """Test: Kill-switch blocks trades when daily loss exceeded."""
        from merid.risk.kill_switches import risk_controller, KillSwitchReason
        from merid.prediction.trading_agent import check_execution_guards, ExecutionGuardResult
        
        # Setup: Mock risk controller with active kill-switch
        with patch.object(risk_controller, 'can_trade', return_value=False), \
             patch.object(risk_controller, 'get_kill_reason', return_value="daily_loss: -$50.00 exceeds $25.00 limit"):
            
            # Mock log function
            log_calls = []
            def mock_log(msg, *args):
                log_calls.append(msg % args if args else msg)
            
            # Execute guards (should be blocked at Layer 0 before other checks)
            result = check_execution_guards(
                asset="BTC",
                timeframe="15m",
                delta_pct=0.001,
                z_score=0.3,
                edge=0.05,
                log_fn=mock_log
            )
            
            # Assert: trade blocked by kill-switch
            assert result.allowed is False, "Trade should be blocked by kill-switch"
            assert result.reason == "kill_switch", f"Expected kill_switch reason, got: {result.reason}"
            
            # Assert: log mentions kill-switch
            assert any("kill_switch" in log.lower() for log in log_calls), \
                "Log should mention kill-switch"

    def test_edge_too_low_blocks_trade(self):
        """Test: Trade with edge below minimum is blocked."""
        from merid.prediction.trading_agent import check_execution_guards, ExecutionGuardResult
        
        # Setup: BTC 15m, low edge
        asset = "BTC"
        timeframe = "15m"
        delta_pct = 0.001  # Valid distance
        z_score = 0.3  # Valid sigma
        edge = 0.01  # 1% edge - below minimum
        
        # Mock log function
        log_calls = []
        def mock_log(msg, *args):
            log_calls.append(msg % args if args else msg)
        
        # Execute guards
        result = check_execution_guards(
            asset=asset,
            timeframe=timeframe,
            delta_pct=delta_pct,
            z_score=z_score,
            edge=edge,
            log_fn=mock_log
        )
        
        # Assert: trade blocked by edge
        assert result.allowed is False, "Trade should be blocked due to low edge"
        assert result.reason == "edge_too_low", f"Expected edge_too_low reason, got: {result.reason}"
        
        # Assert: log mentions edge blocking
        assert any("edge" in log.lower() for log in log_calls), \
            "Log should mention edge blocking"

    def test_non_15m_timeframe_blocked(self):
        """Test: Non-15m timeframe is blocked for execution."""
        from merid.prediction.trading_agent import check_execution_guards, ExecutionGuardResult
        
        # Setup: BTC 1h timeframe (not 15m)
        asset = "BTC"
        timeframe = "1h"
        delta_pct = 0.001
        z_score = 0.3
        edge = 0.06
        
        # Mock log function
        log_calls = []
        def mock_log(msg, *args):
            log_calls.append(msg % args if args else msg)
        
        # Execute guards
        result = check_execution_guards(
            asset=asset,
            timeframe=timeframe,
            delta_pct=delta_pct,
            z_score=z_score,
            edge=edge,
            log_fn=mock_log
        )
        
        # Assert: trade blocked due to non-15m timeframe
        assert result.allowed is False, "Trade should be blocked for non-15m timeframe"
        assert result.reason == "non_15m_timeframe", \
            f"Expected non_15m_timeframe reason, got: {result.reason}"
        
        # Assert: log mentions timeframe restriction
        assert any("timeframe" in log.lower() or "15m" in log.lower() for log in log_calls), \
            "Log should mention timeframe restriction"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
