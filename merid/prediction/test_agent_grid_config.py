"""Unit tests for agent grid configuration alignment with profile YAML."""

import pytest
from merid.prediction.agent_grid_15m import LeanAgentConfig


class TestAgentGridConfigAlignment:
    """Test that agent grid configuration is aligned with profile YAML single source of truth."""
    
    def test_velocity_thresholds_aligned_with_profile_yaml(self):
        """Test that velocity thresholds are aligned with profile YAML (0.00001 for all assets)."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify all velocity thresholds are 0.00001 (0.001%) - aligned with profile YAML
        assert config.velocity_threshold_btc == 0.00001, "BTC velocity threshold should be 0.00001 (aligned with profile YAML)"
        assert config.velocity_threshold_eth == 0.00001, "ETH velocity threshold should be 0.00001 (aligned with profile YAML)"
        assert config.velocity_threshold_sol == 0.00001, "SOL velocity threshold should be 0.00001 (aligned with profile YAML)"
        assert config.velocity_threshold_xrp == 0.00001, "XRP velocity threshold should be 0.00001 (aligned with profile YAML)"
        assert config.velocity_threshold_doge == 0.00001, "DOGE velocity threshold should be 0.00001 (aligned with profile YAML)"
    
    def test_hybrid_mode_price_caps_aligned_with_profile_yaml(self):
        """Test that hybrid mode price caps are aligned with profile YAML (0.70/0.30)."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify price caps match profile YAML values
        assert config.max_entry_price_yes == 0.70, "max_entry_price_yes should be 0.70 (aligned with profile YAML)"
        assert config.min_entry_price_no == 0.30, "min_entry_price_no should be 0.30 (aligned with profile YAML)"
    
    def test_max_orders_per_15m_window_aligned_with_profile_yaml(self):
        """Test that max_orders_per_15m_window is aligned with profile YAML (12)."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify max orders per 15m window matches profile YAML
        assert config.max_orders_per_15m_window == 12, "max_orders_per_15m_window should be 12 (aligned with profile YAML)"
    
    def test_per_asset_cooldown_aligned_with_profile_yaml(self):
        """Test that per_asset_cooldown_s is aligned with profile YAML (8 seconds)."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify cooldown matches profile YAML
        assert config.per_asset_cooldown_s == 8, "per_asset_cooldown_s should be 8 (aligned with profile YAML)"
    
    def test_all_5_assets_have_consistent_velocity_thresholds(self):
        """Test that all 5 crypto assets have consistent velocity thresholds."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # All assets should have the same threshold (0.00001)
        thresholds = [
            config.velocity_threshold_btc,
            config.velocity_threshold_eth,
            config.velocity_threshold_sol,
            config.velocity_threshold_xrp,
            config.velocity_threshold_doge,
        ]
        
        assert all(t == 0.00001 for t in thresholds), "All assets should have velocity_threshold = 0.00001"
