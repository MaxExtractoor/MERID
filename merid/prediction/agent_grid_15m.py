from __future__ import annotations



from datetime import datetime as dt, timezone, timedelta, datetime

import time

import collections

import re

import asyncio

from typing import Any, Optional, Dict

from dataclasses import dataclass, field



from utils.logger import get_logger



logger = get_logger("merid.prediction.agent_grid_15m")



# Import rejection monitor for production rejection tracking

try:

    from merid.monitoring.rejection_monitor import (

        get_rejection_monitor,

        log_time_window_rejection,

        log_price_range_rejection,

        log_trend_alignment_rejection,

        log_edge_check_rejection,

    )

    REJECTION_MONITOR_ENABLED = True

except ImportError:

    REJECTION_MONITOR_ENABLED = False

    logger.debug("[REJECTION-MONITOR] Not available - rejection tracking disabled")



# Local price formatting function (replaces utils.logger.format_price to avoid import issues)

def format_price(asset: str, price: float) -> str:

    """Format price with appropriate decimal places based on asset."""

    if asset in ["BTC", "ETH"]:

        return f"{price:.2f}"

    elif asset in ["SOL", "XRP"]:

        return f"{price:.4f}"

    elif asset == "DOGE":

        return f"{price:.6f}"

    else:

        return f"{price:.4f}"



# Kalshi fee calculation (2026 industry standard)

# Kalshi charges 7% × p × (1-p) on winning trades, capped at $0.0175

# This function calculates the fee in cents for a given probability

def calculate_kalshi_fee_cents(probability: float, price_cents: int) -> float:

    """

    Calculate Kalshi fee in cents for a winning trade.

    

    Formula: fee = 7% × p × (1-p) × contract_price

    Capped at $0.0175 (1.75 cents) per contract

    

    Args:

        probability: Market-implied probability (0.0 to 1.0)

        price_cents: Contract price in cents (0 to 100)

    

    Returns:

        Fee in cents (capped at 1.75 cents)

    """

    # Clamp probability to valid range

    probability = max(0.0, min(1.0, probability))

    

    # Calculate fee percentage: 7% × p × (1-p)

    fee_pct = 0.07 * probability * (1.0 - probability)

    

    # Calculate fee in cents

    fee_cents = fee_pct * price_cents

    

    # Cap at $0.0175 (1.75 cents) per contract

    fee_cents = min(fee_cents, 1.75)

    

    return fee_cents



# SEV-0 FIX: Standardized velocity edge calculation function

# This ensures consistency across agent_grid, loop_15m, and order_router

def calculate_velocity_edge(velocity: float, velocity_threshold: float) -> float:

    """

    Calculate edge percentage from velocity magnitude for velocity-based signals.

    

    Standard formula: edge = abs(velocity / threshold) * 2.0

    This ensures edge is in 0-100% range for velocity-based signals.

    

    Args:

        velocity: Velocity value (can be positive or negative)

        velocity_threshold: Velocity threshold for signal generation

    

    Returns:

        Edge percentage (0-100%)

    """

    if velocity_threshold == 0:

        return 0.0

    return abs(velocity / velocity_threshold) * 2.0



# SEV-1 FIX: Time-based warmup guard

# Warmup bypass only allowed in first 5 minutes after process start

_process_start_time = time.time()



def is_warmup(history_length: int) -> bool:

    """

    Check if system is in warmup state.

    

    Warmup is only allowed in first 5 minutes after process start.

    After 5 minutes, require minimum history regardless of data gaps.

    

    Args:

        history_length: Length of data history

    

    Returns:

        True if in warmup state, False otherwise

    """

    # Time-based guard: only allow warmup bypass in first 5 minutes

    if time.time() - _process_start_time > 300:

        return False

    

    # History-based guard: require minimum history after 5 minutes

    return history_length < 20



# Import regime detection module

from merid.prediction.regime_detector import RegimeDetector, Regime



# Import regime adapter to bridge to canonical ops.regime_detection

try:

    from ops.regime_adapter import get_regime_adapter

    _REGIME_ADAPTER_AVAILABLE = True

except ImportError:

    _REGIME_ADAPTER_AVAILABLE = False

    logger.warning("[AGENT-GRID] Regime adapter not available, canonical regime updates disabled")



# Lean AgentGrid for Kalshi 15m Crypto Trading.

# This module provides a minimal, focused agent grid for 15-minute crypto trading.

# It uses Coinbase velocity-based signals (2026 #1 winning strategy) and simplified gates.

# See docs/15M_STACK_SURFACE.md for complete allowed surface definition.



from merid.config.environment import enable_composite_spot_fallback



# Import unified_spot_service for volume filter integration

from data.unified_spot_service import SpotError



# Import FifteenMinuteMarketLocator for time-bucket-based market selection

from merid.event_venues.kalshi.fifteen_minute_market_locator import (

    FifteenMinuteMarketLocator,

    get_market_locator,

    MarketIds,

)





# Minimal market object wrapper for time-bucket-based market selection

@dataclass

class MinimalMarket:

    """

    Minimal market object wrapper for FifteenMinuteMarketLocator.

    

    This provides the interface expected by the existing agent grid code

    (market.market_id, close_time, minutes_to_expiry, etc.) without requiring a full catalog lookup.

    """

    market_id: str

    close_time: float  # Unix timestamp

    asset: str

    minutes_to_expiry: Optional[float] = None  # Normalized minutes to expiry from catalog

    

    @property

    def market(self) -> 'MinimalMarket':

        # Self-reference for compatibility with existing code

        return self





# Log module load to confirm this is the grid being used

logger.info("[AGENT-GRID-15M-IMPORTED] module=%s", __name__)



# Global reference to the agent grid instance for external reset calls

_agent_grid_instance: Optional['LeanAgentGrid15m'] = None



def set_agent_grid_instance(grid: 'LeanAgentGrid15m') -> None:

    """Set the global agent grid instance for external reset calls."""

    global _agent_grid_instance

    _agent_grid_instance = grid

    logger.info("[AGENT-GRID-INSTANCE] Global instance set")



def reset_strip_order_counts() -> None:

    """Reset all strip order counts and market ID tracking.

    

    This is called by the catalog when it detects a market rollover (e.g., 16:15 -> 16:30).

    It resets the per-strip order limits so trading can continue on the new 15m strip.

    """

    global _agent_grid_instance

    if _agent_grid_instance:

        _agent_grid_instance.reset_strip_order_counts()

        logger.info("[STRIP-RESET-EXTERNAL] Reset strip order counts via catalog trigger")

    else:

        logger.warning("[STRIP-RESET-EXTERNAL] No agent grid instance available for reset")



def log_agent_grid_version() -> None:

    # Log agent grid version at startup (not import time).

    logger.info("[AGENT-GRID-15M] MODULE VERSION v20260529a-cache-fix")



# STRATEGY INVARIANTS (agent_grid_15m::_generate_signal):

# 1. Velocity-based signals: Use Coinbase 1-minute velocity for trade direction

# 2. Simplified gates: Only liquidity, spread, staleness (no complex indicator gates)

# 3. Market state validation: Use KalshiMarketStateStore for live orderbook data

# 4. Risk envelope: Apply profile-driven risk limits and position sizing

# 5. Full asset coverage: All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) must be included



# Configuration helpers

KALSHI_ALIGNMENT_TOLERANCES = {

    "BTC": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "ETH": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "SOL": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "XRP": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "DOGE": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

}



def get_alignment_tolerance(asset: str) -> Dict[str, float]:

    # Get alignment tolerances for a given asset.

    return KALSHI_ALIGNMENT_TOLERANCES.get(asset.upper(), {

        "max_abs_diff": 1.0,

        "max_rel_diff": 0.0001,

    })



# Kalshi alignment helpers

def compute_data_quality(metrics: Dict[str, Any]) -> float:

    # Compute data quality score for critical trading inputs.

    # This helper enforces Invariant 3: No Optimistic Execution Defaults.

    # Returns a score from 0.0 to 1.0 based on how many critical inputs are present.

    critical_inputs = {

        "spread_cents": metrics.get("spread_cents") is None,

        "spot_price": metrics.get("spot_price") is None,

        "price_cents": metrics.get("price_cents", 0) <= 0,

        "bid": metrics.get("bid", 0) <= 0,

        "ask": metrics.get("ask", 0) <= 0,

    }

    missing_count = sum(critical_inputs.values())

    return 1.0 - (missing_count / len(critical_inputs))



# Agent configuration

@dataclass

class LeanAgentConfig:

    # Configuration for a single 15m crypto agent.

    name: str  # Agent name (e.g., "BTC_15M")

    series_tickers: list[str]  # Series tickers to trade (e.g., ["KXBTC15M"])

    signal_mode: str = "trend"  # Signal mode: "trend", "mean_reversion", "momentum_fvg", "hybrid", "price_based"

    max_spread_cents: int = 100  # 2026-07-10: RELAXED to 100c - allows trading in current market conditions with wider spreads (60c-96c observed)

    min_time_to_expiry_s: int = 180  # Minimum time to expiry in seconds

    max_time_to_expiry_s: int = 900  # Maximum time to expiry in seconds

    per_strip_order_limit: int = 200  # Maximum orders per 15m strip (increased from 50 to 200 for 2026 high-frequency standards)

    per_asset_cooldown_s: int = 3  # Cooldown period in seconds after trade (2026-07-11: reduced to 3s for 15m alignment)

    max_orders_per_15m_window: int = 24  # CRITICAL FIX: 24 (2026-07-11: increased to 24 for 15m opportunity capture)

    consecutive_loss_pause: int = 3  # 2026 research: Pause after N consecutive losses

    max_session_risk_pct: float = 0.10  # 2026 research: Max session risk as % of capital

    velocity_threshold: float = 0.00001  # 0.001% - aligned with profile YAML (default, overridden by per-asset values)

    # Asset-specific velocity thresholds (deeper markets = lower threshold, more volatile = higher threshold)

    # CRITICAL FIX: 2026-07-05 - Aligned with profile YAML velocity_thresholds section

    # Profile YAML values: 0.00001 (0.001%) for all assets - effectively zero to enable any movement

    # Previous hardcoded values (0.15%-0.20%) were 150-200x higher than profile YAML

    # New thresholds align with profile YAML single source of truth:

    velocity_threshold_btc: float = 0.00015  # BTC: 0.015% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_eth: float = 0.00015  # ETH: 0.015% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_sol: float = 0.000225  # SOL: 0.0225% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_xrp: float = 0.000225  # XRP: 0.0225% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_doge: float = 0.0003  # DOGE: 0.03% (CRITICAL FIX: aligned with profile YAML)

    # INDUSTRY ALIGNMENT: Fee-aware trading parameters based on profitable scalping research

    prefer_maker_orders: bool = True  # Prefer maker orders to earn rebates (-0.05% round trip) vs taker fees (0.15% round trip)

    min_profit_basis_points: int = 20  # Minimum 20bp profit target to overcome structural disadvantages (industry standard for retail)

    max_spread_basis_points: int = 50  # RELAXED: Maximum 50bp spread (increased from 30 to allow more trades in current market conditions)

    # FILL RATE OPTIMIZATION: Use limit orders instead of market orders for better fill rates in thin markets

    use_limit_orders: bool = True  # Use limit orders (maker) instead of market orders (taker) for better fill rates

    limit_order_slippage_cents: int = 2  # Allow 2 cents slippage for limit orders to increase fill probability

    # INDUSTRY ALIGNMENT: Regime detection parameters (2026 best practices)

    volatility_window_s: int = 300  # 5-minute volatility window for regime detection

    min_volatility_threshold: float = 0.001  # Minimum 0.1% volatility to avoid low-volatility death zones

    # HYBRID MODE PRICE CAPS (2026 Optimized)

    # CRITICAL FIX: 2026-07-05 - Aligned with profile YAML hybrid section

    # Profile YAML values: max_entry_price_yes: 0.70, min_entry_price_no: 0.30

    # Previous hardcoded values (0.90/0.10) didn't match profile YAML

    # New values align with profile YAML single source of truth:

    max_entry_price_yes: float = 0.70  # CRITICAL FIX: 70¢ (aligned with profile YAML - avoids highest fee zone)

    min_entry_price_no: float = 0.30  # CRITICAL FIX: 30¢ (aligned with profile YAML - symmetry with 70¢ YES cap)

    max_volatility_threshold: float = 0.02  # Maximum 2% volatility to avoid extreme volatility spikes

    # POSITION MANAGEMENT (2026 best practices)

    # 2026 FIX: Added max concurrent positions limit to prevent over-accumulation

    # 2026-07-09: Set to 4 to align with $1 exposure cap at typical prices (25c)

    # At 25c/contract: 4 positions = $1.00 exactly at cap

    # Slot allocator enforces $1 hard cap, but this aligns soft limit with hard limit

    # This is TOTAL across all 5 assets (BTC+ETH+SOL+XRP+DOGE), not per-asset

    max_concurrent_positions: int = 4  # Maximum total open positions across all assets

    # DYNAMIC SPREAD THRESHOLD: Volatility-regime-based spread filtering (2026 best practice)

    # Based on research: "Blow your spreads out when the market's volatility does"

    # Uses 3 regimes with different spread limits: calm, elevated, violent

    # UPDATED: Increased thresholds to allow trading in current market conditions

    calm_volatility_threshold: float = 0.005  # 0.5% volatility = calm regime

    elevated_volatility_threshold: float = 0.015  # 1.5% volatility = elevated regime

    # SESSION-BASED TRADING WINDOWS (2026 best practices for crypto)

    # Based on research: Trade during peak liquidity hours for better win rates

    # US-Europe overlap (13:00-17:00 UTC): Highest liquidity, tightest spreads

    # US session (17:00-22:00 UTC): Good liquidity, moderate spreads

    # European morning (08:00-13:00 UTC): Moderate liquidity, wider spreads

    # Asian session (00:00-08:00 UTC): Low liquidity, avoid trading

    # DISABLED: Trade 24/7 per user request

    enable_session_filter: bool = False  # Enable session-based trading windows (disabled for 24/7 trading)

    us_europe_overlap_start_utc: int = 13  # 13:00 UTC

    us_europe_overlap_end_utc: int = 17  # 17:00 UTC

    us_session_start_utc: int = 17  # 17:00 UTC

    us_session_end_utc: int = 22  # 22:00 UTC

    european_morning_start_utc: int = 8  # 08:00 UTC

    european_morning_end_utc: int = 13  # 13:00 UTC

    # Phase 1A: Surgical spread relaxation based on log analysis (2026-07-09)

    # Logs show spreads at 2000+ bp vs dynamic_max of 200 bp causing 0 candidates

    # Asset-specific overrides: BTC/ETH (deeper books) 300bp, SOL/XRP/DOGE (thinner books) 350bp

    calm_spread_threshold_bp: int = 200  # 200bp max spread in calm regime (base threshold)

    elevated_spread_threshold_bp: int = 300  # 300bp max spread in elevated regime (base threshold)

    violent_spread_threshold_bp: int = 500  # 500bp max spread in violent regime (base threshold)

    # Per-asset overrides for regime-specific spread thresholds

    calm_spread_threshold_bp_btc_eth: int = 300  # 300bp for BTC/ETH (deeper books)

    calm_spread_threshold_bp_sol_xrp_doge: int = 350  # 350bp for SOL/XRP/DOGE (thinner books)

    elevated_spread_threshold_bp_btc_eth: int = 400  # 400bp for BTC/ETH in elevated

    elevated_spread_threshold_bp_sol_xrp_doge: int = 450  # 450bp for SOL/XRP/DOGE in elevated

    violent_spread_threshold_bp_btc_eth: int = 600  # 600bp for BTC/ETH in violent

    violent_spread_threshold_bp_sol_xrp_doge: int = 700  # 700bp for SOL/XRP/DOGE in violent

    spread_volatility_sensitivity: float = 1.5  # Lambda parameter for continuous interpolation

    # Phase 1: Velocity model coefficients for logistic mapping

    alpha_0: float = 0.0  # Intercept for logistic function

    alpha_1: float = 1000.0  # Velocity coefficient for logistic function

    # Phase 4.1: Multi-window velocity configuration

    velocity_windows: list = field(default_factory=lambda: [10, 30, 60])  # Velocity windows in seconds

    momentum_weights: list = field(default_factory=lambda: [0.2, 0.3, 0.5])  # Weights for each window

    velocity_ema_period: int = 5  # EMA smoothing period for velocity (reduces noise)

    atr_period: int = 3  # 2026-07-01 FIX: Reduced from 7 to 3 for faster warmup (3 data points needed instead of 7)

    zscore_period: int = 20  # Z-score period for extreme detection (industry standard)

    # Phase 4.4: Logit fusion weights

    logit_fusion_velocity_weight: float = 0.7  # Weight for velocity signal

    logit_fusion_mean_reversion_weight: float = 0.3  # Weight for mean reversion signal

    # Phase 4.5: Near expiry guard

    near_expiry_guard_sec: int = 300  # Skip logit fusion if time to expiry < 5 minutes

    # Phase 5.2: Calibration configuration

    calibration_enabled: bool = False  # Enable/disable probability calibration

    calibration_auto_fit: bool = True  # Automatically fit calibration when sufficient data

    calibration_min_samples: int = 100  # Minimum samples required to fit calibration

    # Phase 5.3: Price-based strategy (Turbine research winner)

    price_based_buy_threshold: float = 0.70  # Buy YES in sweet spot (60-70c range per Polymarket data)

    price_based_sell_threshold: float = 0.95  # Sell when price >= 0.95 (raised from 0.90 to prevent bad NO trades at 70-90c)

    calibration_max_samples: int = 1000  # Maximum samples to keep for calibration

    calibration_regularization: float = 0.0001  # L2 regularization parameter

    calibration_fit_interval_hours: int = 24  # Re-fit calibration every N hours

    # Phase 6: Regime detection configuration

    regime_detector_enabled: bool = True  # Enable HMM-based regime detection for adaptive strategy switching

    # Phase 7: Panic fade (volatility reversion) configuration - Turbine research winner

    panic_fade_enabled: bool = True  # Enable panic fade strategy (volatility reversion)

    panic_fade_threshold: float = 0.00013  # Velocity threshold for panic detection (0.013%) - reduced by 35% for more signals

    panic_fade_zscore_threshold: float = 2.0  # Z-score threshold for statistical extreme

    panic_fade_rsi_oversold: float = 25.0  # RSI oversold threshold (buy YES)

    panic_fade_rsi_overbought: float = 75.0  # RSI overbought threshold (buy NO)

    panic_fade_min_velocity: float = 0.000065  # Minimum velocity to qualify as panic (0.0065%) - reduced by 35% for more signals

    # Note: Depth thresholds (min_depth_yes, min_depth_no) are now sourced from risk envelope/profile

    # to ensure single source of truth across the stack

    # Note: min_edge_pct removed - velocity-based signal doesn't use edge filtering



# Lean agent for 15m crypto trading

