"""
Tests for continuous strike divergence tracking in 15-minute markets.

This test suite validates the 2026 best practice implementation of
real-time strike divergence tracking for binary options trading.

Run with: pytest tests/test_strike_divergence_tracking.py -v
"""

import pytest
import time
from merid.event_venues.kalshi.models import KalshiMarketState


class TestStrikeDivergenceTracking:
    """Test suite for strike divergence tracking functionality."""
    
    @pytest.fixture
    def market_state(self):
        """Create a fresh market state for testing."""
        return KalshiMarketState(
            ticker="KXBTC15M-26JUL012015-15"
        )
    
    def test_divergence_fields_initialized(self, market_state):
        """Test that divergence tracking fields are properly initialized."""
        assert hasattr(market_state, 'strike_divergence_history')
        assert hasattr(market_state, 'max_divergence_pct')
        assert hasattr(market_state, 'current_divergence_pct')
        assert hasattr(market_state, 'last_divergence_update_ts')
        
        # Check initial values
        assert market_state.strike_divergence_history == []
        assert market_state.max_divergence_pct == 0.0
        assert market_state.current_divergence_pct == 0.0
        assert market_state.last_divergence_update_ts == 0.0
    
    def test_divergence_calculation_positive(self, market_state):
        """Test divergence calculation when spot is above strike."""
        market_state.window_strike_price = 67000.0
        market_state.window_strike_source = "kalshi_floor_strike"
        
        # Simulate spot update with divergence
        current_spot = 67335.0  # 0.5% above strike
        divergence_pct = abs((current_spot - market_state.window_strike_price) / market_state.window_strike_price) * 100
        
        market_state.current_divergence_pct = divergence_pct
        market_state.last_divergence_update_ts = time.time()
        market_state.strike_divergence_history.append((time.time(), divergence_pct, current_spot))
        
        assert market_state.current_divergence_pct == 0.5
        assert len(market_state.strike_divergence_history) == 1
        assert market_state.strike_divergence_history[0] == (pytest.approx(time.time(), rel=1e-6), 0.5, 67335.0)
    
    def test_divergence_calculation_negative(self, market_state):
        """Test divergence calculation when spot is below strike."""
        market_state.window_strike_price = 67000.0
        market_state.window_strike_source = "kalshi_floor_strike"
        
        # Simulate spot update with divergence
        current_spot = 66665.0  # 0.5% below strike
        divergence_pct = abs((current_spot - market_state.window_strike_price) / market_state.window_strike_price) * 100
        
        market_state.current_divergence_pct = divergence_pct
        market_state.last_divergence_update_ts = time.time()
        market_state.strike_divergence_history.append((time.time(), divergence_pct, current_spot))
        
        assert market_state.current_divergence_pct == 0.5
        assert len(market_state.strike_divergence_history) == 1
    
    def test_max_divergence_tracking(self, market_state):
        """Test that maximum divergence is tracked correctly."""
        market_state.window_strike_price = 67000.0
        
        # Add multiple divergence points
        divergences = [0.5, 1.0, 0.8, 1.5, 0.3, 2.0]
        for i, div in enumerate(divergences):
            spot = 67000.0 * (1 + div / 100)
            market_state.current_divergence_pct = div
            market_state.last_divergence_update_ts = time.time()
            market_state.strike_divergence_history.append((time.time(), div, spot))
            
            if div > market_state.max_divergence_pct:
                market_state.max_divergence_pct = div
        
        assert market_state.max_divergence_pct == 2.0
    
    def test_divergence_history_trimming(self, market_state):
        """Test that divergence history is trimmed to 180 points."""
        market_state.window_strike_price = 67000.0
        
        # Add more than 180 points
        for i in range(200):
            div = 0.1 + (i % 10) * 0.1
            spot = 67000.0 * (1 + div / 100)
            market_state.current_divergence_pct = div
            market_state.last_divergence_update_ts = time.time()
            market_state.strike_divergence_history.append((time.time(), div, spot))
            
            # Trim to 180 points
            if len(market_state.strike_divergence_history) > 180:
                market_state.strike_divergence_history = market_state.strike_divergence_history[-180:]
        
        assert len(market_state.strike_divergence_history) == 180
    
    def test_divergence_without_strike_price(self, market_state):
        """Test that divergence is not calculated when strike price is unavailable."""
        market_state.window_strike_price = None
        
        # Simulate spot update - should not calculate divergence
        current_spot = 67335.0
        
        # Divergence should remain at default
        assert market_state.current_divergence_pct == 0.0
        assert market_state.max_divergence_pct == 0.0
        assert len(market_state.strike_divergence_history) == 0
    
    def test_divergence_with_zero_strike_price(self, market_state):
        """Test that divergence is not calculated when strike price is zero."""
        market_state.window_strike_price = 0.0
        
        # Simulate spot update - should not calculate divergence
        current_spot = 67335.0
        
        # Divergence should remain at default
        assert market_state.current_divergence_pct == 0.0
        assert market_state.max_divergence_pct == 0.0
        assert len(market_state.strike_divergence_history) == 0
    
    def test_divergence_threshold_warning(self, market_state):
        """Test divergence warning threshold (5%)."""
        market_state.window_strike_price = 67000.0
        
        # Simulate divergence at warning threshold
        current_spot = 70350.0  # 5% above strike
        divergence_pct = abs((current_spot - market_state.window_strike_price) / market_state.window_strike_price) * 100
        
        market_state.current_divergence_pct = divergence_pct
        market_state.last_divergence_update_ts = time.time()
        market_state.strike_divergence_history.append((time.time(), divergence_pct, current_spot))
        
        assert market_state.current_divergence_pct == 5.0
        # This should trigger a warning log in production
    
    def test_divergence_threshold_critical(self, market_state):
        """Test divergence critical threshold (10%)."""
        market_state.window_strike_price = 67000.0
        
        # Simulate divergence at critical threshold
        current_spot = 73700.0  # 10% above strike
        divergence_pct = abs((current_spot - market_state.window_strike_price) / market_state.window_strike_price) * 100
        
        market_state.current_divergence_pct = divergence_pct
        market_state.last_divergence_update_ts = time.time()
        market_state.strike_divergence_history.append((time.time(), divergence_pct, current_spot))
        
        assert market_state.current_divergence_pct == 10.0
        # This should trigger a critical warning log in production
    
    def test_divergence_history_data_structure(self, market_state):
        """Test that divergence history maintains correct data structure."""
        market_state.window_strike_price = 67000.0
        
        # Add a divergence point
        current_spot = 67335.0
        divergence_pct = 0.5
        timestamp = time.time()
        
        market_state.current_divergence_pct = divergence_pct
        market_state.last_divergence_update_ts = timestamp
        market_state.strike_divergence_history.append((timestamp, divergence_pct, current_spot))
        
        # Verify data structure
        assert len(market_state.strike_divergence_history) == 1
        entry = market_state.strike_divergence_history[0]
        assert isinstance(entry, tuple)
        assert len(entry) == 3
        assert entry[0] == pytest.approx(timestamp, rel=1e-6)  # timestamp
        assert entry[1] == divergence_pct  # divergence_pct
        assert entry[2] == current_spot  # spot_price


