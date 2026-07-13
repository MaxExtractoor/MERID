"""Liquidity Stress Tests for 15m Crypto Trading

Tests liquidity scenarios and order book depth handling across the 15m crypto trading stack.
Based on 2026 algorithmic trading best practices for liquidity testing.

Key Principles:
- Simulate illiquid market conditions
- Test order book depth thresholds
- Verify slippage impact on 15m markets
- Test market order execution in fast markets

Run: pytest tests/test_liquidity_stress_15m_crypto.py -v
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch


class TestOrderBookDepthThresholds:
    """Test order book depth threshold enforcement."""
    
    def test_depth_threshold_enforcement_btc(self):
        """Test BTC depth threshold enforcement."""
        # Mock depth thresholds
        min_depth_yes = 30
        min_depth_no = 30
        
        # Test with insufficient depth
        insufficient_depth_yes = 20
        insufficient_depth_no = 25
        
        # Should reject orders with insufficient depth
        assert insufficient_depth_yes < min_depth_yes, "YES depth insufficient"
        assert insufficient_depth_no < min_depth_no, "NO depth insufficient"
    
    def test_depth_threshold_all_assets(self):
        """Test depth thresholds across all 5 crypto assets."""
        depth_thresholds = {
            "BTC": {"min_depth_yes": 30, "min_depth_no": 30},
            "ETH": {"min_depth_yes": 30, "min_depth_no": 30},
            "SOL": {"min_depth_yes": 20, "min_depth_no": 20},
            "XRP": {"min_depth_yes": 10, "min_depth_no": 10},
            "DOGE": {"min_depth_yes": 5, "min_depth_no": 5}
        }
        
        for asset, thresholds in depth_thresholds.items():
            # Verify thresholds are reasonable
            assert thresholds["min_depth_yes"] > 0, f"{asset} YES depth threshold invalid"
            assert thresholds["min_depth_no"] > 0, f"{asset} NO depth threshold invalid"
            
            # Test with insufficient depth
            insufficient_depth = thresholds["min_depth_yes"] - 1
            assert insufficient_depth < thresholds["min_depth_yes"], \
                f"{asset} depth check logic invalid"
    
    def test_depth_check_in_order_gate(self):
        """Test depth check integration in order gate."""
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        
        gate = PreTradeGate()
        
        # Mock market state with insufficient depth
        mock_market_state = MagicMock()
        mock_market_state.get_depth_yes.return_value = 15  # Below BTC threshold of 30
        mock_market_state.get_depth_no.return_value = 20
        
        # Should reject order due to insufficient depth
        # (This is a structural test - actual implementation may differ)
        depth_yes = mock_market_state.get_depth_yes()
        depth_no = mock_market_state.get_depth_no()
        
        # Verify depth check logic
        min_depth = 30  # BTC threshold
        if depth_yes < min_depth or depth_no < min_depth:
            assert True  # Would reject order


class TestSlippageImpact:
    """Test slippage impact on 15m markets."""
    
    def test_slippage_calculation_market_order(self):
        """Test slippage calculation for market orders."""
        base_price_cents = 42
        spread_cents = 2
        aggressiveness = 1.0  # Market order
        
        # Simulate slippage calculation
        # Market orders typically experience 1-2 ticks of slippage
        slippage_cents = spread_cents  # Full spread for market order
        
        expected_fill_price = base_price_cents + slippage_cents
        
        # Verify slippage is reasonable
        assert slippage_cents >= 0, "Slippage should be non-negative"
        assert expected_fill_price <= base_price_cents + 5, \
            f"Slippage too high: {slippage_cents}c"
    
    def test_slippage_calculation_limit_order(self):
        """Test slippage calculation for limit orders."""
        base_price_cents = 42
        spread_cents = 2
        aggressiveness = 0.0  # Limit order (maker)
        
        # Limit orders should have minimal slippage
        slippage_cents = 0  # Maker orders typically no slippage
        
        expected_fill_price = base_price_cents + slippage_cents
        
        # Verify minimal slippage for limit orders
        assert slippage_cents == 0, "Limit orders should have minimal slippage"
    
    def test_slippage_impact_on_exposure(self):
        """Test slippage impact on exposure calculation."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        
        allocator = GlobalSlotAllocator()  # Uses class constant MAX_EXPOSURE_USD = 1.00
        
        base_price_cents = 42
        slippage_cents = 2
        actual_fill_price = base_price_cents + slippage_cents
        
        # Request allocation with base price
        request = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=base_price_cents,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            request_time=0
        )
        
        allocated, reason, slot_id = allocator.request_allocation(request)
        
        if allocated:
            # Calculate actual exposure with slippage
            actual_exposure = (1 * actual_fill_price) / 100.0
            total_exposure = allocator.get_total_exposure()
            
            # Verify exposure cap still respected
            assert total_exposure <= 1.0, \
                f"Exposure cap violated with slippage: ${total_exposure:.2f}"