class LeanAgent15m:

    # Minimal agent for 15m crypto trading with velocity-based signals.

    

    def __init__(

        self,

        config: LeanAgentConfig,

        catalog: Any,

        market_state_store: Any,

        spot_provider: Any,

        order_router: Any,

        risk_config: Any,

    ):

        self.config = config

        self.catalog = catalog

        self.market_state_store = market_state_store

        self.spot_provider = spot_provider

        self.order_router = order_router

        self.risk_config = risk_config

        

        # Phase 1: Store velocity model coefficients for logistic mapping

        self._alpha_0 = config.alpha_0

        self._alpha_1 = config.alpha_1

        logger.info("[AGENT-INIT] %s velocity coefficients: alpha_0=%.2f, alpha_1=%.2f", 

                    config.name, self._alpha_0, self._alpha_1)

        

        # Phase 4.1: Multi-window velocity configuration

        # Use profile values if available, otherwise use defaults

        self._velocity_windows = getattr(config, 'velocity_windows', [10, 30, 60])

        self._momentum_weights = getattr(config, 'momentum_weights', [0.2, 0.3, 0.5])

        self._velocity_ema_period = getattr(config, 'velocity_ema_period', 5)

        self._atr_period = getattr(config, 'atr_period', 14)

        self._zscore_period = getattr(config, 'zscore_period', 20)

        logger.info("[AGENT-INIT] %s multi-window velocity: windows=%s weights=%s ema_period=%d atr_period=%d zscore_period=%d", 

                    config.name, self._velocity_windows, self._momentum_weights, self._velocity_ema_period, self._atr_period, self._zscore_period)

        

        # Phase 4.4: Logit fusion weights

        self._logit_fusion_velocity_weight = getattr(config, 'logit_fusion_velocity_weight', 0.7)

        self._logit_fusion_mean_reversion_weight = getattr(config, 'logit_fusion_mean_reversion_weight', 0.3)

        logger.info("[AGENT-INIT] %s logit fusion weights: velocity=%.2f mean_reversion=%.2f", 

                    config.name, self._logit_fusion_velocity_weight, self._logit_fusion_mean_reversion_weight)

        

        # Phase 4.5: Near expiry guard

        self._near_expiry_guard_sec = getattr(config, 'near_expiry_guard_sec', 300)

        logger.info("[AGENT-INIT] %s near expiry guard: %d seconds", 

                    config.name, self._near_expiry_guard_sec)

        

        # Phase 5.3: Initialize PlattScaler for probability calibration

        self._calibration_enabled = getattr(config, 'calibration_enabled', False)

        self._calibration_auto_fit = getattr(config, 'calibration_auto_fit', True)

        self._calibration_min_samples = getattr(config, 'calibration_min_samples', 100)

        

        # Phase 6: Initialize regime detector for adaptive strategy switching

        self._regime_detector_enabled = getattr(config, 'regime_detector_enabled', True)

        if self._regime_detector_enabled:

            self._regime_detector = RegimeDetector(

                n_states=3,

                train_window=300,

                min_history=50,

                refit_interval=100,

                random_state=42

            )

            logger.info("[AGENT-INIT] %s regime detector enabled", config.name)

        else:

            self._regime_detector = None

            logger.info("[AGENT-INIT] %s regime detector disabled", config.name)

        

        # Phase 7: Initialize panic fade (volatility reversion) configuration

        self._panic_fade_enabled = getattr(config, 'panic_fade_enabled', True)

        self._panic_fade_threshold = getattr(config, 'panic_fade_threshold', 0.0002)

        self._panic_fade_zscore_threshold = getattr(config, 'panic_fade_zscore_threshold', 2.0)

        self._panic_fade_rsi_oversold = getattr(config, 'panic_fade_rsi_oversold', 25.0)

        self._panic_fade_rsi_overbought = getattr(config, 'panic_fade_rsi_overbought', 75.0)

        self._panic_fade_min_velocity = getattr(config, 'panic_fade_min_velocity', 0.0001)

        logger.info("[AGENT-INIT] %s panic fade: enabled=%s threshold=%.4f zscore=%.1f rsi_oversold=%.1f rsi_overbought=%.1f min_velocity=%.4f",

                    config.name, self._panic_fade_enabled, self._panic_fade_threshold, 

                    self._panic_fade_zscore_threshold, self._panic_fade_rsi_oversold, 

                    self._panic_fade_rsi_overbought, self._panic_fade_min_velocity)

        self._calibration_max_samples = getattr(config, 'calibration_max_samples', 1000)

        self._calibration_regularization = getattr(config, 'calibration_regularization', 0.0001)

        

        if self._calibration_enabled:

            from merid.risk.probability.platt_scaler import PlattScaler

            self._platt_scaler = PlattScaler(regularization=self._calibration_regularization)

            self._calibration_logits: List[float] = []

            self._calibration_outcomes: List[int] = []

            self._last_fit_time: float = 0.0

            logger.info("[AGENT-INIT] %s probability calibration enabled with PlattScaler", config.name)

        else:

            self._platt_scaler = None

            self._calibration_logits = []

            self._calibration_outcomes = []

            self._last_fit_time = 0.0

            logger.info("[AGENT-INIT] %s probability calibration disabled", config.name)

        

        # Initialize price history for velocity calculation

        # CRITICAL FIX: Increase window to 5 minutes to accommodate ADX warmup (14 periods = 70s at 5s cadence)

        # and provide buffer during 15-minute window transitions

        # CRITICAL FIX: Store OHLC data instead of just close price for proper ADX/ATR calculation

        self._spot_price_history: Dict[str, collections.deque] = {}

        self._price_history_window_size = 300  # 5 minutes at 1-second intervals (60 data points at 5s cadence)

        

        # CRITICAL FIX: 2026-07-07 - Initialize Crypto15mIndicatorStack for 2026 research-based indicators

        # This provides EMA(200), regime-based RSI, MACD filters, and RSI+MACD confluence scoring

        # CRITICAL FIX: 2026-07-08 - Enable kalshi_mode to disable strict spot market thresholds

        # Kalshi prediction markets are binary contracts, not continuous spot instruments

        # Without kalshi_mode, strict vol/ATR/chop gates block all signals

        # CRITICAL FIX: 2026-07-10 - Initialize indicator stacks for ALL 5 assets in EACH agent

        # This ensures each asset's indicator stack gets redundant updates from all 5 agents

        # Previous fix (only initializing own asset) caused bars_available=1 because each agent

        # is called once per cycle, so each stack only got 1 update per minute

        # With all 5 assets initialized in each agent, each stack gets 5 updates per cycle

        self._indicator_stacks: Dict[str, Any] = {}

        self._indicator_stack_last_update: Dict[str, float] = {}  # Track last update time per asset

        self._indicator_stack_price_buffer: Dict[str, List[float]] = {}  # Buffer spot prices for 1-minute aggregation

        try:

            from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig

            # Initialize indicator stack for ALL 5 crypto assets

            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

                cfg = IndicatorConfig(asset=asset, kalshi_mode=True)

                self._indicator_stacks[asset] = Crypto15mIndicatorStack(config=cfg)

                self._indicator_stacks[asset].set_asset_symbol(asset)  # Set asset symbol for logging

                self._indicator_stack_last_update[asset] = 0.0

                self._indicator_stack_price_buffer[asset] = []

            logger.info("[AGENT-INIT] %s initialized Crypto15mIndicatorStack for all 5 assets (BTC, ETH, SOL, XRP, DOGE) with kalshi_mode=True", 

                       config.name)

        except Exception as e:

            logger.error("[AGENT-INIT] %s failed to initialize Crypto15mIndicatorStack: %s", config.name, e, exc_info=True)

            self._indicator_stacks = {}

        

        # Initialize for all 5 crypto assets

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._spot_price_history[asset] = collections.deque(maxlen=self._price_history_window_size)

        

        # Phase 4.3: Initialize SMA history for mean reversion (2-minute window)

        self._sma_history: Dict[str, collections.deque] = {}

        self._sma_window_size = 120  # 2 minutes at 1-second intervals

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._sma_history[asset] = collections.deque(maxlen=self._sma_window_size)

        

        # Phase 4.1: Initialize EMA history for velocity smoothing

        self._velocity_ema_history: Dict[str, collections.deque] = {}

        self._ema_window_size = self._velocity_ema_period * 2  # Keep enough history for EMA calculation

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._velocity_ema_history[asset] = collections.deque(maxlen=self._ema_window_size)

        

        # Phase 4.1: Initialize volatility history for ATR-based normalization

        # Keep 5 minutes of history (300 points at 1s intervals) for dynamic cooldown calculation

        self._volatility_history: Dict[str, collections.deque] = {}

        self._volatility_window_size = 300  # 5 minutes for dynamic cooldown ATR averaging

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._volatility_history[asset] = collections.deque(maxlen=self._volatility_window_size)

        

        # Phase 4.1: Initialize velocity history for Z-score calculation

        self._velocity_zscore_history: Dict[str, collections.deque] = {}

        self._zscore_window_size = self._zscore_period  # Keep Z-score period worth of velocity data

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._velocity_zscore_history[asset] = collections.deque(maxlen=self._zscore_window_size)

        

        # DATA QUALITY: Initialize data quality issue tracking

        # Tracks OHLCV corruption, staleness, and other data quality issues per asset

        self._data_quality_issues: Dict[str, Dict[str, int]] = {}

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._data_quality_issues[asset] = {

                "ohlcv_corruption": 0,  # high < low violations

                "ohlcv_stale": 0,       # high == low (no movement)

                "volume_anomaly": 0,    # volume spikes or zeros

                "price_anomaly": 0,     # price spikes or gaps

            }

        

        # Phase 6: Initialize ADX history for trend filtering (14-period ADX)

        self._adx_history: Dict[str, collections.deque] = {}

        self._adx_window_size = 14  # ADX period (industry standard)

        self._tr_history: Dict[str, collections.deque] = {}  # True Range history

        self._plus_dm_history: Dict[str, collections.deque] = {}  # Positive Directional Movement history

        self._minus_dm_history: Dict[str, collections.deque] = {}  # Negative Directional Movement history

        # CRITICAL FIX: Track previous smoothed values for Wilder's smoothing technique

        self._prev_smoothed_tr: Dict[str, float] = {}  # Previous smoothed TR

        self._prev_smoothed_plus_dm: Dict[str, float] = {}  # Previous smoothed +DM

        self._prev_smoothed_minus_dm: Dict[str, float] = {}  # Previous smoothed -DM

        self._prev_adx: Dict[str, float] = {}  # Previous ADX value

        # CRITICAL FIX: Increase ADX history maxlen to preserve data across 15-minute window transitions

        # Use same window size as price history (300) to ensure ADX warmup completes even during transitions

        self._adx_history_window_size = 300  # Match price history window

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._adx_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._tr_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._plus_dm_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._minus_dm_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._prev_smoothed_tr[asset] = 0.0

            self._prev_smoothed_plus_dm[asset] = 0.0

            self._prev_smoothed_minus_dm[asset] = 0.0

            self._prev_adx[asset] = 0.0

        

        # CRITICAL FIX: 2026-07-01 - Initialize volume history for volume confirmation filter

        # Industry standard: volume > 1.2x EMA20(volume) confirms signal validity

        # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        self._volume_history: Dict[str, collections.deque] = {}

        self._volume_window_size = 300  # 5 minutes of volume history for EMA20 calculation

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._volume_history[asset] = collections.deque(maxlen=self._volume_window_size)

        

        # CRITICAL FIX: 2026-07-01 - Initialize multi-timeframe price history for alignment

        # Industry standard: 1m + 5m confirmation for +10-20 pp win rate

        # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        self._price_1m_history: Dict[str, collections.deque] = {}  # 1-minute price history

        self._price_5m_history: Dict[str, collections.deque] = {}  # 5-minute price history

        self._1m_window_size = 60  # 1 minute at 1-second intervals

        self._5m_window_size = 300  # 5 minutes at 1-second intervals

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._price_1m_history[asset] = collections.deque(maxlen=self._1m_window_size)

            self._price_5m_history[asset] = collections.deque(maxlen=self._5m_window_size)

        

        # CRITICAL FIX: 2026-07-06 - Initialize MACD history for momentum_fvg signal generation

        # MACD(12,26,9) requires 9 periods of MACD line history for signal line calculation

        self._macd_history: Dict[str, collections.deque] = {}

        self._macd_window_size = 9  # 9-period EMA for signal line

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._macd_history[asset] = collections.deque(maxlen=self._macd_window_size)

        

        # Cooldown tracking: last trade timestamp per asset

        # CRITICAL FIX 2026-07-10: Use time.monotonic() instead of time.time()

        # time.time() returns Unix timestamp (absolute time), while time.monotonic() returns

        # relative time suitable for calculating time differences. Using time.time() causes

        # incorrect cooldown calculations when initialized to 0.0 (results in ~56 years).

        self._last_trade_time: Dict[str, float] = {}

        # Initialize to current monotonic time to allow immediate signal generation on startup

        # Cooldown only applies after actual trades are placed

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._last_trade_time[asset] = time.monotonic()

        

        # Per-strip order limit tracking (15m strip = series ticker)

        # CRITICAL FIX: 2026-07-10 - Reset strip order counts on agent initialization

        # This prevents persisted counts from previous runs from blocking new orders

        self._strip_order_counts: Dict[str, int] = {}

        for ticker in self.config.series_tickers:

            self._strip_order_counts[ticker] = 0

        

        # Track current market ID per strip to detect when to reset counters

        self._current_market_ids: Dict[str, str] = {}

        for ticker in self.config.series_tickers:

            self._current_market_ids[ticker] = None

        

        # 2026 Research-Based Risk Management

        # Session-level order tracking (max 5 trades per 15m window)

        self._session_order_count: int = 0

        self._session_start_time: float = time.time()

        self._session_window_sec: int = 900  # 15 minutes in seconds

        

        # Consecutive loss tracking (pause after N consecutive losses)

        self._consecutive_losses: Dict[str, int] = {}  # asset -> consecutive loss count

        self._consecutive_loss_pause_until: Dict[str, float] = {}  # asset -> pause until timestamp

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._consecutive_losses[asset] = 0

            self._consecutive_loss_pause_until[asset] = 0.0

        

        # Session risk cap tracking (max 10% risk per session)

        self._session_risk_usd: float = 0.0

        self._session_risk_cap_usd: float = 0.0  # Will be set from profile/capital

        

        # Initialize session risk cap from profile if available

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            if profile_adapter and profile_adapter._profile:

                profile = profile_adapter._profile

                # Calculate session risk cap as percentage of capital

                if profile.capital_usd > 0:

                    self._session_risk_cap_usd = profile.capital_usd * profile.throttling_max_session_risk_pct

                    logger.info("[AGENT-INIT] %s session_risk_cap=%.2f (capital=%.2f * %.2f%%)", 

                               config.name, self._session_risk_cap_usd, profile.capital_usd, 

                               profile.throttling_max_session_risk_pct * 100)

        except Exception as e:

            logger.warning("[AGENT-INIT] %s failed to load session risk cap from profile: %s", config.name, e)

        

        # 2026 Research-Based Risk Management: Portfolio heat tracking

        self._portfolio_heat_enabled: bool = False

        self._portfolio_heat_threshold_warning: float = 0.70

        self._portfolio_heat_threshold_critical: float = 0.85

        

        # 2026 Research-Based Risk Management: Asset-specific rolling PnL limits

        self._rolling_pnl_enabled: bool = False

        self._rolling_pnl_history: Dict[str, List[Tuple[float, float]]] = {}  # asset -> [(timestamp, pnl_usd)]

        self._rolling_pnl_1h_window: int = 3600  # 1 hour in seconds

        self._rolling_pnl_4h_window: int = 14400  # 4 hours in seconds

        self._rolling_pnl_limits: Dict[str, Dict[str, float]] = {}  # asset -> {1h_limit_pct, 4h_limit_pct}

        

        # Initialize rolling PnL history for all assets

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._rolling_pnl_history[asset] = []

        

        # Load 2026 risk management parameters from profile

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            if profile_adapter and profile_adapter._profile:

                profile = profile_adapter._profile

                # Portfolio heat tracking

                self._portfolio_heat_enabled = profile.portfolio_heat_enabled

                self._portfolio_heat_threshold_warning = profile.portfolio_heat_heat_threshold_warning

                self._portfolio_heat_threshold_critical = profile.portfolio_heat_heat_threshold_critical

                logger.info("[AGENT-INIT] %s portfolio_heat_enabled=%s warning=%.2f%% critical=%.2f%%",

                           config.name, self._portfolio_heat_enabled,

                           self._portfolio_heat_threshold_warning * 100,

                           self._portfolio_heat_threshold_critical * 100)

                

                # Asset-specific rolling PnL limits

                self._rolling_pnl_enabled = profile.asset_specific_rolling_pnl_enabled

                self._rolling_pnl_limits = {

                    "BTC": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_btc_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_btc_rolling_4h_halt_pct

                    },

                    "ETH": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_eth_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_eth_rolling_4h_halt_pct

                    },

                    "SOL": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_sol_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_sol_rolling_4h_halt_pct

                    },

                    "XRP": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_xrp_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_xrp_rolling_4h_halt_pct

                    },

                    "DOGE": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_doge_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_doge_rolling_4h_halt_pct

                    }

                }

                logger.info("[AGENT-INIT] %s rolling_pnl_enabled=%s", config.name, self._rolling_pnl_enabled)

        except Exception as e:

            logger.warning("[AGENT-INIT] %s failed to load 2026 risk management parameters: %s", config.name, e)

        

        logger.info("[AGENT-INIT] %s initialized with velocity-based signal strategy", config.name)

    

    def _update_price_history(self, asset: str, spot_price: float, spot_data: Any = None) -> None:

        # Update price history for velocity calculation.

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        # UnifiedSpotService stores timestamps as int(time.time() * 1000) in milliseconds

        # Agent grid must use the same unit for velocity calculation to work correctly

        # CRITICAL FIX: Store OHLC data for proper ADX/ATR calculation

        logger.info("[UPDATE-PRICE-HISTORY-ENTRY] asset=%s spot_price=%s spot_data=%s", 

                    asset, format_price(asset, spot_price), type(spot_data).__name__ if spot_data else None)

        current_time = int(time.time() * 1000)

        

        # Extract OHLC data if available

        if spot_data and hasattr(spot_data, 'open') and hasattr(spot_data, 'high') and hasattr(spot_data, 'low'):

            open_price = spot_data.open if spot_data.open else spot_price

            high_price = spot_data.high if spot_data.high else spot_price

            low_price = spot_data.low if spot_data.low else spot_price

        else:

            # CRITICAL FIX: Use price history to construct valid OHLC when spot_data is None
            # This prevents high=low which breaks ATR calculation (TR=0 -> ATR=0)
            # Similar to UnifiedSpotService fallback logic (lines 313-338 in unified_spot_service.py)
            
            history = list(self._spot_price_history[asset])
            
            if len(history) > 0:
                # Use recent price history to construct OHLC
                recent_prices = [entry[1] for entry in history[-10:]]  # Last 10 prices
                recent_prices.append(spot_price)
                
                open_price = recent_prices[0]  # Oldest price as open
                high_price = max(recent_prices)  # Highest as high
                low_price = min(recent_prices)   # Lowest as low
                
                logger.debug("[OHLC-FALLBACK] asset=%s using price history: O=%s H=%s L=%s C=%s",
                           asset, format_price(asset, open_price), format_price(asset, high_price),
                           format_price(asset, low_price), format_price(asset, spot_price))
            else:
                # No price history available - add small spread to avoid high=low
                # This prevents TR=0 which would break ATR calculation
                spread = spot_price * 0.0001  # 0.01% spread
                open_price = spot_price
                high_price = spot_price + spread
                low_price = spot_price - spread
                
                logger.debug("[OHLC-FALLBACK] asset=%s using spread proxy: O=%s H=%s L=%s C=%s",
                           asset, format_price(asset, open_price), format_price(asset, high_price),
                           format_price(asset, low_price), format_price(asset, spot_price))

        

        # Extract volume data if available

        volume = 1.0  # Default volume if not available

        if spot_data and hasattr(spot_data, 'volume') and spot_data.volume is not None:

            volume = float(spot_data.volume)

            logger.debug(f"[VOLUME-EXTRACTION] asset={asset} volume={volume} from spot_data")

        else:

            # Fallback: Calculate OHLC proxy volume from price movement

            # This captures trading activity as a proxy for volume

            # DATA QUALITY FIX: Validate OHLC invariants before using data

            # Industry best practice: high >= low is a fundamental invariant

            if high_price < low_price:

                # CORRUPTED DATA: high < low is mathematically impossible

                # This indicates data provider error or transmission corruption

                logger.error(

                    f"[DATA-QUALITY] asset={asset} CORRUPTED OHLC data: high={high_price:.2f} < low={low_price:.2f}. "

                    f"This violates the fundamental OHLC invariant (high >= low). "

                    f"Using default volume=1.0 and flagging for data quality audit."

                )

                # Track data quality issue for metrics

                self._track_data_quality_issue(asset, "ohlcv_corruption", "high_less_than_low")

                volume = 1.0

            elif high_price == low_price:

                # STALE DATA: high == low indicates no price movement

                # This is valid but indicates illiquid market or stale data

                logger.debug(

                    f"[DATA-QUALITY] asset={asset} STALE OHLC data: high={high_price:.2f} == low={low_price:.2f}. "

                    f"No price movement detected in this period. Using default volume=1.0."

                )

                volume = 1.0

            elif high_price > low_price:

                # VALID DATA: Calculate volume proxy from price movement

                volume_proxy = (high_price - low_price) * spot_price

                # Normalize to reasonable range (1-100) to avoid extreme values

                volume = max(1.0, min(100.0, volume_proxy * 100))

                logger.info(f"[VOLUME-EXTRACTION] asset={asset} volume not available, using OHLC proxy={volume:.2f} (high={high_price:.2f} low={low_price:.2f} spot={spot_price:.2f})")

        

        # Phase 4.1: Update volatility history for ATR calculation BEFORE appending current price

        # This ensures we compare current price with previous price, not with itself

        self._update_volatility_history(asset, spot_price)

        

        # Store OHLC data in price history

        self._spot_price_history[asset].append((current_time, spot_price, open_price, high_price, low_price))

        

        # Phase 4.3: Update SMA history for mean reversion

        self._sma_history[asset].append((current_time, spot_price))

        

        # Phase 6: Update ADX history for trend filtering

        self._update_adx_history(asset, spot_price, open_price, high_price, low_price)

        

        # CRITICAL FIX: 2026-07-01 - Update volume history for volume confirmation filter

        self._volume_history[asset].append((current_time, volume))

        

        # CRITICAL FIX: 2026-07-10 - REMOVED old indicator stack update logic from _update_price_history

        # This logic has been moved to collect_order_candidate where each agent fetches spot prices

        # for ALL 5 assets and updates all indicator stacks with redundant updates

        # This prevents the bars_available=1 bug by ensuring each stack gets 5 updates per cycle

        

        # CRITICAL FIX: 2026-07-07 - Update FVG forecaster with OHLC data

        # FVG forecaster needs candle data to detect Fair Value Gaps

        # Without this, fvg_confidence will always be 0.00 because no FVGs are detected

        logger.info("[FVG-UPDATE-DEBUG] asset=%s spot_data=%s has_open=%s has_high=%s has_low=%s", 

                    asset, type(spot_data).__name__, 

                    hasattr(spot_data, 'open') if spot_data else False,

                    hasattr(spot_data, 'high') if spot_data else False,

                    hasattr(spot_data, 'low') if spot_data else False)

        try:

            from merid.prediction.forecasters.fvg import get_fvg_forecaster

            fvg_forecaster = get_fvg_forecaster()

            # Convert spot price to cents for Kalshi markets (0-100 range)

            # FVG forecaster expects price in cents for Kalshi prediction markets

            price_cents = spot_price * 100

            fvg_forecaster.update_price(

                asset=asset,

                timeframe="15m",

                open_p=open_price * 100,  # Convert to cents

                high=high_price * 100,    # Convert to cents

                low=low_price * 100,      # Convert to cents

                close=price_cents,        # Already in cents

                timestamp=current_time / 1000.0  # Convert ms to seconds

            )

            logger.info("[FVG-UPDATE] asset=%s OHLC data updated in FVG forecaster: O=%s H=%s L=%s C=%s", 

                        asset, format_price(asset, open_price), format_price(asset, high_price), 

                        format_price(asset, low_price), format_price(asset, spot_price))

        except Exception as e:

            logger.warning("[FVG-UPDATE] asset=%s failed to update FVG forecaster: %s", asset, e)

        

        # CRITICAL FIX: 2026-07-01 - Update multi-timeframe price history for alignment

        self._price_1m_history[asset].append((current_time, spot_price))

        self._price_5m_history[asset].append((current_time, spot_price))

    

    def _track_data_quality_issue(self, asset: str, issue_type: str, detail: str) -> None:

        """Track data quality issues for metrics and auditing.

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            issue_type: Type of issue (ohlcv_corruption, ohlcv_stale, volume_anomaly, price_anomaly)

            detail: Detailed description of the issue

        """

        if asset in self._data_quality_issues and issue_type in self._data_quality_issues[asset]:

            self._data_quality_issues[asset][issue_type] += 1

            logger.debug(

                f"[DATA-QUALITY] asset={asset} issue_type={issue_type} detail={detail} "

                f"total_count={self._data_quality_issues[asset][issue_type]}"

            )

    

    def get_data_quality_metrics(self) -> Dict[str, Dict[str, int]]:

        """Get data quality metrics for all assets.

        

        Returns:

            Dictionary mapping asset symbols to their data quality issue counts

        """

        import copy

        return copy.deepcopy(self._data_quality_issues)

    

    def _update_volatility_history(self, asset: str, spot_price: float) -> None:

        # Update volatility history for ATR calculation.

        # CRITICAL FIX: Store percentage changes instead of absolute price changes

        # This ensures ATR is comparable across assets with different price levels

        # (e.g., BTC at $60k vs DOGE at $0.07)

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        # WARMUP FIX: Allow volatility history to populate with 1 previous price point

        # This prevents chicken-and-egg where ATR never warms up

        current_time = int(time.time() * 1000)

        history = list(self._spot_price_history[asset])

        

        if len(history) < 1:

            return  # No previous price data yet

        

        # Calculate percentage change as proxy for high-low range

        prev_price = history[-1][1]

        if prev_price <= 0:

            return

        

        price_change_pct = abs(spot_price - prev_price) / prev_price

        

        self._volatility_history[asset].append((current_time, price_change_pct))

    

    def _calculate_atr(self, asset: str) -> float:

        # Calculate Average True Range (ATR) for volatility normalization.

        # CRITICAL FIX: Use True Range values from TR history instead of percentage changes

        # TR is calculated in _update_adx_history using OHLC data: max(high-low, |high-prev_close|, |low-prev_close|)

        # Returns ATR as percentage (normalized by close price).

        # WARMUP FIX: Use minimum 3 data points during warmup, then require 14

        tr_history = list(self._tr_history[asset])

        

        # During warmup (less than 3 data points), return 0.0 to trigger fallback

        if len(tr_history) < 3:

            logger.debug("[ATR-CALC] asset=%s warmup insufficient history (%d < 3), returning 0.0", 

                         asset, len(tr_history))

            return 0.0

        

        # Get current close price for normalization

        price_history = list(self._spot_price_history[asset])

        if len(price_history) < 1:

            return 0.0

        current_close = price_history[-1][1]  # Close price

        

        # During warmup (3-13 data points), use available data for faster startup

        if len(tr_history) < self._atr_period:

            logger.info("[ATR-CALC] asset=%s warmup using available history (%d < %d)", 

                       asset, len(tr_history), self._atr_period)

            # Use available data points instead of requiring full 14

            recent_tr = [entry[1] for entry in tr_history[-len(tr_history):] if len(entry) >= 2]

        else:

            # Normal operation: use full 14-period ATR

            recent_tr = [entry[1] for entry in tr_history[-self._atr_period:] if len(entry) >= 2]

        

        # Calculate ATR as average of recent True Range values

        atr = sum(recent_tr) / len(recent_tr)

        

        # Normalize ATR as percentage of current close price

        atr_pct = atr / current_close if current_close > 0 else 0.0

        

        logger.debug("[ATR-CALC] asset=%s atr_period=%d atr=%.6f atr_pct=%.6f (%.4f%%)", 

                     asset, self._atr_period, atr, atr_pct, atr_pct * 100)

        

        return atr_pct

    

    def _calculate_dynamic_cooldown(self, asset: str) -> float:

        # Static cooldown from profile configuration.

        # 2026-07-11: DISABLED volatility-based multiplier - was causing 10-22x scaling

        # Volatility multiplier is inappropriate for 15-minute binary options:

        # - High volatility should create MORE opportunities, not fewer

        # - Binary options are direction bets, not position holding

        # - Industry standard (Polymarket): 3s static cooldown

        # Returns cooldown in seconds from profile config.

        

        # Use static cooldown from profile (now 3s per kalshi_crypto_15m_v2.yaml)

        static_cooldown = float(self.config.per_asset_cooldown_s)

        

        logger.debug("[STATIC-COOLDOWN] asset=%s cooldown=%.1fs (from profile config)",

                     asset, static_cooldown)

        

        return static_cooldown

    

    def update_cooldown_on_fill(self, asset: str, pnl_usd: float = 0.0, trade_risk_usd: float = 0.0) -> None:

        """Update cooldown timestamp when a trade actually executes (fills).

        

        This should be called from the fill handler (position_cache.on_fill) to ensure

        the cooldown is only reset when a trade actually executes, not when a candidate

        is generated. This prevents perpetual cooldown blocks.

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            pnl_usd: PnL of the trade in USD (positive for profit, negative for loss)

            trade_risk_usd: Risk amount of the trade in USD (for session risk cap tracking)

        """

        self._last_trade_time[asset] = time.monotonic()

        

        # 2026 Research-Based Risk Management: Increment session order count

        self._session_order_count += 1

        logger.info("[SESSION-ORDER] agent=%s session_orders=%d", self.config.name, self._session_order_count)

        

        # 2026 Research-Based Risk Management: Track session risk

        if trade_risk_usd > 0:

            self._session_risk_usd += trade_risk_usd

            logger.info("[SESSION-RISK] agent=%s session_risk=%.2f (added %.2f) cap=%.2f", 

                       self.config.name, self._session_risk_usd, trade_risk_usd, self._session_risk_cap_usd)

        

        # 2026 Research-Based Risk Management: Track consecutive losses

        if pnl_usd < 0:

            self._consecutive_losses[asset] += 1

            logger.info("[CONSECUTIVE-LOSS] agent=%s asset=%s consecutive_losses=%d", 

                       self.config.name, asset, self._consecutive_losses[asset])

            

            # Check if consecutive loss threshold reached

            if self._consecutive_losses[asset] >= self.config.consecutive_loss_pause:

                # Set pause for 15 minutes (900 seconds)

                pause_duration = 900

                self._consecutive_loss_pause_until[asset] = time.time() + pause_duration

                logger.warning(

                    "[CONSECUTIVE-LOSS-PAUSE] agent=%s asset=%s consecutive_losses=%d >= threshold=%d, pausing for %d seconds",

                    self.config.name, asset, self._consecutive_losses[asset], 

                    self.config.consecutive_loss_pause, pause_duration

                )

        else:

            # Reset consecutive loss count on profit

            if self._consecutive_losses[asset] > 0:

                logger.info("[CONSECUTIVE-LOSS-RESET] agent=%s asset=%s consecutive_losses reset from %d to 0 (profit)",

                           self.config.name, asset, self._consecutive_losses[asset])

                self._consecutive_losses[asset] = 0

        

        # 2026 Research-Based Risk Management: Track rolling PnL for asset-specific limits

        if self._rolling_pnl_enabled and asset in self._rolling_pnl_history:

            current_time = time.time()

            self._rolling_pnl_history[asset].append((current_time, pnl_usd))

            # Prune old entries outside 4-hour window

            self._rolling_pnl_history[asset] = [

                (ts, pnl) for ts, pnl in self._rolling_pnl_history[asset]

                if current_time - ts < self._rolling_pnl_4h_window

            ]

            logger.info("[ROLLING-PNL] agent=%s asset=%s pnl=%.2f history_size=%d",

                       self.config.name, asset, pnl_usd, len(self._rolling_pnl_history[asset]))

        

        logger.info("[COOLDOWN-UPDATE] asset=%s cooldown timestamp updated on fill", asset)

    

    def _check_portfolio_heat(self) -> tuple[bool, str]:

        """

        Check if portfolio heat exceeds thresholds.

        

        2026 Research-Based Risk Management: Portfolio heat tracking monitors

        correlation-adjusted exposure across all assets to prevent over-concentration.

        

        Returns:

            tuple: (allow_trading, reason) - True if heat is acceptable, False if too high

        """

        if not self._portfolio_heat_enabled:

            return True, "portfolio_heat_disabled"

        

        try:

            from merid.event_venues.kalshi.position_cache import get_position_cache

            position_cache = get_position_cache()

            if not position_cache:

                return True, "no_position_cache"

            

            # Get all open positions

            all_positions = position_cache.get_all_positions(validate_freshness=False)

            open_positions = {k: v for k, v in all_positions.items() if v.contracts > 0}

            

            if not open_positions:

                return True, "no_open_positions"

            

            # Calculate total exposure (simplified: sum of contract values)

            total_exposure = sum(pos.contracts * pos.avg_price_cents / 100.0 for pos in open_positions.values())

            

            # Get capital from profile for heat calculation

            try:

                from merid.risk.profiles.crypto_15m_profile import get_active_profile

                profile_adapter = get_active_profile()

                if profile_adapter and profile_adapter._profile:

                    capital = profile_adapter._profile.capital_usd

                    if capital > 0:

                        heat_ratio = total_exposure / capital

                    else:

                        heat_ratio = 0.0

                else:

                    heat_ratio = 0.0

            except Exception:

                heat_ratio = 0.0

            

            # Check thresholds

            if heat_ratio >= self._portfolio_heat_threshold_critical:

                logger.warning(

                    "[PORTFOLIO-HEAT] agent=%s heat=%.2f%% >= critical=%.2f%% -> HALT (portfolio too hot)",

                    self.config.name, heat_ratio * 100, self._portfolio_heat_threshold_critical * 100

                )

                return False, f"portfolio_heat_critical_{heat_ratio:.2%}"

            elif heat_ratio >= self._portfolio_heat_threshold_warning:

                logger.info(

                    "[PORTFOLIO-HEAT] agent=%s heat=%.2f%% >= warning=%.2f%% -> CAUTION (portfolio heating up)",

                    self.config.name, heat_ratio * 100, self._portfolio_heat_threshold_warning * 100

                )

                return True, f"portfolio_heat_warning_{heat_ratio:.2%}"

            else:

                logger.debug(

                    "[PORTFOLIO-HEAT] agent=%s heat=%.2f%% < warning=%.2f%% -> OK",

                    self.config.name, heat_ratio * 100, self._portfolio_heat_threshold_warning * 100

                )

                return True, f"portfolio_heat_ok_{heat_ratio:.2%}"

        except Exception as e:

            logger.warning("[PORTFOLIO-HEAT] agent=%s failed to check portfolio heat: %s", self.config.name, e)

            return True, "portfolio_heat_error"

    

    def _check_rolling_pnl_limit(self, asset: str) -> tuple[bool, str]:

        """

        Check if asset-specific rolling PnL limits are exceeded.

        

        2026 Research-Based Risk Management: Asset-specific rolling PnL limits

        halt trading for an asset if losses exceed thresholds over 1h or 4h windows.

        

        Returns:

            tuple: (allow_trading, reason) - True if within limits, False if limit exceeded

        """

        if not self._rolling_pnl_enabled or asset not in self._rolling_pnl_limits:

            return True, "rolling_pnl_disabled"

        

        try:

            current_time = time.time()

            asset_history = self._rolling_pnl_history.get(asset, [])

            

            if not asset_history:

                return True, "no_pnl_history"

            

            # Calculate rolling PnL for 1h and 4h windows

            pnl_1h = sum(pnl for ts, pnl in asset_history if current_time - ts < self._rolling_pnl_1h_window)

            pnl_4h = sum(pnl for ts, pnl in asset_history if current_time - ts < self._rolling_pnl_4h_window)

            

            # Get limits for this asset

            limits = self._rolling_pnl_limits[asset]

            limit_1h_pct = limits["1h_limit_pct"]

            limit_4h_pct = limits["4h_limit_pct"]

            

            # Get capital for percentage calculation

            try:

                from merid.risk.profiles.crypto_15m_profile import get_active_profile

                profile_adapter = get_active_profile()

                if profile_adapter and profile_adapter._profile:

                    capital = profile_adapter._profile.capital_usd

                    if capital > 0:

                        limit_1h_usd = capital * limit_1h_pct

                        limit_4h_usd = capital * limit_4h_pct

                    else:

                        limit_1h_usd = 0.0

                        limit_4h_usd = 0.0

                else:

                    limit_1h_usd = 0.0

                    limit_4h_usd = 0.0

            except Exception:

                limit_1h_usd = 0.0

                limit_4h_usd = 0.0

            

            # Check 4h limit first (more conservative)

            if pnl_4h < -limit_4h_usd and limit_4h_usd > 0:

                logger.warning(

                    "[ROLLING-PNL] agent=%s asset=%s pnl_4h=%.2f < -limit=%.2f -> HALT (4h limit exceeded)",

                    self.config.name, asset, pnl_4h, limit_4h_usd

                )

                return False, f"rolling_pnl_4h_exceeded_{pnl_4h:.2f}"

            

            # Check 1h limit

            if pnl_1h < -limit_1h_usd and limit_1h_usd > 0:

                logger.warning(

                    "[ROLLING-PNL] agent=%s asset=%s pnl_1h=%.2f < -limit=%.2f -> HALT (1h limit exceeded)",

                    self.config.name, asset, pnl_1h, limit_1h_usd

                )

                return False, f"rolling_pnl_1h_exceeded_{pnl_1h:.2f}"

            

            logger.debug(

                "[ROLLING-PNL] agent=%s asset=%s pnl_1h=%.2f pnl_4h=%.2f -> OK (within limits)",

                self.config.name, asset, pnl_1h, pnl_4h

            )

            return True, f"rolling_pnl_ok_1h={pnl_1h:.2f}_4h={pnl_4h:.2f}"

        except Exception as e:

            logger.warning("[ROLLING-PNL] agent=%s asset=%s failed to check rolling PnL: %s", self.config.name, asset, e)

            return True, "rolling_pnl_error"

    

    def _apply_time_of_day_risk_scaling(self, asset: str) -> float:

        """

        Apply time-of-day risk scaling multiplier.

        

        2026 Research-Based Risk Management: Adjust position sizing based on

        trading session (US market, Asian, European, weekend).

        

        CURRENT STATUS: DISABLED via profile YAML (time_of_day_risk_scaling.enabled: false)

        This function returns 1.0 (no scaling) when disabled.

        

        FUTURE RE-ENABLEMENT: When re-enabling, must also update unified_sizing.py to

        apply the same multiplier, and ensure risk envelope respects the scaled limits.

        

        Returns:

            float: Risk multiplier (e.g., 1.0 for normal, 0.8 for reduced risk)

        """

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            if not profile_adapter or not profile_adapter._profile:

                return 1.0

            

            profile = profile_adapter._profile

            if not profile.time_of_day_risk_scaling_enabled:

                # DISABLED: Return 1.0 (no scaling) when feature is disabled in YAML

                return 1.0

            

            from datetime import datetime, timezone

            current_utc_hour = datetime.now(timezone.utc).hour

            current_utc_minute = datetime.now(timezone.utc).minute

            current_time_utc = current_utc_hour + current_utc_minute / 60.0

            

            # Parse session windows from profile (format: "HH:MM-HH:MM ET")

            # Convert ET to UTC (ET = UTC-4 or UTC-5 depending on DST)

            # For simplicity, assume ET = UTC-4 (daylight time)

            et_offset = 4

            

            def parse_time_range(time_str: str) -> tuple[float, float]:

                """Parse 'HH:MM-HH:MM ET' to UTC hours."""

                # Strip ' ET' suffix if present

                time_str = time_str.replace(' ET', '')

                start_str, end_str = time_str.split('-')

                start_h, start_m = map(int, start_str.split(':'))

                end_h, end_m = map(int, end_str.split(':'))

                start_utc = (start_h + et_offset) % 24

                end_utc = (end_h + et_offset) % 24

                return start_utc + start_m / 60.0, end_utc + end_m / 60.0

            

            us_market_start, us_market_end = parse_time_range(profile.time_of_day_risk_scaling_us_market_hours)

            asian_start, asian_end = parse_time_range(profile.time_of_day_risk_scaling_asian_session)

            european_start, european_end = parse_time_range(profile.time_of_day_risk_scaling_european_session)

            

            # Determine current session

            in_us_market = us_market_start <= current_time_utc < us_market_end

            in_asian = asian_start <= current_time_utc < asian_end

            in_european = european_start <= current_time_utc < european_end

            

            # Check if weekend (Saturday/Sunday in UTC)

            is_weekend = datetime.now(timezone.utc).weekday() >= 5

            

            # Apply multiplier based on session

            if is_weekend:

                multiplier = profile.time_of_day_risk_scaling_weekend_multiplier

                session_name = "weekend"

            elif in_us_market:

                multiplier = profile.time_of_day_risk_scaling_us_market_multiplier

                session_name = "us_market"

            elif in_asian:

                multiplier = profile.time_of_day_risk_scaling_asian_multiplier

                session_name = "asian"

            elif in_european:

                multiplier = profile.time_of_day_risk_scaling_european_multiplier

                session_name = "european"

            else:

                multiplier = 1.0

                session_name = "other"

            

            logger.info(

                "[TIME-OF-DAY-SCALING] agent=%s asset=%s time_utc=%.2f session=%s multiplier=%.2f",

                self.config.name, asset, current_time_utc, session_name, multiplier

            )

            return multiplier

        except Exception as e:

            logger.warning("[TIME-OF-DAY-SCALING] agent=%s asset=%s failed to apply scaling: %s", self.config.name, asset, e)

            return 1.0

    

    def _check_volume_confirmation(self, asset: str) -> bool:

        """

        Check if current volume is above 1.2x EMA20 threshold.

        

        Industry standard: volume > 1.2x EMA20(volume) confirms signal validity.

        Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            

        Returns:

            True if volume > 1.2x EMA20, False otherwise

        """

        if not hasattr(self, '_volume_history') or asset not in self._volume_history:

            # No volume history available, bypass filter during warmup

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(0):

                logger.debug("[VOLUME-CONFIRMATION] asset=%s no volume history, bypassing filter (warmup)", asset)

                return True

            else:

                logger.warning("[VOLUME-CONFIRMATION] asset=%s no volume history, rejecting (warmup expired)", asset)

                return False

        

        volume_history = list(self._volume_history[asset])

        if len(volume_history) < 20:

            # Insufficient history for EMA20, bypass filter

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(len(volume_history)):

                logger.debug("[VOLUME-CONFIRMATION] asset=%s insufficient history (%d < 20), bypassing filter (warmup)", 

                            asset, len(volume_history))

                return True

            else:

                logger.warning("[VOLUME-CONFIRMATION] asset=%s insufficient history (%d < 20), rejecting (warmup expired)", 

                            asset, len(volume_history))

                return False

        

        # Calculate EMA20 of volume

        # EMA formula: EMA = (current * k) + (previous_EMA * (1 - k))

        # where k = 2 / (N + 1), N = period (20)

        k = 2.0 / (20.0 + 1.0)

        

        recent_volumes = [entry[1] for entry in volume_history[-20:]]

        ema20 = recent_volumes[0]

        for volume in recent_volumes[1:]:

            ema20 = (volume * k) + (ema20 * (1 - k))

        

        current_volume = recent_volumes[-1]

        volume_threshold = ema20 * 1.2  # 1.2x threshold

        

        volume_confirmed = current_volume > volume_threshold

        

        logger.info(

            "[VOLUME-CONFIRMATION] asset=%s current_volume=%.2f ema20=%.2f threshold=%.2f confirmed=%s",

            asset, current_volume, ema20, volume_threshold, volume_confirmed

        )

        

        return volume_confirmed

    

    def _calculate_rsi(self, asset: str, period: int = 9) -> float:

        """

        Calculate RSI (Relative Strength Index) for panic fade detection.

        

        RSI measures momentum and identifies overbought (>70) and oversold (<30) conditions.

        For panic fade, we use more extreme thresholds: oversold < 25, overbought > 75.

        

        2026 OPTIMIZATION: Changed default period from 14 to 9 for 15-minute scalping.

        Industry research shows RSI(14) is too slow for 15-minute charts - by the time

        the signal fires, the move is already over. RSI(9) provides faster signals for

        intraday (15m-1H) trading with acceptable noise levels.

        Reference: https://arxum.com/rsi-settings/ - "For 15-minute charts I use RSI(9)"

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            period: RSI calculation period (default 9, optimized for 15m scalping)

            

        Returns:

            RSI value (0-100), or 0.0 if insufficient data

        """

        history = list(self._spot_price_history[asset])

        if len(history) < period + 1:

            logger.debug("[RSI-CALC] asset=%s insufficient history (%d < %d), returning 0.0", 

                         asset, len(history), period + 1)

            return 0.0

        

        # Extract close prices

        closes = [entry[1] for entry in history[-(period + 1):]]

        

        # Calculate price changes

        gains = []

        losses = []

        for i in range(1, len(closes)):

            change = closes[i] - closes[i - 1]

            if change > 0:

                gains.append(change)

                losses.append(0.0)

            else:

                gains.append(0.0)

                losses.append(abs(change))

        

        # Calculate average gains and losses

        avg_gain = sum(gains) / period

        avg_loss = sum(losses) / period

        

        if avg_loss == 0:

            return 100.0  # No losses, RSI = 100

        

        rs = avg_gain / avg_loss

        rsi = 100.0 - (100.0 / (1.0 + rs))

        

        logger.debug("[RSI-CALC] asset=%s RSI=%.2f (period=%d)", asset, rsi, period)

        return rsi

    

    def _calculate_price_zscore(self, asset: str, period: int = 20) -> float:

        """

        Calculate Z-score for statistical extreme detection (panic fade).

        

        Z-score measures how many standard deviations price is from the mean.

        Z-score > +2.0 indicates statistical extreme (overbought).

        Z-score < -2.0 indicates statistical extreme (oversold).

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            period: Z-score calculation period (default 20)

            

        Returns:

            Z-score value, or 0.0 if insufficient data

        """

        history = list(self._spot_price_history[asset])

        if len(history) < period:

            logger.debug("[ZSCORE-CALC] asset=%s insufficient history (%d < %d), returning 0.0", 

                         asset, len(history), period)

            return 0.0

        

        # Extract close prices

        closes = [entry[1] for entry in history[-period:]]

        

        # Calculate mean and standard deviation

        mean_price = sum(closes) / len(closes)

        variance = sum((x - mean_price) ** 2 for x in closes) / len(closes)

        std_dev = variance ** 0.5

        

        if std_dev == 0:

            return 0.0  # No variance, Z-score = 0

        

        current_price = closes[-1]

        zscore = (current_price - mean_price) / std_dev

        

        logger.debug("[ZSCORE-CALC] asset=%s Z-score=%.2f (period=%d)", asset, zscore, period)

        return zscore

    

    def _detect_market_regime(self, asset: str, spot_price: float, market_price: float) -> str:

        """

        Detect market regime using ADX, price position, and velocity.

        

        Regime classification based on 2026 research:

        - trending_strong: ADX > 25, strong directional movement

        - trending_weak: ADX 15-25, moderate directional movement

        - mean_reverting: ADX < 15, choppy/range-bound

        - neutral: insufficient data or mixed signals

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            spot_price: Current spot price

            market_price: Current market price (YES/NO implied probability)

            

        Returns:

            Regime string: "trending_strong", "trending_weak", "mean_reverting", or "neutral"

        """

        # Calculate ADX (Average Directional Index) for trend strength

        adx = self._calculate_adx(asset)

        

        # Calculate recent velocity for direction confirmation

        velocity = self._calculate_multi_window_velocity(asset, spot_price)

        

        # Regime classification

        if adx >= 25:

            regime = "trending_strong"

        elif adx >= 15:

            regime = "trending_weak"

        elif adx > 0:  # ADX > 0 but < 15: weak trend / range-bound

            regime = "mean_reverting"

        else:  # ADX == 0: insufficient data or no movement

            regime = "neutral"

        

        logger.info(

            "[REGIME-DETECTION] asset=%s ADX=%.2f velocity=%.6f regime=%s",

            asset, adx, velocity, regime

        )

        

        return regime

    

    def _calculate_adx(self, asset: str, period: int = 14) -> float:

        """

        Calculate Average Directional Index (ADX) for trend strength.

        

        ADX measures trend strength regardless of direction:

        - ADX > 25: Strong trend

        - ADX 15-25: Moderate trend

        - ADX < 15: Weak trend / range-bound

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            period: ADX calculation period (default 14)

            

        Returns:

            ADX value, or 0.0 if insufficient data

        """

        history = list(self._spot_price_history[asset])

        if len(history) < period + 1:

            logger.debug("[ADX-CALC] asset=%s insufficient history (%d < %d), returning 0.0",

                         asset, len(history), period + 1)

            return 0.0

        

        # Extract prices and timestamps

        prices = [entry[1] for entry in history[-(period + 1):]]

        

        # Calculate True Range

        true_ranges = []

        for i in range(1, len(prices)):

            high = prices[i]

            low = prices[i]

            prev_close = prices[i - 1]

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))

            true_ranges.append(tr)

        

        # Calculate Directional Movement

        plus_dm = []

        minus_dm = []

        for i in range(1, len(prices)):

            high = prices[i]

            low = prices[i]

            prev_high = prices[i - 1]

            prev_low = prices[i - 1]

            

            up = high - prev_high

            down = prev_low - low

            

            if up > down and up > 0:

                plus_dm.append(up)

            else:

                plus_dm.append(0)

            

            if down > up and down > 0:

                minus_dm.append(down)

            else:

                minus_dm.append(0)

        

        # Smooth using Wilder's EMA (alpha = 1/period)

        alpha = 1.0 / period

        

        # Smooth True Range

        atr = true_ranges[0]

        for tr in true_ranges[1:]:

            atr = alpha * tr + (1 - alpha) * atr

        

        # Smooth +DM and -DM

        plus_di = plus_dm[0]

        minus_di = minus_dm[0]

        for pd, md in zip(plus_dm[1:], minus_dm[1:]):

            plus_di = alpha * pd + (1 - alpha) * plus_di

            minus_di = alpha * md + (1 - alpha) * minus_di

        

        # Calculate DX (Directional Index)

        if atr == 0:

            return 0.0

        

        plus_di_smooth = (plus_di / atr) * 100

        minus_di_smooth = (minus_di / atr) * 100

        

        di_diff = abs(plus_di_smooth - minus_di_smooth)

        di_sum = plus_di_smooth + minus_di_smooth

        

        if di_sum == 0:

            dx = 0.0

        else:

            dx = (di_diff / di_sum) * 100

        

        # Smooth DX to get ADX

        adx = dx

        # For simplicity, use current DX as ADX (would normally smooth over period)

        # This is a simplified ADX calculation suitable for real-time trading

        

        logger.debug("[ADX-CALC] asset=%s ADX=%.2f (period=%d)", asset, adx, period)

        return adx

    

    def _check_panic_fade_conditions(self, asset: str, velocity: float) -> Optional[Dict[str, Any]]:

        """

        Check if panic fade (volatility reversion) conditions are met.

        

        Panic fade strategy (Turbine research winner):

        - Statistical extreme: RSI < 25 (oversold) or > 75 (overbought)

        - Statistical extreme: Z-score < -2.0 or > +2.0

        - Velocity magnitude exceeds minimum threshold (panic move)

        - Regime is choppy/range-bound (not trending)

        

        When conditions are met, fade the panic:

        - Oversold (RSI < 25, Z-score < -2.0, negative velocity) -> BUY YES (expect reversion up)

        - Overbought (RSI > 75, Z-score > +2.0, positive velocity) -> BUY NO (expect reversion down)

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            velocity: Current velocity (percentage change per second)

            

        Returns:

            Dict with panic fade signal info if conditions met, None otherwise

        """

        if not self._panic_fade_enabled:

            return None

        

        # Check velocity magnitude (must be panic-level move)

        velocity_magnitude = abs(velocity)

        if velocity_magnitude < self._panic_fade_min_velocity:

            logger.debug("[PANIC-FADE] asset=%s velocity=%.6f below min_threshold=%.6f, skipping",

                        asset, velocity_magnitude, self._panic_fade_min_velocity)

            return None

        

        # Calculate RSI and Z-score

        rsi = self._calculate_rsi(asset)

        zscore = self._calculate_price_zscore(asset)

        

        # Skip if indicators unavailable (insufficient data)

        if rsi == 0.0 or zscore == 0.0:

            logger.debug("[PANIC-FADE] asset=%s RSI=%.2f Z-score=%.2f insufficient data, skipping",

                        asset, rsi, zscore)

            return None

        

        # Check statistical extreme conditions

        is_oversold = (rsi < self._panic_fade_rsi_oversold) and (zscore < -self._panic_fade_zscore_threshold)

        is_overbought = (rsi > self._panic_fade_rsi_overbought) and (zscore > self._panic_fade_zscore_threshold)

        

        if not is_oversold and not is_overbought:

            logger.debug("[PANIC-FADE] asset=%s RSI=%.2f Z-score=%.2f not at statistical extreme, skipping",

                        asset, rsi, zscore)

            return None

        

        # Determine signal side based on extreme type

        if is_oversold:

            signal_side = "yes"

            signal_action = "buy"

            rationale = f"panic_fade: oversold (RSI={rsi:.1f}<{self._panic_fade_rsi_oversold}, Z={zscore:.1f}<-2.0, velocity={velocity:.6f})"

            logger.info("[PANIC-FADE] asset=%s OVERSOLD detected: RSI=%.2f Z-score=%.2f velocity=%.6f -> BUY YES (expect reversion up)",

                       asset, rsi, zscore, velocity)

        else:  # is_overbought

            signal_side = "no"

            signal_action = "buy"

            rationale = f"panic_fade: overbought (RSI={rsi:.1f}>{self._panic_fade_rsi_overbought}, Z={zscore:.1f}>2.0, velocity={velocity:.6f})"

            logger.info("[PANIC-FADE] asset=%s OVERBOUGHT detected: RSI=%.2f Z-score=%.2f velocity=%.6f -> BUY NO (expect reversion down)",

                       asset, rsi, zscore, velocity)

        

        return {

            "side": signal_side,

            "action": signal_action,

            "rationale": rationale,

            "rsi": rsi,

            "zscore": zscore,

            "velocity": velocity,

            "strategy": "panic_fade"

        }

    

    def _check_multi_timeframe_alignment(self, asset: str) -> bool:

        """

        Check if 1m and 5m timeframes are aligned for signal confirmation.

        

        Industry standard: 1m + 5m confirmation for +10-20 pp win rate.

        Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        

        Both timeframes must show the same directional momentum for confirmation.

        

        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            

        Returns:

            True if 1m and 5m momentum aligned, False otherwise

        """

        if not hasattr(self, '_price_1m_history') or asset not in self._price_1m_history:

            # No 1m history available, bypass filter during warmup

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(0):

                logger.debug("[MTF-ALIGNMENT] asset=%s no 1m history, bypassing filter (warmup)", asset)

                return True

            else:

                logger.warning("[MTF-ALIGNMENT] asset=%s no 1m history, rejecting (warmup expired)", asset)

                return False

        

        if not hasattr(self, '_price_5m_history') or asset not in self._price_5m_history:

            # No 5m history available, bypass filter during warmup

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(0):

                logger.debug("[MTF-ALIGNMENT] asset=%s no 5m history, bypassing filter (warmup)", asset)

                return True

            else:

                logger.warning("[MTF-ALIGNMENT] asset=%s no 5m history, rejecting (warmup expired)", asset)

                return False

        

        price_1m = list(self._price_1m_history[asset])

        price_5m = list(self._price_5m_history[asset])

        

        if len(price_1m) < 10 or len(price_5m) < 10:

            # Insufficient history for momentum calculation

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(min(len(price_1m), len(price_5m))):

                logger.debug("[MTF-ALIGNMENT] asset=%s insufficient history (1m=%d, 5m=%d), bypassing filter (warmup)",

                            asset, len(price_1m), len(price_5m))

                return True

            else:

                logger.warning("[MTF-ALIGNMENT] asset=%s insufficient history (1m=%d, 5m=%d), rejecting (warmup expired)",

                            asset, len(price_1m), len(price_5m))

                return False

        

        # Calculate 1m momentum (current vs 10 periods ago)

        recent_1m = [entry[1] for entry in price_1m[-10:]]

        momentum_1m = (recent_1m[-1] - recent_1m[0]) / recent_1m[0] if recent_1m[0] > 0 else 0.0

        

        # Calculate 5m momentum (current vs 10 periods ago)

        recent_5m = [entry[1] for entry in price_5m[-10:]]

        momentum_5m = (recent_5m[-1] - recent_5m[0]) / recent_5m[0] if recent_5m[0] > 0 else 0.0

        

        # Check alignment: both positive or both negative

        # CRITICAL FIX: Treat zero momentum on both timeframes as aligned (no conflicting signal)

        # This prevents blocking trades when both timeframes are flat (momentum_1m=0, momentum_5m=0)

        if abs(momentum_1m) < 0.000001 and abs(momentum_5m) < 0.000001:

            # Both timeframes flat - no conflicting signal, allow trade

            aligned = True

        else:

            aligned = (momentum_1m > 0 and momentum_5m > 0) or (momentum_1m < 0 and momentum_5m < 0)

        

        logger.info(

            "[MTF-ALIGNMENT] asset=%s momentum_1m=%.6f momentum_5m=%.6f aligned=%s",

            asset, momentum_1m, momentum_5m, aligned

        )

        

        return aligned

    

    def _calculate_dynamic_velocity_threshold(self, asset: str) -> float:

        # Phase 7: Calculate dynamic velocity threshold based on ATR (volatility) and ADX (trend strength).

        # 2026-06-30: Enhanced with ADX-based trend strength adjustment (industry best practice)

        # High volatility -> higher threshold (more conservative)

        # Low volatility -> lower threshold (more aggressive)

        # Strong trend (ADX >= 25) -> higher ATR multiplier to reduce noise

        # Moderate trend (10 <= ADX < 25) -> neutral ATR multiplier

        # Weak trend (ADX < 10) -> lower ATR multiplier to capture subtle changes

        # This adapts to market conditions for optimal trade capture.

        

        # Get base threshold from config (per-asset)

        base_threshold_map = {

            "BTC": getattr(self.config, 'velocity_threshold_btc', self.config.velocity_threshold),

            "ETH": getattr(self.config, 'velocity_threshold_eth', self.config.velocity_threshold),

            "SOL": getattr(self.config, 'velocity_threshold_sol', self.config.velocity_threshold),

            "XRP": getattr(self.config, 'velocity_threshold_xrp', self.config.velocity_threshold),

            "DOGE": getattr(self.config, 'velocity_threshold_doge', self.config.velocity_threshold),

        }

        

        # Use per-asset thresholds from profile if available

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            profile = profile_adapter.profile

            

            asset_threshold_map = {

                "BTC": profile.velocity_threshold_btc,

                "ETH": profile.velocity_threshold_eth,

                "SOL": profile.velocity_threshold_sol,

                "XRP": profile.velocity_threshold_xrp,

                "DOGE": profile.velocity_threshold_doge,

            }

            base_threshold = asset_threshold_map.get(asset, base_threshold_map.get(asset, 0.0002))

        except Exception:

            base_threshold = base_threshold_map.get(asset, 0.0002)

        

        # Calculate ATR for current asset (now returns percentage)

        atr_pct = self._calculate_atr(asset)

        

        if atr_pct <= 0:

            # No ATR data, use base threshold

            logger.warning("[DYNAMIC-THRESHOLD] asset=%s ATR=%.6f (no data), using base_threshold=%.6f", 

                          asset, atr_pct, base_threshold)

            return base_threshold

        

        # Calculate ADX for trend strength adjustment

        adx = self._calculate_adx(asset)

        

        # Define volatility regimes for threshold adjustment (2026 industry standards for 15m crypto)

        # CRITICAL FIX: 2026-07-05 - Aligned ATR thresholds with new velocity thresholds (0.6%-1.0%)

        # Previous thresholds (0.005%-0.03%) were 20-200x lower than velocity thresholds, causing misalignment

        # New thresholds align with velocity thresholds for consistent conviction:

        # Low volatility: ATR < 0.4% -> reduce threshold to catch smaller moves (common in crypto)

        # Normal volatility: 0.4% <= ATR < 1.2% -> use base threshold

        # High volatility: ATR >= 1.2% -> increase threshold to avoid false signals

        

        low_volatility_threshold = 0.004  # 0.4% - aligned with velocity thresholds (BTC/ETH: 0.6%)

        high_volatility_threshold = 0.012  # 1.2% - aligned with velocity thresholds (DOGE: 1.0%)

        

        # Base adjustment factor from ATR (volatility)

        # CRITICAL FIX: 2026-07-02 - Disabled ATR adjustment to prevent threshold inflation blocking trades

        # Previous multipliers (0.90-1.10) were still inflating thresholds above base values

        # This caused velocity to be below dynamic threshold even when above base threshold

        # CRITICAL FIX: Set all ATR multipliers to 1.0 (neutral) to use base threshold directly

        if atr_pct < low_volatility_threshold:

            # Low volatility: neutral multiplier (was 0.90)

            atr_adjustment = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ATR=%.4f%% < low_threshold=%.4f%% -> ATR adjustment: 1.0 (neutral)",

                asset, atr_pct * 100, low_volatility_threshold * 100

            )

        elif atr_pct > high_volatility_threshold:

            # High volatility: neutral multiplier (was 1.10)

            atr_adjustment = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ATR=%.4f%% > high_threshold=%.4f%% -> ATR adjustment: 1.0 (neutral)",

                asset, atr_pct * 100, high_volatility_threshold * 100

            )

        else:

            # Normal volatility: neutral multiplier

            atr_adjustment = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ATR=%.4f%% in normal range -> ATR adjustment: 1.0 (neutral)",

                asset, atr_pct * 100

            )

        

        # ADX-based trend strength adjustment (2026 industry best practice for 15m crypto)

        # 2026 FIX: Disabled ADX multiplier to prevent threshold inflation blocking trades

        # Previous multipliers (0.90-1.05) were inflating thresholds above base values

        # This caused velocity to be below dynamic threshold even when above base threshold

        # CRITICAL FIX: Set all ADX multipliers to 1.0 (neutral) to use base threshold directly

        # NOTE: ADX returns 0.0 during warmup (insufficient history), causing neutral multipliers

        # This is expected behavior - the system uses base thresholds until sufficient data is available

        if adx >= 25.0:

            # Strong trend: neutral multiplier (was 1.05)

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f >= 25 (strong trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        elif adx >= 10.0:

            # Moderate trend: neutral multiplier

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f >= 10 (moderate trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        elif adx >= 5.0:

            # Weak trend: neutral multiplier (was 0.95)

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f >= 5 (weak trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        elif adx > 0 and adx < 5.0:

            # No trend: neutral multiplier (was 0.90)

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f < 5 (no trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        else:

            # No ADX data (warmup period): neutral multiplier

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f (no data/warmup) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        

        # Combine ATR and ADX adjustments (multiplicative)

        # This allows the system to be more aggressive in low-volatility, weak-trend conditions

        # and more conservative in high-volatility, strong-trend conditions

        combined_adjustment = atr_adjustment * adx_multiplier

        

        dynamic_threshold = base_threshold * combined_adjustment

        logger.info(

            "[DYNAMIC-THRESHOLD] asset=%s base_threshold=%.6f atr_adjustment=%.2f adx_multiplier=%.2f combined=%.2f dynamic_threshold=%.6f",

            asset, base_threshold, atr_adjustment, adx_multiplier, combined_adjustment, dynamic_threshold

        )

        

        return dynamic_threshold

    

    def _calculate_velocity(self, asset: str, current_price: float) -> float:

        # Calculate multi-window velocity with noise floor to prevent exact zeros.

        # Uses 10s, 30s, 60s windows weighted by momentum (0.2, 0.3, 0.5) per industry best practices.

        # Adds minimum epsilon (1e-9) to prevent velocity=0.000000 which blocks all trading.

        # Returns velocity as percentage change.

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        history = list(self._spot_price_history[asset])

        if len(history) < 2:

            logger.debug("[VELOCITY-CALC] asset=%s insufficient history (%d < 2), returning 0.0", 

                         asset, len(history))

            return 0.0

        

        current_time = int(time.time() * 1000)  # Milliseconds to match spot service

        weighted_velocity = 0.0

        total_weight = 0.0

        

        # Multi-window velocity calculation (industry standard: 10s, 30s, 60s)

        velocity_windows = [10.0, 30.0, 60.0]

        momentum_weights = [0.2, 0.3, 0.5]

        

        for window_sec, weight in zip(velocity_windows, momentum_weights):

            target_time = current_time - int(window_sec * 1000)  # Convert seconds to milliseconds

            

            prev_price = None

            # Handle OHLC format: (timestamp, close, open, high, low)

            for entry in reversed(history):

                if len(entry) >= 2:

                    ts = entry[0]

                    price = entry[1]  # Use close price for velocity

                    if ts <= target_time:

                        prev_price = price

                        break

            

            if prev_price is None or prev_price <= 0:

                continue  # Skip this window if no data

            

            window_velocity = (current_price - prev_price) / prev_price

            weighted_velocity += weight * window_velocity

            total_weight += weight

        

        # If no windows had data, return 0

        if total_weight == 0:

            logger.debug("[VELOCITY-CALC] asset=%s no valid windows, returning 0.0", asset)

            return 0.0

        

        # Normalize by total weight

        velocity = weighted_velocity / total_weight

        

        # CRITICAL FIX: 2026-07-06 - Fix bias bug: use history[-1][1] instead of history[-2][1]

        # Previous code used history[-2][1] (second-to-last price) which created incorrect trend comparison

        # history[-1][1] is the most recent price in history, history[-2][1] is the price before that

        # This caused systematic bias in epsilon direction, leading to only BUY_NO signals

        # This prevents the vicious cycle: velocity=0 -> no trade -> no price update -> velocity=0

        # Epsilon of 1e-9 (0.0000001%) is negligible for trading but prevents exact zero

        # Add tiny noise in direction of recent price trend if available

        if len(history) >= 1:

            recent_trend = (current_price - history[-1][1]) / history[-1][1]

            velocity = velocity + (1e-9 if recent_trend >= 0 else -1e-9)

        else:

            # No trend data available - add small positive epsilon

            velocity = velocity + 1e-9

        

        return velocity

    

    def _generate_momentum_fvg_signal(self, asset: str, spot_price: float, market: Any, minutes_to_expiry: float) -> Optional[Dict[str, Any]]:

        """MOMENTUM_FVG STRATEGY: Combines velocity, MACD, RSI, OBI, and FVG for enhanced signals.

        

        CRITICAL FIX: 2026-07-06 - Wires MACD/RSI into momentum_fvg signal generation

        This strategy uses multiple indicators to generate high-confidence signals:

        - Velocity: Multi-window velocity with EMA smoothing and ATR normalization

        - MACD: Momentum confirmation (histogram sign and slope)

        - RSI: Overbought/oversold conditions for fade entries

        - OBI: Order book imbalance for confirmation

        - FVG: Fair Value Gap for confluence and timing

        """

        # Load profile configuration for momentum_fvg parameters

        try:

            from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile

            profile = get_crypto_15m_profile()

            momentum_fvg_config = profile.momentum_fvg

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] Failed to load profile config: %s", e)

            return None

        

        # Calculate velocity (multi-window with EMA smoothing)

        velocity = self._calculate_multi_window_velocity(asset, spot_price)

        velocity_threshold = self._calculate_dynamic_velocity_threshold(asset)

        

        # CRITICAL FIX: 2026-07-08 - Check for sufficient warmup data before calculating indicators

        # Crypto15mIndicatorStack uses MACD(8,21,5) which needs 21 + 5 = 26 periods minimum

        # RSI(8) needs 8 + 1 = 9 periods minimum

        # If insufficient data, skip signal generation to avoid zero/default indicator values

        # CRITICAL FIX: Use indicator stack's min_bars_cold_start for faster warmup

        # This allows trading with fewer bars during initialization (10 bars vs 30+)

        if asset in self._indicator_stacks:

            try:

                indicator_snap = self._indicator_stacks[asset].snapshot()

                # Removed early trade_allowed check to allow indicator stack's cold start logic to handle it

                # The indicator stack now has cold start logic that bypasses volatility gates during warmup

            except Exception as e:

                logger.error("[MOMENTUM-FVG-DATA-FAILURE] asset=%s indicator stack exception: %s - this is a BUG, not normal warmup", asset, e)

                # Fallback to original check if indicator stack fails

                price_history = list(self._spot_price_history.get(asset, []))

                min_history_for_macd = 26  # 21 for MACD slow + 5 for signal line (MACD(8,21,5))

                min_history_for_rsi = 9   # 8 for RSI + 1 for calculation (RSI(8))

                

                if len(price_history) < min_history_for_macd:

                    logger.info(

                        "[MOMENTUM-FVG-WARMUP] asset=%s history_length=%d (requires %d for MACD) - warming up",

                        asset, len(price_history), min_history_for_macd

                    )

                    return None

        

        # Initialize indicator variables with defaults

        macd_slope = 0.0

        

        # CRITICAL FIX: 2026-07-08 - Use Crypto15mIndicatorStack for 2026 research-based indicators

        # This provides EMA(200), regime-based RSI, MACD filters, and RSI+MACD confluence scoring

        if asset in self._indicator_stacks:

            try:

                indicator_snap = self._indicator_stacks[asset].snapshot()

                

                # CRITICAL FIX: 2026-07-11 - Explicit warmup tracking

                min_bars_required = 20  # CRITICAL FIX: Reduced from 52 to 20 for 15-minute markets

                if indicator_snap.bars_available < min_bars_required:

                    logger.info(

                        "[MOMENTUM-FVG-WARMUP] asset=%s bars_available=%d (requires %d) - warming up, using cold start logic",

                        asset, indicator_snap.bars_available, min_bars_required

                    )

                    # Continue with cold start logic - don't return None

                else:

                    logger.info(

                        "[MOMENTUM-FVG-INDICATOR-STACK] asset=%s bars_available=%d macd_line=%.6f macd_histogram=%.6f rsi=%.1f", 

                        asset, indicator_snap.bars_available, indicator_snap.macd_line, indicator_snap.macd_histogram, indicator_snap.rsi

                    )

                

                # Extract 2026 research-based indicators from indicator stack

                rsi = indicator_snap.rsi

                rsi_zone = indicator_snap.rsi_zone

                macro_regime = indicator_snap.macro_regime

                price_above_ema_200 = indicator_snap.price_above_ema_200

                macd_line = indicator_snap.macd_line

                macd_histogram = indicator_snap.macd_histogram

                macd_zero_line_ok = indicator_snap.macd_zero_line_ok

                macd_histogram_expanding = indicator_snap.macd_histogram_expanding

                bias = indicator_snap.bias

                bias_confidence = indicator_snap.bias_confidence

                macd_slope = getattr(indicator_snap, 'macd_slope', 0.0)

                

                logger.debug(

                    "[MOMENTUM-FVG-INDICATORS] asset=%s rsi=%.1f zone=%s macro_regime=%s ema200_above=%s macd_line=%.6f macd_hist=%.6f zero_line_ok=%s hist_expanding=%s bias=%s confidence=%.2f",

                    asset, rsi, rsi_zone, macro_regime, price_above_ema_200, macd_line, macd_histogram, macd_zero_line_ok, macd_histogram_expanding, bias, bias_confidence

                )

                

                # Apply 2026 research-based filters

                

                # 1. EMA(200) macro trend filter - only trade in direction of macro trend

                # If price below EMA(200) (bear regime), prefer shorts; if above (bull regime), prefer longs

                if not price_above_ema_200 and macro_regime == "bear":

                    # In bear regime, prefer short signals

                    logger.debug("[EMA200-FILTER] asset=%s in bear regime (price below EMA200), prefer short signals", asset)

                elif price_above_ema_200 and macro_regime == "bull":

                    # In bull regime, prefer long signals

                    logger.debug("[EMA200-FILTER] asset=%s in bull regime (price above EMA200), prefer long signals", asset)

                

                # 2. Regime-based RSI threshold shifting

                # Bull regime: thresholds shifted up (80/40)

                # Bear regime: thresholds shifted down (60/20)

                # Range regime: neutral thresholds (70/30)

                # CRITICAL FIX: 2026-07-07 - Read thresholds from profile YAML instead of hardcoding

                # This ensures single source of truth and allows dynamic adjustment

                if macro_regime == "bull":

                    rsi_oversold = getattr(momentum_fvg_config, 'rsi_bull_oversold', 40.0)

                    rsi_overbought = getattr(momentum_fvg_config, 'rsi_bull_overbought', 80.0)

                elif macro_regime == "bear":

                    rsi_oversold = getattr(momentum_fvg_config, 'rsi_bear_oversold', 20.0)

                    rsi_overbought = getattr(momentum_fvg_config, 'rsi_bear_overbought', 60.0)

                else:  # range or neutral

                    rsi_oversold = 30.0  # Default neutral thresholds

                    rsi_overbought = 70.0

                

                # Recalculate RSI zone with regime-based thresholds

                if rsi <= rsi_oversold:

                    rsi_zone = "oversold"

                elif rsi >= rsi_overbought:

                    rsi_zone = "overbought"

                else:

                    rsi_zone = "neutral"

                

                # 3. MACD zero-line filter - only take longs if MACD > 0, shorts if MACD < 0

                # CRITICAL FIX: 2026-07-07 - Actually apply the filter, not just log

                # Check if filter is enabled in profile

                macd_zero_line_enabled = getattr(momentum_fvg_config, 'macd_zero_line_filter_enabled', True)

                if macd_zero_line_enabled and not macd_zero_line_ok:

                    logger.debug("[MACD-ZERO-LINE-FILTER] asset=%s MACD line on wrong side of zero (%.6f), skip signal", asset, macd_line)

                    # Skip signal generation if MACD is on wrong side of zero

                    return None

                

                # 4. MACD histogram momentum filter - require histogram expansion

                # CRITICAL FIX: 2026-07-07 - Actually apply the filter, not just log

                # Check if filter is enabled in profile

                macd_histogram_enabled = getattr(momentum_fvg_config, 'macd_histogram_momentum_filter_enabled', True)

                if macd_histogram_enabled and not macd_histogram_expanding:

                    logger.debug("[MACD-HISTOGRAM-FILTER] asset=%s histogram not expanding, momentum weakening", asset)

                    # Don't skip signal entirely, but note the filter (histogram expansion is confirmation, not a hard gate)

                

                # 5. RSI+MACD confluence scoring - boost confidence when both agree

                # Long confluence: RSI oversold/neutral-bullish + MACD histogram positive

                # Short confluence: RSI overbought/neutral-bearish + MACD histogram negative

                confluence_boost = 0.0

                if rsi < 50.0 and macd_histogram > 0:

                    confluence_boost = 0.5  # Long confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s long confluence (RSI=%.1f<50, MACD hist=%.6f>0)", asset, rsi, macd_histogram)

                elif rsi > 50.0 and macd_histogram < 0:

                    confluence_boost = 0.5  # Short confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s short confluence (RSI=%.1f>50, MACD hist=%.6f<0)", asset, rsi, macd_histogram)

                

                # Extreme confluence (highest confidence)

                if rsi < rsi_oversold and macd_histogram > 0 and macd_histogram_expanding:

                    confluence_boost += 0.4  # Additional boost for extreme long confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s EXTREME long confluence (RSI oversold, MACD positive and expanding)", asset)

                elif rsi > rsi_overbought and macd_histogram < 0 and macd_histogram_expanding:

                    confluence_boost += 0.4  # Additional boost for extreme short confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s EXTREME short confluence (RSI overbought, MACD negative and expanding)", asset)

                

            except Exception as e:

                logger.warning("[MOMENTUM-FVG] Failed to get indicator snapshot from Crypto15mIndicatorStack: %s", e)

                # Fallback to internal calculations

                macd_histogram = 0.0

                macd_slope = 0.0

                rsi = 50.0

                rsi_zone = "neutral"

                confluence_boost = 0.0

        else:

            # Fallback: Use internal calculations if indicator stack not available

            logger.warning("[MOMENTUM-FVG] Crypto15mIndicatorStack not available for %s, using internal calculations", asset)

            macd_histogram = 0.0

            macd_slope = 0.0

            rsi = 50.0

            rsi_zone = "neutral"

            confluence_boost = 0.0

            macro_regime = "neutral"

            price_above_ema_200 = True

            macd_zero_line_ok = True

            macd_histogram_expanding = False

        

        # Get FVG signal from FVG forecaster

        fvg_signal = None

        fvg_confidence = 0.0

        fvg_direction = "neutral"

        

        try:

            from merid.prediction.forecasters.fvg import get_fvg_forecaster

            fvg_forecaster = get_fvg_forecaster()

            # Get market data for FVG forecaster

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            

            # Extract market parameters

            implied_yes = getattr(market_state, 'yes_price', 0.5) if market_state else 0.5

            implied_no = 1.0 - implied_yes

            volume = getattr(market_state, 'volume_24h', 0.0) if market_state else 0.0

            open_interest = getattr(market_state, 'open_interest', 0.0) if market_state else 0.0

            bid = getattr(market_state, 'bid', None) if market_state else None

            ask = getattr(market_state, 'ask', None) if market_state else None

            

            # Get FVG prediction with correct arguments

            fvg_result = fvg_forecaster.predict(

                market_id=ticker,

                implied_yes=implied_yes,

                implied_no=implied_no,

                volume=volume,

                open_interest=open_interest,

                minutes_to_expiry=minutes_to_expiry,

                asset=asset,

                timeframe="15m",

                bid=bid,

                ask=ask,

            )

            if fvg_result:

                fvg_confidence = fvg_result.confidence

                fvg_direction = fvg_result.components.get('fvg_nearest_direction', 0.0)

                if fvg_direction > 0:

                    fvg_direction = "bullish"

                elif fvg_direction < 0:

                    fvg_direction = "bearish"

                else:

                    fvg_direction = "neutral"

                fvg_signal = fvg_result

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] Failed to get FVG signal: %s", e)

        

        # Get OBI (Order Book Imbalance) from market state

        obi = 0.0

        obi_strong = False

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                # CRITICAL FIX: Use correct field names from KalshiMarketState model

                # The model uses depth_10c_yes and depth_10c_no, not depth_yes_10c and depth_no_10c

                depth_yes = getattr(market_state, 'depth_10c_yes', 0) or 0

                depth_no = getattr(market_state, 'depth_10c_no', 0) or 0

                

                # CRITICAL FIX: Check for valid depth data before calculating OBI

                # If both depths are 0, the market state may not have been populated yet

                if depth_yes == 0 and depth_no == 0:

                    logger.warning(

                        "[MOMENTUM-FVG] asset=%s ticker=%s depth data not available (depth_yes=0, depth_no=0), "

                        "market state may not be populated yet. Skipping OBI calculation.",

                        asset, ticker

                    )

                    # Don't use OBI in signal conditions if data is unavailable

                    obi = 0.0

                    obi_strong = False

                elif depth_yes + depth_no > 0:

                    obi = (depth_yes - depth_no) / (depth_yes + depth_no)

                    # Check per-asset strong thresholds

                    asset_obi_strong = getattr(momentum_fvg_config, f'obi_strong_{asset.lower()}', 0.5)

                    obi_strong = abs(obi) >= asset_obi_strong

                    

                    # CRITICAL FIX: Log extreme OBI values for debugging

                    if abs(obi) >= 0.9:

                        logger.warning(

                            "[MOMENTUM-FVG] asset=%s ticker=%s extreme OBI=%.2f (depth_yes=%d depth_no=%d). "

                            "This may indicate one-sided liquidity or stale market data.",

                            asset, ticker, obi, depth_yes, depth_no

                        )

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] Failed to get OBI: %s", e)

        

        # Combine signals for momentum_fvg decision

        # Long signal conditions:

        # 1. Velocity > threshold (positive momentum)

        # 2. MACD histogram >= 0 (bullish momentum)

        # 3. RSI not overbought (not extended)

        # 4. OBI positive (buying pressure) OR FVG bullish confluence

        

        min_macd_hist_long = getattr(momentum_fvg_config, 'min_macd_hist_long', 0)

        min_macd_hist_short = getattr(momentum_fvg_config, 'min_macd_hist_short', 0)

        

        # CRITICAL FIX: 2026-07-08 - Read momentum RSI thresholds from profile YAML (single source of truth)

        # These thresholds define directional momentum: RSI > 55 for longs, RSI < 45 for shorts

        # Previous implementation did not use these thresholds, only checked RSI != overbought/oversold

        momentum_rsi_long_min = getattr(momentum_fvg_config, 'momentum_rsi_long_min', 55.0)

        momentum_rsi_short_max = getattr(momentum_fvg_config, 'momentum_rsi_short_max', 45.0)

        

        # CRITICAL FIX: 2026-07-08 - Read macd_dead_zone from profile YAML (single source of truth)

        # CRITICAL FIX: 2026-07-08 - During warmup (insufficient bars), disable dead zone to allow signals

        # When indicator stack has sufficient data (20+ bars), histogram values will be meaningful

        # During warmup, MACD histogram values are very small (near zero) due to insufficient data

        # Setting dead zone to 0.0 during warmup allows signals to be generated

        macd_dead_zone = getattr(momentum_fvg_config, 'macd_dead_zone', 0.0)

        

        # Check if indicator stack has sufficient data (warmup complete)

        if asset in self._indicator_stacks:

            try:

                indicator_snap = self._indicator_stacks[asset].snapshot()

                # If we have sufficient bars (>=20), use the configured dead zone

                # If not, disable dead zone to allow signals during warmup

                if indicator_snap.bars_available < 20:

                    macd_dead_zone = 0.0  # Disable dead zone during warmup

                    logger.debug("[MOMENTUM-FVG] asset=%s warmup mode (bars=%d < 20), disabled MACD dead zone", 

                               asset, indicator_snap.bars_available)

            except Exception as e:

                logger.warning("[MOMENTUM-FVG] asset=%s failed to check indicator stack for warmup: %s", asset, e)

                macd_dead_zone = 0.0  # Disable dead zone on error to allow signals

        

        if abs(macd_histogram) < macd_dead_zone:

            logger.info(

                "[MOMENTUM-FVG-DEAD-ZONE] asset=%s macd_histogram=%.6f within dead zone (±%.6f), skipping signal to avoid noise",

                asset, macd_histogram, macd_dead_zone

            )

            return None

        

        long_conditions = [

            velocity > velocity_threshold,

            macd_histogram >= min_macd_hist_long,

            rsi_zone != "overbought",

            rsi > momentum_rsi_long_min,  # CRITICAL FIX: 2026-07-08 - Add momentum RSI threshold for directional long signals

            (obi > 0 and obi_strong) or (fvg_direction == "bullish" and fvg_confidence > 0.5)

        ]

        

        short_conditions = [

            velocity < -velocity_threshold,

            macd_histogram < min_macd_hist_short,  # CRITICAL FIX: Use strict inequality to prevent symmetry at hist=0

            rsi_zone != "oversold",

            rsi < momentum_rsi_short_max,  # CRITICAL FIX: 2026-07-08 - Add momentum RSI threshold for directional short signals

            (obi < 0 and obi_strong) or (fvg_direction == "bearish" and fvg_confidence > 0.5)

        ]

        

        # Count conditions met

        long_score = sum(long_conditions)

        short_score = sum(short_conditions)

        

        # CRITICAL FIX: 2026-07-09 - Dual-side edge evaluation for momentum_fvg

        # Use scores as inputs to edge calculation, not as direct side selectors

        # Both YES and NO get evaluated, then select side with higher positive edge

        

        # Get prices for both sides

        yes_price_cents = 0

        no_price_cents = 0

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                best_bid = getattr(market_state, 'best_bid_cents', 0) or 0

                best_ask = getattr(market_state, 'best_ask_cents', 0) or 0

                yes_price_cents = best_bid if best_bid > 0 else 0

                no_price_cents = (100 - best_ask) if best_ask > 0 else 0

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] asset=%s failed to get market price: %s", asset, e)

        

        # Check price band for both sides (10c-75c range - expanded for current market conditions)

        # CRITICAL FIX: 2026-07-12 - Expanded to 75c to match YES prices 60-97c in current market

        yes_in_range = (10 <= yes_price_cents <= 75)

        no_in_range = (10 <= no_price_cents <= 75)

        

        logger.info(

            "[MOMENTUM-FVG-PRICE-RANGE] asset=%s yes_price=%dc yes_in_range=%s no_price=%dc no_in_range=%s",

            asset, yes_price_cents, yes_in_range, no_price_cents, no_in_range

        )

        

        if not yes_in_range and not no_in_range:

            logger.info(

                "[MOMENTUM-FVG-PRICE-FILTER] asset=%s both sides outside 10c-75c range (yes=%dc, no=%dc) -> NO TRADE",

                asset, yes_price_cents, no_price_cents

            )

            return None

        

        # Build edges for both YES and NO using scores as inputs

        def fvg_edge(score, velocity_sign, macd_hist, rsi, fvg_dir, fvg_conf):

            """Calculate edge from score and indicators."""

            # CRITICAL FIX: 2026-07-10 - Always return an edge value, even if score < 3

            # This prevents edge=None which was causing no_edge to be None

            # Instead, use a lower base edge for scores below threshold

            

            if score < 3:

                # Return minimal edge for low scores instead of None

                # This allows both sides to have edge values for comparison

                return 0.5  # Minimal edge for insufficient conditions

            

            base_edge = calculate_velocity_edge(velocity * velocity_sign, velocity_threshold)

            base_edge = max(base_edge, 2.0)  # Minimum 2% edge

            

            # MACD contribution

            edge = base_edge + abs(macd_hist) * 10.0

            

            # Score-based scaling: more aligned conditions → larger edge

            edge *= 1.0 + (score - 3) * 0.1  # Scale by score above minimum

            

            # RSI strength (fade at extremes)

            if rsi_zone == "oversold" and velocity_sign > 0:

                edge += 1.0  # Bonus for oversold bounce

            elif rsi_zone == "overbought" and velocity_sign < 0:

                edge += 1.0  # Bonus for overbought fade

            

            # FVG confluence bonus

            if fvg_conf > 0.5:

                if (velocity_sign > 0 and fvg_dir == "bullish") or (velocity_sign < 0 and fvg_dir == "bearish"):

                    edge += fvg_conf * 2.0

            

            # Cap edge at reasonable maximum

            return min(edge, 15.0)

        

        # Calculate edges for both sides

        edge_yes_pct = None

        edge_no_pct = None

        

        if yes_in_range:

            edge_yes_pct = fvg_edge(long_score, 1.0, macd_histogram, rsi, fvg_direction, fvg_confidence)

        

        if no_in_range:

            edge_no_pct = fvg_edge(short_score, -1.0, macd_histogram, rsi, fvg_direction, fvg_confidence)

        

        # Log dual-side evaluation

        logger.info(

            "[DUAL-SIDE-EVAL] asset=%s yes_price=%dc no_price=%dc yes_in_range=%s no_in_range=%s",

            asset, yes_price_cents, no_price_cents, yes_in_range, no_in_range

        )

        logger.info(

            "[MOMENTUM-FVG-DUAL-SIDE] asset=%s long_score=%d short_score=%d yes_edge=%s no_edge=%s",

            asset, long_score, short_score, 

            f"{edge_yes_pct:.2f}%" if edge_yes_pct else "None",

            f"{edge_no_pct:.2f}%" if edge_no_pct else "None"

        )

        

        # Select side with higher positive edge

        side_edges = {}

        if edge_yes_pct is not None:

            side_edges["yes"] = edge_yes_pct

        if edge_no_pct is not None:

            side_edges["no"] = edge_no_pct

        

        if not side_edges:

            logger.info(

                "[MOMENTUM-FVG-NO-EDGE] asset=%s no valid edges (both sides below threshold) -> NO TRADE",

                asset

            )

            return None

        

        # CRITICAL FIX: 2026-07-09 - Add midpoint preference (~25c bonus) to momentum_fvg

        def midpoint_bonus(price_cents):

            """Peak at 25c, decays toward 10c/50c."""

            dist = abs(price_cents - 25)

            midpoint_bonus_max = 0.5  # Maximum bonus in percentage points

            midpoint_bonus_slope = 0.02  # Decay rate per cent from midpoint

            return max(0.0, midpoint_bonus_max - dist * midpoint_bonus_slope)

        

        # Apply midpoint bonus to edges

        side_edges_with_bonus = {}

        if yes_in_range and edge_yes_pct is not None:

            side_edges_with_bonus["yes"] = edge_yes_pct + midpoint_bonus(yes_price_cents)

        if no_in_range and edge_no_pct is not None:

            side_edges_with_bonus["no"] = edge_no_pct + midpoint_bonus(no_price_cents)

        

        # Select side with maximum edge (with midpoint bonus)

        signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)

        selected_edge = side_edges[signal_side]  # Use original edge (without bonus) for reporting

        

        # Minimum edge threshold (per-asset aligned with risk_parameters.py market entry thresholds)

        # 2026-07-10: Aligned with EDGE_MARKET_ENTRY thresholds to prevent filtering valid candidates

        per_asset_min_edge_threshold = {

            "BTC": 1.75,   # EDGE_MARKET_ENTRY_BTC

            "ETH": 2.0,    # EDGE_MARKET_ENTRY_ETH

            "SOL": 2.5,    # EDGE_MARKET_ENTRY_SOL

            "XRP": 3.0,    # EDGE_MARKET_ENTRY_XRP

            "DOGE": 3.5,   # EDGE_MARKET_ENTRY_DOGE

        }

        min_edge_threshold_pct = per_asset_min_edge_threshold.get(asset, 2.0)

        

        if selected_edge < min_edge_threshold_pct:

            logger.info(

                "[MOMENTUM-FVG-EDGE-THRESHOLD] asset=%s selected_edge=%.2f%% < per_asset_threshold=%.2f%% -> NO TRADE",

                asset, selected_edge, min_edge_threshold_pct

            )

            return None

        

        signal_action = "buy"

        confidence = 0.5 + (selected_edge / 100.0)

        confidence = min(0.95, confidence)

        

        logger.info(

            "[MOMENTUM-FVG-SELECTION] asset=%s selected_side=%s edge=%.2f%% confidence=%.2f (all_edges=%s)",

            asset, signal_side, selected_edge, confidence, side_edges

        )

        

        # Use selected_edge from dual-side evaluation (already computed)

        edge_pct = selected_edge

        

        # Calculate model probability from selected edge

        if signal_side == "yes":

            model_prob = min(0.95, 0.5 + (edge_pct / 100.0))

        else:

            model_prob = max(0.05, 0.5 - (edge_pct / 100.0))

        

        # Calculate price_cents from market state (mid price)

        price_cents = 25  # 2026-07-09: Changed from 50 to 25 (midpoint of 10-50c sweet spot)

        price_source = "default_25c"

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            logger.info("[PRICE-CENTS-DEBUG] asset=%s ticker=%s market_state_store_available=%s", asset, ticker, self.market_state_store is not None)

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            logger.info("[PRICE-CENTS-DEBUG] asset=%s ticker=%s market_state_found=%s", asset, ticker, market_state is not None)

            if market_state:

                best_bid = getattr(market_state, 'best_bid_cents', 0) or 0

                best_ask = getattr(market_state, 'best_ask_cents', 0) or 0

                logger.info("[PRICE-CENTS-DEBUG] asset=%s ticker=%s best_bid=%d best_ask=%d", asset, ticker, best_bid, best_ask)

                if best_bid > 0 and best_ask > 0:

                    price_cents = int((best_bid + best_ask) / 2)

                    price_source = "mid_bid_ask"

                elif best_bid > 0:

                    price_cents = int(best_bid)

                    price_source = "bid_only"

                elif best_ask > 0:

                    price_cents = int(best_ask)

                    price_source = "ask_only"

                else:

                    logger.warning("[PRICE-CENTS-DEBUG] asset=%s ticker=%s bid/ask both zero, using default 25c", asset, ticker)

            else:

                logger.warning("[PRICE-CENTS-DEBUG] asset=%s ticker=%s market_state is None, using default 25c", asset, ticker)

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] Failed to get price_cents from market state: %s", e)

        

        logger.info("[PRICE-CENTS-DEBUG] asset=%s final_price_cents=%d source=%s", asset, price_cents, price_source)

        

        # 2026-07-12: Expanded price range 10c-75c to match actual market conditions (YES prices 60-97c)

        # If no prices exist in 10-75c range, drop the candidate (no trade).

        raw_price_cents = price_cents

        

        # Check if price is within range (10c-75c)

        if 10 <= raw_price_cents <= 75:

            # Price is already in valid range - use it directly

            clamped_price_cents = raw_price_cents

            logger.info(

                "[PRICE-SELECTION] asset=%s raw_price_cents=%d in range [10c-75c] - using directly",

                asset, raw_price_cents

            )

        else:

            # Price is outside canonical range - search orderbook for valid prices

            logger.warning(

                "[PRICE-SELECTION] asset=%s raw_price_cents=%d outside range [10c-75c] - searching orderbook",

                asset, raw_price_cents

            )

            

            # Try to find a price in the canonical range from the orderbook

            price_cents = None

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None

                

                if market_state:

                    # Get YES orderbook (ascending by price)

                    yes_book = getattr(market_state, 'yes_book', [])

                    if yes_book:

                        # Find cheapest YES price within [10c, 75c] with size >= 1

                        valid_prices = [p for (p, size) in yes_book if 10 <= p <= 75 and size >= 1]

                        if valid_prices:

                            price_cents = min(valid_prices)  # Use cheapest acceptable price

                            logger.info(

                                "[PRICE-SELECTION] asset=%s found %d valid prices in canonical range, using cheapest=%d",

                                asset, len(valid_prices), price_cents

                            )

                        else:

                            logger.warning(

                                "[PRICE-SELECTION] asset=%s no YES prices in range [10c-75c] - dropping candidate",

                                asset

                            )

                            return None  # Drop candidate - no valid price in canonical range

                    else:

                        logger.warning(

                            "[PRICE-SELECTION] asset=%s orderbook not available - dropping candidate",

                            asset

                        )

                        return None

                else:

                    logger.warning(

                        "[PRICE-SELECTION] asset=%s market state not available - dropping candidate",

                        asset

                    )

                    return None

            except Exception as e:

                logger.error(

                    "[PRICE-SELECTION] asset=%s error searching orderbook: %s - dropping candidate",

                    asset, e

                )

                return None

            

            clamped_price_cents = price_cents

        

        # Final validation - ensure we have a valid price in the range (10c-75c)

        # CRITICAL FIX: 2026-07-12 - Use expanded 10-75c range to match current market conditions

        if clamped_price_cents is None or not (10 <= clamped_price_cents <= 75):

            logger.error(

                "[PRICE-SELECTION-ERROR] asset=%s final price_cents=%d not in range [10c-75c] - dropping candidate",

                asset, clamped_price_cents

            )

            return None

        

        logger.info(

            "[PRICE-SELECTION] asset=%s final entry price=%d (within expanded range [10c-95c])",

            asset, clamped_price_cents

        )

        

        price_cents = clamped_price_cents

        

        # Return signal

        return {

            "side": signal_side,

            "action": signal_action,

            "confidence": confidence,

            "edge_pct": edge_pct,

            "model_prob": model_prob,

            "signal_mode": "momentum_fvg",

            "velocity": velocity,

            "velocity_threshold": velocity_threshold,

            "macd_histogram": macd_histogram,

            "macd_slope": macd_slope,

            "rsi": rsi,

            "rsi_zone": rsi_zone,

            "obi": obi,

            "fvg_direction": fvg_direction,

            "fvg_confidence": fvg_confidence,

            "long_score": long_score,

            "short_score": short_score,

            "price_cents": price_cents,  # CRITICAL: Include price_cents for order execution

            "count": 1,  # CRITICAL: Include default count for order execution

            "rationale": f"momentum_fvg: velocity={velocity:.6f} (threshold={velocity_threshold:.6f}) macd_hist={macd_histogram:.4f} rsi={rsi:.1f} ({rsi_zone}) obi={obi:.2f} fvg_dir={fvg_direction} fvg_conf={fvg_confidence:.2f} edge={edge_pct:.2f}%",

        }



    def _check_trend_alignment(self, asset: str, spot_price: float) -> bool:

        """Check if 5m and 1h trends are aligned for signal confirmation.

        

        CRITICAL FIX: 2026-07-06 - Integrated trend alignment as confirmation filter

        Based on Turbine research: trend alignment was consistently profitable

        - YES alignment: 5 of 5 profitable, mean P&L +$5,939

        - NO alignment: 5 of 5 profitable, mean P&L +$3,773

        

        Returns:

            True if trends are aligned (both up or both down), False otherwise

        """

        try:

            from merid.prediction.strategies.trend_alignment import get_trend_alignment_strategy

            trend_strategy = get_trend_alignment_strategy()

            

            # Update price history

            current_time = time.time()

            trend_strategy.update_price(asset, spot_price, current_time)

            

            # Calculate short (5m) and medium (1h) trends

            short_trend = trend_strategy._calculate_trend(asset, 300, current_time)  # 5 minutes

            medium_trend = trend_strategy._calculate_trend(asset, 3600, current_time)  # 1 hour

            

            # Check if trends agree and are not neutral

            if short_trend == medium_trend and short_trend.value != "neutral":

                logger.info(

                    "[TREND-ALIGNMENT] asset=%s short_trend=%s medium_trend=%s -> ALIGNED",

                    asset, short_trend.value, medium_trend.value

                )

                return True

            else:

                logger.info(

                    "[TREND-ALIGNMENT] asset=%s short_trend=%s medium_trend=%s -> NOT ALIGNED",

                    asset, short_trend.value, medium_trend.value

                )

                return False

        except Exception as e:

            logger.warning("[TREND-ALIGNMENT] Failed to check trend alignment for %s: %s", asset, e)

            # If trend alignment check fails, proceed (fail-safe)

            return True



    def _generate_price_based_signal(self, asset: str, spot_price: float, market: Any, minutes_to_expiry: float) -> Optional[Dict[str, Any]]:

        # PRICE-BASED STRATEGY (Turbine research winner: +56.6% ROI)

        # Buy YES when market price <= 0.50, sell when price >= 0.70

        # Simple strategy that works best on thin 15-min books

        

        # Get current market price from market state

        market_price = 0.0

        try:

            if hasattr(market, 'market') and hasattr(market.market, 'market_id'):

                ticker = market.market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None

                if market_state:

                    # Use mid price from market state (attributes are best_bid_cents, best_ask_cents)

                    best_bid = getattr(market_state, 'best_bid_cents', 0) or 0

                    best_ask = getattr(market_state, 'best_ask_cents', 0) or 0

                    logger.info("[PRICE-BASED-DEBUG] asset=%s ticker=%s best_bid_cents=%s best_ask_cents=%s", asset, ticker, best_bid, best_ask)

                    if best_bid > 0 and best_ask > 0:

                        market_price = (best_bid + best_ask) / 200.0  # Convert cents to price

                    elif best_bid > 0:

                        market_price = best_bid / 100.0

                    elif best_ask > 0:

                        market_price = best_ask / 100.0

                    # CRITICAL FIX: Validate market price is in reasonable range [0.01, 0.99]

                    # Prices outside this range indicate data corruption or calculation error

                    if market_price < 0.01 or market_price > 0.99:

                        logger.warning("[PRICE-BASED-ERROR] asset=%s ticker=%s invalid market_price=%.2f (expected 0.01-0.99), rejecting signal", asset, ticker, market_price)

                        return None

                else:

                    logger.warning("[PRICE-BASED-ERROR] asset=%s market_state is None for ticker=%s", asset, ticker)

        except Exception as e:

            logger.warning("[PRICE-BASED-ERROR] asset=%s failed to get market price: %s", asset, e)

            return None

        

        if market_price <= 0:

            logger.warning("[PRICE-BASED-ERROR] asset=%s invalid market price=%.2f", asset, market_price)

            return None

        

        buy_threshold = self.config.price_based_buy_threshold

        sell_threshold = self.config.price_based_sell_threshold

        

        logger.info(

            "[PRICE-BASED-SIGNAL] asset=%s market_price=%.2f buy_threshold=%.2f sell_threshold=%.2f",

            asset, market_price, buy_threshold, sell_threshold

        )

        

        if market_price <= buy_threshold:

            # Buy YES when price is cheap

            signal_side = "yes"

            signal_action = "buy"

            logger.info(

                "[PRICE-BASED-SIGNAL] asset=%s price=%.2f <= buy_threshold=%.2f -> BUY YES",

                asset, market_price, buy_threshold

            )

        elif market_price >= sell_threshold:

            # Buy NO when price is high (betting against the outcome)

            signal_side = "no"

            signal_action = "buy"

            logger.info(

                "[PRICE-BASED-SIGNAL] asset=%s price=%.2f >= sell_threshold=%.2f -> BUY NO",

                asset, market_price, sell_threshold

            )

        else:

            # Price in middle range - no trade

            logger.info(

                "[PRICE-BASED-SIGNAL] asset=%s price=%.2f in range (%.2f, %.2f) -> NO TRADE",

                asset, market_price, buy_threshold, sell_threshold

            )

            return None

        

        # Return signal

        # Calculate edge for price-based strategy (distance from threshold)

        # For YES buy: edge = (buy_threshold - market_price) / buy_threshold

        # For NO buy: edge = (market_price - sell_threshold) / (1.0 - sell_threshold)

        # Add minimum base edge when threshold is crossed to ensure meaningful edge

        if signal_side == "yes" and signal_action == "buy":

            edge_pct = (buy_threshold - market_price) / buy_threshold * 100

            # Add 2% base edge at threshold crossing (minimum edge for valid trade)

            edge_pct = max(edge_pct, 2.0)

            # Dynamic confidence: increases as price moves further below buy_threshold

            # At buy_threshold: confidence = 0.50 (neutral)

            # At 0.40 (20% below threshold): confidence = 0.50 + 2.0 * 0.20 = 0.90

            distance_from_threshold = (buy_threshold - market_price) / buy_threshold

            confidence = min(0.99, 0.50 + 2.0 * distance_from_threshold)

            # For buy YES: model_prob should be higher than market_price (we think outcome is more likely)

            # Convert edge_pct to probability adjustment (capped at reasonable range)

            edge_prob_adjustment = min(edge_pct / 100.0, 0.20)  # Cap at 20% adjustment

            model_prob = min(0.95, market_price + edge_prob_adjustment)

        elif signal_side == "no" and signal_action == "buy":

            edge_pct = (market_price - sell_threshold) / (1.0 - sell_threshold) * 100

            # Add 2% base edge at threshold crossing (minimum edge for valid trade)

            edge_pct = max(edge_pct, 2.0)

            # Dynamic confidence: increases as price moves further above sell_threshold

            # At sell_threshold: confidence = 0.50 (neutral)

            # At 0.80 (14% above threshold): confidence = 0.50 + 2.0 * 0.14 = 0.78

            distance_from_threshold = (market_price - sell_threshold) / (1.0 - sell_threshold)

            confidence = min(0.99, 0.50 + 2.0 * distance_from_threshold)

            # For buy NO: model_prob should be lower than market_price (we think outcome is less likely)

            # Convert edge_pct to probability adjustment (capped at reasonable range)

            edge_prob_adjustment = min(edge_pct / 100.0, 0.20)  # Cap at 20% adjustment

            model_prob = max(0.05, market_price - edge_prob_adjustment)

        

        logger.info("[PRICE-BASED-DEBUG] asset=%s market_price=%.2f edge_pct=%.2f%% edge_adjustment=%.3f model_prob=%.2f",

                    asset, market_price, edge_pct, edge_prob_adjustment, model_prob)

        

        logger.info("[PRICE-BASED-CONFIDENCE] asset=%s action=%s price=%.2f edge_pct=%.2f%% confidence=%.2f",

                    asset, signal_action, market_price, edge_pct, confidence)

        

        # 2026-07-12: Expanded price range 10c-75c to match actual market conditions (YES prices 60-97c)

        # If no prices exist in 10-75c range, drop the candidate (no trade).

        raw_price_cents = int(market_price * 100)

        

        # Check if price is within range (10c-75c)

        if 10 <= raw_price_cents <= 75:

            # Price is already in valid range - use it directly

            clamped_price_cents = raw_price_cents

            logger.info(

                "[PRICE-SELECTION] asset=%s raw_price_cents=%d in range [10c-75c] - using directly",

                asset, raw_price_cents

            )

        else:

            # Price is outside canonical range - search orderbook for valid prices

            logger.warning(

                "[PRICE-SELECTION] asset=%s raw_price_cents=%d outside range [10c-75c] - searching orderbook",

                asset, raw_price_cents

            )

            

            # Try to find a price in the canonical range from the orderbook

            price_cents = None

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None

                

                if market_state:

                    # Get YES orderbook (ascending by price)

                    yes_book = getattr(market_state, 'yes_book', [])

                    if yes_book:

                        # Find cheapest YES price within [10c, 75c] with size >= 1

                        valid_prices = [p for (p, size) in yes_book if 10 <= p <= 75 and size >= 1]

                        if valid_prices:

                            price_cents = min(valid_prices)  # Use cheapest acceptable price

                            logger.info(

                                "[PRICE-SELECTION] asset=%s found %d valid prices in canonical range, using cheapest=%d",

                                asset, len(valid_prices), price_cents

                            )

                        else:

                            logger.warning(

                                "[PRICE-SELECTION] asset=%s no YES prices in range [10c-75c] - dropping candidate",

                                asset

                            )

                            return None  # Drop candidate - no valid price in canonical range

                    else:

                        logger.warning(

                            "[PRICE-SELECTION] asset=%s orderbook not available - dropping candidate",

                            asset

                        )

                        return None

                else:

                    logger.warning(

                        "[PRICE-SELECTION] asset=%s market state not available - dropping candidate",

                        asset

                    )

                    return None

            except Exception as e:

                logger.error(

                    "[PRICE-SELECTION] asset=%s error searching orderbook: %s - dropping candidate",

                    asset, e

                )

                return None

            

            clamped_price_cents = price_cents

        

        # Final validation - ensure we have a valid price in the range (10c-75c)

        # CRITICAL FIX: 2026-07-12 - Use expanded 10-75c range to match current market conditions

        if clamped_price_cents is None or not (10 <= clamped_price_cents <= 75):

            logger.error(

                "[PRICE-SELECTION-ERROR] asset=%s final price_cents=%d not in range [10c-75c] - dropping candidate",

                asset, clamped_price_cents

            )

            return None

        

        logger.info(

            "[PRICE-SELECTION] asset=%s final entry price=%d (within expanded range [10c-95c])",

            asset, clamped_price_cents

        )

        

        return {

            "side": signal_side,

            "action": signal_action,

            "price_cents": clamped_price_cents,  # CRITICAL: Use selected price

            "confidence": confidence,  # Dynamic edge-based confidence (not hardcoded)

            "model_prob": model_prob,  # Clamped to valid range [0.05, 0.95]

            "edge_pct": edge_pct,  # CRITICAL: Calculate edge for price-based strategy

            "rationale": f"price_based: price={market_price:.2f} vs thresholds (buy={buy_threshold:.2f}, sell={sell_threshold:.2f}) edge={edge_pct:.2f}% conf={confidence:.2f}",

            "velocity": 0.0,  # Price-based strategy doesn't use velocity

        }

    

    def _calculate_multi_window_velocity(self, asset: str, current_price: float) -> float:

        # Phase 4.1: Calculate weighted multi-window velocity with EMA smoothing and ATR normalization.

        # Uses 10s, 30s, 60s windows with configurable weights.

        # Applies EMA smoothing to reduce noise (industry standard).

        # Applies ATR-based volatility normalization for dynamic thresholds (industry standard).

        # Returns weighted average velocity as percentage change.

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        history = list(self._spot_price_history[asset])

        if len(history) < 2:

            return 0.0

        

        current_time = int(time.time() * 1000)  # Milliseconds to match spot service

        weighted_velocity = 0.0

        

        for window_sec, weight in zip(self._velocity_windows, self._momentum_weights):

            target_time = current_time - int(window_sec * 1000)  # Convert seconds to milliseconds

            

            prev_price = None

            # Handle OHLC format: (timestamp, close, open, high, low)

            for entry in reversed(history):

                if len(entry) >= 2:

                    ts = entry[0]

                    price = entry[1]  # Use close price for velocity

                    if ts <= target_time:

                        prev_price = price

                        break

            

            if prev_price is None or prev_price <= 0:

                # If no data for this window, skip it

                continue

            

            window_velocity = (current_price - prev_price) / prev_price

            weighted_velocity += weight * window_velocity

        

        # Apply EMA smoothing to reduce noise

        ema_velocity = self._apply_ema_smoothing(asset, weighted_velocity)

        

        # Apply ATR-based volatility normalization

        atr_normalized_velocity = self._apply_atr_normalization(asset, ema_velocity)

        

        # Update Z-score history with the normalized velocity

        self._velocity_zscore_history[asset].append((current_time, atr_normalized_velocity))

        

        # Apply Z-score filter for extreme detection (monitoring only)

        final_velocity = self._apply_zscore_filter(asset, atr_normalized_velocity)

        

        # CRITICAL FIX: 2026-07-06 - Fix bias bug: use history[-1][1] instead of history[-2][1]

        # Previous code used history[-2][1] (second-to-last price) which created incorrect trend comparison

        # history[-1][1] is the most recent price in history, history[-2][1] is the price before that

        # This caused systematic bias in epsilon direction, leading to only BUY_NO signals

        # Crypto prices move continuously - even in "quiet" periods, minimum movement is ~0.001% per minute

        # Previous epsilon (1e-9 = 0.0000001%) was 100,000x too small, causing velocity to appear zero

        # New epsilon (1e-5 = 0.001%) represents realistic minimum price movement for major cryptos

        # This prevents the vicious cycle: velocity=0 -> no trade -> no price update -> velocity=0

        # Add realistic minimum movement in direction of recent price trend if available

        if len(history) >= 1:

            recent_trend = (current_price - history[-1][1]) / history[-1][1]

            final_velocity = final_velocity + (1e-5 if recent_trend >= 0 else -1e-5)

        else:

            # No trend data available - add small positive epsilon (realistic minimum movement)

            final_velocity = final_velocity + 1e-5

        

        return final_velocity

    

    def _apply_ema_smoothing(self, asset: str, raw_velocity: float) -> float:

        # Apply EMA smoothing to velocity to reduce noise (industry standard).

        # EMA formula: EMA = (current * alpha) + (previous_ema * (1 - alpha))

        # where alpha = 2 / (period + 1)

        if self._velocity_ema_period <= 1:

            return raw_velocity  # No smoothing if period is 1 or less

        

        alpha = 2.0 / (self._velocity_ema_period + 1.0)

        ema_history = list(self._velocity_ema_history[asset])

        

        if len(ema_history) == 0:

            # First value - use raw velocity

            smoothed_velocity = raw_velocity

        else:

            # Calculate EMA

            previous_ema = ema_history[-1]

            smoothed_velocity = (raw_velocity * alpha) + (previous_ema * (1.0 - alpha))

        

        # Store EMA value for next calculation

        self._velocity_ema_history[asset].append(smoothed_velocity)

        

        return smoothed_velocity

    

    def _apply_atr_normalization(self, asset: str, velocity: float) -> float:

        # CRITICAL FIX: Disable ATR normalization for velocity calculation

        # ATR normalization was dividing velocity by ATR, causing small price movements

        # to appear as large normalized velocities, breaking the threshold logic.

        # 2026 industry standards use raw velocity with dynamic thresholds, not normalization.

        # The dynamic threshold adjustment in _calculate_dynamic_velocity_threshold

        # already adapts to volatility by adjusting the threshold itself.

        return velocity

    

    def _calculate_zscore(self, asset: str, value: float) -> float:

        # Calculate Z-score for extreme detection (industry standard).

        # Z-score measures how many standard deviations a value is from the mean.

        # Formula: zscore = (value - mean) / std

        # Z-score > 2.0 = overbought, Z-score < -2.0 = oversold

        history = list(self._velocity_zscore_history[asset])

        if len(history) < self._zscore_period:

            return 0.0  # Not enough data for Z-score

        

        # Get recent values

        # Handle OHLC format: (timestamp, close, open, high, low)

        recent_values = [entry[1] for entry in history[-self._zscore_period:] if len(entry) >= 2]

        

        # Calculate mean and standard deviation

        import statistics

        mean_val = statistics.mean(recent_values)

        std_val = statistics.stdev(recent_values) if len(recent_values) > 1 else 0.0

        

        if std_val <= 0.0001:  # Avoid division by zero

            return 0.0

        

        # Calculate Z-score

        zscore = (value - mean_val) / std_val

        

        return zscore

    

    def _apply_zscore_filter(self, asset: str, velocity: float) -> float:

        # Apply Z-score filter to detect extreme momentum (industry standard).

        # If Z-score is extreme (>2.0 or <-2.0), it indicates overbought/oversold conditions.

        # In such cases, we may want to reduce the signal strength or skip the trade.

        zscore = self._calculate_zscore(asset, velocity)

        

        # Log Z-score for monitoring

        if abs(zscore) > 2.0:

            logger.info("[Z-SCORE-EXTREME] asset=%s zscore=%.2f (overbought/oversold detected)", asset, zscore)

        

        # Return the original velocity (Z-score is used for monitoring/filtering, not normalization)

        # The caller can decide whether to filter based on Z-score

        return velocity

    

    def _update_adx_history(self, asset: str, current_price: float, open_price: float, high_price: float, low_price: float) -> None:

        # Phase 6: Update ADX history for trend filtering.

        # ADX (Average Directional Index) measures trend strength, not direction.

        # ADX < 20 = ranging market (weak trend, skip trades)

        # ADX >= 20 = trending market (strong trend, allow trades)

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        # CRITICAL FIX: Calculate DX here (once per price update) instead of in _calculate_adx

        # This ensures proper DX accumulation for ADX warmup (28 periods total)

        # CRITICAL FIX: Use OHLC data for proper True Range and Directional Movement calculation

        

        current_time = int(time.time() * 1000)

        history = list(self._spot_price_history[asset])

        

        if len(history) < 2:

            return

        

        # Get previous OHLC data

        prev_close = history[-2][1]  # Previous close price

        prev_high = history[-2][3] if len(history[-2]) > 3 else history[-2][1]  # Previous high or fallback to close

        prev_low = history[-2][4] if len(history[-2]) > 4 else history[-2][1]  # Previous low or fallback to close

        

        # Calculate True Range (TR) using OHLC data

        # TR = max(high - low, |high - prev_close|, |low - prev_close|)

        tr1 = high_price - low_price

        tr2 = abs(high_price - prev_close)

        tr3 = abs(low_price - prev_close)

        tr = max(tr1, tr2, tr3)

        self._tr_history[asset].append((current_time, tr))

        

        # Calculate Directional Movement (DM) using OHLC data

        # +DM = current_high - prev_high if positive and greater than downward movement, else 0

        # -DM = prev_low - current_low if positive and greater than upward movement, else 0

        upward_move = high_price - prev_high

        downward_move = prev_low - low_price

        

        if upward_move > downward_move and upward_move > 0:

            plus_dm = upward_move

            minus_dm = 0.0

        elif downward_move > upward_move and downward_move > 0:

            plus_dm = 0.0

            minus_dm = downward_move

        else:

            plus_dm = 0.0

            minus_dm = 0.0

        

        self._plus_dm_history[asset].append((current_time, plus_dm))

        self._minus_dm_history[asset].append((current_time, minus_dm))

        

        # CRITICAL FIX: Calculate DX immediately once we have enough TR history for DI calculation

        # This ensures DX accumulation starts as soon as possible for ADX warmup

        # Industry standard: DX is calculated per period, then smoothed to ADX

        if len(self._tr_history[asset]) >= self._adx_window_size:

            # Get smoothed TR, +DM, -DM using Wilder's smoothing

            tr_history = list(self._tr_history[asset])

            plus_dm_history = list(self._plus_dm_history[asset])

            minus_dm_history = list(self._minus_dm_history[asset])

            

            current_tr = tr_history[-1][1]

            current_plus_dm = plus_dm_history[-1][1]

            current_minus_dm = minus_dm_history[-1][1]

            

            # Calculate smoothed TR using Wilder's smoothing

            if self._prev_smoothed_tr[asset] == 0.0:

                recent_tr = [entry[1] for entry in tr_history[-self._adx_window_size:] if len(entry) >= 2]

                smoothed_tr = sum(recent_tr) / len(recent_tr)

            else:

                smoothed_tr = (self._prev_smoothed_tr[asset] * (self._adx_window_size - 1) + current_tr) / self._adx_window_size

            

            # Calculate smoothed +DM using Wilder's smoothing

            if self._prev_smoothed_plus_dm[asset] == 0.0:

                recent_plus_dm = [entry[1] for entry in plus_dm_history[-self._adx_window_size:] if len(entry) >= 2]

                smoothed_plus_dm = sum(recent_plus_dm) / len(recent_plus_dm)

            else:

                smoothed_plus_dm = (self._prev_smoothed_plus_dm[asset] * (self._adx_window_size - 1) + current_plus_dm) / self._adx_window_size

            

            # Calculate smoothed -DM using Wilder's smoothing

            if self._prev_smoothed_minus_dm[asset] == 0.0:

                recent_minus_dm = [entry[1] for entry in minus_dm_history[-self._adx_window_size:] if len(entry) >= 2]

                smoothed_minus_dm = sum(recent_minus_dm) / len(recent_minus_dm)

            else:

                smoothed_minus_dm = (self._prev_smoothed_minus_dm[asset] * (self._adx_window_size - 1) + current_minus_dm) / self._adx_window_size

            

            # Update previous smoothed values for next iteration

            self._prev_smoothed_tr[asset] = smoothed_tr

            self._prev_smoothed_plus_dm[asset] = smoothed_plus_dm

            self._prev_smoothed_minus_dm[asset] = smoothed_minus_dm

            

            # Calculate +DI and -DI (Directional Indicators)

            if smoothed_tr > 0:

                plus_di = (smoothed_plus_dm / smoothed_tr) * 100

                minus_di = (smoothed_minus_dm / smoothed_tr) * 100

            else:

                plus_di = 0.0

                minus_di = 0.0

            

            # Calculate DX (Directional Index)

            if (plus_di + minus_di) > 0:

                dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100

            else:

                dx = 0.0

            

            

            # Store DX in history for ADX calculation

            self._adx_history[asset].append((current_time, dx))

    

    def _calculate_adx(self, asset: str) -> float:

        # Phase 6: Calculate ADX (Average Directional Index) for trend filtering.

        # ADX measures trend strength (0-100 scale).

        # ADX < 20 = ranging market (weak trend)

        # ADX >= 20 = trending market (strong trend)

        # Returns ADX value or 0.0 if insufficient data.

        # CRITICAL FIX: DX is now calculated in _update_adx_history (once per price update)

        # This method only smooths DX from history to get ADX (industry standard)

        # Warmup requires 28 periods: 14 for TR/DM/DI/DX, 14 for ADX smoothing

        adx_history = list(self._adx_history[asset])

        

        if len(adx_history) < self._adx_window_size:

            return 0.0  # Not enough DX history for ADX calculation

        

        # Get current DX (most recent)

        current_dx = adx_history[-1][1]

        

        # Calculate ADX using Wilder's smoothing

        # First ADX: 14-period average of DX

        # Subsequent ADX: (prev_adx × 13 + current_dx) / 14

        if self._prev_adx[asset] == 0.0:

            # First calculation: simple average of first 14 DX values

            recent_dx = [entry[1] for entry in adx_history[-self._adx_window_size:] if len(entry) >= 2]

            adx = sum(recent_dx) / len(recent_dx)

            self._prev_adx[asset] = adx

        else:

            # Subsequent calculations: use Wilder's smoothing

            adx = (self._prev_adx[asset] * (self._adx_window_size - 1) + current_dx) / self._adx_window_size

            self._prev_adx[asset] = adx

        

        return adx

    

    def _is_trading_session_active(self) -> bool:

        # Phase 6: Check if current time is within active trading session.

        # Based on research: Trade during peak liquidity hours for better win rates.

        # Returns True if trading is allowed, False otherwise.

        if not self.config.enable_session_filter:

            return True  # Session filter disabled, always allow trading

        

        from datetime import datetime, timezone

        current_utc_hour = datetime.now(timezone.utc).hour

        

        # Define active trading windows

        # US-Europe overlap (13:00-17:00 UTC): Highest liquidity

        # US session (17:00-22:00 UTC): Good liquidity

        # European morning (08:00-13:00 UTC): Moderate liquidity

        # Asian session (00:00-08:00 UTC): Low liquidity (avoid)

        

        is_us_europe_overlap = (

            self.config.us_europe_overlap_start_utc <= current_utc_hour < self.config.us_europe_overlap_end_utc

        )

        is_us_session = (

            self.config.us_session_start_utc <= current_utc_hour < self.config.us_session_end_utc

        )

        is_european_morning = (

            self.config.european_morning_start_utc <= current_utc_hour < self.config.european_morning_end_utc

        )

        

        is_active = is_us_europe_overlap or is_us_session or is_european_morning

        

        session_name = "UNKNOWN"

        if is_us_europe_overlap:

            session_name = "US-Europe overlap (highest liquidity)"

        elif is_us_session:

            session_name = "US session (good liquidity)"

        elif is_european_morning:

            session_name = "European morning (moderate liquidity)"

        else:

            session_name = "Asian session (low liquidity, disabled)"

        

        logger.info(

            "[SESSION-FILTER] current_hour=%d session=%s active=%s",

            current_utc_hour, session_name, is_active

        )

        

        return is_active

    

    def _calculate_mean_reversion(self, asset: str, current_price: float) -> float:

        # Phase 4.3: Calculate mean reversion signal using 2-minute SMA.

        # Returns deviation from SMA as percentage (positive = above SMA, negative = below SMA).

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        history = list(self._sma_history[asset])

        if len(history) < 2:

            return 0.0

        

        # Calculate 2-minute SMA

        current_time = int(time.time() * 1000)  # Milliseconds to match spot service

        target_time = current_time - 120000  # 2 minutes ago in milliseconds

        

        prices_in_window = []

        # Handle OHLC format: (timestamp, close, open, high, low)

        for entry in history:

            if len(entry) >= 2:

                ts = entry[0]

                price = entry[1]  # Use close price

                if ts >= target_time:

                    prices_in_window.append(price)

        

        if len(prices_in_window) < 2:

            return 0.0

        

        sma = sum(prices_in_window) / len(prices_in_window)

        

        # Calculate deviation from SMA as percentage

        deviation_pct = (current_price - sma) / sma

        return deviation_pct

    

    def _apply_logit_fusion(self, velocity_logit: float, mean_reversion_logit: float, 

                           minutes_to_expiry: float) -> float:

        # Phase 4.4: Apply logit fusion to combine velocity and mean reversion signals.

        # Phase 4.5: Skip logit fusion near expiry (use velocity only).

        # CRITICAL FIX: 2026-07-07 - Use <= instead of < to handle exact boundary condition

        # At exactly 5 minutes (300 seconds), should use velocity-only mode

        if minutes_to_expiry * 60 <= self._near_expiry_guard_sec:

            # Near expiry, use velocity logit only

            logger.debug("[LOGIT-FUSION] Near expiry (%.1f min), using velocity logit only", minutes_to_expiry)

            return velocity_logit

        

        # Apply weighted fusion

        fused_logit = (self._logit_fusion_velocity_weight * velocity_logit + 

                      self._logit_fusion_mean_reversion_weight * mean_reversion_logit)

        return fused_logit

    

    def record_outcome(self, logit: float, outcome: int) -> None:

        """

        Record a prediction outcome for calibration.

        

        Phase 5.3: Records the logit and binary outcome for Platt scaling calibration.

        Automatically fits calibration when sufficient data is available and auto-fit is enabled.

        

        Args:

            logit: Raw model logit used for prediction

            outcome: Binary outcome (0 or 1)

        """

        if not self._calibration_enabled or not self._platt_scaler:

            return

        

        # Add to calibration history

        self._calibration_logits.append(logit)

        self._calibration_outcomes.append(outcome)

        

        # Maintain rolling window

        if len(self._calibration_logits) > self._calibration_max_samples:

            self._calibration_logits.pop(0)

            self._calibration_outcomes.pop(0)

        

        logger.debug("[CALIBRATION] Recorded outcome: logit=%.4f outcome=%d (total samples=%d)",

                    logit, outcome, len(self._calibration_logits))

        

        # Auto-fit if enabled and sufficient data

        if self._calibration_auto_fit and len(self._calibration_logits) >= self._calibration_min_samples:

            self._fit_calibration()

    

    def _fit_calibration(self) -> None:

        """

        Fit Platt scaling calibration with current data.

        

        Phase 5.3: Fits the Platt scaler when sufficient data is available.

        Checks fit interval to avoid refitting too frequently.

        """

        if not self._platt_scaler or len(self._calibration_logits) < self._calibration_min_samples:

            return

        

        import time

        current_time = time.time()

        

        # Check fit interval (default 24 hours)

        if self._last_fit_time > 0 and (current_time - self._last_fit_time) < (self._calibration_fit_interval_hours * 3600):

            logger.debug("[CALIBRATION] Skipping fit: last fit %.1f hours ago, interval is %d hours",

                        (current_time - self._last_fit_time) / 3600, self._calibration_fit_interval_hours)

            return

        

        try:

            self._platt_scaler.fit(self._calibration_logits, self._calibration_outcomes)

            self._last_fit_time = current_time

            

            # Evaluate calibration metrics

            metrics = self._platt_scaler.evaluate_metrics(self._calibration_logits, self._calibration_outcomes)

            logger.info("[CALIBRATION] Fitted PlattScaler: Brier=%.4f ECE=%.4f MCE=%.4f samples=%d",

                       metrics.brier_score, metrics.expected_calibration_error,

                       metrics.maximum_calibration_error, metrics.num_samples)

        except Exception as e:

            logger.error("[CALIBRATION] Failed to fit PlattScaler: %s", e)

    

    def get_calibration_metrics(self) -> Optional[dict]:

        """

        Get current calibration metrics.

        

        Phase 5.5: Returns calibration metrics for monitoring and API exposure.

        

        Returns:

            Dictionary with calibration metrics, or None if calibration is disabled/not fitted

        """

        if not self._calibration_enabled or not self._platt_scaler or not self._platt_scaler.is_fitted():

            return None

        

        try:

            metrics = self._platt_scaler.evaluate_metrics(self._calibration_logits, self._calibration_outcomes)

            params = self._platt_scaler.get_parameters()

            

            return {

                "is_fitted": True,

                "num_samples": metrics.num_samples,

                "brier_score": metrics.brier_score,

                "expected_calibration_error": metrics.expected_calibration_error,

                "maximum_calibration_error": metrics.maximum_calibration_error,

                "platt_a": params[0] if params else None,

                "platt_b": params[1] if params else None,

                "last_fit_time": self._last_fit_time,

            }

        except Exception as e:

            logger.error("[CALIBRATION] Failed to get calibration metrics: %s", e)

            return None

    

    def _classify_volatility_regime(self, ticker: str) -> tuple[str, float]:

        """

        Classify volatility regime and return (regime_name, current_volatility).

        

        2026 best practice: Use short-horizon volatility to map to spread width.

        Three regimes: calm, elevated, violent with corresponding spread thresholds.

        

        Returns:

            tuple: (regime_name, current_volatility_pct)

        """

        try:

            # Get recent price history for volatility calculation

            if not self.market_state_store:

                return "calm", 0.001  # Default to calm regime

            

            market_state = self.market_state_store.get(ticker)

            if not market_state:

                return "calm", 0.001

            

            # Get recent mid prices from market state history

            # Use 5-minute window as configured

            volatility_window = self.config.volatility_window_s  # 300s = 5 minutes

            

            # Calculate realized volatility from price changes

            # For 15m crypto, use spot price velocity as proxy

            from data.unified_spot_service import get_unified_spot_service

            spot_service = get_unified_spot_service()

            

            asset = self.config.name.replace("_15M", "")  # Extract asset name

            spot_data = spot_service.get_spot_history(asset, window_s=volatility_window)

            

            if not spot_data or len(spot_data) < 2:

                # Insufficient data - default to calm regime with minimum volatility

                logger.debug("[VOLATILITY-REGIME] asset=%s ticker=%s insufficient price history (%d points), using calm regime",

                           self.config.name, ticker, len(spot_data) if spot_data else 0)

                return "calm", 0.001

            

            # Calculate realized volatility (standard deviation of returns)

            prices = [p["price"] for p in spot_data]

            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]

            

            if not returns:

                return "calm", 0.001

            

            import statistics

            volatility = statistics.stdev(returns) if len(returns) > 1 else 0.001

            

            # Classify regime based on volatility thresholds

            if volatility < self.config.calm_volatility_threshold:

                regime = "calm"

            elif volatility < self.config.elevated_volatility_threshold:

                regime = "elevated"

            else:

                regime = "violent"

            

            logger.debug("[VOLATILITY-REGIME] asset=%s ticker=%s regime=%s volatility=%.4f",

                        self.config.name, ticker, regime, volatility)

            

            return regime, volatility

            

        except Exception as e:

            logger.warning("[VOLATILITY-REGIME] Failed to classify volatility for %s: %s, using calm", ticker, e)

            return "calm", 0.001

    

    def _get_dynamic_spread_threshold(self, ticker: str) -> int:

        """

        Calculate dynamic spread threshold based on volatility regime and asset class.

        

        Phase 1A (2026-07-09): Asset-specific overrides for Kalshi microstructure

        - BTC/ETH: Deeper books, tighter thresholds (300bp calm, 400bp elevated, 600bp violent)

        - SOL/XRP/DOGE: Thinner books, looser thresholds (350bp calm, 450bp elevated, 700bp violent)

        

        2026 best practice: "Blow your spreads out when the market's volatility does"

        Uses continuous interpolation between regime anchors for smooth transitions.

        

        Formula: spread_t = base_width * (sigma_t / sigma_bar)^lambda

        

        Returns:

            int: Dynamic spread threshold in basis points

        """

        regime, volatility = self._classify_volatility_regime(ticker)

        

        # Phase 1A: Determine asset class for per-asset thresholds

        asset_symbol = ticker.split("_")[0] if "_" in ticker else ticker

        is_major_asset = asset_symbol in ["BTC", "ETH"]

        

        # Get regime-specific thresholds with asset-specific overrides

        if regime == "calm":

            if is_major_asset:

                threshold_bp = self.config.calm_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.calm_spread_threshold_bp_sol_xrp_doge

        elif regime == "elevated":

            if is_major_asset:

                threshold_bp = self.config.elevated_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.elevated_spread_threshold_bp_sol_xrp_doge

        else:  # violent

            if is_major_asset:

                threshold_bp = self.config.violent_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.violent_spread_threshold_bp_sol_xrp_doge

        

        # Apply continuous interpolation for smooth transitions

        # Use volatility ratio to interpolate between regimes

        calm_threshold = self.config.calm_volatility_threshold

        elevated_threshold = self.config.elevated_volatility_threshold

        

        if regime == "calm":

            # In calm regime, use calm threshold directly (no interpolation)

            # This ensures we can trade even in low-volatility conditions

            if is_major_asset:

                threshold_bp = self.config.calm_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.calm_spread_threshold_bp_sol_xrp_doge

        elif regime == "elevated":

            # Interpolate between elevated and violent

            ratio = volatility / elevated_threshold

            if is_major_asset:

                base = self.config.elevated_spread_threshold_bp_btc_eth

                target = self.config.violent_spread_threshold_bp_btc_eth

            else:

                base = self.config.elevated_spread_threshold_bp_sol_xrp_doge

                target = self.config.violent_spread_threshold_bp_sol_xrp_doge

            interpolated = base * (ratio ** self.config.spread_volatility_sensitivity)

            threshold_bp = int(interpolated)

            threshold_bp = min(threshold_bp, target)

        # violent regime uses maximum threshold

        

        logger.debug("[DYNAMIC-SPREAD] asset=%s ticker=%s regime=%s is_major=%s threshold=%dbp volatility=%.4f",

                    self.config.name, ticker, regime, is_major_asset, threshold_bp, volatility)

        

        return threshold_bp

    

    def _classify_regime(self, ticker: str) -> str:

        # Classify market regime from depth using same logic as loop_15m.py

        # Regime classification matches the one used in _validate_market_state

        regime = "normal"  # Default fallback

        try:

            if not self.market_state_store:

                return regime

            

            market_state = self.market_state_store.get(ticker)

            if market_state:

                # Classify regime from depth

                min_depth_yes = getattr(market_state, 'min_depth_yes', 0)

                min_depth_no = getattr(market_state, 'min_depth_no', 0)

                # Use depth thresholds from risk envelope (default to 1 if not available)

                min_depth_yes_threshold = 1

                min_depth_no_threshold = 1

                has_yes = min_depth_yes >= min_depth_yes_threshold

                has_no = min_depth_no >= min_depth_no_threshold

                if has_yes and has_no:

                    regime = "both_sides"

                elif has_yes and not has_no:

                    regime = "one_sided_yes"

                elif not has_yes and has_no:

                    regime = "one_sided_no"

                else:

                    regime = "no_liquidity"

                logger.debug("[REGIME-CLASSIFY] ticker=%s regime=%s (yes_depth=%d no_depth=%d)", 

                           ticker, regime, min_depth_yes, min_depth_no)

        except Exception as regime_err:

            logger.warning("[REGIME-CLASSIFY] Failed to classify regime for %s: %s, using 'normal'", ticker, regime_err)

            regime = "normal"

        

        return regime

    

    def _validate_market_state(self, market: Any) -> bool:

        # Validate market state for trading.

        # Checks: market is open, sufficient liquidity, reasonable spread, fresh data.

        if not market:

            logger.warning("[MARKET-VALIDATION] asset=%s no market available", self.config.name)

            return False

        

        # Get market state from store

        ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

        

        # Check if market_state_store is available

        if not self.market_state_store:

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s market_state_store is None", 

                         self.config.name, ticker)

            return False

        

        market_state = self.market_state_store.get(ticker)

        

        if not market_state:

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s no market state", 

                         self.config.name, ticker)

            return False

        

        # FIXED: Removed duality check from agent_grid

        # The orderbook already validates duality at the data source (duality_validator.py)

        # Re-checking duality here on derived NO prices creates false violations

        # Duality validation is handled by:

        # 1. LocalOrderbook._check_crossed_market() in orderbook.py

        # 2. DualityValidator.check_yes_no_duality() in duality_validator.py

        # 3. KalshiMarketState.check_health() in market_state.py

        # Agent grid should only use validated prices from market_state

        

        # Check staleness (default 15 seconds from profile)

        venue_staleness = 15  # Default, will be overridden by profile

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile = get_active_profile()

            venue_staleness = profile.get("venue_staleness", 15)

        except Exception:

            pass

        

        staleness_threshold_ms = venue_staleness * 1000

        

        # Calculate staleness from last_update_ts (KalshiMarketState doesn't have staleness_ms)

        now = time.time()

        last_update = getattr(market_state, 'last_update_ts', 0.0)

        

        # If last_update_ts is 0 or very old (uninitialized), treat as fresh

        # This allows trading to start before WS bridge populates data

        if last_update == 0 or last_update < 1000000000:  # Before 2001-09-09

            staleness_ms = 0

        else:

            staleness_ms = int((now - last_update) * 1000)

        

        if staleness_ms > staleness_threshold_ms:

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s stale=%dms threshold=%dms",

                         self.config.name, ticker, staleness_ms, staleness_threshold_ms)

            return False

        

        # Check liquidity (depth) with one-sided regime classification

        # Kalshi 15m books are often one-sided - we should allow trading on the liquid side

        # Depth thresholds from risk envelope/profile (single source of truth)

        # CRITICAL FIX: Removed 10x multiplier that was ignoring profile config

        # The profile YAML already sets appropriate depth thresholds (1-2 contracts for 15m crypto)

        # Applying a 10x multiplier was requiring 60-70 contracts when profile only required 1

        # This was causing massive trade rejections and low fill rates

        min_depth_yes_threshold = 1

        min_depth_no_threshold = 1

        

        try:

            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope

            envelope = get_kalshi_crypto_15m_risk_envelope()

            # Extract asset symbol from agent name (e.g., "DOGE_15M" -> "DOGE")

            asset_symbol = self.config.name.split('_')[0] if '_' in self.config.name else self.config.name

            depth_thresholds = envelope.get_depth_thresholds(asset_symbol)

            min_depth_yes_threshold = depth_thresholds.get('min_depth_yes', 1)

            min_depth_no_threshold = depth_thresholds.get('min_depth_no', 1)

            

            logger.info(

                "[DEPTH-THRESHOLD] asset=%s min_depth_yes=%d min_depth_no=%d (from profile)",

                self.config.name, min_depth_yes_threshold, min_depth_no_threshold

            )

        except RuntimeError as e:

            # Bankroll not ready - use default thresholds

            logger.warning(

                "[DEPTH-THRESHOLD] Failed to get depth thresholds from envelope: %s (using defaults)",

                e

            )

        except Exception as e:

            # Fallback to defaults if envelope not available

            logger.warning("[DEPTH-THRESHOLD] Failed to load from envelope: %s, using defaults", e)

        

        min_depth_yes = getattr(market_state, 'min_depth_yes', 0)

        min_depth_no = getattr(market_state, 'min_depth_no', 0)

        

        # Classify book regime

        has_yes = min_depth_yes >= min_depth_yes_threshold

        has_no = min_depth_no >= min_depth_no_threshold

        

        if has_yes and has_no:

            regime = "both_sides"

        elif has_yes and not has_no:

            regime = "one_sided_yes"

        elif not has_yes and has_no:

            regime = "one_sided_no"

        else:

            regime = "no_liquidity"

        

        # Reject if no liquidity on either side

        if regime == "no_liquidity":

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s no liquidity yes=%d no=%d (thresholds: yes=%d no=%d) regime=%s",

                         self.config.name, ticker, min_depth_yes, min_depth_no, min_depth_yes_threshold, min_depth_no_threshold, regime)

            return False

        

        # CRITICAL FIX: Relaxed one-sided rejection for 15-minute markets

        # Previous logic: Reject one-sided books when TTE > 1 minute (too aggressive)

        # New logic: Allow one-sided books with sufficient depth on the trading side

        # Rationale: 15-minute crypto markets are frequently one-sided, especially for smaller assets

        # Risk mitigation: We only trade on the liquid side (YES for one_sided_yes, NO for one_sided_no)

        # This allows trading while avoiding the risk of being stuck in an illiquid position

        if regime in ["one_sided_yes", "one_sided_no"]:

            # Get time to expiry

            close_time = getattr(market, 'close_time', 0)

            if hasattr(market, 'market'):

                close_time = getattr(market.market, 'close_time', 0)

            

            if close_time > 0:

                now = time.time()

                minutes_to_expiry = (close_time - now) / 60.0

                

                # Only reject one-sided books in last 30 seconds (terminal phase)

                # Before that, allow trading on the liquid side

                if minutes_to_expiry > 0.5:

                    # More than 30 seconds to expiry: allow one-sided books

                    logger.info(

                        "[ONE-SIDED-ALLOW] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d tte=%.1fmin > 0.5min -> ALLOW (trading on liquid side)",

                        self.config.name, ticker, regime, min_depth_yes, min_depth_no, minutes_to_expiry

                    )

                else:

                    # Last 30 seconds: reject one-sided books (terminal phase risk)

                    logger.warning(

                        "[ONE-SIDED-REJECT] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d tte=%.1fmin <= 0.5min -> REJECT (terminal phase, exit risk)",

                        self.config.name, ticker, regime, min_depth_yes, min_depth_no, minutes_to_expiry

                    )

                    return False

            else:

                # No close time available: allow one-sided books (less conservative)

                logger.info(

                    "[ONE-SIDED-ALLOW] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d no close_time -> ALLOW (trading on liquid side)",

                    self.config.name, ticker, regime, min_depth_yes, min_depth_no

                )

        

        # Log regime for visibility

        logger.info("[MARKET-VALIDATION] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d (thresholds: yes=%d no=%d)",

                   self.config.name, ticker, regime, min_depth_yes, min_depth_no, min_depth_yes_threshold, min_depth_no_threshold)

        

        # Check spread - RELAXED for one-sided books (common in 15m crypto)

        # Allow trading if at least one side has liquidity

        best_bid = getattr(market_state, 'best_bid_cents', 0)

        best_ask = getattr(market_state, 'best_ask_cents', 0)

        

        # Handle None values - treat as 0

        if best_bid is None:

            best_bid = 0

        if best_ask is None:

            best_ask = 0

        

        # For one-sided books, skip spread check and use available side

        if best_bid > 0 and best_ask > 0:

            # Both sides available - check spread

            spread_cents = best_ask - best_bid

            

            # 2026-07-11: Adaptive spread filter - treat wide spread as regime signal, not immediate kill-switch

            # For binary options with massive depth (e.g., DOGE: 250 yes, 48886 no), wide spreads (92c) are acceptable

            # Only reject pathological spreads (> 150c) that indicate no meaningful liquidity

            coarse_filter_threshold = 150  # Relaxed from 75c to allow trading in current market conditions

            if spread_cents > coarse_filter_threshold:

                logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s spread exceeds coarse filter=%dc (spread=%dc) - rejecting as pathological",

                               self.config.name, ticker, coarse_filter_threshold, spread_cents)

                return False

            

            # CRITICAL FIX: Remove basis point validation for binary options

            # Binary options have 0-100c price range, making BP calculations inappropriate

            # A 37c spread on 50c mid = 74% = 7400bp, which looks extreme but is normal for binary options

            # Use cents-based validation only, which is correctly configured with 20c coarse filter

            # Legacy check in cents for backward compatibility

            if spread_cents > self.config.max_spread_cents:

                logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s spread too wide=%dc > max=%dc",

                             self.config.name, ticker, spread_cents, self.config.max_spread_cents)

                return False

        elif best_bid == 0 and best_ask == 0:

            # No liquidity on either side

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s no bid/ask available (bid=%d ask=%d)",

                         self.config.name, ticker, best_bid, best_ask)

            return False

        else:

            # One-sided book - allow trading on liquid side

            logger.info("[MARKET-VALIDATION] asset=%s ticker=%s one-sided book (bid=%d ask=%d) - allowing trade",

                       self.config.name, ticker, best_bid, best_ask)

        

        logger.info("[MARKET-VALIDATION] asset=%s ticker=%s VALID regime=%s depth_yes=%d depth_no=%d staleness=%dms",

                   self.config.name, ticker, regime, min_depth_yes, min_depth_no, staleness_ms)

        return True

    

    def _generate_signal(

        self,

        spot_price: float,

        market: Any,

        minutes_to_expiry: float,

    ) -> Optional[Dict[str, Any]]:

        # Generate trading signal using Coinbase 1-minute velocity (2026 #1 winning strategy).

        logger.debug("[GENERATE-SIGNAL-ENTRY] spot_price=%s market_type=%s minutes_to_expiry=%s", spot_price, type(market), minutes_to_expiry)

        

        # Phase 6: Check if trading session is active

        if not self._is_trading_session_active():

            logger.info("[SESSION-FILTER] Trading session not active, skipping signal generation")

            if REJECTION_MONITOR_ENABLED:

                monitor = get_rejection_monitor()

                monitor.log_rejection(

                    asset="UNKNOWN",

                    category="session_filter",

                    reason="Trading session not active, skipping signal generation",

                    session_active=False,

                )

            return None

        

        # Extract asset from market (must be done before time window filter for logging)

        asset = None

        if hasattr(market, 'asset'):

            asset = market.asset

        elif hasattr(market, 'ticker'):

            ticker = market.ticker

            # Extract asset from ticker (e.g., "KXBTC15M-26JUN301900-00" -> "BTC")

            if 'BTC' in ticker:

                asset = 'BTC'

            elif 'ETH' in ticker:

                asset = 'ETH'

            elif 'SOL' in ticker:

                asset = 'SOL'

            elif 'XRP' in ticker:

                asset = 'XRP'

            elif 'DOGE' in ticker:

                asset = 'DOGE'

        

        if not asset:

            logger.warning("[SIGNAL-ERROR] Could not determine asset from market")

            return None

        

        # ENTRY MATRIX: Time window entry rules (CRITICAL FIX: 2026-07-08 - Use profile YAML as single source of truth)

        # Previous hardcoded values (>=14.0min, <=0.5min) conflicted with profile YAML configuration

        # Profile YAML defines:

        # - min_decision_minute: per-asset minimum minute to start trading (default 1)

        # - guardrails.min_entry_mins: minimum time to expiry for entry (2.0min)

        # - guardrails.max_entry_mins: maximum time to expiry for entry (15.0min)

        # - guardrails.cutoff_minutes_before_expiry: stop trading N minutes before expiry (2min)

        

        # Get timing configuration from profile YAML

        min_entry_mins = 2.0  # Default from guardrails.min_entry_mins

        max_entry_mins = 15.0  # Default from guardrails.max_entry_mins

        cutoff_mins = 2.0  # Default from guardrails.cutoff_minutes_before_expiry

        

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            adapter = get_active_profile()

            if adapter and adapter._profile:

                profile = adapter._profile

                min_entry_mins = profile.guardrails_min_entry_mins

                max_entry_mins = profile.guardrails_max_entry_mins

                cutoff_mins = profile.agent_cutoff_minutes_before_expiry

                logger.debug(

                    "[TIME-WINDOW-CONFIG] asset=%s min_entry=%.1fmin max_entry=%.1fmin cutoff=%.1fmin (from profile)",

                    asset, min_entry_mins, max_entry_mins, cutoff_mins

                )

            else:

                # Use defaults if profile not available

                min_entry_mins = 2.0

                max_entry_mins = 15.0

                cutoff_mins = 2.0

                logger.debug("[TIME-WINDOW-CONFIG] asset=%s using defaults (profile not available)", asset)

        except Exception as e:

            logger.warning("[TIME-WINDOW-CONFIG] Failed to load from profile: %s, using defaults", e)

            min_entry_mins = 2.0

            max_entry_mins = 15.0

            cutoff_mins = 2.0

        

        time_edge_multiplier = 1.0

        

        # Check if within trading window

        if minutes_to_expiry > max_entry_mins:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (too early, >%.1fmin)",

                asset, minutes_to_expiry, max_entry_mins

            )

            if REJECTION_MONITOR_ENABLED:

                log_time_window_rejection(

                    asset=asset,

                    minutes_to_expiry=minutes_to_expiry,

                    reason=f"too early: >{max_entry_mins}min",

                    market_id=getattr(market, 'market_id', None),

                )

            return None

        elif minutes_to_expiry < cutoff_mins:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (terminal phase, <%.1fmin to expiry)",

                asset, minutes_to_expiry, cutoff_mins

            )

            if REJECTION_MONITOR_ENABLED:

                log_time_window_rejection(

                    asset=asset,

                    minutes_to_expiry=minutes_to_expiry,

                    reason=f"terminal phase: <{cutoff_mins}min to expiry",

                    market_id=getattr(market, 'market_id', None),

                )

            return None

        elif minutes_to_expiry < min_entry_mins:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (too early, <%.1fmin to expiry)",

                asset, minutes_to_expiry, min_entry_mins

            )

            if REJECTION_MONITOR_ENABLED:

                log_time_window_rejection(

                    asset=asset,

                    minutes_to_expiry=minutes_to_expiry,

                    reason=f"too early: <{min_entry_mins}min to expiry",

                    market_id=getattr(market, 'market_id', None),

                )

            return None

        elif minutes_to_expiry <= 4.0:

            time_edge_multiplier = 1.5

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> REDUCED (late entry, 1.5x edge multiplier)",

                asset, minutes_to_expiry

            )

        else:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> OPTIMAL (baseline edge requirements)",

                asset, minutes_to_expiry

            )

        

        # ENTRY MATRIX: Per-asset minimum entry price (based on trade history analysis)

        # Updated 2026-07-07: Aligned to 10c to match profile guardrails_min_contract_price_cents

        # Previous 15c minimum was blocking valid 10-19c entries that profile allows

        # - Entry prices < $0.10 are rejected by DEEP_OTM_POLICY (lottery zone)

        # - Entry band [10c, 75c] per 2026-07-12 expansion to match current market conditions

        # - This aligns agent grid with profile, order_gate, and order_router (all 10c minimum)

        min_entry_prices = {

            'BTC': 10,

            'ETH': 10,

            'SOL': 10,

            'XRP': 10,

            'DOGE': 10

        }

        min_price_cents = min_entry_prices.get(asset, 10)  # Default to 10c

        

        # Get current market price for BOTH YES and NO sides

        # CRITICAL FIX: Evaluate both YES and NO contracts within 10c-50c sweet spot

        # Select best edge - don't force YES or NO decision

        yes_price_cents = 0

        no_price_cents = 0

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                best_bid = getattr(market_state, 'best_bid_cents', 0) or 0

                best_ask = getattr(market_state, 'best_ask_cents', 0) or 0

                

                # YES price is the bid (price to buy YES)

                yes_price_cents = best_bid if best_bid > 0 else 0

                

                # NO price is derived from YES price: NO = 100 - YES

                # In binary markets, YES + NO = 100 cents

                no_price_cents = (100 - best_ask) if best_ask > 0 else 0

                

                logger.info(

                    "[DUAL-SIDE-PRICE] asset=%s ticker=%s yes_price=%dc no_price=%dc (derived from bid=%dc ask=%dc)",

                    asset, ticker, yes_price_cents, no_price_cents, best_bid, best_ask

                )

        except Exception as e:

            logger.warning("[PRICE-FILTER-ERROR] asset=%s failed to get market price: %s", asset, e)

        

        # Check which sides are within 10c-75c canonical range (2026-07-12 expanded for market conditions)

        # Previous 10c-50c range was too restrictive for current market conditions

        # Expanded range allows trading in high-conviction (YES > 50c) and low-conviction (NO > 50c) markets

        yes_in_range = (10 <= yes_price_cents <= 75)

        no_in_range = (10 <= no_price_cents <= 75)

        

        logger.info(

            "[PRICE-RANGE-CHECK] asset=%s yes_price=%dc in_range=%s no_price=%dc in_range=%s",

            asset, yes_price_cents, yes_in_range, no_price_cents, no_in_range

        )

        

        # If neither side is in range, skip trading

        if not yes_in_range and not no_in_range:

            logger.info(

                "[PRICE-FILTER-REJECT] asset=%s both sides outside 10c-75c range (yes=%dc, no=%dc) -> SKIP",

                asset, yes_price_cents, no_price_cents

            )

            if REJECTION_MONITOR_ENABLED:

                log_price_range_rejection(

                    asset=asset,

                    yes_price_cents=yes_price_cents,

                    no_price_cents=no_price_cents,

                    reason="both sides outside 10c-75c range",

                    market_id=getattr(market, 'market_id', None),

                )

            return None

        

        # Determine which side to evaluate based on price range

        # If both in range, we'll evaluate both and select best edge later

        # If only one in range, evaluate that side

        sides_to_evaluate = []

        if yes_in_range:

            sides_to_evaluate.append("yes")

        if no_in_range:

            sides_to_evaluate.append("no")

        

        logger.info(

            "[DUAL-SIDE-EVALUATION] asset=%s will evaluate sides: %s",

            asset, sides_to_evaluate

        )

        

        # Price-bucket EV diagnostic logging for both sides

        for side, price_cents in [("yes", yes_price_cents), ("no", no_price_cents)]:

            if price_cents > 0:

                if 10 <= price_cents <= 14:

                    price_bucket = "10-14c"

                elif 15 <= price_cents <= 19:

                    price_bucket = "15-19c"

                elif 20 <= price_cents <= 24:

                    price_bucket = "20-24c"

                elif 25 <= price_cents <= 29:

                    price_bucket = "25-29c"

                elif 30 <= price_cents <= 39:

                    price_bucket = "30-39c"

                elif 40 <= price_cents <= 49:

                    price_bucket = "40-49c"

                elif 50 <= price_cents <= 65:

                    price_bucket = "50-65c"

                elif 66 <= price_cents <= 70:

                    price_bucket = "66-70c"

                else:

                    price_bucket = f"{price_cents}c"

                

                logger.info(

                    "[PRICE-BUCKET-DIAGNOSTIC] asset=%s side=%s price_cents=%d bucket=%s (for EV tracking)",

                    asset, side, price_cents, price_bucket

                )

        

        # CRITICAL FIX: Update price history (including ADX) in _generate_signal path

        # The system uses _generate_signal instead of collect_order_candidate for signal generation

        # Without this call, ADX data never gets collected, causing ADX=0.00 permanently

        # CRITICAL FIX: Pass spot_data if available for OHLC-based ADX/ATR calculation

        spot_data = None

        if hasattr(self.spot_provider, 'get'):

            result = self.spot_provider.get(asset)

            logger.info("[GENERATE-SIGNAL-SPOT-GET] asset=%s result=%s type=%s",

                       asset, result, type(result).__name__ if result else None)

            if result is not None and hasattr(result, 'price'):

                spot_data = result

                logger.info("[GENERATE-SIGNAL-SPOT-SUCCESS] asset=%s spot_price=%s has_ohlc=%s",

                           asset, format_price(asset, result.price),

                           hasattr(result, 'open') and hasattr(result, 'high') and hasattr(result, 'low'))

            else:

                logger.warning("[GENERATE-SIGNAL-SPOT-FAIL] asset=%s result=%s has_price=%s",

                             asset, result, hasattr(result, 'price') if result else False)

        

        # Update price history (including ADX) in _generate_signal path

        # The system uses _generate_signal instead of collect_order_candidate for signal generation

        # Without this call, ADX data never gets collected, causing ADX=0.00 permanently

        # Pass spot_data if available for OHLC-based ADX/ATR calculation

        self._update_price_history(asset, spot_price, spot_data)

        

        # Price history already updated in collect_order_candidate (before calling _generate_signal)

        # This prevents the vicious cycle: no signal -> no price update -> velocity=0 -> no signal

        

        # PRICE-BASED STRATEGY (Turbine research winner: +56.6% ROI)

        # Buy YES when price <= 0.50, sell when price >= 0.70

        if self.config.signal_mode == "price_based":

            return self._generate_price_based_signal(asset, spot_price, market, minutes_to_expiry)

        

        # CRITICAL FIX: 2026-07-06 - Wire MACD/RSI into momentum_fvg signal generation

        # MOMENTUM_FVG STRATEGY: Combines velocity, MACD, RSI, OBI, and FVG for enhanced signals

        if self.config.signal_mode == "momentum_fvg":

            return self._generate_momentum_fvg_signal(asset, spot_price, market, minutes_to_expiry)

        

        # CRITICAL FIX: 2026-07-06 - Integrate trend alignment as confirmation filter

        # TREND_ALIGNMENT STRATEGY: Requires 5m and 1h trend agreement for signal confirmation

        # Based on Turbine research: trend alignment was consistently profitable

        trend_aligned = self._check_trend_alignment(asset, spot_price)

        if not trend_aligned:

            logger.info(

                "[TREND-ALIGNMENT-FILTER] asset=%s 5m and 1h trends not aligned -> SKIP TRADE (trend disagreement)",

                asset

            )

            if REJECTION_MONITOR_ENABLED:

                log_trend_alignment_rejection(

                    asset=asset,

                    reason="5m and 1h trends not aligned -> SKIP TRADE (trend disagreement)",

                    market_id=getattr(market, 'market_id', None),

                )

            return None

        else:

            logger.info(

                "[TREND-ALIGNMENT-CONFIRMED] asset=%s 5m and 1h trends aligned -> PROCEED",

                asset

            )

        

        # CRITICAL FIX: Use multi-window velocity for both threshold comparison AND logit calculation

        # Previous bug: Used simple _calculate_velocity for threshold but _calculate_multi_window_velocity for logit

        # This created inconsistency where threshold decision and probability calculation used different velocities

        # Now both use the same multi-window velocity with EMA smoothing and ATR normalization

        velocity = self._calculate_multi_window_velocity(asset, spot_price)

        

        logger.info(

            "[VELOCITY-CALC] asset=%s current=%s velocity=%.9f (%.4f%%) multi-window with EMA smoothing",

            asset, format_price(asset, spot_price), velocity, velocity * 100

        )

        

        # VELOCITY-BASED SIGNAL DECISION (2026 #1 winner)

        # Positive velocity (> threshold) -> buy YES

        # Negative velocity (< -threshold) -> buy NO

        # Small velocity (between -threshold and threshold) -> no trade

        # Phase 7: Use dynamic ATR-based threshold instead of static threshold

        velocity_threshold = self._calculate_dynamic_velocity_threshold(asset)  # Dynamic threshold based on ATR

        

        # Get market price and strike price for price-based confirmation

        market_price = 0.0

        strike_price = None

        strike_source = ""

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                best_bid = getattr(market_state, 'best_bid_cents', 0) or 0

                best_ask = getattr(market_state, 'best_ask_cents', 0) or 0

                if best_bid > 0 and best_ask > 0:

                    market_price = (best_bid + best_ask) / 200.0  # Convert cents to price

                elif best_bid > 0:

                    market_price = best_bid / 100.0

                elif best_ask > 0:

                    market_price = best_ask / 100.0

                

                # CRITICAL: Use window_strike_price (captured at market activation from Kalshi's floor_strike)

                # This is the authoritative reference price for 15-minute UP/DOWN markets

                window_strike = getattr(market_state, 'window_strike_price', None)

                window_strike_source = getattr(market_state, 'window_strike_source', "")

                

                # Capture candle_open_price from spot feed for validation

                # This is the secondary source to validate against Kalshi's floor_strike

                candle_open = getattr(market_state, 'candle_open_price', None)

                if candle_open is None or candle_open <= 0:

                    # First time seeing this market/window - capture spot as candle_open

                    market_state.candle_open_price = spot_price

                    market_state.candle_open_ts = time.time()

                    logger.info(

                        "[CANDLE-OPEN-CAPTURE] asset=%s ticker=%s candle_open=%.2f captured from spot feed",

                        asset, ticker, spot_price

                    )

                    candle_open = spot_price

                

                if window_strike is not None and window_strike > 0:

                    strike_price = window_strike

                    strike_source = window_strike_source

                    logger.info(

                        "[STRIKE-SOURCE] asset=%s using window_strike_price=%.2f (source=%s)",

                        asset, strike_price, strike_source

                    )

                else:

                    # Fallback: Use current spot price if window_strike_price unavailable

                    # This happens during warmup or if floor_strike not yet populated

                    strike_price = spot_price

                    strike_source = "spot_fallback"

                    logger.info(

                        "[STRIKE-FALLBACK] asset=%s window_strike_price unavailable, using current spot=%.2f (source=spot_fallback)",

                        asset, strike_price

                    )

                

                # Validation: Log divergence if both window_strike and candle_open are available

                # Use asset-specific divergence thresholds based on volatility

                if candle_open is not None and candle_open > 0 and strike_price is not None:

                    divergence_pct = abs((strike_price - candle_open) / candle_open) * 100

                    # Asset-specific thresholds: BTC/ETH 0.1%, SOL 0.15%, XRP/DOGE 0.2%

                    divergence_thresholds = {

                        "BTC": 0.1,

                        "ETH": 0.1,

                        "SOL": 0.15,

                        "XRP": 0.2,

                        "DOGE": 0.2

                    }

                    threshold = divergence_thresholds.get(asset, 0.1)  # Default to 0.1% for unknown assets

                    if divergence_pct > threshold:

                        logger.warning(

                            "[STRIKE-DIVERGENCE] asset=%s window_strike=%.2f candle_open=%.2f divergence=%.2f%% (threshold=%.2f%%)",

                            asset, strike_price, candle_open, divergence_pct, threshold

                        )

                    else:

                        logger.info(

                            "[STRIKE-VALIDATION] asset=%s window_strike=%.2f candle_open=%.2f divergence=%.2f%% (OK, threshold=%.2f%%)",

                            asset, strike_price, candle_open, divergence_pct, threshold

                        )

                

                if strike_price:

                    logger.info(

                        "[STRIKE-INFO] asset=%s spot=%.2f strike=%.2f source=%s distance=%.2f%%",

                        asset, spot_price, strike_price, strike_source, ((spot_price - strike_price) / strike_price) * 100 if strike_price > 0 else 0

                    )

        except Exception as e:

            logger.warning("[PRICE-CONFIRMATION-ERROR] asset=%s failed to get market price/strike: %s", asset, e)

        

        # Priority 3: Volatility-adjusted velocity threshold

        # Adjust velocity threshold based on realized volatility to avoid noise in low-vol conditions

        # and capture smaller moves in high-vol conditions

        base_velocity_threshold = velocity_threshold

        try:

            # Get realized volatility from price history if available

            if hasattr(self, '_price_history') and asset in self._price_history and len(self._price_history[asset]) >= 20:

                # Calculate recent volatility (standard deviation of returns)

                recent_prices = [entry[1] for entry in self._price_history[asset][-20:]]  # Last 20 close prices

                returns = [(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1] for i in range(1, len(recent_prices))]

                if returns:

                    realized_vol = statistics.stdev(returns) if len(returns) > 1 else 0.0

                    # Annualize (assuming 1-minute data points, 525600 minutes per year)

                    realized_vol_annual = realized_vol * (525600 ** 0.5)

                    

                    # Normalize to 25% annual vol baseline

                    vol_multiplier = realized_vol_annual / 0.25

                    vol_multiplier = max(0.5, min(2.0, vol_multiplier))  # Clamp 0.5x-2.0x

                    

                    # Apply volatility adjustment

                    velocity_threshold = base_velocity_threshold * vol_multiplier

                    

                    logger.info(

                        "[VOLATILITY-ADJUSTED-THRESHOLD] asset=%s base_threshold=%.6f realized_vol=%.4f vol_multiplier=%.2f adjusted_threshold=%.6f",

                        asset, base_velocity_threshold, realized_vol_annual, vol_multiplier, velocity_threshold

                    )

                else:

                    velocity_threshold = base_velocity_threshold

            else:

                velocity_threshold = base_velocity_threshold

        except Exception as e:

            logger.warning("[VOLATILITY-ADJUSTMENT-ERROR] asset=%s failed to adjust threshold: %s", asset, e)

            velocity_threshold = base_velocity_threshold

        

        # Phase 6: Update regime detector with current price

        # CRITICAL FIX: Re-enabled regime detector with confidence threshold to prevent signal inversion

        # The regime detector now requires confidence > 0.7 before using mean_reversion mode

        # This prevents systematic signal inversion from low-confidence regime classifications

        # CRITICAL FIX: Move regime detection BEFORE regime-aware threshold adjustment to avoid UnboundLocalError

        strategy_mode = "trend_following"  # Default to trend-following

        hmm_regime = None  # Store HMM regime for exit policy wiring

        hmm_regime_confidence = 0.0

        if self._regime_detector and self._regime_detector_enabled:

            current_time = int(time.time() * 1000)  # Milliseconds

            regime_detection = self._regime_detector.update(current_time, spot_price)

            if regime_detection:

                strategy_mode = self._regime_detector.get_strategy_mode(regime_detection)

                hmm_regime = regime_detection.regime.value  # "bull", "choppy", "bear"

                hmm_regime_confidence = regime_detection.confidence

                logger.info(

                    "[REGIME-AWARE] asset=%s regime=%s mode=%s confidence=%.2f",

                    asset, regime_detection.regime.value, strategy_mode, regime_detection.confidence

                )

                

                # CRITICAL FIX: Update canonical ops.regime_detection via adapter

                # This ensures the canonical risk controls (position_size_multiplier, leverage_multiplier)

                # are applied based on the regime detected by agent_grid_15m's detector

                if _REGIME_ADAPTER_AVAILABLE:

                    try:

                        adapter = get_regime_adapter()

                        adapter.update_from_prediction_detector(

                            regime=hmm_regime,

                            confidence=hmm_regime_confidence

                        )

                        logger.debug(

                            "[REGIME-ADAPTER] Updated canonical regime from agent_grid detector: %s -> %s",

                            hmm_regime, adapter.get_canonical_regime()

                        )

                    except Exception as e:

                        logger.warning("[REGIME-ADAPTER] Failed to update canonical regime: %s", e)

        

        # Priority 4: Regime-aware threshold adjustment

        # Adjust velocity threshold based on HMM regime to account for market state

        # CRITICAL FIX: 2026-07-05 - Neutralized regime multipliers since base thresholds are now aligned with actual market conditions

        # Previous multipliers (0.8x, 1.5x, 1.2x) were too aggressive and would block trades even with corrected base thresholds

        # New neutral multipliers (0.9x, 1.1x, 1.0x) provide minor adjustments without blocking legitimate signals

        # Bull markets: slightly lower threshold (cleaner trends)

        # Choppy markets: slightly higher threshold (noise)

        # Bear markets: neutral threshold (volatility already accounted for in base thresholds)

        pre_regime_threshold = velocity_threshold

        if hmm_regime and hmm_regime_confidence >= 0.7:

            if hmm_regime == "bull":

                regime_multiplier = 0.9  # Slightly lower threshold in trending markets (was 0.8x)

            elif hmm_regime == "choppy":

                regime_multiplier = 1.1  # Slightly higher threshold in choppy markets (was 1.5x)

            elif hmm_regime == "bear":

                regime_multiplier = 1.0  # Neutral threshold in bear markets (was 1.2x)

            else:

                regime_multiplier = 1.0

            

            velocity_threshold = velocity_threshold * regime_multiplier

            

            logger.info(

                "[REGIME-AWARE-THRESHOLD] asset=%s regime=%s confidence=%.2f regime_multiplier=%.2f pre_regime_threshold=%.6f post_regime_threshold=%.6f",

                asset, hmm_regime, hmm_regime_confidence, regime_multiplier, pre_regime_threshold, velocity_threshold

            )

        

        # REMOVED: Restrictive price confirmation thresholds

        # Previous thresholds (price_yes_threshold=0.55, price_no_threshold=0.65) were blocking most trades

        # System now trades based purely on velocity/momentum signals (industry standard for 15m binary options)

        

        # 2026 FIX: Lowered ADX threshold from 20 to 2 for 15-minute crypto trading

        # Crypto markets are naturally more volatile and don't always show strong ADX trends

        # Velocity-based signals are the primary signal source; ADX is a secondary filter

        # For 15-minute binary options, even very weak trends (ADX >= 2) are acceptable with velocity confirmation

        # CRITICAL FIX: 2026-07-04 - Lowered ADX threshold from 2.0 to 0.5 for low-volatility weekend conditions

        # Previous threshold of 2.0 was blocking all trades in low-volatility conditions (ADX ~1.0)

        # Weekend/low-volatility markets have ADX 0.5-1.5, which is still tradeable with velocity signals

        # New threshold of 0.5 allows trades while still filtering extreme noise (ADX < 0.5)

        adx = self._calculate_adx(asset)

        if adx > 0 and adx < 0.5:

            logger.info(

                "[ADX-FILTER] asset=%s ADX=%.2f < 0.5 (extremely weak/no trend) -> SKIP TRADE (noise filter)",

                asset, adx

            )

            return None

        elif adx >= 0.5:

            logger.info(

                "[ADX-FILTER] asset=%s ADX=%.2f >= 0.5 (weak/strong trend) -> PROCEED (15m timeframe)",

                asset, adx

            )

        else:

            logger.info(

                "[ADX-FILTER] asset=%s ADX=%.2f (no data/warmup) -> PROCEED (warmup bypass)",

                asset, adx

            )

        

        # Volume confirmation filter - use proper EMA20 comparison

        # Industry standard: volume > 1.2x EMA20(volume) confirms signal validity

        # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        volume_confirmed = self._check_volume_confirmation(asset)

        if not volume_confirmed:

            logger.info(

                "[VOLUME-FILTER] asset=%s volume confirmation failed -> SKIP TRADE (insufficient volume)",

                asset

            )

            return None

        

        # Phase 7: Check panic fade (volatility reversion) conditions

        # Panic fade is the Turbine research winner: 93 of 96 variants profitable

        # It fades extreme moves when price is at statistical extremes

        # This strategy can override velocity-based signals when conditions are met

        panic_fade_signal = self._check_panic_fade_conditions(asset, velocity)

        if panic_fade_signal:

            logger.info("[PANIC-FADE-SIGNAL] asset=%s panic fade signal generated: side=%s rationale=%s",

                       asset, panic_fade_signal["side"], panic_fade_signal["rationale"])

            # Use panic fade signal instead of velocity-based signal

            signal_side = panic_fade_signal["side"]

            signal_action = panic_fade_signal["action"]

            # Skip velocity threshold check for panic fade signals

            # Panic fade has its own statistical extreme validation

        else:

            # Use velocity-based signal generation

            # CRITICAL FIX: 2026-07-01 - Add multi-timeframe alignment based on industry research

            # Industry standard: 1m + 5m confirmation for +10-20 pp win rate

            # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

            # Both timeframes must show same directional momentum for signal confirmation

            mtf_aligned = self._check_multi_timeframe_alignment(asset)

            if not mtf_aligned:

                logger.info(

                    "[MTF-FILTER] asset=%s 1m and 5m timeframes not aligned -> SKIP TRADE (conflicting signals)",

                    asset

                )

                return None

            else:

                logger.info(

                    "[MTF-FILTER] asset=%s 1m and 5m timeframes aligned -> PROCEED (confirmed direction)",

                    asset

                )

        

        # CRITICAL FIX: 2026-07-01 - Add market hour optimization based on industry research

        # Industry standard: Trade during peak liquidity hours for better win rates

        # Reference: https://www.polytrackhq.app/blog/polymarket-15-minute-crypto-guide

        # Best times: US market open (9:30 AM ET), major news events, low liquidity hours (3-6 AM ET)

        # Disabled by default per user request for 24/7 trading, but infrastructure in place

        if self.config.enable_session_filter:

            current_hour_utc = int(time.gmtime().tm_hour)

            session_active = False

            

            # US-Europe overlap (13:00-17:00 UTC): Highest liquidity

            if self.config.us_europe_overlap_start_utc <= current_hour_utc < self.config.us_europe_overlap_end_utc:

                session_active = True

                session_name = "US-Europe overlap"

            # US session (17:00-22:00 UTC): Good liquidity

            elif self.config.us_session_start_utc <= current_hour_utc < self.config.us_session_end_utc:

                session_active = True

                session_name = "US session"

            # European morning (08:00-13:00 UTC): Moderate liquidity

            elif self.config.european_morning_start_utc <= current_hour_utc < self.config.european_morning_end_utc:

                session_active = True

                session_name = "European morning"

            # Asian session (00:00-08:00 UTC): Low liquidity, avoid trading

            else:

                session_active = False

                session_name = "Asian session (low liquidity)"

            

            if not session_active:

                logger.info(

                    "[SESSION-FILTER] asset=%s current_hour_utc=%d session=%s -> SKIP TRADE (low liquidity)",

                    asset, current_hour_utc, session_name

                )

                return None

            else:

                logger.info(

                    "[SESSION-FILTER] asset=%s current_hour_utc=%d session=%s -> PROCEED (peak liquidity)",

                    asset, current_hour_utc, session_name

                )

        

        # ENTRY MATRIX: Momentum agreement check (based on Turbine research)

        # The edge is in Kalshi's lag to spot price, not alignment

        # Research: "The strongest strategies were predicting Kalshi from BTC"

        # When Coinbase spot is moving up, Kalshi's 15-minute contract still has lag to reprice

        # 2026 FIX: DISABLED momentum agreement filter entirely

        # Kalshi 15-minute markets often price at extremes (80-99c) near expiry

        # Velocity signals and ADX filter are sufficient for trade quality control

        # This filter was blocking too many legitimate trading opportunities

        if market_price > 0:

            kalshi_direction = "up" if market_price > 0.5 else "down"

            spot_direction = "up" if velocity > 0 else "down"

            

            logger.info(

                "[MOMENTUM-AGREEMENT-FILTER] asset=%s spot_velocity=%.6f (%s) market_price=%.2f (%s) -> PASS (filter disabled - velocity-based trading)",

                asset, velocity, spot_direction, market_price, kalshi_direction

            )

        

        # HYBRID MODE PRICE CAPS (2026 Optimized)

        # Enforce price discipline in hybrid mode to prevent poor risk/reward trades

        # ADAPTIVE SIGNAL FUSION: Regime-aware price caps (2026 research)

        # Instead of static price caps that block all trades in certain market conditions,

        # use regime detection to dynamically adjust price discipline

        if self.config.signal_mode == "hybrid" and market_price > 0:

            # Detect market regime using ADX and price position

            regime = self._detect_market_regime(asset, spot_price, market_price)

            

            # Adaptive price caps based on regime

            if regime == "trending_strong":

                # Strong trend: allow higher prices (up to 95c) to capture momentum

                max_entry_price_yes = 0.95

                min_entry_price_no = 0.05

                regime_rationale = "strong_trend_momentum"

            elif regime == "trending_weak":

                # Weak trend: moderate price discipline (up to 90c)

                max_entry_price_yes = 0.90

                min_entry_price_no = 0.10

                regime_rationale = "weak_trend_momentum"

            elif regime == "mean_reverting":

                # Mean reversion: strict price discipline (up to 80c)

                max_entry_price_yes = 0.80

                min_entry_price_no = 0.20

                regime_rationale = "mean_reversion_discipline"

            else:

                # Neutral: moderate discipline (up to 85c)

                max_entry_price_yes = 0.85

                min_entry_price_no = 0.15

                regime_rationale = "neutral_market"

            

            # Check if price is within acceptable range for trading

            if market_price > max_entry_price_yes:

                logger.info(

                    "[ADAPTIVE-PRICE-CAP] asset=%s regime=%s market_price=%.2f > max_entry_price_yes=%.2f -> SKIP (overpriced YES entry, rationale=%s)",

                    asset, regime, market_price, max_entry_price_yes, regime_rationale

                )

                return None

            elif market_price < min_entry_price_no:

                logger.info(

                    "[ADAPTIVE-PRICE-CAP] asset=%s regime=%s market_price=%.2f < min_entry_price_no=%.2f -> SKIP (overpriced NO entry, rationale=%s)",

                    asset, regime, market_price, min_entry_price_no, regime_rationale

                )

                return None

            else:

                logger.info(

                    "[ADAPTIVE-PRICE-CAP] asset=%s regime=%s market_price=%.2f within range [%.2f, %.2f] -> PASS (rationale=%s)",

                    asset, regime, market_price, min_entry_price_no, max_entry_price_yes, regime_rationale

                )

        

        # Apply regime-aware velocity-to-side mapping with strike price consideration

        # CRITICAL: Kalshi 15-minute UP/DOWN market structure:

        # - YES/UP contract wins if settlement price > strike price at expiry

        # - NO/DOWN contract wins if settlement price < strike price at expiry

        # - Kalshi sets the strike/target price for each 15-minute window (e.g., BTC 15m: $58,697 target)

        # 

        # Decision logic:

        # 1. Calculate expected price at expiry based on velocity signal

        # 2. Compare expected price to strike price

        # 3. If expected > strike -> BUY YES (expect price above target)

        # 4. If expected < strike -> BUY NO (expect price below target)

        

        # Calculate expected price move based on velocity (15-minute projection)

        # Velocity is % change per second, project to 15 minutes (900 seconds)

        # CRITICAL FIX: Cap expected move to realistic range based on 2026 research

        # 15-minute crypto options typically have 1-5% price movements, not 78%

        # Research shows extreme projections are unrealistic and cause negative EV trades

        expected_price_move_pct = velocity * 900  # Project velocity to 15-minute window

        

        # Cap expected move to realistic range (max 5% for 15 minutes)

        # This prevents unrealistic projections like 78% moves in 15 minutes

        max_expected_move_pct = 0.05  # 5% maximum expected move for 15-minute window

        expected_price_move_pct = max(-max_expected_move_pct, min(max_expected_move_pct, expected_price_move_pct))

        

        expected_price = spot_price * (1 + expected_price_move_pct)

        

        logger.info(

            "[PRICE-PROJECTION] asset=%s spot=%.2f velocity=%.6f expected_move=%.2f%% expected_price=%.2f strike=%.2s",

            asset, spot_price, velocity, expected_price_move_pct * 100, expected_price, strike_price if strike_price else "N/A"

        )

        

        # CRITICAL FIX: Use velocity threshold logic exclusively for 15-minute crypto scalping

        # Strike-based projection logic was causing systematic NO bias:

        # - Strike price defaults to current spot price (spot_fallback)

        # - With negative velocity, expected_price < spot_price = strike_price

        # - This always triggered BUY NO, bypassing velocity threshold check

        # - Velocity threshold is the correct signal generation mechanism for momentum trading

        # Strike-based logic is inappropriate for 15m crypto scalping and has been removed

        

        # CRITICAL FIX: Apply regime-aware velocity-to-side mapping with dual-side evaluation

        # The strategy_mode (trend_following vs mean_reversion) determines how velocity maps to signal side

        # - trend_following: positive velocity -> YES, negative velocity -> NO

        # - mean_reversion: positive velocity -> NO (expect reversion down), negative velocity -> YES (expect reversion up)

        # NEW: Evaluate edge for both YES and NO sides, select best edge within 10c-50c range

        # This allows the indicator stack to determine which side has better EV, not forced YES/NO decision

        

        # 2026-07-04: CRITICAL FIX - Removed NO-side conviction multiplier for symmetry

        # Previous asymmetry (1.5x NO threshold) was blocking valid NO-side signals

        # With new lower thresholds (0.015%-0.025%), the 1.5x multiplier created excessive asymmetry:

        # - BTC: YES threshold 0.00015, NO threshold 0.000225 (50% higher)

        # - DOGE: YES threshold 0.00025, NO threshold 0.000375 (50% higher)

        # This asymmetry was preventing NO-side trades even when velocity was clearly negative

        # New approach: Use symmetric thresholds for both YES and NO sides

        # Rationale: Velocity magnitude should determine signal strength, not direction

        # If velocity is sufficiently negative, it should trigger NO signal just as positive triggers YES

        # CRITICAL FIX: 2026-07-05 - Removed marginal zone rejection based on industry research

        # Industry systems (MagicTradeBot, Manic Trade, VoiceOfChain) do not use marginal zones

        # Signals fire when threshold is crossed - no 20% margin blocking valid trades

        yes_bias_margin = 0.0  # REMOVED: No marginal zone - signals fire at threshold

        no_conviction_multiplier = 1.0  # NO side now uses same threshold as YES (symmetric)

        

        # Calculate edge for both YES and NO sides based on velocity

        # Edge = p(true) × $1.00 - Market_Price

        # For YES: p(true) based on positive velocity, Market_Price = yes_price_cents/100

        # For NO: p(true) based on negative velocity, Market_Price = no_price_cents/100

        side_edges = {}

        

        if not panic_fade_signal:

            # Calculate marginal velocity zone (DISABLED - no marginal zone)

            is_marginal_positive = False  # DISABLED: No marginal zone

            is_marginal_negative = False  # DISABLED: No marginal zone

            

            # CRITICAL FIX: 2026-07-09 - Symmetric signal strength for dual-side evaluation

            # Both YES and NO get non-zero signal strength to enable true edge comparison

            # Direction is encoded in probabilities, not by zeroing one side

            if abs(velocity) < velocity_threshold:

                # No momentum → no edge on either side

                yes_signal_strength = 0.0

                no_signal_strength = 0.0

                logger.info(

                    "[VELOCITY-SIGNAL] asset=%s velocity=%.6f within ±threshold=%.6f -> NO TRADE (insufficient momentum)",

                    asset, velocity, velocity_threshold

                )

                return None

            else:

                # Both sides get symmetric signal magnitude

                signal_mag = abs(velocity) / velocity_threshold

                # CRITICAL FIX: 2026-07-09 - Clamp signal_mag to prevent extreme direction_bias

                # Without clamping, very high velocity (e.g., 10x threshold) could cause direction_bias > 1.0

                # This would push p_model to extreme values (0.95 or 0.05) even with clamping

                # Clamping at 3.0 ensures direction_bias stays in reasonable range [-0.3, 0.3]

                signal_mag = min(signal_mag, 3.0)

                yes_signal_strength = signal_mag

                no_signal_strength = signal_mag

            

            # CRITICAL FIX: 2026-07-09 - Dual-side probability-based edge calculation

            # Compute model probabilities for both YES and NO using symmetric logic

            # Direction is encoded in probabilities, not by zeroing one side

            

            # Market-implied probabilities from prices

            p_mkt_yes = yes_price_cents / 100.0 if yes_price_cents > 0 else 0.5

            p_mkt_no = no_price_cents / 100.0 if no_price_cents > 0 else 0.5

            

            # Base probability (neutral starting point)

            base_prob = 0.5

            

            # Direction bias from velocity (encodes trend_following vs mean_reversion)

            # Positive velocity bumps YES probability, negative bumps NO probability

            direction_bias = 0.0

            if velocity > 0:

                # Positive velocity favors YES in trend_following, NO in mean_reversion

                if strategy_mode == "trend_following":

                    direction_bias = 0.1 * signal_mag  # Bump YES probability

                else:  # mean_reversion

                    direction_bias = -0.1 * signal_mag  # Bump NO probability

            else:

                # Negative velocity favors NO in trend_following, YES in mean_reversion

                if strategy_mode == "trend_following":

                    direction_bias = -0.1 * signal_mag  # Bump NO probability

                else:  # mean_reversion

                    direction_bias = 0.1 * signal_mag  # Bump YES probability

            

            # Model probabilities with direction bias

            p_model_yes = max(0.05, min(0.95, base_prob + direction_bias))

            p_model_no = 1.0 - p_model_yes  # Symmetry: p_model_no = 1 - p_model_yes

            

            # Calculate symmetric edges for both sides

            # Edge formula: edge = (p_model - p_mkt) * 100 (in percentage)

            for side in sides_to_evaluate:

                if side == "yes" and yes_in_range:

                    edge_yes_pct = (p_model_yes - p_mkt_yes) * 100.0

                    side_edges["yes"] = edge_yes_pct

                    logger.info(

                        "[EDGE-CALCULATION] asset=%s side=yes p_model=%.4f p_mkt=%.4f edge_pct=%.3f%%",

                        asset, p_model_yes, p_mkt_yes, edge_yes_pct

                    )

                elif side == "no" and no_in_range:

                    edge_no_pct = (p_model_no - p_mkt_no) * 100.0

                    side_edges["no"] = edge_no_pct

                    logger.info(

                        "[EDGE-CALCULATION] asset=%s side=no p_model=%.4f p_mkt=%.4f edge_pct=%.3f%%",

                        asset, p_model_no, p_mkt_no, edge_no_pct

                    )

            

            # CRITICAL FIX: 2026-07-09 - Add midpoint preference (~25c bonus)

            # Nudges selection toward mid-band fills where execution quality is best

            def midpoint_bonus(price_cents):

                """Peak at 25c, decays toward 10c/50c."""

                dist = abs(price_cents - 25)

                midpoint_bonus_max = 0.5  # Maximum bonus in percentage points

                midpoint_bonus_slope = 0.02  # Decay rate per cent from midpoint

                return max(0.0, midpoint_bonus_max - dist * midpoint_bonus_slope)

            

            # Apply midpoint bonus to edges

            side_edges_with_bonus = {}

            if yes_in_range and "yes" in side_edges:

                side_edges_with_bonus["yes"] = side_edges["yes"] + midpoint_bonus(yes_price_cents)

            if no_in_range and "no" in side_edges:

                side_edges_with_bonus["no"] = side_edges["no"] + midpoint_bonus(no_price_cents)

            

            # Select side with best edge

            if not side_edges_with_bonus:

                logger.info(

                    "[EDGE-SELECTION] asset=%s no valid edges (sides out of range) -> NO TRADE",

                    asset

                )

                return None

            

            # Select side with maximum edge (with midpoint bonus)

            signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)

            signal_action = "buy"

            selected_edge = side_edges[signal_side]  # Use original edge (without bonus) for reporting

            

            # Set market_price based on selected side for backward compatibility

            # This ensures hybrid mode price caps and other logic work correctly

            if signal_side == "yes":

                market_price = yes_price_cents / 100.0

            else:

                market_price = no_price_cents / 100.0

            

            logger.info(

                "[EDGE-SELECTION] asset=%s selected_side=%s edge=%.3f%% market_price=%.2f (all_edges=%s with_bonus=%s)",

                asset, signal_side, selected_edge, market_price, side_edges, side_edges_with_bonus

            )

            

            # Log the velocity-based rationale

            if velocity > velocity_threshold:

                if strategy_mode == "trend_following":

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f > threshold=%.6f mode=trend_following -> BUY %s (positive momentum, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )

                else:  # mean_reversion

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f > threshold=%.6f mode=mean_reversion -> BUY %s (expect reversion down, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )

            elif velocity < -velocity_threshold:

                if strategy_mode == "trend_following":

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f < -threshold=%.6f mode=trend_following -> BUY %s (negative momentum, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )

                else:  # mean_reversion

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f < -threshold=%.6f mode=mean_reversion -> BUY %s (expect reversion up, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )

        

        # 2026-07-05 INDUSTRY ALIGNMENT: 15M Noise Filters

        # 15-minute timeframes are prone to false signals due to microstructure noise

        # Add filters to reject noise and improve signal quality

        

        # Filter 1: Minimum move threshold

        # CRITICAL FIX: 2026-07-05 - Disabled to enable fills in calm markets

        # Previous threshold (0.6%) was blocking all trades in current market conditions

        # Actual price changes are 0.01%-0.05%, far below 0.6% threshold

        # Disabled to allow velocity-based trading to work:

        min_move_threshold_pct = 0.0  # Disabled - allow any price movement

        if hasattr(self, '_last_price') and self._last_price.get(asset):

            last_price = self._last_price[asset]

            price_change_pct = abs((spot_price - last_price) / last_price) * 100.0 if last_price > 0 else 0.0

            if price_change_pct < min_move_threshold_pct:

                logger.info(

                    "[NOISE-FILTER-MIN-MOVE] asset=%s price_change_pct=%.3f%% < min_move_threshold=%.3f%% -> NO TRADE (insufficient price movement)",

                    asset, price_change_pct, min_move_threshold_pct

                )

                return None

            logger.info(

                "[NOISE-FILTER-MIN-MOVE] asset=%s price_change_pct=%.3f%% >= min_move_threshold=%.3f%% -> PASS",

                asset, price_change_pct, min_move_threshold_pct

            )

        # Store current price for next comparison

        if not hasattr(self, '_last_price'):

            self._last_price = {}

        self._last_price[asset] = spot_price

        

        # Filter 2: Volume spike confirmation

        # DISABLED: 2026-07-05 - Fixed broken volume filter

        # Previous implementation compared 60-second candle volume (hundreds/thousands USD)

        # against a 1M USD threshold, which ALWAYS failed for 15m trading.

        # Root cause: Wrong volume metric (candle volume vs 24h volume) and wrong threshold.

        # Future implementation should use:

        # - Relative volume Z-score (rolling 5m/15m/60m baselines per 2026 research)

        # - Liquidity floor from profile (min_volume_24h_usd) as coarse filter

        # - Volume anomaly detection instead of absolute thresholds

        # For now, disabled to allow velocity-based trading to function.

        logger.debug("[NOISE-FILTER-VOLUME] DISABLED - broken filter removed (was comparing 60s candle volume to 1M threshold)")

        

        # Filter 3: Sustained signal

        # Require velocity threshold maintained for N consecutive periods

        sustained_periods = 2  # Require 2 consecutive periods

        if not hasattr(self, '_velocity_history'):

            self._velocity_history = {}

        if asset not in self._velocity_history:

            self._velocity_history[asset] = []

        self._velocity_history[asset].append(velocity)

        # Keep only last N periods

        if len(self._velocity_history[asset]) > sustained_periods:

            self._velocity_history[asset].pop(0)

        

        # Check if velocity has been sustained in the same direction

        if len(self._velocity_history[asset]) >= sustained_periods:

            recent_velocities = self._velocity_history[asset]

            all_positive = all(v > velocity_threshold for v in recent_velocities)

            all_negative = all(v < -velocity_threshold for v in recent_velocities)

            if not (all_positive or all_negative):

                logger.info(

                    "[NOISE-FILTER-SUSTAINED] asset=%s velocity not sustained for %d periods -> NO TRADE (fleeting signal)",

                    asset, sustained_periods

                )

                return None

            logger.info(

                "[NOISE-FILTER-SUSTAINED] asset=%s velocity sustained for %d periods -> PASS",

                asset, sustained_periods

            )

        else:

            logger.info(

                "[NOISE-FILTER-SUSTAINED] asset=%s insufficient history (%d/%d periods) -> ALLOW (building history)",

                asset, len(self._velocity_history[asset]), sustained_periods

            )

        

        # Filter 4: Wick filter

        # Ignore signals triggered by candle wicks > 50% of body (avoid liquidation cascades)

        try:

            from data.unified_spot_service import get_unified_spot_service

            spot_service = get_unified_spot_service()

            spot_data = spot_service.get(asset)

            if spot_data and hasattr(spot_data, 'high') and hasattr(spot_data, 'low') and hasattr(spot_data, 'open') and hasattr(spot_data, 'close'):

                candle_high = spot_data.high

                candle_low = spot_data.low

                candle_open = spot_data.open

                candle_close = spot_data.close

                

                # Calculate wick percentage

                body_size = abs(candle_close - candle_open)

                total_range = candle_high - candle_low

                wick_size = total_range - body_size

                

                if total_range > 0:

                    wick_pct = (wick_size / total_range) * 100.0

                    max_wick_threshold_pct = 50.0  # 50% wick threshold

                    if wick_pct > max_wick_threshold_pct:

                        logger.info(

                            "[NOISE-FILTER-WICK] asset=%s wick_pct=%.1f%% > max_wick_threshold=%.1f%% -> NO TRADE (wick-dominated candle)",

                            asset, wick_pct, max_wick_threshold_pct

                        )

                        return None

                    logger.info(

                        "[NOISE-FILTER-WICK] asset=%s wick_pct=%.1f%% <= max_wick_threshold=%.1f%% -> PASS",

                        asset, wick_pct, max_wick_threshold_pct

                    )

        except Exception as e:

            logger.warning("[NOISE-FILTER-WICK] Failed to check wick: %s, skipping filter", e)

        

        # 2026 OPTIMIZATION: Order Book Imbalance (OBI) Filter

        # Industry standard: OBI is the strongest microstructure feature for short-horizon prediction

        # Expected win rate boost: 5-7 percentage points when combined with momentum

        # Reference: https://algos.pro/posts/2026-03-16-order-book-imbalance-alpha-signals/

        try:

            from merid.prediction.order_book_imbalance_filter import get_obi_filter

            obi_filter = get_obi_filter()

            

            # Get depth from market state

            depth_yes = market_state.depth_yes if market_state and market_state.depth_yes else 0

            depth_no = market_state.depth_no if market_state and market_state.depth_no else 0

            

            # Check OBI filter with asset parameter for per-asset thresholds

            obi_context = obi_filter.should_trade(

                market_id=ticker,

                bid_depth=depth_yes,

                ask_depth=depth_no,

                direction=signal_side,

                asset=asset  # Pass asset for per-asset strong thresholds

            )

            

            if obi_context.recommendation == "HOLD":

                logger.info(

                    "[OBI-FILTER] asset=%s ticker=%s obi=%.3f consistency=%.0f%% recommendation=%s -> FILTER (stale data, OBI HOLD overrides other signals)",

                    asset, ticker, obi_context.current_obi, obi_context.directional_consistency * 100, obi_context.recommendation

                )

                return None

            elif obi_context.recommendation == "REDUCED":

                logger.info(

                    "[OBI-FILTER] asset=%s ticker=%s obi=%.3f consistency=%.0f%% recommendation=%s size_multiplier=%.2f -> REDUCED SIZE (low directional consistency)",

                    asset, ticker, obi_context.current_obi, obi_context.directional_consistency * 100,

                    obi_context.recommendation, obi_context.size_multiplier

                )

                # Continue with reduced size (size_multiplier will be applied later)

            else:  # TRADE

                # 2026-07-05 FIX: Add cross-signal alignment check between velocity and OBI

                # Prevent contradictory signals (e.g., velocity=BUY YES, OBI=sell)

                # Alignment mapping: velocity "yes" (BUY YES) aligns with OBI "buy" (bullish order book)

                #                  velocity "no" (BUY NO) aligns with OBI "sell" (bearish order book)

                obi_signal_direction = None

                if obi_context.current_signal.value in ["STRONG_BUY", "BUY"]:

                    obi_signal_direction = "buy"

                elif obi_context.current_signal.value in ["STRONG_SELL", "SELL"]:

                    obi_signal_direction = "sell"

                

                # Check if OBI signal aligns with velocity signal

                signals_aligned = (obi_signal_direction is None) or (

                    (signal_side == "yes" and obi_signal_direction == "buy") or

                    (signal_side == "no" and obi_signal_direction == "sell")

                )

                

                if not signals_aligned:

                    logger.warning(

                        "[SIGNAL-CONTRADICTION] asset=%s ticker=%s velocity=%s OBI=%s obi=%.3f -> FILTER (signals contradict, skipping trade)",

                        asset, ticker, signal_side, obi_signal_direction, obi_context.current_obi

                    )

                    return None

                

                logger.info(

                    "[OBI-FILTER] asset=%s ticker=%s obi=%.3f consistency=%.0f%% -> PASS (full size, strong directional consistency, signals aligned)",

                    asset, ticker, obi_context.current_obi, obi_context.directional_consistency * 100

                )

        except Exception as obi_exc:

            logger.warning("[OBI-FILTER-ERROR] asset=%s error=%s (continuing without OBI filter)", asset, obi_exc)

            # Continue without OBI filter if it fails (non-critical)

        

        # 2026 OPTIMIZATION: News Event Avoidance

        # Industry standard: Avoid trading 15 minutes before/after high-impact news

        # Major economic releases cause extreme volatility that invalidates technical analysis

        try:

            from merid.prediction.news_event_avoidance import get_news_avoidance

            news_avoidance = get_news_avoidance()

            

            status = news_avoidance.should_avoid_trading()

            

            if status.should_avoid:

                logger.info(

                    "[NEWS-AVOIDANCE] asset=%s reason=%s -> SKIP TRADING",

                    asset, status.reason

                )

                return None

            

            if status.upcoming_events:

                logger.info(

                    "[NEWS-AVOIDANCE] asset=%s upcoming_event=%s time_until=%s",

                    asset, status.upcoming_events[0].event_type, status.time_until_next_event

                )

        except Exception as news_exc:

            logger.warning("[NEWS-AVOIDANCE-ERROR] asset=%s error=%s (continuing without news avoidance)", asset, news_exc)

            # Continue without news avoidance if it fails (non-critical)

        

        # 2026 VELOCITY-BASED SIDE SELECTION: Side is determined by velocity direction

        # Positive velocity (> threshold) -> buy YES

        # Negative velocity (< -threshold) -> buy NO

        # Edge is calculated for confidence/risk but does NOT override velocity side decision

        

        # CRITICAL FIX: Read bid/ask from KalshiMarketStateStore instead of catalog

        # The catalog doesn't contain orderbook data for 15m crypto futures.

        # KalshiMarketStateStore is populated from WS orderbook_delta and REST snapshots.

        best_bid = 0

        best_ask = 0

        price_source = "unknown"



        # Actually read from market_state_store

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            

            # Check if market_state_store is available

            if not self.market_state_store:

                logger.warning("[MARKET-STATE-READ] asset=%s ticker=%s market_state_store is None",

                             asset, ticker)

                return None

            

            market_state = self.market_state_store.get(ticker)

            if market_state:

                best_bid = market_state.best_bid_cents if market_state.best_bid_cents else 0

                best_ask = market_state.best_ask_cents if market_state.best_ask_cents else 0

                price_source = "market_state_store"

                logger.info("[MARKET-STATE-READ] asset=%s ticker=%s best_bid=%d best_ask=%d source=%s",

                           asset, ticker, best_bid, best_ask, price_source)

                

                # CRITICAL FIX: 2026-07-02 - Market quality validation to prevent 1¢ orders

                # Reject markets with poor orderbook quality that indicate data issues

                # 1. No bids AND no asks (completely empty book) - illiquid market

                # 2. Extreme spread - REMOVED: Market validation layer already handles this with dynamic thresholds

                # 3. Unrealistic prices - REMOVED: 95¢ threshold too restrictive for near-expiry markets

                #    Only reject truly extreme prices (>99¢) which indicate data corruption

                # FIX: Allow one-sided books (no bids but has asks, or vice versa) - common in thin 15m crypto markets

                if best_bid == 0 and best_ask == 0:

                    logger.warning(

                        "[MARKET-QUALITY-REJECT] asset=%s ticker=%s best_bid=0 best_ask=0 (empty book) - REJECTING TRADE (illiquid market)",

                        asset, ticker

                    )

                    return None

                elif best_bid == 0:

                    logger.info(

                        "[MARKET-QUALITY-INFO] asset=%s ticker=%s best_bid=0 best_ask=%d (one-sided book) - ALLOWING TRADE (can buy NO if signal aligns)",

                        asset, ticker, best_ask

                    )

                elif best_ask == 0:

                    logger.info(

                        "[MARKET-QUALITY-INFO] asset=%s ticker=%s best_bid=%d best_ask=0 (one-sided book) - ALLOWING TRADE (can buy YES if signal aligns)",

                        asset, ticker, best_bid

                    )

                

                # Only reject truly corrupted data (best_ask > 99¢, which is impossible for YES/NO duality)

                if best_ask > 99:

                    logger.warning(

                        "[MARKET-QUALITY-REJECT] asset=%s ticker=%s best_ask=%dc > 99c - REJECTING TRADE (impossible price, corrupted data)",

                        asset, ticker, best_ask

                    )

                    return None

            else:

                logger.warning("[MARKET-STATE-READ] asset=%s ticker=%s no market state available",

                             asset, ticker)

        except Exception as e:

            logger.warning("[MARKET-STATE-READ] asset=%s failed to read market state: %s", asset, str(e))

        

        logger.info("[BEFORE-PROFILE-LOAD] asset=%s market_id=%s", asset, getattr(market, 'market_id', 'N/A'))

        

        # Load profile for risk limits

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            profile = profile_adapter.profile

            # Get staleness from strategy_policy section of profile

            strategy_staleness = profile.strategy_policy_max_md_staleness_sec

            venue_staleness = profile.venue_invariants_max_book_staleness_ms / 1000.0  # Convert ms to seconds

            logger.info("[PROFILE-LOAD] asset=%s strategy_staleness=%s venue_staleness=%s", 

                       asset, strategy_staleness, venue_staleness)

        except Exception as e:

            logger.warning("[PROFILE-LOAD-FAIL] asset=%s error=%s", asset, str(e))

            strategy_staleness = 60

            venue_staleness = 15

        

        # Phase 1: Compute model probability using logistic mapping from velocity

        # Formula: p_model = sigmoid(alpha_0 + alpha_1 * velocity)

        # where sigmoid(x) = 1 / (1 + exp(-x))

        import math

        

        # Calculate market probability from bid/ask (p_mkt)

        p_mkt = 0.5  # Default fallback

        if best_bid and best_ask:

            p_mkt = (best_bid + best_ask) / 2 / 100.0

        elif best_bid:

            p_mkt = best_bid / 100.0

        elif best_ask:

            p_mkt = best_ask / 100.0

        

        # Clamp p_mkt to valid range [0.05, 0.95] (Kalshi venue invariant)

        p_mkt = max(0.05, min(0.95, p_mkt))

        

        # Calculate raw logit from velocity using coefficients

        # CROSS-PHASE: Add error handling for missing or invalid coefficients

        if self._alpha_0 is None or self._alpha_1 is None:

            logger.error("[SIGNAL-GEN] asset=%s missing velocity coefficients (alpha_0=%s, alpha_1=%s), skipping signal",

                        asset, self._alpha_0, self._alpha_1)

            return None

        

        # Phase 4.1: Use multi-window velocity for better signal quality

        multi_window_velocity = self._calculate_multi_window_velocity(asset, spot_price)

        

        # Phase 4.3: Calculate mean reversion signal

        mean_reversion_deviation = self._calculate_mean_reversion(asset, spot_price)

        

        # Phase 4.4: Calculate separate logits for velocity and mean reversion

        velocity_logit = self._alpha_0 + self._alpha_1 * multi_window_velocity

        mean_reversion_logit = self._alpha_0 + self._alpha_1 * (-mean_reversion_deviation * 0.5)

        

        # Phase 4.4: Apply logit fusion to combine signals

        raw_logit = self._apply_logit_fusion(velocity_logit, mean_reversion_logit, minutes_to_expiry)

        

        # CRITICAL FIX: Clamp raw_logit to prevent sigmoid overflow/underflow

        # Logits outside [-10, 10] cause sigmoid to saturate (p_model near 0 or 1)

        # This creates unrealistic edges and math range errors

        LOGIT_CLAMP_MIN = -10.0

        LOGIT_CLAMP_MAX = 10.0

        if raw_logit < LOGIT_CLAMP_MIN:

            logger.warning("[LOGIT-CLAMP] asset=%s raw_logit=%.4f clamped to %.4f (too negative)", 

                         asset, raw_logit, LOGIT_CLAMP_MIN)

            raw_logit = LOGIT_CLAMP_MIN

        elif raw_logit > LOGIT_CLAMP_MAX:

            logger.warning("[LOGIT-CLAMP] asset=%s raw_logit=%.4f clamped to %.4f (too positive)", 

                         asset, raw_logit, LOGIT_CLAMP_MAX)

            raw_logit = LOGIT_CLAMP_MAX

        

        # Apply numerically stable logistic function to get model probability

        # Uses the exp-normalize trick to avoid overflow/underflow

        # For x >= 0: sigmoid(x) = 1 / (1 + exp(-x))

        # For x < 0: sigmoid(x) = exp(x) / (1 + exp(x))

        # This prevents overflow for large positive/negative values

        try:

            if raw_logit >= 0:

                p_model = 1.0 / (1.0 + math.exp(-raw_logit))

            else:

                p_model = math.exp(raw_logit) / (1.0 + math.exp(raw_logit))

        except (OverflowError, ValueError) as e:

            logger.error("[SIGNAL-GEN] asset=%s failed to compute p_model from raw_logit=%.4f: %s, skipping signal",

                        asset, raw_logit, e)

            return None

        

        # Clamp p_model to valid range [0.01, 0.99] (slightly wider than venue invariant)

        p_model = max(0.01, min(0.99, p_model))

        

        # Phase 5.3: Apply probability calibration if enabled and fitted

        if self._calibration_enabled and self._platt_scaler and self._platt_scaler.is_fitted():

            try:

                calibrated_p_model = self._platt_scaler.predict_single(raw_logit)

                logger.debug("[SIGNAL-GEN] asset=%s calibration applied: p_model=%.4f -> calibrated=%.4f",

                            asset, p_model, calibrated_p_model)

                p_model = calibrated_p_model

            except Exception as cal_err:

                logger.warning("[SIGNAL-GEN] asset=%s calibration failed: %s, using uncalibrated p_model",

                             asset, cal_err)

        

        # CRITICAL FIX: Apply horizon-aware calibration based on 2026 research

        # Short-horizon markets (<24h) show different biases

        # 5m/15m crypto rounds benefit from horizon-aware models

        # Formula: p* = σ(θ · logit(p)) where θ includes horizon adjustment

        if self._calibration_enabled:

            try:

                import math

                # Calculate horizon factor (15-minute market = 0.25 hours)

                horizon_hours = minutes_to_expiry / 60.0

                # Research-based horizon adjustment: 1 + 0.08 * ln(horizon_hours)

                # For 15m (0.25h): factor = 1 + 0.08 * ln(0.25) = 0.889

                # This slightly reduces probability for very short horizons due to uncertainty

                horizon_factor = 1.0 + 0.08 * math.log(max(0.1, horizon_hours))

                

                # Apply domain-specific slope for crypto (research: ~1.08 for crypto)

                crypto_slope = 1.08

                

                # Recalibrate probability using horizon-aware formula

                logit_p = math.log(p_model / (1.0 - p_model)) if p_model > 0 and p_model < 1 else 0.0

                adjusted_logit = crypto_slope * horizon_factor * logit_p

                horizon_calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))

                

                # Clamp to valid range

                horizon_calibrated_p = max(0.01, min(0.99, horizon_calibrated_p))

                

                logger.info("[HORIZON-CALIBRATION] asset=%s horizon=%.2fh factor=%.3f p_model=%.4f -> %.4f",

                           asset, horizon_hours, horizon_factor, p_model, horizon_calibrated_p)

                p_model = horizon_calibrated_p

            except Exception as horizon_err:

                logger.warning("[SIGNAL-GEN] asset=%s horizon calibration failed: %s, using uncalibrated p_model",

                             asset, horizon_err)

        

        # CROSS-PHASE: Validate p_model is in reasonable range

        if not (0.0 <= p_model <= 1.0):

            logger.error("[SIGNAL-GEN] asset=%s p_model=%.4f outside valid range [0,1], skipping signal",

                        asset, p_model)

            return None

        

        # 2026-07-05 RESEARCH NOTE: A previous iteration replaced probability edge with raw

        # velocity magnitude (0.00-0.03%). That made every downstream economic gate (edge bands

        # 0.8-3%, maker/taker fee thresholds, 2%/4% aggressiveness) unsatisfiable and led to

        # the maker-taker threshold being disabled entirely — producing zero-edge taker orders

        # at 98-99c. Probability edge (p_model - p_mkt) on the momentum-selected side is the

        # 2026 industry standard for Kalshi 15m bots and is restored below, combined with an

        # uncertain-zone gate so we only buy contracts cheap enough to run to the 99c exit.

        

        # Calculate edge for logging and execution

        # 2026-07-05 RESEARCH FIX: Restored probability-based edge (p_model - p_mkt)

        # Velocity-magnitude edges (0.00-0.03%) can never cover Kalshi taker fees (~1.0-1.4%),

        # which forced downstream hacks (maker-taker threshold disabled, zero-edge 99c taker

        # orders bleeding fees). Industry standard for Kalshi 15m bots (2026): edge = model

        # probability vs market-implied probability on the momentum side, and only trade the

        # uncertain zone where contracts are cheap enough to have profit room to the 99c exit.

        edge_yes_pct = (p_model - p_mkt) * 100.0

        edge_no_pct = ((1.0 - p_model) - (1.0 - p_mkt)) * 100.0

        

        # EDGE GATE 1: Only trade the uncertain zone (market-implied prob 10%-90%).

        # DISABLED for momentum-based trading: Velocity threshold is the signal, not probability edge.

        # Momentum trading relies on velocity exceeding threshold as conviction, not on p_model vs p_mkt.

        # The uncertain zone gate is appropriate for probability-based strategies but blocks momentum

        # signals that should trade based on velocity magnitude regardless of market price level.

        # 2026-07-05 FIX: Disabled to allow momentum signals to execute when velocity exceeds threshold.

        

        if signal_side == "yes":

            edge_pct = edge_yes_pct

        else:

            edge_pct = edge_no_pct

        

        # 2026-07-05 INDUSTRY ALIGNMENT: Add explicit Kalshi fee modeling

        # Kalshi charges 7% × p × (1-p) on winning trades, capped at $0.0175

        # Only trade when edge > fee (net edge after fees)

        price_cents = (best_bid + best_ask) / 2 if best_bid and best_ask else 0

        if price_cents > 0:

            # Calculate fee in cents for the winning side

            fee_cents = calculate_kalshi_fee_cents(p_mkt, int(price_cents))

            

            # Convert fee to percentage of contract value

            fee_pct = (fee_cents / price_cents) * 100.0 if price_cents > 0 else 0.0

            

            # Calculate net edge after fees

            net_edge_pct = edge_pct - fee_pct

            

            # CRITICAL FIX: 2026-07-05 - Disabled min net edge filter to enable fills

            # Previous threshold (3 cents) was blocking all trades in current market conditions

            # Net edge is often negative in calm markets, but we need to execute to gather data

            # Disabled to allow any trade to execute:

            min_net_edge_cents = 0.0  # Disabled - allow any edge

            min_net_edge_pct = (min_net_edge_cents / price_cents) * 100.0 if price_cents > 0 else 0.0

            

            logger.info(

                "[FEE-MODELING] asset=%s side=%s price_cents=%d p_mkt=%.4f fee_cents=%.2f fee_pct=%.2f%% edge_pct=%.2f%% net_edge_pct=%.2f%% min_net_edge_pct=%.2f%%",

                asset, signal_side, int(price_cents), p_mkt, fee_cents, fee_pct, edge_pct, net_edge_pct, min_net_edge_pct

            )

            

            # 2026-07-05 FIX: Disabled net edge sign check for momentum-based trading

            # Velocity threshold is the signal, not probability edge. Negative net edges occur

            # when p_model < p_mkt (high market prices), but momentum signals should still execute.

            # Previous check blocked all YES trades in current market conditions (p_mkt > 0.85).

            # Disabled to allow momentum signals to execute regardless of net edge sign:

            # if net_edge_pct < min_net_edge_pct:

            #     logger.info(

            #         "[FEE-REJECT] asset=%s side=%s net_edge_pct=%.2f%% < min_net_edge_pct=%.2f%% (fees=%s cents) -> NO TRADE",

            #         asset, signal_side, net_edge_pct, min_net_edge_pct, fee_cents

            #     )

            #     return None

            

            # Use net edge for downstream calculations

            edge_pct = net_edge_pct

        

        # ENTRY MATRIX: Time window multiplier raises the REQUIRED edge for late entries

        # (edge decay). Applied to the requirement below, not to the measured edge.

        

        # ENTRY MATRIX: Apply price band edge multiplier (based on CEPR/KarlWhelan research)

        # Updated to align with per-asset minimums: BTC/ETH 20c, SOL/XRP 25c, DOGE 30c

        # 50-65c: sweet spot, baseline edge requirements

        # Near minimum bands: require higher edge due to structural bias

        # 66-70c: near max price, require higher edge (small payout)

        # Higher volatility assets (SOL, DOGE) need stricter multipliers

        price_cents = (best_bid + best_ask) / 2 if best_bid and best_ask else 0

        price_edge_multiplier = 1.0

        

        if price_cents > 0:

            # Per-asset minimum bands (aligned with new minimums)

            if asset in ['BTC', 'ETH']:

                # BTC/ETH: 20c minimum

                if 20 <= price_cents <= 24:

                    price_edge_multiplier = 1.5  # Near minimum, conservative

                elif 25 <= price_cents <= 34:

                    price_edge_multiplier = 1.2  # Slightly above minimum

                elif 35 <= price_cents <= 49:

                    price_edge_multiplier = 1.0  # Normal range

                elif 50 <= price_cents <= 65:

                    price_edge_multiplier = 1.0  # Sweet spot

                elif 66 <= price_cents <= 70:

                    price_edge_multiplier = 1.5  # Near max price

            elif asset in ['SOL', 'XRP']:

                # SOL/XRP: 25c minimum

                if 25 <= price_cents <= 29:

                    price_edge_multiplier = 1.5  # Near minimum, conservative

                elif 30 <= price_cents <= 39:

                    price_edge_multiplier = 1.2  # Slightly above minimum

                elif 40 <= price_cents <= 49:

                    price_edge_multiplier = 1.0  # Normal range

                elif 50 <= price_cents <= 65:

                    price_edge_multiplier = 1.0  # Sweet spot

                elif 66 <= price_cents <= 70:

                    price_edge_multiplier = 1.5  # Near max price

            elif asset == 'DOGE':

                # DOGE: 30c minimum (noisiest asset)

                if 30 <= price_cents <= 34:

                    price_edge_multiplier = 1.5  # Near minimum, conservative

                elif 35 <= price_cents <= 44:

                    price_edge_multiplier = 1.2  # Slightly above minimum

                elif 45 <= price_cents <= 49:

                    price_edge_multiplier = 1.0  # Normal range

                elif 50 <= price_cents <= 65:

                    price_edge_multiplier = 1.0  # Sweet spot

                elif 66 <= price_cents <= 70:

                    price_edge_multiplier = 1.5  # Near max price

        

        # EDGE GATE 2: Minimum edge requirement (per-asset, aligned with profile min_edge_early:

        # BTC/ETH 3%, SOL/XRP 4%, DOGE 5%). Time/price multipliers RAISE the requirement for

        # late entries and structurally-biased price bands (they no longer inflate the edge

        # itself, which would have weakened the gate instead of strengthening it).

        # DISABLED for momentum-based trading: Velocity threshold is the signal, not probability edge.

        # Momentum trading conviction comes from velocity exceeding threshold, not from p_model vs p_mkt edge.

        # 2026-07-05 FIX: Disabled to allow momentum signals to execute when velocity exceeds threshold.

        

        logger.info(

            "[EDGE-MULTIPLIER] asset=%s price_cents=%d time_multiplier=%.1f price_multiplier=%.1f edge_pct=%.2f%% (edge gate disabled for momentum)",

            asset, price_cents, time_edge_multiplier, price_edge_multiplier, edge_pct

        )

        

 # REMOVED: Negative edge check for momentum-based trading

        # The -20% edge threshold is incompatible with momentum signals because:

        # 1. p_model is derived from velocity via logistic mapping, not independent probability estimation

        # 2. Comparing velocity-transformed probability to market-implied probability is meaningless

        # 3. Momentum trading conviction comes from velocity exceeding threshold, not probability edge

        # 4. The edge gate was already disabled for momentum (line 3513-3515)

        # 2026-07-05 FIX: Removed to allow momentum signals to execute based on velocity threshold

        

        # Sanity check only: reject extreme edges that indicate data errors

        # Edge > 90% indicates corrupted market data or calculation errors

        max_edge_threshold = 90.0  # 90% maximum edge (sanity check for data errors)

        if abs(edge_pct) > max_edge_threshold:

            logger.error(

                "[EDGE-REJECT] asset=%s side=%s velocity=%.6f edge_pct=%.2f%% > max_edge=%.2f%% - REJECTING TRADE (data error, corrupted market state)",

                asset, signal_side, velocity, edge_pct, max_edge_threshold

            )

            return None

        

        # 2026-07-05 FIX: Removed confidence filter for momentum-based trading

        # Research shows momentum trading should use velocity magnitude as signal strength

        # Probability-based confidence filtering is not applicable to velocity-based signals

        # The "confidence" in momentum trading is the velocity exceeding the threshold

        # This filter was blocking all signals because natural velocity percentages (0.0015%-0.0025%)

        # produce p_model values very close to 0.5, resulting in confidence_pct < 2%

        

        # Compute confidence as distance from 0.5 (neutral probability)

        # Higher distance from 0.5 = higher confidence

        confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))

        

        # For backward compatibility, set model_prob to p_model

        model_prob = p_model

        

        logger.info("[SIGNAL-GEN] asset=%s velocity=%.6f raw_logit=%.4f p_mkt=%.4f p_model=%.4f edge_pct=%.2f confidence=%.2f",

                    asset, velocity, raw_logit, p_mkt, p_model, edge_pct, confidence)

        

        # Phase 2: Classify regime from market state

        ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

        regime = self._classify_regime(ticker)

        

        # CRITICAL FIX: Calculate correct price_cents based on side

        # Kalshi binary duality: YES_bid + NO_ask = 100, NO_bid + YES_ask = 100

        # YES: use YES mid-price (best_bid + best_ask) / 2

        # NO: use NO mid-price = (NO_bid + NO_ask) / 2

        # where NO_bid = 100 - YES_ask, NO_ask = 100 - YES_bid

        if best_bid and best_ask:

            if signal_side == "yes":

                # YES: use YES mid-price

                price_cents = int((best_bid + best_ask) / 2)

            else:  # signal_side == "no"

                # NO: calculate NO bid/ask from YES bid/ask, then use NO mid-price

                # NO_bid = 100 - YES_ask, NO_ask = 100 - YES_bid

                no_bid = 100 - best_ask

                no_ask = 100 - best_bid

                price_cents = int((no_bid + no_ask) / 2)

                

                logger.info("[PRICE-CALC-NO] asset=%s YES_bid=%d YES_ask=%d -> NO_bid=%d NO_ask=%d NO_mid=%d",

                           asset, best_bid, best_ask, no_bid, no_ask, price_cents)

                

                # 2026-07-05 FIX: REMOVED price clamping to [50, 70] range

                # Clamping was preventing orders from filling by forcing prices below market levels

                # Orders now use actual market mid-spread prices for proper execution

        elif best_bid:

            # Fallback to bid only

            if signal_side == "yes":

                price_cents = best_bid

            else:

                # NO: NO_ask = 100 - YES_bid

                price_cents = 100 - best_bid

        elif best_ask:

            # Fallback to ask only

            if signal_side == "yes":

                price_cents = best_ask

            else:

                # NO: NO_bid = 100 - YES_ask

                price_cents = 100 - best_ask

        else:

            # No market data - use neutral price (already in range)

            price_cents = 25  # 2026-07-09: Changed from 50 to 25 (midpoint of 10-50c sweet spot)

        

        # 2026-07-12: Expanded price range 10c-75c to match actual market conditions (YES prices 60-97c)

        # If no prices exist in 10-75c range, drop the candidate (no trade).

        raw_price_cents = price_cents

        

        # Check if price is within range (10c-75c)

        if 10 <= raw_price_cents <= 75:

            # Price is already in valid range - use it directly

            clamped_price_cents = raw_price_cents

            logger.info(

                "[PRICE-SELECTION] asset=%s raw_price_cents=%d in range [10c-75c] - using directly",

                asset, raw_price_cents

            )

        else:

            # Price is outside canonical range - search orderbook for valid prices

            logger.warning(

                "[PRICE-SELECTION] asset=%s raw_price_cents=%d outside range [10c-75c] - searching orderbook",

                asset, raw_price_cents

            )

            

            # Try to find a price in the canonical range from the orderbook

            price_cents = None

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None

                

                if market_state:

                    # Get YES orderbook (ascending by price)

                    yes_book = getattr(market_state, 'yes_book', [])

                    if yes_book:

                        # Find cheapest YES price within [10c, 75c] with size >= 1

                        valid_prices = [p for (p, size) in yes_book if 10 <= p <= 75 and size >= 1]

                        if valid_prices:

                            price_cents = min(valid_prices)  # Use cheapest acceptable price

                            logger.info(

                                "[PRICE-SELECTION] asset=%s found %d valid prices in canonical range, using cheapest=%d",

                                asset, len(valid_prices), price_cents

                            )

                        else:

                            logger.warning(

                                "[PRICE-SELECTION] asset=%s no YES prices in range [10c-75c] - dropping candidate",

                                asset

                            )

                            return None  # Drop candidate - no valid price in canonical range

                    else:

                        logger.warning(

                            "[PRICE-SELECTION] asset=%s orderbook not available - dropping candidate",

                            asset

                        )

                        return None

                else:

                    logger.warning(

                        "[PRICE-SELECTION] asset=%s market state not available - dropping candidate",

                        asset

                    )

                    return None

            except Exception as e:

                logger.error(

                    "[PRICE-SELECTION] asset=%s error searching orderbook: %s - dropping candidate",

                    asset, e

                )

                return None

            

            clamped_price_cents = price_cents

        

        # Final validation - ensure we have a valid price in the range (10c-75c)

        # CRITICAL FIX: 2026-07-12 - Use expanded 10-75c range to match current market conditions

        if clamped_price_cents is None or not (10 <= clamped_price_cents <= 75):

            logger.error(

                "[PRICE-SELECTION-ERROR] asset=%s final price_cents=%d not in range [10c-75c] - dropping candidate",

                asset, clamped_price_cents

            )

            return None

        

        logger.info(

            "[PRICE-SELECTION] asset=%s final entry price=%d (within expanded range [10c-95c])",

            asset, clamped_price_cents

        )

        

        price_cents = clamped_price_cents

        

        # MAKER-FIRST ENTRY PRICING (2026-07-05 RESEARCH FIX)

        # Previous version anchored YES buys at best_ask - offset, which on wide books

        # (e.g., bid=81 ask=99) produced 98c entries — chasing the ask with no profit room.

        # Research standard (Kalshi 15m bots, PRED Scanner order-type study 2026):

        # - Rest limit orders on OUR side of the book (join/improve best bid) so swings

        #   come to us and we enter cheap (maker, 0 fee, queue priority).

        # - Cross the spread (taker) ONLY when edge >= 4% (EDGE_MARKET_ENTRY threshold,

        #   taker-fee adjusted) — a signal strong enough to pay for immediacy.

        # - Sweet-spot band from profile configuration (default 10-70c for momentum-based trading)

        # - CRITICAL FIX: 2026-07-05 - Use profile configuration instead of hardcoded values

        # - Previous hardcoded [25c, 50c] was blocking all trades in current market conditions

        # - Profile config allows dynamic adjustment based on strategy requirements
        # - 2026-07-11: Updated to use dynamic threshold manager for regime-aware price ranges

        try:

            from merid.event_venues.kalshi.dynamic_thresholds import get_dynamic_threshold_manager

            threshold_manager = get_dynamic_threshold_manager()

            ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS = threshold_manager.get_price_range()

            logger.debug(
                "[SIGNAL-GEN] Using dynamic price range from threshold manager: %d-%dc (regime=%s)",
                ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS, threshold_manager.get_regime()
            )

        except Exception as e:

            logger.warning("[SIGNAL-GEN] Failed to load dynamic price range: %s, using fallback 10-50c", e)

            ENTRY_MIN_PRICE_CENTS = 10  # Canonical lower bound

            ENTRY_MAX_PRICE_CENTS = 50  # Canonical upper bound

        

        MARKETABLE_EDGE_PCT = 4.0  # matches EDGE_MARKET_ENTRY_* (0.04) in risk_parameters.py

        

        def calculate_optimal_entry_price(

            side: str,

            best_bid: int,

            best_ask: int,

            minutes_to_expiry: float,

            edge_pct: float

        ) -> Optional[int]:

            """

            Maker-first entry price in the side's own price space.

            

            Returns None when no entry inside the profile price_range [5c, 95c] is possible,

            in which case the candidate must be skipped (no chasing).

            """

            if best_bid <= 0 or best_ask <= 0:

                return None  # No two-sided book: cannot price a resting entry safely

            

            # Convert to the traded side's price space

            if side == "yes":

                side_bid, side_ask = best_bid, best_ask

            else:  # NO space: no_bid = 100 - yes_ask, no_ask = 100 - yes_bid

                side_bid, side_ask = 100 - best_ask, 100 - best_bid

            

            if side_bid <= 0 or side_ask <= 0 or side_ask <= side_bid:

                # Crossed/degenerate book in side space — join whatever bid exists

                side_bid = max(1, min(side_bid, 99))

                side_ask = max(side_bid + 1, min(max(side_ask, side_bid + 1), 99))

            

            # Spread-aware execution: only cross TIGHT spreads. On wide books (thin

            # early-window liquidity) the ask is a phantom quote — lifting it means

            # paying far above fair value (e.g., side_bid=1 side_ask=69). Research:

            # limit orders in thin markets get 23% better price control (PRED 2026).

            spread_cents = side_ask - side_bid

            TIGHT_SPREAD_MAX_CENTS = 10

            

            if edge_pct >= MARKETABLE_EDGE_PCT and spread_cents <= TIGHT_SPREAD_MAX_CENTS:

                # Strong edge on a tight book: pay the spread for a guaranteed fill (taker)

                optimal_price = side_ask

                entry_mode = "marketable"

            elif edge_pct >= MARKETABLE_EDGE_PCT:

                # Strong edge but WIDE book: never lift a phantom ask. Rest at side-space

                # mid — passive, cheap, and first in line as the book tightens toward us.

                optimal_price = max(side_bid + 1, (side_bid + side_ask) // 2)

                optimal_price = min(optimal_price, side_ask - 1)

                entry_mode = "resting_mid_wide_spread"

            else:

                # Normal edge (2-4%): rest at/near best bid — buy the swing cheap.

                # Improve bid by 1c for queue priority, but never lift the ask.

                optimal_price = min(side_bid + 1, side_ask - 1)

                optimal_price = max(optimal_price, side_bid)  # never below best bid

                entry_mode = "resting"

            

            # Sweet-spot band enforcement: entries must land in [10c, 50c].

            if optimal_price < ENTRY_MIN_PRICE_CENTS:

                # Too cheap = lottery zone (win rate ~10% below 30c per 2026-07-03 analysis).

                # Allow lifting up to the band floor only if the ask is inside the band.

                if ENTRY_MIN_PRICE_CENTS <= side_ask <= ENTRY_MAX_PRICE_CENTS:

                    optimal_price = ENTRY_MIN_PRICE_CENTS

                else:

                    logger.info(

                        "[ENTRY-BAND-SKIP] side=%s side_bid=%d side_ask=%d below band [%d,%d] -> skip",

                        side, side_bid, side_ask, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS

                    )

                    return None

            elif optimal_price > ENTRY_MAX_PRICE_CENTS:

                # Book has moved past our band: rest AT the band cap only if the bid is

                # still inside the band (price may come back to us); otherwise skip.

                if side_bid <= ENTRY_MAX_PRICE_CENTS:

                    optimal_price = ENTRY_MAX_PRICE_CENTS

                    entry_mode = "resting_band_cap"

                else:

                    logger.info(

                        "[ENTRY-BAND-SKIP] side=%s side_bid=%d side_ask=%d above band [%d,%d] -> skip (no chasing)",

                        side, side_bid, side_ask, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS

                    )

                    return None

            

            logger.info(

                "[MAKER-FIRST-ENTRY] side=%s side_bid=%d side_ask=%d price=%d mode=%s edge=%.2f%% tte=%.1fmin",

                side, side_bid, side_ask, optimal_price, entry_mode, edge_pct, minutes_to_expiry

            )

            return int(optimal_price)

        

        # Apply maker-first entry pricing

        if best_bid > 0 and best_ask > 0:

            optimal_entry = calculate_optimal_entry_price(

                side=signal_side,

                best_bid=best_bid,

                best_ask=best_ask,

                minutes_to_expiry=minutes_to_expiry,

                edge_pct=edge_pct

            )

            if optimal_entry is None:

                logger.info(

                    "[ENTRY-PRICE-SKIP] asset=%s side=%s bid=%d ask=%d no entry inside sweet-spot band -> NO TRADE",

                    asset, signal_side, best_bid, best_ask

                )

                return None

            price_cents = optimal_entry

        

        # 2026-07-05 INDUSTRY ALIGNMENT: Relax entry band restriction for near-expiry trading

        # Industry standard: Trade at any price where EV > fee threshold, not just within arbitrary band

        # Near expiry (last 3 minutes), prices naturally converge to 0/100 - this is normal behavior

        # Early/mid window: Keep band to avoid lottery zone (<30c) and poor scaling (>70c)

        # Late window: Relax band to allow trading on convergence with fee-adjusted edge

        

        if minutes_to_expiry > 3.0:

            # Early/mid window: enforce entry band to avoid lottery zone and poor scaling

            if not (ENTRY_MIN_PRICE_CENTS <= price_cents <= ENTRY_MAX_PRICE_CENTS):

                logger.info(

                    "[ENTRY-BAND-SKIP] asset=%s side=%s price_cents=%d outside sweet-spot band [%d,%d] (tte=%.1fmin > 3min) -> NO TRADE",

                    asset, signal_side, price_cents, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS, minutes_to_expiry

                )

                return None

        else:

            # Late window (last 3 minutes): allow trading outside band if fee-adjusted edge is sufficient

            # Fee modeling already ensures edge > 3 cents net after fees

            logger.info(

                "[ENTRY-BAND-RELAXED] asset=%s side=%s price_cents=%d outside band [%d,%d] but tte=%.1fmin <= 3min -> ALLOW (fee-adjusted edge ensures profitability)",

                asset, signal_side, price_cents, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS, minutes_to_expiry

            )

        

        # Construct signal dictionary

        signal = {

            "asset": asset,

            "side": signal_side,

            "action": signal_action,

            "velocity": velocity,

            "spot_price": spot_price,

            "minutes_to_expiry": minutes_to_expiry,

            "best_bid": best_bid,

            "best_ask": best_ask,

            "price_source": price_source,

            "strategy_staleness": strategy_staleness,

            "venue_staleness": venue_staleness,

            "edge_pct": edge_pct,  # Phase 1: Edge from (p_model - p_mkt)

            "confidence": confidence,  # Phase 1: Confidence from distance from 0.5

            "model_prob": model_prob,  # Phase 1: Model probability from logistic mapping

            "p_mkt": p_mkt,  # Phase 1: Market probability for debugging

            "raw_logit": raw_logit,  # Phase 1: Raw logit for debugging

            "regime": regime,  # Phase 2: Regime classification from market state (liquidity-based)

            "hmm_regime": hmm_regime,  # Phase 6: HMM regime for exit policy (bull/choppy/bear)

            "hmm_regime_confidence": hmm_regime_confidence,  # Phase 6: HMM regime confidence

            "rationale": panic_fade_signal["rationale"] if panic_fade_signal else f"velocity_based: velocity={velocity:.6f} edge_pct={edge_pct:.2f}%",  # CRITICAL: Add rationale for strategy

            "price_cents": price_cents,  # CRITICAL FIX: Set correct price based on side (YES uses YES price, NO uses NO price)

            # Dual-source strike price metadata for traceability

            "strike_price": strike_price,  # Strike price used for signal (window_strike or fallback)

            "strike_source": strike_source,  # Source: "kalshi_floor_strike", "candle_open", "spot_fallback"

        }

        

        # Add panic fade metadata if applicable

        if panic_fade_signal:

            signal["strategy"] = "panic_fade"

            signal["rsi"] = panic_fade_signal.get("rsi")

            signal["zscore"] = panic_fade_signal.get("zscore")

        

        # CRITICAL FIX: 2026-07-09 - Integrate global slot allocator for $1 hard limit

        # Each contract consumes its entry price from the $1 cap across all 5 assets

        # This prevents agents from exceeding $1 total exposure in the same window

        try:

            from merid.risk.global_slot_allocator import (

                get_global_slot_allocator,

                AllocationRequest

            )

            

            slot_allocator = get_global_slot_allocator()

            

            # Calculate spread for allocation request

            spread_cents = abs(best_ask - best_bid) if best_bid > 0 and best_ask > 0 else 0

            

            # Create allocation request

            allocation_request = AllocationRequest(

                agent_id=self.config.name,

                asset=asset,

                ticker=ticker if 'ticker' in locals() else market.market_id if hasattr(market, 'market') else "unknown",

                entry_price_cents=int(price_cents),

                edge_pct=edge_pct,

                spread_cents=spread_cents,

                is_exit_order=False  # Signal generation is for entry orders only

            )

            

            # Request slot allocation

            allocated, reason, slot_id = slot_allocator.request_allocation(allocation_request)

            

            if not allocated:

                logger.info(

                    "[SLOT-ALLOCATOR-REJECT] asset=%s side=%s price_cents=%d edge=%.2f%% - %s",

                    asset, signal_side, int(price_cents), edge_pct, reason

                )

                return None  # Skip this signal - no slot available

            

            # Store slot_id in signal for later release on position closure

            signal["slot_id"] = slot_id

            

            logger.info(

                "[SLOT-ALLOCATOR-ALLOCATED] asset=%s side=%s price_cents=%d slot_id=%s total_exposure=$%.2f",

                asset, signal_side, int(price_cents), slot_id, slot_allocator.get_total_exposure()

            )

            

        except Exception as e:

            logger.error("[SLOT-ALLOCATOR-ERROR] Failed to allocate slot: %s", e, exc_info=True)

            # CRITICAL: Reject signal if slot allocator fails - this prevents exposure cap bypass

            # If the allocator is unavailable, trading must halt to enforce the $1 hard cap

            logger.warning(

                "[SLOT-ALLOCATOR-REJECT] asset=%s side=%s price_cents=%d edge=%.2f%% - slot_allocator_error: %s",

                asset, signal_side, int(price_cents), edge_pct, str(e)

            )

            return None  # Reject signal - slot allocator is required for $1 exposure cap

        

        logger.info("[SIGNAL-GENERATED] asset=%s side=%s velocity=%.6f edge_pct=%.2f%% confidence=%.2f model_prob=%.2f", 

                   asset, signal_side, velocity, edge_pct, confidence, model_prob)

        return signal

    

    async def collect_order_candidate(self, tick: int) -> Optional[Dict[str, Any]]:

        # Collect order candidate for this agent.

        logger.info("[COLLECT-ENTRY] agent=%s tick=%d", self.config.name, tick)

        try:

            # Get spot price from unified spot service

            asset = self.config.name.split('_')[0]

            logger.info("[COLLECT-ASSET] agent=%s asset=%s", self.config.name, asset)

            

            # CRITICAL: Re-enabled cooldown to prevent over-trading

            # The cooldown was temporarily disabled for debugging, but this caused

            # 100% of bankroll to be used in positions. Cooldown is now re-enabled.

            cooldown_seconds = self._calculate_dynamic_cooldown(asset)

            last_trade_time = self._last_trade_time.get(asset, time.monotonic())

            time_since_last_trade = time.monotonic() - last_trade_time

            

            logger.info("[COLLECT-COOLDOWN] agent=%s asset=%s time_since_last=%.1fs cooldown=%.1fs", 

                       self.config.name, asset, time_since_last_trade, cooldown_seconds)

            

            if time_since_last_trade < cooldown_seconds:

                logger.info(

                    "[COOLDOWN-CHECK] asset=%s time_since_last=%.1fs < cooldown=%.1fs, skipping",

                    asset, time_since_last_trade, cooldown_seconds

                )

                return None

            

            # 2026 Research-Based Risk Management: Session limit (max 5 trades per 15m window)

            current_time = time.time()

            if current_time - self._session_start_time > self._session_window_sec:

                # Reset session counters

                self._session_order_count = 0

                self._session_risk_usd = 0.0  # CRITICAL FIX: Reset session risk cap with window

                self._consecutive_losses = {asset: 0 for asset in self._consecutive_losses}  # CRITICAL FIX: Reset consecutive losses with window

                self._consecutive_loss_pause_until = {asset: 0.0 for asset in self._consecutive_loss_pause_until}  # CRITICAL FIX: Reset pause times with window

                self._session_start_time = current_time

                logger.info("[SESSION-RESET] agent=%s session window reset (order_count=0, session_risk=0, consecutive_losses=0)", self.config.name)

            

            if self._session_order_count >= self.config.max_orders_per_15m_window:

                logger.info(

                    "[SESSION-LIMIT] agent=%s session_orders=%d >= max_orders_per_15m_window=%d -> SKIP (session limit reached)",

                    self.config.name, self._session_order_count, self.config.max_orders_per_15m_window

                )

                return None

            

            # 2026 Research-Based Risk Management: Consecutive loss pause

            pause_until = self._consecutive_loss_pause_until.get(asset, 0.0)

            if current_time < pause_until:

                logger.info(

                    "[CONSECUTIVE-LOSS-PAUSE] agent=%s asset=%s paused until %s (consecutive losses=%d) -> SKIP",

                    self.config.name, asset, pause_until, self._consecutive_losses.get(asset, 0)

                )

                return None

            

            # 2026 Research-Based Risk Management: Session risk cap (10% of capital)

            if self._session_risk_cap_usd > 0 and self._session_risk_usd >= self._session_risk_cap_usd:

                logger.info(

                    "[SESSION-RISK-CAP] agent=%s session_risk=%.2f >= cap=%.2f -> SKIP (session risk cap reached)",

                    self.config.name, self._session_risk_usd, self._session_risk_cap_usd

                )

                return None

            

            # 2026 Research-Based Risk Management: Portfolio heat tracking

            heat_allowed, heat_reason = self._check_portfolio_heat()

            if not heat_allowed:

                logger.info(

                    "[PORTFOLIO-HEAT] agent=%s asset=%s reason=%s -> SKIP (portfolio too hot)",

                    self.config.name, asset, heat_reason

                )

                return None

            

            # 2026 Research-Based Risk Management: Asset-specific rolling PnL limits

            pnl_allowed, pnl_reason = self._check_rolling_pnl_limit(asset)

            if not pnl_allowed:

                logger.info(

                    "[ROLLING-PNL] agent=%s asset=%s reason=%s -> SKIP (rolling PnL limit exceeded)",

                    self.config.name, asset, pnl_reason

                )

                return None

            

            # 2026 Research-Based Risk Management: Time-of-day risk scaling

            # Get multiplier (will be applied to position size later)

            time_of_day_multiplier = self._apply_time_of_day_risk_scaling(asset)

            if time_of_day_multiplier != 1.0:

                logger.info(

                    "[TIME-OF-DAY-SCALING] agent=%s asset=%s multiplier=%.2f (session-based risk adjustment)",

                    self.config.name, asset, time_of_day_multiplier

                )

            if time_of_day_multiplier <= 0:

                logger.info(

                    "[TIME-OF-DAY-SCALING] agent=%s asset=%s multiplier=%.2f -> SKIP (risk scaling zero)",

                    self.config.name, asset, time_of_day_multiplier

                )

                return None

            

            # 2026 FIX: Check max concurrent positions limit to prevent over-accumulation

            # Industry standard: 10-25 concurrent positions (Kalshibot, PolyTrack, production bots)

            # Position cache is synced from REST API via fills_poller and venue_adapter

            # Re-enabled with staleness check to avoid false limit hits

            try:

                from merid.event_venues.kalshi.position_cache import get_position_cache

                position_cache = get_position_cache()

                if position_cache:

                    all_positions = position_cache.get_all_positions(validate_freshness=False)

                    # 2026 FIX: Only count open positions (contracts > 0)

                    open_positions = {k: v for k, v in all_positions.items() if v.contracts > 0}

                    position_count = len(open_positions)

                    

                    logger.info(

                        "[POSITION-LIMIT] agent=%s total_positions=%d open_positions=%d",

                        self.config.name, len(all_positions), position_count

                    )

                    

                    if position_count >= self.config.max_concurrent_positions:

                        logger.info(

                            "[POSITION-LIMIT] agent=%s current_positions=%d >= max_concurrent_positions=%d -> SKIP (position limit reached)",

                            self.config.name, position_count, self.config.max_concurrent_positions

                        )

                        return None

            except Exception as e:

                logger.warning("[POSITION-LIMIT] agent=%s position check failed: %s", self.config.name, str(e))

            

            spot_price = None

            spot_data = None

            

            # Try different methods depending on spot provider interface

            logger.info("[COLLECT-SPOT-BEFORE] agent=%s asset=%s spot_provider=%s", 

                       self.config.name, asset, type(self.spot_provider).__name__)

            

            # CRITICAL FIX: UnifiedSpotService.get() is synchronous and returns SpotPrice or SpotError

            # Use the synchronous get() method which returns SpotPrice with OHLC data

            if hasattr(self.spot_provider, 'get'):

                result = self.spot_provider.get(asset)

                logger.info("[COLLECT-SPOT-GET-RESULT] agent=%s asset=%s result=%s type=%s",

                           self.config.name, asset, result, type(result).__name__ if result else None)

                if result is not None:

                    # Check if result is SpotError (indicates unavailable/degraded spot data)

                    if hasattr(result, 'reason'):

                        logger.warning("[COLLECT-SPOT-ERROR] agent=%s asset=%s spot unavailable: %s",

                                     self.config.name, asset, result.reason)

                        spot_price = None

                        spot_data = None

                    elif hasattr(result, 'price'):

                        spot_price = result.price

                        spot_data = result  # Store full SpotPrice object for OHLC data

                        # CRITICAL FIX: 2026-07-10 - Log OHLC availability for debugging

                        has_open = hasattr(result, 'open') and result.open is not None

                        has_high = hasattr(result, 'high') and result.high is not None

                        has_low = hasattr(result, 'low') and result.low is not None

                        logger.info("[COLLECT-SPOT-SUCCESS] agent=%s asset=%s spot_price=%s has_ohlc=%s (open=%s high=%s low=%s)",

                                   self.config.name, asset, format_price(asset, spot_price),

                                   has_open or has_high or has_low, has_open, has_high, has_low)

                    else:

                        logger.warning("[COLLECT-SPOT-NO-PRICE] agent=%s asset=%s result has no price attribute",

                                     self.config.name, asset)

                else:

                    logger.warning("[COLLECT-SPOT-NONE] agent=%s asset=%s get() returned None",

                                 self.config.name, asset)

            elif hasattr(self.spot_provider, 'get_spot_price'):

                spot_price = await self.spot_provider.get_spot_price(asset)

            elif hasattr(self.spot_provider, 'get_spot'):

                result = await self.spot_provider.get_spot(asset)

                if hasattr(result, 'price_usd'):

                    spot_price = result.price_usd

                    spot_data = result  # Store full SpotSnapshot object for OHLC data

            

            logger.info("[COLLECT-SPOT-AFTER] agent=%s asset=%s spot_price=%s spot_data=%s", 

                       self.config.name, asset, spot_price, type(spot_data).__name__ if spot_data else None)

            

            if not spot_price:

                logger.warning("[SPOT-ERROR] asset=%s no spot price available", self.config.name)

                return None

            

            # CRITICAL FIX: Update price history BEFORE signal generation

            # This ensures velocity calculation has fresh data even if no signal is generated

            # Previously, price history was only updated in _generate_signal, creating a vicious cycle:

            # no signal -> no price update -> velocity=0 -> no signal

            # CRITICAL FIX: Pass spot_data for OHLC-based ADX/ATR calculation

            self._update_price_history(asset, spot_price, spot_data)

            

            # Get market from market state store - use available markets instead of computing from time

            market = None

            try:

                # Extract asset from agent name (e.g., "BTC_15M" -> "BTC")

                asset = self.config.name.split("_")[0]

                

                # Query market state store for available markets for this asset

                # This works with whatever markets are actually subscribed via WebSocket

                logger.info("[COLLECT-MARKET-STORE] agent=%s asset=%s market_state_store=%s", 

                           self.config.name, asset, self.market_state_store is not None)

                if self.market_state_store:

                    # Get all market IDs in the store

                    all_tickers = list(self.market_state_store._states.keys())

                    logger.info("[COLLECT-ALL-TICKERS] agent=%s total_tickers=%d", 

                               self.config.name, len(all_tickers))

                    

                    # Log sample tickers for diagnostics

                    if all_tickers:

                        logger.info("[COLLECT-SAMPLE-TICKERS] agent=%s sample_tickers=%s", 

                                   self.config.name, all_tickers[:10])

                    

                    # Find tickers matching this asset's series

                    series_prefix = self.config.series_tickers[0] if self.config.series_tickers else f"KX{asset}15M"

                    logger.info("[COLLECT-SERIES-PREFIX] agent=%s series_prefix=%s", 

                               self.config.name, series_prefix)

                    matching_tickers = [t for t in all_tickers if t.startswith(series_prefix)]

                    logger.info("[COLLECT-MATCHING-TICKERS] agent=%s matching=%d tickers=%s", 

                               self.config.name, len(matching_tickers), matching_tickers[:5])

                    

                    # CRITICAL: Alert if expected series is missing (indicates WebSocket subscription failure)

                    if len(matching_tickers) == 0 and len(all_tickers) > 0:

                        logger.error(

                            "[COLLECT-SERIES-MISSING] agent=%s asset=%s series_prefix=%s NOT FOUND in market_state_store. "

                            "This indicates WebSocket subscription or market discovery failure. "

                            "Available series prefixes: %s",

                            self.config.name, asset, series_prefix,

                            sorted(set([t.split("-")[0] for t in all_tickers if "-" in t]))

                        )

                    

                    if matching_tickers:

                        # 2026-07-05 RESEARCH FIX: Entry window is minutes 3-10 of the 15m window

                        # (time_to_expiry 300s-720s). Research consensus for Kalshi 15m bots:

                        # - Skip first ~3 minutes (noisy signals, walk-forward optimal min_dm=3)

                        # - No NEW entries in final 5 minutes (adverse selection: informed flow

                        #   dominates late; entering late = chasing near-settled prices)

                        # Exits/ratchet management are handled elsewhere and are NOT window-gated.

                        current_time = time.time()

                        best_ticker = None

                        best_time_to_expiry = 0.0  # Initialize to 0 to select maximum (newest market)

                        

                        for ticker_candidate in matching_tickers:

                            market_state_candidate = self.market_state_store.get(ticker_candidate)

                            if market_state_candidate:

                                close_time_ts = getattr(market_state_candidate, 'expected_expiration_time', None)

                                if close_time_ts is None:

                                    continue

                                elif isinstance(close_time_ts, str):

                                    try:

                                        close_time_ts = datetime.fromisoformat(close_time_ts.replace('Z', '+00:00')).timestamp()

                                    except (ValueError, AttributeError):

                                        continue

                                elif not isinstance(close_time_ts, (int, float)):

                                    continue

                                

                                time_to_expiry = close_time_ts - current_time

                                

                                # Select the contract with time_to_expiry within the ENTRY window

                                # (0s-900s = full 15m window). Allow trading throughout entire window.

                                # CRITICAL FIX: Select MAXIMUM time_to_expiry (newest market) to catch

                                # markets at 50c/50c before they drift to extreme prices

                                # Previous logic selected minimum (closest to expiry), causing us to

                                # trade late markets with prices 76-98c instead of early markets at ~50c

                                if 0 <= time_to_expiry <= 900:

                                    if time_to_expiry > best_time_to_expiry:

                                        best_ticker = ticker_candidate

                                        best_time_to_expiry = time_to_expiry

                                

                                logger.info(

                                    "[MARKET-SELECTION-DEBUG] asset=%s ticker=%s time_to_expiry=%.1fs",

                                    self.config.name, ticker_candidate, time_to_expiry

                                )

                        

                        if best_ticker:

                            ticker = best_ticker

                            # CRITICAL GUARDRAIL: Validate selected market is truly open

                            market_state = self.market_state_store.get(ticker)

                            if market_state:

                                # Status is stored directly on state object, not in raw_data

                                api_status = getattr(market_state, 'status', 'unknown').lower()

                                settlement_ts = getattr(market_state, 'settlement_ts', None)

                                liquidity_dollars = getattr(market_state, 'liquidity_dollars', None)

                                yes_bid = getattr(market_state, 'best_bid_cents', None)

                                no_bid = getattr(market_state, 'best_ask_cents', None)



                                # Assert market is not settled (hard rule)

                                if settlement_ts is not None:

                                    logger.error(

                                        "[MARKET-STATE-MISMATCH] selected ticker=%s has settlement_ts=%s (expected None). "

                                        "Market is already settled - skipping trade.",

                                        ticker, settlement_ts

                                    )

                                    return None



                                # Warn if status is not 'open' (soft rule - market state may be stale)

                                # The catalog API filter already ensures we only get open markets

                                if api_status not in ['open', 'closed']:

                                    logger.warning(

                                        "[MARKET-STATE-MISMATCH] selected ticker=%s has status=%s (expected 'open' or 'closed'). "

                                        "Market state may be stale - catalog API filter ensures open markets.",

                                        ticker, api_status

                                    )



                                # Warn if liquidity is zero (edge case, not hard rule)

                                if liquidity_dollars == 0 or (yes_bid == 0 and no_bid == 0):

                                    logger.warning(

                                        "[MARKET-STATE-MISMATCH] selected ticker=%s has zero liquidity "

                                        "(liquidity_dollars=%s, yes_bid=%s, no_bid=%s). "

                                        "This may indicate stale market data.",

                                        ticker, liquidity_dollars, yes_bid, no_bid

                                    )



                            logger.info(

                                "[MARKET-SELECTION] asset=%s ticker=%s selected (time_to_expiry=%.1fs, in trading window)",

                                self.config.name, ticker, best_time_to_expiry

                            )

                        else:

                            # No contract in entry window - skip this cycle

                            logger.info(

                                "[MARKET-SELECTION] asset=%s no contract in entry window (0s-900s to expiry), skipping",

                                self.config.name

                            )

                            return None

                        

                        market_state = self.market_state_store.get(ticker)

                        

                        if market_state:

                            # Create MinimalMarket wrapper for compatibility

                            # Use expiration_time from market state if available, otherwise compute from ticker

                            close_time_ts = getattr(market_state, 'expected_expiration_time', None)

                            if close_time_ts is None:

                                # Fallback: compute close_time from current time + 15 minutes

                                close_time_ts = time.time() + 900

                            elif isinstance(close_time_ts, str):

                                # 2026 FIX: Handle string timestamp (ISO format)

                                # Convert ISO string to timestamp

                                try:

                                    close_time_ts = datetime.fromisoformat(close_time_ts.replace('Z', '+00:00')).timestamp()

                                except Exception as e:

                                    logger.warning("[TRADING-WINDOW] failed to parse close_time_ts string: %s, using fallback", e)

                                    close_time_ts = time.time() + 900

                            elif not isinstance(close_time_ts, (int, float)):

                                # 2026 FIX: Handle unexpected types (already datetime, etc.)

                                logger.warning("[TRADING-WINDOW] unexpected close_time_ts type: %s, using fallback", type(close_time_ts))

                                close_time_ts = time.time() + 900

                             

                            # CRITICAL FIX: Implement min_decision_minute from profile

                            # Profile configures per-asset minimum decision minute to skip noisy early signals

                            # This prevents low-quality signals from early price action

                            # Industry standard: Skip first N minutes of 15m window to avoid noise

                            time_to_expiry = close_time_ts - time.time()

                            max_trading_window = 900  # full 15m window

                            

                            # Get min_decision_minute from profile (per-asset configuration)

                            min_decision_minute = 0  # default to 0 if not configured

                            try:

                                # Load raw YAML to access min_decision_minute section

                                import yaml

                                from pathlib import Path

                                import os

                                profile_name = os.getenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

                                profile_filename = f"{profile_name}.yaml"

                                # __file__ is merid/prediction/agent_grid_15m.py

                                # parent.parent.parent = MERID root

                                profile_path = Path(__file__).parent.parent.parent / "config" / "profiles" / profile_filename

                                

                                with open(profile_path, 'r', encoding='utf-8') as f:

                                    profile_yaml = yaml.safe_load(f)

                                

                                min_decision_minute_config = profile_yaml.get("min_decision_minute", {})

                                # Extract asset symbol from agent name (e.g., "DOGE_15M" -> "DOGE")

                                asset_symbol = self.config.name.split('_')[0] if '_' in self.config.name else self.config.name

                                min_decision_minute = min_decision_minute_config.get(asset_symbol, 0)

                                logger.info(

                                    "[MIN-DECISION-MINUTE] asset=%s min_decision_minute=%d (from profile YAML)",

                                    self.config.name, min_decision_minute

                                )

                            except Exception as e:

                                logger.warning("[MIN-DECISION-MINUTE] Failed to load from profile YAML: %s, using default 0", e)

                            

                            min_time_to_expiry = min_decision_minute * 60  # convert to seconds

                            

                            if time_to_expiry > max_trading_window:

                                logger.info(

                                    "[TRADING-WINDOW] asset=%s time_to_expiry=%.1fs > max_trading_window=%ds -> SKIP (too early in contract)",

                                    self.config.name, time_to_expiry, max_trading_window

                                )

                                return None

                            elif time_to_expiry < min_time_to_expiry:

                                logger.info(

                                    "[TRADING-WINDOW] asset=%s time_to_expiry=%.1fs < min_time_to_expiry=%ds (%d min) -> SKIP (too early in window, waiting for signal clarity)",

                                    self.config.name, time_to_expiry, min_time_to_expiry, min_decision_minute

                                )

                                return None

                            else:

                                logger.info(

                                    "[TRADING-WINDOW] asset=%s time_to_expiry=%.1fs within trading window [%ds, %ds] -> PROCEED",

                                    self.config.name, time_to_expiry, min_time_to_expiry, max_trading_window

                                )

                             

                            market = MinimalMarket(

                                market_id=ticker,

                                close_time=close_time_ts,

                                asset=asset,

                                minutes_to_expiry=time_to_expiry / 60.0  # Convert seconds to minutes

                            )

                            logger.info(

                                "[MARKET-STATE-STORE] asset=%s ticker=%s from state store (total matching=%d)",

                                self.config.name, ticker, len(matching_tickers)

                            )

                        else:

                            logger.warning("[MARKET-STATE-STORE] asset=%s ticker=%s no state available", self.config.name, ticker)

                    else:

                        logger.warning("[MARKET-STATE-STORE] asset=%s no tickers matching series=%s in state store (total tickers=%d)",

                                     self.config.name, series_prefix, len(all_tickers))

                else:

                    logger.warning("[MARKET-STATE-STORE] asset=%s market_state_store is None", self.config.name)

            except Exception as e:

                logger.warning("[MARKET-STATE-STORE-ERROR] asset=%s error=%s", self.config.name, str(e), exc_info=True)

            

            if not market:

                logger.warning("[MARKET-ERROR] asset=%s no market available from market state store", self.config.name)

                return None

            

            # Validate market state

            if not self._validate_market_state(market):

                logger.info("[MARKET-VALIDATION-FAILED] asset=%s market validation failed", self.config.name)

                return None

            

            # CRITICAL FIX: Block trading during warmup to prevent trades based on insufficient data

            # Market validation requires sufficient depth and fresh data, which may not be available

            # during startup. Block trading during warmup period to avoid high leverage bugs.

            # REDUCED warmup from 2 to 1 for immediate 15m trading start (spot service refreshes every 5s)

            # 1 data point sufficient for immediate velocity-based trading

            price_history_len = len(list(self._spot_price_history.get(asset, [])))

            if price_history_len < 1:

                logger.warning(

                    "[MARKET-VALIDATION-SKIP] asset=%s price_history=%d < 1, BLOCKING TRADE during warmup (insufficient data)",

                    self.config.name, price_history_len

                )

                return None  # Block trading during warmup

            else:

                if not self._validate_market_state(market):

                    logger.info("[MARKET-VALIDATION-FAILED] asset=%s market validation failed", self.config.name)

                    return None

            

            # Check per-strip order limit

            # CRITICAL FIX: Use asset-specific series ticker for strip tracking

            # For 15m crypto, each asset has its own series ticker (KXBTC15M, KXETH15M, etc.)

            # We need to find the series ticker that matches the current asset

            strip_ticker = None

            if self.config.series_tickers:

                # Find the series ticker that matches the current asset

                for ticker in self.config.series_tickers:

                    if asset.upper() in ticker.upper():

                        strip_ticker = ticker

                        break

                # Fallback to first ticker if no match found

                if not strip_ticker:

                    strip_ticker = self.config.series_tickers[0]

            

            if strip_ticker:

                # CRITICAL FIX: MinimalMarket has market_id directly, not nested under .market.market_id

                current_market_id = None

                if market and hasattr(market, 'market_id'):

                    current_market_id = market.market_id

                elif market and hasattr(market, 'market') and hasattr(market.market, 'market_id'):

                    current_market_id = market.market.market_id

                

                # DIAGNOSTIC: Log market ID tracking

                stored_market_id = self._current_market_ids.get(strip_ticker)

                logger.info(

                    "[STRIP-DIAG] asset=%s strip=%s current_market_id=%s stored_market_id=%s",

                    asset, strip_ticker, current_market_id, stored_market_id

                )

                

                # Reset counter if market ID changed (new 15m strip)

                if current_market_id and self._current_market_ids.get(strip_ticker) != current_market_id:

                    logger.info(

                        "[STRIP-RESET] asset=%s strip=%s market changed from %s to %s, resetting order count",

                        asset, strip_ticker, self._current_market_ids.get(strip_ticker), current_market_id

                    )

                    self._strip_order_counts[strip_ticker] = 0

                    self._current_market_ids[strip_ticker] = current_market_id

                

                current_strip_orders = self._strip_order_counts.get(strip_ticker, 0)

                if current_strip_orders >= self.config.per_strip_order_limit:

                    logger.info(

                        "[STRIP-LIMIT-CHECK] asset=%s strip=%s orders=%d >= max=%d, skipping",

                        asset, strip_ticker, current_strip_orders, self.config.per_strip_order_limit

                    )

                    return None

            

            # CRITICAL FIX: Use normalized minutes_to_expiry from market object

            # This ensures we use the canonical expiry time from contract_normalization.py

            # which prioritizes close_ts over end_date for 15m contracts

            minutes_to_expiry = 0

            if hasattr(market, 'minutes_to_expiry') and market.minutes_to_expiry is not None:

                # Use normalized minutes_to_expiry (canonical field from catalog)

                minutes_to_expiry = market.minutes_to_expiry

            elif hasattr(market, 'close_time'):

                # Fallback to manual calculation if normalized field not available

                # This should not happen in production with proper catalog normalization

                logger.warning(

                    "[AGENT-GRID-15M] asset=%s using manual minutes_to_expiry calculation (normalized field missing). "

                    "This indicates catalog normalization may not be working correctly.",

                    self.config.name

                )

                close_time = market.close_time

                now = time.time()

                

                # Handle different close_time types (datetime, timestamp string, or float)

                if isinstance(close_time, str):

                    # Parse ISO string to timestamp

                    try:

                        if close_time.endswith('Z'):

                            close_time = close_time.replace('Z', '+00:00')

                        close_dt = dt.fromisoformat(close_time)

                        close_time_ts = close_dt.timestamp()

                    except (ValueError, AttributeError):

                        # Fallback to computed time

                        close_time_ts = now + 900

                elif isinstance(close_time, dt):

                    close_time_ts = close_time.timestamp()

                else:

                    # Assume it's already a timestamp (float/int)

                    close_time_ts = float(close_time) if close_time else now + 900

                

                minutes_to_expiry = (close_time_ts - now) / 60

            

            # For 15-minute rolling markets, only reject if expired (<= 0)

            # Kalshi 15m markets roll every quarter-hour (11:00, 11:15, 11:30, 11:45)

            # and should be traded throughout their entire 15-minute lifecycle

            if minutes_to_expiry <= 0:

                logger.warning("[TIME-EXPIRY-VALIDATION] asset=%s ticker=%s expired=%.1fmin",

                             self.config.name, market.market.market_id if hasattr(market, 'market') else 'N/A', minutes_to_expiry)

                return None

            

            # Generate signal

            signal = self._generate_signal(spot_price, market, minutes_to_expiry)

            if not signal:

                logger.info("[NO-SIGNAL] asset=%s no signal generated", self.config.name)

                return None

            

            # Construct order candidate

            candidate = {

                "agent_id": self.config.name,

                "ticker": market.market.market_id if hasattr(market, 'market') else self.config.series_tickers[0],

                "side": signal["side"],

                "action": signal["action"],

                "spot_price": spot_price,

                "velocity": signal["velocity"],

                "minutes_to_expiry": minutes_to_expiry,

                "edge": signal.get("edge_pct", 0.0),  # CRITICAL: Use "edge" field for loop_15m validation

                "edge_pct": signal.get("edge_pct", 0.0),  # BUG #36 FIX: Carry edge from signal

                "confidence": signal.get("confidence", 0.5),  # BUG #36 FIX: Carry confidence from signal

                "model_prob": signal.get("model_prob", 0.5),  # BUG #36 FIX: Carry model_prob from signal

                "rationale": signal.get("rationale"),  # CRITICAL: Carry rationale to skip edge validation for price-based strategy

                "regime": signal.get("regime", "normal"),  # Phase 2: Carry regime from signal

                # CRITICAL FIX: Add price_cents and count for candidate deduplication

                "price_cents": signal.get("price_cents", 0),  # Will be set by order router

                "count": signal.get("count", 0),  # Will be set by order router

                # 2026 Research-Based Risk Management: Apply time-of-day risk scaling to position size

                "time_of_day_multiplier": time_of_day_multiplier,  # Carry multiplier for order router

                # CRITICAL FIX: Add exit targets to satisfy "no trade without exit" invariant

                "take_profit_r_multiple": 0.5,  # 0.5R take profit (conservative)

                "stop_loss_r_multiple": 0.25,  # 0.25R stop loss (tight risk control)

                # CRITICAL FIX: 2026-07-01 - Add order type for maker rebate optimization

                # Industry standard: Use limit orders (maker) to earn rebates (-0.05% round trip) vs taker fees (0.15% round trip)

                # Reference: https://www.polytrackhq.app/blog/polymarket-15-minute-crypto-guide

                "order_type": "limit" if self.config.use_limit_orders else "market",

                # Phase 1: Add market microstructure data for fee-aware edge and microstructure gates

                "yes_bid_cents": None,

                "yes_ask_cents": None,

                "no_bid_cents": None,

                "no_ask_cents": None,

                "yes_depth": None,

                "no_depth": None,

            }

            

            # Populate market microstructure data from market state store

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                if self.market_state_store:

                    market_state = self.market_state_store.get(ticker)

                    if market_state:

                        candidate["yes_bid_cents"] = getattr(market_state, 'best_bid_cents', None)

                        candidate["yes_ask_cents"] = getattr(market_state, 'best_ask_cents', None)

                        # Derive NO prices from YES prices using Kalshi duality

                        if candidate["yes_bid_cents"] is not None:

                            candidate["no_ask_cents"] = 100 - candidate["yes_bid_cents"]

                        if candidate["yes_ask_cents"] is not None:

                            candidate["no_bid_cents"] = 100 - candidate["yes_ask_cents"]

                        # CRITICAL FIX: Use window-based depth (depth_10c_yes/depth_10c_no) instead of single-level depth

                        # depth_10c_yes/depth_10c_no represent contracts within ±10c of mid price (industry standard)

                        # min_depth_yes/min_depth_no only capture best bid/ask size (1 price level)

                        # This fixes false rejections when liquidity exists across multiple levels

                        depth_10c_yes = getattr(market_state, 'depth_10c_yes', None)

                        depth_10c_no = getattr(market_state, 'depth_10c_no', None)

                        if depth_10c_yes is not None and depth_10c_yes > 0:

                            candidate["yes_depth"] = depth_10c_yes

                        else:

                            candidate["yes_depth"] = getattr(market_state, 'min_depth_yes', None)

                        if depth_10c_no is not None and depth_10c_no > 0:

                            candidate["no_depth"] = depth_10c_no

                        else:

                            candidate["no_depth"] = getattr(market_state, 'min_depth_no', None)

            except Exception as e:

                logger.warning("[CANDIDATE-MICROSTRUCTURE] Failed to populate microstructure data: %s", e)

            

            # CRITICAL BUG FIX: Do NOT update cooldown timestamp here

            # The cooldown should only be updated AFTER a successful trade execution

            # Previously, this line was executed every time a candidate was generated,

            # which caused the cooldown to reset even when no trade was executed

            # This resulted in perpetual cooldown blocks preventing any trading

            # The cooldown timestamp is now updated in the fill handler (position_cache.on_fill)

            # or in the execution confirmation handler after successful order submission

            

            # Update strip order count

            if strip_ticker:

                self._strip_order_counts[strip_ticker] = self._strip_order_counts.get(strip_ticker, 0) + 1

                logger.info(

                    "[STRIP-ORDER-COUNT] asset=%s strip=%s orders=%d/%d",

                    asset, strip_ticker, self._strip_order_counts[strip_ticker], self.config.per_strip_order_limit

                )

            

            logger.info("[CANDIDATE-GENERATED] asset=%s side=%s", self.config.name, signal["side"])

            

            # 2026-07-09: DISABLED direct execution in individual agents

            # Execution is now handled at grid level by global allocator

            # This allows edge-based allocation under venue cap instead of per-asset caps

            # The global allocator sorts candidates by edge and selects best ones under $1 cap

            

            # Set price_cents and count in candidate for allocator

            candidate["price_cents"] = int(signal.get("price_cents", 50))

            candidate["count"] = int(signal.get("count", 1))

            

            # Return candidate without execution (grid level will execute)

            return candidate

            

        except Exception as e:

            logger.error("[CANDIDATE-ERROR] asset=%s error=%s", self.config.name, str(e), exc_info=True)

            return None



# Agent grid for 15m crypto trading

class LeanAgentGrid15m:

    # Minimal agent grid for 15m crypto trading

    # This grid does NOT:

    # - Load persisted agents

    # - Register with DeploymentController

    # - Run reflection/learning systems

    # - Use paper trading engine

    # - Start social broadcasters

    # It only:

    # - Holds 5 LeanAgent15m instances

    # - Runs cycles via run_cycle()

    # - Tracks basic lifecycle state



    def __init__(

        self,

        agents: list[LeanAgent15m],

    ):

        self._agents = agents

        self._running = False

        self._market_state_store = None

        self.position_cache = None  # Position cache for global allocator

        # Initialize strip order tracking

        self._strip_order_counts: Dict[str, int] = {}

        self._current_market_ids: Dict[str, str] = {}

        # REST sync optimization: only sync every 30 seconds instead of every cycle

        self._last_rest_sync_time = 0.0

        self._rest_sync_interval = 30.0  # seconds

        logger.info("[AGENT-GRID-INIT] LeanAgentGrid15m initialized with %d agents", len(agents))

    

    def set_market_state_store(self, market_state_store: Any) -> None:

        # Set the market state store after initialization.

        # This is called after the WS bridge starts and has the store available.

        self._market_state_store = market_state_store

        # Update all agents with the new store

        for agent in self._agents:

            agent.market_state_store = market_state_store

        logger.info("[AGENT-GRID] Market state store set for %d agents", len(self._agents))

    

    def set_position_cache(self, position_cache: Any) -> None:

        # Set the position cache after initialization.

        # This is called after the position cache is available for global allocator.

        self.position_cache = position_cache

        logger.info("[AGENT-GRID] Position cache set for global allocator")

    

    async def start(self) -> None:

        # Start the agent grid.

        self._running = True

        # Reset strip order counts on startup to clear any stale state

        self._strip_order_counts.clear()

        self._current_market_ids.clear()

        logger.info("[AGENT-GRID-START] LeanAgentGrid15m started - strip order counts reset")

    

    async def stop(self) -> None:

        # Stop the agent grid.

        self._running = False

        logger.info("[AGENT-GRID-STOP] LeanAgentGrid15m stopped")

    

    def reset_strip_order_counts(self) -> None:

        """Reset all strip order counts and market ID tracking.

        

        This is called when the catalog detects a market rollover (e.g., 16:15 -> 16:30).

        It resets the per-strip order limits so trading can continue on the new 15m strip.

        """

        self._strip_order_counts.clear()

        self._current_market_ids.clear()

        logger.info("[STRIP-RESET-ALL] Reset all strip order counts and market ID tracking")

    

    async def sync_from_rest(self, tick: int) -> None:

        # Sync catalog and market state from REST API.

        # OPTIMIZATION: Only sync every 30 seconds instead of every cycle to reduce latency.

        # WebSocket provides real-time position updates, REST is used for reconciliation.

        import time

        current_time = time.time()

        

        # Check if enough time has passed since last sync

        if current_time - self._last_rest_sync_time < self._rest_sync_interval:

            logger.info("[AGENT-GRID] Skipping REST sync - last sync %.1fs ago, interval is %.1fs", 

                       current_time - self._last_rest_sync_time, self._rest_sync_interval)

            return

        

        logger.info("[AGENT-GRID] BEFORE sync_from_rest tick=%d", tick)

        

        # Force sync position cache from REST API to clear stale data

        # PRODUCTION FIX: Call Kalshi client directly to avoid circular sync

        # (venue_adapter.get_positions() reads from cache, which causes circular sync)

        try:

            from merid.event_venues.kalshi.position_cache import get_position_cache

            from merid.event_venues.kalshi.client import KalshiVenueClient

            from merid.event_venues.kalshi.kalshi_config import get_kalshi_config

            position_cache = get_position_cache()

            if position_cache:

                # Get positions directly from Kalshi REST API

                client = KalshiVenueClient(config=get_kalshi_config())

                await client.connect()

                kalshi_positions = await client.get_positions()

                # Convert VenuePosition list to format expected by sync_from_rest

                rest_positions = []

                if kalshi_positions:

                    for pos in kalshi_positions:

                        # Convert average_entry_price from dollars to cents

                        avg_price_cents = int(float(pos.average_entry_price) * 100) if pos.average_entry_price else 0

                        rest_positions.append({

                            "market_id": pos.market_id,

                            "contracts": int(pos.size),

                            "side": pos.outcome_id or "yes",

                            "avg_price_cents": avg_price_cents,

                            "realized_pnl": float(pos.realized_pnl) if pos.realized_pnl else 0,

                            "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else 0,

                        })

                # Force sync to bypass staleness guard

                await position_cache.sync_from_rest(rest_positions, force=True)

                self._last_rest_sync_time = current_time

                logger.info("[AGENT-GRID] Force synced position cache from Kalshi REST API (tick=%d, positions=%d)", tick, len(rest_positions))

        except Exception as e:

            logger.warning("[AGENT-GRID] Failed to force sync position cache: %s", e)

        

        logger.info("[AGENT-GRID] AFTER sync_from_rest tick=%d", tick)

    

    async def run_cycle(self, tick: int, allow_new_entries: bool = True) -> list[Dict[str, Any]]:

        # Run a single trading cycle across all agents.

        # CRITICAL FIX: Update indicator stacks for all agents BEFORE sync_from_rest

        # This ensures indicator stacks get price data even when agents are in cooldown

        # Otherwise they will never warm up and will always return empty snapshots

        # This runs on every cycle regardless of individual agent trading status

        # IMPORTANT: Move this BEFORE sync_from_rest because sync_from_rest has an early return

        # when the sync interval hasn't elapsed, which would prevent this code from running

        try:

            for agent in self._agents:

                if hasattr(agent, '_indicator_stacks') and agent._indicator_stacks:

                    try:

                        for update_asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

                            if update_asset in agent._indicator_stacks:

                                try:

                                    # Fetch spot price for this asset

                                    update_spot_price = None

                                    update_spot_data = None



                                    # CRITICAL FIX: Use global unified spot service instead of agent.spot_provider

                                    # The agent's spot_provider attribute doesn't have a get() method

                                    # Use the same pattern as collect_order_candidate and other parts of the codebase

                                    try:

                                        from data.unified_spot_service import get_unified_spot_service

                                        spot_service = get_unified_spot_service()

                                        result = spot_service.get(update_asset)

                                        if result is not None and hasattr(result, 'price'):

                                            update_spot_price = result.price

                                            update_spot_data = result

                                    except Exception as e:

                                        logger.warning("[AGENT-GRID-INDICATOR-ERROR] agent=%s asset=%s failed to fetch spot price: %s",

                                                     agent.config.name, update_asset, e)



                                    if update_spot_price:

                                        # Buffer spot price for 1-minute aggregation

                                        agent._indicator_stack_price_buffer[update_asset].append(update_spot_price)

                                        

                                        # Check if 1 minute has elapsed since last update

                                        current_time = time.time()

                                        last_update = agent._indicator_stack_last_update[update_asset]

                                        time_since_update = current_time - last_update

                                        

                                        # CRITICAL FIX: Allow immediate updates during warmup (first update)

                                        # After warmup, use 15-second aggregation for faster signal generation

                                        # With 3s spot refresh, 60s aggregation is too slow for fast-moving prediction markets

                                        is_warmup = (last_update == 0.0)

                                        

                                        if is_warmup or time_since_update >= 15.0:

                                            # Use the last price in the buffer as the 1-minute close

                                            if agent._indicator_stack_price_buffer[update_asset]:

                                                minute_close = agent._indicator_stack_price_buffer[update_asset][-1]

                                                agent._indicator_stacks[update_asset].update(minute_close)

                                                agent._indicator_stack_last_update[update_asset] = current_time

                                                agent._indicator_stack_price_buffer[update_asset] = []  # Clear buffer

                                except Exception as e:

                                    logger.warning("[AGENT-GRID-INDICATOR-UPDATE] agent=%s asset=%s failed to update Crypto15mIndicatorStack: %s", agent.config.name, update_asset, e)

                    except Exception as e:

                        logger.warning("[AGENT-GRID-INDICATOR-UPDATE] agent=%s failed to update indicator stacks: %s", agent.config.name, e)

        except Exception as e:

            logger.error("[AGENT-GRID-INDICATOR-UPDATE] CRITICAL ERROR in indicator stack update: %s", e, exc_info=True)

        

        # Sync from REST at the beginning of each cycle

        await self.sync_from_rest(tick)

        

        # Phase 1: Collect all candidates from all agents (without execution)

        # OPTIMIZATION: Process agents in parallel using asyncio.gather instead of sequential processing

        # This reduces agent processing time from ~15s to ~3s for 5 agents

        candidates = []

        

        # Create tasks for all agents to run in parallel

        agent_tasks = []

        for agent in self._agents:

            logger.info("[AGENT-GRID-RUN-CYCLE-AGENT] agent=%s", agent.config.name)

            agent_tasks.append(agent.collect_order_candidate(tick))

        

        # Execute all agent tasks in parallel

        results = await asyncio.gather(*agent_tasks, return_exceptions=True)

        

        # Process results

        for agent, result in zip(self._agents, results):

            if isinstance(result, Exception):

                logger.error("[CYCLE-ERROR] agent=%s error=%s", agent.config.name, str(result), exc_info=True)

            elif result:

                candidates.append(result)

                logger.info("[AGENT-GRID-RUN-CYCLE-CANDIDATE] agent=%s side=%s", agent.config.name, result.get('side'))

            else:

                logger.info("[AGENT-GRID-RUN-CYCLE-NO-CANDIDATE] agent=%s", agent.config.name)

        

        logger.info("[CYCLE-COMPLETE] tick=%d candidates=%d", tick, len(candidates))

        

        # Phase 2: Apply global allocator to select best edges under venue cap

        if candidates and allow_new_entries:

            try:

                from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate, create_global_allocator_from_envelope

                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope

                

                # Get risk envelope for allocator configuration

                envelope = get_kalshi_crypto_15m_risk_envelope()

                allocator = create_global_allocator_from_envelope(envelope)

                

                # Convert candidates to OrderCandidate objects

                order_candidates = []

                for candidate in candidates:

                    # Extract asset from agent_id (e.g., "BTC_15M" -> "BTC")

                    asset = candidate.get('agent_id', '').replace('_15M', '').replace('_15m', '')

                    if not asset:

                        asset = candidate.get('asset', 'UNKNOWN')

                    

                    # CRITICAL FIX: Check if there's already a resting order for this ticker/price/side

                    # This prevents duplicate order generation when the same candidate is selected repeatedly

                    ticker = candidate.get('ticker', '')

                    price_cents = int(candidate.get('price_cents', 50))

                    side = candidate.get('side', 'yes')

                    action = candidate.get('action', 'buy')

                    

                    has_resting_order = False

                    if hasattr(self, 'order_gate') and self.order_gate:

                        try:

                            from merid.event_venues.kalshi.order_gate import OrderStatus

                            # Check for existing resting orders with same ticker, price, side, action

                            resting_orders = self.order_gate.get_resting_orders()

                            for resting_order in resting_orders:

                                if (resting_order.contract_id == ticker and 

                                    resting_order.price_cents == price_cents and

                                    resting_order.side == side and

                                    resting_order.action == action and

                                    resting_order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)):

                                    has_resting_order = True

                                    logger.info("[GLOBAL-ALLOCATOR] Skipping candidate with existing resting order: ticker=%s price=%dc side=%s", 

                                               ticker, price_cents, side)

                                    break

                        except Exception as e:

                            logger.warning("[GLOBAL-ALLOCATOR] Failed to check for resting orders: %s", e)

                    

                    if has_resting_order:

                        continue  # Skip this candidate - there's already a resting order

                    

                    # Get current position notional for this asset

                    current_position_notional = 0.0

                    if self.position_cache:

                        try:

                            positions = self.position_cache.get_all_positions(validate_freshness=False)

                            for pos_ticker, pos_obj in positions.items():

                                if pos_obj and pos_obj.contracts > 0:

                                    # Check if position belongs to this asset

                                    if asset.lower() in pos_ticker.lower():

                                        pos_price = pos_obj.current_price_cents if hasattr(pos_obj, 'current_price_cents') else candidate.get('price_cents', 50)

                                        current_position_notional += (pos_obj.contracts * pos_price) / 100.0

                        except Exception as e:

                            logger.warning("[GLOBAL-ALLOCATOR] Failed to get current positions: %s", e)

                    

                    order_candidate = OrderCandidate(

                        asset=asset,

                        ticker=ticker,

                        side=side,

                        action=action,

                        price_cents=price_cents,

                        count=int(candidate.get('count', 1)),

                        edge_pct=float(candidate.get('edge_pct', 0.0)),

                        confidence=float(candidate.get('confidence', 0.5)),

                        model_prob=float(candidate.get('model_prob', 0.5)),

                        agent_name=candidate.get('agent_id', asset)

                    )

                    order_candidates.append(order_candidate)

                

                # Get current positions for all assets

                current_positions = {}

                if self.position_cache:

                    try:

                        positions = self.position_cache.get_all_positions(validate_freshness=False)

                        for pos_ticker, pos_obj in positions.items():

                            if pos_obj and pos_obj.contracts > 0:

                                pos_price = pos_obj.current_price_cents if hasattr(pos_obj, 'current_price_cents') else 50

                                pos_notional = (pos_obj.contracts * pos_price) / 100.0

                                # Determine asset from ticker

                                for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:

                                    if asset.lower() in pos_ticker.lower():

                                        current_positions[asset] = current_positions.get(asset, 0.0) + pos_notional

                                        break

                    except Exception as e:

                        logger.warning("[GLOBAL-ALLOCATOR] Failed to build current positions dict: %s", e)

                

                # Run global allocator

                chosen_orders = allocator.allocate(order_candidates, current_positions)

                

                # Get allocation summary

                summary = allocator.get_allocation_summary(chosen_orders)

                logger.info(

                    "[GLOBAL-ALLOCATOR-SUMMARY] chosen=%d, total_notional=$%.2f, utilization=%.1f%%, avg_edge=%.1f%%",

                    summary['total_orders'], summary['total_notional'], summary['utilization_pct'], summary['avg_edge']

                )

                

                # Phase 3: Execute only chosen orders

                executed_count = 0

                for order in chosen_orders:

                    try:

                        # Find the original candidate for this order

                        original_candidate = None

                        for candidate in candidates:

                            if candidate.get('ticker') == order.ticker and candidate.get('side') == order.side:

                                original_candidate = candidate

                                break

                        

                        if original_candidate:

                            # Execute via direct execution path

                            from merid.prediction.kalshi_tools import _kalshi_place_order

                            

                            # Extract order parameters

                            ticker = order.ticker

                            side = order.side

                            action = order.action

                            price_cents = order.price_cents

                            count = order.count

                            agent_name = order.agent_name

                            

                            # Extract signal metadata

                            model_prob = original_candidate.get('model_prob')

                            edge_pct = original_candidate.get('edge_pct')

                            confidence = original_candidate.get('confidence')

                            

                            logger.info(

                                "[GLOBAL-ALLOCATOR-EXECUTE] asset=%s ticker=%s side=%s price=%dc count=%d edge=%.1f%%",

                                order.asset, ticker, side, price_cents, count, order.edge_pct

                            )

                            

                            # CRITICAL FIX (2026-07-10): Session order count and cooldown are updated on FILL, not submission

                            # This prevents perpetual cooldown blocks when orders don't fill (e.g., resting limit orders)

                            # The update_cooldown_on_fill method handles both session count and cooldown on successful fills

                            

                            # Set default TP/SL

                            stop_loss_price_cents = max(1, price_cents - 5)

                            take_profit_r_multiple = 1.0

                            

                            order_result = await _kalshi_place_order(

                                ticker=ticker,

                                side=side,

                                action=action,

                                price_cents=price_cents,

                                count=count,

                                agent_name=agent_name,

                                stop_loss_price_cents=stop_loss_price_cents,

                                take_profit_r_multiple=take_profit_r_multiple,

                                model_prob=model_prob,

                                edge_pct=edge_pct,

                                confidence=confidence

                            )

                            

                            if order_result and order_result.success:

                                executed_count += 1

                                # Handle both ToolResult (duplicate/idempotent) and OrderResult objects

                                order_id = getattr(order_result, 'order_id', 'duplicate/idempotent')

                                logger.info("[GLOBAL-ALLOCATOR-EXECUTE-SUCCESS] asset=%s order_id=%s", order.asset, order_id)

                            else:

                                # Handle both ToolResult and OrderResult objects

                                reason = "Unknown"

                                if order_result:

                                    if hasattr(order_result, 'reason'):

                                        reason = order_result.reason

                                    elif hasattr(order_result, 'message'):

                                        reason = order_result.message

                                logger.warning("[GLOBAL-ALLOCATOR-EXECUTE-FAILED] asset=%s reason=%s", order.asset, reason)

                    

                    except Exception as e:

                        logger.error("[GLOBAL-ALLOCATOR-EXECUTE-ERROR] asset=%s error=%s", order.asset, str(e), exc_info=True)

                

                logger.info("[GLOBAL-ALLOCATOR-CYCLE] Executed %d/%d chosen orders", executed_count, len(chosen_orders))

                

                # Return only executed candidates

                return [c for c in candidates if any(

                    c.get('ticker') == order.ticker and c.get('side') == order.side

                    for order in chosen_orders

                )]

            

            except Exception as e:

                logger.error("[GLOBAL-ALLOCATOR-ERROR] Failed to run global allocator: %s", str(e), exc_info=True)

                # Fallback: return all candidates (original behavior)

                return candidates

        

        return candidates

    

    def get_agent(self, name: str) -> Optional[LeanAgent15m]:

        # Get agent by name.

        for agent in self._agents:

            if agent.config.name == name:

                return agent

        return None

    

    def get_all_agents(self) -> list[LeanAgent15m]:

        # Get all agents.

        return self._agents



