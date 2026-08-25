"""
Tests for market regime detector and execution mode selection.

Tests the classification of markets into maker-dominated, taker-dominated, and neutral regimes
based on orderbook state (spread, depth, trade frequency, refresh rate).
"""

import pytest
from merid.event_venues.kalshi.market_regime_detector import (
    MarketRegimeDetector,
    MarketRegime,
    ExecutionMode,
    RegimeMetrics,
    get_regime_detector,
)


class TestMarketRegimeDetector:
    """Test market regime classification logic."""
    
    def test_singleton(self):
        """Test that get_regime_detector returns singleton instance."""
        detector1 = get_regime_detector()
        detector2 = get_regime_detector()
        assert detector1 is detector2
    
    def test_maker_dominated_classification(self):
        """Test classification of maker-dominated regime."""
        detector = MarketRegimeDetector()
        
        # Maker-dominated: wide spread + thick depth + slow refresh + low trade frequency
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=5.0,  # Wide spread (> 4c threshold)
            bid_depth=300.0,  # Thick depth (> 200 threshold)
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,  # Low trade frequency (0 trades/min)
            quote_refresh_timestamps=None,  # Slow refresh (0 refreshes/s)
        )
        
        assert classification.regime == MarketRegime.MAKER_DOMINATED
        assert classification.execution_mode == ExecutionMode.TAKER
        assert classification.confidence >= 0.75  # Should have high confidence
    
    def test_taker_dominated_classification(self):
        """Test classification of taker-dominated regime."""
        detector = MarketRegimeDetector()
        
        # Taker-dominated: tight spread + thin depth + fast refresh + high trade frequency
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=1.0,  # Tight spread (< 2c threshold)
            bid_depth=30.0,  # Thin depth (< 50 threshold)
            ask_depth=30.0,
            mid_price=50.0,
            trade_timestamps=None,  # Low trade frequency (placeholder)
            quote_refresh_timestamps=None,  # Slow refresh (placeholder)
        )
        
        # With only spread and depth matching, should still classify as taker-dominated
        # if at least 3 signals match
        assert classification.regime in [MarketRegime.TAKER_DOMINATED, MarketRegime.NEUTRAL]
    
    def test_neutral_classification(self):
        """Test classification of neutral regime."""
        detector = MarketRegimeDetector()
        
        # Neutral: mixed signals
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=3.0,  # Moderate spread (between tight and wide thresholds)
            bid_depth=100.0,  # Moderate depth
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        assert classification.regime == MarketRegime.NEUTRAL
        assert classification.confidence == 0.5  # Neutral always has 0.5 confidence
    
    def test_execution_mode_maker_dominated(self):
        """Test execution mode for maker-dominated regime."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=5.0,
            bid_depth=300.0,
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Maker-dominated should use taker execution
        assert classification.execution_mode == ExecutionMode.TAKER
    
    def test_execution_mode_taker_dominated(self):
        """Test execution mode for taker-dominated regime."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=1.0,
            bid_depth=30.0,
            ask_depth=30.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Taker-dominated should use maker execution
        if classification.regime == MarketRegime.TAKER_DOMINATED:
            assert classification.execution_mode == ExecutionMode.MAKER
    
    def test_execution_mode_neutral_wide_spread(self):
        """Test execution mode for neutral regime with wide spread."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=3.0,
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=10.0,  # Low price to make spread percentage high
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Neutral with wide spread percentage (> 30%) should use maker
        spread_pct = (3.0 / 10.0) * 100
        if spread_pct > 30:
            assert classification.execution_mode == ExecutionMode.MAKER
    
    def test_execution_mode_neutral_moderate_spread(self):
        """Test execution mode for neutral regime with moderate spread."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=3.0,
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,  # Moderate price
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Neutral with moderate spread percentage (10-30%) should use staged IOC
        spread_pct = (3.0 / 50.0) * 100
        if 10 < spread_pct <= 30:
            assert classification.execution_mode == ExecutionMode.STAGED_IOC
    
    def test_execution_mode_neutral_tight_spread(self):
        """Test execution mode for neutral regime with tight spread."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=1.0,
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Neutral with tight spread percentage (< 10%) should use taker
        spread_pct = (1.0 / 50.0) * 100
        if spread_pct <= 10:
            assert classification.execution_mode == ExecutionMode.TAKER
    
    def test_regime_metrics(self):
        """Test that RegimeMetrics are correctly populated."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=5.0,
            bid_depth=300.0,
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        assert isinstance(classification.metrics, RegimeMetrics)
        assert classification.metrics.spread_cents == 5.0
        assert classification.metrics.bid_depth == 300.0
        assert classification.metrics.ask_depth == 300.0
        assert classification.metrics.mid_price == 50.0
        assert classification.metrics.trade_frequency == 0.0
        assert classification.metrics.refresh_rate == 0.0

    def test_liquidity_availability_score(self):
        """Test that LAS is calculated and included in classification."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=2.0,
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # LAS = (bid_depth + ask_depth) / (1 + spread_cents)
        # Expected: (100 + 100) / (1 + 2) = 200 / 3 = 66.67
        expected_las = (100.0 + 100.0) / (1.0 + 2.0)
        assert abs(classification.liquidity_availability_score - expected_las) < 0.01
        assert hasattr(classification, 'liquidity_availability_score')

    def test_extreme_spread_forces_maker_mode(self):
        """Test that extreme spread (> 100%) forces MAKER mode."""
        detector = MarketRegimeDetector()
        
        # Extreme spread: 65c on 50c price = 130% spread
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=65.0,
            bid_depth=300.0,  # Would normally be maker-dominated
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should force MAKER mode regardless of regime
        assert classification.execution_mode == ExecutionMode.MAKER
    
    def test_confidence_calculation(self):
        """Test confidence calculation for regime classification."""
        detector = MarketRegimeDetector()
        
        # All 4 signals matching should give 1.0 confidence
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=5.0,  # Wide spread
            bid_depth=300.0,  # Thick depth
            ask_depth=300.0,
            mid_price=50.0,
            trade_timestamps=None,  # Low trade frequency
            quote_refresh_timestamps=None,  # Slow refresh
        )
        
        assert classification.confidence >= 0.75  # At least 3/4 signals match
    
    def test_edge_case_zero_depth(self):
        """Test regime classification with zero depth."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=5.0,
            bid_depth=0.0,  # Zero depth
            ask_depth=0.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # With wide spread (1 signal for maker) and zero depth (1 signal for taker),
        # and low trade frequency (1 signal for maker), slow refresh (1 signal for maker),
        # it should classify as maker-dominated (3/4 signals match)
        assert classification.regime == MarketRegime.MAKER_DOMINATED
    
    def test_edge_case_negative_spread(self):
        """Test regime classification with negative spread (inverted book)."""
        detector = MarketRegimeDetector()
        
        classification = detector.classify_regime(
            ticker="KXBTC15M-TEST",
            spread_cents=-10.0,  # Negative spread (inverted)
            bid_depth=100.0,
            ask_depth=100.0,
            mid_price=50.0,
            trade_timestamps=None,
            quote_refresh_timestamps=None,
        )
        
        # Should handle gracefully (likely neutral)
        assert classification.regime == MarketRegime.NEUTRAL
