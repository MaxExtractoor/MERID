"""Unit tests for trailing stop functionality."""

import pytest
from unittest.mock import MagicMock, patch


class TestTrailingStop:
    """Test trailing stop configuration and logic."""
    
    def test_trailing_stop_config_from_profile(self):
        """Test that trailing stop configuration is read from profile."""
        # Mock profile with trailing stop enabled
        mock_profile = MagicMock()
        mock_profile.trailing_stop_enabled = True
        mock_profile.trailing_stop_trailing_distance_cents = 5
        mock_profile.trailing_stop_min_profit_cents = 12
        mock_profile.trailing_stop_activation_delay_sec = 30
        
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=mock_profile)):
            
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                assert profile.trailing_stop_enabled is True
                assert profile.trailing_stop_trailing_distance_cents == 5
                assert profile.trailing_stop_min_profit_cents == 12
                assert profile.trailing_stop_activation_delay_sec == 30
    
    def test_trailing_stop_config_defaults(self):
        """Test that trailing stop has sensible defaults when profile unavailable."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        
        profile = Crypto15mProfile(
            profile_name="test",
            profile_version="1.0",
            description="test",
            capital_usd=1000.0,
            min_notional_usd=0.35,
            min_contracts=1,
            fractional_contract_override_threshold=0.5,
            allow_fallback_trades=False,
            max_fallback_notional_usd=0.35,
            max_fallback_cycles=3,
            catalog_staleness_enforced=True,
            signal_mode="hybrid",
            price_based_buy_threshold=0.70,
            price_based_sell_threshold=0.90,
            # Add required fields with defaults
            momentum_fvg_rsi_long_min=55.0,
            momentum_fvg_rsi_short_max=45.0,
            momentum_fvg_min_macd_hist_long=0.0,
            momentum_fvg_min_macd_hist_short=0.0,
            momentum_fvg_obi_min=0.25,
            momentum_fvg_obi_persistence_min=0.6,
            momentum_fvg_obi_persistence_window_sec=10.0,
            momentum_fvg_obi_ewma_alpha=0.15,
            momentum_fvg_obi_strong_btc=0.55,
            momentum_fvg_obi_strong_eth=0.55,
            momentum_fvg_obi_strong_sol=0.45,
            momentum_fvg_obi_strong_xrp=0.45,
            momentum_fvg_obi_strong_doge=0.45,
            momentum_fvg_obi_ewma_alpha_btc=0.15,
            momentum_fvg_obi_ewma_alpha_eth=0.15,
            momentum_fvg_obi_ewma_alpha_sol=0.20,
            momentum_fvg_obi_ewma_alpha_xrp=0.20,
            momentum_fvg_obi_ewma_alpha_doge=0.20,
            momentum_fvg_fvg_max_age_bars=4,
            momentum_fvg_fvg_min_size_ticks=3,
            momentum_fvg_fvg_min_time_to_expiry_min=30.0,
            momentum_fvg_require_ema_stack=True,
            momentum_fvg_require_price_vs_ema50=True,
            momentum_fvg_liquidity_high_threshold=200,
            momentum_fvg_liquidity_high_size_factor=1.0,
            momentum_fvg_liquidity_medium_threshold=80,
            momentum_fvg_liquidity_medium_size_factor=0.75,
            momentum_fvg_liquidity_low_threshold=40,
            momentum_fvg_liquidity_low_size_factor=0.5,
            momentum_fvg_liquidity_ultra_low_threshold=25,
            momentum_fvg_liquidity_ultra_low_size_factor=0.25,
            momentum_fvg_liquidity_min_threshold=25,
            momentum_fvg_liquidity_min_size_factor=0.0,
            momentum_fvg_spread_gate_cents=40,
            momentum_fvg_spread_gate_obi_persistence_boost=0.75,
            max_cycle_risk_pct=0.10,
            max_cycle_risk_usd=0.0,
            venue_max_single_order_pct=0.05,
            venue_max_total_notional_pct=0.25,
            venue_max_category_notional_pct=0.10,
            venue_bankroll_cap_pct=0.02,
            venue_max_orders_per_minute=30,
            venue_max_orders_per_hour=300,
            agent_max_notional_pct=0.02,
            agent_max_orders_per_window=24,  # 2026-07-11: updated to 24 for 15m alignment
            agent_max_yes_position=3,
            agent_max_no_position=3,
            agent_max_concurrent_trades=5,
            agent_minutes_before_expiry=30,
            agent_cutoff_minutes_before_expiry=2,
            confidence_use_crypto_threshold_matrix=True,
            confidence_profile_name="modern_tradeable_kalshi_v1",
            confidence_kelly_multiplier_no_trade=0.0,
            confidence_kelly_multiplier_cautious=0.5,
            confidence_kelly_multiplier_quick_win=0.6,
            confidence_kelly_multiplier_confident=1.0,
            guardrails_max_spread_cents=30,
            guardrails_max_slippage_cents=3,
            guardrails_min_depth_contracts=5,
            guardrails_min_post_fee_edge=0.02,
            guardrails_min_time_to_expiry_min=2.5,
            guardrails_drawdown_halt_pct=0.10,
            guardrails_drawdown_unwind_pct=0.05,
            guardrails_max_daily_loss_usd=200.0,
            guardrails_max_position_value_usd=100000.0,
            guardrails_max_dist_pct_trade=2.0,
            guardrails_min_contract_price_cents=50,  # Updated 2026-07-03 to align with trade history analysis
            guardrails_max_contract_price_cents=70,  # 2026 research: 80% payout recommended
            guardrails_max_same_side_per_strip=2,
            guardrails_max_entry_mins=12.0,
            guardrails_min_entry_mins=2.0,
            guardrails_depth_size_multiplier=3.0,
            guardrails_regime_cooldown_enabled=False,
            guardrails_regime_cooldown_min_trades=20,
            guardrails_regime_cooldown_min_winrate=0.4,
            guardrails_regime_cooldown_max_loss_pct=0.1,
            guardrails_experimental_price_band_enabled=False,
            guardrails_experimental_min_price_cents=45,
            guardrails_experimental_max_price_cents=60,
            guardrails_experimental_tte_band_enabled=False,
            guardrails_experimental_min_tte_min=4.0,
            guardrails_experimental_max_tte_min=7.0,
            kelly_hard_cap=0.05,
            kelly_min_edge_pct=1.0,
            kelly_max_edge_pct=25.0,
            kelly_min_win_prob=0.01,
            kelly_max_win_prob=0.99,
            kelly_global_notional_cap_pct=0.05,
            contract_caps_max_contracts_total=5000,
            contract_caps_max_contracts_per_asset=1750,
            contract_caps_max_contracts_per_cluster=750,
            contract_caps_max_single_order_contracts=10,
            risk_policy_group_notional_cap_pct=0.05,
            risk_policy_group_notional_cap_min_usd=5.00,
            risk_policy_group_notional_cap_max_usd=2000.0,
            risk_policy_max_fee_to_notional_pct=15.0,
            strategy_policy_min_edge=0.05,
            strategy_policy_min_confidence=0.50,
            strategy_policy_max_md_staleness_sec=120.0,
            throttling_global_orders_window_sec=60.0,
            throttling_global_orders_limit=20,
            throttling_per_asset_cooldown_sec=10.0,
            throttling_per_strip_order_limit=1,
            throttling_per_strip_notional_usd=0.0,
            universe_min_volume=5,
            universe_min_open_interest=1,
            universe_max_spread_cents=30,
            failsafe_max_contracts_per_order=1,
            venue_invariants_valid_price_cents_min=20,
            venue_invariants_valid_price_cents_max=99,
            venue_invariants_deep_otm_threshold_cents=5,
            venue_invariants_deep_itm_threshold_cents=95,
            venue_invariants_ioc_auto_below_seconds=120,
            venue_invariants_max_book_staleness_ms=30000,
            legacy_disable_balance_calibration=True,
            legacy_disable_dynamic_contract_caps=True,
            legacy_disable_bankroll_category_limits=True,
            legacy_disable_bankroll_prediction_risk=True,
            legacy_disable_bankroll_guardrails=True,
            velocity_model_alpha_0_btc=0.0,
            velocity_model_alpha_1_btc=2.0,
            velocity_model_alpha_0_eth=0.0,
            velocity_model_alpha_1_eth=2.0,
            velocity_model_alpha_0_sol=0.0,
            velocity_model_alpha_1_sol=3.0,
            velocity_model_alpha_0_xrp=0.0,
            velocity_model_alpha_1_xrp=3.0,
            velocity_model_alpha_0_doge=0.0,
            velocity_model_alpha_1_doge=5.0,
            velocity_threshold_btc=0.004,
            velocity_threshold_eth=0.004,
            velocity_threshold_sol=0.006,
            velocity_threshold_xrp=0.006,
            velocity_threshold_doge=0.008,
            momentum_weights_windows=[10, 30, 60],
            momentum_weights_values=[0.2, 0.3, 0.5],
            logit_fusion_velocity_weight=0.7,
            logit_fusion_mean_reversion_weight=0.3,
            near_expiry_guard_sec=300,
            calibration_enabled=True,
            calibration_auto_fit=True,
            calibration_min_samples=50,
            calibration_max_samples=500,
            calibration_regularization=0.0001,
            calibration_fit_interval_hours=1,
            strategies={},
            asset_configs={},
        )
        
        # Check defaults
        assert profile.trailing_stop_enabled is False
        assert profile.trailing_stop_trailing_distance_cents == 5
        assert profile.trailing_stop_min_profit_cents == 12  # Updated from 3 to 12 (align with 2026 research)
        assert profile.trailing_stop_activation_delay_sec == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
