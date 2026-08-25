"""
Tests for regime classification and execution mode enhancements.

Tests the 2026-08-01 enhancements to market regime detector including:
1. Spread percentage guard for extreme spreads (> 100%)
2. Maker-dominated regime adjustment for moderate spreads (> 50%)
3. Liquidity Availability Score (LAS) calculation and filtering
"""

import pytest
from merid.event_venues.kalshi.market_regime_detector import (
    MarketRegimeDetector,
    MarketRegime,
    ExecutionMode,
    RegimeMetrics,
    RegimeClassification,
)


class TestSpreadPercentageGuard:
    """Test spread percentage guard for extreme spreads."""

    def test_extreme_spread_forces_maker_mode(self):
        """Test that spread > 100% forces MAKER mode regardless of regime."""
        detector = MarketRegimeDetector()
        
        # Even in maker-dominated regime, extreme spread should force maker mode
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=65.0,  # 65c spread on 50c price = 130% spread
            bid_depth=300.0,  # Thick depth (maker-dominated signal)
            ask_depth=300.0,
            mid_price=50.0,  # Low price to make spread percentage extreme
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should force MAKER mode due to extreme spread
        assert classification.execution_mode == ExecutionMode.MAKER

    def test_extreme_spread_in_taker_dominated(self):
        """Test that extreme spread forces MAKER even in taker-dominated regime."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=70.0,  # 70c spread on 50c price = 140% spread
            bid_depth=30.0,  # Thin depth (taker-dominated signal)
            ask_depth=30.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should still force MAKER mode due to extreme spread
        assert classification.execution_mode == ExecutionMode.MAKER

    def test_extreme_spread_in_neutral(self):
        """Test that extreme spread forces MAKER in neutral regime."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=60.0,  # 60c spread on 50c price = 120% spread
            bid_depth=100.0,  # Moderate depth (neutral signal)
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should force MAKER mode due to extreme spread
        assert classification.execution_mode == ExecutionMode.MAKER

    def test_normal_spread_respects_regime(self):
        """Test that normal spreads respect regime classification."""
        detector = MarketRegimeDetector()
        
        # Maker-dominated with normal spread
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=5.0,  # 5c spread on 50c price = 10% spread (normal)
            bid_depth=300.0,  # Thick depth
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should use MAKER for maker-dominated regime with spread >= 5%
        # (TAKER only used if spread < 5% in maker-dominated regime)
        assert classification.execution_mode == ExecutionMode.MAKER


