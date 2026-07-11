"""
Unit tests for regime detection module.

Tests regime detection logic, hysteresis, and adjustment factors.
"""

import pytest
import numpy as np
from merid.event_venues.kalshi.regime_detector import (
    RegimeDetector,
    Regime,
    RegimeState,
    reset_regime_detector
)


class TestRegimeDetector:
    """Test suite for RegimeDetector."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        reset_regime_detector()
        self.detector = RegimeDetector(lookback_periods=14, hysteresis_periods=3)
    
    def test_initial_state(self):
        """Test initial regime state."""
        state = self.detector.get_state()
        assert state.current == Regime.MEAN_REVERSION
        assert state.atr_pct == 0.0
        assert state.periods_in_regime == 0
    
    def test_atr_calculation(self):
        """Test ATR% calculation."""
        # Create price series with known volatility
        prices = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 
                          108.0, 109.0, 110.0, 111.0, 112.0, 113.0, 114.0])
        
        atr_pct = self.detector._calculate_atr_pct(prices)
        assert atr_pct > 0
        assert atr_pct < 10  # Should be reasonable for 1% daily change
    
    def test_regime_classification_normal(self):
        """Test regime classification for normal volatility."""
        # Normal volatility: ATR% around 1-2%
        prices = np.array([100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0, 103.5,
                          104.0, 104.5, 105.0, 105.5, 106.0, 106.5, 107.0])
        
        atr_pct = self.detector._calculate_atr_pct(prices)
        regime = self.detector._classify_regime(atr_pct, 0.5, 0.3)
        
        assert regime == Regime.MEAN_REVERSION
    
    def test_regime_classification_crisis(self):
        """Test regime classification for crisis volatility."""
        # Crisis volatility: ATR% > 4% with high correlation
        # Use more extreme price changes to ensure ATR% exceeds EXTREME threshold
        prices = np.array([100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0,
                          180.0, 190.0, 200.0, 210.0, 220.0, 230.0, 240.0])
        
        atr_pct = self.detector._calculate_atr_pct(prices)
        regime = self.detector._classify_regime(atr_pct, 0.95, 0.8)  # High correlation
        
        assert regime == Regime.CRISIS
    
    def test_regime_classification_momentum(self):
        """Test regime classification for momentum."""
        # Moderate volatility (ATR% > NORMAL threshold of 2.0) + high order flow
        # Use larger price changes to ensure ATR% exceeds NORMAL threshold
        prices = np.array([100.0, 103.0, 106.0, 109.0, 112.0, 115.0, 118.0, 121.0,
                          124.0, 127.0, 130.0, 133.0, 136.0, 139.0, 142.0])
        
        atr_pct = self.detector._calculate_atr_pct(prices)
        regime = self.detector._classify_regime(atr_pct, 0.5, 0.7)  # High order flow (>0.6 threshold)
        
        assert regime == Regime.MOMENTUM
    
    def test_hysteresis(self):
        """Test hysteresis prevents regime flickering."""
        # Start with normal regime
        prices_normal = np.array([100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0, 103.5,
                                  104.0, 104.5, 105.0, 105.5, 106.0, 106.5, 107.0])
        
        # Update with normal regime
        state = self.detector.update(
            {"BTC": prices_normal},
            {"BTC": np.ones(15)},
            {"BTC": {"bid_depth": 100, "ask_depth": 100}}
        )
        
        assert state.current == Regime.MEAN_REVERSION
        
        # Now switch to crisis volatility (use extreme price changes)
        prices_crisis = np.array([100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0,
                                   180.0, 190.0, 200.0, 210.0, 220.0, 230.0, 240.0])
        
        # First update: should not switch yet (hysteresis)
        state = self.detector.update(
            {"BTC": prices_crisis},
            {"BTC": np.ones(15)},
            {"BTC": {"bid_depth": 100, "ask_depth": 100}}
        )
        
        assert state.current == Regime.MEAN_REVERSION  # Still in old regime
        assert state.periods_in_regime == 1
        
        # Second update: still not enough
        state = self.detector.update(
            {"BTC": prices_crisis},
            {"BTC": np.ones(15)},
            {"BTC": {"bid_depth": 100, "ask_depth": 100}}
        )
        
        assert state.current == Regime.MEAN_REVERSION
        assert state.periods_in_regime == 2
        
        # Third update: should switch (hysteresis threshold reached)
        state = self.detector.update(
            {"BTC": prices_crisis},
            {"BTC": np.ones(15)},
            {"BTC": {"bid_depth": 100, "ask_depth": 100}}
        )
        
        assert state.current == Regime.CRISIS
        assert state.periods_in_regime == 0
    
    def test_adjustment_factors(self):
        """Test adjustment factors for each regime."""
        # Mean reversion: no adjustment
        factors = self.detector.get_adjustment_factor()
        assert factors["price_range_multiplier"] == 1.0
        assert factors["spread_multiplier"] == 1.0
        assert factors["position_size_multiplier"] == 1.0
        
        # Force crisis regime
        self.detector.state.current = Regime.CRISIS
        factors = self.detector.get_adjustment_factor()
        
        assert factors["price_range_multiplier"] == 1.9
        assert factors["spread_multiplier"] == 3.3
        assert factors["position_size_multiplier"] == 0.5
    
    def test_confidence_calculation(self):
        """Test confidence calculation based on history."""
        # Initially low confidence
        state = self.detector.get_state()
        assert state.confidence == 0.0
        
        # Add some consistent history
        for _ in range(10):
            prices = np.array([100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0, 103.5,
                              104.0, 104.5, 105.0, 105.5, 106.0, 106.5, 107.0])
            self.detector.update(
                {"BTC": prices},
                {"BTC": np.ones(15)},
                {"BTC": {"bid_depth": 100, "ask_depth": 100}}
            )
        
        state = self.detector.get_state()
        assert state.confidence > 0.5  # Should be high after consistent updates
    
    def test_atr_thresholds_update(self):
        """Test updating ATR thresholds."""
        new_thresholds = {
            "LOW": 0.5,
            "NORMAL": 1.5,
            "HIGH": 2.5,
            "EXTREME": 3.5
        }
        
        self.detector.set_atr_thresholds(new_thresholds)
        
        assert self.detector.atr_thresholds["LOW"] == 0.5
        assert self.detector.atr_thresholds["NORMAL"] == 1.5
        assert self.detector.atr_thresholds["HIGH"] == 2.5
        assert self.detector.atr_thresholds["EXTREME"] == 3.5
    
    def test_insufficient_data(self):
        """Test behavior with insufficient data."""
        # Not enough data for ATR calculation
        prices = np.array([100.0, 101.0])
        
        state = self.detector.update(
            {"BTC": prices},
            {"BTC": np.ones(2)},
            {"BTC": {"bid_depth": 100, "ask_depth": 100}}
        )
        
        # Should return current state without crashing
        assert state.current == Regime.MEAN_REVERSION
        assert state.atr_pct == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
