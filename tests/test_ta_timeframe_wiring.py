"""
TA Timeframe Wiring Test Harness

Tests that TA timeframes are correctly wired for Kalshi 15-minute markets:
- 1-5 minute candles for primary entry signals
- 15-minute candles for trend confirmation
- Per-asset volatility tuning
- Timeframe alignment to market window

Usage:
    pytest tests/test_ta_timeframe_wiring.py
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

try:
    from merid.prediction.ta_timeframe_wiring import (
        TimeframeConfig,
        get_timeframe_config,
        validate_timeframe_alignment,
        TimeframeWiring,
        TimeframeData,
        CandleResolution,
        TimeframeType,
    )
except ImportError:
    pytest.skip("Required modules not available")


class TestTimeframeConfig:
    """Test suite for timeframe configurations."""
    
    def test_btc_timeframe_config(self):
        """Test BTC timeframe configuration."""
        config = get_timeframe_config("BTC")
        assert config is not None
        assert config.asset == "BTC"
        assert config.primary_resolution == CandleResolution.ONE_MINUTE
        assert config.confirmation_resolution == CandleResolution.FIFTEEN_MINUTE
        assert config.volatility_multiplier == 1.0
        assert config.min_velocity_threshold == 0.00005
    
    def test_eth_timeframe_config(self):
        """Test ETH timeframe configuration."""
        config = get_timeframe_config("ETH")
        assert config is not None
        assert config.asset == "ETH"
        assert config.primary_resolution == CandleResolution.ONE_MINUTE
        assert config.confirmation_resolution == CandleResolution.FIFTEEN_MINUTE
        assert config.volatility_multiplier == 1.2  # Higher than BTC
    
    def test_sol_timeframe_config(self):
        """Test SOL timeframe configuration."""
        config = get_timeframe_config("SOL")
        assert config is not None
        assert config.asset == "SOL"
        assert config.primary_resolution == CandleResolution.FIVE_MINUTE  # 5m for higher vol
        assert config.confirmation_resolution == CandleResolution.FIFTEEN_MINUTE
        assert config.volatility_multiplier == 1.5
    
    def test_xrp_timeframe_config(self):
        """Test XRP timeframe configuration."""
        config = get_timeframe_config("XRP")
        assert config is not None
        assert config.asset == "XRP"
        assert config.primary_resolution == CandleResolution.FIVE_MINUTE
        assert config.confirmation_resolution == CandleResolution.FIFTEEN_MINUTE
        assert config.volatility_multiplier == 1.3
    
    def test_doge_timeframe_config(self):
        """Test DOGE timeframe configuration."""
        config = get_timeframe_config("DOGE")
        assert config is not None
        assert config.asset == "DOGE"
        assert config.primary_resolution == CandleResolution.FIVE_MINUTE
        assert config.confirmation_resolution == CandleResolution.FIFTEEN_MINUTE
        assert config.volatility_multiplier == 1.8  # Highest volatility
    
    def test_unsupported_asset(self):
        """Test that unsupported asset returns None."""
        config = get_timeframe_config("INVALID")
        assert config is None
    
    def test_all_assets_covered(self):
        """Test that all 5 assets have configurations."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            config = get_timeframe_config(asset)
            assert config is not None, f"Asset {asset} should have config"


class TestTimeframeAlignment:
    """Test suite for timeframe alignment validation."""
    
    def test_1m_to_15m_alignment(self):
        """Test 1m primary to 15m confirmation alignment."""
        is_valid, error = validate_timeframe_alignment(
            primary_resolution=CandleResolution.ONE_MINUTE,
            confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
            market_window_minutes=15,
        )
        assert is_valid, f"1m to 15m should be valid: {error}"
    
    def test_5m_to_15m_alignment(self):
        """Test 5m primary to 15m confirmation alignment."""
        is_valid, error = validate_timeframe_alignment(
            primary_resolution=CandleResolution.FIVE_MINUTE,
            confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
            market_window_minutes=15,
        )
        assert is_valid, f"5m to 15m should be valid: {error}"
    
    def test_primary_exceeds_market_window(self):
        """Test that primary resolution exceeding market window fails."""
        is_valid, error = validate_timeframe_alignment(
            primary_resolution=CandleResolution.ONE_HOUR,
            confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
            market_window_minutes=15,
        )
        assert not is_valid, "Primary > market window should fail"
        assert "exceeds market window" in error.lower()
    
    def test_confirmation_not_equal_to_market_window(self):
        """Test that confirmation not equal to market window fails."""
        is_valid, error = validate_timeframe_alignment(
            primary_resolution=CandleResolution.ONE_MINUTE,
            confirmation_resolution=CandleResolution.ONE_HOUR,
            market_window_minutes=15,
        )
        assert not is_valid, "Confirmation != market window should fail"
        assert "must equal market window" in error.lower()
    
    def test_primary_does_not_divide_into_confirmation(self):
        """Test that primary not dividing into confirmation fails."""
        # Use a case where primary doesn't divide into confirmation
        # 5m does not divide into 17m evenly
        is_valid, error = validate_timeframe_alignment(
            primary_resolution=CandleResolution.FIVE_MINUTE,
            confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
            market_window_minutes=17,
        )
        assert not is_valid, "Primary not dividing into confirmation should fail"
        # Error could be about confirmation != market window or not dividing evenly
        assert "divide evenly" in error.lower() or "must equal market window" in error.lower()


