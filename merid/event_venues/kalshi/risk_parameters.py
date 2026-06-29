"""
Kalshi Risk Parameters - Named constants for all trading thresholds.

This module centralizes all numeric trading parameters to enforce the
"no magic numbers" policy. All price bands, size thresholds, edge limits,
and probability bounds must be defined here or in config, never as literals
in trading logic.

Policy:
- No literal prices, qty thresholds, or risk numbers in logic except via
  named constants or config.
- Any numeric trading threshold must come from this module or environment
  configuration.
- Changes to trading behavior require changes to config/constants, not
  sneaking in random literals in code.
"""

from typing import Final

# ============================================================================
# PRICE BAND CONSTANTS (cents)
# ── Price Band Constants ────────────────────────────────────────────────────────

MIN_KALSHI_PRICE_CENTS: Final[int] = 1
MAX_KALSHI_PRICE_CENTS: Final[int] = 99
DEFAULT_KALSHI_PRICE_CENTS: Final[int] = 50  # Midpoint fallback when market price unavailable
DEEP_OTM_CHEAP_CENTS: Final[int] = 5
DEEP_OTM_EXPENSIVE_CENTS: Final[int] = 95
MAX_PRICE_DIFFERENCE_CENTS: Final[int] = 50  # Max realistic price jump (data error threshold)  

# Mid-band - reasonable pricing
MID_BAND_LOW_CENTS: Final[int] = 20
MID_BAND_HIGH_CENTS: Final[int] = 80

# Minimum price for opening orders (anti-dust)
MIN_OPEN_PRICE_CENTS: Final[int] = 2
MAX_OPEN_PRICE_CENTS: Final[int] = 98

# ============================================================================
# PROBABILITY THRESHOLDS (0.0 - 1.0)
# ============================================================================

# Minimum model probability for opening orders
MIN_MODEL_PROB: Final[float] = 0.60

# Confidence bands
CONFIDENCE_NO_TRADE: Final[float] = 0.60
CONFIDENCE_CAUTIOUS: Final[float] = 0.75
CONFIDENCE_CONFIDENT: Final[float] = 0.75

# ============================================================================
# MARKETABLE LIMIT ORDER PARAMETERS
# ============================================================================

# Edge thresholds for order aggressiveness (per asset)
# Higher edge = more aggressive (cross spread), lower edge = resting (join spread)
EDGE_MARKET_ENTRY_BTC: Final[float] = 0.55  # BTC: cross spread if edge >= 55%
EDGE_MARKET_ENTRY_ETH: Final[float] = 0.55  # ETH: cross spread if edge >= 55%
EDGE_MARKET_ENTRY_SOL: Final[float] = 0.58  # SOL: cross spread if edge >= 58% (more conservative)
EDGE_MARKET_ENTRY_XRP: Final[float] = 0.60  # XRP: cross spread if edge >= 60% (more conservative)
EDGE_MARKET_ENTRY_DOGE: Final[float] = 0.62  # DOGE: cross spread if edge >= 62% (most conservative)

EDGE_RESTING_ENTRY_BTC: Final[float] = 0.52  # BTC: join spread if edge >= 52%
EDGE_RESTING_ENTRY_ETH: Final[float] = 0.52  # ETH: join spread if edge >= 52%
EDGE_RESTING_ENTRY_SOL: Final[float] = 0.54  # SOL: join spread if edge >= 54%
EDGE_RESTING_ENTRY_XRP: Final[float] = 0.55  # XRP: join spread if edge >= 55%
EDGE_RESTING_ENTRY_DOGE: Final[float] = 0.57  # DOGE: join spread if edge >= 57%

# Edge threshold for canceling resting orders (edge decay below this triggers cancel)
EDGE_CANCEL_THRESHOLD_BTC: Final[float] = 0.50
EDGE_CANCEL_THRESHOLD_ETH: Final[float] = 0.50
EDGE_CANCEL_THRESHOLD_SOL: Final[float] = 0.52
EDGE_CANCEL_THRESHOLD_XRP: Final[float] = 0.53
EDGE_CANCEL_THRESHOLD_DOGE: Final[float] = 0.55

# Maximum time to keep resting orders alive (auto-cancel after this)
MAX_LIVE_SECONDS_RESTING_BTC: Final[int] = 120  # 2 minutes
MAX_LIVE_SECONDS_RESTING_ETH: Final[int] = 120  # 2 minutes
MAX_LIVE_SECONDS_RESTING_SOL: Final[int] = 90   # 1.5 minutes
MAX_LIVE_SECONDS_RESTING_XRP: Final[int] = 90   # 1.5 minutes
MAX_LIVE_SECONDS_RESTING_DOGE: Final[int] = 60  # 1 minute

