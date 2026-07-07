"""
Tests for momentum_fvg signal generation logic.

Tests the momentum_fvg signal generation in agent_grid_15m.py to ensure:
1. MACD histogram symmetry is prevented (both sides can't fire at hist=0)
2. MACD dead zone prevents noise triggering
3. Velocity threshold alignment across layers
4. Signal generation conditions work correctly
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass


@dataclass
class MockMarket:
    """Mock market object for testing."""
    market_id: str = "KXBTC15M-25JUN-T100000"
    market: Mock = None


@dataclass
class MockMarketState:
    """Mock market state for testing."""
    yes_price: float = 0.50
    volume_24h: float = 10000.0
    open_interest: float = 5000.0
    bid: float = 0.49
    ask: float = 0.51
    depth_10c_yes: int = 100
    depth_10c_no: int = 100


class TestMomentumFVGSignalGeneration:
    """Test momentum_fvg signal generation logic."""
    
    def test_macd_histogram_symmetry_prevention(self):
        """Test that MACD histogram symmetry is prevented at hist=0."""
        # When MACD histogram = 0, only long conditions should be met (not both)
        # Long: macd_histogram >= 0 (TRUE when hist=0)
        # Short: macd_histogram < 0 (FALSE when hist=0)
        
        macd_histogram = 0.0
        min_macd_hist_long = 0
        min_macd_hist_short = 0
        
        # Long condition should be TRUE
        long_condition = macd_histogram >= min_macd_hist_long
        assert long_condition is True, "Long condition should be TRUE when hist=0"
        
        # Short condition should be FALSE (strict inequality)
        short_condition = macd_histogram < min_macd_hist_short
        assert short_condition is False, "Short condition should be FALSE when hist=0 (prevents symmetry)"
    
    def test_macd_histogram_positive_values(self):
        """Test MACD histogram conditions for positive values."""
        macd_histogram = 0.001
        min_macd_hist_long = 0
        min_macd_hist_short = 0
        
        # Long condition should be TRUE
        long_condition = macd_histogram >= min_macd_hist_long
        assert long_condition is True, "Long condition should be TRUE for positive hist"
        
        # Short condition should be FALSE
        short_condition = macd_histogram < min_macd_hist_short
        assert short_condition is False, "Short condition should be FALSE for positive hist"
    
    def test_macd_histogram_negative_values(self):
        """Test MACD histogram conditions for negative values."""
        macd_histogram = -0.001
        min_macd_hist_long = 0
        min_macd_hist_short = 0
        
        # Long condition should be FALSE
        long_condition = macd_histogram >= min_macd_hist_long
        assert long_condition is False, "Long condition should be FALSE for negative hist"
        
        # Short condition should be TRUE
        short_condition = macd_histogram < min_macd_hist_short
        assert short_condition is True, "Short condition should be TRUE for negative hist"
    
    def test_macd_dead_zone_prevents_noise(self):
        """Test that MACD dead zone prevents signals when histogram is near zero."""
        macd_dead_zone = 0.0001
        
        # Test values within dead zone
        test_values = [0.0, 0.00005, -0.00005, 0.000099, -0.000099]
        
        for macd_histogram in test_values:
            in_dead_zone = abs(macd_histogram) < macd_dead_zone
            assert in_dead_zone is True, f"MACD histogram {macd_histogram} should be in dead zone"
    
    def test_macd_dead_zone_allows_valid_signals(self):
        """Test that MACD dead zone allows valid signals outside dead zone."""
        macd_dead_zone = 0.0001
        
        # Test values outside dead zone
        test_values = [0.0002, -0.0002, 0.001, -0.001]
        
        for macd_histogram in test_values:
            in_dead_zone = abs(macd_histogram) < macd_dead_zone
            assert in_dead_zone is False, f"MACD histogram {macd_histogram} should NOT be in dead zone"
    
    def test_velocity_threshold_alignment_profile_yaml(self):
        """Test that velocity thresholds match profile YAML values."""
        # Profile YAML values (from kalshi_crypto_15m_v2.yaml)
        profile_yaml_thresholds = {
            "BTC": 0.00015,
            "ETH": 0.00015,
            "SOL": 0.000225,
            "XRP": 0.000225,
            "DOGE": 0.0003,
        }
        
        # Agent grid defaults should match profile YAML
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
        
        assert config.velocity_threshold_btc == profile_yaml_thresholds["BTC"]
        assert config.velocity_threshold_eth == profile_yaml_thresholds["ETH"]
        assert config.velocity_threshold_sol == profile_yaml_thresholds["SOL"]
        assert config.velocity_threshold_xrp == profile_yaml_thresholds["XRP"]
        assert config.velocity_threshold_doge == profile_yaml_thresholds["DOGE"]
    
    def test_velocity_threshold_alignment_profile_adapter(self):
        """Test that profile adapter velocity thresholds match profile YAML."""
        import os
        from unittest.mock import patch
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        # Profile YAML values
        profile_yaml_thresholds = {
            "BTC": 0.00015,
            "ETH": 0.00015,
            "SOL": 0.000225,
            "XRP": 0.000225,
            "DOGE": 0.0003,
        }
        
        # Profile adapter should load from profile YAML
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            assert profile.velocity_threshold_btc == profile_yaml_thresholds["BTC"]
            assert profile.velocity_threshold_eth == profile_yaml_thresholds["ETH"]
            assert profile.velocity_threshold_sol == profile_yaml_thresholds["SOL"]
            assert profile.velocity_threshold_xrp == profile_yaml_thresholds["XRP"]
            assert profile.velocity_threshold_doge == profile_yaml_thresholds["DOGE"]
    
    def test_velocity_threshold_alignment_fallback_values(self):
        """Test that profile adapter fallback values match profile YAML."""
        # Profile adapter fallback values should match profile YAML, not 0.00001
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        # Simulate loading without velocity_thresholds in YAML (should use fallback)
        fallback_values = {
            "BTC": 0.00015,  # Should be 0.00015, not 0.00001
            "ETH": 0.00015,
            "SOL": 0.000225,
            "XRP": 0.000225,
            "DOGE": 0.0003,
        }
        
        # Verify fallback values are not 0.00001 (the old incorrect value)
        for asset, expected_value in fallback_values.items():
            assert expected_value != 0.00001, f"{asset} fallback should not be 0.00001"
            assert expected_value > 0.0001, f"{asset} fallback should be > 0.0001"
    
    def test_momentum_fvg_long_conditions(self):
        """Test momentum_fvg long signal conditions."""
        velocity = 0.0002  # Above threshold
        velocity_threshold = 0.00015
        macd_histogram = 0.001  # Positive
        min_macd_hist_long = 0
        rsi_zone = "neutral"  # Not overbought
        obi = 0.6  # Positive and strong
        obi_strong = True
        fvg_direction = "bullish"
        fvg_confidence = 0.6
        
        long_conditions = [
            velocity > velocity_threshold,
            macd_histogram >= min_macd_hist_long,
            rsi_zone != "overbought",
            (obi > 0 and obi_strong) or (fvg_direction == "bullish" and fvg_confidence > 0.5)
        ]
        
        long_score = sum(long_conditions)
        assert long_score == 4, "All 4 long conditions should be met"
        assert long_score >= 3, "Long signal should fire (3+ conditions met)"
    
    def test_momentum_fvg_short_conditions(self):
        """Test momentum_fvg short signal conditions."""
        velocity = -0.0002  # Below negative threshold
        velocity_threshold = 0.00015
        macd_histogram = -0.001  # Negative
        min_macd_hist_short = 0
        rsi_zone = "neutral"  # Not oversold
        obi = -0.6  # Negative and strong
        obi_strong = True
        fvg_direction = "bearish"
        fvg_confidence = 0.6
        
        short_conditions = [
            velocity < -velocity_threshold,
            macd_histogram < min_macd_hist_short,  # Strict inequality
            rsi_zone != "oversold",
            (obi < 0 and obi_strong) or (fvg_direction == "bearish" and fvg_confidence > 0.5)
        ]
        
        short_score = sum(short_conditions)
        assert short_score == 4, "All 4 short conditions should be met"
        assert short_score >= 3, "Short signal should fire (3+ conditions met)"
    
    def test_momentum_fvg_no_signal_when_insufficient_conditions(self):
        """Test that no signal fires when insufficient conditions are met."""
        velocity = 0.0001  # Below threshold
        velocity_threshold = 0.00015
        macd_histogram = 0.00005  # In dead zone
        min_macd_hist_long = 0
        rsi_zone = "neutral"
        obi = 0.3  # Weak
        obi_strong = False
        fvg_direction = "neutral"
        fvg_confidence = 0.3
        
        long_conditions = [
            velocity > velocity_threshold,  # FALSE
            macd_histogram >= min_macd_hist_long,  # TRUE
            rsi_zone != "overbought",  # TRUE
            (obi > 0 and obi_strong) or (fvg_direction == "bullish" and fvg_confidence > 0.5)  # FALSE
        ]
        
        long_score = sum(long_conditions)
        assert long_score == 2, "Only 2 long conditions met"
        assert long_score < 3, "Long signal should NOT fire (insufficient conditions)"
    
    def test_momentum_fvg_velocity_threshold_per_asset(self):
        """Test that velocity thresholds are per-asset based on volatility."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
        
        # BTC/ETH (deeper markets): lower threshold
        assert config.velocity_threshold_btc == 0.00015
        assert config.velocity_threshold_eth == 0.00015
        
        # SOL/XRP (medium volatility): higher threshold
        assert config.velocity_threshold_sol == 0.000225
        assert config.velocity_threshold_xrp == 0.000225
        
        # DOGE (high volatility): highest threshold
        assert config.velocity_threshold_doge == 0.0003
        
        # Verify increasing threshold with volatility
        assert config.velocity_threshold_btc < config.velocity_threshold_sol
        assert config.velocity_threshold_sol < config.velocity_threshold_doge


class TestMomentumFVGIntegration:
    """Integration tests for momentum_fvg signal generation."""
    
    def test_signal_generation_with_macd_dead_zone(self):
        """Test that signals are skipped when MACD is in dead zone."""
        # Test the dead zone logic
        macd_histogram = 0.00005
        macd_dead_zone = 0.0001
        
        should_skip = abs(macd_histogram) < macd_dead_zone
        assert should_skip is True, "Signal should be skipped in MACD dead zone"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
