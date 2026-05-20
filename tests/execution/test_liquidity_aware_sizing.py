"""Tests for Liquidity-Aware Sizing."""

import pytest
from execution.liquidity_aware_sizing import (
    LiquidityAwareSizer,
    get_liquidity_sizer,
    LiquidityLevel,
    LiquidityConfig,
    LiquidityAnalysis
)


class TestLiquidityAwareSizer:
    """Test suite for LiquidityAwareSizer."""
    
    def test_singleton(self):
        """Test that LiquidityAwareSizer is a singleton."""
        sizer1 = get_liquidity_sizer()
        sizer2 = get_liquidity_sizer()
        assert sizer1 is sizer2
    
    def test_initialization(self):
        """Test sizer initialization."""
        sizer = get_liquidity_sizer()
        assert sizer is not None
    
    def test_get_config(self):
        """Test configuration retrieval."""
        sizer = get_liquidity_sizer()
        config = sizer.get_config()
        assert isinstance(config, LiquidityConfig)
        assert config.max_participation_rate == 0.1
    
    def test_should_reduce_size(self):
        """Test size reduction logic."""
        sizer = get_liquidity_sizer()
        should_reduce, recommended, reason = sizer.should_reduce_size(
            ticker="KXBTC15M-TEST",
            desired_contracts=100
        )
        assert isinstance(should_reduce, bool)
        assert isinstance(recommended, int)
        assert isinstance(reason, str)
    
    def test_get_liquidity_aware_size(self):
        """Test liquidity-aware sizing."""
        sizer = get_liquidity_sizer()
        size = sizer.get_liquidity_aware_size(
            ticker="KXBTC15M-TEST",
            side="yes",
            desired_contracts=100,
            max_participation_rate=0.1
        )
        assert isinstance(size, int)
        assert size >= 0
        assert size <= 100
    
    def test_analyze_liquidity(self):
        """Test liquidity analysis."""
        sizer = get_liquidity_sizer()
        analysis = sizer._analyze_liquidity("KXBTC15M-TEST")
        assert analysis is not None
        assert analysis.ticker == "KXBTC15M-TEST"
        assert isinstance(analysis.liquidity_level, LiquidityLevel)
    
    def test_liquidity_level_classification(self):
        """Test liquidity level classification."""
        sizer = get_liquidity_sizer()
        # Test with different liquidity levels
        analysis = sizer._analyze_liquidity("KXBTC15M-TEST")
        assert analysis.liquidity_level in [
            LiquidityLevel.HIGH,
            LiquidityLevel.MEDIUM,
            LiquidityLevel.LOW,
            LiquidityLevel.ILLIQUID
        ]
    
    def test_get_liquidity_summary(self):
        """Test liquidity summary."""
        sizer = get_liquidity_sizer()
        summary = sizer.get_liquidity_summary(["KXBTC15M-TEST", "KXETH15M-TEST"])
        assert "total_tickers" in summary
        assert "liquidity_distribution" in summary
        assert summary["total_tickers"] == 2
    
    def test_clear_cache(self):
        """Test cache clearing."""
        sizer = get_liquidity_sizer()
        sizer.clear_cache()
        # Should not raise an exception


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
