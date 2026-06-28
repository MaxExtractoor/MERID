"""
Tests for momentum_fvg profile parameter loading.

Tests that the Kalshi-specific momentum_fvg parameters are correctly loaded
from the profile and can be accessed by the signal gate.
"""

import os
import pytest
from unittest.mock import patch

from merid.risk.profiles.crypto_15m_profile import (
    Crypto15mProfileAdapter,
    get_active_profile,
)


class TestMomentumFVGProfileParameters:
    """Test momentum_fvg parameter loading from profile."""
    
    def test_signal_mode_default_hybrid(self):
        """Test default signal_mode is 'hybrid'."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            assert profile.signal_mode == "hybrid"
    
    def test_momentum_fvg_rsi_thresholds(self):
        """Test momentum_fvg RSI thresholds are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            assert profile.momentum_fvg_rsi_long_min == 55.0
            assert profile.momentum_fvg_rsi_short_max == 45.0
    
    def test_momentum_fvg_obi_parameters(self):
        """Test momentum_fvg OBI parameters are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            assert profile.momentum_fvg_obi_min == 0.25
            assert profile.momentum_fvg_obi_persistence_min == 0.6
            assert profile.momentum_fvg_obi_persistence_window_sec == 10.0
            assert profile.momentum_fvg_obi_ewma_alpha == 0.15
    
    def test_momentum_fvg_per_asset_obi_strong(self):
        """Test per-asset OBI strong thresholds are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # BTC/ETH should have higher threshold (deeper books)
            assert profile.momentum_fvg_obi_strong_btc == 0.55
            assert profile.momentum_fvg_obi_strong_eth == 0.55
            
            # SOL/XRP/DOGE should have lower threshold (thinner books)
            assert profile.momentum_fvg_obi_strong_sol == 0.45
            assert profile.momentum_fvg_obi_strong_xrp == 0.45
            assert profile.momentum_fvg_obi_strong_doge == 0.45
    
    def test_momentum_fvg_per_asset_ewma_alpha(self):
        """Test per-asset EWMA alpha values are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # BTC/ETH should have lower alpha (smoother, more depth)
            assert profile.momentum_fvg_obi_ewma_alpha_btc == 0.15
            assert profile.momentum_fvg_obi_ewma_alpha_eth == 0.15
            
            # SOL/XRP/DOGE should have higher alpha (quicker reaction, less depth)
            assert profile.momentum_fvg_obi_ewma_alpha_sol == 0.20
            assert profile.momentum_fvg_obi_ewma_alpha_xrp == 0.20
            assert profile.momentum_fvg_obi_ewma_alpha_doge == 0.20
    
    def test_momentum_fvg_fvg_parameters(self):
        """Test momentum_fvg FVG parameters are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            assert profile.momentum_fvg_fvg_max_age_bars == 4
            assert profile.momentum_fvg_fvg_min_size_ticks == 3
            assert profile.momentum_fvg_fvg_min_time_to_expiry_min == 30.0
    
    def test_momentum_fvg_liquidity_tiers(self):
        """Test momentum_fvg liquidity tier parameters are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # High liquidity tier
            assert profile.momentum_fvg_liquidity_high_threshold == 200
            assert profile.momentum_fvg_liquidity_high_size_factor == 1.0
            
            # Medium liquidity tier
            assert profile.momentum_fvg_liquidity_medium_threshold == 80
            assert profile.momentum_fvg_liquidity_medium_size_factor == 0.75
            
            # Low liquidity tier
            assert profile.momentum_fvg_liquidity_low_threshold == 40
            assert profile.momentum_fvg_liquidity_low_size_factor == 0.5
            
            # Ultra-low liquidity tier
            assert profile.momentum_fvg_liquidity_ultra_low_threshold == 25
            assert profile.momentum_fvg_liquidity_ultra_low_size_factor == 0.25
            
            # Minimum threshold
            assert profile.momentum_fvg_liquidity_min_threshold == 25
            assert profile.momentum_fvg_liquidity_min_size_factor == 0.0
    
    def test_momentum_fvg_spread_gate_parameters(self):
        """Test momentum_fvg spread gate parameters are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            assert profile.momentum_fvg_spread_gate_cents == 40
            assert profile.momentum_fvg_spread_gate_obi_persistence_boost == 0.75
    
    def test_momentum_fvg_trend_confirmation_defaults(self):
        """Test momentum_fvg trend confirmation defaults are loaded correctly."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            assert profile.momentum_fvg_require_ema_stack is True
            assert profile.momentum_fvg_require_price_vs_ema50 is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
