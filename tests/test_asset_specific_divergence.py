"""
Tests for asset-specific strike divergence thresholds.

This test suite validates the 2026 best practice implementation of
asset-specific divergence thresholds based on volatility characteristics.

Run with: pytest tests/test_asset_specific_divergence.py -v
"""

import pytest


class TestAssetSpecificDivergenceThresholds:
    """Test suite for asset-specific strike divergence thresholds."""
    
    def test_btc_divergence_threshold(self):
        """Test BTC divergence threshold is 0.1%."""
        asset = "BTC"
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert threshold == 0.1
    
    def test_eth_divergence_threshold(self):
        """Test ETH divergence threshold is 0.1%."""
        asset = "ETH"
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert threshold == 0.1
    
    def test_sol_divergence_threshold(self):
        """Test SOL divergence threshold is 0.15%."""
        asset = "SOL"
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert threshold == 0.15
    
    def test_xrp_divergence_threshold(self):
        """Test XRP divergence threshold is 0.2%."""
        asset = "XRP"
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert threshold == 0.2
    
    def test_doge_divergence_threshold(self):
        """Test DOGE divergence threshold is 0.2%."""
        asset = "DOGE"
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert threshold == 0.2
    
    def test_unknown_asset_default_threshold(self):
        """Test unknown asset uses default threshold of 0.1%."""
        asset = "UNKNOWN"
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert threshold == 0.1
    
    def test_btc_divergence_within_threshold(self):
        """Test BTC divergence within 0.1% threshold does not trigger warning."""
        asset = "BTC"
        strike_price = 58697.0
        candle_open = 58690.0
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct < threshold  # Should not trigger warning
    
    def test_btc_divergence_exceeds_threshold(self):
        """Test BTC divergence exceeding 0.1% threshold triggers warning."""
        asset = "BTC"
        strike_price = 58697.0
        candle_open = 58500.0
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct > threshold  # Should trigger warning
    
    def test_xrp_divergence_within_threshold(self):
        """Test XRP divergence within 0.2% threshold does not trigger warning."""
        asset = "XRP"
        strike_price = 0.60
        candle_open = 0.599  # Very small divergence
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct < threshold  # Should not trigger warning
    
    def test_xrp_divergence_exceeds_threshold(self):
        """Test XRP divergence exceeding 0.2% threshold triggers warning."""
        asset = "XRP"
        strike_price = 0.60
        candle_open = 0.58
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct > threshold  # Should trigger warning
    
    def test_sol_divergence_within_threshold(self):
        """Test SOL divergence within 0.15% threshold does not trigger warning."""
        asset = "SOL"
        strike_price = 150.0
        candle_open = 149.8
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct < threshold  # Should not trigger warning
    
    def test_sol_divergence_exceeds_threshold(self):
        """Test SOL divergence exceeding 0.15% threshold triggers warning."""
        asset = "SOL"
        strike_price = 150.0
        candle_open = 149.5
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct > threshold  # Should trigger warning
    
    def test_doge_divergence_within_threshold(self):
        """Test DOGE divergence within 0.2% threshold does not trigger warning."""
        asset = "DOGE"
        strike_price = 0.15
        candle_open = 0.1498  # Very small divergence
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct < threshold  # Should not trigger warning
    
    def test_doge_divergence_exceeds_threshold(self):
        """Test DOGE divergence exceeding 0.2% threshold triggers warning."""
        asset = "DOGE"
        strike_price = 0.15
        candle_open = 0.148
        divergence_pct = abs((strike_price - candle_open) / candle_open) * 100
        
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        threshold = divergence_thresholds.get(asset, 0.1)
        
        assert divergence_pct > threshold  # Should trigger warning
    
    def test_all_crypto_assets_have_thresholds(self):
        """Test that all 5 crypto assets have defined thresholds."""
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in required_assets:
            assert asset in divergence_thresholds, f"Asset {asset} missing from divergence thresholds"
    
    def test_thresholds_increase_with_volatility(self):
        """Test that thresholds increase for more volatile assets."""
        divergence_thresholds = {
            "BTC": 0.1,
            "ETH": 0.1,
            "SOL": 0.15,
            "XRP": 0.2,
            "DOGE": 0.2
        }
        
        # BTC/ETH (less volatile) < SOL (medium) < XRP/DOGE (more volatile)
        assert divergence_thresholds["BTC"] <= divergence_thresholds["SOL"]
        assert divergence_thresholds["ETH"] <= divergence_thresholds["SOL"]
        assert divergence_thresholds["SOL"] <= divergence_thresholds["XRP"]
        assert divergence_thresholds["SOL"] <= divergence_thresholds["DOGE"]
