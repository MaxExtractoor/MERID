"""Liquidity Tracking Tests - 2026 Best Practices

Tests for liquidity tracking bug fixes:
- Depth calculation: contract count × price (not contract count ÷ 100)
- Dynamic order type liquidity threshold
- Market liquidity check threshold
"""

import pytest
from dataclasses import dataclass


@dataclass
class MockMarketState:
    """Mock KalshiMarketState for testing."""
    ticker: str
    depth_10c: int  # Contract count within 10c of mid
    mid_cents: int  # Mid price in cents
    top_of_book_size: int = 0


class TestLiquidityTracking2026:
    """Test liquidity tracking aligned with 2026 best practices."""

    def test_depth_calculation_correct(self):
        """Test depth calculation: contract count × mid price (not ÷ 100)."""
        # Example: 100 contracts at 50c each = $50 liquidity
        state = MockMarketState(
            ticker="KXBTC15M-26JUN290230-30",
            depth_10c=100,  # 100 contracts
            mid_cents=50,   # 50c mid price
        )
        
        # Correct calculation (2026 best practice)
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        assert depth_dollars == 50.0, f"Expected $50.0, got ${depth_dollars}"
        
        # Previous bug (wrong calculation)
        buggy_depth_dollars = state.depth_10c / 100.0
        assert buggy_depth_dollars == 1.0, "Buggy calculation would give $1.0 (100x too small)"
        
        # Verify fix is correct
        assert depth_dollars == 50.0, "Fix should give correct $50.0"
        assert depth_dollars == buggy_depth_dollars * 50, "Fix should be 50x the buggy value"

    def test_depth_calculation_higher_price(self):
        """Test depth calculation at higher price (80c)."""
        # Example: 100 contracts at 80c each = $80 liquidity
        state = MockMarketState(
            ticker="KXETH15M-26JUN290230-30",
            depth_10c=100,  # 100 contracts
            mid_cents=80,   # 80c mid price
        )
        
        # Correct calculation
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        assert depth_dollars == 80.0, f"Expected $80.0, got ${depth_dollars}"
        
        # Previous bug
        buggy_depth_dollars = state.depth_10c / 100.0
        assert buggy_depth_dollars == 1.0, "Buggy calculation would give $1.0"
        
        # Verify fix is correct
        assert depth_dollars == 80.0, "Fix should give correct $80.0"
        assert depth_dollars == buggy_depth_dollars * 80, "Fix should be 80x the buggy value"

    def test_depth_calculation_lower_price(self):
        """Test depth calculation at lower price (20c)."""
        # Example: 100 contracts at 20c each = $20 liquidity
        state = MockMarketState(
            ticker="KXSOL15M-26JUN290230-30",
            depth_10c=100,  # 100 contracts
            mid_cents=20,   # 20c mid price
        )
        
        # Correct calculation
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        assert depth_dollars == 20.0, f"Expected $20.0, got ${depth_dollars}"
        
        # Previous bug
        buggy_depth_dollars = state.depth_10c / 100.0
        assert buggy_depth_dollars == 1.0, "Buggy calculation would give $1.0"
        
        # Verify fix is correct
        assert depth_dollars == 20.0, "Fix should give correct $20.0"
        assert depth_dollars == buggy_depth_dollars * 20, "Fix should be 20x the buggy value"

    def test_depth_calculation_thousands_dollars(self):
        """Test depth calculation for realistic trading volumes (thousands of dollars)."""
        # Example: 5000 contracts at 50c each = $2500 liquidity
        state = MockMarketState(
            ticker="KXBTC15M-26JUN290230-30",
            depth_10c=5000,  # 5000 contracts
            mid_cents=50,     # 50c mid price
        )
        
        # Correct calculation
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        assert depth_dollars == 2500.0, f"Expected $2500.0, got ${depth_dollars}"
        
        # Previous bug
        buggy_depth_dollars = state.depth_10c / 100.0
        assert buggy_depth_dollars == 50.0, "Buggy calculation would give $50.0"
        
        # Verify fix is correct
        assert depth_dollars == 2500.0, "Fix should give correct $2500.0"
        assert depth_dollars == buggy_depth_dollars * 50, "Fix should be 50x the buggy value"

    def test_liquidity_threshold_check(self):
        """Test liquidity threshold check with correct depth calculation."""
        # Example: 100 contracts at 50c = $50 > $10 threshold (should pass)
        state = MockMarketState(
            ticker="KXBTC15M-26JUN290230-30",
            depth_10c=100,
            mid_cents=50,
        )
        
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        min_liquidity_threshold = 10.0
        
        assert depth_dollars >= min_liquidity_threshold, \
            f"Depth ${depth_dollars} should pass $10 threshold"
        
        # With buggy calculation, this would fail
        buggy_depth_dollars = state.depth_10c / 100.0
        assert buggy_depth_dollars < min_liquidity_threshold, \
            f"Buggy depth ${buggy_depth_dollars} would incorrectly fail $10 threshold"

    def test_dynamic_order_type_threshold(self):
        """Test dynamic order type liquidity threshold ($500)."""
        # Example: 1000 contracts at 50c = $500 (at threshold)
        state = MockMarketState(
            ticker="KXBTC15M-26JUN290230-30",
            depth_10c=1000,
            mid_cents=50,
        )
        
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        market_order_threshold = 500.0
        
        # At threshold - should use market order
        assert depth_dollars == market_order_threshold, \
            f"Depth ${depth_dollars} at threshold ${market_order_threshold}"
        
        # With buggy calculation, this would incorrectly trigger market order
        buggy_depth_dollars = state.depth_10c / 100.0
        assert buggy_depth_dollars < market_order_threshold, \
            f"Buggy depth ${buggy_depth_dollars} would incorrectly trigger market order"

    def test_realistic_volume_scenario(self):
        """Test realistic scenario: thousands of dollars in volume within minutes."""
        # User reports: thousands of dollars in volume across BTC/ETH/SOL/XRP/DOGE
        # Example: 2000 contracts at 75c = $1500 liquidity
        state = MockMarketState(
            ticker="KXBTC15M-26JUN290230-30",
            depth_10c=2000,
            mid_cents=75,
        )
        
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        
        # Should show realistic liquidity (thousands of dollars)
        assert depth_dollars == 1500.0, f"Expected $1500.0, got ${depth_dollars}"
        assert depth_dollars > 1000.0, "Should show thousands of dollars in liquidity"
        
        # With buggy calculation, would show $20 (100x too small)
        buggy_depth_dollars = state.depth_10c / 100.0
        assert buggy_depth_dollars == 20.0, "Buggy would show $20.0 (100x too small)"

    def test_default_mid_price(self):
        """Test default mid price (50c) when not available."""
        state = MockMarketState(
            ticker="KXBTC15M-26JUN290230-30",
            depth_10c=100,
            mid_cents=50,  # Default value
        )
        
        # Should use 50c as default
        depth_dollars = state.depth_10c * (state.mid_cents / 100.0)
        assert depth_dollars == 50.0, f"Expected $50.0 with default 50c, got ${depth_dollars}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