# Time-to-expiry threshold: use only marketable orders in last N seconds
MARKET_ONLY_LAST_SECONDS: Final[int] = 150  # 2.5 minutes before expiry

# Probability vs price consistency tolerance (max deviation allowed)
PROB_PRICE_TOLERANCE_PCT: Final[float] = 0.05  # 5%

# ============================================================================
# EDGE THRESHOLDS (percentage)
# ============================================================================

# Minimum edge required for opening orders
MIN_EDGE_PCT: Final[float] = 0.025  # 2.5%

# Edge thresholds for deep OTM contracts (require stronger justification)
DEEP_OTM_MIN_EDGE_PCT: Final[float] = 0.20  # 20%

# Edge thresholds for implausible underlying moves
IMPLAUSIBLE_MOVE_MIN_EDGE_PCT: Final[float] = 0.20  # 20%

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def compute_order_aggressiveness(asset: str, edge_pct: float, seconds_to_expiry: int) -> float:
    """Compute order aggressiveness based on edge, asset, and time-to-expiry.
    
    Returns:
        0.0: resting (join spread)
        0.5-1.0: marketable (cross spread, higher = more aggressive)
    
    Logic:
        - If edge >= market_entry threshold: aggressive (cross spread)
        - If edge >= resting_entry threshold: resting (join spread)
        - If edge < resting_entry threshold: no trade
        - In last MARKET_ONLY_LAST_SECONDS: force marketable if edge high enough
    """
    from typing import Dict
    
    # Map asset to thresholds
    market_thresholds: Dict[str, float] = {
        "BTC": EDGE_MARKET_ENTRY_BTC,
        "ETH": EDGE_MARKET_ENTRY_ETH,
        "SOL": EDGE_MARKET_ENTRY_SOL,
        "XRP": EDGE_MARKET_ENTRY_XRP,
        "DOGE": EDGE_MARKET_ENTRY_DOGE,
    }
    
    resting_thresholds: Dict[str, float] = {
        "BTC": EDGE_RESTING_ENTRY_BTC,
        "ETH": EDGE_RESTING_ENTRY_ETH,
        "SOL": EDGE_RESTING_ENTRY_SOL,
        "XRP": EDGE_RESTING_ENTRY_XRP,
        "DOGE": EDGE_RESTING_ENTRY_DOGE,
    }
    
    market_threshold = market_thresholds.get(asset, EDGE_MARKET_ENTRY_BTC)
    resting_threshold = resting_thresholds.get(asset, EDGE_RESTING_ENTRY_BTC)
    
    # Check if near expiry - force marketable if edge justifies
    if seconds_to_expiry < MARKET_ONLY_LAST_SECONDS:
        if edge_pct >= market_threshold:
            return 1.0  # Full aggressiveness near expiry
        elif edge_pct >= resting_threshold:
            return 0.5  # Moderate aggressiveness near expiry
        else:
            return 0.0  # No trade near expiry if edge too low
    
    # Normal case: decide based on edge
    if edge_pct >= market_threshold:
        # Scale aggressiveness from 0.5 to 1.0 based on how far above threshold
        excess_edge = edge_pct - market_threshold
        return min(0.5 + excess_edge * 2.0, 1.0)  # Cap at 1.0
    elif edge_pct >= resting_threshold:
        return 0.0  # Resting (join spread)
    else:
        return 0.0  # No trade (edge too low)

# ============================================================================
# SIZE THRESHOLDS (contracts)
# ============================================================================

# Minimum contracts per order (anti-dust)
MIN_CONTRACTS: Final[int] = 1

# Maximum contracts per order (position sizing cap)
MAX_CONTRACTS_DEFAULT: Final[int] = 1000

# Size bands for risk scaling
SIZE_SMALL: Final[int] = 10
SIZE_MEDIUM: Final[int] = 100
SIZE_LARGE: Final[int] = 500

# ============================================================================
# POSITION SIZING CONSTANTS
# ============================================================================

# Kelly fraction for position sizing
# CONSOLIDATED: Single source of truth is profile YAML (kalshi_crypto_15m.yaml)
# This constant is DEPRECATED and kept only for backward compatibility
# All sizing code should use profile.kelly_fraction instead
# DEPRECATION: Remove DEFAULT_KELLY_FRACTION after profile integration is complete
DEFAULT_KELLY_FRACTION: Final[float] = 0.05  # P1-FIX1: 0.25 -> 0.05. DEPRECATED: Use profile.kelly_fraction

