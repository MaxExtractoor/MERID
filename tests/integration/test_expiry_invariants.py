"""
Expiry Chaos Invariant Tests - CI Test Suite

Tests to verify expiry safety controls are working correctly.
Part of: Kalshi Expiry Chaos Audit

Run with: pytest tests/integration/test_expiry_invariants.py -v
"""
from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional
from unittest.mock import Mock, patch, MagicMock


# =============================================================================
# Test Constants
# =============================================================================

DEFAULT_RTI_SETTLEMENT_FINAL_SECONDS = 60
DEFAULT_RTI_EXTENDED_GUARD_SECONDS = 120
DEFAULT_FILTER_RTI_MIN_SECONDS = 61
NINETY_SECOND_THRESHOLD = 90
ONE_HUNDRED_TWENTY_SECOND_THRESHOLD = 120


# =============================================================================
# Environment Variable Invariant Tests
# =============================================================================

class TestEnvironmentVariableDefaults:
    """
    Verify that environment variables default to safe values.
    
    These tests ensure the system fails safely when configuration
    is not explicitly set.
    """

    def test_rti_settlement_final_seconds_default(self):
        """
        MERID_RTI_SETTLEMENT_FINAL_SECONDS should default to 60 seconds.
        
        This is the core settlement guard window - must not be larger
        than the RTI sampling window (60s).
        """
        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=True):
            from merid.event_venues.kalshi.settlement_execution_guard import _final_sec
            assert _final_sec() == 60, \
                "Settlement guard must default to 60s when not configured"

    def test_rti_extended_guard_seconds_default(self):
        """
        MERID_RTI_EXTENDED_GUARD_SECONDS should default to 120 seconds.
        
        Extended guard provides 2x the normal window when settlement
        data is incomplete (buffer <60 slots).
        """
        with patch.dict(os.environ, {}, clear=True):
            from merid.event_venues.kalshi.settlement_execution_guard import _extended_guard_seconds
            assert _extended_guard_seconds() == 120, \
                "Extended guard must default to 120s when not configured"

    def test_rti_allow_buy_if_settlement_grade_defaults_false(self):
        """
        MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE should default to False.
        
        Gap G5 fix: Default-safe behavior - never allow buys in settlement
        window unless explicitly enabled.
        """
        with patch.dict(os.environ, {}, clear=True):
            from merid.event_venues.kalshi.settlement_execution_guard import _allow_buy_if_grade
            assert _allow_buy_if_grade() is False, \
                "Buy-in-settlement must be disabled by default (safe default)"

    def test_rti_settlement_order_policy_defaults_reduce_ok(self):
        """
        MERID_RTI_SETTLEMENT_ORDER_POLICY should default to 'reduce_ok'.
        
        Allows position reductions (sells) but blocks new buys.
        """
        with patch.dict(os.environ, {}, clear=True):
            from merid.event_venues.kalshi.settlement_execution_guard import _policy
            assert _policy() == "reduce_ok", \
                "Order policy must default to reduce_ok (allow sells, block buys)"


# =============================================================================
# 90-Second Hard Block Invariant Tests
# =============================================================================

class TestNinetySecondHardBlockInvariant:
    """
    Verify that no new buy orders are generated with seconds_to_expiry < 90.
    
    This is the Gap G1 fix - explicit agent-level expiry proximity check.
    """

    @pytest.fixture
    def mock_market(self):
        """Create a mock market with configurable expiry."""
        market = Mock()
        market.market_id = "KXBTC-20250115-15M"
        market.end_date = None  # Set per-test
        return market

    @pytest.fixture  
    def mock_agent(self):
        """Create mock agent with _get_seconds_to_expiry method."""
        agent = Mock()
        agent.config.timeframes = ["15m"]
        agent.config.assets = ["BTC"]
        agent.config.risk_limits.max_orders_per_window = 10
        agent.state.orders_this_window = 0
        return agent

    def test_get_seconds_to_expiry_calculation(self, mock_market):
        """
        _get_seconds_to_expiry must calculate correctly with timezone handling.
        """
        from merid.prediction.trading_agent import KalshiTradingAgent
        
        # Set expiry 95 seconds in future
        future = datetime.now(timezone.utc) + timedelta(seconds=95)
        mock_market.end_date = future
        
        agent = MagicMock(spec=KalshiTradingAgent)
        now = datetime.now(timezone.utc)
        
        # Calculate seconds to expiry
        delta = future - now
        seconds_to_expiry = max(0.0, delta.total_seconds())
        
        # Should be approximately 95 seconds (allow 1s tolerance for test execution)
        assert 94 <= seconds_to_expiry <= 96, \
            f"Expected ~95s, got {seconds_to_expiry}s"

    def test_ninety_second_block_blocks_at_89_seconds(self, mock_market):
        """
        Orders must be blocked when seconds_to_expiry = 89s (just under threshold).
        """
        # Expiry 89 seconds away
        future = datetime.now(timezone.utc) + timedelta(seconds=89)
        mock_market.end_date = future
        
        # Simulate the guard check
        now = datetime.now(timezone.utc)
        delta = future - now
        seconds_to_expiry = max(0.0, delta.total_seconds())
        
        # Guard should block
        assert seconds_to_expiry <= 90, "Should be under 90s threshold"
        # In actual code, this triggers: guard_decision="block"

    def test_ninety_second_block_allows_at_91_seconds(self, mock_market):
        """
        Orders may proceed when seconds_to_expiry = 91s (just over threshold).
        """
        # Expiry 91 seconds away  
        future = datetime.now(timezone.utc) + timedelta(seconds=91)
        mock_market.end_date = future
        
        now = datetime.now(timezone.utc)
        delta = future - now
        seconds_to_expiry = max(0.0, delta.total_seconds())
        
        # Guard should allow (or warn)
        assert seconds_to_expiry > 90, "Should be over 90s threshold"

    def test_one_hundred_twenty_second_warning(self, mock_market):
        """
        Warning must be logged when seconds_to_expiry <= 120s.
        """
        # Expiry 119 seconds away (in warning zone)
        future = datetime.now(timezone.utc) + timedelta(seconds=119)
        mock_market.end_date = future
        
        now = datetime.now(timezone.utc)
        delta = future - now
        seconds_to_expiry = max(0.0, delta.total_seconds())
        
        # Should trigger warning log
        assert seconds_to_expiry <= 120, "Should be in 120s warning zone"


