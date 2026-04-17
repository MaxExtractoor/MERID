"""Tests for dynamic allocation and edge calibration systems.

This test suite verifies:
1. Dynamic allocation calculator produces risk-parity or Kelly-optimal allocations
2. Dynamic edge calibrator computes edges based on volatility
3. Settings module returns dynamic caps instead of hardcoded values
4. KalshiRiskConfig computes category limits dynamically
"""

import os
import sys
import pytest
from decimal import Decimal

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDynamicAllocationCalculator:
    """Test the DynamicAllocationCalculator."""

    def test_risk_parity_weights_sum_to_one(self):
        """Risk parity weights should sum to 1.0."""
        from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
        
        calculator = get_dynamic_allocation_calculator()
        allocations = calculator.compute_allocations(50000, strategy="risk_parity")
        
        total = sum(allocations.values())
        assert 0.99 <= float(total) <= 1.01, f"Weights sum to {total}, expected ~1.0"
    
    def test_asset_caps_scale_with_portfolio(self):
        """Asset caps should scale proportionally with portfolio size."""
        from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
        
        calculator = get_dynamic_allocation_calculator()
        
        # Get caps for two different portfolio sizes
        caps_50k = calculator.get_all_caps(50000)
        caps_100k = calculator.get_all_caps(100000)
        
        # Each asset cap should roughly double
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            ratio = caps_100k[asset] / caps_50k[asset]
            assert 1.8 <= ratio <= 2.2, f"{asset} cap ratio {ratio} should be ~2.0"
    
    def test_btc_has_higher_cap_than_doge(self):
        """BTC (lower vol, higher liquidity) should have higher allocation than DOGE."""
        from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
        
        calculator = get_dynamic_allocation_calculator()
        allocations = calculator.compute_allocations(50000, strategy="risk_parity")
        
        assert allocations["BTC"] > allocations["DOGE"], \
            f"BTC allocation {allocations['BTC']} should be > DOGE {allocations['DOGE']}"
    
    def test_max_single_asset_cap_enforced(self):
        """No single asset should exceed max_single_asset_pct."""
        from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
        
        calculator = get_dynamic_allocation_calculator()
        calculator.config.max_single_asset_pct = Decimal("0.40")
        
        allocations = calculator.compute_allocations(50000)
        
        for asset, alloc in allocations.items():
            assert float(alloc) <= 0.40, f"{asset} allocation {alloc} exceeds 40% max"
    
    def test_timeframe_distribution_sums_to_allocation(self):
        """Timeframe distribution for an asset should sum to its total allocation."""
        from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
        
        calculator = get_dynamic_allocation_calculator()
        
        btc_allocation = calculator.compute_allocations(50000)["BTC"]
        tf_dist = calculator.get_timeframe_distribution("BTC", float(btc_allocation) * 50000)
        
        total_tf = sum(tf_dist.values())
        expected = float(btc_allocation) * 50000
        
        assert 0.95 * expected <= total_tf <= 1.05 * expected, \
            f"Timeframe sum {total_tf} should be ~{expected}"