# Minimum and maximum contracts per trade
SIZER_MIN_CONTRACTS: Final[int] = 1
SIZER_MAX_CONTRACTS: Final[int] = 50

# Bankroll fraction caps
# STANDARDIZED: Max 5% of bankroll per trade for all 15m crypto agents
# This prevents any single trade from risking excessive capital
SIZER_MAX_BANKROLL_PCT: Final[float] = 0.03  # 3% max per trade (tightened from 5%)
SIZER_MIN_BANKROLL_PCT: Final[float] = 0.01  # 1% min per trade

# PF/expectancy gates for size scaling
SIZER_PF_MIN_FOR_SCALING: Final[float] = 1.3
SIZER_PF_FULL_KELLY_AT: Final[float] = 2.0
SIZER_EXPECTANCY_MIN_CENTS: Final[float] = 6.0

# Per-underlying hourly exposure cap
SIZER_MAX_CONTRACTS_PER_UNDERLYING_PER_HOUR: Final[int] = 100

# Minimum sample size before scaling up
SIZER_MIN_TRADES_FOR_SCALING: Final[int] = 50

# Drawdown thresholds for position sizing
SIZER_DOWNTOWN_CAUTION_THRESHOLD_PCT: Final[float] = 15.0
SIZER_DOWNTOWN_DANGER_THRESHOLD_PCT: Final[float] = 25.0

# Volatility thresholds for position sizing
SIZER_VOL_CAUTION_THRESHOLD_PCT: Final[float] = 30.0
SIZER_VOL_DANGER_THRESHOLD_PCT: Final[float] = 50.0

# Fraction reduction factors
SIZER_DOWNTOWN_DANGER_REDUCTION: Final[float] = 0.25
SIZER_DOWNTOWN_CAUTION_REDUCTION: Final[float] = 0.5
SIZER_VOL_DANGER_REDUCTION: Final[float] = 0.25
SIZER_VOL_CAUTION_REDUCTION: Final[float] = 0.5
SIZER_TIGHT_REDUCTION: Final[float] = 0.5
SIZER_VOL_HIGH_REDUCTION: Final[float] = 0.7

# Target volatility for position sizing
SIZER_TARGET_VOL: Final[float] = 0.02
SIZER_MIN_SCALE: Final[float] = 0.25

# Maximum risk per trade
SIZER_MAX_RISK_PCT: Final[float] = 0.02

# Probability bounds for win probability
PROB_MIN_BOUND: Final[float] = 0.01
PROB_MAX_BOUND: Final[float] = 0.99

# ============================================================================
# STOP LOSS CONSTANTS
# ============================================================================

# Stop loss invalidation drop threshold (cents)
SL_INVALIDATION_DROP_CENTS: Final[int] = 20

# Stop loss losing percentage threshold
SL_CLOSE_LOSING_AFTER_PCT: Final[float] = 0.75

# Microscalping profit target percentage
PM_MICROSCALP_PROFIT_TARGET_PCT: Final[float] = 0.03

# Edge decay threshold
EDGE_DECAY_THRESHOLD: Final[float] = 0.50

# Minimum profit in cents after fees
PM_MIN_PROFIT_CENTS: Final[int] = 2

# Volatility-based profit targets
PM_LOW_VOLATILITY_TARGET: Final[float] = 0.03
PM_NORMAL_VOLATILITY_TARGET: Final[float] = 0.05
PM_HIGH_VOLATILITY_TARGET: Final[float] = 0.08

# Volatility thresholds
PM_LOW_VOL_THRESHOLD: Final[float] = 0.02
PM_HIGH_VOL_THRESHOLD: Final[float] = 0.05

# Momentum thresholds
PM_STRONG_MOMENTUM_THRESHOLD: Final[float] = 0.15
PM_WEAK_MOMENTUM_THRESHOLD: Final[float] = 0.05

# Momentum adjustment factors
PM_MOMENTUM_BOOST_FACTOR: Final[float] = 1.5
PM_MOMENTUM_REDUCE_FACTOR: Final[float] = 0.7

# Trailing stop settings
PM_TRAILING_STOP_DISTANCE_PCT: Final[float] = 0.02
PM_TRAILING_ACTIVATION_PCT: Final[float] = 0.02

