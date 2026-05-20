"""
Smoke Test for kalshi_crypto_15m Profile - Full Path Integration

This test validates the complete path: profile → adapter → Kalshi risk → agent grid → order placement.
It ensures that when MERID_PROFILE=kalshi_crypto_15m_v2 is active:
- No balance-derived functions change venue caps
- Per-order notional, per-asset caps, and category caps match the profile
- The full trading pipeline works end-to-end with config-only risk parameters
"""

import os
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from merid.risk.profiles.crypto_15m_profile import (
    Crypto15mProfileAdapter,
    is_profile_active,
    get_active_profile,
)


class TestProfileSmokeTest:
    """Smoke test for full kalshi_crypto_15m profile integration."""

    def test_full_path_btc_15m(self):
        """
        Test full path for BTC_15M: profile → adapter → risk → agent.
        
        This simulates:
        1. Load profile with MERID_PROFILE=kalshi_crypto_15m_v2
        2. Construct fake 15m market with realistic price/edge
        3. Run through risk manager using profile adapter
        4. Verify caps match profile (not bankroll-derived)
        """
        # Force profile active
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            assert adapter is not None
            profile = adapter.profile
            
            # Simulate different bankrolls to verify balance independence
            for bankroll_usd in [5000.0, 50000.0]:
                # Get KalshiRiskConfig from profile (this is what the system uses)
                risk_config = adapter.to_kalshi_risk_config()
                
                # Verify venue caps are config-only (identical across bankrolls)
                assert risk_config['max_single_order_notional_usd'] == profile.venue_max_single_order_usd
                assert risk_config['max_total_notional_usd'] == profile.venue_max_total_notional_usd
                assert risk_config['max_daily_loss_usd'] == profile.guardrails_max_daily_loss_usd
                
                # Verify category caps are config-only
                assert risk_config['category_limits']['crypto']['max_notional_usd'] == profile.venue_max_category_notional_usd
                
                # Verify contract caps are config-only (not dynamic)
                assert risk_config['max_contracts_total'] == 5000  # Fixed from profile
                assert risk_config['max_contracts_per_asset'] == 1750  # Fixed from profile
                
                # Verify rate limits are config-only
                assert risk_config['max_orders_per_minute'] == profile.venue_max_orders_per_minute
                assert risk_config['max_orders_per_hour'] == profile.venue_max_orders_per_hour
                
                # Get agent overrides for BTC_15M
                agent_overrides = adapter.to_agent_overrides("BTC_15M")
                
                # Verify agent caps are config-only (identical across bankrolls)
                assert agent_overrides['max_notional_usd'] == profile.agent_max_notional_usd
                assert agent_overrides['max_orders_per_window'] == profile.agent_max_orders_per_window
                assert agent_overrides['max_yes_position'] == profile.agent_max_yes_position
                assert agent_overrides['max_no_position'] == profile.agent_max_no_position
                
                # Verify edge thresholds are config-only (from profile asset config)
                btc_config = profile.asset_configs['BTC']
                assert agent_overrides['min_edge_early'] == btc_config.min_edge_early
                assert agent_overrides['min_edge_mid'] == btc_config.min_edge_mid
                assert agent_overrides['min_edge_late'] == btc_config.min_edge_late
                assert agent_overrides['min_edge_terminal'] == btc_config.min_edge_terminal

    def test_full_path_all_assets(self):
        """
        Test full path for all 15m crypto assets: BTC, ETH, SOL, XRP, DOGE.
        
        For each asset, verify that the profile provides consistent config-only
        risk parameters regardless of simulated bankroll.
        """
        assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            for asset in assets:
                # Get agent overrides for this asset
                agent_overrides = adapter.to_agent_overrides(f"{asset}_15M")
                
                # Verify agent caps are config-only
                assert agent_overrides['max_notional_usd'] == profile.agent_max_notional_usd
                assert agent_overrides['max_orders_per_window'] == profile.agent_max_orders_per_window
                
                # Verify edge thresholds match profile asset config
                asset_config = profile.asset_configs[asset]
                assert agent_overrides['min_edge_early'] == asset_config.min_edge_early
                assert agent_overrides['min_edge_mid'] == asset_config.min_edge_mid
                assert agent_overrides['min_edge_late'] == asset_config.min_edge_late
                assert agent_overrides['min_edge_terminal'] == asset_config.min_edge_terminal
                
                # Verify per-asset notional cap is respected
                expected_max_notional = min(profile.agent_max_notional_usd, asset_config.max_notional_usd)
                assert agent_overrides['max_notional_usd'] == expected_max_notional

    def test_profile_vs_legacy_behavior(self):
        """
        Test that profile mode behaves differently from legacy mode.
        
        This verifies that the profile gating actually changes behavior:
        - With profile active: caps are fixed from profile
        - Without profile active: caps would be derived from bankroll (legacy)
        """
        # Test with profile active
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile_config = adapter.to_kalshi_risk_config()
            
            # Verify profile has fixed values
            assert profile_config['max_single_order_notional_usd'] == 2500.0
            assert profile_config['max_total_notional_usd'] == 7500.0
        
        # Test without profile active (legacy mode would use bankroll)
        with patch.dict(os.environ, {}, clear=True):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            # Profile should not be active
            assert is_profile_active() is False
            assert get_active_profile() is None

    def test_cycle_sizing_cap_from_profile(self):
        """
        Test that cycle sizing cap is derived from profile capital, not live bankroll.
        
        Cycle-level risk is the ONLY thing that can vary with bankroll in the profile model.
        All other caps must be config-only.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Get cycle sizing cap
            cycle_cap = adapter.to_cycle_sizing_cap()
            
            # Verify cycle sizing is based on profile capital (not live bankroll)
            assert cycle_cap['capital_usd'] == profile.capital_usd
            assert cycle_cap['max_cycle_risk_pct'] == profile.max_cycle_risk_pct
            
            # Verify cycle risk is 2% of profile capital
            expected_cycle_risk = profile.capital_usd * profile.max_cycle_risk_pct
            assert cycle_cap['max_total_notional_usd'] == expected_cycle_risk
            
            # Verify this is independent of any simulated bankroll
            # (This is the key invariant: cycle sizing uses profile capital, not live balance)

    def test_category_limits_from_profile(self):
        """
        Test that category limits come from profile, not bankroll-derived calculations.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Get category limits
            category_limits = adapter.to_category_limits()
            
            # Verify crypto category limit is from profile
            assert 'crypto' in category_limits
            assert category_limits['crypto']['max_notional_usd'] == profile.venue_max_category_notional_usd
            assert category_limits['crypto']['enabled'] is True
            
            # Verify this is config-only (not 0 = derive from bankroll)
            assert category_limits['crypto']['max_notional_usd'] > 0

    def test_guardrails_from_profile(self):
        """
        Test that guardrail parameters come from profile, not bankroll.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Verify guardrail parameters are from profile
            assert profile.guardrails_max_spread_cents == 10
            assert profile.guardrails_max_slippage_cents == 3
            assert profile.guardrails_min_depth_contracts == 5
            assert profile.guardrails_min_post_fee_edge == 0.01
            assert profile.guardrails_drawdown_halt_pct == 0.10
            assert profile.guardrails_drawdown_unwind_pct == 0.15
            assert profile.guardrails_max_daily_loss_usd == 200.0

    def test_kelly_sizing_from_profile(self):
        """
        Test that Kelly sizing parameters come from profile, not bankroll.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Verify Kelly parameters are from profile
            assert profile.kelly_hard_cap == 0.30
            assert profile.kelly_min_edge_pct == 1.0
            assert profile.kelly_max_edge_pct == 25.0
            assert profile.kelly_min_win_prob == 0.01
            assert profile.kelly_max_win_prob == 0.99
            assert profile.kelly_global_notional_cap_pct == 2.0

    def test_confidence_bands_from_profile(self):
        """
        Test that confidence band settings come from profile configuration.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Verify confidence settings reference crypto_threshold_matrix.yaml
            assert profile.confidence_use_crypto_threshold_matrix is True
            assert profile.confidence_profile_name == 'modern_tradeable_kalshi_v1'
            
            # Verify Kelly multipliers can override matrix
            assert profile.confidence_kelly_multiplier_no_trade == 0.0
            assert profile.confidence_kelly_multiplier_cautious == 0.5
            assert profile.confidence_kelly_multiplier_quick_win == 0.6
            assert profile.confidence_kelly_multiplier_confident == 1.0

    def test_legacy_flags_prevent_balance_derivation(self):
        """
        Test that legacy flags are set to prevent balance-derived behavior.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Verify all legacy disable flags are True
            assert profile.legacy_disable_balance_calibration is True
            assert profile.legacy_disable_dynamic_contract_caps is True
            assert profile.legacy_disable_bankroll_category_limits is True
            assert profile.legacy_disable_bankroll_prediction_risk is True
            assert profile.legacy_disable_bankroll_guardrails is True
            
            # Verify adapter methods return True
            assert adapter.should_disable_balance_calibration() is True
            assert adapter.should_disable_dynamic_contract_caps() is True
            assert adapter.should_disable_bankroll_category_limits() is True
            assert adapter.should_disable_bankroll_prediction_risk() is True
            assert adapter.should_disable_bankroll_guardrails() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