class TestDynamicEdgeCalibrator:
    """Test the DynamicEdgeCalibrator."""

    def test_edge_computed_for_all_assets(self):
        """Edge calibrator should return values for all crypto assets."""
        from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
        
        calibrator = get_dynamic_edge_calibrator()
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            edge = calibrator.compute_edge_threshold(asset, "15m")
            assert edge > 0, f"Edge for {asset} should be positive"
            assert edge <= Decimal("0.08"), f"Edge for {asset} should not exceed ceiling"
    
    def test_timeframe_scaling_applied(self):
        """Longer timeframes should have higher edge requirements."""
        from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
        
        calibrator = get_dynamic_edge_calibrator()
        
        edge_15m = calibrator.compute_edge_threshold("BTC", "15m")
        edge_daily = calibrator.compute_edge_threshold("BTC", "daily")
        edge_annual = calibrator.compute_edge_threshold("BTC", "annual")
        
        assert edge_15m < edge_daily < edge_annual, \
            f"Edge scaling failed: 15m={edge_15m}, daily={edge_daily}, annual={edge_annual}"
    
    def test_asset_risk_multiplier_applied(self):
        """Higher risk assets (DOGE) should have higher edge than lower risk (BTC)."""
        from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
        
        calibrator = get_dynamic_edge_calibrator()
        
        btc_edge = calibrator.compute_edge_threshold("BTC", "15m")
        doge_edge = calibrator.compute_edge_threshold("DOGE", "15m")
        
        assert doge_edge > btc_edge, \
            f"DOGE edge {doge_edge} should be > BTC edge {btc_edge}"
    
    def test_edge_clamped_to_bounds(self):
        """Edge should never go below floor or above ceiling."""
        from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
        
        calibrator = get_dynamic_edge_calibrator()
        calibrator.config.min_edge_floor = Decimal("0.005")
        calibrator.config.max_edge_ceiling = Decimal("0.08")
        
        # Get edges for all assets/timeframes
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            for tf in ["15m", "1h", "daily", "weekly", "monthly", "annual"]:
                edge = calibrator.compute_edge_threshold(asset, tf)
                assert Decimal("0.005") <= edge <= Decimal("0.08"), \
                    f"Edge {edge} for {asset}/{tf} outside bounds"
    
    def test_all_thresholds_returns_complete_grid(self):
        """get_all_thresholds should return 5 assets × 6 timeframes."""
        from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
        
        calibrator = get_dynamic_edge_calibrator()
        all_edges = calibrator.get_all_thresholds()
        
        assert len(all_edges) == 5, "Should have 5 assets"
        for asset in all_edges:
            assert len(all_edges[asset]) == 6, f"{asset} should have 6 timeframes"


class TestSettingsDynamicCaps:
    """Test that settings module returns dynamic caps."""
    
    def test_get_dynamic_asset_caps_returns_caps(self):
        """Settings should return dynamic asset caps."""
        from merid.settings import settings
        
        caps = settings.get_dynamic_asset_caps()
        
        assert "BTC" in caps
        assert "ETH" in caps
        assert caps["BTC"].max_daily_notional_usd > 0
        assert caps["BTC"].max_single_trade_usd > 0
    
    def test_dynamic_caps_scale_with_bankroll(self):
        """Caps should scale when bankroll changes."""
        from merid.settings import settings
        
        # Get baseline caps
        original_bankroll = settings.KALSHI_PORTFOLIO_BANKROLL_CENTS
        
        try:
            # Set $50k bankroll
            settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = 5_000_000
            caps_50k = settings.get_dynamic_asset_caps()
            btc_50k = caps_50k["BTC"].max_daily_notional_usd
            
            # Clear cache
            settings._asset_caps_cache = None
            settings._asset_caps_cache_time = 0
            
            # Set $100k bankroll
            settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = 10_000_000
            caps_100k = settings.get_dynamic_asset_caps()
            btc_100k = caps_100k["BTC"].max_daily_notional_usd
            
            # 100k should be ~2x 50k
            ratio = btc_100k / btc_50k
            assert 1.8 <= ratio <= 2.2, f"Cap ratio {ratio} should be ~2.0"
        finally:
            # Restore original
            settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = original_bankroll
            settings._asset_caps_cache = None
            settings._asset_caps_cache_time = 0


class TestKalshiRiskDynamicLimits:
    """Test that KalshiRiskConfig computes dynamic category limits."""
    
    def test_dynamic_category_limits_computed(self):
        """Category limits should be computed dynamically."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        
        config = KalshiRiskConfig()
        
        assert "crypto" in config.category_limits
        assert "economics" in config.category_limits
        assert config.category_limits["crypto"].max_notional_usd > 0
    
    def test_crypto_is_largest_category(self):
        """Crypto should have the highest notional limit."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        
        config = KalshiRiskConfig()
        
        crypto_limit = config.category_limits["crypto"].max_notional_usd
        
        for category, limit in config.category_limits.items():
            if category != "crypto":
                assert crypto_limit >= limit.max_notional_usd, \
                    f"Crypto {crypto_limit} should be >= {category} {limit.max_notional_usd}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