# Profit target bounds
PM_MAX_PROFIT_TARGET_PCT: Final[float] = 0.10
PM_MIN_PROFIT_TARGET_PCT: Final[float] = 0.02

# Analytics window size
PM_ANALYTICS_WINDOW: Final[int] = 50

# Minimum exits for optimization
PM_MIN_EXITS_FOR_OPTIMIZATION: Final[int] = 30

# ============================================================================
# FEE CALCULATION CONSTANTS
# ============================================================================

# Fee rates for Kalshi contracts
TAKER_FEE_RATE: Final[float] = 0.07
MAKER_FEE_RATE: Final[float] = 0.0175

# Price bounds for fee calculation
FEE_MIN_PRICE_DOLLARS: Final[float] = 0.01
FEE_MAX_PRICE_DOLLARS: Final[float] = 0.99

# Maximum fees per contract at P = 0.5
MAX_TAKER_FEE_PER_CONTRACT_CENTS: Final[float] = 1.75
MAX_MAKER_FEE_PER_CONTRACT_CENTS: Final[float] = 0.4375

# Fee tier boundaries (contract counts)
FEE_TIER_SMALL_MIN: Final[int] = 0
FEE_TIER_SMALL_MAX: Final[int] = 100
FEE_TIER_MEDIUM_MIN: Final[int] = 100
FEE_TIER_MEDIUM_MAX: Final[int] = 1000
FEE_TIER_LARGE_MIN: Final[int] = 1000
FEE_TIER_LARGE_MAX: Final[int] = 999999999

# Fee tier rates
FEE_RATE_SMALL: Final[float] = 0.07
FEE_RATE_MEDIUM: Final[float] = 0.05
FEE_RATE_LARGE: Final[float] = 0.03

# ============================================================================
# DEPLOYMENT SAFETY CHECK CONSTANTS
# ============================================================================

# Deep OTM/ITM thresholds for "lotto ticket" detection
# CONSOLIDATED: Single source of truth is profile YAML (kalshi_crypto_15m.yaml)
# These constants are DEPRECATED and kept only for backward compatibility
# All deployment safety code should use profile.venue_invariants_deep_otm_threshold_cents instead
# DEPRECATION: Remove DEEP_OTM/ITM_THRESHOLD_CENTS after profile integration is complete
# FIX: Relaxed deep ITM threshold from 95c to 99c for 15m crypto markets
# 15m crypto markets can legitimately trade at 97-99c with high liquidity
DEEP_OTM_THRESHOLD_CENTS: Final[int] = 5   # DEPRECATED: Use profile.venue_invariants_deep_otm_threshold_cents
DEEP_ITM_THRESHOLD_CENTS: Final[int] = 99  # DEPRECATED: Use profile.venue_invariants_deep_itm_threshold_cents

# Model probability distance threshold (for detecting misaligned trades)
# Alert if abs(model_prob - price_cents/100) exceeds this value
# 2 percentage points is appropriate for 15m crypto volatility
MODEL_PROB_DISTANCE_THRESHOLD: Final[float] = 0.02  # 2 percentage points

# Exceptional edge threshold for allowing extreme price trades
# Allows deep OTM/ITM trades only if edge exceeds this threshold
# 20 percentage points is appropriate for 15m crypto markets
EXCEPTIONAL_EDGE_THRESHOLD_PCT: Final[float] = 20.0

# Minimum volume threshold for universe inclusion
UNIVERSE_MIN_VOLUME_DEFAULT: Final[int] = 50

# Minimum open interest threshold for universe inclusion
UNIVERSE_MIN_OPEN_INTEREST_DEFAULT: Final[int] = 10

# Maximum bid-ask spread for universe inclusion
UNIVERSE_MAX_SPREAD_CENTS_DEFAULT: Final[int] = 15

# Maximum markets per agent sweep
UNIVERSE_MAX_PER_AGENT_DEFAULT: Final[int] = 50

# Maximum reasonable move for 15m crypto timeframe
MAX_REASONABLE_15M_MOVE_PCT: Final[float] = 5.0

# Maximum reasonable move for 1h timeframe
MAX_REASONABLE_1H_MOVE_PCT: Final[float] = 8.0

# Maximum reasonable move for daily timeframe
MAX_REASONABLE_1D_MOVE_PCT: Final[float] = 15.0

# Threshold for "implausible move" guard
IMPLAUSIBLE_MOVE_THRESHOLD_PCT: Final[float] = 5.0

# ============================================================================
# POSITION LIFECYCLE (seconds)
# ============================================================================

