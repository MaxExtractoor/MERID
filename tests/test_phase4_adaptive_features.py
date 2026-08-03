"""
Test suite for Phase 4 adaptive features (2026-06-28).

Tests:
1. Regime detection (market regime classification)
2. Adaptive strategy selection (strategy selection based on regime)
"""
import pytest
import time
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRegimeDetection:
    """Test regime detection."""
    
    def test_regime_detector_can_be_imported(self):
        """Test that regime detector can be imported."""
        try:
            from merid.prediction.strategies.regime_detection import RegimeDetector
            assert RegimeDetector is not None
        except Exception as e:
            pytest.fail(f"Failed to import RegimeDetector: {e}")
    
    def test_regime_detector_initialization(self):
        """Test regime detector initialization."""
        from merid.prediction.strategies.regime_detection import RegimeDetector
        
        detector = RegimeDetector()
        
        assert detector.trend_window == 3600  # 1 hour
        assert detector.volatility_window == 300  # 5 minutes
        assert detector.trend_threshold == 0.002
    
    def test_regime_detector_custom_parameters(self):
        """Test regime detector with custom parameters."""
        from merid.prediction.strategies.regime_detection import RegimeDetector
        
        detector = RegimeDetector(
            trend_window=1800,
            volatility_window=600,
            trend_threshold=0.003,
        )
        
        assert detector.trend_window == 1800
        assert detector.volatility_window == 600
        assert detector.trend_threshold == 0.003
    
    def test_trend_calculation_up(self):
        """Test trend calculation for upward movement."""
        from merid.prediction.strategies.regime_detection import RegimeDetector
        
        detector = RegimeDetector(trend_window=10)
        
        # Simulate upward trend
        now = time.time()
        for i in range(20):
            price = 65000.0 + (i * 50)  # Upward trend
            detector.update_price("BTC-USD", price, now - (20 - i))
        
        # Should detect positive trend
        regime = detector.get_regime("BTC-USD")
        assert regime is not None
        assert regime.trend_strength > 0
    
    def test_trend_calculation_down(self):
        """Test trend calculation for downward movement."""
        from merid.prediction.strategies.regime_detection import RegimeDetector
        
        detector = RegimeDetector(trend_window=10)
        
        # Simulate downward trend
        now = time.time()
        for i in range(20):
            price = 65000.0 - (i * 50)  # Downward trend
            detector.update_price("BTC-USD", price, now - (20 - i))
        
        # Should detect negative trend
        regime = detector.get_regime("BTC-USD")
        assert regime is not None
        assert regime.trend_strength < 0
    
    def test_regime_detection_trending_up(self):
        """Test detection of trending up regime."""
        from merid.prediction.strategies.regime_detection import (
            RegimeDetector,
            MarketRegime,
        )
        
        detector = RegimeDetector(
            trend_window=10,
            trend_threshold=0.001,
        )
        
        # Simulate strong upward trend
        now = time.time()
        for i in range(20):
            price = 65000.0 + (i * 200)  # Strong upward trend
            detector.update_price("BTC-USD", price, now - (20 - i))
        
        # Should detect TRENDING_UP regime
        regime = detector.get_regime("BTC-USD")
        assert regime is not None
        assert regime.regime == MarketRegime.TRENDING_UP
    
    def test_regime_detection_trending_down(self):
        """Test detection of trending down regime."""
        from merid.prediction.strategies.regime_detection import (
            RegimeDetector,
            MarketRegime,
        )
        
        detector = RegimeDetector(
            trend_window=10,
            trend_threshold=0.001,
        )
        
        # Simulate strong downward trend
        now = time.time()
        for i in range(20):
            price = 65000.0 - (i * 200)  # Strong downward trend
            detector.update_price("BTC-USD", price, now - (20 - i))
        
        # Should detect TRENDING_DOWN regime
        regime = detector.get_regime("BTC-USD")
        assert regime is not None
        assert regime.regime == MarketRegime.TRENDING_DOWN
    
    def test_regime_detection_ranging(self):
        """Test detection of ranging regime."""
        from merid.prediction.strategies.regime_detection import (
            RegimeDetector,
            MarketRegime,
        )
        
        detector = RegimeDetector(
            trend_window=10,
            trend_threshold=0.01,  # High threshold
            volatility_threshold=0.01,  # High threshold
        )
        
        # Simulate ranging (small movements around a mean)
        now = time.time()
        for i in range(20):
            price = 65000.0 + (i % 5 - 2) * 10  # Small oscillations
            detector.update_price("BTC-USD", price, now - (20 - i))
        
        # Should detect RANGING regime
        regime = detector.get_regime("BTC-USD")
        assert regime is not None
        # Could be RANGING or QUIET depending on exact values
        assert regime.regime in [MarketRegime.RANGING, MarketRegime.QUIET]
    
    def test_regime_detection_insufficient_data(self):
        """Test regime detection with insufficient data."""
        from merid.prediction.strategies.regime_detection import (
            RegimeDetector,
            MarketRegime,
        )
        
        detector = RegimeDetector()
        
        # Only one data point
        detector.update_price("BTC-USD", 65000.0, time.time())
        
        # Should default to QUIET regime
        regime = detector.get_regime("BTC-USD")
        assert regime is not None
        assert regime.regime == MarketRegime.QUIET
        assert regime.confidence == 0.0
    
    def test_regime_detector_singleton(self):
        """Test that singleton returns same instance."""
        from merid.prediction.strategies.regime_detection import get_regime_detector
        
        detector1 = get_regime_detector()
        detector2 = get_regime_detector()
        
        assert detector1 is detector2