class TestTimeframeWiring:
    """Test suite for timeframe wiring."""
    
    def test_get_primary_candles(self):
        """Test getting primary timeframe candles."""
        wiring = TimeframeWiring()
        
        # Add some 1m candles for BTC
        now = datetime.now(timezone.utc)
        for i in range(10):
            candle = TimeframeData(
                resolution=CandleResolution.ONE_MINUTE,
                open=50000.0 + i,
                high=50010.0 + i,
                low=49990.0 + i,
                close=50005.0 + i,
                volume=100.0,
                timestamp=now + timedelta(minutes=i),
            )
            wiring.add_candle_data("BTC", CandleResolution.ONE_MINUTE, candle)
        
        # Get primary candles
        candles = wiring.get_primary_candles("BTC", count=5)
        assert len(candles) == 5
        assert all(c.resolution == CandleResolution.ONE_MINUTE for c in candles)
    
    def test_get_confirmation_candles(self):
        """Test getting confirmation timeframe candles."""
        wiring = TimeframeWiring()
        
        # Add some 15m candles for BTC
        now = datetime.now(timezone.utc)
        for i in range(5):
            candle = TimeframeData(
                resolution=CandleResolution.FIFTEEN_MINUTE,
                open=50000.0 + i * 10,
                high=50020.0 + i * 10,
                low=49980.0 + i * 10,
                close=50010.0 + i * 10,
                volume=1000.0,
                timestamp=now + timedelta(minutes=i * 15),
            )
            wiring.add_candle_data("BTC", CandleResolution.FIFTEEN_MINUTE, candle)
        
        # Get confirmation candles
        candles = wiring.get_confirmation_candles("BTC", count=3)
        assert len(candles) == 3
        assert all(c.resolution == CandleResolution.FIFTEEN_MINUTE for c in candles)
    
    def test_validate_timeframe_consistency(self):
        """Test timeframe consistency validation."""
        wiring = TimeframeWiring()
        
        # Add data for BTC
        now = datetime.now(timezone.utc)
        
        # Add 1m candles
        for i in range(10):
            candle = TimeframeData(
                resolution=CandleResolution.ONE_MINUTE,
                open=50000.0 + i,
                high=50010.0 + i,
                low=49990.0 + i,
                close=50005.0 + i,
                volume=100.0,
                timestamp=now + timedelta(minutes=i),
            )
            wiring.add_candle_data("BTC", CandleResolution.ONE_MINUTE, candle)
        
        # Add 15m candles
        for i in range(5):
            candle = TimeframeData(
                resolution=CandleResolution.FIFTEEN_MINUTE,
                open=50000.0 + i * 10,
                high=50020.0 + i * 10,
                low=49980.0 + i * 10,
                close=50010.0 + i * 10,
                volume=1000.0,
                timestamp=now + timedelta(minutes=i * 15),
            )
            wiring.add_candle_data("BTC", CandleResolution.FIFTEEN_MINUTE, candle)
        
        # Validate consistency
        is_valid, error = wiring.validate_timeframe_consistency("BTC")
        assert is_valid, f"BTC should be consistent: {error}"
    
    def test_missing_primary_candles(self):
        """Test that missing primary candles fail validation."""
        wiring = TimeframeWiring()
        
        # Add only 15m candles (no primary)
        now = datetime.now(timezone.utc)
        for i in range(5):
            candle = TimeframeData(
                resolution=CandleResolution.FIFTEEN_MINUTE,
                open=50000.0 + i * 10,
                high=50020.0 + i * 10,
                low=49980.0 + i * 10,
                close=50010.0 + i * 10,
                volume=1000.0,
                timestamp=now + timedelta(minutes=i * 15),
            )
            wiring.add_candle_data("BTC", CandleResolution.FIFTEEN_MINUTE, candle)
        
        # Validate consistency
        is_valid, error = wiring.validate_timeframe_consistency("BTC")
        assert not is_valid, "Missing primary candles should fail"
        assert "No primary candles" in error
    
    def test_missing_confirmation_candles(self):
        """Test that missing confirmation candles fail validation."""
        wiring = TimeframeWiring()
        
        # Add only 1m candles (no confirmation)
        now = datetime.now(timezone.utc)
        for i in range(10):
            candle = TimeframeData(
                resolution=CandleResolution.ONE_MINUTE,
                open=50000.0 + i,
                high=50010.0 + i,
                low=49990.0 + i,
                close=50005.0 + i,
                volume=100.0,
                timestamp=now + timedelta(minutes=i),
            )
            wiring.add_candle_data("BTC", CandleResolution.ONE_MINUTE, candle)
        
        # Validate consistency
        is_valid, error = wiring.validate_timeframe_consistency("BTC")
        assert not is_valid, "Missing confirmation candles should fail"
        assert "No confirmation candles" in error
    
    def test_per_asset_resolution_selection(self):
        """Test that different assets use different primary resolutions."""
        wiring = TimeframeWiring()
        
        # BTC should use 1m
        btc_config = wiring.get_config("BTC")
        assert btc_config.primary_resolution == CandleResolution.ONE_MINUTE
        
        # SOL should use 5m
        sol_config = wiring.get_config("SOL")
        assert sol_config.primary_resolution == CandleResolution.FIVE_MINUTE
        
        # DOGE should use 5m
        doge_config = wiring.get_config("DOGE")
        assert doge_config.primary_resolution == CandleResolution.FIVE_MINUTE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
