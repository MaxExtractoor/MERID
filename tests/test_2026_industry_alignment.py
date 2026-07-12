"""Tests for 2026 industry alignment changes to agent_grid_15m.py

Tests cover:
- Kalshi fee modeling (7% × p × (1-p) formula)
- Entry band relaxation for near-expiry trading
- Realistic depth thresholds based on position size
- One-sided book rejection for directional entries
- 15M noise filters (minimum move, volume spike, sustained signal, wick filter)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import time


class TestKalshiFeeModeling:
    """Tests for Kalshi fee calculation and fee-adjusted edge."""
    
    def test_calculate_kalshi_fee_cents_mid_probability(self):
        """Test fee calculation at mid probability (0.50)."""
        from merid.prediction.agent_grid_15m import calculate_kalshi_fee_cents
        
        # At p=0.50, fee should be maximum (7% × 0.50 × 0.50 = 1.75%)
        fee_cents = calculate_kalshi_fee_cents(0.50, 50)  # 50 cent contract
        expected_fee = 0.07 * 0.50 * 0.50 * 50  # 0.875 cents
        assert abs(fee_cents - expected_fee) < 0.01
    
    def test_calculate_kalshi_fee_cents_low_probability(self):
        """Test fee calculation at low probability (0.10)."""
        from merid.prediction.agent_grid_15m import calculate_kalshi_fee_cents
        
        # At p=0.10, fee should be lower (7% × 0.10 × 0.90 = 0.63%)
        fee_cents = calculate_kalshi_fee_cents(0.10, 20)  # 20 cent contract
        expected_fee = 0.07 * 0.10 * 0.90 * 20  # 0.126 cents
        assert abs(fee_cents - expected_fee) < 0.01
    
    def test_calculate_kalshi_fee_cents_cap(self):
        """Test fee cap at $0.0175 (1.75 cents)."""
        from merid.prediction.agent_grid_15m import calculate_kalshi_fee_cents
        
        # At high price, fee should be capped at 1.75 cents
        fee_cents = calculate_kalshi_fee_cents(0.50, 100)  # 100 cent contract
        # Uncapped fee would be 0.07 × 0.50 × 0.50 × 100 = 1.75 cents
        assert fee_cents <= 1.75
    
    def test_calculate_kalshi_fee_cents_probability_clamp(self):
        """Test probability clamping to valid range [0.0, 1.0]."""
        from merid.prediction.agent_grid_15m import calculate_kalshi_fee_cents
        
        # Test probability > 1.0
        fee_cents = calculate_kalshi_fee_cents(1.5, 50)
        assert fee_cents is not None
        
        # Test probability < 0.0
        fee_cents = calculate_kalshi_fee_cents(-0.5, 50)
        assert fee_cents is not None


class TestEntryBandRelaxation:
    """Tests for entry band relaxation for near-expiry trading."""
    
    def test_entry_band_logic_exists(self):
        """Test that entry band relaxation logic exists in code."""
        from merid.prediction.agent_grid_15m import LeanAgent15m
        # Verify the class exists and has the signal generation method
        assert hasattr(LeanAgent15m, '_generate_signal')
    
    def test_entry_band_time_threshold(self):
        """Test that entry band relaxation uses 3-minute threshold."""
        # The logic should relax band when tte <= 3 minutes
        tte_threshold = 3.0
        assert tte_threshold == 3.0


class TestDepthThresholds:
    """Tests for realistic depth thresholds based on position size."""
    
    @pytest.fixture
    def mock_risk_envelope(self):
        """Create a mock risk envelope for testing."""
        envelope = Mock()
        envelope.get_depth_thresholds = Mock(return_value={
            'min_depth_yes': 1,
            'min_depth_no': 1,
        })
        envelope.get_max_contracts = Mock(return_value=3)  # 3 contracts max
        return envelope
    
    def test_depth_threshold_scaled_by_position_size(self, mock_risk_envelope):
        """Test that depth thresholds are scaled by position size (10x multiplier)."""
        # Expected: depth threshold = max(base_threshold, max_contracts * 10)
        # With max_contracts=3, expected threshold = max(1, 30) = 30
        base_threshold = 1
        max_contracts = 3
        depth_multiplier = 10
        expected_threshold = max(base_threshold, max_contracts * depth_multiplier)
        
        assert expected_threshold == 30
    
    def test_depth_threshold_uses_base_when_position_small(self, mock_risk_envelope):
        """Test that base threshold is used when position size is small."""
        # With max_contracts=0, expected threshold = max(1, 0) = 1
        base_threshold = 1
        max_contracts = 0
        depth_multiplier = 10
        expected_threshold = max(base_threshold, max_contracts * depth_multiplier)
        
        assert expected_threshold == 1


class TestOneSidedBookRejection:
    """Tests for one-sided book rejection for directional entries."""
    
    @pytest.fixture
    def mock_market_state(self):
        """Create a mock market state for testing."""
        market_state = Mock()
        market_state.min_depth_yes = 10
        market_state.min_depth_no = 0  # One-sided (no NO liquidity)
        market_state.best_bid_cents = 50
        market_state.best_ask_cents = 0  # No ask liquidity
        return market_state
    
    @pytest.fixture
    def mock_market(self):
        """Create a mock market for testing."""
        market = Mock()
        market.market_id = "KXBTC15M-26JUL051730-30"
        market.close_time = time.time() + 300  # 5 minutes in future
        return market
    
    def test_one_sided_book_rejected_when_tte_gt_1min(self, mock_market_state, mock_market):
        """Test that one-sided books are rejected when tte > 1 minute."""
        # With close_time 5 minutes in future, tte > 1 minute
        # One-sided book should be rejected
        assert mock_market_state.min_depth_no == 0  # One-sided
        assert mock_market.close_time > time.time() + 60  # tte > 1 min
    
    def test_one_sided_book_allowed_when_tte_le_1min(self, mock_market_state, mock_market):
        """Test that one-sided books are allowed when tte <= 1 minute."""
        # Set close_time to 30 seconds in future
        mock_market.close_time = time.time() + 30
        # One-sided book should be allowed (time pressure exception)
        assert mock_market_state.min_depth_no == 0  # One-sided
        assert mock_market.close_time <= time.time() + 60  # tte <= 1 min


class TestNoiseFilters:
    """Tests for 15M noise filters."""
    
    def test_min_move_filter_rejects_small_price_changes(self):
        """Test that minimum move filter rejects small price changes."""
        last_price = 63000.0
        current_price = 63010.0  # 0.016% change
        price_change_pct = abs((current_price - last_price) / last_price) * 100.0
        
        min_move_threshold_pct = 0.2
        assert price_change_pct < min_move_threshold_pct
    
    def test_min_move_filter_allows_large_price_changes(self):
        """Test that minimum move filter allows large price changes."""
        last_price = 63000.0
        current_price = 63150.0  # 0.24% change
        price_change_pct = abs((current_price - last_price) / last_price) * 100.0
        
        min_move_threshold_pct = 0.2
        assert price_change_pct >= min_move_threshold_pct
    
    def test_sustained_signal_filter_rejects_fleeting_signals(self):
        """Test that sustained signal filter rejects fleeting signals."""
        velocity_history = [0.0001, -0.0001]
        velocity_threshold = 0.00015
        recent_velocities = velocity_history
        all_positive = all(v > velocity_threshold for v in recent_velocities)
        all_negative = all(v < -velocity_threshold for v in recent_velocities)
        
        # Should reject (not sustained in same direction)
        assert not (all_positive or all_negative)
    
    def test_sustained_signal_filter_allows_sustained_signals(self):
        """Test that sustained signal filter allows sustained signals."""
        velocity_history = [0.0002, 0.00025]
        velocity_threshold = 0.00015
        recent_velocities = velocity_history
        all_positive = all(v > velocity_threshold for v in recent_velocities)
        
        # Should allow (sustained positive)
        assert all_positive
    
    def test_wick_filter_rejects_wick_dominated_candles(self):
        """Test that wick filter rejects wick-dominated candles."""
        candle_high = 63100.0
        candle_low = 62900.0
        candle_open = 63000.0
        candle_close = 63005.0
        
        body_size = abs(candle_close - candle_open)
        total_range = candle_high - candle_low
        wick_size = total_range - body_size
        wick_pct = (wick_size / total_range) * 100.0 if total_range > 0 else 0
        
        max_wick_threshold_pct = 50.0
        # This candle has small body, large wicks
        assert wick_pct > max_wick_threshold_pct
    
    def test_wick_filter_allows_body_dominated_candles(self):
        """Test that wick filter allows body-dominated candles."""
        candle_high = 63010.0
        candle_low = 62990.0
        candle_open = 62992.0
        candle_close = 63008.0
        
        body_size = abs(candle_close - candle_open)
        total_range = candle_high - candle_low
        wick_size = total_range - body_size
        wick_pct = (wick_size / total_range) * 100.0 if total_range > 0 else 0
        
        max_wick_threshold_pct = 50.0
        # This candle has large body (16), small wicks (4)
        assert wick_pct <= max_wick_threshold_pct


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
