from __future__ import annotations

from datetime import datetime as dt, timezone, timedelta
import time
import collections
import re
from typing import Any, Optional, Dict
from dataclasses import dataclass, field

from utils.logger import get_logger

logger = get_logger("merid.prediction.agent_grid_15m")

# Lean AgentGrid for Kalshi 15m Crypto Trading.
# This module provides a minimal, focused agent grid for 15-minute crypto trading.
# It uses Coinbase velocity-based signals (2026 #1 winning strategy) and simplified gates.
# See docs/15M_STACK_SURFACE.md for complete allowed surface definition.

from merid.config.environment import enable_composite_spot_fallback

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
    (market.market_id, close_time, etc.) without requiring a full catalog lookup.
    """
    market_id: str
    close_time: float  # Unix timestamp
    asset: str
    
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
    max_spread_cents: int = 100  # Maximum spread in cents
    min_time_to_expiry_s: int = 180  # Minimum time to expiry in seconds
    max_time_to_expiry_s: int = 900  # Maximum time to expiry in seconds
    per_strip_order_limit: int = 50  # Maximum orders per 15m strip (increased from 5 to allow more trading)
    per_asset_cooldown_s: int = 10  # Cooldown period in seconds after trade (reduced from 30s to allow more frequent trading)
    velocity_threshold: float = 0.002  # Velocity threshold for signal generation (0.2% - aligned with industry standards for 15m crypto trading)
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
    max_volatility_threshold: float = 0.02  # Maximum 2% volatility to avoid extreme volatility spikes
    # DYNAMIC SPREAD THRESHOLD: Volatility-regime-based spread filtering (2026 best practice)
    # Based on research: "Blow your spreads out when the market's volatility does"
    # Uses 3 regimes with different spread limits: calm, elevated, violent
    calm_volatility_threshold: float = 0.005  # 0.5% volatility = calm regime
    elevated_volatility_threshold: float = 0.015  # 1.5% volatility = elevated regime
    calm_spread_threshold_bp: int = 50  # 50bp max spread in calm regime
    elevated_spread_threshold_bp: int = 100  # 100bp max spread in elevated regime
    violent_spread_threshold_bp: int = 150  # 150bp max spread in violent regime
    spread_volatility_sensitivity: float = 1.5  # Lambda parameter for continuous interpolation
    # Phase 1: Velocity model coefficients for logistic mapping
    alpha_0: float = 0.0  # Intercept for logistic function
    alpha_1: float = 1000.0  # Velocity coefficient for logistic function
    # Phase 4.1: Multi-window velocity configuration
    velocity_windows: list = field(default_factory=lambda: [10, 30, 60])  # Velocity windows in seconds
    momentum_weights: list = field(default_factory=lambda: [0.2, 0.3, 0.5])  # Weights for each window
    velocity_ema_period: int = 5  # EMA smoothing period for velocity (reduces noise)
    atr_period: int = 14  # ATR period for volatility normalization (industry standard)
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
        
        # Initialize price history for velocity calculation (2-minute window)
        self._spot_price_history: Dict[str, collections.deque] = {}
        self._price_history_window_size = 120  # 2 minutes at 1-second intervals
        
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
        self._volatility_history: Dict[str, collections.deque] = {}
        self._volatility_window_size = self._atr_period  # Keep ATR period worth of volatility data
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._volatility_history[asset] = collections.deque(maxlen=self._volatility_window_size)
        
        # Phase 4.1: Initialize velocity history for Z-score calculation
        self._velocity_zscore_history: Dict[str, collections.deque] = {}
        self._zscore_window_size = self._zscore_period  # Keep Z-score period worth of velocity data
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._velocity_zscore_history[asset] = collections.deque(maxlen=self._zscore_window_size)
        
        # Cooldown tracking: last trade timestamp per asset
        self._last_trade_time: Dict[str, float] = {}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._last_trade_time[asset] = 0.0
        
        # Per-strip order limit tracking (15m strip = series ticker)
        self._strip_order_counts: Dict[str, int] = {}
        for ticker in self.config.series_tickers:
            self._strip_order_counts[ticker] = 0
        
        # Track current market ID per strip to detect when to reset counters
        self._current_market_ids: Dict[str, str] = {}
        for ticker in self.config.series_tickers:
            self._current_market_ids[ticker] = None
        
        logger.info("[AGENT-INIT] %s initialized with velocity-based signal strategy", config.name)
    
    def _update_price_history(self, asset: str, spot_price: float) -> None:
        # Update price history for velocity calculation.
        current_time = time.time()
        self._spot_price_history[asset].append((current_time, spot_price))
        
        # Phase 4.3: Update SMA history for mean reversion
        self._sma_history[asset].append((current_time, spot_price))
        
        # Phase 4.1: Update volatility history for ATR calculation
        self._update_volatility_history(asset, spot_price)
    
    def _update_volatility_history(self, asset: str, spot_price: float) -> None:
        # Update volatility history for ATR calculation.
        # ATR uses high-low range, but for spot prices we use price changes as proxy.
        current_time = time.time()
        history = list(self._spot_price_history[asset])
        
        if len(history) < 2:
            return
        
        # Calculate price change as proxy for high-low range
        prev_price = history[-1][1]
        price_change = abs(spot_price - prev_price)
        
        self._volatility_history[asset].append((current_time, price_change))
    
    def _calculate_atr(self, asset: str) -> float:
        # Calculate Average True Range (ATR) for volatility normalization.
        # Uses price changes as proxy for high-low range (spot prices don't have OHLC).
        # Returns ATR as percentage of current price.
        history = list(self._volatility_history[asset])
        if len(history) < self._atr_period:
            return 0.0
        
        # Get recent price changes
        recent_changes = [price for ts, price in history[-self._atr_period:]]
        
        # Calculate ATR as average of recent changes
        atr = sum(recent_changes) / len(recent_changes)
        
        # Get current price for normalization
        price_history = list(self._spot_price_history[asset])
        if len(price_history) == 0:
            return 0.0
        
        current_price = price_history[-1][1]
        if current_price <= 0:
            return 0.0
        
        # Return ATR as percentage of current price
        atr_pct = atr / current_price
        return atr_pct
    
    def _calculate_velocity(self, asset: str, current_price: float) -> float:
        # Calculate 15-second velocity from price history (optimized for spot price update frequency).
        # Spot prices refresh every 2-3s, so 15s window provides ~5-7 data points for reliable velocity calculation.
        # Returns velocity as percentage change.
        history = list(self._spot_price_history[asset])
        if len(history) < 2:
            return 0.0
        
        current_time = time.time()
        target_time = current_time - 15.0  # 15 seconds ago (optimized for 2-3s spot price updates)
        
        prev_price = None
        for ts, price in reversed(history):
            if ts <= target_time:
                prev_price = price
                break
        
        if prev_price is None or prev_price <= 0:
            return 0.0
        
        velocity = (current_price - prev_price) / prev_price
        return velocity
    
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
        
        return {
            "side": signal_side,
            "action": signal_action,
            "price_cents": int(market_price * 100),
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
        history = list(self._spot_price_history[asset])
        if len(history) < 2:
            return 0.0
        
        current_time = time.time()
        weighted_velocity = 0.0
        
        for window_sec, weight in zip(self._velocity_windows, self._momentum_weights):
            target_time = current_time - window_sec
            
            prev_price = None
            for ts, price in reversed(history):
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
        # Apply ATR-based volatility normalization to velocity.
        # Normalizes velocity by current volatility to create dynamic thresholds.
        # Formula: normalized_velocity = velocity / (ATR + epsilon)
        # This makes the signal adaptive to market volatility (industry standard).
        atr = self._calculate_atr(asset)
        
        if atr <= 0.0001:  # Avoid division by zero or extreme values
            return velocity  # Return unnormalized if ATR is too small
        
        # Normalize velocity by ATR
        normalized_velocity = velocity / atr
        
        return normalized_velocity
    
    def _calculate_zscore(self, asset: str, value: float) -> float:
        # Calculate Z-score for extreme detection (industry standard).
        # Z-score measures how many standard deviations a value is from the mean.
        # Formula: zscore = (value - mean) / std
        # Z-score > 2.0 = overbought, Z-score < -2.0 = oversold
        history = list(self._velocity_zscore_history[asset])
        if len(history) < self._zscore_period:
            return 0.0  # Not enough data for Z-score
        
        # Get recent values
        recent_values = [val for ts, val in history[-self._zscore_period:]]
        
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
    
    def _calculate_mean_reversion(self, asset: str, current_price: float) -> float:
        # Phase 4.3: Calculate mean reversion signal using 2-minute SMA.
        # Returns deviation from SMA as percentage (positive = above SMA, negative = below SMA).
        history = list(self._sma_history[asset])
        if len(history) < 2:
            return 0.0
        
        # Calculate 2-minute SMA
        current_time = time.time()
        target_time = current_time - 120.0  # 2 minutes ago
        
        prices_in_window = []
        for ts, price in history:
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
        if minutes_to_expiry * 60 < self._near_expiry_guard_sec:
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
        Calculate dynamic spread threshold based on volatility regime.
        
        2026 best practice: "Blow your spreads out when the market's volatility does"
        Uses continuous interpolation between regime anchors for smooth transitions.
        
        Formula: spread_t = base_width * (sigma_t / sigma_bar)^lambda
        
        Returns:
            int: Dynamic spread threshold in basis points
        """
        regime, volatility = self._classify_volatility_regime(ticker)
        
        # Get regime-specific thresholds
        if regime == "calm":
            threshold_bp = self.config.calm_spread_threshold_bp
        elif regime == "elevated":
            threshold_bp = self.config.elevated_spread_threshold_bp
        else:  # violent
            threshold_bp = self.config.violent_spread_threshold_bp
        
        # Apply continuous interpolation for smooth transitions
        # Use volatility ratio to interpolate between regimes
        calm_threshold = self.config.calm_volatility_threshold
        elevated_threshold = self.config.elevated_volatility_threshold
        
        if regime == "calm":
            # Interpolate between calm and elevated
            ratio = volatility / calm_threshold
            interpolated = self.config.calm_spread_threshold_bp * (ratio ** self.config.spread_volatility_sensitivity)
            threshold_bp = min(int(interpolated), self.config.elevated_spread_threshold_bp)
        elif regime == "elevated":
            # Interpolate between elevated and violent
            ratio = volatility / elevated_threshold
            base = self.config.elevated_spread_threshold_bp
            target = self.config.violent_spread_threshold_bp
            interpolated = base * (ratio ** self.config.spread_volatility_sensitivity)
            threshold_bp = min(int(interpolated), target)
        # violent regime uses maximum threshold
        
        logger.debug("[DYNAMIC-SPREAD] asset=%s ticker=%s regime=%s threshold=%dbp volatility=%.4f",
                    self.config.name, ticker, regime, threshold_bp, volatility)
        
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
        # Fallback to sensible defaults if envelope not available
        min_depth_yes_threshold = 1
        min_depth_no_threshold = 1
        
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            depth_thresholds = envelope.get_depth_thresholds(asset)
            min_depth_yes_threshold = depth_thresholds.get('min_depth_yes', 1)
            min_depth_no_threshold = depth_thresholds.get('min_depth_no', 1)
        except Exception:
            # Fallback to defaults if envelope not available
            pass
        
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
        
        # Log regime for visibility - one-sided books are now acceptable
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
            # INDUSTRY ALIGNMENT: Convert spread to basis points for regime-aware validation
            # Use mid price as reference for bp calculation
            mid_price_cents = (best_bid + best_ask) / 2
            if mid_price_cents > 0:
                spread_bp = (spread_cents / mid_price_cents) * 100
                # 2026 BEST PRACTICE: Use dynamic spread threshold based on volatility regime
                # "Blow your spreads out when the market's volatility does"
                dynamic_threshold_bp = self._get_dynamic_spread_threshold(ticker)
                if spread_bp > dynamic_threshold_bp:
                    logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s spread too wide=%.1fbp > dynamic_max=%dbp (cents=%d regime=%s)",
                                 self.config.name, ticker, spread_bp, dynamic_threshold_bp, spread_cents,
                                 self._classify_volatility_regime(ticker)[0])
                    return False
                logger.info("[MARKET-VALIDATION] asset=%s ticker=%s spread OK=%.1fbp <= dynamic_max=%dbp (cents=%d regime=%s)",
                           self.config.name, ticker, spread_bp, dynamic_threshold_bp, spread_cents,
                           self._classify_volatility_regime(ticker)[0])
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
        
        # Extract asset from market
        asset = None
        if hasattr(market, 'asset'):
            asset = market.asset
        elif hasattr(market, 'ticker'):
            ticker = market.ticker
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
        
        # Price history already updated in collect_order_candidate (before calling _generate_signal)
        # This prevents the vicious cycle: no signal -> no price update -> velocity=0 -> no signal
        
        # PRICE-BASED STRATEGY (Turbine research winner: +56.6% ROI)
        # Buy YES when price <= 0.50, sell when price >= 0.70
        if self.config.signal_mode == "price_based":
            return self._generate_price_based_signal(asset, spot_price, market, minutes_to_expiry)
        
        # Calculate velocity
        velocity = self._calculate_velocity(asset, spot_price)
        
        logger.info(
            "[VELOCITY-CALC] asset=%s current=%.2f prev=%.2f velocity=%.6f (%.2f%%)",
            asset, spot_price, spot_price / (1 + velocity) if velocity != 0 else spot_price, velocity, velocity * 100
        )
        
        # VELOCITY-BASED SIGNAL DECISION (2026 #1 winner)
        # Positive velocity (> threshold) -> buy YES
        # Negative velocity (< -threshold) -> buy NO
        # Small velocity (between -threshold and threshold) -> no trade
        velocity_threshold = self.config.velocity_threshold  # Use configurable threshold
        
        if velocity > velocity_threshold:
            # Positive momentum -> buy YES
            signal_side = "yes"
            signal_action = "buy"
            logger.info(
                "[VELOCITY-SIGNAL] asset=%s velocity=%.6f > threshold=%.6f -> BUY YES",
                asset, velocity, velocity_threshold
            )
        elif velocity < -velocity_threshold:
            # Negative momentum -> buy NO
            signal_side = "no"
            signal_action = "buy"
            logger.info(
                "[VELOCITY-SIGNAL] asset=%s velocity=%.6f < -threshold=%.6f -> BUY NO",
                asset, velocity, velocity_threshold
            )
        else:
            # Insufficient momentum -> no trade
            logger.info(
                "[VELOCITY-SIGNAL] asset=%s velocity=%.6f within ±threshold=%.6f -> NO TRADE (insufficient momentum)",
                asset, velocity, velocity_threshold
            )
            return None
        
        # 2026 SIMPLIFIED GATES: Skip complex indicator gates (velocity IS the signal)
        # Removed: vol_gate, atr_move, chop_gate, trend_aligned, RSI zones, OBI, FVG
        # Kept only: liquidity, spread, staleness (essential for 15m trading)
        logger.info(
            "[SIGNAL-GATE-SKIP] asset=%s skipping complex indicator gates (velocity-based signal)",
            asset
        )
        
        # 2026 VELOCITY OVERRIDE: Use velocity-based side decision instead of edge-based
        # The velocity signal already determined the trade direction (YES/NO)
        # Skip the complex edge-based selection logic
        try:
            side = signal_side  # Use velocity-based decision
            logger.info(
                "[VELOCITY-SIDE-OVERRIDE] asset=%s using velocity-based side=%s (overriding edge-based selection)",
                asset, side
            )
            
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
            
        except Exception as e:
            logger.error("[CRASH-POST-VELOCITY] asset=%s error=%s", asset, str(e), exc_info=True)
            return None
        
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
        
        # Apply logistic function to get model probability
        try:
            p_model = 1.0 / (1.0 + math.exp(-raw_logit))
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
        
        # CROSS-PHASE: Validate p_model is in reasonable range
        if not (0.0 <= p_model <= 1.0):
            logger.error("[SIGNAL-GEN] asset=%s p_model=%.4f outside valid range [0,1], skipping signal",
                        asset, p_model)
            return None
        
        # Compute edge as difference between model and market probability
        # Edge is in percentage points
        edge_pct = (p_model - p_mkt) * 100.0
        
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
        
        # Construct signal dictionary
        signal = {
            "asset": asset,
            "side": side,
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
            "regime": regime,  # Phase 2: Regime classification from market state
            "rationale": f"velocity_based: velocity={velocity:.6f} edge_pct={edge_pct:.2f}%",  # CRITICAL: Add rationale for velocity-based strategy
        }
        
        logger.info("[SIGNAL-GENERATED] asset=%s side=%s velocity=%.6f edge_pct=%.2f%% confidence=%.2f model_prob=%.2f", 
                   asset, side, velocity, edge_pct, confidence, model_prob)
        return signal
    
    async def collect_order_candidate(self, tick: int) -> Optional[Dict[str, Any]]:
        # Collect order candidate for this agent.
        try:
            # Get spot price from unified spot service
            asset = self.config.name.split('_')[0]
            
            # Check cooldown
            current_time = time.time()
            last_trade = self._last_trade_time.get(asset, 0.0)
            time_since_last_trade = current_time - last_trade
            if time_since_last_trade < self.config.per_asset_cooldown_s:
                logger.info("[COOLDOWN-CHECK] asset=%s in cooldown=%.1fs < required=%ds",
                           asset, time_since_last_trade, self.config.per_asset_cooldown_s)
                return None
            
            spot_price = None
            
            # Try different methods depending on spot provider interface
            if hasattr(self.spot_provider, 'get_spot_price'):
                spot_price = await self.spot_provider.get_spot_price(asset)
            elif hasattr(self.spot_provider, 'get'):
                result = self.spot_provider.get(asset)
                if hasattr(result, 'price'):
                    spot_price = result.price
            elif hasattr(self.spot_provider, 'get_spot'):
                result = await self.spot_provider.get_spot(asset)
                if hasattr(result, 'price_usd'):
                    spot_price = result.price_usd
            
            if not spot_price:
                logger.warning("[SPOT-ERROR] asset=%s no spot price available", self.config.name)
                return None
            
            # CRITICAL FIX: Update price history BEFORE signal generation
            # This ensures velocity calculation has fresh data even if no signal is generated
            # Previously, price history was only updated in _generate_signal, creating a vicious cycle:
            # no signal -> no price update -> velocity=0 -> no signal
            self._update_price_history(asset, spot_price)
            
            # Get market from market state store - use available markets instead of computing from time
            market = None
            try:
                # Extract asset from agent name (e.g., "BTC_15M" -> "BTC")
                asset = self.config.name.split("_")[0]
                
                # Query market state store for available markets for this asset
                # This works with whatever markets are actually subscribed via WebSocket
                if self.market_state_store:
                    # Get all market IDs in the store
                    all_tickers = list(self.market_state_store._states.keys())
                    
                    # Find tickers matching this asset's series
                    series_prefix = self.config.series_tickers[0] if self.config.series_tickers else f"KX{asset}15M"
                    matching_tickers = [t for t in all_tickers if t.startswith(series_prefix)]
                    
                    if matching_tickers:
                        # CRITICAL FIX: Sort tickers by expiration time to pick the most recent non-expired market
                        # Extract expiration time from ticker suffix (e.g., 26JUN281730-30 -> 17:30 UTC)
                        def extract_expiration_time(ticker):
                            # Parse ticker format: KXASSET15M-YYMMMDDHHMM-SS
                            match = re.search(r'-(\d{2}[A-Z]{3}\d{2})(\d{2})(\d{2})-(\d{2})', ticker)
                            if match:
                                day_str = match.group(1)  # e.g., 26JUN28
                                hour = int(match.group(2))  # e.g., 17
                                minute = int(match.group(3))  # e.g., 30
                                second = int(match.group(4))  # e.g., 00
                                
                                # Parse day_str to datetime
                                try:
                                    # Format: DDMMMYY -> 26JUN26
                                    day_part = day_str[:2]
                                    month_part = day_str[2:5]
                                    year_part = day_str[5:7]
                                    year = 2000 + int(year_part)
                                    
                                    month_map = {
                                        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                                        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
                                    }
                                    month = month_map.get(month_part, 1)
                                    day = int(day_part)
                                    
                                    # Use exp_dt to avoid shadowing module-level datetime
                                    exp_dt = dt(year, month, day, hour, minute, second, tzinfo=timezone.utc)
                                    return exp_dt
                                except Exception:
                                    return None
                            return None
                        
                        # Sort tickers by expiration time (most recent first)
                        now_utc = dt.now(timezone.utc)
                        sorted_tickers = sorted(
                            matching_tickers,
                            key=lambda t: (extract_expiration_time(t) or dt.min),
                            reverse=True
                        )
                        
                        # Pick the first ticker that hasn't expired
                        ticker = None
                        for sorted_ticker in sorted_tickers:
                            exp_time = extract_expiration_time(sorted_ticker)
                            if exp_time and exp_time > now_utc:
                                ticker = sorted_ticker
                                break
                        
                        # Fallback to first ticker if all expired (shouldn't happen with proper catalog refresh)
                        if not ticker and sorted_tickers:
                            ticker = sorted_tickers[0]
                        
                        market_state = self.market_state_store.get(ticker)
                        
                        if market_state:
                            # Create MinimalMarket wrapper for compatibility
                            # Use expiration_time from market state if available, otherwise compute from ticker
                            close_time_ts = getattr(market_state, 'expected_expiration_time', None)
                            if close_time_ts is None:
                                # Fallback: compute close_time from current time + 15 minutes
                                close_time_ts = time.time() + 900
                            
                            market = MinimalMarket(
                                market_id=ticker,
                                close_time=close_time_ts,
                                asset=asset
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
            
            # Calculate minutes to expiry
            minutes_to_expiry = 0
            if hasattr(market, 'close_time'):
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
                "edge_pct": signal.get("edge_pct", 0.0),  # BUG #36 FIX: Carry edge from signal
                "confidence": signal.get("confidence", 0.5),  # BUG #36 FIX: Carry confidence from signal
                "model_prob": signal.get("model_prob", 0.5),  # BUG #36 FIX: Carry model_prob from signal
                "rationale": signal.get("rationale"),  # CRITICAL: Carry rationale to skip edge validation for price-based strategy
                "regime": signal.get("regime", "normal"),  # Phase 2: Carry regime from signal
                # CRITICAL FIX: Add exit targets to satisfy "no trade without exit" invariant
                "take_profit_r_multiple": 0.5,  # 0.5R take profit (conservative)
                "stop_loss_r_multiple": 0.25,  # 0.25R stop loss (tight risk control)
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
                        candidate["yes_depth"] = getattr(market_state, 'min_depth_yes', None)
                        candidate["no_depth"] = getattr(market_state, 'min_depth_no', None)
            except Exception as e:
                logger.warning("[CANDIDATE-MICROSTRUCTURE] Failed to populate microstructure data: %s", e)
            
            # Update cooldown timestamp
            self._last_trade_time[asset] = time.time()
            
            # Update strip order count
            if strip_ticker:
                self._strip_order_counts[strip_ticker] = self._strip_order_counts.get(strip_ticker, 0) + 1
                logger.info(
                    "[STRIP-ORDER-COUNT] asset=%s strip=%s orders=%d/%d",
                    asset, strip_ticker, self._strip_order_counts[strip_ticker], self.config.per_strip_order_limit
                )
            
            logger.info("[CANDIDATE-GENERATED] asset=%s side=%s", self.config.name, signal["side"])
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
        # Initialize strip order tracking
        self._strip_order_counts: Dict[str, int] = {}
        self._current_market_ids: Dict[str, str] = {}
        logger.info("[AGENT-GRID-INIT] LeanAgentGrid15m initialized with %d agents", len(agents))
    
    def set_market_state_store(self, market_state_store: Any) -> None:
        # Set the market state store after initialization.
        # This is called after the WS bridge starts and has the store available.
        self._market_state_store = market_state_store
        # Update all agents with the new store
        for agent in self._agents:
            agent.market_state_store = market_state_store
        logger.info("[AGENT-GRID] Market state store set for %d agents", len(self._agents))
    
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
        # This is called at the beginning of each cycle to ensure fresh data.
        logger.info("[AGENT-GRID] BEFORE sync_from_rest tick=%d", tick)
        
        # In production, this would refresh the catalog from Kalshi REST API
        # For now, we rely on the catalog being refreshed by the main loop
        # and the market state store being populated by WebSocket
        
        logger.info("[AGENT-GRID] AFTER sync_from_rest tick=%d", tick)
    
    async def run_cycle(self, tick: int, allow_new_entries: bool = True) -> list[Dict[str, Any]]:
        # Run a single trading cycle across all agents.
        logger.info("[AGENT-GRID-RUN-CYCLE] tick=%d allow_new_entries=%s agents=%d", tick, allow_new_entries, len(self._agents))
        
        # Sync from REST at the beginning of each cycle
        await self.sync_from_rest(tick)
        
        candidates = []
        
        for agent in self._agents:
            try:
                logger.debug("[AGENT-GRID-RUN-CYCLE-AGENT] agent=%s", agent.config.name)
                candidate = await agent.collect_order_candidate(tick)
                if candidate:
                    candidates.append(candidate)
                    logger.info("[AGENT-GRID-RUN-CYCLE-CANDIDATE] agent=%s side=%s", agent.config.name, candidate.get('side'))
            except Exception as e:
                logger.error("[CYCLE-ERROR] agent=%s error=%s", agent.config.name, str(e), exc_info=True)
        
        logger.info("[CYCLE-COMPLETE] tick=%d candidates=%d", tick, len(candidates))
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
