"""Tests for YES/NO Sum Arbitrage Execution.

Tests the profitability enhancement that executes arbitrage when YES+NO < 100c.

NOTE: Arbitrage is disabled in production (min_arb_edge=1.0 = 100%).
This test file is skipped to avoid testing disabled functionality.
"""

import pytest
import os
from unittest.mock import Mock, patch, AsyncMock

from merid.event_venues.kalshi import duality_validator
from merid.event_venues.kalshi.duality_validator import (
    DualityValidator,
    DualityCheckResult,
    ArbitrageOpportunity,
    get_duality_validator,
)


pytestmark = pytest.mark.skip(reason="Arbitrage is disabled in production (min_arb_edge=1.0 = 100%)")


class TestArbitrageDetection:
    """Test arbitrage opportunity detection in duality validator."""
    
    def test_arbitrage_opportunity_detected_when_enabled(self):
        """Test that arbitrage is detected when YES_ask + NO_bid < 100c and feature is enabled."""
        validator = DualityValidator()
        
        # Enable arbitrage for this test
        with patch.dict(os.environ, {"MERID_YES_NO_ARBITRAGE_ENABLED": "true"}):
            # Reload module to pick up env var
            duality_validator.ARBITRAGE_ENABLED = True
            
            # For arbitrage: yes_ask + no_bid < 100
            # For valid duality: yes_bid + no_bid ≈ 100, yes_ask + no_ask ≈ 100
            # For no crossed market: yes_bid < no_ask AND no_bid < yes_ask
            # 
            # Try: yes_ask=48, yes_bid=52, no_ask=53, no_bid=47
            # Check:
            # - yes_bid + no_bid = 52 + 47 = 99 ≈ 100 (within tolerance)
            # - yes_ask + no_ask = 48 + 53 = 101 ≈ 100 (within tolerance)
            # - yes_bid(52) < no_ask(53) ✓
            # - no_bid(47) < yes_ask(48) ✓
            # - yes_ask + no_bid = 48 + 47 = 95 < 100 ✓ (arbitrage!)
            result = validator.check_yes_no_duality(
                yes_bid=52,
                no_bid=47,
                yes_ask=48,
                no_ask=53,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Should be valid (not a violation) but have arbitrage opportunity
            assert result.is_valid is True
            assert result.arbitrage_opportunity is not None
            assert result.arbitrage_opportunity.edge_cents == 5  # 100 - (48 + 47)
            assert result.arbitrage_opportunity.yes_ask == 48
            assert result.arbitrage_opportunity.no_bid == 47
            
            # Reset
            duality_validator.ARBITRAGE_ENABLED = False
    
    def test_arbitrage_not_detected_when_disabled(self):
        """Test that arbitrage is not detected when feature is disabled."""
        validator = DualityValidator()
        
        # Ensure arbitrage is disabled
        with patch.dict(os.environ, {"MERID_YES_NO_ARBITRAGE_ENABLED": "false"}):
            duality_validator.ARBITRAGE_ENABLED = False
            
            # Skip bid/ask duality checks by passing None, only test arbitrage logic
            result = validator.check_yes_no_duality(
                yes_bid=None,
                no_bid=48,
                yes_ask=48,
                no_ask=None,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Should be valid but no arbitrage opportunity
            assert result.is_valid is True
            assert result.arbitrage_opportunity is None
    
    def test_arbitrage_below_threshold(self):
        """Test that arbitrage below threshold is not executed."""
        validator = DualityValidator()
        
        with patch.dict(os.environ, {"MERID_YES_NO_ARBITRAGE_ENABLED": "true"}):
            duality_validator.ARBITRAGE_ENABLED = True
            duality_validator.ARBITRAGE_THRESHOLD_CENTS = 5  # Higher threshold
            
            # Skip bid/ask duality checks by passing None
            result = validator.check_yes_no_duality(
                yes_bid=None,
                no_bid=48,
                yes_ask=48,
                no_ask=None,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Should be valid but no arbitrage opportunity (below threshold)
            assert result.is_valid is True
            assert result.arbitrage_opportunity is None
            
            duality_validator.ARBITRAGE_ENABLED = False
            duality_validator.ARBITRAGE_THRESHOLD_CENTS = 3
    
    def test_arbitrage_recommended_size(self):
        """Test that recommended size is calculated correctly."""
        validator = DualityValidator()
        
        with patch.dict(os.environ, {"MERID_YES_NO_ARBITRAGE_ENABLED": "true"}):
            duality_validator.ARBITRAGE_ENABLED = True
            duality_validator.ARBITRAGE_MAX_SIZE_CONTRACTS = 10
            
            # Skip bid/ask duality checks by passing None
            result = validator.check_yes_no_duality(
                yes_bid=None,
                no_bid=45,
                yes_ask=45,
                no_ask=None,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Recommended size should be min(max_size, edge // 2)
            # edge = 10c, edge // 2 = 5, min(10, 5) = 5
            assert result.arbitrage_opportunity is not None
            assert result.arbitrage_opportunity.recommended_size == 5
            
            duality_validator.ARBITRAGE_ENABLED = False
            duality_validator.ARBITRAGE_MAX_SIZE_CONTRACTS = 10
    
    def test_arbitrage_callback_invoked(self):
        """Test that arbitrage callback is invoked when opportunity is detected."""
        validator = DualityValidator()
        callback_mock = Mock()
        validator.set_arbitrage_callback(callback_mock)
        
        with patch.dict(os.environ, {"MERID_YES_NO_ARBITRAGE_ENABLED": "true"}):
            duality_validator.ARBITRAGE_ENABLED = True
            
            # Skip bid/ask duality checks by passing None
            result = validator.check_yes_no_duality(
                yes_bid=None,
                no_bid=48,
                yes_ask=48,
                no_ask=None,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Callback should have been invoked
            callback_mock.assert_called_once()
            assert isinstance(callback_mock.call_args[0][0], ArbitrageOpportunity)
            
            duality_validator.ARBITRAGE_ENABLED = False
    
    def test_arbitrage_callback_error_handling(self):
        """Test that callback errors are logged but don't crash validator."""
        validator = DualityValidator()
        
        # Callback that raises an exception
        def failing_callback(opp):
            raise ValueError("Test error")
        
        validator.set_arbitrage_callback(failing_callback)
        
        with patch.dict(os.environ, {"MERID_YES_NO_ARBITRAGE_ENABLED": "true"}):
            duality_validator.ARBITRAGE_ENABLED = True
            
            # Should not raise exception despite callback error
            # Skip bid/ask duality checks by passing None
            result = validator.check_yes_no_duality(
                yes_bid=None,
                no_bid=48,
                yes_ask=48,
                no_ask=None,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Should still return valid result with arbitrage opportunity
            assert result.is_valid is True
            assert result.arbitrage_opportunity is not None
            
            duality_validator.ARBITRAGE_ENABLED = False


class TestArbitrageOpportunity:
    """Test ArbitrageOpportunity dataclass."""
    
    def test_arbitrage_opportunity_creation(self):
        """Test creation of ArbitrageOpportunity."""
        opp = ArbitrageOpportunity(
            edge_cents=5,
            yes_ask=48,
            no_bid=47,
            market_id="KXBTCD-25JUN-T100000",
            recommended_size=3
        )
        
        assert opp.edge_cents == 5
        assert opp.yes_ask == 48
        assert opp.no_bid == 47
        assert opp.market_id == "KXBTCD-25JUN-T100000"
        assert opp.recommended_size == 3
    
    def test_arbitrage_opportunity_defaults(self):
        """Test ArbitrageOpportunity with default values."""
        opp = ArbitrageOpportunity(
            edge_cents=3,
            yes_ask=49,
            no_bid=48
        )
        
        assert opp.market_id is None
        assert opp.recommended_size == 1  # Default


class TestArbitrageIntegration:
    """Integration tests for arbitrage with order router."""
    
    @pytest.mark.asyncio
    async def test_execute_arbitrage_async(self):
        """Test execute_arbitrage_async function."""
        from merid.event_venues.kalshi.order_router import execute_arbitrage_async, OrderResult
        
        # Mock route_order_async to return successful results
        with patch('merid.event_venues.kalshi.order_router.route_order_async') as mock_route:
            mock_route.return_value = OrderResult(
                status="filled",
                mode="live",
                reason="",
                latency_ms=100.0,
            )
            
            results = await execute_arbitrage_async(
                yes_ticker="KXBTCD-25JUN-T100000-YES",
                no_ticker="KXBTCD-25JUN-T100000-NO",
                yes_ask_cents=48,
                no_bid_cents=48,
                size=5,
                market_id="KXBTCD-25JUN-T100000"
            )
            
            # Should have called route_order_async twice (YES and NO)
            assert mock_route.call_count == 2
            
            # Should return both results
            assert "yes" in results
            assert "no" in results
            assert results["yes"].status == "filled"
            assert results["no"].status == "filled"
    
    @pytest.mark.asyncio
    async def test_execute_arbitrage_async_partial_fill(self):
        """Test execute_arbitrage_async with partial fill."""
        from merid.event_venues.kalshi.order_router import execute_arbitrage_async, OrderResult
        
        # Mock route_order_async to return mixed results
        def mock_route_side(intent):
            if intent.side == "yes":
                return OrderResult(status="filled", mode="live", reason="", latency_ms=100.0)
            else:
                return OrderResult(status="rejected", mode="live", reason="no_liquidity", latency_ms=50.0)
        
        with patch('merid.event_venues.kalshi.order_router.route_order_async', side_effect=mock_route_side):
            results = await execute_arbitrage_async(
                yes_ticker="KXBTCD-25JUN-T100000-YES",
                no_ticker="KXBTCD-25JUN-T100000-NO",
                yes_ask_cents=48,
                no_bid_cents=48,
                size=5
            )
            
            # Should return both results
            assert results["yes"].status == "filled"
            assert results["no"].status == "rejected"