class TestAdaptiveStrategySelection:
    """Test adaptive strategy selection."""
    
    def test_adaptive_selector_can_be_imported(self):
        """Test that adaptive selector can be imported."""
        try:
            from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
            assert AdaptiveStrategySelector is not None
        except Exception as e:
            pytest.fail(f"Failed to import AdaptiveStrategySelector: {e}")
    
    def test_adaptive_selector_initialization(self):
        """Test adaptive selector initialization."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        
        selector = AdaptiveStrategySelector()
        
        assert selector.regime_detector is not None
    
    def test_strategy_map_trending_up(self):
        """Test strategy mapping for trending up regime."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import MarketRegime
        
        selector = AdaptiveStrategySelector()
        
        trending_strategies = selector.REGIME_STRATEGY_MAP.get(MarketRegime.TRENDING_UP, [])
        
        # Should include momentum strategies
        assert "coinbase_velocity" in trending_strategies
        assert "trend_alignment" in trending_strategies
        assert "ma_crossover" in trending_strategies
    
    def test_strategy_map_trending_down(self):
        """Test strategy mapping for trending down regime."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import MarketRegime
        
        selector = AdaptiveStrategySelector()
        
        trending_strategies = selector.REGIME_STRATEGY_MAP.get(MarketRegime.TRENDING_DOWN, [])
        
        # Should include momentum strategies
        assert "coinbase_velocity" in trending_strategies
        assert "trend_alignment" in trending_strategies
        assert "ma_crossover" in trending_strategies
    
    @pytest.mark.skip(reason="2026-07-18: Panic fade disabled - causing losses by betting against trend")
    def test_strategy_map_ranging(self):
        """Test strategy mapping for ranging regime."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import MarketRegime
        
        selector = AdaptiveStrategySelector()
        
        ranging_strategies = selector.REGIME_STRATEGY_MAP.get(MarketRegime.RANGING, [])
        
        # Should include mean reversion strategies
        assert "panic_fade" in ranging_strategies
        assert "vwap_premium" in ranging_strategies
    
    @pytest.mark.skip(reason="2026-07-18: Panic fade disabled - causing losses by betting against trend")
    def test_strategy_map_volatile(self):
        """Test strategy mapping for volatile regime."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import MarketRegime
        
        selector = AdaptiveStrategySelector()
        
        volatile_strategies = selector.REGIME_STRATEGY_MAP.get(MarketRegime.VOLATILE, [])
        
        # Should include volatility reversion
        assert "panic_fade" in volatile_strategies
    
    def test_strategy_map_quiet(self):
        """Test strategy mapping for quiet regime."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import MarketRegime
        
        selector = AdaptiveStrategySelector()
        
        quiet_strategies = selector.REGIME_STRATEGY_MAP.get(MarketRegime.QUIET, [])
        
        # Should be empty (reduce activity in quiet markets)
        assert len(quiet_strategies) == 0
    
    def test_strategy_recommendation_generation(self):
        """Test strategy recommendation generation."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import MarketRegime, RegimeDetector
        
        # Use regime detector with lower threshold for testing
        regime_detector = RegimeDetector(
            trend_window=10,
            trend_threshold=0.001,  # Lower threshold for testing
        )
        selector = AdaptiveStrategySelector(regime_detector=regime_detector)
        
        # Simulate trending up regime
        now = time.time()
        for i in range(20):
            price = 65000.0 + (i * 200)  # Strong upward trend
            selector.update_price("BTC-USD", price, now - (20 - i))
        
        # Get recommendation
        recommendation = selector.get_recommendation("BTC-USD")
        
        assert recommendation is not None
        assert recommendation.asset == "BTC-USD"
        assert recommendation.regime == MarketRegime.TRENDING_UP
        assert len(recommendation.recommended_strategies) > 0
    
    def test_is_strategy_enabled(self):
        """Test strategy enabled check."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import RegimeDetector
        
        # Use regime detector with lower threshold for testing
        regime_detector = RegimeDetector(
            trend_window=10,
            trend_threshold=0.001,  # Lower threshold for testing
        )
        selector = AdaptiveStrategySelector(regime_detector=regime_detector)
        
        # Simulate trending up regime
        now = time.time()
        for i in range(20):
            price = 65000.0 + (i * 200)
            selector.update_price("BTC-USD", price, now - (20 - i))
        
        # Check if momentum strategy is enabled
        is_enabled = selector.is_strategy_enabled("BTC-USD", "coinbase_velocity")
        
        assert is_enabled == True
    
    @pytest.mark.skip(reason="2026-07-18: Panic fade disabled - causing losses by betting against trend")
    def test_is_strategy_disabled(self):
        """Test strategy disabled check."""
        from merid.prediction.strategies.adaptive_strategy import AdaptiveStrategySelector
        from merid.prediction.strategies.regime_detection import RegimeDetector
        
        # Use regime detector with lower threshold for testing
        regime_detector = RegimeDetector(
            trend_window=10,
            trend_threshold=0.001,  # Lower threshold for testing
        )
        selector = AdaptiveStrategySelector(regime_detector=regime_detector)
        
        # Simulate trending up regime
        now = time.time()
        for i in range(20):
            price = 65000.0 + (i * 200)
            selector.update_price("BTC-USD", price, now - (20 - i))
        
        # Check if mean reversion strategy is disabled in trending regime
        is_enabled = selector.is_strategy_enabled("BTC-USD", "panic_fade")
        
        # panic_fade should not be in trending up strategy list
        assert is_enabled == False
    
    def test_adaptive_selector_singleton(self):
        """Test that singleton returns same instance."""
        from merid.prediction.strategies.adaptive_strategy import get_adaptive_strategy_selector
        
        selector1 = get_adaptive_strategy_selector()
        selector2 = get_adaptive_strategy_selector()
        
        assert selector1 is selector2


class TestPhase4ModuleStructure:
    """Test that Phase 4 module structure is correct."""
    
    def test_regime_detection_exists(self):
        """Test that regime_detection.py exists."""
        regime_file = Path(__file__).parent.parent / "merid" / "prediction" / "strategies" / "regime_detection.py"
        assert regime_file.exists(), "regime_detection.py should exist"
    
    def test_adaptive_strategy_exists(self):
        """Test that adaptive_strategy.py exists."""
        adaptive_file = Path(__file__).parent.parent / "merid" / "prediction" / "strategies" / "adaptive_strategy.py"
        assert adaptive_file.exists(), "adaptive_strategy.py should exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
