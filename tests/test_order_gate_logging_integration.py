"""
Integration tests for order gate logging enhancements.

ENHANCED LOGGING (2026-07-26): Integration tests to verify enhanced logging
works end-to-end through the actual order router and gate components.
"""

import pytest
from unittest.mock import Mock, patch
from merid.event_venues.kalshi.order_gate import PreTradeGate, GateVerdict, OrderStatus
from merid.event_venues.kalshi.order_router import OrderIntent


class TestOrderGateLoggingIntegration:
    """Integration tests for order gate logging with actual components."""
    
    @pytest.fixture
    def gate(self):
        """Create a real PreTradeGate instance for integration testing."""
        return PreTradeGate()
    
    def test_duplicate_order_logging_integration(self, gate):
        """Integration test: verify duplicate order rejection logs full context.
        
        This test uses the actual PreTradeGate.check() method to verify
        that enhanced logging works end-to-end with real components.
        Uses a non-crypto-15m market to avoid exit policy requirements.
        """
        # Use a non-crypto-15m market to avoid exit policy validation
        contract_id = "TEST-MARKET-123"
        
        # First, submit an order to populate the store
        first_verdict = gate.check(
            agent_id="test_agent",
            strategy_group="test_strategy",
            contract_id=contract_id,
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=1234567890.0,
            intent_id="test_intent_1",
        )
        
        # First order should be allowed
        assert first_verdict.allowed
        
        # Now submit the same order again (should be rejected as duplicate)
        with patch('merid.event_venues.kalshi.order_gate.logger') as mock_logger:
            second_verdict = gate.check(
                agent_id="test_agent",
                strategy_group="test_strategy",
                contract_id=contract_id,
                side="yes",
                action="buy",
                target_count=1,
                price_cents=50,
                decision_ts=1234567890.0,
                intent_id="test_intent_1",
            )
            
            # Verify rejection
            assert not second_verdict.allowed
            assert second_verdict.is_duplicate
            
            # Verify logging was called
            mock_logger.warning.assert_called()
            
            # Verify format string contains enhanced context fields
            format_string = mock_logger.warning.call_args[0][0]
            assert "duplicate_order_attempt_blocked" in format_string
            assert "agent=%s" in format_string
            assert "strategy=%s" in format_string
            assert "side=%s" in format_string
            assert "action=%s" in format_string
            assert "count=%d" in format_string
            assert "price=%dc" in format_string
            assert "intent_id=%s" in format_string
    
    def test_gate_metrics_tracking(self, gate):
        """Integration test: verify gate metrics are properly tracked for rejections."""
        # Use a non-crypto-15m market to avoid exit policy validation
        contract_id = "TEST-MARKET-456"
        
        # Submit an order
        first_verdict = gate.check(
            agent_id="test_agent",
            strategy_group="test_strategy",
            contract_id=contract_id,
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=1234567890.0,
            intent_id="test_intent_2",
        )
        
        # Verify check counter incremented
        assert gate._store._metrics.checks == 1
        
        # Submit duplicate
        second_verdict = gate.check(
            agent_id="test_agent",
            strategy_group="test_strategy",
            contract_id=contract_id,
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=1234567890.0,
            intent_id="test_intent_2",
        )
        
        # Verify duplicate rejection metric incremented
        assert gate._store._metrics.blocked_duplicate == 1
        assert gate._store._metrics.checks == 2
    
    def test_exit_policy_logging_integration(self, gate):
        """Integration test: verify exit policy rejection logs full context.
        
        This test uses a crypto 15m market to trigger exit policy validation
        and verify the enhanced logging works for that rejection path.
        """
        with patch('merid.event_venues.kalshi.order_router._is_crypto_15m_market', return_value=True):
            with patch('merid.event_venues.kalshi.order_gate.logger') as mock_logger:
                # Submit order without exit policy metadata (should be rejected)
                verdict = gate.check(
                    agent_id="test_agent",
                    strategy_group="btc_15m",
                    contract_id="KXBTC15M-26JUL211745-45",
                    side="yes",
                    action="buy",
                    target_count=1,
                    price_cents=50,
                    decision_ts=1234567890.0,
                    intent_id="test_intent_3",
                    exit_policy_id=None,  # Missing exit policy
                    window_resolution_id=None,
                    risk_tier=None,
                    max_hold_seconds=None,
                )
                
                # Verify rejection
                assert not verdict.allowed
                assert "exit_policy_metadata_missing" in verdict.reason
                
                # Verify logging was called with enhanced context
                mock_logger.error.assert_called()
                format_string = mock_logger.error.call_args[0][0]
                assert "exit_policy_metadata_missing" in format_string
                assert "agent=%s" in format_string
                assert "strategy=%s" in format_string
                assert "action=%s" in format_string
                assert "count=%d" in format_string
                assert "price=%dc" in format_string
                assert "intent_id=%s" in format_string


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