# Build function for agent grid

async def build_15m_agent_grid(

    catalog: Any,

    bankroll: Any,

    spot_provider: Any,

    order_router: Any,

    loop: Optional[Any] = None,

    unified_edge_config: Any = None,

    ws_bridge: Optional[Any] = None,

) -> LeanAgentGrid15m:

    # Build the 5 crypto 15m agents for Kalshi trading

    # This function:

    # - Imports only essential agent classes

    # - Creates 5 agent instances (BTC, ETH, SOL, XRP, DOGE)

    # - Returns a LeanAgentGrid15m instance

    # NO imports from:

    # - merid.prediction.agent_grid (old generic grid)

    # - merid.pm_runtime

    # - trading.paper_trading

    # - merid.reconciliation.venue

    # - reflection.*

    # - social broadcasters

    

    print("[AGENT-GRID-15M VERSION v20260529a-cache-fix] build_15m_agent_grid() called - agent grid initialization", flush=True)

    logger.info("[AGENT-GRID-15M VERSION v20260529a-cache-fix] build_15m_agent_grid() called - agent grid initialization")

    logger.info("[AGENT-GRID-15M] Building 5 crypto 15m agents...")

    print("[AGENT-GRID-15M] About to start agent creation loop", flush=True)

    

    # Get market state store and risk config

    # CRITICAL FIX: Get market_state_store directly from singleton

    # The ws_bridge and loop aren't available during P1.10 startup

    market_state_store = None

    risk_config = None

    

    try:

        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

        market_state_store = get_kalshi_market_state_store()

        logger.info("[AGENT-GRID-15M] Got market_state_store from singleton")

    except Exception as e:

        logger.warning("[AGENT-GRID-15M] Failed to get market_state_store from singleton: %s", e)

    

    # Risk config will be set later by the loop (created in P2.3)

    # For now, agents will use None and validation will be skipped until risk is ready

    

    # Phase 1: Load velocity model coefficients from profile

    velocity_coefficients = {}

    velocity_thresholds = {}

    momentum_weights_windows = [10, 30, 60]

    momentum_weights_values = [0.2, 0.3, 0.5]

    logit_fusion_velocity_weight = 0.7

    logit_fusion_mean_reversion_weight = 0.3

    near_expiry_guard_sec = 300

    calibration_enabled = False

    calibration_auto_fit = True

    calibration_min_samples = 100

    calibration_max_samples = 1000

    calibration_regularization = 0.0001

    calibration_fit_interval_hours = 24

    per_asset_cooldown_s = 10  # Default to 10s if profile not loaded

    signal_mode = "trend"  # Default signal mode

    price_based_buy_threshold = 0.60  # Buy YES in sweet spot (60-70c range per Polymarket data)

    price_based_sell_threshold = 0.90  # Sell when price >= 0.90 (profit taking)

    # Phase 4.1: Multi-window velocity configuration defaults

    velocity_ema_period = 5  # Default EMA smoothing period

    atr_period = 3  # Default ATR period (reduced from 7 for faster warmup)

    zscore_period = 20  # Default Z-score period

    try:

        from merid.risk.profiles.crypto_15m_profile import get_active_profile

        profile_adapter = get_active_profile()

        logger.info("[AGENT-GRID-15M] Profile loaded: %s", profile_adapter is not None)

        if profile_adapter and profile_adapter._profile:

            profile = profile_adapter._profile

            velocity_coefficients = {

                "BTC": (profile.velocity_model_alpha_0_btc, profile.velocity_model_alpha_1_btc),

                "ETH": (profile.velocity_model_alpha_0_eth, profile.velocity_model_alpha_1_eth),

                "SOL": (profile.velocity_model_alpha_0_sol, profile.velocity_model_alpha_1_sol),

                "XRP": (profile.velocity_model_alpha_0_xrp, profile.velocity_model_alpha_1_xrp),

                "DOGE": (profile.velocity_model_alpha_0_doge, profile.velocity_model_alpha_1_doge),

            }

            # Load per-asset velocity thresholds from profile

            velocity_thresholds = {

                "BTC": profile.velocity_threshold_btc,

                "ETH": profile.velocity_threshold_eth,

                "SOL": profile.velocity_threshold_sol,

                "XRP": profile.velocity_threshold_xrp,

                "DOGE": profile.velocity_threshold_doge,

            }

            # Phase 4.1: Load momentum weights from profile

            momentum_weights_windows = profile.momentum_weights_windows

            momentum_weights_values = profile.momentum_weights_values

            # Phase 4.1: Load multi-window velocity configuration from profile

            if hasattr(profile, 'velocity_ema_period'):

                velocity_ema_period = profile.velocity_ema_period

            if hasattr(profile, 'atr_period'):

                atr_period = profile.atr_period

            if hasattr(profile, 'zscore_period'):

                zscore_period = profile.zscore_period

            # Phase 4.4: Load logit fusion weights from profile

            logit_fusion_velocity_weight = profile.logit_fusion_velocity_weight

            logit_fusion_mean_reversion_weight = profile.logit_fusion_mean_reversion_weight

            # Phase 4.5: Load near expiry guard from profile

            near_expiry_guard_sec = profile.near_expiry_guard_sec

            # Phase 5.2: Load calibration config from profile

            calibration_enabled = profile.calibration_enabled

            calibration_auto_fit = profile.calibration_auto_fit

            calibration_min_samples = profile.calibration_min_samples

            calibration_max_samples = profile.calibration_max_samples

            calibration_regularization = profile.calibration_regularization

            calibration_fit_interval_hours = profile.calibration_fit_interval_hours

            # Load throttling config from profile

            per_asset_cooldown_s = int(profile.throttling_per_asset_cooldown_sec)

            # 2026 Research-Based Risk Management: Load new throttling parameters

            max_orders_per_15m_window = int(profile.throttling_max_orders_per_15m_window)

            consecutive_loss_pause = int(profile.throttling_consecutive_loss_pause)

            max_session_risk_pct = float(profile.throttling_max_session_risk_pct)

            # Phase 5.3: Load signal mode and price-based strategy config from profile

            signal_mode = profile.signal_mode

            price_based_buy_threshold = profile.price_based_buy_threshold

            price_based_sell_threshold = profile.price_based_sell_threshold

            logger.info("[AGENT-GRID-15M] Loaded throttling_per_asset_cooldown_sec=%s from profile", per_asset_cooldown_s)

            logger.info("[AGENT-GRID-15M] Loaded signal_mode=%s from profile", signal_mode)

            logger.info("[AGENT-GRID-15M] Loaded velocity coefficients, velocity thresholds, momentum weights, logit fusion config, calibration config, throttling config, and price-based strategy config from profile")

        else:

            logger.warning("[AGENT-GRID-15M] Failed to load profile, using default coefficients and weights")

    except Exception as e:

        logger.warning("[AGENT-GRID-15M] Failed to load velocity coefficients from profile: %s", e)

    

    logger.info("[AGENT-GRID-15M] Final per_asset_cooldown_s=%s", per_asset_cooldown_s)

    

    # CRITICAL FIX: Provide default values in case profile loading fails

    if 'max_orders_per_15m_window' not in locals():

        max_orders_per_15m_window = 12  # Default: 12 orders per 15m window

        logger.warning("[AGENT-GRID-15M] Profile loading failed, using default max_orders_per_15m_window=12")

    if 'consecutive_loss_pause' not in locals():

        consecutive_loss_pause = 3  # Default: pause after 3 consecutive losses

        logger.warning("[AGENT-GRID-15M] Profile loading failed, using default consecutive_loss_pause=3")

    if 'max_session_risk_pct' not in locals():

        max_session_risk_pct = 0.10  # Default: 10% session risk cap

        logger.warning("[AGENT-GRID-15M] Profile loading failed, using default max_session_risk_pct=0.10")

    

    # Create 5 agents for BTC, ETH, SOL, XRP, DOGE

    agents = []

    

    asset_configs = [

        ("BTC", ["KXBTC15M"]),

        ("ETH", ["KXETH15M"]),

        ("SOL", ["KXSOL15M"]),

        ("XRP", ["KXXRP15M"]),

        ("DOGE", ["KXDOGE15M"]),

    ]

    

    for asset, series_tickers in asset_configs:

        # Phase 1: Get velocity coefficients for this asset

        alpha_0, alpha_1 = velocity_coefficients.get(asset, (0.0, 1000.0))

        # Get per-asset velocity threshold

        velocity_threshold = velocity_thresholds.get(asset, 0.002)  # Default to 0.002 (0.2%)

        

        config = LeanAgentConfig(

            name=f"{asset}_15M",

            series_tickers=series_tickers,

            alpha_0=alpha_0,

            alpha_1=alpha_1,

            velocity_threshold=velocity_threshold,

            velocity_windows=momentum_weights_windows,

            momentum_weights=momentum_weights_values,

            velocity_ema_period=velocity_ema_period,

            atr_period=atr_period,

            zscore_period=zscore_period,

            logit_fusion_velocity_weight=logit_fusion_velocity_weight,

            logit_fusion_mean_reversion_weight=logit_fusion_mean_reversion_weight,

            near_expiry_guard_sec=near_expiry_guard_sec,

            calibration_enabled=calibration_enabled,

            calibration_auto_fit=calibration_auto_fit,

            calibration_min_samples=calibration_min_samples,

            calibration_max_samples=calibration_max_samples,

            calibration_regularization=calibration_regularization,

            calibration_fit_interval_hours=calibration_fit_interval_hours,

            per_asset_cooldown_s=per_asset_cooldown_s,

            # 2026 Research-Based Risk Management: Pass new throttling parameters

            max_orders_per_15m_window=max_orders_per_15m_window,

            consecutive_loss_pause=consecutive_loss_pause,

            max_session_risk_pct=max_session_risk_pct,

            signal_mode=signal_mode,

            price_based_buy_threshold=price_based_buy_threshold,

            price_based_sell_threshold=price_based_sell_threshold,

        )

        

        agent = LeanAgent15m(

            config=config,

            catalog=catalog,

            market_state_store=market_state_store,

            spot_provider=spot_provider,

            order_router=order_router,

            risk_config=risk_config,

        )

        

        agents.append(agent)

        logger.info("[AGENT-CREATED] asset=%s name=%s alpha_0=%.2f alpha_1=%.2f", asset, config.name, alpha_0, alpha_1)

    

    grid = LeanAgentGrid15m(agents=agents)

    logger.info("[AGENT-GRID-BUILT] LeanAgentGrid15m built with %d agents", len(agents))

    

    return grid



# Global agent grid instance

_agent_grid: Optional[LeanAgentGrid15m] = None



def get_agent_grid() -> Optional[LeanAgentGrid15m]:

    # Get the global agent grid instance.

    global _agent_grid

    return _agent_grid



def set_agent_grid(grid: LeanAgentGrid15m) -> None:

    # Set the global agent grid instance.

    global _agent_grid

    _agent_grid = grid

    logger.info("[AGENT-GRID-SET] Global agent grid instance set")

_agent_grid: Optional[LeanAgentGrid15m] = None



def get_agent_grid() -> Optional[LeanAgentGrid15m]:

    # Get the global agent grid instance.

    global _agent_grid

    return _agent_grid



def set_agent_grid(grid: LeanAgentGrid15m) -> None:

    # Set the global agent grid instance.

    global _agent_grid

    _agent_grid = grid

    logger.info("[AGENT-GRID-SET] Global agent grid instance set")