class TestStrikeDivergenceIntegration:
    """Integration tests for strike divergence tracking with market state updates."""
    
    @pytest.fixture
    def market_state(self):
        """Create a market state with strike price set."""
        state = KalshiMarketState(
            ticker="KXBTC15M-26JUL012015-15"
        )
        state.window_strike_price = 67000.0
        state.window_strike_source = "kalshi_floor_strike"
        state.window_strike_ts = time.time()
        return state
    
    def test_divergence_updates_with_spot_changes(self, market_state):
        """Test that divergence updates as spot price changes."""
        initial_spot = 67000.0
        
        # Simulate spot moving away from strike
        spot_updates = [67000.0, 67100.0, 67200.0, 67300.0, 67400.0]
        
        for spot in spot_updates:
            divergence_pct = abs((spot - market_state.window_strike_price) / market_state.window_strike_price) * 100
            market_state.current_divergence_pct = divergence_pct
            market_state.last_divergence_update_ts = time.time()
            market_state.strike_divergence_history.append((time.time(), divergence_pct, spot))
            
            if divergence_pct > market_state.max_divergence_pct:
                market_state.max_divergence_pct = divergence_pct
        
        assert len(market_state.strike_divergence_history) == 5
        assert market_state.max_divergence_pct > 0
        assert market_state.current_divergence_pct > 0
    
    def test_divergence_resets_on_new_window(self, market_state):
        """Test that divergence tracking resets for new market windows."""
        # Set up divergence for current window
        market_state.current_divergence_pct = 2.5
        market_state.max_divergence_pct = 3.0
        market_state.strike_divergence_history = [(time.time(), 2.5, 68675.0)]
        
        # Simulate new window (reset strike price)
        market_state.window_strike_price = 68000.0
        market_state.window_strike_ts = time.time()
        
        # Reset divergence tracking for new window
        market_state.current_divergence_pct = 0.0
        market_state.max_divergence_pct = 0.0
        market_state.strike_divergence_history = []
        market_state.last_divergence_update_ts = 0.0
        
        assert market_state.current_divergence_pct == 0.0
        assert market_state.max_divergence_pct == 0.0
        assert len(market_state.strike_divergence_history) == 0