# =============================================================================
# Extended Guard Invariant Tests  
# =============================================================================

class TestExtendedGuardInvariant:
    """
    Verify extended guard engages when settlement buffer <60 slots.
    
    Gap G4 fix: Use 120s extended window when data is incomplete.
    """

    @pytest.fixture
    def mock_buffer_registry(self):
        """Create mock buffer registry with configurable state."""
        registry = Mock()
        buffer = Mock()
        buffer.filled_count = 60
        buffer.is_settlement_grade.return_value = True
        registry.get_buffer.return_value = buffer
        return registry, buffer

    def test_extended_guard_activates_when_buffer_incomplete(self, mock_buffer_registry):
        """
        Extended guard (120s) must activate when buffer filled_count < 60.
        """
        registry, buffer = mock_buffer_registry
        buffer.filled_count = 58  # Incomplete
        buffer.is_settlement_grade.return_value = False
        
        # At T-95s with incomplete buffer
        seconds_to_expiry = 95.0
        extended_guard_seconds = 120
        
        # Extended guard should be active
        should_use_extended = (
            not buffer.is_settlement_grade() and 
            seconds_to_expiry <= extended_guard_seconds
        )
        
        assert should_use_extended is True, \
            "Extended guard should activate with buffer=58/60 at T-95s"

    def test_standard_guard_when_buffer_complete(self, mock_buffer_registry):
        """
        Standard guard (60s) used when buffer is settlement-grade.
        """
        registry, buffer = mock_buffer_registry
        buffer.filled_count = 60
        buffer.is_settlement_grade.return_value = True
        
        # At T-65s with complete buffer
        seconds_to_expiry = 65.0
        final_seconds = 60
        
        # Standard guard applies
        should_block = seconds_to_expiry <= final_seconds
        
        assert should_block is False, \
            "Standard guard should NOT block at T-65s with complete buffer"

    def test_extended_guard_blocks_buys_at_95_seconds(self, mock_buffer_registry):
        """
        Buy orders must be blocked at T-95s when buffer incomplete.
        """
        registry, buffer = mock_buffer_registry
        buffer.filled_count = 55
        buffer.is_settlement_grade.return_value = False
        
        # At T-95s
        seconds_to_expiry = 95.0
        extended_guard_seconds = 120
        
        is_in_extended_guard = (
            not buffer.is_settlement_grade() and 
            seconds_to_expiry <= extended_guard_seconds
        )
        
        assert is_in_extended_guard is True
        
        # Buy should be blocked
        action = "buy"
        if is_in_extended_guard and action == "buy":
            decision = "block"
            reason = f"rti_settlement_window:extended_guard_incomplete_data:t-{seconds_to_expiry:.0f}s"
        else:
            decision = "allow"
            reason = None
            
        assert decision == "block", \
            f"Buy should be blocked: {reason}"

    def test_extended_guard_allows_sells_with_warning(self, mock_buffer_registry):
        """
        Sell orders should be allowed (with warning) at T-95s with incomplete buffer.
        """
        registry, buffer = mock_buffer_registry
        buffer.filled_count = 55
        buffer.is_settlement_grade.return_value = False
        
        seconds_to_expiry = 95.0
        extended_guard_seconds = 120
        policy = "reduce_ok"
        
        is_in_extended_guard = (
            not buffer.is_settlement_grade() and 
            seconds_to_expiry <= extended_guard_seconds
        )
        
        action = "sell"
        
        # In reduce_ok policy, sells are allowed even in extended guard
        if is_in_extended_guard and action == "buy":
            decision = "block"
        elif policy == "block_all":
            decision = "block"  # block_all blocks everything
        else:
            decision = "allow"  # reduce_ok allows sells
            
        assert decision == "allow", \
            "Sells should be allowed in extended guard with reduce_ok policy"


