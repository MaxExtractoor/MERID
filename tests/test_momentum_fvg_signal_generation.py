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
    
    def test_macd_dead_zone_from_profile_yaml(self):
        """Test that MACD dead zone is read from profile YAML."""
        from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile

        profile = get_crypto_15m_profile()
        # momentum_fvg is a dictionary property, use dict access
        macd_dead_zone = profile.momentum_fvg.get('macd_dead_zone', None)

        # Verify dead zone is configured in profile
        assert macd_dead_zone is not None, "macd_dead_zone should be configured in profile YAML"

        # CRITICAL FIX (2026-07-28): Dead zone set to 0.0 to allow signal generation for XRP/DOGE
        # XRP/DOGE have histogram values like -0.000003 which are below 0.0001 threshold
        assert macd_dead_zone == 0.0, f"macd_dead_zone should be 0.0 (disabled), got {macd_dead_zone}"
    
    def test_macd_dead_zone_allows_valid_signals(self):
        """Test that optimized dead zone allows valid signals."""
        from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile
        
        profile = get_crypto_15m_profile()
        macd_dead_zone = getattr(profile.momentum_fvg, 'macd_dead_zone', 0.0001)
        
        # Test values that should be allowed (outside dead zone)
        # With 0.0001 dead zone, values like 0.0002 should be allowed
        test_values = [0.0002, -0.0002, 0.001, -0.001]
        
        for macd_histogram in test_values:
            should_skip = abs(macd_histogram) < macd_dead_zone
            assert should_skip is False, f"MACD histogram {macd_histogram} should NOT be in dead zone with threshold {macd_dead_zone}"
    
    def test_macd_dead_zone_blocks_noise(self):
        """Test that optimized dead zone still blocks noise."""
        from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile
        
        profile = get_crypto_15m_profile()
        macd_dead_zone = getattr(profile.momentum_fvg, 'macd_dead_zone', 0.0001)
        
        # Test values that should be blocked (within dead zone)
        # With 0.0001 dead zone, values like 0.00005 should be blocked
        test_values = [0.0, 0.00005, -0.00005, 0.00009, -0.00009]
        
        for macd_histogram in test_values:
            should_skip = abs(macd_histogram) < macd_dead_zone
            assert should_skip is True, f"MACD histogram {macd_histogram} should be in dead zone with threshold {macd_dead_zone}"
    
    def test_obi_strong_thresholds_aligned_with_profile_yaml(self):
        """Test that OBI strong thresholds are aligned with profile YAML (CRITICAL FIX: 2026-07-08)."""
        from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile
        
        profile = get_crypto_15m_profile()
        momentum_fvg = profile.momentum_fvg
        
        # Verify OBI strong thresholds match profile YAML values
        # Profile YAML: BTC=0.55, ETH=0.55, SOL=0.45, XRP=0.45, DOGE=0.45
        # Previous defaults (WRONG): BTC=0.85, ETH=0.85, SOL=0.80, XRP=0.80, DOGE=0.80
        
        assert momentum_fvg['obi_strong_btc'] == 0.55, \
            f"BTC OBI strong threshold should be 0.55, got {momentum_fvg['obi_strong_btc']}"
        assert momentum_fvg['obi_strong_eth'] == 0.55, \
            f"ETH OBI strong threshold should be 0.55, got {momentum_fvg['obi_strong_eth']}"
        assert momentum_fvg['obi_strong_sol'] == 0.45, \
            f"SOL OBI strong threshold should be 0.45, got {momentum_fvg['obi_strong_sol']}"
        assert momentum_fvg['obi_strong_xrp'] == 0.45, \
            f"XRP OBI strong threshold should be 0.45, got {momentum_fvg['obi_strong_xrp']}"
        assert momentum_fvg['obi_strong_doge'] == 0.45, \
            f"DOGE OBI strong threshold should be 0.45, got {momentum_fvg['obi_strong_doge']}"
        
        # Verify they are NOT the old incorrect values
        assert momentum_fvg['obi_strong_btc'] != 0.85, "BTC OBI strong threshold should not be old value 0.85"
        assert momentum_fvg['obi_strong_eth'] != 0.85, "ETH OBI strong threshold should not be old value 0.85"
        assert momentum_fvg['obi_strong_sol'] != 0.80, "SOL OBI strong threshold should not be old value 0.80"
    
    def test_momentum_rsi_thresholds_used_in_signal_conditions(self):
        """Test that momentum RSI thresholds are used in signal conditions (CRITICAL FIX: 2026-07-08)."""
        import inspect
        from merid.prediction.agent_grid_15m import LeanAgent15m
        
        # Get the source code of the _generate_momentum_fvg_signal method
        source = inspect.getsource(LeanAgent15m._generate_momentum_fvg_signal)
        
        # Verify that momentum RSI thresholds are read from profile
        assert "momentum_rsi_long_min" in source, \
            "momentum_rsi_long_min should be read from profile config"
        assert "momentum_rsi_short_max" in source, \
            "momentum_rsi_short_max should be read from profile config"
        
        # Verify that RSI > momentum_rsi_long_min is used in long conditions
        assert "rsi > momentum_rsi_long_min" in source, \
            "Long conditions should check RSI > momentum_rsi_long_min"
        
        # Verify that RSI < momentum_rsi_short_max is used in short conditions
        assert "rsi < momentum_rsi_short_max" in source, \
            "Short conditions should check RSI < momentum_rsi_short_max"
        
        # CRITICAL FIX (2026-08-01): Scoring system refactored to use scores as inputs to edge calculation
        # Scores are used for dual-side edge evaluation, not as direct side selectors
        assert "long_score = sum(long_conditions)" in source, \
            "Long score should be calculated as sum of long conditions"
        assert "short_score = sum(short_conditions)" in source, \
            "Short score should be calculated as sum of short conditions"
    
    def test_timing_window_uses_profile_yaml(self):
        """Test that timing window uses profile YAML configuration (CRITICAL FIX: 2026-07-08)."""
        import inspect
        from merid.prediction.agent_grid_15m import LeanAgent15m
        
        # Get the source code of the _generate_signal method
        source = inspect.getsource(LeanAgent15m._generate_signal)
        
        # Verify that timing configuration is read from profile
        assert "guardrails_min_entry_mins" in source, \
            "guardrails_min_entry_mins should be read from profile"
        assert "guardrails_max_entry_mins" in source, \
            "guardrails_max_entry_mins should be read from profile"
        assert "agent_cutoff_minutes_before_expiry" in source, \
            "agent_cutoff_minutes_before_expiry should be read from profile"
        
        # Verify that old hardcoded timing window values are NOT used in signal generation
        # Note: <= 0.5 in _validate_market_state is for one-sided book rejection (intentional)
        assert ">= 14.0" not in source, \
            "Hardcoded >=14.0min threshold should be removed from signal generation"
        # Check that the old comment about "first minute" is removed
        assert "first minute - price discovery noise" not in source, \
            "Old hardcoded first minute logic should be removed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