# Maximum holding time before forced exit (relative to settlement)
MAX_HOLDING_BEFORE_SETTLEMENT_SEC: Final[int] = 300  # 5 minutes

# Minimum time to settlement before allowing new entries
MIN_TIME_TO_SETTLEMENT_SEC: Final[int] = 60  # 1 minute

# Position lifecycle check interval
POSITION_LIFECYCLE_CHECK_INTERVAL_SEC: Final[int] = 30

# ============================================================================
# EXIT CONDITIONS
# ============================================================================

# Default take-profit percentage (relative to entry)
DEFAULT_TAKE_PROFIT_PCT: Final[float] = 0.15  # 15%

# Default stop-loss percentage (relative to entry)
DEFAULT_STOP_LOSS_PCT: Final[float] = 0.10  # 10%

# Trailing take-profit activation threshold
TRAILING_TP_ACTIVATION_PCT: Final[float] = 0.10  # 10%

# Maximum holding time (absolute)
MAX_HOLDING_TIME_SEC: Final[int] = 172800  # 48 hours

# ============================================================================
# RISK LIMITS (percentage of capital)
# ============================================================================

# Per-market exposure cap
# STANDARDIZED: Max 5% of bankroll per market for all 15m crypto agents
# This prevents concentration risk in any single market
PER_MARKET_EXPOSURE_CAP_PCT: Final[float] = 0.05  # 5% max per market

# Per-strategy exposure cap
# STANDARDIZED: Max 5% of bankroll per strategy for all 15m crypto agents
PER_STRATEGY_EXPOSURE_CAP_PCT: Final[float] = 0.05  # 5%

# Maximum drawdown before forced exit
MAX_DRAWDOWN_PCT: Final[float] = 0.15  # 15%

# Daily loss limit
# STANDARDIZED: Max 10% daily loss for all 15m crypto agents
DAILY_LOSS_LIMIT_PCT: Final[float] = 0.10  # 10%

# Venue exposure cap (max total open exposure on Kalshi across all 15m crypto agents)
# STANDARDIZED: Max 20% of bankroll total on Kalshi venue for all 15m crypto agents
VENUE_EXPOSURE_CAP_PCT: Final[float] = 0.20  # 20% max total on Kalshi

# ============================================================================
# FEE AWARENESS
# ============================================================================

# Kalshi fee per leg (cents) - formula: ceil(0.07 × C × P × (1−P))
KALSHI_FEE_FACTOR: Final[float] = 0.07

# Minimum edge to cover fees (cents)
MIN_EDGE_TO_COVER_FEES_CENTS: Final[int] = 3

# Fee drag warning threshold (percentage of PnL)
FEE_DRAG_WARNING_PCT: Final[float] = 0.20  # 20%

# ============================================================================
# VALIDATION POLICY FLAGS
# ============================================================================

# Whether to enforce deep OTM policy (False = allow with strong edge)
# CRITICAL: Enabled for 15m crypto markets to prevent losing deep OTM trades (7c BTC, 10c SOL)
# Edge-based filtering (20% minimum edge) was insufficient - need hard price floor
ENFORCE_DEEP_OTM_POLICY: Final[bool] = True  # Enabled to block deep OTM longshots

# Whether to enforce prob-price consistency check
ENFORCE_PROB_PRICE_CONSISTENCY: Final[bool] = True  # Enabled to ensure model prob supports market price

# Whether to enforce underlying plausibility check
ENFORCE_UNDERLYING_PLAUSIBILITY: Final[bool] = True

# Whether to enforce position lifecycle guards
ENFORCE_POSITION_LIFECYCLE: Final[bool] = True

# ============================================================================
# ASSET-SPECIFIC PARAMETERS
# ============================================================================

# Distance caps for spot vs contract alignment (percentage)
BTC_DISTANCE_CAP_15M: Final[float] = 3.0
ETH_DISTANCE_CAP_15M: Final[float] = 4.0
SOL_DISTANCE_CAP_15M: Final[float] = 5.0
XRP_DISTANCE_CAP_15M: Final[float] = 5.0
DOGE_DISTANCE_CAP_15M: Final[float] = 6.0

# Hard caps (maximum allowed distance regardless of volatility)
BTC_HARD_DISTANCE_CAP: Final[float] = 25.0
ETH_HARD_DISTANCE_CAP: Final[float] = 30.0
SOL_HARD_DISTANCE_CAP: Final[float] = 32.0
XRP_HARD_DISTANCE_CAP: Final[float] = 35.0
DOGE_HARD_DISTANCE_CAP: Final[float] = 40.0