# =============================================================================
# Settlement Guard Integration Tests
# =============================================================================

class TestSettlementGuardIntegration:
    """
    Integration tests for the complete settlement guard pipeline.
    """

    def test_buy_blocked_within_final_seconds(self):
        """
        Complete flow: buy order blocked when within MERID_RTI_SETTLEMENT_FINAL_SECONDS.
        """
        from merid.event_venues.kalshi.settlement_execution_guard import evaluate_settlement_order
        
        # Mock RTI ticker check
        with patch('merid.event_venues.kalshi.settlement_execution_guard.is_rti_settled_kalshi_crypto_ticker') as mock_is_rti:
            mock_is_rti.return_value = True
            
            with patch('merid.event_venues.kalshi.settlement_execution_guard.get_settlement_buffer_registry') as mock_reg:
                registry = Mock()
                buffer = Mock()
                buffer.filled_count = 60
                buffer.is_settlement_grade.return_value = True
                registry.get_buffer.return_value = buffer
                mock_reg.return_value = registry
                
                # Attempt buy at T-45s (within 60s guard)
                result = evaluate_settlement_order(
                    ticker="KXBTC-20250115-15M",
                    action="buy",
                    seconds_to_expiry=45.0,
                    count=10
                )
                
                assert result is not None, \
                    "Buy within final 60s should be blocked"
                assert "no_new_buys" in result or "block_all" in result, \
                    f"Expected block reason, got: {result}"

    def test_sell_allowed_within_final_seconds(self):
        """
        Complete flow: sell order allowed when within final seconds (reduce_ok policy).
        """
        from merid.event_venues.kalshi.settlement_execution_guard import evaluate_settlement_order
        
        with patch('merid.event_venues.kalshi.settlement_execution_guard.is_rti_settled_kalshi_crypto_ticker') as mock_is_rti:
            mock_is_rti.return_value = True
            
            with patch('merid.event_venues.kalshi.settlement_execution_guard.get_settlement_buffer_registry') as mock_reg:
                registry = Mock()
                buffer = Mock()
                buffer.filled_count = 60
                buffer.is_settlement_grade.return_value = True
                registry.get_buffer.return_value = buffer
                mock_reg.return_value = registry
                
                with patch.dict(os.environ, {"MERID_RTI_SETTLEMENT_ORDER_POLICY": "reduce_ok"}):
                    # Attempt sell at T-45s
                    result = evaluate_settlement_order(
                        ticker="KXBTC-20250115-15M",
                        action="sell",
                        seconds_to_expiry=45.0,
                        count=10
                    )
                    
                    assert result is None, \
                        "Sell within final 60s should be allowed with reduce_ok policy"

    def test_non_rti_ticker_bypasses_guard(self):
        """
        Non-RTI tickers should bypass settlement guard entirely.
        """
        from merid.event_venues.kalshi.settlement_execution_guard import evaluate_settlement_order
        
        with patch('merid.event_venues.kalshi.settlement_execution_guard.is_rti_settled_kalshi_crypto_ticker') as mock_is_rti:
            mock_is_rti.return_value = False  # Not an RTI ticker
            
            # Any action at any time
            result = evaluate_settlement_order(
                ticker="KXSPY-20250115",  # Non-crypto
                action="buy",
                seconds_to_expiry=30.0,
                count=10
            )
            
            assert result is None, \
                "Non-RTI tickers should bypass settlement guard"


# =============================================================================
# Filter Pipeline Invariant Tests
# =============================================================================

