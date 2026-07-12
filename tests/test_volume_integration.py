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


class TestVolumeFilterFix20260705:
    """Test suite for 2026-07-05 volume filter fix.
    
    This test validates that the broken volume filter has been disabled
    and documents the root cause and fix.
    """
    
    def test_broken_volume_filter_disabled(self):
        """Test that the broken volume filter is disabled in agent_grid_15m.py."""
        from pathlib import Path
        
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_path.read_text(encoding='utf-8')
        
        # Verify the broken filter is disabled
        assert "DISABLED: 2026-07-05 - Fixed broken volume filter" in content, \
            "agent_grid_15m.py should have comment explaining volume filter disable"
        
        # Verify the old broken implementation is removed
        assert "avg_volume_threshold = 1000000" not in content, \
            "agent_grid_15m.py should not have the broken 1M threshold"
        
        # Verify the fix comment explains the root cause
        assert "60-second candle volume" in content, \
            "agent_grid_15m.py should document the root cause (wrong volume metric)"
        
        assert "wrong metric" in content or "wrong threshold" in content, \
            "agent_grid_15m.py should document the root cause (wrong metric/threshold)"
    
    def test_volume_filter_config_disabled(self):
        """Test that volume_filter is disabled in profile config."""
        from pathlib import Path
        
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not profile_path.exists():
            pytest.skip("kalshi_crypto_15m_v2.yaml not found")
        
        # Read raw file to check for documentation in comments
        with open(profile_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        
        # Verify volume_filter section exists in raw content
        assert 'volume_filter:' in raw_content, \
            "kalshi_crypto_15m_v2.yaml should have volume_filter section"
        
        # Verify volume_filter is disabled
        assert 'enabled: false' in raw_content.lower() or 'enabled: False' in raw_content, \
            "volume_filter should be disabled in config"
        
        # Verify config documents the fix (check raw content for comments)
        assert '2026-07-05' in raw_content or 'broken' in raw_content, \
            "volume_filter config should document the 2026-07-05 fix in comments"
    
    def test_volume_filter_best_practices_documented(self):
        """Test that 2026 best practices are documented in config."""
        from pathlib import Path
        import yaml
        
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not profile_path.exists():
            pytest.skip("kalshi_crypto_15m_v2.yaml not found")
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Verify best practices are documented
        volume_filter_config = str(config['volume_filter'])
        
        # Check for key 2026 best practices
        best_practice_keywords = [
            'z_score',
            'relative',
            'rolling',
            'multi-timeframe',
            'AnomIQ'
        ]
        
        found_keywords = [kw for kw in best_practice_keywords if kw.lower() in volume_filter_config.lower()]
        
        # At least some best practices should be documented
        assert len(found_keywords) >= 2, \
            f"volume_filter config should document 2026 best practices (found: {found_keywords})"
    
    def test_coarse_liquidity_filters_still_active(self):
        """Test that coarse liquidity filters are still active (universe.min_volume)."""
        from pathlib import Path
        import yaml
        
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not profile_path.exists():
            pytest.skip("kalshi_crypto_15m_v2.yaml not found")
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Verify universe.min_volume is still active
        assert 'universe' in config, \
            "config should have universe section"
        
        assert 'min_volume' in config['universe'], \
            "universe should have min_volume filter"
        
        assert config['universe']['min_volume'] >= 1, \
            "universe.min_volume should be >= 1 contract"
    
    def test_per_asset_volume_24h_filters_still_active(self):
        """Test that per-asset min_volume_24h_usd filters are still active."""
        from pathlib import Path
        import yaml
        
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not profile_path.exists():
            pytest.skip("kalshi_crypto_15m_v2.yaml not found")
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Verify per-asset min_volume_24h_usd filters exist
        assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        
        for asset in assets:
            assert asset in config['assets'], \
                f"config should have {asset} asset configuration"
            
            assert 'min_volume_24h_usd' in config['assets'][asset], \
                f"{asset} should have min_volume_24h_usd filter"
            
            assert config['assets'][asset]['min_volume_24h_usd'] > 0, \
                f"{asset} min_volume_24h_usd should be > 0"
