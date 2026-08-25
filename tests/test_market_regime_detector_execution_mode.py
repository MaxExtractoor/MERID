"""
Tests for market regime detector execution mode selection.

Tests the fix for BUG #1: Execution mode selection backwards for maker-dominated regimes.
- Maker-dominated regimes should default to MAKER execution
- Only use TAKER if spread is extremely tight (< 5%)
"""

import pytest
from merid.event_venues.kalshi.market_regime_detector import (
    MarketRegimeDetector,
    MarketRegime,
    ExecutionMode,
    RegimeMetrics,
    RegimeClassification
)


class TestExecutionModeSelection:
    """Test execution mode selection logic for different regimes."""
    
    def setup_method(self):
        """Initialize detector before each test."""
        self.detector = MarketRegimeDetector()
    
    def test_maker_dominated_defaults_to_maker(self):
        """Test that maker-dominated regime defaults to MAKER execution."""
        metrics = RegimeMetrics(
            spread_cents=5.0,
            bid_depth=1000,
            ask_depth=1000,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        classification = self.detector.classify_regime(
            ticker="KXBTC15M-26AUG011915-15",
            spread_cents=5.0,
            bid_depth=1000,
            ask_depth=1000,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None
        )
        
        # Manually set to maker-dominated for this test
        classification.regime = MarketRegime.MAKER_DOMINATED
        
        # Test execution mode selection
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.MAKER_DOMINATED,
            metrics
        )
        
        # Should default to MAKER for maker-dominated regime
        assert execution_mode == ExecutionMode.MAKER, \
            f"Expected MAKER for maker-dominated regime, got {execution_mode}"
    
    def test_maker_dominated_uses_taker_for_tight_spread(self):
        """Test that maker-dominated uses TAKER only if spread < 5%."""
        metrics = RegimeMetrics(
            spread_cents=2.0,  # 2c spread on 50c mid = 4% (< 5% threshold)
            bid_depth=1000,
            ask_depth=1000,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.MAKER_DOMINATED,
            metrics
        )
        
        # Should use TAKER for extremely tight spreads (< 5%)
        assert execution_mode == ExecutionMode.TAKER, \
            f"Expected TAKER for tight spread (<5%), got {execution_mode}"
    
    def test_maker_dominated_uses_maker_for_normal_spread(self):
        """Test that maker-dominated uses MAKER for normal spreads (>= 5%)."""
        metrics = RegimeMetrics(
            spread_cents=5.0,  # 5c spread on 50c mid = 10% (>= 5% threshold)
            bid_depth=1000,
            ask_depth=1000,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.MAKER_DOMINATED,
            metrics
        )
        
        # Should use MAKER for normal spreads
        assert execution_mode == ExecutionMode.MAKER, \
            f"Expected MAKER for normal spread (>=5%), got {execution_mode}"
    
    def test_taker_dominated_uses_maker(self):
        """Test that taker-dominated regime uses MAKER execution."""
        metrics = RegimeMetrics(
            spread_cents=10.0,
            bid_depth=100,
            ask_depth=1000,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.TAKER_DOMINATED,
            metrics
        )
        
        # Should use MAKER for taker-dominated (provide liquidity)
        assert execution_mode == ExecutionMode.MAKER, \
            f"Expected MAKER for taker-dominated regime, got {execution_mode}"
    
    def test_neutral_uses_adaptive_routing(self):
        """Test that neutral regime uses adaptive routing based on spread."""
        # Test with very wide spread (> 30%)
        metrics_wide = RegimeMetrics(
            spread_cents=20.0,  # 20c spread on 50c mid = 40% (> 30%)
            bid_depth=500,
            ask_depth=500,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.NEUTRAL,
            metrics_wide
        )
        
        assert execution_mode == ExecutionMode.MAKER, \
            f"Expected MAKER for wide spread (>30%), got {execution_mode}"
        
        # Test with moderate spread (10-30%)
        metrics_moderate = RegimeMetrics(
            spread_cents=10.0,  # 10c spread on 50c mid = 20% (10-30%)
            bid_depth=500,
            ask_depth=500,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.NEUTRAL,
            metrics_moderate
        )
        
        assert execution_mode == ExecutionMode.STAGED_IOC, \
            f"Expected STAGED_IOC for moderate spread (10-30%), got {execution_mode}"
        
        # Test with tight spread (< 10%)
        metrics_tight = RegimeMetrics(
            spread_cents=3.0,  # 3c spread on 50c mid = 6% (< 10%)
            bid_depth=500,
            ask_depth=500,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.NEUTRAL,
            metrics_tight
        )
        
        assert execution_mode == ExecutionMode.TAKER, \
            f"Expected TAKER for tight spread (<10%), got {execution_mode}"
    
    def test_extreme_spread_forces_maker(self):
        """Test that extreme spreads (> 100%) force MAKER regardless of regime."""
        metrics = RegimeMetrics(
            spread_cents=60.0,  # 60c spread on 50c mid = 120% (> 100%)
            bid_depth=500,
            ask_depth=500,
            trade_frequency=10.0,
            refresh_rate=5.0,
            mid_price=50.0
        )
        
        # Test with neutral regime
        execution_mode = self.detector._select_execution_mode(
            MarketRegime.NEUTRAL,
            metrics
        )
        
        assert execution_mode == ExecutionMode.MAKER, \
            f"Expected MAKER for extreme spread (>100%), got {execution_mode}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