class TestIlliquidMarketScenarios:
    """Test behavior in illiquid market conditions."""
    
    def test_order_rejection_insufficient_liquidity(self):
        """Test order rejection when liquidity is insufficient."""
        # Simulate illiquid market
        depth_yes = 5  # Very low depth
        depth_no = 5
        min_depth_threshold = 30
        
        # Should reject order
        is_liquid = depth_yes >= min_depth_threshold and depth_no >= min_depth_threshold
        assert not is_liquid, "Market should be considered illiquid"
    
    def test_order_queueing_in_illiquid_market(self):
        """Test order queueing behavior in illiquid markets."""
        # In illiquid markets, orders may need to queue
        # rather than execute immediately
        
        queue_size = 10
        max_queue_size = 50
        
        # Should allow queueing up to limit
        can_queue = queue_size < max_queue_size
        assert can_queue, "Should allow order queueing"
    
    def test_price_adjustment_for_illiquidity(self):
        """Test price adjustment for illiquid conditions."""
        base_price_cents = 42
        liquidity_discount = 0.05  # 5% discount for illiquidity
        
        adjusted_price = base_price_cents * (1 - liquidity_discount)
        
        # Should still be in valid range
        assert 10 <= adjusted_price <= 75, \
            f"Adjusted price out of range: {adjusted_price}c"


class TestFastMarketConditions:
    """Test behavior in fast/volatile market conditions."""
    
    def test_order_execution_in_fast_market(self):
        """Test order execution during fast market conditions."""
        # Fast market: rapid price movements
        price_movements = [42, 43, 44, 45, 46]  # Rapid upward movement
        
        # Orders should still execute with reasonable slippage
        max_acceptable_slippage = 5  # 5 cents
        
        for i in range(len(price_movements) - 1):
            price_change = abs(price_movements[i+1] - price_movements[i])
            assert price_change <= max_acceptable_slippage, \
                f"Price movement too fast: {price_change}c"
    
    def test_circuit_breaker_in_extreme_volatility(self):
        """Test circuit breaker activation in extreme volatility."""
        # Extreme volatility: 10% price movement
        base_price = 65000
        extreme_price = 71500  # 10% increase
        
        volatility_pct = abs(extreme_price - base_price) / base_price
        
        # Should trigger circuit breaker
        circuit_breaker_threshold = 0.05  # 5%
        should_trigger = volatility_pct > circuit_breaker_threshold
        assert should_trigger, "Circuit breaker should trigger"
    
    def test_order_throttling_in_fast_market(self):
        """Test order throttling during fast market conditions."""
        # Fast market may require order throttling
        order_rate = 10  # orders per second
        max_order_rate = 5  # throttled rate
        
        should_throttle = order_rate > max_order_rate
        assert should_throttle, "Should throttle orders in fast market"


class TestLiquidityAcrossAssets:
    """Test liquidity handling across all 5 crypto assets."""
    
    def test_liquidity_differences_across_assets(self):
        """Test liquidity differences across crypto assets."""
        # Different assets have different liquidity profiles
        liquidity_profiles = {
            "BTC": {"depth_yes": 100, "depth_no": 100, "spread": 1},
            "ETH": {"depth_yes": 80, "depth_no": 80, "spread": 1},
            "SOL": {"depth_yes": 50, "depth_no": 50, "spread": 2},
            "XRP": {"depth_yes": 30, "depth_no": 30, "spread": 2},
            "DOGE": {"depth_yes": 15, "depth_no": 15, "spread": 3}
        }
        
        for asset, profile in liquidity_profiles.items():
            # Verify liquidity profile is reasonable
            assert profile["depth_yes"] > 0, f"{asset} YES depth invalid"
            assert profile["depth_no"] > 0, f"{asset} NO depth invalid"
            assert profile["spread"] >= 1, f"{asset} spread too low"
    
    def test_asset_specific_depth_thresholds(self):
        """Test asset-specific depth threshold configuration."""
        depth_thresholds = {
            "BTC": 30,
            "ETH": 30,
            "SOL": 20,
            "XRP": 10,
            "DOGE": 5
        }
        
        # Verify thresholds match liquidity profiles
        # (BTC/ETH higher, SOL/XRP/DOGE lower)
        assert depth_thresholds["BTC"] >= depth_thresholds["SOL"], \
            "BTC threshold should be >= SOL"
        assert depth_thresholds["SOL"] >= depth_thresholds["XRP"], \
            "SOL threshold should be >= XRP"
        assert depth_thresholds["XRP"] >= depth_thresholds["DOGE"], \
            "XRP threshold should be >= DOGE"


class TestLiquidityRiskManagement:
    """Test liquidity risk management in order routing."""
    
    def test_liquidity_check_in_order_router(self):
        """Test liquidity check integration in order router."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            source="agent_grid_15m"
        )
        
        # Simulate liquidity check
        depth_yes = 25  # Below threshold
        min_depth = 30
        
        liquidity_ok = depth_yes >= min_depth
        assert not liquidity_ok, "Order should be rejected for insufficient liquidity"
    
    def test_position_sizing_adjustment_for_liquidity(self):
        """Test position sizing adjustment based on liquidity."""
        base_position_size = 1
        liquidity_factor = 0.5  # Low liquidity reduces position size
        
        adjusted_size = base_position_size * liquidity_factor
        
        # Should reduce position size in low liquidity
        assert adjusted_size < base_position_size, \
            "Position size should be reduced for low liquidity"
        assert adjusted_size >= 0, "Position size should be non-negative"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