# Volatility multipliers for distance scaling
VOL_MULTIPLIER_LOW: Final[float] = 0.7
VOL_MULTIPLIER_MEDIUM: Final[float] = 1.0
VOL_MULTIPLIER_HIGH: Final[float] = 1.3

# Tenor multipliers for distance scaling
TENOR_MULTIPLIER_LT_6H: Final[float] = 0.5
TENOR_MULTIPLIER_6H_2D: Final[float] = 0.75
TENOR_MULTIPLIER_2D_14D: Final[float] = 1.0
TENOR_MULTIPLIER_GT_14D: Final[float] = 1.3

# ============================================================================
# KELLY CRITERION PARAMETERS
# ============================================================================

# Base Kelly fraction (fraction of full Kelly for capital preservation)
KELLY_BASE_FRACTION: Final[float] = 0.20  # Fifth-Kelly

# Maximum Kelly allocation (cap to prevent over-leverage)
KELLY_MAX_ALLOCATION_PCT: Final[float] = 0.05  # 5% of capital per trade

# Kelly confidence floor (minimum confidence to use Kelly)
KELLY_CONFIDENCE_FLOOR: Final[float] = 0.65

# ============================================================================
# TIMEFRAME-SPECIFIC EDGE THRESHOLDS
# ============================================================================

# Edge scaling factors by timeframe (higher for shorter timeframes)
TIMEFRAME_EDGE_MULTIPLIER_15M: Final[float] = 10.0
TIMEFRAME_EDGE_MULTIPLIER_1H: Final[float] = 6.0
TIMEFRAME_EDGE_MULTIPLIER_1D: Final[float] = 3.0
TIMEFRAME_EDGE_MULTIPLIER_1W: Final[float] = 1.5
TIMEFRAME_EDGE_MULTIPLIER_1M: Final[float] = 1.0
TIMEFRAME_EDGE_MULTIPLIER_1Y: Final[float] = 0.5

# ============================================================================
# ARBITRAGE THRESHOLDS
# ============================================================================

# YES/NO sum arbitrage detection threshold
YES_NO_SUM_ARB_THRESHOLD_CENTS: Final[int] = 100

# Minimum arb edge to execute
MIN_ARB_EDGE_PCT: Final[float] = 0.02  # 2%

# Cross-venue arb minimum edge
CROSS_VENUE_MIN_ARB_EDGE_PCT: Final[float] = 0.03  # 3%

# ============================================================================
# SENTIMENT INTEGRATION
# ============================================================================

# Sentiment history window size
SENTIMENT_HISTORY_WINDOW: Final[int] = 30

# Sentiment divergence threshold (to trigger position size reduction)
SENTIMENT_DIVERGENCE_THRESHOLD: Final[float] = 0.30  # 30%

# Minimum sentiment confidence to use in sizing
MIN_SENTIMENT_CONFIDENCE: Final[float] = 0.70

# ============================================================================
# VALIDATION ERROR CODES
# ============================================================================

# Standardized error codes for validation failures
ERR_MISSING_MODEL_PROB: Final[str] = "missing_model_prob"
ERR_NO_EDGE_VS_IMPLIED: Final[str] = "no_edge_vs_implied"
ERR_DEEP_OTM_DISALLOWED: Final[str] = "deep_otm_disallowed"
ERR_DEEP_OTM_INSUFFICIENT_EDGE: Final[str] = "deep_otm_insufficient_edge"
ERR_IMPLAUSIBLE_MOVE: Final[str] = "implausible_move"
ERR_PRICE_OUT_OF_RANGE: Final[str] = "price_out_of_range"
ERR_SIZE_BELOW_MIN: Final[str] = "size_below_min"
ERR_SIZE_ABOVE_MAX: Final[str] = "size_above_max"
ERR_NO_EXIT_PLAN: Final[str] = "no_exit_plan"
ERR_EXPOSURE_CAP_EXCEEDED: Final[str] = "exposure_cap_exceeded"
ERR_DRAWDOWN_EXCEEDED: Final[str] = "drawdown_exceeded"
ERR_DAILY_LOSS_EXCEEDED: Final[str] = "daily_loss_exceeded"
ERR_TIME_TO_SETTLEMENT_TOO_SHORT: Final[str] = "time_to_settlement_too_short"
ERR_POSITION_STALE: Final[str] = "position_stale"
ERR_EXIT_ORDER_REJECTED: Final[str] = "exit_order_rejected"
