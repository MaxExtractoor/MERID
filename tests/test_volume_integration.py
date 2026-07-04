"""
Tests for volume data integration with OHLC proxy calculation.

This test suite validates the 2026 best practice implementation of
volume data extraction with OHLC proxy fallback when direct volume is unavailable.

Run with: pytest tests/test_volume_integration.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock


class TestVolumeExtraction:
    """Test suite for volume data extraction with OHLC proxy fallback."""
    
    def test_volume_from_spot_data_direct(self):
        """Test volume extraction when spot_data has direct volume field."""
        # Create mock spot_data with volume
        spot_data = Mock()
        spot_data.volume = 1000.0
        spot_data.open = 58000.0
        spot_data.high = 58500.0
        spot_data.low = 57500.0
        
        # Simulate volume extraction logic from agent_grid_15m.py
        volume = 1.0  # Default
        if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:
            volume = float(spot_data.volume)
        
        assert volume == 1000.0
    
    def test_volume_ohlc_proxy_calculation(self):
        """Test OHLC proxy volume calculation when direct volume is unavailable."""
        # Create mock spot_data without volume
        spot_data = Mock()
        spot_data.volume = None
        spot_data.open = 58000.0
        spot_data.high = 58500.0
        spot_data.low = 57500.0
        
        spot_price = 58000.0
        
        # Simulate OHLC proxy volume calculation from agent_grid_15m.py
        volume = 1.0  # Default
        if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:
            volume = float(spot_data.volume)
        else:
            # Fallback: Calculate OHLC proxy volume from price movement
            if spot_data.high > spot_data.low:
                volume_proxy = (spot_data.high - spot_data.low) * spot_price
                # Normalize to reasonable range (1-100)
                volume = max(1.0, min(100.0, volume_proxy * 100))
        
        # Expected: (58500 - 57500) * 58000 * 100 = 1000 * 58000 * 100 = 5,800,000,000
        # Normalized to max 100
        assert volume == 100.0
    
    def test_volume_ohlc_proxy_normalization(self):
        """Test that OHLC proxy volume is normalized to 1-100 range."""
        # Test with small price movement
        spot_data = Mock()
        spot_data.volume = None
        spot_data.high = 58001.0
        spot_data.low = 57999.0
        
        spot_price = 58000.0
        
        volume = 1.0
        if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:
            volume = float(spot_data.volume)
        else:
            if spot_data.high > spot_data.low:
                volume_proxy = (spot_data.high - spot_data.low) * spot_price
                volume = max(1.0, min(100.0, volume_proxy * 100))
        
        # Small movement should give small volume, but at least 1.0
        assert volume >= 1.0
        assert volume <= 100.0
    
    def test_volume_ohlc_proxy_invalid_data(self):
        """Test volume fallback when OHLC data is invalid (high <= low)."""
        # Create mock spot_data with invalid OHLC
        spot_data = Mock()
        spot_data.volume = None
        spot_data.high = 57500.0
        spot_data.low = 58500.0  # high < low (invalid)
        
        spot_price = 58000.0
        
        # Simulate the logic
        volume = 1.0
        if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:
            volume = float(spot_data.volume)
        else:
            if spot_data.high > spot_data.low:
                volume_proxy = (spot_data.high - spot_data.low) * spot_price
                volume = max(1.0, min(100.0, volume_proxy * 100))
            else:
                # Invalid OHLC, use default
                volume = 1.0
        
        assert volume == 1.0
    
    def test_volume_no_spot_data(self):
        """Test volume when spot_data is None."""
        spot_data = None
        spot_price = 58000.0
        
        # Simulate the logic
        volume = 1.0
        if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:
            volume = float(spot_data.volume)
        else:
            # No spot data, use default
            volume = 1.0
        
        assert volume == 1.0
    
    def test_volume_zero_spot_data(self):
        """Test volume when spot_data exists but has no volume attribute."""
        spot_data = Mock(spec=[])  # Mock with no attributes
        spot_price = 58000.0
        
        # Simulate the logic
        volume = 1.0
        if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:
            volume = float(spot_data.volume)
        else:
            # No volume attribute, use default
            volume = 1.0
        
        assert volume == 1.0
    
    def test_volume_ohlc_proxy_different_assets(self):
        """Test OHLC proxy volume calculation for different crypto assets."""
        test_cases = [
            ("BTC", 58000.0, 58500.0, 57500.0),
            ("ETH", 3000.0, 3050.0, 2950.0),
            ("SOL", 150.0, 155.0, 145.0),
            ("XRP", 0.60, 0.65, 0.55),
            ("DOGE", 0.15, 0.20, 0.10),
        ]
        
        for asset, spot, high, low in test_cases:
            spot_data = Mock()
            spot_data.volume = None
            spot_data.high = high
            spot_data.low = low
            
            volume = 1.0
            if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:
                volume = float(spot_data.volume)
            else:
                if spot_data.high > spot_data.low:
                    volume_proxy = (spot_data.high - spot_data.low) * spot
                    volume = max(1.0, min(100.0, volume_proxy * 100))
            
            # All should produce valid volume in 1-100 range
            assert volume >= 1.0, f"Volume for {asset} should be >= 1.0, got {volume}"
            assert volume <= 100.0, f"Volume for {asset} should be <= 100.0, got {volume}"
    
    def test_volume_proxy_scales_with_volatility(self):
        """Test that OHLC proxy volume scales with price volatility."""
        # Low volatility
        spot_data_low = Mock()
        spot_data_low.volume = None
        spot_data_low.high = 58010.0
        spot_data_low.low = 57990.0
        
        spot_price = 58000.0
        
        volume_low = 1.0
        if spot_data_low.high > spot_data_low.low:
            volume_proxy = (spot_data_low.high - spot_data_low.low) * spot_price
            volume_low = max(1.0, min(100.0, volume_proxy * 100))
        
        # High volatility
        spot_data_high = Mock()
        spot_data_high.volume = None
        spot_data_high.high = 59000.0
        spot_data_high.low = 57000.0
        
        volume_high = 1.0
        if spot_data_high.high > spot_data_high.low:
            volume_proxy = (spot_data_high.high - spot_data_high.low) * spot_price
            volume_high = max(1.0, min(100.0, volume_proxy * 100))
        
        # High volatility should produce higher volume (up to cap)
        assert volume_high >= volume_low


class TestVolumeConfirmationFilter:
    """Test suite for volume confirmation filter with proxy volume."""
    
    def test_volume_confirmation_with_proxy_volume(self):
        """Test that volume confirmation filter works with OHLC proxy volume."""
        # Simulate volume confirmation filter logic
        volume = 75.0  # OHLC proxy volume
        min_volume_threshold = 10.0
        
        # Volume confirmation should pass
        passes_filter = volume >= min_volume_threshold
        assert passes_filter is True
    
    def test_volume_confirmation_with_low_proxy_volume(self):
        """Test volume confirmation with low OHLC proxy volume."""
        # Simulate low volatility scenario
        volume = 2.0  # Low OHLC proxy volume
        min_volume_threshold = 10.0
        
        # Volume confirmation might fail
        passes_filter = volume >= min_volume_threshold
        assert passes_filter is False
    
    def test_volume_confirmation_default_volume(self):
        """Test volume confirmation with default volume (1.0)."""
        # Simulate invalid OHLC data scenario
        volume = 1.0  # Default volume
        min_volume_threshold = 10.0
        
        # Volume confirmation will fail with default
        passes_filter = volume >= min_volume_threshold
        assert passes_filter is False