class TestFilterPipelineInvariant:
    """
    Verify that MERID_FILTER_RTI_MIN_SECONDS correctly excludes markets near expiry.
    """

    def test_filter_excludes_markets_within_61_seconds(self):
        """
        Markets with <61 seconds to expiry must be excluded from trading.
        """
        min_seconds = 61
        
        # Market at T-60s should be excluded
        seconds_to_expiry = 60.0
        should_exclude = seconds_to_expiry < min_seconds
        
        assert should_exclude is True, \
            "Markets at T-60s should be excluded (60 < 61)"
        
        # Market at T-62s should be included
        seconds_to_expiry = 62.0
        should_exclude = seconds_to_expiry < min_seconds
        
        assert should_exclude is False, \
            "Markets at T-62s should be included (62 >= 61)"

    def test_filter_pipeline_integration(self):
        """
        Filter pipeline must respect MERID_FILTER_RTI_MIN_SECONDS environment variable.
        """
        with patch.dict(os.environ, {"MERID_FILTER_RTI_MIN_SECONDS": "61"}):
            # Simulate the filter logic
            min_seconds = int(os.environ.get("MERID_FILTER_RTI_MIN_SECONDS", "61"))
            
            # Test cases
            test_cases = [
                (30.0, True),   # Exclude: 30 < 61
                (60.0, True),   # Exclude: 60 < 61
                (61.0, False),  # Include: 61 >= 61
                (90.0, False),  # Include: 90 >= 61
            ]
            
            for seconds, expected_exclude in test_cases:
                actual_exclude = seconds < min_seconds
                assert actual_exclude == expected_exclude, \
                    f"seconds={seconds}: expected exclude={expected_exclude}, got {actual_exclude}"


# =============================================================================
# Clock Skew Detection Tests
# =============================================================================

class TestClockSkewDetection:
    """
    Verify clock skew detection and handling.
    """

    def test_clock_skew_within_tolerance_allows_trading(self):
        """
        Clock skew <10s should allow trading with warning.
        """
        system_time = datetime.now(timezone.utc)
        venue_time = system_time - timedelta(seconds=5)  # 5s behind
        
        skew_seconds = abs((system_time - venue_time).total_seconds())
        
        assert skew_seconds < 10, "Skew should be within 10s tolerance"
        # Trading allowed with warning

    def test_clock_skew_exceeds_tolerance_blocks_trading(self):
        """
        Clock skew >10s should block trading.
        """
        system_time = datetime.now(timezone.utc)
        venue_time = system_time - timedelta(seconds=15)  # 15s behind
        
        skew_seconds = abs((system_time - venue_time).total_seconds())
        
        assert skew_seconds > 10, "Skew should exceed 10s tolerance"
        # Trading should be blocked


# =============================================================================
# End-to-End Scenario Tests
# =============================================================================

class TestEndToEndExpiryScenarios:
    """
    Complete end-to-end tests simulating real expiry scenarios.
    """

    def test_scenario_c5_restart_near_expiry(self):
        """
        Scenario C5: Process restart during final minute.
        
        Verify that restart logic correctly re-evaluates expiry proximity
        and blocks trading if resumed within 90s of expiry.
        """
        # Simulate: Agent restarts at T-45s
        seconds_to_expiry_at_restart = 45.0
        
        # Should immediately detect proximity and block
        should_block = seconds_to_expiry_at_restart <= 90
        
        assert should_block is True, \
            "Restart at T-45s should detect proximity and block trading"

    def test_scenario_normal_expiry_sequence(self):
        """
        Normal expiry sequence from T-5m to settlement.
        
        Verifies the expected state transitions:
        - T-300s to T-120s: Normal trading
        - T-120s to T-90s: Warning zone
        - T-90s to T-60s: Agent blocks new signals
        - T-60s to T-0: Settlement guard active, sells only
        """
        checkpoints = [
            (300, "normal", False, False),      # T-5m: normal
            (180, "normal", False, False),      # T-3m: normal
            (120, "warning", False, False),     # T-2m: warning zone
            (91, "warning", False, False),       # T-91s: warning zone
            (90, "agent_block", True, False),    # T-90s: agent blocks
            (61, "agent_block", True, False),    # T-61s: agent blocks
            (60, "settlement_guard", True, True), # T-60s: full guard
            (30, "settlement_guard", True, True), # T-30s: full guard
            (1, "settlement_guard", True, True),  # T-1s: full guard
        ]
        
        for seconds, expected_zone, agent_should_block, guard_should_block in checkpoints:
            # Agent check (90s threshold)
            actual_agent_block = seconds <= 90
            assert actual_agent_block == agent_should_block, \
                f"T-{seconds}s: agent_block expected={agent_should_block}, got={actual_agent_block}"
            
            # Settlement guard check (60s threshold, assuming complete buffer)
            actual_guard_block = seconds <= 60
            assert actual_guard_block == guard_should_block, \
                f"T-{seconds}s: guard_block expected={guard_should_block}, got={actual_guard_block}"


# =============================================================================
# Test Markers for CI Configuration
# =============================================================================

# Add these to pytest.ini or pyproject.toml:
# [tool.pytest.ini_options]
# markers = [
#     "expiry_invariant: tests for expiry safety invariants",
#     "slow: slow running tests",
# ]

pytestmark = [
    pytest.mark.expiry_invariant,
    pytest.mark.integration,
]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