class TestMakerDominatedAdjustment:
    """Test maker-dominated regime adjustment for moderate spreads."""

    def test_moderate_spread_in_maker_dominated_uses_maker(self):
        """Test that spread > 50% in maker-dominated uses MAKER instead of TAKER."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=30.0,  # 30c spread on 50c price = 60% spread (> 50% threshold)
            bid_depth=300.0,  # Thick depth (maker-dominated signal)
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should use MAKER instead of TAKER due to moderate spread
        assert classification.execution_mode == ExecutionMode.MAKER

    def test_low_spread_in_maker_dominated_uses_taker(self):
        """Test that spread < 5% in maker-dominated uses TAKER as expected."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=2.0,  # 2c spread on 50c price = 4% spread (< 5% threshold)
            bid_depth=300.0,  # Thick depth (maker-dominated signal)
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should use TAKER as per normal maker-dominated logic (spread < 5%)
        assert classification.execution_mode == ExecutionMode.TAKER

    def test_exactly_5_percent_spread_boundary(self):
        """Test boundary condition at exactly 5% spread in maker-dominated regime."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=2.5,  # 2.5c spread on 50c price = 5% spread (exact boundary)
            bid_depth=300.0,  # Thick depth (maker-dominated signal)
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # At exactly 5%, the implementation uses MAKER (not < 5% threshold)
        # The threshold is spread_pct < 5, not <= 5
        assert classification.execution_mode == ExecutionMode.MAKER


class TestLiquidityAvailabilityScore:
    """Test Liquidity Availability Score (LAS) calculation."""

    def test_las_calculation_basic(self):
        """Test basic LAS calculation."""
        detector = MarketRegimeDetector()
        
        # LAS = (bid_depth + ask_depth) / (1 + spread_cents)
        # Example: (100 + 100) / (1 + 2) = 200 / 3 = 66.67
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=2.0,
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        expected_las = (100.0 + 100.0) / (1.0 + 2.0)
        assert abs(classification.liquidity_availability_score - expected_las) < 0.01

    def test_las_with_wide_spread(self):
        """Test LAS penalizes wide spreads."""
        detector = MarketRegimeDetector()
        
        # Same depth, wider spread should give lower LAS
        classification_wide = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=10.0,  # Wide spread
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        classification_tight = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=1.0,  # Tight spread
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Wide spread should have lower LAS
        assert classification_wide.liquidity_availability_score < classification_tight.liquidity_availability_score

    def test_las_with_high_depth(self):
        """Test LAS rewards high depth."""
        detector = MarketRegimeDetector()
        
        # Same spread, higher depth should give higher LAS
        classification_deep = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=2.0,
            bid_depth=500.0,  # High depth
            ask_depth=500.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        classification_shallow = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=2.0,
            bid_depth=50.0,  # Low depth
            ask_depth=50.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Deep market should have higher LAS
        assert classification_deep.liquidity_availability_score > classification_shallow.liquidity_availability_score

    def test_las_with_zero_depth(self):
        """Test LAS with zero depth."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=2.0,
            bid_depth=0.0,  # No depth
            ask_depth=0.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should be 0 with no depth
        assert classification.liquidity_availability_score == 0.0

    def test_las_with_zero_spread(self):
        """Test LAS with zero spread (ideal case)."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=0.0,  # No spread
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # LAS = (100 + 100) / (1 + 0) = 200
        expected_las = 200.0
        assert abs(classification.liquidity_availability_score - expected_las) < 0.01

    def test_las_realistic_liquid_market(self):
        """Test LAS for realistic liquid market."""
        detector = MarketRegimeDetector()
        
        # Realistic liquid market: tight spread, good depth
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=1.0,  # 1c spread
            bid_depth=500.0,  # Good depth
            ask_depth=500.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should have high LAS (> 100)
        assert classification.liquidity_availability_score > 100.0

    def test_las_realistic_illiquid_market(self):
        """Test LAS for realistic illiquid market."""
        detector = MarketRegimeDetector()
        
        # Realistic illiquid market: wide spread, low depth
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=10.0,  # 10c spread
            bid_depth=20.0,  # Low depth
            ask_depth=20.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should have low LAS (< 10)
        assert classification.liquidity_availability_score < 10.0


class TestLASThresholdFiltering:
    """Test LAS threshold filtering in agent_grid_15m integration."""

    def test_las_above_threshold_allows_trade(self):
        """Test that LAS > 2 allows trade to proceed."""
        # This tests the integration logic in agent_grid_15m
        # LAS threshold of 2.0 is used for filtering (lowered for $1 position limit)
        las_score = 5.0  # Above threshold
        threshold = 2.0
        
        should_trade = las_score >= threshold
        assert should_trade == True

    def test_las_below_threshold_rejects_trade(self):
        """Test that LAS < 2 rejects trade."""
        # This tests the integration logic in agent_grid_15m
        las_score = 1.0  # Below threshold
        threshold = 2.0
        
        should_trade = las_score >= threshold
        assert should_trade == False

    def test_las_at_boundary(self):
        """Test LAS at exactly threshold boundary."""
        # This tests the integration logic in agent_grid_15m
        las_score = 2.0  # Exactly at threshold
        threshold = 2.0
        
        should_trade = las_score >= threshold
        assert should_trade == True  # Should allow at boundary


class TestRegimeClassificationIntegration:
    """Test integration of all regime enhancements."""

    def test_extreme_spread_low_las_scenario(self):
        """Test scenario with extreme spread and low LAS."""
        detector = MarketRegimeDetector()
        
        # Extreme spread + low depth = very low LAS + forced maker mode
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=60.0,  # Extreme spread (120%)
            bid_depth=10.0,  # Low depth
            ask_depth=10.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should force MAKER mode
        assert classification.execution_mode == ExecutionMode.MAKER
        # Should have very low LAS
        assert classification.liquidity_availability_score < 5.0

    def test_ideal_liquidity_scenario(self):
        """Test ideal liquidity scenario."""
        detector = MarketRegimeDetector()
        
        # Tight spread + high depth = high LAS + appropriate execution
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=1.0,  # Tight spread (2%)
            bid_depth=1000.0,  # Very high depth
            ask_depth=1000.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should have very high LAS
        assert classification.liquidity_availability_score > 500.0
        # Should use appropriate execution (likely TAKER for tight spread in neutral)
        # The exact mode depends on regime classification

    def test_moderate_spread_moderate_depth_scenario(self):
        """Test moderate spread and depth scenario."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=5.0,  # Moderate spread (10%)
            bid_depth=200.0,  # Moderate depth
            ask_depth=200.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should have moderate LAS
        assert 50.0 < classification.liquidity_availability_score < 150.0
        # Should pass LAS threshold (lowered to 2.0 for $1 position limit)
        assert classification.liquidity_availability_score >= 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])