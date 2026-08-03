"""Unit tests for agent grid configuration alignment with profile YAML."""

import pytest
from merid.prediction.agent_grid_15m import LeanAgentConfig


class TestAgentGridConfigAlignment:
    """Test that agent grid configuration is aligned with profile YAML single source of truth."""
    
    def test_velocity_thresholds_aligned_with_profile_yaml(self):
        """Test that velocity thresholds are aligned with profile YAML (per-asset values)."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify velocity thresholds match profile YAML values (2026-07-07 fix)
        assert config.velocity_threshold_btc == 0.00015, "BTC velocity threshold should be 0.00015 (0.015%)"
        assert config.velocity_threshold_eth == 0.00015, "ETH velocity threshold should be 0.00015 (0.015%)"
        assert config.velocity_threshold_sol == 0.000225, "SOL velocity threshold should be 0.000225 (0.0225%)"
        assert config.velocity_threshold_xrp == 0.000225, "XRP velocity threshold should be 0.000225 (0.0225%)"
        assert config.velocity_threshold_doge == 0.0003, "DOGE velocity threshold should be 0.0003 (0.03%)"
    
    def test_hybrid_mode_price_caps_aligned_with_profile_yaml(self):
        """Test that hybrid mode price caps are aligned with profile YAML (0.70/0.30)."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify price caps match profile YAML values
        assert config.max_entry_price_yes == 0.70, "max_entry_price_yes should be 0.70 (aligned with profile YAML)"
        assert config.min_entry_price_no == 0.30, "min_entry_price_no should be 0.30 (aligned with profile YAML)"
    
    def test_max_orders_per_15m_window_removed(self):
        """Test that max_orders_per_15m_window was removed (CRITICAL FIX 2026-07-17).
        
        CRITICAL FIX (2026-07-17): Removed per_strip_order_limit and max_orders_per_15m_window 
        - $1 exposure cap is now the limit
        - GlobalSlotAllocator enforces MAX_EXPOSURE_USD=1.00, MAX_CONTRACTS_PER_ORDER=1, MAX_POSITIONS_PER_ASSET=1
        """
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify max_orders_per_15m_window no longer exists (removed 2026-07-17)
        assert not hasattr(config, 'max_orders_per_15m_window'), "max_orders_per_15m_window should be removed (replaced by $1 exposure cap)"
    
    def test_per_asset_cooldown_aligned_with_profile_yaml(self):
        """Test that per_asset_cooldown_s is aligned with profile YAML (3 seconds)."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Verify cooldown matches profile YAML (2026-07-11: updated to 3s)
        assert config.per_asset_cooldown_s == 3, "per_asset_cooldown_s should be 3 (aligned with profile YAML)"
    
    def test_all_5_assets_have_per_asset_velocity_thresholds(self):
        """Test that all 5 crypto assets have appropriate per-asset velocity thresholds."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Assets should have per-asset thresholds based on volatility characteristics
        # BTC/ETH (deeper markets): 0.00015
        # SOL/XRP (medium volatility): 0.000225
        # DOGE (high volatility): 0.0003
        assert config.velocity_threshold_btc == 0.00015, "BTC should have 0.00015 threshold"
        assert config.velocity_threshold_eth == 0.00015, "ETH should have 0.00015 threshold"
        assert config.velocity_threshold_sol == 0.000225, "SOL should have 0.000225 threshold"
        assert config.velocity_threshold_xrp == 0.000225, "XRP should have 0.000225 threshold"
        assert config.velocity_threshold_doge == 0.0003, "DOGE should have 0.0003 threshold"
    
    def test_default_velocity_threshold_is_fallback(self):
        """Test that default velocity threshold is a fallback value."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Default threshold is a fallback, per-asset thresholds should be used
        assert config.velocity_threshold == 0.00001, "Default velocity_threshold is fallback (0.00001)"
        # But per-asset thresholds should be used in practice
        assert config.velocity_threshold_btc != config.velocity_threshold, "Per-asset threshold should differ from default"
