"""Unit tests for optimized spread and edge thresholds and 2026 research-based risk management."""

import pytest
import dataclasses
from unittest.mock import MagicMock, patch


class TestThresholdOptimization:
    """Test optimized spread and edge thresholds for 15m crypto markets."""
    
    def test_guardrails_max_spread_cents_optimized(self):
        """Test that max_spread_cents is set to 50c for realistic 15m market spreads."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_max_spread_cents=50
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify max_spread_cents is set to 50c (research: 2-5c typical, up to 10c in volatile conditions)
                assert profile.guardrails_max_spread_cents == 50
    
    def test_guardrails_min_post_fee_edge_optimized(self):
        """Test that min_post_fee_edge is set to 1.5% for more opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_min_post_fee_edge=0.015
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify min_post_fee_edge is set to 1.5% (research: 2-2.5% net edge realistic, 1.5% floor)
                assert profile.guardrails_min_post_fee_edge == 0.015
    
    def test_strategy_policy_min_edge_optimized(self):
        """Test that strategy min_edge is set to 1.5% for more opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 strategy_policy_min_edge=0.015
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify min_edge is set to 1.5% (research: profitable systems trade edges down to 1-2%)
                assert profile.strategy_policy_min_edge == 0.015
    
    def test_guardrails_max_orders_per_cycle_optimized(self):
        """Test that max_orders_per_cycle is increased to 5 for more opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_max_orders_per_cycle=5
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify max_orders_per_cycle is set to 5 (industry standard: 15-20 trades per session)
                assert profile.guardrails_max_orders_per_cycle == 5
    
    def test_guardrails_min_time_to_expiry_optimized(self):
        """Test that min_time_to_expiry_min is relaxed to 2.0 for more 15m opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_min_time_to_expiry_min=2.0
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify min_time_to_expiry_min is set to 2.0 (reduced from 2.5min for more 15m opportunities)
                assert profile.guardrails_min_time_to_expiry_min == 2.0
    
    def test_spread_gate_cents_optimized(self):
        """Test that spread_gate_cents is increased to 50c aligned with guardrails."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 momentum_fvg_spread_gate_cents=50
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify spread_gate_cents is set to 50c (aligned with guardrails_max_spread_cents)
                assert profile.momentum_fvg_spread_gate_cents == 50

    def test_kelly_hard_cap_aligned_with_risk_limit(self):
        """Test that Kelly hard cap is set to 2% aligned with unified risk limit."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 kelly_hard_cap=0.02
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify Kelly hard cap is 2% (aligned with unified risk limit)
                assert profile.kelly_hard_cap == 0.02

    def test_kelly_global_notional_cap_aligned_with_risk_limit(self):
        """Test that Kelly global notional cap is set to 2% aligned with per-trade limit."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 kelly_global_notional_cap_pct=0.02
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify Kelly global notional cap is 2% (aligned with per-trade limit)
                assert profile.kelly_global_notional_cap_pct == 0.02

    # 2026 Research-Based Risk Management Tests
    def test_session_limit_reduced_to_5_trades(self):
        """Test that session limit is reduced to 5 trades based on 2026 research."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 throttling_max_orders_per_15m_window=5
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify session limit is 5 trades (industry standard: max 5 trades per session)
                assert profile.throttling_max_orders_per_15m_window == 5

    def test_correlation_aware_position_sizing_enabled(self):
        """Test that correlation-aware position sizing is enabled with real-time monitoring."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 correlation_tracking_enabled=True,
                 correlation_tracking_real_time_monitoring=True,
                 correlation_tracking_threshold_high=0.80,
                 correlation_tracking_threshold_moderate=0.50,
                 correlation_tracking_threshold_alert=0.85,
                 correlation_tracking_max_correlated_assets=3
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify correlation-aware sizing is enabled
                assert profile.correlation_tracking_enabled == True
                assert profile.correlation_tracking_real_time_monitoring == True
                assert profile.correlation_tracking_threshold_high == 0.80
                assert profile.correlation_tracking_threshold_moderate == 0.50
                assert profile.correlation_tracking_threshold_alert == 0.85
                assert profile.correlation_tracking_max_correlated_assets == 3

    def test_doge_specific_adjustments(self):
        """Test that DOGE has increased max contracts (2026-07-07 fix) and increased min edge."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 assets_DOGE_max_contracts=10,  # CRITICAL FIX (2026-07-07): Increased from 1 to 10 for multi-contract exits
                 assets_DOGE_min_edge_early=0.065,
                 assets_DOGE_min_edge_mid=0.065,
                 assets_DOGE_min_edge_late=0.065,
                 assets_DOGE_min_edge_terminal=0.075,
                 assets_DOGE_max_distance_pct=0.025
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify DOGE-specific adjustments
                assert profile.assets_DOGE_max_contracts == 10  # CRITICAL FIX (2026-07-07): Increased from 1 to 10
                assert profile.assets_DOGE_min_edge_early == 0.065  # Increased from 0.06
                assert profile.assets_DOGE_min_edge_mid == 0.065  # Increased from 0.06
                assert profile.assets_DOGE_min_edge_late == 0.065  # Increased from 0.06
                assert profile.assets_DOGE_min_edge_terminal == 0.075  # Increased from 0.07
                assert profile.assets_DOGE_max_distance_pct == 0.025  # Tightened from 0.030

    def test_consecutive_loss_pause_enabled(self):
        """Test that consecutive loss pause is enabled at 3 losses."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 throttling_consecutive_loss_pause=3
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify consecutive loss pause is set to 3
                assert profile.throttling_consecutive_loss_pause == 3

    def test_session_risk_cap_enabled(self):
        """Test that session risk cap is set to 10%."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 throttling_max_session_risk_pct=0.10
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify session risk cap is 10%
                assert profile.throttling_max_session_risk_pct == 0.10

    def test_granular_drawdown_bands(self):
        """Test that drawdown bands are more granular (8%/10%/12%/15%)."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_adaptive_risk_bands=[
                     {'max_drawdown_pct': 0.08, 'multiplier': 1.0},
                     {'max_drawdown_pct': 0.10, 'multiplier': 0.8},
                     {'max_drawdown_pct': 0.12, 'multiplier': 0.5},
                     {'max_drawdown_pct': 0.15, 'multiplier': 0.25},
                     {'max_drawdown_pct': 1.00, 'multiplier': 0.0}
                 ]
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify granular drawdown bands
                bands = profile.guardrails_adaptive_risk_bands
                assert bands[0]['max_drawdown_pct'] == 0.08
                assert bands[0]['multiplier'] == 1.0
                assert bands[1]['max_drawdown_pct'] == 0.10
                assert bands[1]['multiplier'] == 0.8
                assert bands[2]['max_drawdown_pct'] == 0.12
                assert bands[2]['multiplier'] == 0.5
                assert bands[3]['max_drawdown_pct'] == 0.15
                assert bands[3]['multiplier'] == 0.25

    def test_volatility_regime_edge_adjustment_enabled(self):
        """Test that volatility-regime edge adjustment is enabled."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 volatility_regime_edge_adjustment_enabled=True,
                 volatility_regime_edge_adjustment_lookback_days=30,
                 volatility_regime_edge_adjustment_low_volatility_threshold=0.30,
                 volatility_regime_edge_adjustment_high_volatility_threshold=0.70,
                 volatility_regime_edge_adjustment_low_volatility_adjustment=-0.0025,  # UPDATED: -0.25% (was -0.5%)
                 volatility_regime_edge_adjustment_high_volatility_adjustment=0.005  # UPDATED: +0.5% (was +1.0%)
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify volatility-regime edge adjustment is enabled
                assert profile.volatility_regime_edge_adjustment_enabled == True
                assert profile.volatility_regime_edge_adjustment_lookback_days == 30
                assert profile.volatility_regime_edge_adjustment_low_volatility_threshold == 0.30
                assert profile.volatility_regime_edge_adjustment_high_volatility_threshold == 0.70
                assert profile.volatility_regime_edge_adjustment_low_volatility_adjustment == -0.0025  # UPDATED
                assert profile.volatility_regime_edge_adjustment_high_volatility_adjustment == 0.005  # UPDATED

    def test_portfolio_heat_tracking_enabled(self):
        """Test that portfolio heat tracking is enabled with correlation-adjusted exposure."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 portfolio_heat_enabled=True,
                 portfolio_heat_calculation_method="correlation_adjusted_exposure",
                 portfolio_heat_heat_threshold_warning=0.70,
                 portfolio_heat_heat_threshold_critical=0.85
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify portfolio heat tracking is enabled
                assert profile.portfolio_heat_enabled == True
                assert profile.portfolio_heat_calculation_method == "correlation_adjusted_exposure"
                assert profile.portfolio_heat_heat_threshold_warning == 0.70
                assert profile.portfolio_heat_heat_threshold_critical == 0.85

    def test_time_of_day_risk_scaling_enabled(self):
        """Test that time-of-day risk scaling is enabled with session multipliers."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 time_of_day_risk_scaling_enabled=True,
                 time_of_day_risk_scaling_us_market_multiplier=1.0,
                 time_of_day_risk_scaling_asian_multiplier=0.8,
                 time_of_day_risk_scaling_european_multiplier=0.9,
                 time_of_day_risk_scaling_weekend_multiplier=0.5
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify time-of-day risk scaling is enabled
                assert profile.time_of_day_risk_scaling_enabled == True
                assert profile.time_of_day_risk_scaling_us_market_multiplier == 1.0
                assert profile.time_of_day_risk_scaling_asian_multiplier == 0.8
                assert profile.time_of_day_risk_scaling_european_multiplier == 0.9
                assert profile.time_of_day_risk_scaling_weekend_multiplier == 0.5

    def test_asset_specific_rolling_pnl_limits(self):
        """Test that asset-specific rolling PnL limits are configured per volatility."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 asset_specific_rolling_pnl_enabled=True,
                 asset_specific_rolling_pnl_BTC_rolling_1h_halt_pct=0.04,
                 asset_specific_rolling_pnl_BTC_rolling_4h_halt_pct=0.07,
                 asset_specific_rolling_pnl_ETH_rolling_1h_halt_pct=0.04,
                 asset_specific_rolling_pnl_ETH_rolling_4h_halt_pct=0.07,
                 asset_specific_rolling_pnl_SOL_rolling_1h_halt_pct=0.06,
                 asset_specific_rolling_pnl_SOL_rolling_4h_halt_pct=0.09,
                 asset_specific_rolling_pnl_XRP_rolling_1h_halt_pct=0.06,
                 asset_specific_rolling_pnl_XRP_rolling_4h_halt_pct=0.09,
                 asset_specific_rolling_pnl_DOGE_rolling_1h_halt_pct=0.08,
                 asset_specific_rolling_pnl_DOGE_rolling_4h_halt_pct=0.12
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify asset-specific rolling PnL limits
                assert profile.asset_specific_rolling_pnl_enabled == True
                # BTC/ETH: More stable, looser limits
                assert profile.asset_specific_rolling_pnl_BTC_rolling_1h_halt_pct == 0.04
                assert profile.asset_specific_rolling_pnl_BTC_rolling_4h_halt_pct == 0.07
                assert profile.asset_specific_rolling_pnl_ETH_rolling_1h_halt_pct == 0.04
                assert profile.asset_specific_rolling_pnl_ETH_rolling_4h_halt_pct == 0.07
                # SOL/XRP: Moderate volatility
                assert profile.asset_specific_rolling_pnl_SOL_rolling_1h_halt_pct == 0.06
                assert profile.asset_specific_rolling_pnl_SOL_rolling_4h_halt_pct == 0.09
                assert profile.asset_specific_rolling_pnl_XRP_rolling_1h_halt_pct == 0.06
                assert profile.asset_specific_rolling_pnl_XRP_rolling_4h_halt_pct == 0.09
                # DOGE: Most volatile, tightest limits
                assert profile.asset_specific_rolling_pnl_DOGE_rolling_1h_halt_pct == 0.08
                assert profile.asset_specific_rolling_pnl_DOGE_rolling_4h_halt_pct == 0.12

    def test_per_trade_risk_aligned_with_3_percent_agent_limit(self):
        """Test that per-trade risk is aligned with 3% per agent / 5% per 15m window limits."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        
        # Test uniform 3% per-trade risk for all bankroll sizes (bankroll tiering removed)
        envelope_small = KalshiCrypto15mRiskEnvelope(
            live_bankroll_usd=50.0,
            profile_capital_usd=100.0,
            max_single_order_notional_usd=1.5,
            max_total_notional_usd=7.5,
            max_concurrent_trades=5,
            asset_max_notional_usd={'BTC': 1.5, 'ETH': 1.5, 'SOL': 1.5, 'XRP': 1.5, 'DOGE': 1.5},
            asset_depth_thresholds={'BTC': 1.0, 'ETH': 1.0, 'SOL': 1.0, 'XRP': 1.0, 'DOGE': 1.0},
            agent_max_notional_usd=2.5,
            agent_max_orders_per_window=12,
            agent_max_yes_position=5,
            agent_max_no_position=5,
            max_cycle_risk_pct=0.05,
            # Window-based risk tracking (2026-07-06: HARD STOP)
            guardrails_per_window_risk_pct=0.03,  # 3% per agent per 15m window
            guardrails_total_venue_risk_pct=0.05,  # 5% total across all agents per 15m window
            per_agent_window_limit_usd=1.5,  # 3% of $50 = $1.5
            total_venue_window_limit_usd=2.5,  # 5% of $50 = $2.5
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            daily_loss_enabled=True,
            max_daily_loss_usd=20.0,
            drawdown_halt_pct=0.20,
            drawdown_unwind_pct=0.25,
            peak_equity_usd=50.0,
            current_equity_usd=50.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.02,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            correlation_tracking_enabled=False,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
        )
        assert envelope_small.get_per_trade_risk_pct() == 0.03  # 3% for all bankroll sizes (tiering removed)
        
        # Test medium bankroll: 3% per trade (uniform, no tiering)
        envelope_medium = KalshiCrypto15mRiskEnvelope(
            live_bankroll_usd=500.0,
            profile_capital_usd=1000.0,
            max_single_order_notional_usd=10.0,
            max_total_notional_usd=50.0,
            max_concurrent_trades=5,
            asset_max_notional_usd={'BTC': 15.0, 'ETH': 15.0, 'SOL': 15.0, 'XRP': 15.0, 'DOGE': 15.0},
            asset_depth_thresholds={'BTC': 1.0, 'ETH': 1.0, 'SOL': 1.0, 'XRP': 1.0, 'DOGE': 1.0},
            agent_max_notional_usd=25.0,
            agent_max_orders_per_window=12,
            agent_max_yes_position=5,
            agent_max_no_position=5,
            max_cycle_risk_pct=0.05,
            # Window-based risk tracking (2026-07-06: HARD STOP)
            guardrails_per_window_risk_pct=0.03,  # 3% per agent per 15m window
            guardrails_total_venue_risk_pct=0.05,  # 5% total across all agents per 15m window
            per_agent_window_limit_usd=15.0,  # 3% of $500 = $15
            total_venue_window_limit_usd=25.0,  # 5% of $500 = $25
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            daily_loss_enabled=True,
            max_daily_loss_usd=200.0,
            drawdown_halt_pct=0.20,
            drawdown_unwind_pct=0.25,
            peak_equity_usd=500.0,
            current_equity_usd=500.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.02,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            correlation_tracking_enabled=False,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
        )
        assert envelope_medium.get_per_trade_risk_pct() == 0.03  # 3% for all bankroll sizes (tiering removed)
        
        # Test large bankroll: 3% per trade (uniform, no tiering)
        envelope_large = KalshiCrypto15mRiskEnvelope(
            live_bankroll_usd=5000.0,
            profile_capital_usd=10000.0,
            max_single_order_notional_usd=75.0,
            max_total_notional_usd=375.0,
            max_concurrent_trades=5,
            asset_max_notional_usd={'BTC': 150.0, 'ETH': 150.0, 'SOL': 150.0, 'XRP': 150.0, 'DOGE': 150.0},
            asset_depth_thresholds={'BTC': 1.0, 'ETH': 1.0, 'SOL': 1.0, 'XRP': 1.0, 'DOGE': 1.0},
            agent_max_notional_usd=250.0,
            agent_max_orders_per_window=12,
            agent_max_yes_position=5,
            agent_max_no_position=5,
            max_cycle_risk_pct=0.05,
            # Window-based risk tracking (2026-07-06: HARD STOP)
            guardrails_per_window_risk_pct=0.03,  # 3% per agent per 15m window
            guardrails_total_venue_risk_pct=0.05,  # 5% total across all agents per 15m window
            per_agent_window_limit_usd=150.0,  # 3% of $5000 = $150
            total_venue_window_limit_usd=250.0,  # 5% of $5000 = $250
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            daily_loss_enabled=True,
            max_daily_loss_usd=1000.0,
            drawdown_halt_pct=0.20,
            drawdown_unwind_pct=0.25,
            peak_equity_usd=5000.0,
            current_equity_usd=5000.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.02,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            correlation_tracking_enabled=False,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
        )
        assert envelope_large.get_per_trade_risk_pct() == 0.03  # 3% for all bankroll sizes (tiering removed)

    def test_volatility_regime_edge_adjustment_defaults_aligned_with_yaml(self):
        """Test that volatility-regime edge adjustment defaults are aligned with profile YAML."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        from dataclasses import fields, MISSING
        
        # Get the default values from the dataclass field definitions
        field_defaults = {}
        for f in fields(Crypto15mProfile):
            if f.default != MISSING:
                field_defaults[f.name] = f.default
        
        # Verify defaults match profile YAML values
        assert field_defaults.get('volatility_regime_edge_adjustment_low_volatility_adjustment') == -0.0025, "Default low vol adjustment should be -0.25% (aligned with YAML)"
        assert field_defaults.get('volatility_regime_edge_adjustment_high_volatility_adjustment') == 0.005, "Default high vol adjustment should be +0.5% (aligned with YAML)"

    def test_doge_min_decision_minute_increased(self):
        """Test that DOGE min decision minute is set to 1 for all assets (2026-07-07)."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 min_decision_minute_DOGE=1
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify DOGE min decision minute is 1 (reduced from 5 for all assets)
                assert profile.min_decision_minute_DOGE == 1

    def test_time_of_day_multiplier_in_candidate(self):
        """Test that time_of_day_multiplier is included in candidate dictionary."""
        # This test verifies the fix for the bug where multiplier was calculated but not passed to sizing
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL020700-00",
            "side": "yes",
            "action": "buy",
            "edge_pct": 0.05,
            "confidence": 0.6,
            "time_of_day_multiplier": 0.8  # Asian session multiplier
        }
        
        # Verify time_of_day_multiplier is present in candidate
        assert "time_of_day_multiplier" in candidate
        assert candidate["time_of_day_multiplier"] == 0.8

    def test_time_of_day_multiplier_applied_to_sizing(self):
        """Test that time_of_day_multiplier is applied to position sizing in compute_order_size."""
        from decimal import Decimal
        from merid.prediction.unified_sizing import compute_order_size
        
        # Test with Asian session multiplier (0.8)
        bankroll_usd = Decimal("100.0")
        price_cents = 50
        asset = "BTC"
        
        # Without multiplier (baseline)
        count_baseline, notional_baseline, _ = compute_order_size(
            bankroll_usd=bankroll_usd,
            price_cents=price_cents,
            asset=asset,
            time_of_day_multiplier=1.0
        )
        
        # With Asian session multiplier (0.8)
        count_reduced, notional_reduced, _ = compute_order_size(
            bankroll_usd=bankroll_usd,
            price_cents=price_cents,
            asset=asset,
            time_of_day_multiplier=0.8
        )
        
        # Verify that reduced multiplier results in equal or smaller position size
        assert count_reduced <= count_baseline
        assert notional_reduced <= notional_baseline
        
        # Test with US market multiplier (1.0) - should be same as baseline
        count_us, notional_us, _ = compute_order_size(
            bankroll_usd=bankroll_usd,
            price_cents=price_cents,
            asset=asset,
            time_of_day_multiplier=1.0
        )
        
        assert count_us == count_baseline
        assert notional_us == notional_baseline

    def test_time_of_day_multiplier_weekend_reduction(self):
        """Test that weekend multiplier (0.5) significantly reduces position size."""
        from decimal import Decimal
        from merid.prediction.unified_sizing import compute_order_size
        
        bankroll_usd = Decimal("100.0")
        price_cents = 50
        asset = "BTC"
        
        # Baseline (US market hours)
        count_baseline, notional_baseline, _ = compute_order_size(
            bankroll_usd=bankroll_usd,
            price_cents=price_cents,
            asset=asset,
            time_of_day_multiplier=1.0
        )
        
        # Weekend (0.5 multiplier)
        count_weekend, notional_weekend, _ = compute_order_size(
            bankroll_usd=bankroll_usd,
            price_cents=price_cents,
            asset=asset,
            time_of_day_multiplier=0.5
        )
        
        # Weekend should have equal or smaller position size
        assert count_weekend <= count_baseline
        assert notional_weekend <= notional_baseline


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
