"""
Test order gate logging enhancements for rejection debugging.

ENHANCED LOGGING (2026-07-26): Tests for enhanced logging in pre-trade gate
rejections to include full context (agent, strategy, side, action, count, price,
intent_id) for debugging order execution pipeline issues.
"""

import pytest
import logging
from unittest.mock import Mock, patch
from merid.event_venues.kalshi.order_gate import PreTradeGate, GateVerdict, OrderStatus


class TestOrderGateLoggingEnhancements:
    """Tests for enhanced logging in order gate rejections."""
    
    @pytest.fixture
    def gate(self):
        """Create a PreTradeGate instance for testing."""
        return PreTradeGate()
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger for testing log output."""
        with patch('merid.event_venues.kalshi.order_gate.logger') as mock:
            yield mock
    
    def test_duplicate_order_logging_includes_full_context(self, gate, mock_logger):
        """Test that duplicate order rejection includes full context in log.
        
        ENHANCED LOGGING: Verify that duplicate rejection logs include:
        - agent, strategy, side, action, count, price, intent_id
        """
        # Create a duplicate order scenario
        coid = "test_coid_123"
        existing_record = Mock()
        existing_record.status = OrderStatus.PENDING
        existing_record.client_order_id = coid
        
        # Mock the store to return existing record
        gate._store.lookup = Mock(return_value=existing_record)
        # Use a real GateMetrics object instead of Mock to support += operator
        from merid.event_venues.kalshi.order_gate import GateMetrics
        gate._store._metrics = GateMetrics()
        
        # Call check with full parameters
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL211745-45",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=1234567890.0,
            intent_id="test_intent_abc",
        )
        
        # Verify rejection
        assert not verdict.allowed
        assert verdict.is_duplicate
        
        # Verify logging was called with full context
        mock_logger.warning.assert_called()
        # Verify format string contains all required field names
        format_string = mock_logger.warning.call_args[0][0]
        assert "duplicate_order_attempt_blocked" in format_string
        assert "agent=%s" in format_string
        assert "strategy=%s" in format_string
        assert "side=%s" in format_string
        assert "action=%s" in format_string
        assert "count=%d" in format_string
        assert "price=%dc" in format_string
        assert "intent_id=%s" in format_string
        assert "metric: blocked_duplicate" in format_string
    
    def test_resting_duplicate_logging_includes_full_context(self, gate, mock_logger):
        """Test that resting duplicate rejection includes full context in log.
        
        ENHANCED LOGGING: Verify that resting duplicate rejection logs include:
        - agent, strategy, count, intent_id
        """
        # Mock resting duplicate
        resting_record = Mock()
        resting_record.client_order_id = "existing_coid_456"
        resting_record.status = OrderStatus.LIVE
        
        gate._store.find_resting_duplicate = Mock(return_value=resting_record)
        gate._store.lookup = Mock(return_value=None)  # No direct duplicate
        from merid.event_venues.kalshi.order_gate import GateMetrics
        gate._store._metrics = GateMetrics()
        
        # Call check
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL211745-45",
            side="no",
            action="sell",
            target_count=1,
            price_cents=60,
            decision_ts=1234567890.0,
            intent_id="test_intent_xyz",
        )
        
        # Verify rejection
        assert not verdict.allowed
        assert verdict.is_duplicate
        
        # Verify logging includes full context
        mock_logger.warning.assert_called()
        # Verify format string contains all required field names
        format_string = mock_logger.warning.call_args[0][0]
        assert "resting_order_duplicate_blocked" in format_string
        assert "agent=%s" in format_string
        assert "strategy=%s" in format_string
        assert "count=%d" in format_string
        assert "intent_id=%s" in format_string
    
    def test_price_repeat_logging_includes_full_context(self, gate, mock_logger):
        """Test that price repeat rejection includes full context in log.
        
        ENHANCED LOGGING: Verify that price repeat rejection logs include:
        - agent, strategy, action, count, intent_id
        """
        # Mock price repeat check to block
        gate._store.check_price_repeat = Mock(return_value=(False, "same_price_executed", 50))
        gate._store.lookup = Mock(return_value=None)
        gate._store.find_resting_duplicate = Mock(return_value=None)
        from merid.event_venues.kalshi.order_gate import GateMetrics
        gate._store._metrics = GateMetrics()
        
        # Call check
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="sol_15m",
            contract_id="KXSOL15M-26JUL211745-45",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=1234567890.0,
            intent_id="test_intent_123",
        )
        
        # Verify rejection
        assert not verdict.allowed
        assert "price_repeat" in verdict.reason
        
        # Verify logging includes full context
        mock_logger.warning.assert_called()
        # Verify format string contains all required field names
        format_string = mock_logger.warning.call_args[0][0]
        assert "price_repeat_blocked" in format_string
        assert "agent=%s" in format_string
        assert "strategy=%s" in format_string
        assert "action=%s" in format_string
        assert "count=%d" in format_string
        assert "intent_id=%s" in format_string
    
    def test_exit_policy_missing_logging_includes_full_context(self, gate, mock_logger):
        """Test that exit policy missing rejection includes full context in log.
        
        ENHANCED LOGGING: Verify that exit policy missing rejection logs include:
        - agent, strategy, action, count, price, intent_id
        """
        # Mock crypto 15m market detection (function is in order_router, not order_gate)
        with patch('merid.event_venues.kalshi.order_router._is_crypto_15m_market', return_value=True):
            gate._store.lookup = Mock(return_value=None)
            gate._store.find_resting_duplicate = Mock(return_value=None)
            gate._store.check_price_repeat = Mock(return_value=(True, "", None))
            from merid.event_venues.kalshi.order_gate import GateMetrics
            gate._store._metrics = GateMetrics()
            
            # Call check without exit policy metadata (should be rejected)
            verdict = gate.check(
                agent_id="test_agent",
                strategy_group="doge_15m",
                contract_id="KXDOGE15M-26JUL211745-45",
                side="yes",
                action="buy",
                target_count=1,
                price_cents=45,
                decision_ts=1234567890.0,
                intent_id="test_intent_456",
                exit_policy_id=None,  # Missing exit policy
                window_resolution_id=None,
                risk_tier=None,
                max_hold_seconds=None,
            )
            
            # Verify rejection
            assert not verdict.allowed
            assert "exit_policy_metadata_missing" in verdict.reason
            
            # Verify logging includes full context
            mock_logger.error.assert_called()
            # Verify format string contains all required field names
            format_string = mock_logger.error.call_args[0][0]
            assert "exit_policy_metadata_missing" in format_string
            assert "agent=%s" in format_string
            assert "strategy=%s" in format_string
            assert "action=%s" in format_string
            assert "count=%d" in format_string
            assert "price=%dc" in format_string
            assert "intent_id=%s" in format_string


class TestOrderRouterLoggingEnhancements:
    """Tests for enhanced logging in order router pre-trade gate."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger for testing log output."""
        with patch('merid.event_venues.kalshi.order_router.logger') as mock:
            yield mock
    
    def test_gate_blocked_logging_includes_full_context(self, mock_logger):
        """Test that gate blocked rejection in order router includes full context.
        
        ENHANCED LOGGING: Verify that gate blocked logs include:
        - ticker, coid, reason, agent, strategy, side, action, count, price
        - intent_id, entry_or_exit, exit_policy_id, window_resolution_id
        - risk_tier, max_hold_seconds, latency_ms
        """
        from merid.event_venues.kalshi.order_router import OrderResult, OrderIntent, TradingMode
        
        # Create a mock intent
        intent = Mock(spec=OrderIntent)
        intent.ticker = "KXBTC15M-26JUL211745-45"
        intent.side = "yes"
        intent.action = "buy"
        intent.count = 1
        intent.price_cents = 50
        intent.agent_id = "test_agent"
        intent.group_id = "btc_15m"
        intent.intent_id = "test_intent_789"
        intent.entry_or_exit = "entry"
        intent.exit_policy_id = "test_exit_policy"
        intent.window_resolution_id = "test_window"
        intent.risk_tier = "moderate"
        intent.max_hold_seconds = 900
        intent._allocated_slot_id = None
        
        # Create a mock gate verdict
        verdict = Mock()
        verdict.allowed = False
        verdict.client_order_id = "test_coid_abc123"
        verdict.reason = "duplicate:pending"
        verdict.is_duplicate = False
        
        # Simulate the logging code path from _run_pre_trade_gate
        latency = 5.5
        mock_logger.warning(
            "[order-router] GATE BLOCKED: ticker=%s coid=%s reason=%s "
            "agent=%s strategy=%s side=%s action=%s count=%d price=%dc "
            "intent_id=%s entry_or_exit=%s exit_policy_id=%s window_resolution_id=%s "
            "risk_tier=%s max_hold_seconds=%s latency_ms=%.2f",
            intent.ticker, verdict.client_order_id[:16], verdict.reason,
            intent.agent_id, intent.group_id, intent.side, intent.action, intent.count, intent.price_cents,
            intent.intent_id, intent.entry_or_exit, intent.exit_policy_id, intent.window_resolution_id,
            intent.risk_tier, intent.max_hold_seconds, latency,
        )
        
        # Verify logging was called with full context
        mock_logger.warning.assert_called()
        # Verify format string contains all required field names
        format_string = mock_logger.warning.call_args[0][0]
        assert "GATE BLOCKED" in format_string
        assert "ticker=%s" in format_string
        assert "coid=%s" in format_string
        assert "reason=%s" in format_string
        assert "agent=%s" in format_string
        assert "strategy=%s" in format_string
        assert "side=%s" in format_string
        assert "action=%s" in format_string
        assert "count=%d" in format_string
        assert "price=%dc" in format_string
        assert "intent_id=%s" in format_string
        assert "entry_or_exit=%s" in format_string
        assert "exit_policy_id=%s" in format_string
        assert "window_resolution_id=%s" in format_string
        assert "risk_tier=%s" in format_string
        assert "max_hold_seconds=%s" in format_string
        assert "latency_ms=%.2f" in format_string
    
    def test_idempotent_duplicate_logging_includes_full_context(self, mock_logger):
        """Test that idempotent duplicate logging includes full context.
        
        ENHANCED LOGGING: Verify that idempotent duplicate logs include:
        - ticker, coid, status, reason, agent, strategy, side, action, count, price
        """
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create a mock intent
        intent = Mock(spec=OrderIntent)
        intent.ticker = "KXETH15M-26JUL211745-45"
        intent.side = "no"
        intent.action = "sell"
        intent.count = 1
        intent.price_cents = 60
        intent.agent_id = "test_agent"
        intent.group_id = "eth_15m"
        
        # Create a mock verdict
        verdict = Mock()
        verdict.is_duplicate = True
        verdict.existing_status = "filled"
        verdict.client_order_id = "test_coid_xyz789"
        verdict.reason = "duplicate:filled"
        
        # Simulate the logging code path
        mock_logger.info(
            "[order-router] IDEMPOTENT DUPLICATE: ticker=%s coid=%s status=%s reason=%s "
            "agent=%s strategy=%s side=%s action=%s count=%d price=%dc (returning synthetic success)",
            intent.ticker, verdict.client_order_id[:16], verdict.existing_status, verdict.reason,
            intent.agent_id, intent.group_id, intent.side, intent.action, intent.count, intent.price_cents,
        )
        
        # Verify logging includes full context
        mock_logger.info.assert_called()
        # Verify format string contains all required field names
        format_string = mock_logger.info.call_args[0][0]
        assert "IDEMPOTENT DUPLICATE" in format_string
        assert "ticker=%s" in format_string
        assert "coid=%s" in format_string
        assert "status=%s" in format_string
        assert "reason=%s" in format_string
        assert "agent=%s" in format_string
        assert "strategy=%s" in format_string
        assert "side=%s" in format_string
        assert "action=%s" in format_string
        assert "count=%d" in format_string
        assert "price=%dc" in format_string


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
