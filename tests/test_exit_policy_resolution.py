"""Tests for order_router.resolve_exit_policy (FIXED_CENTS mode).

INVARIANT MARKER: This test validates the "No Trade Without Exit" invariant by ensuring
exit policy resolution uses profile-based SL cents instead of hardcoded values.
"""

import pytest

# Test the actual resolve_exit_policy from order_router
from merid.event_venues.kalshi.order_router import resolve_exit_policy as router_resolve_exit_policy, StopLossMode


class TestOrderRouterExitPolicy:
    """Tests for order_router.resolve_exit_policy (FIXED_CENTS mode)."""
    
    def test_fixed_cents_mode_for_binary_options(self):
        """Verify resolve_exit_policy uses FIXED_CENTS mode for binary options.
        
        INVARIANT: SL cents must be loaded from profile config, not hardcoded.
        """
        # Load expected SL cents from profile
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile = get_active_profile().profile
            expected_sl_cents = profile.dynamic_risk_sl_cents_normal_vol
        except Exception:
            # Fallback if profile unavailable
            expected_sl_cents = 8  # Updated default from profile
        
        # Test with different regimes
        for regime in ["conservative", "normal", "aggressive"]:
            result = router_resolve_exit_policy(edge_result=None, asset="BTC", regime=regime)
            
            # Verify FIXED_CENTS mode is used
            assert result.sl_mode == StopLossMode.FIXED_CENTS, f"Expected FIXED_CENTS mode for regime={regime}, got {result.sl_mode}"
            
            # Verify sl_cents is loaded from profile (not hardcoded 5)
            assert result.sl_cents == expected_sl_cents, f"Expected sl_cents={expected_sl_cents} (from profile) for regime={regime}, got {result.sl_cents}"
            
            # Verify sl_r_multiple is still set for legacy compatibility
            assert result.sl_r_multiple == 0.5, f"Expected sl_r_multiple=0.5 for regime={regime}, got {result.sl_r_multiple}"
    
    def test_trailing_enabled_with_correct_params(self):
        """Verify trailing is enabled with correct parameters."""
        result = router_resolve_exit_policy(edge_result=None, asset="BTC", regime="normal")
        
        assert result.trailing_enabled is True
        assert result.trailing_activation_r == 0.8
        assert result.trailing_giveback_cents == 5  # 5 cent giveback
    
    def test_tp_r_multiple_by_regime(self):
        """Verify TP R-multiple varies by regime."""
        conservative = router_resolve_exit_policy(edge_result=None, asset="BTC", regime="conservative")
        normal = router_resolve_exit_policy(edge_result=None, asset="BTC", regime="normal")
        aggressive = router_resolve_exit_policy(edge_result=None, asset="BTC", regime="aggressive")
        
        # Conservative should have lower TP
        assert conservative.tp_r_multiple == 0.75
        # Normal should have baseline TP
        assert normal.tp_r_multiple == 1.0
        # Aggressive should have higher TP
        assert aggressive.tp_r_multiple == 1.2
    
    def test_asset_specific_adjustments(self):
        """Verify tier 2 assets (SOL, XRP, DOGE) have wider TP thresholds."""
        btc_result = router_resolve_exit_policy(edge_result=None, asset="BTC", regime="normal")
        sol_result = router_resolve_exit_policy(edge_result=None, asset="SOL", regime="normal")
        
        # SOL should have higher tp_min_cents
        assert sol_result.tp_min_cents >= btc_result.tp_min_cents


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
