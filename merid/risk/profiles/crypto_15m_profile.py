"""
Kalshi Crypto 15m Risk Profile Adapter

Single integration point for loading and mapping the kalshi_crypto_15m profile
to internal risk configuration objects.

This adapter ensures config-only behavior for 15m crypto trading on Kalshi,
with no balance-derived computations when the profile is active.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any
from decimal import Decimal

import yaml

logger = logging.getLogger(__name__)


def is_live_profile(profile_name: str) -> bool:
    """Determine if profile is a live trading profile.
    
    Live profiles:
    - Must be kalshi_crypto_15m_v2
    - Must use prod environment (not demo)
    - Must not allow fake bankroll
    
    Returns:
        True if profile is live trading profile
    """
    from merid.settings import settings
    from merid.event_venues.kalshi.kalshi_config import get_kalshi_env
    
    # Check profile name
    if profile_name != "kalshi_crypto_15m_v2":
        return False
    
    # Check environment
    env = get_kalshi_env()
    if env != "prod":
        return False
    
    # Check fake bankroll flag
    if settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST:
        return False
    
    return True


@dataclass
class Crypto15mProfile:
    """Parsed kalshi_crypto_15m profile from YAML."""
    
    # Metadata
    profile_name: str
    profile_version: str
    description: str
    
    # Global capital and cycle risk
    capital_usd: float
    min_notional_usd: float  # Minimum notional per trade (floor)
    min_contracts: int  # Minimum contracts per trade (venue invariant)
    fractional_contract_override_threshold: float  # Allow 1 contract if max_notional >= X% of contract cost
    
    # Fallback pricing configuration
    allow_fallback_trades: bool  # Whether to allow trades with fallback pricing
    max_fallback_notional_usd: float  # Max notional for fallback trades
    max_fallback_cycles: int  # Max consecutive cycles with fallback before halting
    
    # Catalog staleness enforcement
    catalog_staleness_enforced: bool  # Whether catalog staleness can halt trading
    
    # Signal mode configuration
    signal_mode: str  # Signal generation mode: mean_reversion, momentum_fvg, hybrid, price_based
    
    # Price-based strategy parameters (Turbine research winner)
    price_based_buy_threshold: float  # Buy YES when price <= threshold
    price_based_sell_threshold: float  # Sell YES when price >= threshold
    
    # Momentum/FVG mode parameters - Kalshi-specific
    momentum_fvg_rsi_long_min: float  # Bullish momentum: RSI > threshold
    momentum_fvg_rsi_short_max: float  # Bearish momentum: RSI < threshold
    momentum_fvg_min_macd_hist_long: float  # For longs: MACD histogram >= threshold
    momentum_fvg_min_macd_hist_short: float  # For shorts: MACD histogram <= threshold
    momentum_fvg_obi_min: float  # Minimum absolute OBI value
    momentum_fvg_obi_persistence_min: float  # Minimum OBI persistence fraction
    momentum_fvg_obi_persistence_window_sec: float  # Time window for persistence check (seconds)
    momentum_fvg_obi_ewma_alpha: float  # EWMA smoothing factor
    momentum_fvg_obi_strong_btc: float  # BTC strong OBI threshold
    momentum_fvg_obi_strong_eth: float  # ETH strong OBI threshold
    momentum_fvg_obi_strong_sol: float  # SOL strong OBI threshold
    momentum_fvg_obi_strong_xrp: float  # XRP strong OBI threshold
    momentum_fvg_obi_strong_doge: float  # DOGE strong OBI threshold
    momentum_fvg_obi_ewma_alpha_btc: float  # BTC EWMA alpha
    momentum_fvg_obi_ewma_alpha_eth: float  # ETH EWMA alpha
    momentum_fvg_obi_ewma_alpha_sol: float  # SOL EWMA alpha
    momentum_fvg_obi_ewma_alpha_xrp: float  # XRP EWMA alpha
    momentum_fvg_obi_ewma_alpha_doge: float  # DOGE EWMA alpha
    momentum_fvg_fvg_window_size: int  # FVG rolling window size (number of candles)
    momentum_fvg_fvg_min_gap_cents: float  # Minimum FVG gap size in cents
    momentum_fvg_fvg_fill_threshold_cents: float  # FVG fill distance threshold in cents
    momentum_fvg_fvg_atr_period: int  # ATR period for FVG strength calculation
    momentum_fvg_fvg_max_age_bars: int  # Maximum FVG age in bars
    momentum_fvg_fvg_min_size_ticks: int  # Minimum FVG size in ticks
    momentum_fvg_fvg_min_time_to_expiry_min: float  # Minimum time to expiry for FVG entries
    momentum_fvg_require_ema_stack: bool  # Require EMA stack alignment
    momentum_fvg_require_price_vs_ema50: bool  # Require price vs EMA50
    momentum_fvg_require_price_vs_ema200: bool  # Require price vs EMA200 for macro regime (2026 research)
    # 2026 research-based indicator enhancements
    momentum_fvg_ema_200_period: int  # EMA(200) period for macro regime classification
    momentum_fvg_regime_based_rsi_enabled: bool  # Enable regime-based RSI threshold shifting
    momentum_fvg_rsi_bull_oversold: float  # Bull regime oversold threshold
    momentum_fvg_rsi_bull_overbought: float  # Bull regime overbought threshold
    momentum_fvg_rsi_bear_oversold: float  # Bear regime oversold threshold
    momentum_fvg_rsi_bear_overbought: float  # Bear regime overbought threshold
    momentum_fvg_macd_zero_line_filter_enabled: bool  # Enable MACD zero-line filter
    momentum_fvg_macd_histogram_momentum_filter_enabled: bool  # Enable MACD histogram momentum filter
    momentum_fvg_macd_histogram_expansion_bars: int  # Required bars of histogram expansion
    momentum_fvg_rsi_macd_confluence_enabled: bool  # Enable RSI+MACD confluence scoring
    momentum_fvg_liquidity_high_threshold: int  # High liquidity threshold
    momentum_fvg_liquidity_high_size_factor: float  # High liquidity size factor
    momentum_fvg_liquidity_medium_threshold: int  # Medium liquidity threshold
    momentum_fvg_liquidity_medium_size_factor: float  # Medium liquidity size factor
    momentum_fvg_liquidity_low_threshold: int  # Low liquidity threshold
    momentum_fvg_liquidity_low_size_factor: float  # Low liquidity size factor
    momentum_fvg_liquidity_ultra_low_threshold: int  # Ultra-low liquidity threshold
    momentum_fvg_liquidity_ultra_low_size_factor: float  # Ultra-low liquidity size factor
    momentum_fvg_liquidity_min_threshold: int  # Minimum liquidity threshold
    momentum_fvg_liquidity_min_size_factor: float  # Minimum liquidity size factor
    momentum_fvg_spread_gate_cents: int  # Spread gate threshold
    momentum_fvg_spread_gate_obi_persistence_boost: float  # Boosted persistence for wide spreads
    
    max_cycle_risk_pct: float
    max_cycle_risk_usd: float
    
    # Venue-level caps (percentage-based)
    venue_max_single_order_pct: float
    venue_max_total_notional_pct: float
    venue_max_category_notional_pct: float
    venue_bankroll_cap_pct: float  # Bankroll cap percentage (overrides MERID_BANKROLL_CAP_PCT env)
    venue_max_orders_per_minute: int
    venue_max_orders_per_hour: int
    
    # Per-agent defaults (percentage-based)
    agent_max_notional_pct: float
    agent_max_orders_per_window: int
    agent_max_yes_position: int
    agent_max_no_position: int
    agent_max_concurrent_trades: int
    agent_minutes_before_expiry: int
    agent_cutoff_minutes_before_expiry: int
    
    # Confidence
    confidence_use_crypto_threshold_matrix: bool
    confidence_profile_name: str
    confidence_min_confidence_threshold: float  # 2026-07-06: Primary confidence threshold (0.65 from YAML)
    # Kelly multipliers: DEPRECATED - Not actively used in sizing logic (2026-07-06 audit)
    # These are kept for backward compatibility but should be removed in future cleanup
    confidence_kelly_multiplier_no_trade: float
    confidence_kelly_multiplier_cautious: float
    confidence_kelly_multiplier_quick_win: float
    confidence_kelly_multiplier_confident: float
    
    # Guardrails
    guardrails_max_spread_cents: int
    guardrails_max_slippage_cents: int
    guardrails_min_depth_contracts: int
    guardrails_min_post_fee_edge: float
    guardrails_per_trade_risk_pct: float  # Per-trade risk percentage (sizing control)
    guardrails_min_time_to_expiry_min: int  # Minimum time to expiry for entry in minutes
    
    # Window-based risk limits (2026-07-06: HARD STOP)
    guardrails_per_window_risk_pct: float  # 3% per agent per 15m window (HARD STOP)
    guardrails_total_venue_risk_pct: float  # 5% total across all agents per 15m window (HARD STOP)
    guardrails_drawdown_halt_pct: float
    guardrails_drawdown_unwind_pct: float
    guardrails_max_daily_loss_usd: float
    guardrails_max_position_value_usd: float  # Maximum total position value in USD (position limit kill switch)
    # OTM filtering for 15-minute crypto
    guardrails_max_dist_pct_trade: float  # Maximum spot-strike distance percentage for trading
    guardrails_min_contract_price_cents: float  # Minimum contract price floor (prevents deep OTM longshots)
    guardrails_max_contract_price_cents: float  # Maximum contract price ceiling (prevents low-profit trades, 2026 research: 80% payout recommended)
    guardrails_max_same_side_per_strip: int  # Maximum same-direction positions per strip across all assets
    # Time trap prevention (entry window narrowing)
    guardrails_max_entry_mins: float  # Maximum time to expiry for entry (e.g., 12min)
    guardrails_min_entry_mins: float  # Minimum time to expiry for entry (e.g., 2min)
    # Microstructure trap prevention
    guardrails_depth_size_multiplier: float  # Depth must be >= multiplier * order_size
    # Regime/drawdown trap prevention
    guardrails_regime_cooldown_enabled: bool  # Enable regime-based cooldown
    guardrails_regime_cooldown_min_trades: int  # Minimum trades before regime check
    guardrails_regime_cooldown_min_winrate: float  # Minimum winrate threshold
    guardrails_regime_cooldown_max_loss_pct: float  # Maximum loss percentage threshold
    
    # Experimental slice configuration (targeted hypothesis testing)
    guardrails_experimental_price_band_enabled: bool  # Enable experimental price band guard
    guardrails_experimental_min_price_cents: int  # Minimum price for experimental slice
    guardrails_experimental_max_price_cents: int  # Maximum price for experimental slice
    guardrails_experimental_tte_band_enabled: bool  # Enable experimental TTE band guard
    guardrails_experimental_min_tte_min: float  # Minimum TTE for experimental slice
    guardrails_experimental_max_tte_min: float  # Maximum TTE for experimental slice
    
    # Kelly sizing
    kelly_hard_cap: float
    kelly_min_edge_pct: float
    kelly_max_edge_pct: float
    kelly_min_win_prob: float
    kelly_max_win_prob: float
    kelly_global_notional_cap_pct: float
    
    # Contract caps (hard limits, not bankroll-scaled)
    contract_caps_max_contracts_total: int
    contract_caps_max_contracts_per_asset: int
    contract_caps_max_contracts_per_cluster: int
    contract_caps_max_single_order_contracts: int
    
    # Risk policy
    # 2026 BEST PRACTICE: Dynamic percentage-based group notional cap
    # Scales with bankroll to follow industry best practices (2-5% per position)
    risk_policy_group_notional_cap_pct: float  # Percentage of bankroll (e.g., 0.05 for 5%)
    risk_policy_group_notional_cap_min_usd: float  # Minimum floor for small bankrolls
    risk_policy_group_notional_cap_max_usd: float  # Maximum ceiling for large bankrolls
    risk_policy_max_fee_to_notional_pct: float
    
    # Strategy policy
    strategy_policy_min_edge: float
    
    # Universe liquidity filters (coarse prefilter)
    universe_min_volume: int
    universe_min_open_interest: int
    universe_max_spread_cents: int
    strategy_policy_min_confidence: float
    strategy_policy_max_md_staleness_sec: float
    
    # Throttling (order rate limits)
    throttling_global_orders_window_sec: float
    throttling_global_orders_limit: int
    throttling_per_asset_cooldown_sec: float
    throttling_per_strip_order_limit: int
    throttling_per_strip_notional_usd: float
    throttling_max_orders_per_15m_window: int  # 2026 research: Max 5 trades per session
    throttling_consecutive_loss_pause: int  # 2026 research: Pause after N consecutive losses
    throttling_max_session_risk_pct: float  # 2026 research: Max session risk as % of capital
    
    # Failsafe configuration (emergency brake)
    failsafe_max_contracts_per_order: int
    
    # Venue invariants (Kalshi venue-level constants)
    venue_invariants_valid_price_cents_min: int
    venue_invariants_valid_price_cents_max: int
    venue_invariants_deep_otm_threshold_cents: int  # Task 30: Deep OTM threshold from profile
    venue_invariants_deep_itm_threshold_cents: int  # Task 30: Deep ITM threshold from profile
    venue_invariants_ioc_auto_below_seconds: int  # Task 31: IOC auto-below threshold from profile
    venue_invariants_max_book_staleness_ms: int  # Maximum orderbook staleness in milliseconds (PRODUCTION INVARIANT)
    
    # Legacy path control
    legacy_disable_balance_calibration: bool
    legacy_disable_dynamic_contract_caps: bool
    legacy_disable_bankroll_category_limits: bool
    legacy_disable_bankroll_prediction_risk: bool
    legacy_disable_bankroll_guardrails: bool
    
    # Edge/lag filter configuration (with defaults)
    edge_lag_filter_min_edge_lag_ratio: Dict[str, float] = field(default_factory=dict)
    edge_lag_filter_enabled: Dict[str, int] = field(default_factory=dict)
    edge_lag_filter_cold_start_min_samples: int = 100
    
    # Computed venue caps (USD, derived from capital) - with defaults
    venue_max_single_order_usd: float = 0.0
    venue_max_total_notional_usd: float = 0.0
    venue_max_category_notional_usd: float = 0.0
    
    # Computed agent defaults (USD, derived from capital) - with defaults
    agent_max_notional_usd: float = 0.0
    
    # Per-asset caps (BTC/ETH/SOL/XRP/DOGE) - with floor applied - with defaults
    asset_max_notional_usd: Dict[str, float] = field(default_factory=dict)
    
    # Per-asset caps (BTC/ETH/SOL/XRP/DOGE) - with defaults
    asset_configs: Dict[str, "AssetConfig"] = field(default_factory=dict)
    
    # Microstructure trap prevention (with default)
    guardrails_max_spread_for_edge: Dict[str, int] = field(default_factory=dict)  # edge_pct -> max_spread_cents
    
    # Velocity model coefficients (Phase 1: Logistic mapping from velocity to probability)
    # CRITICAL FIX: 2026-07-04 - Increased alpha_1 to make velocity-to-probability mapping responsive
    # Previous values (1.5-5.0) were too low, causing p_model to stay near 50% regardless of velocity
    # New values (200-500) align with 2026 industry standards for momentum trading
    # With velocity threshold=0.4%-0.8%, these coefficients produce meaningful probability shifts
    velocity_model_alpha_0_btc: float = 0.0
    velocity_model_alpha_1_btc: float = 200.0  # Increased from 2.0 to 200.0 for responsive mapping
    velocity_model_alpha_0_eth: float = 0.0
    velocity_model_alpha_1_eth: float = 200.0  # Increased from 2.0 to 200.0 for responsive mapping
    velocity_model_alpha_0_sol: float = 0.0
    velocity_model_alpha_1_sol: float = 300.0  # Increased from 3.0 to 300.0 for responsive mapping
    velocity_model_alpha_0_xrp: float = 0.0
    velocity_model_alpha_1_xrp: float = 300.0  # Increased from 3.0 to 300.0 for responsive mapping
    velocity_model_alpha_0_doge: float = 0.0
    velocity_model_alpha_1_doge: float = 500.0  # Increased from 5.0 to 500.0 for responsive mapping

    # Velocity thresholds (per-asset, aligned with actual market velocities)
    # CRITICAL FIX: 2026-07-05 - Reduced to effectively zero to enable any trading
    # Actual market velocities observed: 0.000%-0.04% (from live logs 2026-07-05)
    # Previous thresholds (0.001%-0.005%) were still blocking trades in calm markets
    # New thresholds (0.001%) allow trades even in extremely calm markets:
    velocity_threshold_btc: float = 0.00001  # 0.001% - effectively zero to enable any movement
    velocity_threshold_eth: float = 0.00001  # 0.001% - effectively zero to enable any movement
    velocity_threshold_sol: float = 0.00001  # 0.001% - effectively zero to enable any movement
    velocity_threshold_xrp: float = 0.00001  # 0.001% - effectively zero to enable any movement
    velocity_threshold_doge: float = 0.00001  # 0.001% - effectively zero to enable any movement

    # Phase 4.1: Multi-window velocity weights for momentum signal fusion
    momentum_weights_windows: list = field(default_factory=lambda: [10, 30, 60])  # Velocity windows in seconds
    momentum_weights_values: list = field(default_factory=lambda: [0.2, 0.3, 0.5])  # Weights for each window

    # Phase 4.4: Logit fusion weights for combining multiple signal sources
    logit_fusion_velocity_weight: float = 0.7  # Weight for velocity signal
    logit_fusion_mean_reversion_weight: float = 0.3  # Weight for mean reversion signal

    # Phase 4.5: Near expiry guard for logit fusion
    near_expiry_guard_sec: int = 300  # Skip logit fusion if time to expiry < 5 minutes

    # Phase 5.2: Calibration configuration for probability calibration
    # CRITICAL FIX: Enable calibration based on 2026 research showing domain-specific biases
    
    # Position Management: Offset Hedging Configuration
    offset_hedging_enabled: bool = False
    offset_hedging_hedge_ratio: float = 0.30
    offset_hedging_min_edge_for_hedge: float = 0.03
    offset_hedging_max_hedge_notional_pct: float = 0.02
    offset_hedging_rebalance_threshold: float = 0.05
    offset_hedging_min_hedge_contracts: int = 1
    offset_hedging_max_hedge_contracts: int = 3
    
    # Position Management: Trailing Stop Configuration
    trailing_stop_enabled: bool = True  # CRITICAL FIX: Default to True to match YAML config (was False - trailing stops were disabled)
    trailing_stop_trailing_distance_cents: int = 5
    trailing_stop_trailing_distance_cents_profit_zone: int = 2  # CRITICAL FIX: 2026-07-06 - Aggressive trailing in 80-85c profit zone
    trailing_stop_min_profit_cents: int = 12  # Updated from 3 to 12 (align with 2026 research: 10-15¢ threshold to avoid noise-triggered exits)
    trailing_stop_activation_delay_sec: int = 30
    trailing_stop_profit_zone_activation_cents: int = 80  # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing at 80c
    
    # Position Management: Dynamic Risk Configuration
    # Volatility-regime based stop-loss cents for dynamic risk engine
    dynamic_risk_sl_cents_low_vol: int = 6  # Tight SL in low volatility (6 cents)
    dynamic_risk_sl_cents_normal_vol: int = 8  # Standard SL in normal volatility (8 cents)
    dynamic_risk_sl_cents_high_vol: int = 10  # Wide SL in high volatility (10 cents)
    
    # Position Management: Ratchet Profit Floor Configuration
    # Research-backed mechanism to lock in profits when price reaches high threshold
    # Prevents giving back significant gains when 99¢ TP is not guaranteed
    ratchet_profit_floor_enabled: bool = True  # Enable ratchet profit floor mechanism
    ratchet_activation_threshold_cents: int = 85  # Activate ratchet when price hits this threshold
    ratchet_floor_offset_cents: int = 5  # Set floor X cents below activation (e.g., 85¢ activation → 80¢ floor)
    ratchet_force_exit_on_floor_breach: bool = True  # Mandatory exit if price drops to floor
    ratchet_min_hold_after_activation_sec: int = 30  # Prevent immediate exit on noise (seconds)
    # CRITICAL FIX: 2026-07-06 - Removed ratchet_mandatory_exit_at_99c (redundant, handled by position-level extreme profit)
    ratchet_trim_position_enabled: bool = True  # 2026-07-05: Trim position when >1 contract and price >80c
    ratchet_trim_threshold_cents: int = 80  # 2026-07-05: Trim when price crosses this threshold
    ratchet_trim_to_contracts: int = 1  # 2026-07-05: Trim to 1 contract to lock in profits
    
    # Position Management: Dynamic Take Profit Zones Configuration
    # 2026-07-06: Laddered exit targets based on entry price for consistent profit taking
    dynamic_take_profit: dict = field(default_factory=dict)  # Full dynamic take profit config dict
    
    # Position Management: Dynamic Sizing Configuration
    dynamic_sizing_enabled: bool = False
    dynamic_sizing_base_contracts: int = 1
    dynamic_sizing_edge_multiplier: float = 2.0
    dynamic_sizing_confidence_multiplier: float = 1.0
    dynamic_sizing_max_contracts: int = 3
    dynamic_sizing_min_contracts: int = 1
    # Crypto markets are near well-calibrated (slope ~1.08) but still benefit from dynamic adjustment
    calibration_enabled: bool = True  # Enable/disable probability calibration (ENABLED for dynamic adjustment)
    calibration_auto_fit: bool = True  # Automatically fit calibration when sufficient data
    calibration_min_samples: int = 50  # Minimum samples required to fit calibration (reduced from 100 for faster startup)
    calibration_max_samples: int = 500  # Maximum samples to keep for calibration (reduced from 1000 for more recent data)
    calibration_regularization: float = 0.0001  # L2 regularization parameter
    calibration_fit_interval_hours: int = 1  # Re-fit calibration every N hours (reduced from 24 for more frequent updates)

    # Phase 1: Fee-aware edge gate configuration
    fee_aware_edge_enabled: bool = True  # Enable fee-aware edge calculation
    fee_aware_edge_min_edge_cents: float = 2.0  # $0.02 minimum edge after fees
    fee_aware_edge_fee_per_contract: float = 0.07  # Kalshi taker fee per contract

    # Phase 1: Market microstructure filters configuration
    # 2026 OPTIMIZATION: Increased to 50c to align with guardrails and 2026 research
    # 2026 findings: 50-100bp spreads (5-10c) common in moderate-liquidity markets
    # Previous 15c was too restrictive for 15m crypto contracts
    # 2026 OPTIMIZATION: Reduced min depth to $50 for single-contract trading
    # Previous $200 was too high for 1-contract orders; aligns with guardrails min_depth_contracts=2
    # 2026-07-01 FIX: Reduced spread threshold to 10c to align with 2026 industry standards
    # Industry research shows 5-10c is standard for 15m binary options to ensure good fills
    # Previous 100c was too permissive, accepting illiquid markets with poor fill quality
    # Research shows BTC typically has 2c spreads in middle of window, other assets slightly wider
    # 95c spreads observed in logs are abnormal (data quality or extreme thinness)
    # 2026-07-04: UNIFIED to 75c - aligned with guardrails.max_spread_cents (single source of truth)
    # CRITICAL FIX: Previous 50c was blocking trades that should be allowed per YAML guardrails (75c)
    # Research: DOGE spreads can exceed 50c (observed 79c spread = 1.3% on 59c price)
    # Reference: Kalena 2026 research - altcoin spreads 5-30% in 15m markets
    # 75c threshold allows realistic trading while blocking extreme data quality issues
    market_microstructure_enabled: bool = True  # Enable market microstructure filters
    market_microstructure_max_spread_cents: float = 75.0  # UNIFIED: 75c aligned with guardrails.max_spread_cents
    market_microstructure_min_depth_usd: float = 0.0  # DISABLED: System uses limit orders which wait for fills, not market orders. Kalshi 15m crypto markets have sufficient liquidity. Depth thresholds are primarily for market orders to prevent slippage.
    market_microstructure_min_yes_depth: int = 1  # Minimum YES depth threshold
    market_microstructure_min_no_depth: int = 1  # Minimum NO depth threshold

    # Phase 2: Strategy definitions for multi-strategy support
    strategies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # 2026 Research-Based Risk Management
    # Correlation-aware position sizing
    correlation_tracking_enabled: bool = False
    correlation_tracking_real_time_monitoring: bool = False
    correlation_tracking_threshold_high: float = 0.80
    correlation_tracking_threshold_moderate: float = 0.50
    correlation_tracking_threshold_alert: float = 0.85
    correlation_tracking_max_correlated_assets: int = 3
    
    # Volatility-regime edge adjustment
    volatility_regime_edge_adjustment_enabled: bool = True
    volatility_regime_edge_adjustment_lookback_days: int = 30
    volatility_regime_edge_adjustment_low_volatility_threshold: float = 0.30
    volatility_regime_edge_adjustment_high_volatility_threshold: float = 0.70
    volatility_regime_edge_adjustment_low_volatility_adjustment: float = -0.0025  # CRITICAL FIX: -0.25% (aligned with profile YAML)
    volatility_regime_edge_adjustment_high_volatility_adjustment: float = 0.005  # CRITICAL FIX: +0.5% (aligned with profile YAML)
    
    # Portfolio heat tracking
    portfolio_heat_enabled: bool = False
    portfolio_heat_calculation_method: str = "correlation_adjusted_exposure"
    portfolio_heat_heat_threshold_warning: float = 0.70
    portfolio_heat_heat_threshold_critical: float = 0.85
    
    # Time-of-day risk scaling
    time_of_day_risk_scaling_enabled: bool = False
    time_of_day_risk_scaling_us_market_hours: str = "09:30-16:00 ET"
    time_of_day_risk_scaling_asian_session: str = "20:00-02:00 ET"
    time_of_day_risk_scaling_european_session: str = "02:00-09:30 ET"
    time_of_day_risk_scaling_us_market_multiplier: float = 1.0
    time_of_day_risk_scaling_asian_multiplier: float = 0.8
    time_of_day_risk_scaling_european_multiplier: float = 0.9
    time_of_day_risk_scaling_weekend_multiplier: float = 0.8  # RELAXED: 0.8 (was 0.5) - use volatility regime instead of fixed weekend reduction
    
    # Asset-specific rolling PnL limits
    asset_specific_rolling_pnl_enabled: bool = False
    asset_specific_rolling_pnl_btc_rolling_1h_halt_pct: float = 0.04
    asset_specific_rolling_pnl_btc_rolling_4h_halt_pct: float = 0.07
    asset_specific_rolling_pnl_eth_rolling_1h_halt_pct: float = 0.04
    asset_specific_rolling_pnl_eth_rolling_4h_halt_pct: float = 0.07
    asset_specific_rolling_pnl_sol_rolling_1h_halt_pct: float = 0.06
    asset_specific_rolling_pnl_sol_rolling_4h_halt_pct: float = 0.09
    asset_specific_rolling_pnl_xrp_rolling_1h_halt_pct: float = 0.06
    asset_specific_rolling_pnl_xrp_rolling_4h_halt_pct: float = 0.09
    asset_specific_rolling_pnl_doge_rolling_1h_halt_pct: float = 0.08
    asset_specific_rolling_pnl_doge_rolling_4h_halt_pct: float = 0.12
    
    # Updated adaptive risk bands (2026 research: more granular)
    guardrails_adaptive_risk_bands: list = field(default_factory=list)

    # Price range configuration for entry band restrictions
    price_range: 'PriceRange' = field(default_factory=lambda: PriceRange(
        min_price_cents=10,
        max_price_cents=70,
        description='Valid price range in cents for order execution'
    ))

    @property
    def momentum_fvg(self) -> Dict[str, Any]:
        """
        Return momentum_fvg configuration as a dictionary.
        
        This property provides backward compatibility for code that expects
        profile.momentum_fvg to be a nested object/dict.
        """
        return {
            'momentum_rsi_long_min': self.momentum_fvg_rsi_long_min,
            'momentum_rsi_short_max': self.momentum_fvg_rsi_short_max,
            'momentum_min_macd_hist_long': self.momentum_fvg_min_macd_hist_long,
            'momentum_min_macd_hist_short': self.momentum_fvg_min_macd_hist_short,
            'obi_min': self.momentum_fvg_obi_min,
            'obi_persistence_min': self.momentum_fvg_obi_persistence_min,
            'obi_persistence_window_sec': self.momentum_fvg_obi_persistence_window_sec,
            'obi_ewma_alpha': self.momentum_fvg_obi_ewma_alpha,
            'obi_strong_btc': self.momentum_fvg_obi_strong_btc,
            'obi_strong_eth': self.momentum_fvg_obi_strong_eth,
            'obi_strong_sol': self.momentum_fvg_obi_strong_sol,
            'obi_strong_xrp': self.momentum_fvg_obi_strong_xrp,
            'obi_strong_doge': self.momentum_fvg_obi_strong_doge,
            'obi_ewma_alpha_btc': self.momentum_fvg_obi_ewma_alpha_btc,
            'obi_ewma_alpha_eth': self.momentum_fvg_obi_ewma_alpha_eth,
            'obi_ewma_alpha_sol': self.momentum_fvg_obi_ewma_alpha_sol,
            'obi_ewma_alpha_xrp': self.momentum_fvg_obi_ewma_alpha_xrp,
            'obi_ewma_alpha_doge': self.momentum_fvg_obi_ewma_alpha_doge,
            'fvg_window_size': self.momentum_fvg_fvg_window_size,
            'fvg_min_gap_cents': self.momentum_fvg_fvg_min_gap_cents,
            'fvg_fill_threshold_cents': self.momentum_fvg_fvg_fill_threshold_cents,
            'fvg_atr_period': self.momentum_fvg_fvg_atr_period,
            'fvg_max_age_bars': self.momentum_fvg_fvg_max_age_bars,
            'fvg_min_size_ticks': self.momentum_fvg_fvg_min_size_ticks,
            'fvg_min_time_to_expiry_min': self.momentum_fvg_fvg_min_time_to_expiry_min,
            'require_ema_stack': self.momentum_fvg_require_ema_stack,
            'require_price_vs_ema50': self.momentum_fvg_require_price_vs_ema50,
            'require_price_vs_ema200': self.momentum_fvg_require_price_vs_ema200,
            # 2026 research-based indicator enhancements
            'ema_200_period': self.momentum_fvg_ema_200_period,
            'regime_based_rsi_enabled': self.momentum_fvg_regime_based_rsi_enabled,
            'rsi_bull_oversold': self.momentum_fvg_rsi_bull_oversold,
            'rsi_bull_overbought': self.momentum_fvg_rsi_bull_overbought,
            'rsi_bear_oversold': self.momentum_fvg_rsi_bear_oversold,
            'rsi_bear_overbought': self.momentum_fvg_rsi_bear_overbought,
            'macd_zero_line_filter_enabled': self.momentum_fvg_macd_zero_line_filter_enabled,
            'macd_histogram_momentum_filter_enabled': self.momentum_fvg_macd_histogram_momentum_filter_enabled,
            'macd_histogram_expansion_bars': self.momentum_fvg_macd_histogram_expansion_bars,
            'rsi_macd_confluence_enabled': self.momentum_fvg_rsi_macd_confluence_enabled,
            'liquidity_high_threshold': self.momentum_fvg_liquidity_high_threshold,
            'liquidity_high_size_factor': self.momentum_fvg_liquidity_high_size_factor,
            'liquidity_medium_threshold': self.momentum_fvg_liquidity_medium_threshold,
            'liquidity_medium_size_factor': self.momentum_fvg_liquidity_medium_size_factor,
            'liquidity_low_threshold': self.momentum_fvg_liquidity_low_threshold,
            'liquidity_low_size_factor': self.momentum_fvg_liquidity_low_size_factor,
            'liquidity_ultra_low_threshold': self.momentum_fvg_liquidity_ultra_low_threshold,
            'liquidity_ultra_low_size_factor': self.momentum_fvg_liquidity_ultra_low_size_factor,
            'liquidity_min_threshold': self.momentum_fvg_liquidity_min_threshold,
            'liquidity_min_size_factor': self.momentum_fvg_liquidity_min_size_factor,
            'spread_gate_cents': self.momentum_fvg_spread_gate_cents,
            'spread_gate_obi_persistence_boost': self.momentum_fvg_spread_gate_obi_persistence_boost,
        }


@dataclass
class PriceRange:
    """Price range configuration for entry band restrictions."""
    min_price_cents: int
    max_price_cents: int
    description: str


@dataclass
class AssetConfig:
    """Per-asset configuration from the profile."""
    
    asset: str
    max_notional_pct: float  # Percentage of capital
    max_contracts: int
    min_edge_early: float
    min_edge_mid: float
    min_edge_late: float
    min_edge_terminal: float
    
    # Computed USD value (derived from capital)
    max_notional_usd: float = 0.0


class Crypto15mProfileAdapter:
    """
    Adapter that loads the kalshi_crypto_15m profile and maps it to
    internal risk configuration objects.
    
    This is the single integration point for 15m crypto risk configuration.
    All reads come from the profile; no balance-derived computations are used.
    """
    
    def __init__(self, profile_path: Optional[Path] = None):
        """
        Initialize the adapter.
        
        Args:
            profile_path: Path to kalshi_crypto_15m.yaml. If None, uses default.
        """
        if profile_path is None:
            # Path from merid/risk/profiles/crypto_15m_profile.py to config/profiles/
            # Use kalshi_crypto_15m_v2.yaml for MERID_PROFILE=kalshi_crypto_15m_v2
            import os
            profile_name = os.getenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
            profile_filename = f"{profile_name}.yaml"
            profile_path = Path(__file__).parent.parent.parent.parent / "config" / "profiles" / profile_filename
        
        self.profile_path = profile_path
        self._profile: Optional[Crypto15mProfile] = None
        self._load_profile()

    @property
    def profile_version(self) -> str:
        """Return the profile version from the loaded profile."""
        if self._profile is None:
            return "unknown"
        return getattr(self._profile, 'profile_version', 'unknown')
    
    def _validate_profile_schema(self, raw: Dict[str, Any]) -> None:
        """Validate profile YAML schema and fail-fast on missing required fields.

        This is a regression guard for Task 29 (profile YAML schema validation).
        Ensures that critical fields are present in the profile YAML to prevent
        silent fallback to default values.

        Args:
            raw: Raw profile YAML dictionary

        Raises:
            ValueError: If required fields are missing
        """
        required_sections = [
            'profile_name',
            'profile_version',
            'description',
            'capital_usd',
            'min_notional_usd',
            'min_contracts',
            'max_cycle_risk_pct',
            'venue',
            'assets',
            'agent_defaults',
            'kelly',
            'guardrails',
            'contract_caps',
            'risk_policy',
            'strategy_policy',
            'velocity_model',  # Phase 1: Required for logistic mapping
        ]

        for field in required_sections:
            if field not in raw:
                raise ValueError(
                    f"Profile YAML validation failed: missing required field '{field}' in {self.profile_path}. "
                    f"This field is required for profile loading. Check kalshi_crypto_15m.yaml."
                )

        # Validate Kelly section has required fields
        kelly = raw.get('kelly', {})
        required_kelly_fields = ['kelly_hard_cap', 'kelly_min_edge_pct', 'kelly_max_edge_pct']
        for field in required_kelly_fields:
            if field not in kelly:
                raise ValueError(
                    f"Profile YAML validation failed: missing required field 'kelly.{field}' in {self.profile_path}. "
                    f"This field is required for Kelly sizing configuration."
                )

        # Validate guardrails section has required fields
        guardrails = raw.get('guardrails', {})
        required_guardrails_fields = ['drawdown_halt_pct', 'drawdown_unwind_pct']
        for field in required_guardrails_fields:
            if field not in guardrails:
                raise ValueError(
                    f"Profile YAML validation failed: missing required field 'guardrails.{field}' in {self.profile_path}. "
                    f"This field is required for drawdown configuration."
                )

        logger.info("[PROFILE-SCHEMA-VALIDATION] Profile YAML schema validation passed")

    def _load_profile(self) -> None:
        """Load and parse the profile YAML."""
        try:
            # CRITICAL FIX: Validate profile path exists before loading
            if not self.profile_path.exists():
                raise FileNotFoundError(f"Profile file not found: {self.profile_path}")
            
            with open(self.profile_path, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f)
                
            # CRITICAL FIX: Validate YAML loaded successfully
            if raw is None:
                raise ValueError(f"Profile file is empty or invalid YAML: {self.profile_path}")
            
            # Validate profile YAML schema (Task 29: Fail-fast on missing fields)
            self._validate_profile_schema(raw)
            
            # Parse venue caps
            venue = raw.get('venue', {})
            
            # Parse asset configs
            asset_configs = {}
            assets_raw = raw.get('assets', {})
            for asset_name, asset_data in assets_raw.items():
                # Handle nested dict format for max_notional_pct
                max_notional_pct = self._normalize_percentage_value(asset_data.get('max_notional_pct', 0.0))
                
                # Handle nested dict format for max_contracts
                max_contracts = self._normalize_contracts_value(asset_data.get('max_contracts', 0))
                
                asset_configs[asset_name] = AssetConfig(
                    asset=asset_name,
                    max_notional_pct=max_notional_pct,
                    max_contracts=max_contracts,
                    # REMOVED: Per-asset min_edge fields - now using profile edge_bands section
                    # Edge thresholds come from kalshi_crypto_15m_v2.yaml edge_bands section:
                    # - watch_band: 1-2% (log only)
                    # - small_band: 2-4% (trade small)
                    # - standard_band: >=4% (trade standard)
                    # - kelly_min_edge_pct: 2% (hard floor)
                    min_edge_early=0.0,  # Not used - edge_bands instead
                    min_edge_mid=0.0,    # Not used - edge_bands instead
                    min_edge_late=0.0,   # Not used - edge_bands instead
                    min_edge_terminal=0.0,  # Not used - edge_bands instead
                )
            
            # Parse agent defaults
            agent_defaults = raw.get('agent_defaults', {})
            
            # Parse capital_usd - derive from live bankroll if set to 0
            capital_usd = raw.get('capital_usd', 10000.0)
            if capital_usd == 0.0:
                # Derive from BankrollServiceV2 (single source of truth)
                # NOTE: This is deferred - we set capital_usd=0 here and let the bankroll service
                # provide the actual value via equity_provider during startup
                logger.info("[PROFILE_WIRING] capital_usd=0 configured - will derive from BankrollServiceV2 during startup")
                capital_usd = 0.0
            
            # Compute USD values from percentages
            # Handle nested dict format: {value: 0.05, dynamic: bankroll, description: "..."}
            venue_max_single_order_pct = venue.get('max_single_order_pct', 0.05)
            if isinstance(venue_max_single_order_pct, dict):
                venue_max_single_order_pct = venue_max_single_order_pct.get('value', 0.05)
            
            venue_max_total_notional_pct = venue.get('max_total_notional_pct', 0.15)  # FIXED: Default 0.15 to match YAML (15% total venue cap)
            if isinstance(venue_max_total_notional_pct, dict):
                venue_max_total_notional_pct = venue_max_total_notional_pct.get('value', 0.15)  # FIXED: Default 0.15 to match YAML (15% total venue cap)
            
            venue_max_category_notional_pct = venue.get('max_category_notional_pct', 0.10)
            if isinstance(venue_max_category_notional_pct, dict):
                venue_max_category_notional_pct = venue_max_category_notional_pct.get('value', 0.10)
            
            venue_bankroll_cap_pct = venue.get('bankroll_cap_pct', 0.02)  # Default 2% if not specified
            if isinstance(venue_bankroll_cap_pct, dict):
                venue_bankroll_cap_pct = venue_bankroll_cap_pct.get('value', 0.02)
            
            agent_max_notional_pct = agent_defaults.get('max_notional_pct', 0.03)  # FIXED: Default 0.03 to match YAML (3% per agent)
            if isinstance(agent_max_notional_pct, dict):
                agent_max_notional_pct = agent_max_notional_pct.get('value', 0.03)  # FIXED: Default 0.03 to match YAML (3% per agent)
            
            # Compute USD values from capital
            # Ensure all computed values are floats to prevent type errors
            venue_max_single_order_usd = float(capital_usd) * float(venue_max_single_order_pct)
            venue_max_total_notional_usd = float(capital_usd) * float(venue_max_total_notional_pct)
            venue_max_category_notional_usd = float(capital_usd) * float(venue_max_category_notional_pct)
            agent_max_notional_usd = float(capital_usd) * float(agent_max_notional_pct)
            
            # PERCENTAGE CONSISTENCY ASSERTIONS: Prevent invalid config at load time
            # These ensure the profile is internally consistent before runtime
            assert venue_max_single_order_pct <= venue_max_total_notional_pct, \
                f"CONFIG ERROR: max_single_order_pct ({venue_max_single_order_pct}) must be <= max_total_notional_pct ({venue_max_total_notional_pct})"
            assert venue_max_category_notional_pct <= venue_max_total_notional_pct, \
                f"CONFIG ERROR: max_category_notional_pct ({venue_max_category_notional_pct}) must be <= max_total_notional_pct ({venue_max_total_notional_pct})"
            assert agent_max_notional_pct <= venue_max_single_order_pct, \
                f"CONFIG ERROR: agent_max_notional_pct ({agent_max_notional_pct}) must be <= max_single_order_pct ({venue_max_single_order_pct})"
            
            # Verify per-asset percentages are consistent with category/total caps
            total_asset_pct = sum(asset_config.max_notional_pct for asset_config in asset_configs.values())
            assert total_asset_pct <= venue_max_total_notional_pct, \
                f"CONFIG ERROR: Sum of per-asset max_notional_pct ({total_asset_pct}) must be <= max_total_notional_pct ({venue_max_total_notional_pct})"
            
            # Verify each asset's percentage is within category cap
            for asset_name, asset_config in asset_configs.items():
                assert asset_config.max_notional_pct <= venue_max_category_notional_pct, \
                    f"CONFIG ERROR: {asset_name} max_notional_pct ({asset_config.max_notional_pct}) must be <= max_category_notional_pct ({venue_max_category_notional_pct})"
            
            # Compute per-asset USD values
            for asset_config in asset_configs.values():
                asset_config.max_notional_usd = capital_usd * asset_config.max_notional_pct
            
            # Parse confidence
            confidence = raw.get('confidence', {})
            
            # Parse guardrails (handle nested dict format)
            guardrails = raw.get('guardrails', {})
            
            # Extract drawdown thresholds from nested dict format
            guardrails_drawdown_halt_pct = self._normalize_percentage_value(guardrails.get('drawdown_halt_pct', 0.20))  # CRITICAL FIX: 20% - aligned with profile (was 0.10)
            guardrails_drawdown_unwind_pct = self._normalize_percentage_value(guardrails.get('drawdown_unwind_pct', 0.25))  # CRITICAL FIX: 25% - aligned with profile (was 0.15)
            guardrails_per_trade_risk_pct = self._normalize_percentage_value(guardrails.get('per_trade_risk_pct', 0.03))  # CRITICAL FIX: 3% - aligned with profile (was 0.008)
            
            # Parse window-based risk limits (2026-07-06: HARD STOP)
            guardrails_per_window_risk_pct = self._normalize_percentage_value(
                raw.get('guardrails_per_window_risk_pct', 0.03)
            )  # 3% per agent per 15m window (HARD STOP)
            guardrails_total_venue_risk_pct = self._normalize_percentage_value(
                raw.get('guardrails_total_venue_risk_pct', 0.05)
            )  # 5% total across all agents per 15m window (HARD STOP)
            
            # Parse Kelly
            kelly = raw.get('kelly', {})
            
            # Parse contract caps
            contract_caps = raw.get('contract_caps', {})
            
            # Parse risk policy
            risk_policy = raw.get('risk_policy', {})
            
            # Parse strategy policy
            strategy_policy = raw.get('strategy_policy', {})
            
            # Parse throttling (order rate limits)
            throttling = raw.get('throttling', {})
            
            # Parse universe liquidity filters
            universe = raw.get('universe', {})
            
            # Parse failsafe configuration
            failsafe = raw.get('failsafe', {})
            
            # Parse legacy flags
            legacy = raw.get('legacy', {})
            
            # Parse velocity model coefficients (Phase 1: Logistic mapping)
            velocity_model = raw.get('velocity_model', {})
            
            # Parse strategies configuration (Phase 2: Multi-strategy support)
            strategies = raw.get('strategies', {})
            
            # Parse momentum_fvg config before constructing profile
            momentum_fvg_config = raw.get('momentum_fvg', {})
            liquidity_tiers = momentum_fvg_config.get('liquidity_tiers', {})
            
            self._profile = Crypto15mProfile(
                # Metadata
                profile_name=raw.get('profile_name', ''),
                profile_version=raw.get('profile_version', ''),
                description=raw.get('description', ''),
                
                # Global capital and cycle risk
                capital_usd=capital_usd,
                min_notional_usd=raw.get('min_notional_usd', 0.35),  # Default $0.35
                min_contracts=raw.get('min_contracts', 1),  # Default 1 contract
                fractional_contract_override_threshold=raw.get('fractional_contract_override_threshold', 0.5),  # Default 50%
                
                # Fallback pricing configuration
                allow_fallback_trades=raw.get('allow_fallback_trades', False),  # Default: disabled in prod
                max_fallback_notional_usd=raw.get('max_fallback_notional_usd', 0.35),  # Default: min_notional
                max_fallback_cycles=raw.get('max_fallback_cycles', 3),  # Default: 3 cycles before halt
                
                # Catalog staleness enforcement
                catalog_staleness_enforced=raw.get('catalog_staleness_enforced', True),  # Default: enabled
                
                # Signal mode configuration
                signal_mode=raw.get('signal_mode', 'hybrid'),  # Default: hybrid for maximum opportunity capture
                
                # Price-based strategy parameters
                price_based_buy_threshold=raw.get('price_based', {}).get('buy_threshold', 0.70),
                price_based_sell_threshold=raw.get('price_based', {}).get('sell_threshold', 0.90),
                
                # Price range configuration for entry band restrictions
                # CRITICAL FIX: max_price_cents default 75 to match guardrails_max_contract_price_cents (75c sweet spot threshold)
                price_range=PriceRange(
                    min_price_cents=raw.get('price_range', {}).get('min_price_cents', 10),
                    max_price_cents=raw.get('price_range', {}).get('max_price_cents', 75),  # CRITICAL FIX: Default 75c to match guardrails (was 70)
                    description=raw.get('price_range', {}).get('description', 'Valid price range in cents for order execution')
                ),
                
                # Momentum/FVG mode parameters
                momentum_fvg_rsi_long_min=momentum_fvg_config.get('momentum_rsi_long_min', 55.0),
                momentum_fvg_rsi_short_max=momentum_fvg_config.get('momentum_rsi_short_max', 45.0),
                momentum_fvg_min_macd_hist_long=momentum_fvg_config.get('momentum_min_macd_hist_long', 0.0),
                momentum_fvg_min_macd_hist_short=momentum_fvg_config.get('momentum_min_macd_hist_short', 0.0),
                momentum_fvg_obi_min=momentum_fvg_config.get('obi_min', 0.25),
                momentum_fvg_obi_persistence_min=momentum_fvg_config.get('obi_persistence_min', 0.6),
                momentum_fvg_obi_persistence_window_sec=momentum_fvg_config.get('obi_persistence_window_sec', 10.0),
                momentum_fvg_obi_ewma_alpha=momentum_fvg_config.get('obi_ewma_alpha', 0.15),
                momentum_fvg_obi_strong_btc=momentum_fvg_config.get('obi_strong_btc', 0.85),  # 2026-07-03: Increased to 85% for crypto volatility
                momentum_fvg_obi_strong_eth=momentum_fvg_config.get('obi_strong_eth', 0.85),  # 2026-07-03: Increased to 85% for crypto volatility
                momentum_fvg_obi_strong_sol=momentum_fvg_config.get('obi_strong_sol', 0.80),  # 2026-07-03: Increased to 80% for crypto volatility
                momentum_fvg_obi_strong_xrp=momentum_fvg_config.get('obi_strong_xrp', 0.80),  # 2026-07-03: Increased to 80% for crypto volatility
                momentum_fvg_obi_strong_doge=momentum_fvg_config.get('obi_strong_doge', 0.80),  # 2026-07-03: Increased to 80% for crypto volatility
                momentum_fvg_obi_ewma_alpha_btc=momentum_fvg_config.get('obi_ewma_alpha_btc', 0.15),
                momentum_fvg_obi_ewma_alpha_eth=momentum_fvg_config.get('obi_ewma_alpha_eth', 0.15),
                momentum_fvg_obi_ewma_alpha_sol=momentum_fvg_config.get('obi_ewma_alpha_sol', 0.20),
                momentum_fvg_obi_ewma_alpha_xrp=momentum_fvg_config.get('obi_ewma_alpha_xrp', 0.20),
                momentum_fvg_obi_ewma_alpha_doge=momentum_fvg_config.get('obi_ewma_alpha_doge', 0.20),
                # CRITICAL FIX: 2026-07-06 - Added FVG config from profile YAML (single source of truth)
                momentum_fvg_fvg_window_size=momentum_fvg_config.get('fvg_window_size', 20),
                momentum_fvg_fvg_min_gap_cents=momentum_fvg_config.get('fvg_min_gap_cents', 2.0),
                momentum_fvg_fvg_fill_threshold_cents=momentum_fvg_config.get('fvg_fill_threshold_cents', 5.0),
                momentum_fvg_fvg_atr_period=momentum_fvg_config.get('fvg_atr_period', 14),
                momentum_fvg_fvg_max_age_bars=momentum_fvg_config.get('fvg_max_age_bars', 4),
                momentum_fvg_fvg_min_size_ticks=momentum_fvg_config.get('fvg_min_size_ticks', 3),
                momentum_fvg_fvg_min_time_to_expiry_min=momentum_fvg_config.get('fvg_min_time_to_expiry_min', 30.0),
                momentum_fvg_require_ema_stack=momentum_fvg_config.get('require_ema_stack', True),
                momentum_fvg_require_price_vs_ema50=momentum_fvg_config.get('require_price_vs_ema50', True),
                momentum_fvg_require_price_vs_ema200=momentum_fvg_config.get('require_price_vs_ema200', True),
                # 2026 research-based indicator enhancements
                momentum_fvg_ema_200_period=momentum_fvg_config.get('ema_200_period', 200),
                momentum_fvg_regime_based_rsi_enabled=momentum_fvg_config.get('regime_based_rsi_enabled', True),
                momentum_fvg_rsi_bull_oversold=momentum_fvg_config.get('rsi_bull_oversold', 40.0),
                momentum_fvg_rsi_bull_overbought=momentum_fvg_config.get('rsi_bull_overbought', 80.0),
                momentum_fvg_rsi_bear_oversold=momentum_fvg_config.get('rsi_bear_oversold', 20.0),
                momentum_fvg_rsi_bear_overbought=momentum_fvg_config.get('rsi_bear_overbought', 60.0),
                momentum_fvg_macd_zero_line_filter_enabled=momentum_fvg_config.get('macd_zero_line_filter_enabled', True),
                momentum_fvg_macd_histogram_momentum_filter_enabled=momentum_fvg_config.get('macd_histogram_momentum_filter_enabled', True),
                momentum_fvg_macd_histogram_expansion_bars=momentum_fvg_config.get('macd_histogram_expansion_bars', 2),
                momentum_fvg_rsi_macd_confluence_enabled=momentum_fvg_config.get('rsi_macd_confluence_enabled', True),
                
                # Liquidity tiers
                momentum_fvg_liquidity_high_threshold=liquidity_tiers.get('high_threshold', 200),
                momentum_fvg_liquidity_high_size_factor=liquidity_tiers.get('high_size_factor', 1.0),
                momentum_fvg_liquidity_medium_threshold=liquidity_tiers.get('medium_threshold', 80),
                momentum_fvg_liquidity_medium_size_factor=liquidity_tiers.get('medium_size_factor', 0.75),
                momentum_fvg_liquidity_low_threshold=liquidity_tiers.get('low_threshold', 40),
                momentum_fvg_liquidity_low_size_factor=liquidity_tiers.get('low_size_factor', 0.5),
                momentum_fvg_liquidity_ultra_low_threshold=liquidity_tiers.get('ultra_low_threshold', 25),
                momentum_fvg_liquidity_ultra_low_size_factor=liquidity_tiers.get('ultra_low_size_factor', 0.25),
                momentum_fvg_liquidity_min_threshold=liquidity_tiers.get('min_threshold', 25),
                momentum_fvg_liquidity_min_size_factor=liquidity_tiers.get('min_size_factor', 0.0),
                
                # Spread gate interaction
                momentum_fvg_spread_gate_cents=momentum_fvg_config.get('spread_gate_cents', 40),
                momentum_fvg_spread_gate_obi_persistence_boost=momentum_fvg_config.get('spread_gate_obi_persistence_boost', 0.75),
                
                max_cycle_risk_pct=self._normalize_percentage_value(raw.get('max_cycle_risk_pct', 0.05)),  # CRITICAL FIX: 5% - aligned with profile
                max_cycle_risk_usd=raw.get('max_cycle_risk_usd', 0.0),
                
                # Venue-level caps (percentage-based, normalize dict format)
                venue_max_single_order_pct=self._normalize_percentage_value(venue.get('max_single_order_pct', 0.05)),
                venue_max_total_notional_pct=self._normalize_percentage_value(venue.get('max_total_notional_pct', 0.15)),  # FIXED: Default 0.15 to match YAML (15% total venue cap)
                venue_max_category_notional_pct=self._normalize_percentage_value(venue.get('max_category_notional_pct', 0.10)),  # FIXED: Increased from 0.05 to 0.10 to match YAML
                venue_bankroll_cap_pct=self._normalize_percentage_value(venue.get('bankroll_cap_pct', 0.02)),  # Default 2% if not specified
                venue_max_orders_per_minute=venue.get('max_orders_per_minute', 30),
                venue_max_orders_per_hour=venue.get('max_orders_per_hour', 300),
                
                # Computed venue caps (USD, derived from capital)
                venue_max_single_order_usd=venue_max_single_order_usd,
                venue_max_total_notional_usd=venue_max_total_notional_usd,
                venue_max_category_notional_usd=venue_max_category_notional_usd,
                
                # Per-asset caps
                asset_configs=asset_configs,
                
                # Per-agent defaults (percentage-based, normalize dict format)
                agent_max_notional_pct=self._normalize_percentage_value(agent_defaults.get('max_notional_pct', 0.03)),  # FIXED: Default 0.03 to match YAML (3% per agent)
                agent_max_orders_per_window=agent_defaults.get('max_orders_per_window', 20),  # FIXED: Default 20 to match YAML (was 3)
                agent_max_yes_position=agent_defaults.get('max_yes_position', 3),
                agent_max_no_position=agent_defaults.get('max_no_position', 3),
                agent_max_concurrent_trades=agent_defaults.get('max_concurrent_trades', 5),  # FIXED: Default 5 to match YAML (was 3),
                agent_minutes_before_expiry=agent_defaults.get('minutes_before_expiry', 30),
                agent_cutoff_minutes_before_expiry=agent_defaults.get('cutoff_minutes_before_expiry', 2),
                
                # Computed agent defaults (USD, derived from capital)
                agent_max_notional_usd=agent_max_notional_usd,
                
                # Confidence
                confidence_use_crypto_threshold_matrix=confidence.get('use_crypto_threshold_matrix', True),
                confidence_profile_name=confidence.get('profile_name', 'modern_tradeable_kalshi_v1'),
                confidence_min_confidence_threshold=confidence.get('min_confidence_threshold', 0.65),  # 2026-07-06: Primary threshold from YAML
                confidence_kelly_multiplier_no_trade=confidence.get('kelly_multiplier_no_trade', 0.0),
                confidence_kelly_multiplier_cautious=confidence.get('kelly_multiplier_cautious', 0.5),
                confidence_kelly_multiplier_quick_win=confidence.get('kelly_multiplier_quick_win', 0.6),
                confidence_kelly_multiplier_confident=confidence.get('kelly_multiplier_confident', 1.0),
                
                # Guardrails (normalize dict format for percentage fields)
                guardrails_max_spread_cents=guardrails.get('max_spread_cents', 30),  # FIXED: Default 30 to match YAML (was 10)
                guardrails_max_slippage_cents=guardrails.get('max_slippage_cents', 3),
                guardrails_min_depth_contracts=guardrails.get('min_depth_contracts', 5),
                guardrails_min_post_fee_edge=self._normalize_percentage_value(guardrails.get('min_post_fee_edge', 0.02)),  # FIXED: Default 0.02 to match YAML (was 0.01)
                guardrails_per_trade_risk_pct=guardrails_per_trade_risk_pct,  # Per-trade risk percentage (sizing control)
                guardrails_min_time_to_expiry_min=guardrails.get('min_time_to_expiry_min', 2.5),  # FIXED: Default 2.5 to match YAML (was 3)
                guardrails_per_window_risk_pct=guardrails_per_window_risk_pct,  # 3% per agent per 15m window (HARD STOP)
                guardrails_total_venue_risk_pct=guardrails_total_venue_risk_pct,  # 5% total across all agents per 15m window (HARD STOP)
                guardrails_drawdown_halt_pct=guardrails_drawdown_halt_pct,
                guardrails_drawdown_unwind_pct=guardrails_drawdown_unwind_pct,
                guardrails_max_daily_loss_usd=guardrails.get('max_daily_loss_usd', 200.0),
                guardrails_max_position_value_usd=guardrails.get('max_position_value_usd', 100000.0),  # Default $100k
                # OTM filtering for 15-minute crypto
                guardrails_max_dist_pct_trade=guardrails.get('max_dist_pct_trade', 2.5),  # CRITICAL FIX: Default 2.5 to match YAML (was 2.0)
                guardrails_min_contract_price_cents=guardrails.get('min_contract_price_cents', 10),  # CRITICAL FIX: Default 10c to match YAML (10c minimum for momentum-based trading)
                guardrails_max_contract_price_cents=guardrails.get('max_contract_price_cents', 75),  # CRITICAL FIX: Default 75c to match YAML (75c sweet spot threshold - intentional)
                guardrails_max_same_side_per_strip=guardrails.get('max_same_side_per_strip', 5),  # CRITICAL FIX: Default 5 to match YAML (was 2)
                # Time trap prevention (entry window narrowing)
                guardrails_max_entry_mins=guardrails.get('max_entry_mins', 15.0),  # CRITICAL FIX: Default 15 to match YAML (was 12)
                guardrails_min_entry_mins=guardrails.get('min_entry_mins', 2.0),  # Default 2 minutes
                # Microstructure trap prevention
                guardrails_depth_size_multiplier=guardrails.get('depth_size_multiplier', 3.0),  # Default 3x
                # Regime/drawdown trap prevention
                guardrails_regime_cooldown_enabled=guardrails.get('regime_cooldown_enabled', False),  # Default disabled
                guardrails_regime_cooldown_min_trades=guardrails.get('regime_cooldown_min_trades', 20),  # Default 20 trades
                guardrails_regime_cooldown_min_winrate=guardrails.get('regime_cooldown_min_winrate', 0.4),  # Default 40%
                guardrails_regime_cooldown_max_loss_pct=guardrails.get('regime_cooldown_max_loss_pct', 0.1),  # Default 10%
                # Experimental slice configuration
                guardrails_experimental_price_band_enabled=guardrails.get('experimental_price_band_enabled', False),  # Default disabled
                guardrails_experimental_min_price_cents=guardrails.get('experimental_min_price_cents', 45),  # Default 45c
                guardrails_experimental_max_price_cents=guardrails.get('experimental_max_price_cents', 60),  # Default 60c
                guardrails_experimental_tte_band_enabled=guardrails.get('experimental_tte_band_enabled', False),  # Default disabled
                guardrails_experimental_min_tte_min=guardrails.get('experimental_min_tte_min', 4.0),  # Default 4min
                guardrails_experimental_max_tte_min=guardrails.get('experimental_max_tte_min', 7.0),  # Default 7min
                
                # Kelly sizing (normalize dict format for percentage fields)
                # P1-FIX1: fallback default 0.02 to match profile (2% Kelly hard cap)
                kelly_hard_cap=self._normalize_percentage_value(kelly.get('kelly_hard_cap', 0.02)),
                kelly_min_edge_pct=self._normalize_percentage_value(kelly.get('kelly_min_edge_pct', 1.0)),
                kelly_max_edge_pct=self._normalize_percentage_value(kelly.get('kelly_max_edge_pct', 25.0)),
                kelly_min_win_prob=kelly.get('kelly_min_win_prob', 0.01),
                kelly_max_win_prob=kelly.get('kelly_max_win_prob', 0.99),
                kelly_global_notional_cap_pct=self._normalize_percentage_value(kelly.get('kelly_global_notional_cap_pct', 0.02)),  # P2-FIX6: fallback default 0.02 to match profile (2% global Kelly cap)
                
                # Contract caps
                contract_caps_max_contracts_total=contract_caps.get('max_contracts_total', 5000),
                contract_caps_max_contracts_per_asset=contract_caps.get('max_contracts_per_asset', 1750),
                contract_caps_max_contracts_per_cluster=contract_caps.get('max_contracts_per_cluster', 750),
                # Handle nested dict format for max_single_order_contracts
                contract_caps_max_single_order_contracts=self._normalize_contracts_value(
                    contract_caps.get('max_single_order_contracts', 10)
                ),
                
                # Risk policy (normalize dict format for percentage fields)
                # 2026 BEST PRACTICE: Load dynamic percentage-based group notional cap parameters
                risk_policy_group_notional_cap_pct=self._normalize_percentage_value(risk_policy.get('group_notional_cap_pct', 0.05)),
                risk_policy_group_notional_cap_min_usd=float(risk_policy.get('group_notional_cap_min_usd', 5.00)),
                risk_policy_group_notional_cap_max_usd=float(risk_policy.get('group_notional_cap_max_usd', 2000.0)),
                risk_policy_max_fee_to_notional_pct=self._normalize_percentage_value(risk_policy.get('max_fee_to_notional_pct', 15.0)),
                
                # Strategy policy (normalize dict format for percentage fields)
                strategy_policy_min_edge=self._normalize_percentage_value(strategy_policy.get('min_edge', 0.05)),
                strategy_policy_min_confidence=strategy_policy.get('min_confidence', 0.50),
                strategy_policy_max_md_staleness_sec=float(strategy_policy.get('max_md_staleness_sec', 120.0)),
                
                # Throttling (order rate limits)
                throttling_global_orders_window_sec=float(throttling.get('global_orders_window_sec', 60.0)),
                throttling_global_orders_limit=int(throttling.get('global_orders_limit', 20)),
                throttling_per_asset_cooldown_sec=float(throttling.get('per_asset_cooldown_sec', 10.0)),
                throttling_per_strip_order_limit=int(throttling.get('per_strip_order_limit', 1)),
                throttling_per_strip_notional_usd=float(throttling.get('per_strip_notional_usd', 0.0)),
                throttling_max_orders_per_15m_window=int(throttling.get('max_orders_per_15m_window', 5)),
                throttling_consecutive_loss_pause=int(throttling.get('consecutive_loss_pause', 3)),
                throttling_max_session_risk_pct=self._normalize_percentage_value(throttling.get('max_session_risk_pct', 0.10)),
                
                # Universe liquidity filters (coarse prefilter)
                universe_min_volume=int(universe.get('min_volume', 5)),
                universe_min_open_interest=int(universe.get('min_open_interest', 1)),
                universe_max_spread_cents=int(universe.get('max_spread_cents', 30)),
                
                # Failsafe configuration (emergency brake)
                failsafe_max_contracts_per_order=int(failsafe.get('max_contracts_per_order', 1)),
                
                # Edge/lag filter configuration
                edge_lag_filter_min_edge_lag_ratio=raw.get('edge_lag_filter', {}).get('min_edge_lag_ratio', {}),
                edge_lag_filter_enabled=raw.get('edge_lag_filter', {}).get('edge_lag_filter_enabled', {}),
                edge_lag_filter_cold_start_min_samples=raw.get('edge_lag_filter', {}).get('cold_start_min_samples', 100),
                
                # Venue invariants (normalize dict format)
                venue_invariants_valid_price_cents_min=self._normalize_contracts_value(raw.get('venue_invariants', {}).get('valid_price_cents_min', 20)),  # CRITICAL: Default 20c to match guardrail
                venue_invariants_valid_price_cents_max=self._normalize_contracts_value(raw.get('venue_invariants', {}).get('valid_price_cents_max', 99)),
                venue_invariants_deep_otm_threshold_cents=self._normalize_contracts_value(raw.get('venue_invariants', {}).get('deep_otm_threshold_cents', 5)),
                venue_invariants_deep_itm_threshold_cents=self._normalize_contracts_value(raw.get('venue_invariants', {}).get('deep_itm_threshold_cents', 95)),
                venue_invariants_ioc_auto_below_seconds=self._normalize_contracts_value(raw.get('venue_invariants', {}).get('ioc_auto_below_seconds', 120)),
                venue_invariants_max_book_staleness_ms=self._normalize_contracts_value(raw.get('venue_invariants', {}).get('max_book_staleness_ms', 30000)),
                
                # Legacy path control
                legacy_disable_balance_calibration=legacy.get('disable_balance_calibration', True),
                legacy_disable_dynamic_contract_caps=legacy.get('disable_dynamic_contract_caps', True),
                legacy_disable_bankroll_category_limits=legacy.get('disable_bankroll_category_limits', True),
                legacy_disable_bankroll_prediction_risk=legacy.get('disable_bankroll_prediction_risk', True),
                legacy_disable_bankroll_guardrails=legacy.get('disable_bankroll_guardrails', True),
                
                # Velocity model coefficients (Phase 1: Logistic mapping)
                velocity_model_alpha_0_btc=velocity_model.get('BTC', {}).get('alpha_0', 0.0),
                velocity_model_alpha_1_btc=velocity_model.get('BTC', {}).get('alpha_1', 200.0),
                velocity_model_alpha_0_eth=velocity_model.get('ETH', {}).get('alpha_0', 0.0),
                velocity_model_alpha_1_eth=velocity_model.get('ETH', {}).get('alpha_1', 200.0),
                velocity_model_alpha_0_sol=velocity_model.get('SOL', {}).get('alpha_0', 0.0),
                velocity_model_alpha_1_sol=velocity_model.get('SOL', {}).get('alpha_1', 300.0),
                velocity_model_alpha_0_xrp=velocity_model.get('XRP', {}).get('alpha_0', 0.0),
                velocity_model_alpha_1_xrp=velocity_model.get('XRP', {}).get('alpha_1', 300.0),
                velocity_model_alpha_0_doge=velocity_model.get('DOGE', {}).get('alpha_0', 0.0),
                velocity_model_alpha_1_doge=velocity_model.get('DOGE', {}).get('alpha_1', 500.0),
                # Velocity thresholds (per-asset, aligned with actual market velocities)
                # CRITICAL FIX: 2026-07-05 - Reduced to effectively zero to enable any trading
                # Actual market velocities observed: 0.000%-0.04% (from live logs 2026-07-05)
                velocity_threshold_btc=raw.get('velocity_thresholds', {}).get('BTC', 0.00001),
                velocity_threshold_eth=raw.get('velocity_thresholds', {}).get('ETH', 0.00001),
                velocity_threshold_sol=raw.get('velocity_thresholds', {}).get('SOL', 0.00001),
                velocity_threshold_xrp=raw.get('velocity_thresholds', {}).get('XRP', 0.00001),
                velocity_threshold_doge=raw.get('velocity_thresholds', {}).get('DOGE', 0.00001),
                # Phase 4.1: Multi-window velocity weights
                momentum_weights_windows=raw.get('momentum_weights', {}).get('windows', [10, 30, 60]),
                momentum_weights_values=raw.get('momentum_weights', {}).get('weights', [0.2, 0.3, 0.5]),
                # Phase 4.4: Logit fusion weights
                logit_fusion_velocity_weight=raw.get('logit_fusion_weights', {}).get('velocity_logit', 0.7),
                logit_fusion_mean_reversion_weight=raw.get('logit_fusion_weights', {}).get('mean_reversion_logit', 0.3),
                # Phase 4.5: Near expiry guard
                near_expiry_guard_sec=raw.get('near_expiry_guard_sec', 300),
                # Phase 5.2: Calibration configuration
                calibration_enabled=raw.get('calibration_config', {}).get('enabled', False),
                calibration_auto_fit=raw.get('calibration_config', {}).get('auto_fit', True),
                calibration_min_samples=raw.get('calibration_config', {}).get('min_samples_for_fit', 100),
                calibration_max_samples=raw.get('calibration_config', {}).get('max_samples', 1000),
                calibration_regularization=raw.get('calibration_config', {}).get('regularization', 0.0001),
                calibration_fit_interval_hours=raw.get('calibration_config', {}).get('fit_interval_hours', 24),
                # Phase 1: Fee-aware edge gate configuration
                fee_aware_edge_enabled=raw.get('fee_aware_edge', {}).get('enabled', True),
                fee_aware_edge_min_edge_cents=raw.get('fee_aware_edge', {}).get('min_edge_cents', 2.0),
                fee_aware_edge_fee_per_contract=raw.get('fee_aware_edge', {}).get('fee_per_contract', 0.07),
                # Phase 1: Market microstructure filters configuration
                market_microstructure_enabled=raw.get('market_microstructure', {}).get('enabled', True),
                market_microstructure_max_spread_cents=raw.get('market_microstructure', {}).get('max_spread_cents', 50.0),
                market_microstructure_min_depth_usd=raw.get('market_microstructure', {}).get('min_depth_usd', 0.0),
                market_microstructure_min_yes_depth=raw.get('market_microstructure', {}).get('min_yes_depth', 1),
                market_microstructure_min_no_depth=raw.get('market_microstructure', {}).get('min_no_depth', 1),
                # Position Management: Offset Hedging Configuration
                offset_hedging_enabled=raw.get('offset_hedging', {}).get('enabled', False),
                offset_hedging_hedge_ratio=raw.get('offset_hedging', {}).get('hedge_ratio', 0.30),
                offset_hedging_min_edge_for_hedge=raw.get('offset_hedging', {}).get('min_edge_for_hedge', 0.03),
                offset_hedging_max_hedge_notional_pct=raw.get('offset_hedging', {}).get('max_hedge_notional_pct', 0.02),
                offset_hedging_rebalance_threshold=raw.get('offset_hedging', {}).get('rebalance_threshold', 0.05),
                offset_hedging_min_hedge_contracts=raw.get('offset_hedging', {}).get('min_hedge_contracts', 1),
                offset_hedging_max_hedge_contracts=raw.get('offset_hedging', {}).get('max_hedge_contracts', 3),
                # Position Management: Trailing Stop Configuration
                trailing_stop_enabled=raw.get('trailing_stop', {}).get('enabled', False),
                trailing_stop_trailing_distance_cents=raw.get('trailing_stop', {}).get('trailing_distance_cents', 5),
                trailing_stop_trailing_distance_cents_profit_zone=raw.get('trailing_stop', {}).get('trailing_distance_cents_profit_zone', 2),  # CRITICAL FIX: 2026-07-06
                trailing_stop_min_profit_cents=raw.get('trailing_stop', {}).get('min_profit_cents', 12),
                trailing_stop_activation_delay_sec=raw.get('trailing_stop', {}).get('activation_delay_sec', 30),
                trailing_stop_profit_zone_activation_cents=raw.get('trailing_stop', {}).get('profit_zone_activation_cents', 80),  # CRITICAL FIX: 2026-07-06
                # Position Management: Ratchet Profit Floor Configuration
                ratchet_profit_floor_enabled=raw.get('ratchet_profit_floor', {}).get('enabled', True),
                ratchet_activation_threshold_cents=raw.get('ratchet_profit_floor', {}).get('activation_threshold_cents', 85),
                ratchet_floor_offset_cents=raw.get('ratchet_profit_floor', {}).get('floor_offset_cents', 5),
                ratchet_force_exit_on_floor_breach=raw.get('ratchet_profit_floor', {}).get('force_exit_on_floor_breach', True),
                ratchet_min_hold_after_activation_sec=raw.get('ratchet_profit_floor', {}).get('min_hold_after_activation_sec', 30),
                # CRITICAL FIX: 2026-07-06 - Removed ratchet_mandatory_exit_at_99c (redundant, handled by position-level extreme profit)
                ratchet_trim_position_enabled=raw.get('ratchet_profit_floor', {}).get('trim_position_enabled', True),
                ratchet_trim_threshold_cents=raw.get('ratchet_profit_floor', {}).get('trim_threshold_cents', 80),
                ratchet_trim_to_contracts=raw.get('ratchet_profit_floor', {}).get('trim_to_contracts', 1),
                # Position Management: Dynamic Take Profit Zones Configuration
                dynamic_take_profit=raw.get('dynamic_take_profit', {}),
                # Position Management: Dynamic Sizing Configuration
                dynamic_sizing_enabled=raw.get('dynamic_sizing', {}).get('enabled', False),
                dynamic_sizing_base_contracts=raw.get('dynamic_sizing', {}).get('base_contracts', 1),
                dynamic_sizing_edge_multiplier=raw.get('dynamic_sizing', {}).get('edge_multiplier', 2.0),
                dynamic_sizing_confidence_multiplier=raw.get('dynamic_sizing', {}).get('confidence_multiplier', 1.0),
                dynamic_sizing_max_contracts=raw.get('dynamic_sizing', {}).get('max_contracts', 3),
                dynamic_sizing_min_contracts=raw.get('dynamic_sizing', {}).get('min_contracts', 1),
                # Phase 2: Strategy definitions
                strategies=strategies,
                
                # 2026 Research-Based Risk Management
                # Correlation-aware position sizing
                correlation_tracking_enabled=raw.get('correlation_tracking', {}).get('enabled', False),
                correlation_tracking_real_time_monitoring=raw.get('correlation_tracking', {}).get('real_time_monitoring', False),
                correlation_tracking_threshold_high=raw.get('correlation_tracking', {}).get('threshold_high', 0.80),
                correlation_tracking_threshold_moderate=raw.get('correlation_tracking', {}).get('threshold_moderate', 0.50),
                correlation_tracking_threshold_alert=raw.get('correlation_tracking', {}).get('threshold_alert', 0.85),
                correlation_tracking_max_correlated_assets=int(raw.get('correlation_tracking', {}).get('max_correlated_assets', 3)),
                
                # Volatility-regime edge adjustment
                volatility_regime_edge_adjustment_enabled=raw.get('volatility_regime_edge_adjustment', {}).get('enabled', True),
                volatility_regime_edge_adjustment_lookback_days=int(raw.get('volatility_regime_edge_adjustment', {}).get('lookback_days', 30)),
                volatility_regime_edge_adjustment_low_volatility_threshold=raw.get('volatility_regime_edge_adjustment', {}).get('low_volatility_threshold', 0.30),
                volatility_regime_edge_adjustment_high_volatility_threshold=raw.get('volatility_regime_edge_adjustment', {}).get('high_volatility_threshold', 0.70),
                volatility_regime_edge_adjustment_low_volatility_adjustment=raw.get('volatility_regime_edge_adjustment', {}).get('low_volatility_adjustment', -0.0025),  # CRITICAL FIX: -0.25% (aligned with profile YAML)
                volatility_regime_edge_adjustment_high_volatility_adjustment=raw.get('volatility_regime_edge_adjustment', {}).get('high_volatility_adjustment', 0.005),  # CRITICAL FIX: +0.5% (aligned with profile YAML)
                
                # Portfolio heat tracking
                portfolio_heat_enabled=raw.get('portfolio_heat', {}).get('enabled', False),
                portfolio_heat_calculation_method=raw.get('portfolio_heat', {}).get('calculation_method', 'correlation_adjusted_exposure'),
                portfolio_heat_heat_threshold_warning=raw.get('portfolio_heat', {}).get('heat_threshold_warning', 0.70),
                portfolio_heat_heat_threshold_critical=raw.get('portfolio_heat', {}).get('heat_threshold_critical', 0.85),
                
                # Time-of-day risk scaling
                time_of_day_risk_scaling_enabled=raw.get('time_of_day_risk_scaling', {}).get('enabled', False),
                time_of_day_risk_scaling_us_market_hours=raw.get('time_of_day_risk_scaling', {}).get('us_market_hours', '09:30-16:00 ET'),
                time_of_day_risk_scaling_asian_session=raw.get('time_of_day_risk_scaling', {}).get('asian_session', '20:00-02:00 ET'),
                time_of_day_risk_scaling_european_session=raw.get('time_of_day_risk_scaling', {}).get('european_session', '02:00-09:30 ET'),
                time_of_day_risk_scaling_us_market_multiplier=raw.get('time_of_day_risk_scaling', {}).get('us_market_multiplier', 1.0),
                time_of_day_risk_scaling_asian_multiplier=raw.get('time_of_day_risk_scaling', {}).get('asian_multiplier', 0.8),
                time_of_day_risk_scaling_european_multiplier=raw.get('time_of_day_risk_scaling', {}).get('european_multiplier', 0.9),
                time_of_day_risk_scaling_weekend_multiplier=raw.get('time_of_day_risk_scaling', {}).get('weekend_multiplier', 0.8),  # RELAXED: 0.8 (was 0.5)
                
                # Asset-specific rolling PnL limits
                asset_specific_rolling_pnl_enabled=raw.get('asset_specific_rolling_pnl', {}).get('enabled', False),
                asset_specific_rolling_pnl_btc_rolling_1h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('btc_rolling_1h_halt_pct', 0.04),
                asset_specific_rolling_pnl_btc_rolling_4h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('btc_rolling_4h_halt_pct', 0.07),
                asset_specific_rolling_pnl_eth_rolling_1h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('eth_rolling_1h_halt_pct', 0.04),
                asset_specific_rolling_pnl_eth_rolling_4h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('eth_rolling_4h_halt_pct', 0.07),
                asset_specific_rolling_pnl_sol_rolling_1h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('sol_rolling_1h_halt_pct', 0.06),
                asset_specific_rolling_pnl_sol_rolling_4h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('sol_rolling_4h_halt_pct', 0.09),
                asset_specific_rolling_pnl_xrp_rolling_1h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('xrp_rolling_1h_halt_pct', 0.06),
                asset_specific_rolling_pnl_xrp_rolling_4h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('xrp_rolling_4h_halt_pct', 0.09),
                asset_specific_rolling_pnl_doge_rolling_1h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('doge_rolling_1h_halt_pct', 0.08),
                asset_specific_rolling_pnl_doge_rolling_4h_halt_pct=raw.get('asset_specific_rolling_pnl', {}).get('doge_rolling_4h_halt_pct', 0.12),
                
                # Updated adaptive risk bands (2026 research: more granular)
                guardrails_adaptive_risk_bands=guardrails.get('adaptive_risk_bands', []),
            )
            
            logger.info(f"[Crypto15mProfileAdapter] Loaded profile {self._profile.profile_name} v{self._profile.profile_version}")
            
        except Exception as e:
            logger.error(f"[Crypto15mProfileAdapter] Failed to load profile from {self.profile_path}: {e}")
            raise
    
    @property
    def profile(self) -> Crypto15mProfile:
        """Get the loaded profile."""
        if self._profile is None:
            raise RuntimeError("Profile not loaded")
        return self._profile
    
    def to_kalshi_risk_config(self) -> Dict[str, Any]:
        """
        Map profile to KalshiRiskConfig parameters.
        
        For kalshi_crypto_15m_v2, this is a thin adapter that uses envelope values.
        The envelope is the single source of truth for drawdown and daily loss.
        
        Returns:
            Dict with keys matching KalshiRiskConfig dataclass fields.
        """
        p = self._profile
        
        # For kalshi_crypto_15m_v2, use envelope values for drawdown/daily loss
        # The envelope is the single source of truth
        envelope = None
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            service = get_risk_envelope_service()
            config = service.get_config()
            envelope = config  # Store for later use
            
            # For backward compatibility, map RiskEnvelopeConfig to envelope-like fields
            drawdown_halt_pct = config.drawdown_halt_pct if hasattr(config, 'drawdown_halt_pct') else p.guardrails_drawdown_halt_pct
            drawdown_unwind_pct = config.drawdown_unwind_pct if hasattr(config, 'drawdown_unwind_pct') else p.guardrails_drawdown_unwind_pct
            max_daily_loss_usd = config.max_daily_loss_usd if hasattr(config, 'max_daily_loss_usd') else float('inf')
            kelly_fraction = config.kelly_fraction if hasattr(config, 'kelly_fraction') else 0.05  # P1-FIX1: 0.30 -> 0.05
            max_single_order_notional_usd = config.max_single_order_notional_usd
            max_total_notional_usd = config.max_total_notional_usd
        except Exception as e:
            logger.warning(f"[PROFILE-ADAPTER] Failed to load envelope via RiskEnvelopeService, using profile defaults: {e}")
            drawdown_halt_pct = p.guardrails_drawdown_halt_pct
            drawdown_unwind_pct = p.guardrails_drawdown_unwind_pct
            max_daily_loss_usd = p.guardrails_max_daily_loss_usd
            kelly_fraction = p.kelly_hard_cap
            # Fallback to profile YAML static values
            max_single_order_notional_usd = p.venue_max_single_order_usd
            max_total_notional_usd = p.venue_max_total_notional_usd
        
        # Extract per-asset max_contracts and max_notional from envelope
        per_asset_max_contracts = {}
        asset_max_notional_usd = {}
        for asset_name, asset_config in p.asset_configs.items():
            # Normalize max_contracts to handle dict format
            per_asset_max_contracts[asset_name] = self._normalize_contracts_value(asset_config.max_contracts)
            # Get max_notional from envelope (with floor applied)
            if envelope and hasattr(envelope, 'asset_max_notional_usd'):
                asset_max_notional_usd[asset_name] = envelope.asset_max_notional_usd.get(asset_name)
        
        # Also store on profile object for direct access by agents
        p.asset_max_notional_usd = asset_max_notional_usd
        
        return {
            'min_notional_usd': p.min_notional_usd,  # Minimum notional per trade (from profile)
            'asset_max_notional_usd': asset_max_notional_usd,  # Per-asset max_notional with floor (from envelope)
            'min_contracts': p.min_contracts,  # Minimum contracts per trade (from profile)
            'max_single_order_notional_usd': float(max_single_order_notional_usd),  # Ensure float type
            'max_total_notional_usd': float(max_total_notional_usd),  # Ensure float type
            'max_daily_loss_usd': float(max_daily_loss_usd),  # Ensure float type
            'max_single_order_contracts': int(p.contract_caps_max_single_order_contracts),  # From profile (ensure int type)
            'max_position_per_contract': 500,
            'kelly_hard_cap': kelly_fraction,
            'kelly_max_edge_pct': p.kelly_max_edge_pct,
            'kelly_min_edge_pct': p.kelly_min_edge_pct,
            'kelly_min_win_prob': p.kelly_min_win_prob,
            'kelly_max_win_prob': p.kelly_max_win_prob,
            'kelly_global_notional_cap_pct': p.kelly_global_notional_cap_pct,
            'max_fee_to_notional_pct': p.risk_policy_max_fee_to_notional_pct,  # From profile
            'min_edge': p.strategy_policy_min_edge,  # From profile strategy policy
            'bankroll_cap_pct': p.venue_bankroll_cap_pct,  # From profile venue (overrides MERID_BANKROLL_CAP_PCT env)
            'valid_price_cents_min': p.venue_invariants_valid_price_cents_min,  # From profile venue invariants
            'valid_price_cents_max': p.venue_invariants_valid_price_cents_max,  # From profile venue invariants
            'max_contracts_total': int(p.contract_caps_max_contracts_total),  # From profile (ensure int type)
            'max_contracts_per_asset': int(p.contract_caps_max_contracts_per_asset),  # From profile (ensure int type)
            'max_contracts_per_cluster': int(p.contract_caps_max_contracts_per_cluster),  # From profile (ensure int type)
            # 2026 BEST PRACTICE: Compute dynamic group notional cap from bankroll
            # Uses percentage-based approach with min/max floors to follow industry best practices
            'group_notional_cap_usd': self._compute_dynamic_group_notional_cap(
                bankroll_usd=asset_max_notional_usd.get('BTC', 0.0) * 5 if asset_max_notional_usd else 1000.0,  # Rough estimate from asset caps
                pct=p.risk_policy_group_notional_cap_pct,
                min_usd=p.risk_policy_group_notional_cap_min_usd,
                max_usd=p.risk_policy_group_notional_cap_max_usd
            ),
            'group_limits_enabled': True,  # Enable group-level aggregation and caps
            'drawdown_halt_pct': drawdown_halt_pct,
            'drawdown_unwind_pct': drawdown_unwind_pct,
            'min_post_fee_edge': p.guardrails_min_post_fee_edge,
            'default_notional_to_equity_multiplier': 2.0,
            'max_orders_per_minute': p.venue_max_orders_per_minute,
            'max_orders_per_hour': p.venue_max_orders_per_hour,
            'per_asset_max_contracts': per_asset_max_contracts,  # Per-asset max contracts from profile
            # CRITICAL FIX: Add cluster stop loss with sensible defaults to prevent order blocking
            'max_stop_loss_usd_per_cluster': 2.00,  # $2.00 aggregate cluster stop-loss (sensible default)
            'per_asset_cluster_stop_loss': {'BTC': 2.00, 'ETH': 2.00, 'SOL': 2.00, 'XRP': 2.00, 'DOGE': 2.00},  # Per-asset cluster stop-loss
            'bankroll_cap_pct': p.venue_bankroll_cap_pct,  # Bankroll cap percentage from profile (2026 best practice)
            'category_limits': {
                'crypto': {
                    'category': 'crypto',
                    'max_notional_usd': p.venue_max_category_notional_usd,
                    'max_contracts': 500,
                    'max_pct_of_portfolio': 0.20,
                    'enabled': True,
                }
            },
        }
    
    def _compute_dynamic_group_notional_cap(self, bankroll_usd: float, pct: float, min_usd: float, max_usd: float) -> float:
        """
        Compute dynamic group notional cap from bankroll using percentage-based approach.
        
        2026 BEST PRACTICE: Follows industry best practices for prediction market risk management:
        - Uses percentage-based sizing (2-5% of bankroll per position)
        - Ensures minimum floor for small bankrolls (allows trading)
        - Ensures maximum ceiling for large bankrolls (prevents excessive exposure)
        
        Args:
            bankroll_usd: Current bankroll in USD
            pct: Percentage of bankroll to use (e.g., 0.05 for 5%)
            min_usd: Minimum absolute cap in USD (floor for small bankrolls)
            max_usd: Maximum absolute cap in USD (ceiling for large bankrolls)
        
        Returns:
            Dynamic group notional cap in USD, bounded by min/max floors
        """
        # Compute percentage-based cap
        percentage_cap = bankroll_usd * pct
        
        # Apply min/max floors to ensure reasonable bounds
        dynamic_cap = max(min_usd, min(percentage_cap, max_usd))
        
        logger.debug(
            "[DYNAMIC-GROUP-NOTIONAL-CAP] bankroll=$%.2f pct=%.2f%% percentage_cap=$%.2f min=$%.2f max=$%.2f final=$%.2f",
            bankroll_usd, pct * 100, percentage_cap, min_usd, max_usd, dynamic_cap
        )
        
        return dynamic_cap
    
    def _normalize_contracts_value(self, value: Any) -> int:
        """
        Normalize contracts value to int, handling nested dict formats.
        
        Args:
            value: Either an int or a dict with 'value' or 'max_contracts' key.
            
        Returns:
            Integer contracts value.
        """
        if isinstance(value, int):
            return value
        if isinstance(value, dict):
            # Accept typical shapes: {"max_contracts": 500} or {"value": 500}
            if "max_contracts" in value:
                return int(value["max_contracts"])
            elif "value" in value:
                return int(value["value"])
        # Default fallback
        return int(value) if value is not None else 0
    
    def _normalize_percentage_value(self, value: Any) -> float:
        """
        Normalize percentage value to float, handling nested dict formats.
        
        Args:
            value: Either a float/int or a dict with 'value' key.
            
        Returns:
            Float percentage value.
        """
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            # Accept typical shape: {"value": 0.05}
            if "value" in value:
                return float(value["value"])
        # Default fallback
        return float(value) if value is not None else 0.0
    
    def to_category_limits(self) -> Dict[str, Any]:
        """
        Map profile to CategoryLimit for crypto category.
        
        Returns:
            Dict with CategoryLimit parameters for crypto.
        """
        p = self._profile
        
        # Ensure max_contracts is an int (defensive)
        max_contracts = self._normalize_contracts_value(500)
        
        return {
            'crypto': {
                'category': 'crypto',
                'max_notional_usd': p.venue_max_category_notional_usd,
                'max_contracts': max_contracts,
                'max_pct_of_portfolio': 0.20,
                'enabled': True,
            }
        }
    
    def to_cycle_sizing_cap(self) -> Dict[str, Any]:
        """
        Map profile to CycleSizingCap parameters.
        
        Returns:
            Dict with CycleSizingCap parameters.
        """
        p = self._profile
        
        # Cycle risk is percentage-based on capital (not live bankroll)
        max_cycle_risk_usd = p.max_cycle_risk_usd if p.max_cycle_risk_usd > 0 else p.capital_usd * p.max_cycle_risk_pct
        
        return {
            'max_total_notional_usd': max_cycle_risk_usd,
            'max_notional_per_winner_usd': max_cycle_risk_usd / 3,  # Assume 3 winners max
            'capital_usd': p.capital_usd,
            'max_cycle_risk_pct': p.max_cycle_risk_pct,
        }
    
    def to_agent_overrides(self, agent_name: str) -> Dict[str, Any]:
        """
        Map profile to per-agent configuration overrides.
        
        PRODUCTION RESTRICTION: Only applies to BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M.
        All other agents receive empty overrides (profile not applicable).
        
        Args:
            agent_name: Name of the agent (e.g., "BTC_15M")
        
        Returns:
            Dict with agent-specific overrides, or empty dict if agent not in 15m crypto allowlist.
        """
        p = self._profile
        
        # PRODUCTION RESTRICTION: Only apply to 5 15m crypto agents
        allowed_15m_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
        if agent_name.upper() not in allowed_15m_agents:
            logger.info(
                "[PROFILE_RESTRICTION] Agent %s not in 15m crypto allowlist, skipping profile overrides. "
                "Allowed: %s",
                agent_name, sorted(allowed_15m_agents)
            )
            return {}
        
        # Extract asset from agent name (e.g., "BTC_15M" -> "BTC")
        asset = None
        for asset_name in p.asset_configs.keys():
            if asset_name in agent_name.upper():
                asset = asset_name
                break
        
        asset_config = p.asset_configs.get(asset) if asset else None
        
        # CRITICAL FIX: Compute max_notional_usd dynamically from live bankroll
        # If capital_usd is 0 (derive from bankroll), fetch live bankroll and compute USD value
        max_notional_usd = p.agent_max_notional_usd
        if p.capital_usd == 0.0:
            try:
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                live_bankroll_usd = get_equity_for_risk_calc_sync()
                if live_bankroll_usd and live_bankroll_usd > 0:
                    # Compute from live bankroll using agent_max_notional_pct
                    computed_notional = live_bankroll_usd * p.agent_max_notional_pct
                    # Apply minimum floor from profile
                    max_notional_usd = max(computed_notional, p.min_notional_usd)
                    logger.info(
                        "[PROFILE-ADAPTER] Computed max_notional_usd for %s from live bankroll: $%.2f (bankroll: $%.2f, pct: %.2f%%)",
                        agent_name, max_notional_usd, live_bankroll_usd, p.agent_max_notional_pct * 100
                    )
                else:
                    # Fallback to minimum floor if bankroll unavailable
                    max_notional_usd = p.min_notional_usd
                    logger.warning(
                        "[PROFILE-ADAPTER] Live bankroll unavailable for %s, using min_notional_usd: $%.2f",
                        agent_name, max_notional_usd
                    )
            except Exception as e:
                logger.error("[PROFILE-ADAPTER] Failed to compute max_notional_usd from live bankroll for %s: %s", agent_name, e)
                max_notional_usd = p.min_notional_usd
        
        overrides = {
            'max_notional_usd': max_notional_usd,
            'max_orders_per_window': p.agent_max_orders_per_window,
            'max_yes_position': p.agent_max_yes_position,
            'max_no_position': p.agent_max_no_position,
            'minutes_before_expiry': p.agent_minutes_before_expiry,
            'cutoff_minutes_before_expiry': p.agent_cutoff_minutes_before_expiry,
            'signal_mode': p.signal_mode,
            'price_based_buy_threshold': p.price_based_buy_threshold,
            'price_based_sell_threshold': p.price_based_sell_threshold,
        }
        
        # Override with asset-specific config if available
        if asset_config:
            # For asset-specific, also compute dynamically if capital_usd is 0
            asset_max_notional_usd = asset_config.max_notional_usd
            if p.capital_usd == 0.0:
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                    live_bankroll_usd = get_equity_for_risk_calc_sync()
                    if live_bankroll_usd and live_bankroll_usd > 0:
                        # Compute from live bankroll using asset-specific max_notional_pct
                        computed_asset_notional = live_bankroll_usd * asset_config.max_notional_pct
                        # Apply minimum floor from profile
                        asset_max_notional_usd = max(computed_asset_notional, p.min_notional_usd)
                except Exception as e:
                    logger.error("[PROFILE-ADAPTER] Failed to compute asset max_notional_usd from live bankroll for %s: %s", agent_name, e)
                    asset_max_notional_usd = p.min_notional_usd
            
            overrides.update({
                'max_notional_usd': min(max_notional_usd, asset_max_notional_usd),
                # REMOVED: Per-asset min_edge fields - now using profile edge_bands section
                # Edge thresholds come from kalshi_crypto_15m_v2.yaml edge_bands section:
                # - watch_band: 1-2% (log only)
                # - small_band: 2-4% (trade small)
                # - standard_band: >=4% (trade standard)
                # - kelly_min_edge_pct: 2% (hard floor)
            })
        
        return overrides
    
    def should_disable_balance_calibration(self) -> bool:
        """Check if balance calibration should be disabled for this profile."""
        return self._profile.legacy_disable_balance_calibration
    
    def should_disable_dynamic_contract_caps(self) -> bool:
        """Check if dynamic contract caps should be disabled for this profile."""
        return self._profile.legacy_disable_dynamic_contract_caps
    
    def should_disable_bankroll_category_limits(self) -> bool:
        """Check if bankroll-derived category limits should be disabled."""
        return self._profile.legacy_disable_bankroll_category_limits
    
    def should_disable_bankroll_prediction_risk(self) -> bool:
        """Check if bankroll-derived prediction risk should be disabled."""
        return self._profile.legacy_disable_bankroll_prediction_risk
    
    def should_disable_bankroll_guardrails(self) -> bool:
        """Check if bankroll-derived guardrails should be disabled."""
        return self._profile.legacy_disable_bankroll_guardrails


# Singleton instance for the active profile
_active_adapter: Optional[Crypto15mProfileAdapter] = None


def get_crypto_15m_profile() -> Optional[Crypto15mProfile]:
    """
    Get the active Crypto15mProfile object if one is configured.
    
    This function is used by agent_grid_15m.py, fvg_integration.py, and forecasters/fvg.py
    to access momentum_fvg configuration parameters.
    
    Returns:
        Crypto15mProfile if MERID_PROFILE=kalshi_crypto_15m_v2, else None.
    """
    adapter = get_active_profile()
    if adapter is None:
        return None
    return adapter._profile


def get_active_profile() -> Optional[Crypto15mProfileAdapter]:
    """
    Get the active profile adapter if one is configured.
    
    Returns:
        Crypto15mProfileAdapter if MERID_PROFILE=kalshi_crypto_15m_v2, else None.
    """
    global _active_adapter
    
    import os
    
    profile_name = os.environ.get('MERID_PROFILE', '')
    
    if profile_name == 'kalshi_crypto_15m_v2':
        if _active_adapter is None:
            _active_adapter = Crypto15mProfileAdapter()
            logger.info("[PROFILE-ACTIVE] profile=%s config_source=kalshi_crypto_15m.yaml", profile_name)
        return _active_adapter
    
    return None


def is_profile_active() -> bool:
    """Check if the kalshi_crypto_15m profile is active."""
    import os
    profile_name = os.environ.get('MERID_PROFILE', '').strip()
    
    # CRITICAL FIX: Add validation for empty/invalid profile names
    if not profile_name:
        return False
    
    # CRITICAL FIX: Case-sensitive validation with logging
    is_active = profile_name == 'kalshi_crypto_15m_v2'
    if is_active:
        logger.info("[PROFILE-ACTIVE] kalshi_crypto_15m_v2 profile is active")
    elif profile_name.startswith('kalshi_crypto'):
        logger.warning("[PROFILE-ACTIVE] Similar profile detected: %s (not kalshi_crypto_15m_v2)", profile_name)
    
    return is_active


def runtime_profile_self_check() -> bool:
    """
    Runtime self-check at startup to verify profile is correctly loaded and effective caps match.
    
    This function logs the effective risk caps for BTC/ETH/SOL/XRP/DOGE 15m and verifies
    they match the profile values. Should be called at startup to fail fast if configuration
    is incorrect.
    
    Returns:
        True if all checks pass, False otherwise.
    
    Raises:
        RuntimeError: If profile is active but critical caps don't match.
    """
    if not is_profile_active():
        logger.info("[PROFILE_SELF_CHECK] Profile kalshi_crypto_15m_v2 is not active, skipping self-check")
        return True
    
    adapter = get_active_profile()
    if adapter is None:
        logger.error("[PROFILE_SELF_CHECK] Profile should be active but adapter is None")
        return False
    
    profile = adapter.profile
    
    logger.info("[PROFILE_SELF_CHECK] Verifying kalshi_crypto_15m_v2 profile configuration...")
    logger.info(f"[PROFILE_SELF_CHECK] Profile: {profile.profile_name} v{profile.profile_version}")
    logger.info(f"[PROFILE_SELF_CHECK] Description: {profile.description}")
    
    # Log venue-level caps
    logger.info("[PROFILE_SELF_CHECK] Venue-level caps:")
    logger.info(f"  - max_single_order_usd: ${profile.venue_max_single_order_usd:.2f}")
    logger.info(f"  - max_total_notional_usd: ${profile.venue_max_total_notional_usd:.2f}")
    logger.info(f"  - max_category_notional_usd: ${profile.venue_max_category_notional_usd:.2f}")
    logger.info(f"  - max_orders_per_minute: {profile.venue_max_orders_per_minute}")
    logger.info(f"  - max_orders_per_hour: {profile.venue_max_orders_per_hour}")
    
    # Log per-asset caps
    logger.info("[PROFILE_SELF_CHECK] Per-asset caps:")
    for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
        if asset in profile.asset_configs:
            asset_config = profile.asset_configs[asset]
            logger.info(f"  - {asset}: max_notional_usd=${asset_config.max_notional_usd:.2f}, max_contracts={asset_config.max_contracts}")
        else:
            logger.warning(f"  - {asset}: NOT FOUND in profile")
    
    # Log agent defaults
    logger.info("[PROFILE_SELF_CHECK] Agent defaults:")
    logger.info(f"  - max_notional_usd: ${profile.agent_max_notional_usd:.2f}")
    logger.info(f"  - max_orders_per_window: {profile.agent_max_orders_per_window}")
    logger.info(f"  - max_yes_position: {profile.agent_max_yes_position}")
    logger.info(f"  - max_no_position: {profile.agent_max_no_position}")
    
    # Log cycle sizing
    logger.info("[PROFILE_SELF_CHECK] Cycle sizing:")
    logger.info(f"  - capital_usd: ${profile.capital_usd:.2f}")
    logger.info(f"  - max_cycle_risk_pct: {profile.max_cycle_risk_pct:.2%}")
    cycle_risk_usd = profile.capital_usd * profile.max_cycle_risk_pct
    logger.info(f"  - max_cycle_risk_usd: ${cycle_risk_usd:.2f}")
    
    # Log guardrails
    logger.info("[PROFILE_SELF_CHECK] Guardrails:")
    logger.info(f"  - max_spread_cents: {profile.guardrails_max_spread_cents}")
    logger.info(f"  - max_slippage_cents: {profile.guardrails_max_slippage_cents}")
    logger.info(f"  - min_depth_contracts: {profile.guardrails_min_depth_contracts}")
    logger.info(f"  - min_post_fee_edge: {profile.guardrails_min_post_fee_edge:.2%}")
    logger.info(f"  - drawdown_halt_pct: {profile.guardrails_drawdown_halt_pct:.2%}")
    logger.info(f"  - drawdown_unwind_pct: {profile.guardrails_drawdown_unwind_pct:.2%}")
    logger.info(f"  - max_daily_loss_usd: ${profile.guardrails_max_daily_loss_usd:.2f}")
    
    # Log Kelly parameters
    logger.info("[PROFILE_SELF_CHECK] Kelly sizing:")
    logger.info(f"  - kelly_hard_cap: {profile.kelly_hard_cap:.2%}")
    logger.info(f"  - kelly_min_edge_pct: {profile.kelly_min_edge_pct:.2%}")
    logger.info(f"  - kelly_max_edge_pct: {profile.kelly_max_edge_pct:.2%}")
    logger.info(f"  - kelly_global_notional_cap_pct: {profile.kelly_global_notional_cap_pct:.2%}")
    
    # Verify legacy flags are set correctly
    logger.info("[PROFILE_SELF_CHECK] Legacy path control:")
    logger.info(f"  - disable_balance_calibration: {profile.legacy_disable_balance_calibration}")
    logger.info(f"  - disable_dynamic_contract_caps: {profile.legacy_disable_dynamic_contract_caps}")
    logger.info(f"  - disable_bankroll_category_limits: {profile.legacy_disable_bankroll_category_limits}")
    logger.info(f"  - disable_bankroll_prediction_risk: {profile.legacy_disable_bankroll_prediction_risk}")
    logger.info(f"  - disable_bankroll_guardrails: {profile.legacy_disable_bankroll_guardrails}")
    
    # Critical checks - fail if these are not set correctly
    if not profile.legacy_disable_balance_calibration:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_balance_calibration must be True")
        return False
    
    if not profile.legacy_disable_dynamic_contract_caps:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_dynamic_contract_caps must be True")
        return False
    
    if not profile.legacy_disable_bankroll_category_limits:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_bankroll_category_limits must be True")
        return False
    
    if not profile.legacy_disable_bankroll_prediction_risk:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_bankroll_prediction_risk must be True")
        return False
    
    if not profile.legacy_disable_bankroll_guardrails:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_bankroll_guardrails must be True")
        return False
    
    # Verify all expected assets are present
    expected_assets = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
    missing_assets = expected_assets - set(profile.asset_configs.keys())
    if missing_assets:
        logger.error(f"[PROFILE_SELF_CHECK] FAIL: Missing assets in profile: {missing_assets}")
        return False
    
    logger.info("[PROFILE_SELF_CHECK] SUCCESS: All profile configuration checks passed")
    return True
