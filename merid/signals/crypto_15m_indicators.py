"""
Crypto 15-Minute Indicator Stack
=================================
Unified feature vector for Kalshi 15-minute crypto Up/Down agents.

Computes from a rolling 1-minute price buffer (fed by spot price proxies):

  1. **Trend baseline** — EMA(50) regime filter + EMA(5)/EMA(20) crossover on 1m candles
  2. **Momentum/overextension** — RSI(8) + MACD(8,21,5) + distance-from-EMA in ATR units
  3. **Volatility gate** — 30-60 min realized vol band + ATR(14) + ATR min-move gate
  4. **Chop filters** — consecutive closes, MACD persistence, histogram magnitude
  5. **Liquidity filter** — spread width and depth thresholds
  6. **Fee-aware EV** — mid-curve penalty, per-trade fee calculator
  7. **Backtest logging** — all fields needed for replay and Monte Carlo

IMPORTANT: This stack uses spot price feeds (CoinGecko/Coinbase/Binance) as PROXIES
for market context. Kalshi contracts settle on CF Benchmarks Real-Time Indices (RTIs),
not these single-exchange spot prices. Use these indicators for directional bias only,

Reference: https://www.cfbenchmarks.com/blog/kalshi-leads-surging-crypto-event-contract-market-powered-by-cf-benchmarks

Usage::

    from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack

    stack = Crypto15mIndicatorStack()

    # Feed 1-minute close prices as they arrive:
    stack.update(price=87450.0)

    # Get the current indicator snapshot:
    snap = stack.snapshot()
    if snap.trade_allowed:
        ...  # proceed with edge evaluation
"""

from __future__ import annotations

import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional
from datetime import datetime, timezone

import logging

logger = logging.getLogger("merid.prediction.agent_grid_15m")


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class IndicatorConfig:
    """Tunable parameters for the 15-minute indicator stack.
    
    OPTIMIZED (2026-05-10): Asset-specific configurations for EMA, ATR, and chop filters.
    Hybrid approach: BTC/ETH use faster EMAs (9/21), SOL/XRP/DOGE use slower EMAs (13/34).
    
    KALSHI MODE: When kalshi_mode=True, use lenient thresholds for prediction markets.
    Kalshi prediction markets are binary contracts, not continuous price instruments.
    They don't have the same volatility characteristics as spot markets.
    """

    # ── Asset identifier for parameter lookup ─────────────────────────
    asset: str = "BTC"  # BTC, ETH, SOL, XRP, DOGE
    kalshi_mode: bool = False  # Use lenient thresholds for Kalshi prediction markets

    # ── Trend Baselines (EMA crossovers) ──────────────────────────────────
    # NOTE: 21/34 EMA used for trend direction (bullish/bearish crossover)
    # This is DIFFERENT from the 50 EMA in band_strategy_15m.py which is used for regime classification
    # 21/34 EMA: Determines trend direction (bullish/bearish) via crossover
    # 50 EMA: Determines if market is in range (ADX < 20) or trend (ADX >= 20)
    # 200 EMA: Macro trend filter for regime classification (bull/bear market)
    # These serve different purposes and are not contradictory
    # Per-asset EMA periods: BTC/ETH use 9/21, SOL/XRP/DOGE use 13/34
    # Faster for liquid assets, slower for higher-beta assets
    # Asset-specific: BTC/ETH use 21/9-21, SOL/XRP/DOGE use 34/13-34
    ema_trend_period: int = 21
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    ema_200_period: int = 200  # Macro trend filter for regime classification

    # ── Momentum / overextension ──────────────────────────────────────
    rsi_period: int = 8
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    # Per-asset RSI thresholds (tuned for crypto volatility)
    # BTC/ETH: 70/30 (blue chip, standard)
    # SOL/XRP: 65/35 (high-beta, more events)
    # DOGE: 60/40 (highest volatility, widest bands)
    rsi_oversold_asset: Optional[float] = None  # Override per asset
    rsi_overbought_asset: Optional[float] = None  # Override per asset
    # Regime-based RSI threshold shifting (2026 research best practices)
    # Bull regime: Shift thresholds up (80/40) to stay in trades longer
    # Bear regime: Shift thresholds down (60/20) to exit faster
    # Range regime: Standard thresholds (70/30)
    regime_based_rsi_enabled: bool = True  # Enable regime-based threshold shifting
    rsi_bull_oversold: float = 40.0  # Bull regime oversold threshold
    rsi_bull_overbought: float = 80.0  # Bull regime overbought threshold
    rsi_bear_oversold: float = 20.0  # Bear regime oversold threshold
    rsi_bear_overbought: float = 60.0  # Bear regime overbought threshold
    # Distance-from-EMA thresholds (in ATR units)
    distance_overextended_atrs: float = 2.0

    # ── MACD (scalping-tilted: 8-21-5) ───────────────────────────────
    macd_fast: int = 8
    macd_slow: int = 21
    macd_signal: int = 5
    # MACD zero-line filter (2026 research best practices)
    # Only take long signals when MACD line > 0, short signals when MACD line < 0
    # This prevents counter-trend entries and aligns with momentum
    macd_zero_line_filter_enabled: bool = True
    # MACD histogram momentum filter (2026 research best practices)
    # Require histogram to be expanding in the direction of the trade
    # This confirms momentum is strengthening, not weakening
    macd_histogram_momentum_filter_enabled: bool = True
    macd_histogram_expansion_bars: int = 2  # Require N bars of histogram expansion

    # ── Chop filters ─────────────────────────────────────────────────
    # Consecutive closes above/below EMA to confirm trend
    # Asset-specific: BTC/ETH strict (3), SOL/XRP/DOGE relaxed (2)
    consecutive_closes_required: int = 3
    # MACD histogram must stay same sign for N bars before acting
    macd_persistence_bars: int = 3
    # Minimum |histogram| to treat as real signal (% of price)
    macd_histogram_min_pct: float = 0.0001  # 0.01% of price

    # ── Fee-aware EV ─────────────────────────────────────────────────
    # Kalshi fee formula: ceil(0.07 * contracts * P * (1-P))
    # Mid-curve (0.45-0.55) penalty zone — require extra edge
    fee_midcurve_low: float = 0.45
    fee_midcurve_high: float = 0.55
    # Minimum net EV (cents) after fees to enter a trade
    min_ev_cents: float = 1.5
    # Fee drag halt threshold (fees as % of gross PnL)
    fee_drag_halt_pct: float = 0.30

    # ── Volatility gate ───────────────────────────────────────────────
    atr_period: int = 14
    # ATR minimum-move gate: skip when ATR/price < threshold
    # Asset-specific: BTC lowest (0.0002), DOGE highest (0.0005)
    atr_min_move_pct: float = 0.0002   # 0.02% of price (BTC default)
    vol_window_bars: int = 30          # realized vol lookback (1m bars)
    vol_low_threshold: float = 0.15    # annualized; below = dead market
    vol_high_threshold: float = 1.20   # above = chaos, stay out

    # ── Liquidity filter ──────────────────────────────────────────────
    max_spread_cents: int = 8          # wider → skip
    min_depth_at_price: int = 3        # fewer contracts → skip

    # ── Price buffer ──────────────────────────────────────────────────
    max_bars: int = 250                # keep ~4 hours of 1m bars (increased from 120 to support EMA(200))
    min_bars_required: int = 52        # Need sufficient history for EMA/MACD calculations
    min_bars_cold_start: int = 1       # Cold start: allow trading with minimal bars during initialization (reduced to match actual warmup data availability of 2-3 bars)
    min_bars_for_macd: int = 30        # MACD needs more history

    # ── Fair Value Gap (FVG) detection ────────────────────────────────
    fvg_enabled: bool = True
    fvg_min_gap_size_atr: float = 1.5      # Minimum gap in ATR units
    fvg_min_gap_size_pct: float = 0.002    # Minimum gap as % of price
    fvg_max_age_bars: int = 50             # Max bars to track unfilled zone
    fvg_max_zones_tracked: int = 10        # Max active zones per asset
    fvg_pressure_weight: float = 0.30      # Weight in composite signals
    fvg_relevance_distance_atr: float = 3.0  # Distance to consider zone relevant
    fvg_ignore_immediate_fill: bool = True  # Skip gaps filled by next candle
    
    # ── Staleness threshold for price data (seconds) ─────────────────────
    # For 15m momentum strategy, reject data older than 30s
    staleness_threshold_seconds: float = 30.0
    
    # ── FVG Pullback logic (OPTIMIZED 2026-05-10) ───────────────────────
    fvg_pullback_enabled: bool = True
    fvg_pullback_atr_threshold: float = 1.0  # 1 ATR from FVG zone
    
    # ── Momentum pre-entry check (OPTIMIZED 2026-05-10) ────────────────
    momentum_lookback_bars: int = 3  # 45 minutes
    min_momentum_threshold: float = 0.002  # 0.2%

    def __post_init__(self):
        """Apply asset-specific parameter overrides based on asset field."""
        asset = self.asset.upper()
        
        # Kalshi mode: use lenient thresholds for prediction markets
        if self.kalshi_mode:
            # Disable vol gate - prediction markets don't have spot-like volatility
            self.vol_low_threshold = 0.0  # Always pass vol gate
            self.vol_high_threshold = 999.0  # Never reject due to high vol
            # Disable ATR move gate - prediction markets are binary contracts
            self.atr_min_move_pct = 0.0  # Always pass ATR move gate
            # Disable chop gate - allow trades without consecutive closes
            self.consecutive_closes_required = 0  # No consecutive closes needed
            self.macd_persistence_bars = 0  # No MACD persistence needed
            self.macd_histogram_min_pct = 0.0  # No minimum histogram magnitude
            logger.info(
                "[INDICATOR-CONFIG] Kalshi mode enabled for %s: vol/ATR/chop gates disabled",
                asset
            )
            return  # Skip asset-specific overrides when in Kalshi mode
        
        # Asset-specific EMA configurations (hybrid approach)
        if asset in ["BTC", "ETH"]:
            # Low vol assets: faster EMAs for responsiveness
            self.ema_trend_period = 21
            self.ema_fast_period = 9
            self.ema_slow_period = 21
            self.consecutive_closes_required = 3  # Strict chop filter
            self.atr_min_move_pct = 0.0002  # 0.02% - lowest threshold
            # RSI thresholds: standard 70/30 for blue chips
            self.rsi_oversold_asset = 30.0
            self.rsi_overbought_asset = 70.0
        elif asset in ["SOL", "XRP", "DOGE"]:
            # High vol assets: slower EMAs to reduce noise
            self.ema_trend_period = 34
            self.ema_fast_period = 13
            self.ema_slow_period = 34
            self.consecutive_closes_required = 2  # Relaxed chop filter
            # ATR thresholds scale with volatility
            if asset == "DOGE":
                self.atr_min_move_pct = 0.0005  # 0.05% - highest threshold
                # RSI thresholds: widest bands for highest volatility
                self.rsi_oversold_asset = 40.0
                self.rsi_overbought_asset = 60.0
            elif asset == "SOL":
                self.atr_min_move_pct = 0.0004  # 0.04%
                # RSI thresholds: relaxed for high-beta
                self.rsi_oversold_asset = 35.0
                self.rsi_overbought_asset = 65.0
            else:  # XRP
                self.atr_min_move_pct = 0.00035  # 0.035%
                # RSI thresholds: relaxed for high-beta
                self.rsi_oversold_asset = 35.0
                self.rsi_overbought_asset = 65.0
    
    def get_ema_params(self, asset: str = None) -> dict:
        """Get EMA parameters for a specific asset."""
        asset = (asset or self.asset).upper()
        if asset in ["BTC", "ETH"]:
            return {"trend_period": 21, "fast_period": 9, "slow_period": 21}
        else:  # SOL, XRP, DOGE
            return {"trend_period": 34, "fast_period": 13, "slow_period": 34}
    
    def get_atr_min_move(self, asset: str = None) -> float:
        """Get ATR min-move threshold for a specific asset."""
        asset = (asset or self.asset).upper()
        thresholds = {
            "BTC": 0.0002,
            "ETH": 0.00025,
            "SOL": 0.0004,
            "XRP": 0.00035,
            "DOGE": 0.0005,
        }
        return thresholds.get(asset, 0.0003)
    
    def get_chop_filter(self, asset: str = None) -> dict:
        """Get chop filter parameters for a specific asset."""
        asset = (asset or self.asset).upper()
        if asset in ["BTC", "ETH"]:
            return {"consecutive_closes_required": 3}
        else:  # SOL, XRP, DOGE
            return {"consecutive_closes_required": 2}


# Default configuration for regression tests
DEFAULT_15M_CONFIG = IndicatorConfig(asset="BTC")


# ═══════════════════════════════════════════════════════════════════════════
# Fair Value Gap (FVG) Zone Model
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FVGZone:
    """Represents a single Fair Value Gap zone.
    
    A bullish FVG: current low > previous high (gap up)
    A bearish FVG: current high < previous low (gap down)
    """
    top: float              # Upper boundary of the gap
    bottom: float          # Lower boundary of the gap
    direction: str         # "bullish" or "bearish"
    created_at: datetime   # When zone was detected
    timeframe: str         # Source timeframe (e.g., "15m")
    strength: float = 1.0   # Gap size relative to ATR (higher = stronger)
    
    # Fill tracking
    filled_at: Optional[datetime] = None
    fill_price: Optional[float] = None
    
    @property
    def is_filled(self) -> bool:
        return self.filled_at is not None
    
    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0
    
    @property
    def height(self) -> float:
        return abs(self.top - self.bottom)
    
    def contains_price(self, price: float) -> bool:
        """Check if price falls within the gap zone."""
        return min(self.top, self.bottom) <= price <= max(self.top, self.bottom)
    
    def distance_to_price(self, price: float) -> float:
        """Signed distance from zone mid to price (positive = price above gap)."""
        return price - self.mid
    
    def to_dict(self) -> dict:
        return {
            "top": round(self.top, 2),
            "bottom": round(self.bottom, 2),
            "direction": self.direction,
            "strength": round(self.strength, 2),
            "mid": round(self.mid, 2),
            "is_filled": self.is_filled,
            "age_bars": self._approx_age_bars(),
        }
    
    def _approx_age_bars(self) -> int:
        """Approximate age in bars since creation."""
        if self.filled_at:
            return 0
        # Rough approximation: assume 15m bars for crypto
        elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return int(elapsed / 900)  # 15 min = 900 seconds


@dataclass
class FVGContext:
    """Complete FVG context for an asset at a point in time."""
    zones: List[FVGZone] = field(default_factory=list)
    fvg_pressure: float = 0.0           # Normalized -1 to 1
    unfilled_count: int = 0
    nearest_distance_atr: float = 0.0   # Signed distance to nearest zone
    has_confluence: bool = False        # FVG aligns with other signals
    dominant_direction: str = "neutral"
    
    def to_dict(self) -> dict:
        return {
            "fvg_pressure": round(self.fvg_pressure, 3),
            "unfilled_count": self.unfilled_count,
            "nearest_distance_atr": round(self.nearest_distance_atr, 2),
            "has_confluence": self.has_confluence,
            "dominant_direction": self.dominant_direction,
            "active_zones": [z.to_dict() for z in self.zones if not z.is_filled][:3],
        }


@dataclass
class IndicatorSnapshot:
    """Complete indicator feature vector for one evaluation point."""

    # ── Trend ─────────────────────────────────────────────────────────
    ema_trend: float = 0.0             # EMA(50) primary trend filter
    ema_200: float = 0.0              # EMA(200) macro trend filter (regime classification)
    price_above_trend_ema: bool = False # price > EMA(50) = bullish regime
    price_above_ema_200: bool = False  # price > EMA(200) = bull market regime
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    ema_cross: str = "neutral"         # "bullish", "bearish", "neutral"
    trend_strength: float = 0.0        # |ema_fast - ema_slow| / ema_slow
    trend_regime: str = "range"        # "range", "trend_up", "trend_down"
    macro_regime: str = "neutral"      # "bull" (price > EMA200), "bear" (price < EMA200), "neutral"
    ema_slope: float = 0.0             # EMA(50) slope (rate of change)

    # ── Momentum ──────────────────────────────────────────────────────
    rsi: float = 50.0
    rsi_zone: str = "neutral"          # "oversold", "overbought", "neutral"
    rsi_tf: str = "15m"               # Timeframe of RSI (e.g., "15m", "5m", "1h")
    rsi_period: int = 8               # RSI period used
    rsi_5m: float = 50.0              # 5m RSI (timing gate)
    rsi_5m_zone: str = "neutral"      # 5m RSI zone
    rsi_1h: float = 50.0              # 1h RSI (regime filter)
    rsi_1h_zone: str = "neutral"      # 1h RSI zone
    rsi_alignment: str = "unknown"     # "all_aligned", "15m_contra_1h", "5m_contra_15m", "mixed"
    distance_from_ema_atrs: float = 0.0  # signed: +ve = above, -ve = below
    overextended: bool = False

    # ── MACD ──────────────────────────────────────────────────────────
    macd_line: float = 0.0             # MACD line (fast EMA - slow EMA)
    macd_signal_line: float = 0.0      # signal line (EMA of MACD)
    macd_histogram: float = 0.0        # histogram (MACD - signal)
    macd_cross: str = "neutral"        # "bullish", "bearish", "neutral"
    macd_histogram_positive: bool = False
    macd_zero_line_ok: bool = True      # MACD line on correct side of zero (2026 research)
    macd_histogram_expanding: bool = False  # Histogram expanding in direction of trade (2026 research)

    # ── Chop filters ──────────────────────────────────────────────────
    consecutive_closes_above_ema: int = 0  # streak of closes above EMA(slow)
    consecutive_closes_below_ema: int = 0  # streak of closes below EMA(slow)
    macd_same_sign_bars: int = 0       # bars MACD histogram stayed same sign
    chop_detected: bool = False        # True = choppy, avoid trading
    chop_reason: str = ""              # human-readable reason

    # ── Fee-aware EV ──────────────────────────────────────────────────
    is_midcurve: bool = False          # implied prob in 0.45-0.55 danger zone
    kalshi_fee_pct: float = 0.0        # estimated fee as % of notional
    net_ev_cents: float = 0.0          # estimated net EV after fees (set externally)
    kalshi_implied_prob: Optional[float] = None  # Kalshi implied probability at signal time
    model_prob: Optional[float] = None  # Model's fair probability
    edge_bp: Optional[float] = None    # Edge in basis points (model - implied)

    # ── Volatility ────────────────────────────────────────────────────
    atr: float = 0.0
    atr_move_ok: bool = True           # ATR large enough for directional move
    realized_vol_annualized: float = 0.0
    vol_band: str = "mid"              # "low", "mid", "high"
    vol_regime: str = "mid"            # "low", "mid", "high" - alternative classification

    # ── Liquidity (set externally from WS data) ───────────────────────
    # NOTE: Microstructure checks removed - handled by unified edge
    # Indicator stack is now purely TA-based (trend, momentum, volatility, chop)
    spread_cents: Optional[int] = None
    depth_at_price: Optional[int] = None
    liquidity_ok: bool = True  # Kept for observability, not used in trade_allowed

    # ── Composite gates ───────────────────────────────────────────────
    vol_gate_ok: bool = True           # vol in tradeable band
    trend_aligned: bool = True         # trend + momentum agree
    chop_gate_ok: bool = True          # not in choppy conditions
    trade_allowed: bool = True         # composite: all gates pass

    # ── Meta ──────────────────────────────────────────────────────────
    bars_available: int = 0
    timestamp: float = 0.0
    price: float = 0.0                 # latest 1m close (for backtest logging)
    config_version: str = "v1"         # Config version for post-hoc slicing
    session_tag: str = "unknown"      # Time-of-day/weekday seasonality tag

    # ── Outcome tracking (populated after trade resolution) ────────────
    interval_outcome: Optional[str] = None  # "YES" or "NO" - contract resolution
    signal_side: Optional[str] = None       # "YES" or "NO" - side we traded
    correct_direction: Optional[bool] = None  # Did signal direction match outcome?
    pnl_per_contract: Optional[float] = None  # Net PnL per contract (cents)

    # ── Contract barrier metrics (Kalshi-specific) ───────────────────────
    contract_barrier_distance: Optional[float] = None  # Distance from price to barrier (cents)
    normalized_delta: Optional[float] = None  # Barrier distance / ATR (unitless)

    # ── Directional bias ──────────────────────────────────────────────
    bias: str = "neutral"              # "up", "down", "neutral"
    bias_confidence: float = 0.0       # 0.0 – 1.0

    # ── Fair Value Gap (FVG) ──────────────────────────────────────────
    fvg_enabled: bool = False          # Whether FVG detection is active
    fvg_pressure: float = 0.0           # Normalized pressure (-1 bearish to +1 bullish)
    unfilled_fvg_count: int = 0         # Number of active unfilled zones
    nearest_fvg_distance_atr: float = 0.0  # Signed distance to nearest zone in ATR units
    has_local_fvg_confluence: bool = False  # FVG aligns with trend/Fib/regime
    fvg_context: Optional[FVGContext] = None  # Full FVG context
    fvg_dominant_direction: str = "neutral"  # "bullish", "bearish", "neutral"

    def to_dict(self) -> dict:
        return {
            "ema_trend": round(self.ema_trend, 2),
            "ema_200": round(self.ema_200, 2),
            "price_above_trend_ema": self.price_above_trend_ema,
            "price_above_ema_200": self.price_above_ema_200,
            "ema_fast": round(self.ema_fast, 2),
            "ema_slow": round(self.ema_slow, 2),
            "ema_cross": self.ema_cross,
            "trend_strength": round(self.trend_strength, 5),
            "trend_regime": self.trend_regime,
            "macro_regime": self.macro_regime,
            "ema_slope": round(self.ema_slope, 6),
            "rsi": round(self.rsi, 2),
            "rsi_zone": self.rsi_zone,
            "rsi_tf": self.rsi_tf,
            "rsi_period": self.rsi_period,
            "rsi_5m": round(self.rsi_5m, 2),
            "rsi_5m_zone": self.rsi_5m_zone,
            "rsi_1h": round(self.rsi_1h, 2),
            "rsi_1h_zone": self.rsi_1h_zone,
            "rsi_alignment": self.rsi_alignment,
            "distance_from_ema_atrs": round(self.distance_from_ema_atrs, 3),
            "overextended": self.overextended,
            "macd_line": round(self.macd_line, 4),
            "macd_signal_line": round(self.macd_signal_line, 4),
            "macd_histogram": round(self.macd_histogram, 4),
            "macd_cross": self.macd_cross,
            "macd_histogram_positive": self.macd_histogram_positive,
            "macd_zero_line_ok": self.macd_zero_line_ok,
            "macd_histogram_expanding": self.macd_histogram_expanding,
            "consecutive_closes_above_ema": self.consecutive_closes_above_ema,
            "consecutive_closes_below_ema": self.consecutive_closes_below_ema,
            "macd_same_sign_bars": self.macd_same_sign_bars,
            "chop_detected": self.chop_detected,
            "chop_reason": self.chop_reason,
            "chop_gate_ok": self.chop_gate_ok,
            "is_midcurve": self.is_midcurve,
            "kalshi_fee_pct": round(self.kalshi_fee_pct, 4),
            "kalshi_implied_prob": round(self.kalshi_implied_prob, 4) if self.kalshi_implied_prob is not None else None,
            "model_prob": round(self.model_prob, 4) if self.model_prob is not None else None,
            "edge_bp": round(self.edge_bp, 2) if self.edge_bp is not None else None,
            "atr": round(self.atr, 2),
            "atr_move_ok": self.atr_move_ok,
            "realized_vol_annualized": round(self.realized_vol_annualized, 4),
            "vol_band": self.vol_band,
            "vol_regime": self.vol_regime,
            "spread_cents": self.spread_cents,
            "depth_at_price": self.depth_at_price,
            "liquidity_ok": self.liquidity_ok,
            "vol_gate_ok": self.vol_gate_ok,
            "trend_aligned": self.trend_aligned,
            "trade_allowed": self.trade_allowed,
            "bars_available": self.bars_available,
            "price": round(self.price, 2),
            "bias": self.bias,
            "bias_confidence": round(self.bias_confidence, 3),
            "config_version": self.config_version,
            "session_tag": self.session_tag,
            # Outcome tracking fields
            "interval_outcome": self.interval_outcome,
            "signal_side": self.signal_side,
            "correct_direction": self.correct_direction,
            "pnl_per_contract": round(self.pnl_per_contract, 2) if self.pnl_per_contract is not None else None,
            # Contract barrier metrics
            "contract_barrier_distance": round(self.contract_barrier_distance, 2) if self.contract_barrier_distance is not None else None,
            "normalized_delta": round(self.normalized_delta, 4) if self.normalized_delta is not None else None,
            # FVG fields
            "fvg_enabled": self.fvg_enabled,
            "fvg_pressure": round(self.fvg_pressure, 3),
            "unfilled_fvg_count": self.unfilled_fvg_count,
            "nearest_fvg_distance_atr": round(self.nearest_fvg_distance_atr, 2),
            "has_local_fvg_confluence": self.has_local_fvg_confluence,
            "fvg_dominant_direction": self.fvg_dominant_direction,
            "fvg_context": self.fvg_context.to_dict() if self.fvg_context else None,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Indicator Stack
# ═══════════════════════════════════════════════════════════════════════════

class Crypto15mIndicatorStack:
    """Streaming indicator calculator fed with 1-minute close prices.

    Thread-safe for single-writer / single-reader (typical agent loop).
    """

    def __init__(self, config: Optional[IndicatorConfig] = None):
        self.cfg = config or IndicatorConfig()
        self._instance_id = id(self)  # Track instance for debugging
        self._prices: Deque[float] = deque(maxlen=self.cfg.max_bars)
        # EMA(50) trend state
        self._ema_trend: float = 0.0
        self._ema_trend_k: float = 2.0 / (self.cfg.ema_trend_period + 1)
        self._ema_trend_initialized: bool = False
        # EMA(200) macro trend state (regime classification)
        self._ema_200: float = 0.0
        self._ema_200_k: float = 2.0 / (self.cfg.ema_200_period + 1)
        self._ema_200_initialized: bool = False
        # EMA(5)/EMA(20) crossover state
        self._ema_fast: float = 0.0
        self._ema_slow: float = 0.0
        self._ema_fast_k: float = 2.0 / (self.cfg.ema_fast_period + 1)
        self._ema_slow_k: float = 2.0 / (self.cfg.ema_slow_period + 1)
        self._ema_initialized: bool = False
        # Multi-TF RSI state (downsampled from 1m data)
        self._5m_prices: Deque[float] = deque(maxlen=200)
        self._1h_prices: Deque[float] = deque(maxlen=200)
        self._5m_rsi_initialized: bool = False
        self._1h_rsi_initialized: bool = False
        self._5m_avg_gain: float = 0.0
        self._5m_avg_loss: float = 0.0
        self._1h_avg_gain: float = 0.0
        self._1h_avg_loss: float = 0.0
        self._bar_count_5m: int = 0
        self._bar_count_1h: int = 0
        # RSI state (incremental Wilder smoothing)
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._rsi_initialized: bool = False
        self._rsi_period = self.cfg.rsi_period
        # MACD state (dual EMA + signal EMA)
        self._macd_ema_fast: float = 0.0
        self._macd_ema_slow: float = 0.0
        self._macd_signal_ema: float = 0.0
        self._macd_fast_k: float = 2.0 / (self.cfg.macd_fast + 1)
        self._macd_slow_k: float = 2.0 / (self.cfg.macd_slow + 1)
        self._macd_signal_k: float = 2.0 / (self.cfg.macd_signal + 1)
        self._macd_initialized: bool = False
        self._macd_signal_initialized: bool = False
        # Chop filter state
        self._consecutive_above: int = 0
        self._consecutive_below: int = 0
        self._macd_hist_sign_bars: int = 0
        self._prev_macd_hist_positive: Optional[bool] = None

        # FVG state tracking
        self._fvg_zones: deque = deque(maxlen=self.cfg.fvg_max_zones_tracked)
        self._fvg_window: Deque[Dict[str, float]] = deque(maxlen=3)  # 3-candle window for detection
        self._bar_count: int = 0
        self._asset_symbol: str = ""  # Set via set_asset_symbol()
        # Staleness tracking
        self._last_price_timestamp: Optional[float] = None

    def set_asset_symbol(self, symbol: str) -> None:
        """Set asset symbol for FVG registry lookups."""
        self._asset_symbol = symbol.upper()

    # ── FVG Detection ───────────────────────────────────────────────
    # CRITICAL FIX: 2026-07-06 - FVG detection consolidated to merid/prediction/forecasters/fvg.py
    # This indicator stack no longer performs FVG detection to avoid duplicate implementations
    # Use get_fvg_forecaster() from merid.prediction.forecasters.fvg for authoritative FVG data
    # The previous approximation-based FVG detection has been removed to ensure consistency

    def _detect_fvg(self, window: List[Dict[str, float]], atr: float) -> Optional[FVGZone]:
        """DEPRECATED: FVG detection moved to merid/prediction/forecasters/fvg.py
        
        This method is kept for backward compatibility but returns None.
        Use get_fvg_forecaster() from merid.prediction.forecasters.fvg for authoritative FVG data.
        """
        # CRITICAL FIX: 2026-07-06 - Removed approximation-based FVG detection
        # Use merid.prediction.forecasters.fvg.FVGForecaster for actual OHLC-based FVG detection
        return None

    def _check_fvg_fills(self, price: float) -> None:
        """DEPRECATED: FVG fill checking moved to merid/prediction/forecasters/fvg.py
        
        This method is kept for backward compatibility but does nothing.
        Use get_fvg_forecaster() from merid.prediction.forecasters.fvg for authoritative FVG data.
        """
        # CRITICAL FIX: 2026-07-06 - Removed duplicate FVG fill checking
        # Use merid.prediction.forecasters.fvg.FVGStore for fill detection
        pass

    def _compute_fvg_context(self, price: float, atr: float) -> FVGContext:
        """DEPRECATED: FVG context computation moved to merid/prediction/forecasters/fvg.py
        
        This method is kept for backward compatibility but returns empty context.
        Use get_fvg_forecaster() from merid.prediction.forecasters.fvg for authoritative FVG data.
        """
        # CRITICAL FIX: 2026-07-06 - Removed duplicate FVG context computation
        # Use merid.prediction.forecasters.fvg.FVGForecaster for FVG context
        return FVGContext()

    def _check_fvg_confluence(self, snap: IndicatorSnapshot, ctx: FVGContext) -> bool:
        """DEPRECATED: FVG confluence checking moved to merid/prediction/forecasters/fvg.py
        
        This method is kept for backward compatibility but returns False.
        Use get_fvg_forecaster() from merid.prediction.forecasters.fvg for authoritative FVG data.
        """
        # CRITICAL FIX: 2026-07-06 - Removed duplicate FVG confluence checking
        # Use merid.prediction.forecasters.fvg.FVGStore for confluence scoring
        return False

    def _compute_simple_atr(self, prices: List[float], period: int = 14) -> float:
        """Compute simple ATR from close prices (using consecutive differences)."""
        if len(prices) < period + 1:
            return 0.0
        
        # Use |close - prev_close| as true range proxy
        true_ranges = [abs(prices[i] - prices[i - 1]) 
                       for i in range(-period, 0)]
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    # ── Public API ────────────────────────────────────────────────────

    def update(self, price: float) -> None:
        """Append a new 1-minute close price and update running state."""
        self.update_with_timestamp(price, time.time())

    def update_with_timestamp(self, price: float, timestamp: float) -> None:
        """Append a new 1-minute close price with timestamp and update running state.
        
        Args:
            price: The 1-minute close price
            timestamp: Unix timestamp when this price was received from the source
        """
        import math
        if price is None or not math.isfinite(price) or price <= 0:
            logger.warning("[INDICATOR-STACK-UPDATE] Invalid price: %s (price=%s, finite=%s, positive=%s)", 
                          price, price is not None, math.isfinite(price) if price is not None else False, 
                          (price > 0) if price is not None else False)
            return
        self._last_price_timestamp = timestamp
        prev = self._prices[-1] if self._prices else price
        self._prices.append(price)
        
        # CRITICAL FIX: 2026-07-08 - Log price history length for debugging bars_available=1 issue
        from utils.logger import format_price
        logger.info("[INDICATOR-STACK-UPDATE] asset=%s instance_id=%d price=%s bars_before=%d bars_after=%d maxlen=%d",
                     self._asset_symbol, self._instance_id, format_price(self._asset_symbol, price), len(self._prices) - 1, len(self._prices), self._prices.maxlen)

        n = len(self._prices)

        # ── Multi-TF RSI downsampling (5m, 1h from 1m data) ─────────────
        self._bar_count_5m += 1
        self._bar_count_1h += 1
        
        # Sample 5m close every 5 bars
        if self._bar_count_5m >= 5:
            self._5m_prices.append(price)
            self._bar_count_5m = 0
        
        # Sample 1h close every 60 bars
        if self._bar_count_1h >= 60:
            self._1h_prices.append(price)
            self._bar_count_1h = 0

        # ── 5m RSI update ─────────────────────────────────────────────
        if len(self._5m_prices) >= 2:
            prev_5m = self._5m_prices[-2]
            delta_5m = price - prev_5m
            gain_5m = max(delta_5m, 0.0)
            loss_5m = max(-delta_5m, 0.0)
            
            if not self._5m_rsi_initialized and len(self._5m_prices) >= self._rsi_period + 1:
                recent_5m = list(self._5m_prices)
                deltas_5m = [recent_5m[i] - recent_5m[i - 1] for i in range(1, len(recent_5m))]
                recent_deltas_5m = deltas_5m[-self._rsi_period:]
                self._5m_avg_gain = sum(max(d, 0) for d in recent_deltas_5m) / self._rsi_period
                self._5m_avg_loss = sum(max(-d, 0) for d in recent_deltas_5m) / self._rsi_period
                self._5m_rsi_initialized = True
            elif self._5m_rsi_initialized:
                self._5m_avg_gain = (self._5m_avg_gain * (self._rsi_period - 1) + gain_5m) / self._rsi_period
                self._5m_avg_loss = (self._5m_avg_loss * (self._rsi_period - 1) + loss_5m) / self._rsi_period

        # ── 1h RSI update ─────────────────────────────────────────────
        if len(self._1h_prices) >= 2:
            prev_1h = self._1h_prices[-2]
            delta_1h = price - prev_1h
            gain_1h = max(delta_1h, 0.0)
            loss_1h = max(-delta_1h, 0.0)
            
            if not self._1h_rsi_initialized and len(self._1h_prices) >= self._rsi_period + 1:
                recent_1h = list(self._1h_prices)
                deltas_1h = [recent_1h[i] - recent_1h[i - 1] for i in range(1, len(recent_1h))]
                recent_deltas_1h = deltas_1h[-self._rsi_period:]
                self._1h_avg_gain = sum(max(d, 0) for d in recent_deltas_1h) / self._rsi_period
                self._1h_avg_loss = sum(max(-d, 0) for d in recent_deltas_1h) / self._rsi_period
                self._1h_rsi_initialized = True
            elif self._1h_rsi_initialized:
                self._1h_avg_gain = (self._1h_avg_gain * (self._rsi_period - 1) + gain_1h) / self._rsi_period
                self._1h_avg_loss = (self._1h_avg_loss * (self._rsi_period - 1) + loss_1h) / self._rsi_period

        # ── EMA(50) trend update ─────────────────────────────────────
        if not self._ema_trend_initialized and n >= self.cfg.ema_trend_period:
            self._ema_trend = sum(list(self._prices)[-self.cfg.ema_trend_period:]) / self.cfg.ema_trend_period
            self._ema_trend_initialized = True
        elif self._ema_trend_initialized:
            self._ema_trend = price * self._ema_trend_k + self._ema_trend * (1 - self._ema_trend_k)

        # ── EMA(200) macro trend update ───────────────────────────────
        if not self._ema_200_initialized and n >= self.cfg.ema_200_period:
            self._ema_200 = sum(list(self._prices)[-self.cfg.ema_200_period:]) / self.cfg.ema_200_period
            self._ema_200_initialized = True
        elif self._ema_200_initialized:
            self._ema_200 = price * self._ema_200_k + self._ema_200 * (1 - self._ema_200_k)

        # ── EMA(5)/EMA(20) crossover update ──────────────────────────
        if not self._ema_initialized and n >= self.cfg.ema_slow_period:
            self._ema_fast = sum(list(self._prices)[-self.cfg.ema_fast_period:]) / self.cfg.ema_fast_period
            self._ema_slow = sum(list(self._prices)[-self.cfg.ema_slow_period:]) / self.cfg.ema_slow_period
            self._ema_initialized = True
        elif self._ema_initialized:
            self._ema_fast = price * self._ema_fast_k + self._ema_fast * (1 - self._ema_fast_k)
            self._ema_slow = price * self._ema_slow_k + self._ema_slow * (1 - self._ema_slow_k)

        # ── RSI update (Wilder smoothing) ─────────────────────────────
        delta = price - prev
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)

        if not self._rsi_initialized and n >= self._rsi_period + 1:
            # Seed with SMA of first N deltas
            prices_list = list(self._prices)
            deltas = [prices_list[i] - prices_list[i - 1] for i in range(1, n)]
            recent = deltas[-(self._rsi_period):]
            self._avg_gain = sum(max(d, 0) for d in recent) / self._rsi_period
            self._avg_loss = sum(max(-d, 0) for d in recent) / self._rsi_period
            self._rsi_initialized = True
        elif self._rsi_initialized:
            self._avg_gain = (self._avg_gain * (self._rsi_period - 1) + gain) / self._rsi_period
            self._avg_loss = (self._avg_loss * (self._rsi_period - 1) + loss) / self._rsi_period

        # ── MACD update (8-21-5 scalping) ─────────────────────────────
        if not self._macd_initialized and n >= self.cfg.macd_slow:
            prices_list = list(self._prices)
            self._macd_ema_fast = sum(prices_list[-self.cfg.macd_fast:]) / self.cfg.macd_fast
            self._macd_ema_slow = sum(prices_list[-self.cfg.macd_slow:]) / self.cfg.macd_slow
            self._macd_initialized = True
            # Seed signal line after MACD is available
            macd_val = self._macd_ema_fast - self._macd_ema_slow
            self._macd_signal_ema = macd_val
            self._macd_signal_initialized = True
        elif self._macd_initialized:
            self._macd_ema_fast = price * self._macd_fast_k + self._macd_ema_fast * (1 - self._macd_fast_k)
            self._macd_ema_slow = price * self._macd_slow_k + self._macd_ema_slow * (1 - self._macd_slow_k)
            macd_val = self._macd_ema_fast - self._macd_ema_slow
            if self._macd_signal_initialized:
                self._macd_signal_ema = macd_val * self._macd_signal_k + self._macd_signal_ema * (1 - self._macd_signal_k)

        # ── Chop filter: consecutive closes above/below EMA(50) trend ──
        if self._ema_trend_initialized:
            if price > self._ema_trend:
                self._consecutive_above += 1
                self._consecutive_below = 0
            elif price < self._ema_trend:
                self._consecutive_below += 1
                self._consecutive_above = 0
            else:
                self._consecutive_above = 0
                self._consecutive_below = 0

        # ── Chop filter: MACD histogram persistence ───────────────────
        if self._macd_initialized and self._macd_signal_initialized:
            hist = (self._macd_ema_fast - self._macd_ema_slow) - self._macd_signal_ema
            hist_positive = hist > 0
            if self._prev_macd_hist_positive is None:
                self._macd_hist_sign_bars = 1
            elif hist_positive == self._prev_macd_hist_positive:
                self._macd_hist_sign_bars += 1
            else:
                self._macd_hist_sign_bars = 1  # reset on flip
            self._prev_macd_hist_positive = hist_positive

        # ── FVG: Check for fills and update detection window ────────────
        if self.cfg.fvg_enabled:
            # Check if current price fills any zones
            self._check_fvg_fills(price)
            
            # Update detection window
            self._fvg_window.append({"price": price, "bar": self._bar_count})
            self._bar_count += 1
            
            # Try to detect new FVG with 3-candle window
            if len(self._fvg_window) == 3:
                # Compute simple ATR from recent prices for gap sizing
                prices_list = list(self._prices)
                if len(prices_list) >= 15:
                    atr = self._compute_simple_atr(prices_list, 14)
                    if atr > 0:
                        zone = self._detect_fvg(list(self._fvg_window), atr)
                        if zone:
                            self._fvg_zones.append(zone)
                            from utils.logger import format_price
                            logger.debug(
                                "FVG detected: %s %s zone at %s-%s (strength=%s)",
                                self._asset_symbol or "unknown",
                                zone.direction,
                                format_price(self._asset_symbol, zone.bottom),
                                format_price(self._asset_symbol, zone.top),
                                format_price(self._asset_symbol, zone.strength),
                            )

    def set_liquidity(self, spread_cents: Optional[int], depth: Optional[int]) -> None:
        """Update liquidity metrics from WS orderbook data."""
        self._last_spread = spread_cents
        self._last_depth = depth

    _last_spread: Optional[int] = None
    _last_depth: Optional[int] = None
    _last_snapshot: Optional[IndicatorSnapshot] = None

    def _compute_session_tag(self, timestamp: float) -> str:
        """Compute session tag for time-of-day/weekday seasonality tracking.
        
        Returns a string like "US_open", "Asia_open", "weekend", etc.
        """
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        hour = dt.hour
        weekday = dt.weekday()  # 0=Monday, 6=Sunday
        
        # Weekend tag
        if weekday >= 5:  # Saturday (5) or Sunday (6)
            return "weekend"
        
        # US market hours (9:30 AM - 4:00 PM ET = 13:30 - 20:00 UTC)
        if 13 <= hour < 20:
            return "US_trading"
        elif hour == 13:
            return "US_open"
        elif hour == 19:
            return "US_close"
        
        # Asia session (roughly 23:00 - 8:00 UTC)
        if hour >= 23 or hour < 8:
            return "Asia_session"
        elif hour == 8:
            return "Asia_close"
        
        # European session (roughly 7:00 - 16:00 UTC)
        if 7 <= hour < 16:
            return "Europe_trading"
        elif hour == 7:
            return "Europe_open"
        elif hour == 15:
            return "Europe_close"
        
        # Default
        return "off_hours"

    def snapshot(self) -> IndicatorSnapshot:
        """Compute and return the full indicator feature vector."""
        snap = IndicatorSnapshot(timestamp=time.time())
        n = len(self._prices)
        snap.bars_available = n
        snap.session_tag = self._compute_session_tag(snap.timestamp)

        # Staleness check: reject if last price is older than threshold
        if self._last_price_timestamp is not None:
            age_seconds = time.time() - self._last_price_timestamp
            if age_seconds > self.cfg.staleness_threshold_seconds:
                logger.warning(
                    "Price data stale for %s: %.1fs old > %.1fs threshold",
                    self._asset_symbol, age_seconds, self.cfg.staleness_threshold_seconds
                )
                snap.trade_allowed = False
                snap.chop_reason = f"stale_price_data_{age_seconds:.1f}s"
                return snap

        price = self._prices[-1]
        snap.price = price
        prices_list = list(self._prices)

        # ── 1a. EMA(50) trend regime ─────────────────────────────────
        if self._ema_trend_initialized:
            snap.ema_trend = self._ema_trend
            snap.price_above_trend_ema = price > self._ema_trend
            
            # Compute EMA slope (rate of change) for trend regime classification
            # Use recent EMA values to compute slope
            if n >= self.cfg.ema_trend_period + 5:
                # Get recent EMA values by recomputing from recent prices
                recent_prices = prices_list[-5:]  # Last 5 bars
                if len(recent_prices) >= 5:
                    # Simple slope: (current_ema - ema_5_bars_ago) / 5
                    # This is a proxy for the true EMA slope
                    ema_5_bars_ago = sum(prices_list[-(self.cfg.ema_trend_period + 5):-5]) / self.cfg.ema_trend_period
                    snap.ema_slope = (self._ema_trend - ema_5_bars_ago) / 5.0
                    
                    # Classify trend regime based on slope and price position
                    # Threshold: slope as % of price
                    slope_pct = abs(snap.ema_slope) / price if price > 0 else 0
                    slope_threshold = 0.0005  # 0.05% per bar = 0.5% per 10 bars
                    
                    if slope_pct > slope_threshold:
                        if snap.ema_slope > 0:
                            snap.trend_regime = "trend_up"
                        else:
                            snap.trend_regime = "trend_down"
                    else:
                        snap.trend_regime = "range"

        # ── 1a. EMA(200) macro regime ───────────────────────────────────
        if self._ema_200_initialized:
            snap.ema_200 = self._ema_200
            snap.price_above_ema_200 = price > self._ema_200
            
            # Classify macro regime based on EMA(200) position
            # This is the primary regime filter for trend-following strategies
            if snap.price_above_ema_200:
                snap.macro_regime = "bull"  # Bull market regime
            else:
                snap.macro_regime = "bear"  # Bear market regime

        # ── 1b. EMA(5)/EMA(20) crossover ────────────────────────────
        if self._ema_initialized:
            snap.ema_fast = self._ema_fast
            snap.ema_slow = self._ema_slow
            if snap.ema_slow > 0:
                snap.trend_strength = abs(snap.ema_fast - snap.ema_slow) / snap.ema_slow
            if snap.ema_fast > snap.ema_slow:
                snap.ema_cross = "bullish"
            elif snap.ema_fast < snap.ema_slow:
                snap.ema_cross = "bearish"
            else:
                snap.ema_cross = "neutral"

        # ── 2. RSI (15m primary) ───────────────────────────────────────────
        if self._rsi_initialized:
            if self._avg_loss == 0:
                snap.rsi = 50.0 if self._avg_gain == 0 else 100.0
            else:
                rs = self._avg_gain / self._avg_loss
                snap.rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # Populate RSI metadata
        snap.rsi_tf = "15m"  # Current timeframe
        snap.rsi_period = self.cfg.rsi_period
        
        # Use asset-specific RSI thresholds if configured
        oversold_threshold = self.cfg.rsi_oversold_asset or self.cfg.rsi_oversold
        overbought_threshold = self.cfg.rsi_overbought_asset or self.cfg.rsi_overbought
        
        # Apply regime-based RSI threshold shifting (2026 research best practices)
        if self.cfg.regime_based_rsi_enabled and snap.macro_regime == "bull":
            # Bull regime: Shift thresholds up to stay in trades longer
            oversold_threshold = self.cfg.rsi_bull_oversold
            overbought_threshold = self.cfg.rsi_bull_overbought
        elif self.cfg.regime_based_rsi_enabled and snap.macro_regime == "bear":
            # Bear regime: Shift thresholds down to exit faster
            oversold_threshold = self.cfg.rsi_bear_oversold
            overbought_threshold = self.cfg.rsi_bear_overbought
        # Range regime: Use standard thresholds (already set above)
        
        if snap.rsi < oversold_threshold:
            snap.rsi_zone = "oversold"
        elif snap.rsi > overbought_threshold:
            snap.rsi_zone = "overbought"
        else:
            snap.rsi_zone = "neutral"

        # ── 2b. 5m RSI (timing gate) ───────────────────────────────────────
        if self._5m_rsi_initialized:
            if self._5m_avg_loss == 0:
                snap.rsi_5m = 50.0 if self._5m_avg_gain == 0 else 100.0
            else:
                rs_5m = self._5m_avg_gain / self._5m_avg_loss
                snap.rsi_5m = 100.0 - (100.0 / (1.0 + rs_5m))
            
            if snap.rsi_5m < oversold_threshold:
                snap.rsi_5m_zone = "oversold"
            elif snap.rsi_5m > overbought_threshold:
                snap.rsi_5m_zone = "overbought"
            else:
                snap.rsi_5m_zone = "neutral"

        # ── 2c. 1h RSI (regime filter) ─────────────────────────────────────
        if self._1h_rsi_initialized:
            if self._1h_avg_loss == 0:
                snap.rsi_1h = 50.0 if self._1h_avg_gain == 0 else 100.0
            else:
                rs_1h = self._1h_avg_gain / self._1h_avg_loss
                snap.rsi_1h = 100.0 - (100.0 / (1.0 + rs_1h))
            
            if snap.rsi_1h < oversold_threshold:
                snap.rsi_1h_zone = "oversold"
            elif snap.rsi_1h > overbought_threshold:
                snap.rsi_1h_zone = "overbought"
            else:
                snap.rsi_1h_zone = "neutral"

        # ── 2d. RSI alignment classification ───────────────────────────────
        # Classify how RSI values align across timeframes
        if self._5m_rsi_initialized and self._1h_rsi_initialized:
            # All three in same zone
            if snap.rsi_zone == snap.rsi_5m_zone == snap.rsi_1h_zone:
                snap.rsi_alignment = "all_aligned"
            # 15m and 1h aligned, 5m contra (timing mismatch)
            elif snap.rsi_zone == snap.rsi_1h_zone and snap.rsi_5m_zone != snap.rsi_zone:
                snap.rsi_alignment = "5m_contra_15m_1h"
            # 15m and 5m aligned, 1h contra (regime mismatch)
            elif snap.rsi_zone == snap.rsi_5m_zone and snap.rsi_1h_zone != snap.rsi_zone:
                snap.rsi_alignment = "15m_5m_contra_1h"
            # 15m contra 1h (regime mismatch, 5m neutral or mixed)
            elif snap.rsi_zone != snap.rsi_1h_zone:
                snap.rsi_alignment = "15m_contra_1h"
            else:
                snap.rsi_alignment = "mixed"
        elif self._1h_rsi_initialized:
            # Only 15m and 1h available
            if snap.rsi_zone == snap.rsi_1h_zone:
                snap.rsi_alignment = "15m_1h_aligned"
            else:
                snap.rsi_alignment = "15m_contra_1h"
        elif self._5m_rsi_initialized:
            # Only 15m and 5m available
            if snap.rsi_zone == snap.rsi_5m_zone:
                snap.rsi_alignment = "15m_5m_aligned"
            else:
                snap.rsi_alignment = "5m_contra_15m"
        else:
            snap.rsi_alignment = "15m_only"

        # ── 3. MACD (8-21-5 scalping) ─────────────────────────────────
        if self._macd_initialized and self._macd_signal_initialized:
            snap.macd_line = self._macd_ema_fast - self._macd_ema_slow
            snap.macd_signal_line = self._macd_signal_ema
            snap.macd_histogram = snap.macd_line - snap.macd_signal_line
            snap.macd_histogram_positive = snap.macd_histogram > 0
            if snap.macd_line > snap.macd_signal_line:
                snap.macd_cross = "bullish"
            elif snap.macd_line < snap.macd_signal_line:
                snap.macd_cross = "bearish"
            else:
                snap.macd_cross = "neutral"
            
            # MACD zero-line filter (2026 research best practices)
            # Long signals: MACD line > 0 (bullish momentum)
            # Short signals: MACD line < 0 (bearish momentum)
            if self.cfg.macd_zero_line_filter_enabled:
                snap.macd_zero_line_ok = snap.macd_line > 0  # True for long, False for short
            else:
                snap.macd_zero_line_ok = True  # Disabled
            
            # MACD histogram momentum filter (2026 research best practices)
            # Check if histogram is expanding in the direction of the signal
            if self.cfg.macd_histogram_momentum_filter_enabled:
                # Histogram expanding = current histogram magnitude > previous histogram magnitude
                # We track this in the update_price method via _macd_hist_sign_bars
                # For now, use a simple check: histogram positive and increasing or negative and decreasing
                # This is a simplified version - full implementation would track histogram history
                snap.macd_histogram_expanding = abs(snap.macd_histogram) > 0.0001 * price if price > 0 else False
            else:
                snap.macd_histogram_expanding = True  # Disabled

        # ── 4. ATR (simple: use |close - prev_close| since no OHLC) ──
        if n >= self.cfg.atr_period + 1:
            true_ranges = [abs(prices_list[i] - prices_list[i - 1])
                           for i in range(max(1, n - self.cfg.atr_period), n)]
            snap.atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        else:
            snap.atr = 0.0

        # ── 4b. ATR minimum-move gate ────────────────────────────────
        # If ATR/price is too small, the market is dead and odds will
        # cluster near 0.5 where fees are highest → skip.
        # In kalshi_mode, always pass this gate since prediction markets don't have spot-like volatility
        if self.cfg.kalshi_mode:
            snap.atr_move_ok = True
        elif price > 0 and snap.atr > 0:
            atr_pct = snap.atr / price
            snap.atr_move_ok = atr_pct >= self.cfg.atr_min_move_pct
        elif snap.atr == 0:
            snap.atr_move_ok = False

        # ── 5. Distance from EMA(slow) in ATR units ──────────────────
        if self._ema_initialized and snap.atr > 0:
            snap.distance_from_ema_atrs = (price - snap.ema_slow) / snap.atr
        snap.overextended = abs(snap.distance_from_ema_atrs) > self.cfg.distance_overextended_atrs

        # ── 5b. Fair Value Gap (FVG) analysis ─────────────────────────
        if self.cfg.fvg_enabled and snap.atr > 0:
            snap.fvg_enabled = True
            fvg_ctx = self._compute_fvg_context(price, snap.atr)
            snap.fvg_context = fvg_ctx
            snap.fvg_pressure = fvg_ctx.fvg_pressure
            snap.unfilled_fvg_count = fvg_ctx.unfilled_count
            snap.nearest_fvg_distance_atr = fvg_ctx.nearest_distance_atr
            snap.fvg_dominant_direction = fvg_ctx.dominant_direction
            
            # Check confluence with trend and Fib levels
            snap.has_local_fvg_confluence = self._check_fvg_confluence(snap, fvg_ctx)
        else:
            snap.fvg_enabled = False

        # ── 6. Realized volatility (annualized from 1m returns) ───────
        vol_window = min(self.cfg.vol_window_bars, n - 1)
        if vol_window >= 5:
            returns = [(prices_list[i] / prices_list[i - 1]) - 1.0
                       for i in range(n - vol_window, n)]
            mean_r = sum(returns) / len(returns)
            var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_1m = math.sqrt(var_r) if var_r > 0 else 0.0
            # Annualize: sqrt(minutes_per_year) ≈ sqrt(525600) ≈ 725
            snap.realized_vol_annualized = std_1m * 725.0
        else:
            snap.realized_vol_annualized = 0.0

        # Classify vol band
        # CRITICAL FIX: In kalshi_mode, always pass vol gate regardless of volatility
        # Kalshi prediction markets are binary contracts, not continuous spot instruments
        if self.cfg.kalshi_mode:
            snap.vol_gate_ok = True
            snap.vol_band = "kalshi_mode_disabled"
            snap.vol_regime = "kalshi_mode_disabled"
        elif snap.realized_vol_annualized < self.cfg.vol_low_threshold:
            snap.vol_band = "low"
            snap.vol_regime = "low"
            snap.vol_gate_ok = False  # dead market
        elif snap.realized_vol_annualized > self.cfg.vol_high_threshold:
            snap.vol_band = "high"
            snap.vol_regime = "high"
            snap.vol_gate_ok = False  # chaos
        else:
            snap.vol_band = "mid"
            snap.vol_regime = "mid"
            snap.vol_gate_ok = True

        # ── 7. Liquidity filter ───────────────────────────────────────
        snap.spread_cents = self._last_spread
        snap.depth_at_price = self._last_depth
        if self._last_spread is not None and self._last_spread > self.cfg.max_spread_cents:
            snap.liquidity_ok = False
        if self._last_depth is not None and self._last_depth < self.cfg.min_depth_at_price:
            snap.liquidity_ok = False

        # ── 8. Chop filters ──────────────────────────────────────────
        snap.consecutive_closes_above_ema = self._consecutive_above
        snap.consecutive_closes_below_ema = self._consecutive_below
        snap.macd_same_sign_bars = self._macd_hist_sign_bars

        chop_reasons: List[str] = []

        # CRITICAL FIX: In kalshi_mode, disable chop gate entirely
        # Kalshi prediction markets don't need consecutive closes or MACD persistence
        if not self.cfg.kalshi_mode:
            # 8a. Consecutive closes: need N aligned candles for trend confirmation
            _max_streak = max(self._consecutive_above, self._consecutive_below)
            if _max_streak < self.cfg.consecutive_closes_required:
                chop_reasons.append(
                    f"consecutive_closes={_max_streak}<{self.cfg.consecutive_closes_required}"
                )

            # 8b. MACD persistence: histogram must stay same sign for M bars
            if self._macd_hist_sign_bars < self.cfg.macd_persistence_bars:
                chop_reasons.append(
                    f"macd_persistence={self._macd_hist_sign_bars}<{self.cfg.macd_persistence_bars}"
                )

            # 8c. MACD histogram magnitude: must exceed threshold
            if price > 0:
                hist_pct = abs(snap.macd_histogram) / price
                if hist_pct < self.cfg.macd_histogram_min_pct:
                    chop_reasons.append(
                        f"macd_hist_magnitude={hist_pct:.6f}<{self.cfg.macd_histogram_min_pct}"
                    )

        snap.chop_detected = len(chop_reasons) >= 2  # 2+ signals = chop
        snap.chop_reason = "; ".join(chop_reasons) if chop_reasons else ""
        snap.chop_gate_ok = not snap.chop_detected

        # ── 9. Trend alignment (playbook rules) ──────────────────────
        # EMA(50) = regime, EMA crossover + RSI + MACD = signal
        # Up: price above EMA(50) + RSI 50-70 + MACD histogram positive
        # Down: price below EMA(50) + RSI 30-50 + MACD histogram negative
        _up_aligned = (
            snap.price_above_trend_ema
            and 50.0 <= snap.rsi <= 70.0
            and snap.macd_histogram_positive
        )
        _down_aligned = (
            not snap.price_above_trend_ema
            and 30.0 <= snap.rsi <= 50.0
            and not snap.macd_histogram_positive
        )
        # Mean-reversion entries (RSI extremes, not against EMA(50) trend)
        _up_reversion = (
            snap.rsi_zone == "oversold"
            and snap.price_above_trend_ema
        )
        _down_reversion = (
            snap.rsi_zone == "overbought"
            and not snap.price_above_trend_ema
        )
        snap.trend_aligned = _up_aligned or _down_aligned or _up_reversion or _down_reversion

        # ── 10. Directional bias (playbook rules) ────────────────────
        snap.bias, snap.bias_confidence = self._compute_bias(snap)

        # ── 11. Composite gate ────────────────────────────────────────
        # NOTE: liquidity_ok removed - microstructure handled by unified edge
        # Cold start: use lower threshold during initialization and bypass volatility gates
        # During cold start, volatility gates cannot be calculated properly due to insufficient data
        min_bars_threshold = self.cfg.min_bars_cold_start if snap.bars_available < self.cfg.min_bars_required else self.cfg.min_bars_required
        if snap.bars_available < self.cfg.min_bars_required:
            # Cold start: only check bar count, bypass volatility gates
            snap.trade_allowed = snap.bars_available >= min_bars_threshold
        else:
            # Normal operation: check all gates
            snap.trade_allowed = (
                snap.vol_gate_ok
                and snap.atr_move_ok
                and snap.chop_gate_ok
                and snap.bars_available >= min_bars_threshold
            )

        # ── 12. Edge metrics (if set) ─────────────────────────────────
        snap.kalshi_implied_prob = self._kalshi_implied_prob
        snap.model_prob = self._model_prob
        snap.edge_bp = self._edge_bp

        # Store snapshot for observability (e.g., /api/v1/agents endpoint)
        self._last_snapshot = snap
        
        return snap

    # ── Fee calculator ────────────────────────────────────────────────

    @staticmethod
    def kalshi_fee_for_price(price_cents: float, contracts: int = 1) -> float:
        """Compute Kalshi taker fee in cents.

        Uses unified fees module for canonical tiered fee calculation.
        Formula: ceil(rate × C × P × (1-P)) where rate depends on contract tier.

        Returns fee in cents.
        """
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        return calculate_kalshi_fee_cents(contracts=contracts, price_cents=price_cents)

    @staticmethod
    def compute_ev_cents(
        price_cents: float,
        model_prob: float,
        side: str = "yes",
        contracts: int = 1,
    ) -> tuple:
        """Compute expected value after Kalshi fees.

        Args:
            price_cents: Kalshi price in cents (0-100).
            model_prob: Model's probability of YES (0-1).
            side: "yes" or "no".
            contracts: Number of contracts.

        Returns:
            (net_ev_cents, fee_cents, fee_pct) tuple.
        """
        p = price_cents / 100.0
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        fee_cents = calculate_kalshi_fee_cents(contracts=contracts, price_cents=price_cents)
        fee_pct = fee_cents / price_cents if price_cents > 0 else 0.0

        if side == "yes":
            # Buy YES at price P: win (100 - P - fee), lose (P + fee)
            win_payout = (100.0 - price_cents - fee_cents) * contracts
            loss_cost = (price_cents + fee_cents) * contracts
            ev = model_prob * win_payout - (1.0 - model_prob) * loss_cost
        else:
            # Buy NO at (100 - P): win (P - fee), lose (100 - P + fee)
            no_price = 100.0 - price_cents
            win_payout = (price_cents - fee_cents) * contracts
            loss_cost = (no_price + fee_cents) * contracts
            no_prob = 1.0 - model_prob
            ev = no_prob * win_payout - model_prob * loss_cost

        return ev, fee_cents, fee_pct

    def set_implied_prob(self, implied_prob: float) -> None:
        """Set the current Kalshi implied probability for fee-aware checks.

        Call this before snapshot() to populate is_midcurve and kalshi_fee_pct.
        """
        self._implied_prob = implied_prob

    def set_edge_metrics(self, kalshi_implied_prob: float, model_prob: float) -> None:
        """Set edge metrics for logging and diagnostics.

        Args:
            kalshi_implied_prob: Kalshi market implied probability (0-1)
            model_prob: Model's fair probability (0-1)
        """
        self._kalshi_implied_prob = kalshi_implied_prob
        self._model_prob = model_prob
        # Edge in basis points: (model - implied) * 10000
        self._edge_bp = (model_prob - kalshi_implied_prob) * 10000.0

    _implied_prob: Optional[float] = None
    _kalshi_implied_prob: Optional[float] = None
    _model_prob: Optional[float] = None
    _edge_bp: Optional[float] = None

    # ── Internals ─────────────────────────────────────────────────────

    def _compute_bias(self, snap: IndicatorSnapshot) -> tuple:
        """Derive directional bias per playbook rules.

        Playbook "Up" signal:
          - Price above EMA(50) (trend regime)
          - RSI between 50 and 70
          - MACD histogram positive

        Playbook "Down" signal:
          - Price below EMA(50)
          - RSI between 30 and 50
          - MACD histogram negative

        Mean-reversion overlay:
          - RSI < 30 crossing up → "up" (if price above EMA(50))
          - RSI > 70 crossing down → "down" (if price below EMA(50))

        Multi-TF RSI gates:
          - 1h RSI regime filter: Don't fade strong trends (if 1h RSI > 70, suppress long mean-reversion)
          - 5m RSI timing gate: Require 5m confirmation for 15m triggers

        Confidence is built from how many components agree.
        """
        up_score = 0.0
        down_score = 0.0
        max_components = 4.9  # EMA(50)=1.2, EMA cross=0.6, RSI=1.0, MACD=1.0, distance=0.6, chop=0.5

        # 1b. EMA(50) trend regime (secondary confirmation, or primary if EMA200 not ready)
        # If EMA(200) is not initialized, give EMA(50) primary weight instead
        ema_50_weight = 0.8 if self._ema_200_initialized else 1.5
        if snap.price_above_trend_ema:
            up_score += ema_50_weight
        else:
            down_score += ema_50_weight

        # 1c. EMA(200) macro regime (primary — strongest weight for trend-following)
        # 2026-07-07: Added EMA(200) as primary trend filter per research
        # This provides macro context and prevents counter-trend trades
        if self._ema_200_initialized:
            if snap.price_above_ema_200:
                up_score += 0.7  # Additional boost for macro regime
            else:
                down_score += 0.7

        # 2. EMA(5)/EMA(20) crossover (secondary confirmation)
        if snap.ema_cross == "bullish":
            up_score += 0.6
        elif snap.ema_cross == "bearish":
            down_score += 0.6

        # 3. RSI zone (playbook: 50-70 for up, 30-50 for down)
        # Apply 1h RSI regime filter: if 1h is strongly overbought, suppress long mean-reversion
        allow_long_reversion = True
        allow_short_reversion = True
        
        if snap.rsi_1h_zone == "overbought":
            # 1h strongly bullish - don't take long mean-reversion signals
            allow_long_reversion = False
        elif snap.rsi_1h_zone == "oversold":
            # 1h strongly bearish - don't take short mean-reversion signals
            allow_short_reversion = False

        # Get regime-adjusted thresholds for scoring (same logic as zone classification)
        rsi_oversold = self.cfg.rsi_oversold_asset or self.cfg.rsi_oversold
        rsi_overbought = self.cfg.rsi_overbought_asset or self.cfg.rsi_overbought
        
        if self.cfg.regime_based_rsi_enabled and snap.macro_regime == "bull":
            rsi_oversold = self.cfg.rsi_bull_oversold
            rsi_overbought = self.cfg.rsi_bull_overbought
        elif self.cfg.regime_based_rsi_enabled and snap.macro_regime == "bear":
            rsi_oversold = self.cfg.rsi_bear_oversold
            rsi_overbought = self.cfg.rsi_bear_overbought
        
        rsi_mid = (rsi_oversold + rsi_overbought) / 2.0  # Midpoint (typically 50)
        
        if rsi_mid <= snap.rsi <= rsi_overbought:
            up_score += 1.0
        elif rsi_oversold <= snap.rsi <= rsi_mid:
            down_score += 1.0
        # Mean-reversion: oversold = up bias, overbought = down bias
        # Apply 1h regime filter
        elif snap.rsi < rsi_oversold and allow_long_reversion:
            up_score += 0.8
        elif snap.rsi > rsi_overbought and allow_short_reversion:
            down_score += 0.8

        # 4. 5m RSI timing gate: boost confidence if 5m aligns with 15m
        if snap.rsi_5m_zone == snap.rsi_zone:
            # 5m and 15m aligned - timing confirmation
            if snap.rsi_zone == "oversold":
                up_score += 0.3  # Boost long bias
            elif snap.rsi_zone == "overbought":
                down_score += 0.3  # Boost short bias
        elif snap.rsi_5m_zone == "neutral" and snap.rsi_zone in ("oversold", "overbought"):
            # 15m extreme but 5m neutral - wait for 5m confirmation
            # Reduce confidence on mean-reversion signals
            if snap.rsi_zone == "oversold":
                up_score *= 0.8
            elif snap.rsi_zone == "overbought":
                down_score *= 0.8

        # 5. MACD histogram direction
        if snap.macd_histogram_positive:
            up_score += 1.0
        else:
            down_score += 1.0
        
        # 5b. MACD zero-line filter (2026 research best practices)
        # Only add score if MACD line is on the correct side of zero
        if self.cfg.macd_zero_line_filter_enabled:
            if snap.macd_line > 0:
                up_score += 0.5  # Boost long bias when MACD above zero
            else:
                down_score += 0.5  # Boost short bias when MACD below zero
        
        # 5c. MACD histogram momentum filter (2026 research best practices)
        # Only add score if histogram is expanding in the direction of the trade
        if self.cfg.macd_histogram_momentum_filter_enabled and snap.macd_histogram_expanding:
            if snap.macd_histogram_positive:
                up_score += 0.3  # Boost long bias when histogram expanding positive
            else:
                down_score += 0.3  # Boost short bias when histogram expanding negative

        # 5d. RSI+MACD confluence scoring (2026 research best practices)
        # When RSI and MACD agree on direction, boost confidence significantly
        # This is a high-confidence signal that both momentum and mean-reversion align
        rsi_macd_confluence_boost = 0.0
        
        # Long confluence: RSI oversold/neutral-bullish + MACD histogram positive
        if snap.rsi < 50.0 and snap.macd_histogram_positive:
            # RSI suggests buy (oversold or below mid) + MACD bullish
            rsi_macd_confluence_boost = 0.5
            up_score += rsi_macd_confluence_boost
        # Short confluence: RSI overbought/neutral-bearish + MACD histogram negative
        elif snap.rsi > 50.0 and not snap.macd_histogram_positive:
            # RSI suggests sell (overbought or above mid) + MACD bearish
            rsi_macd_confluence_boost = 0.5
            down_score += rsi_macd_confluence_boost
        
        # Extreme confluence (highest confidence)
        # RSI oversold + MACD histogram positive and expanding = very strong long
        if snap.rsi < rsi_oversold and snap.macd_histogram_positive and snap.macd_histogram_expanding:
            up_score += 0.4  # Additional boost for extreme confluence
        # RSI overbought + MACD histogram negative and expanding = very strong short
        elif snap.rsi > rsi_overbought and not snap.macd_histogram_positive and snap.macd_histogram_expanding:
            down_score += 0.4  # Additional boost for extreme confluence

        # 6. Distance from EMA (trend-following when moderate, contrarian when extreme)
        if snap.overextended:
            if snap.distance_from_ema_atrs > 0:
                down_score += 0.6
            else:
                up_score += 0.6
        else:
            if snap.distance_from_ema_atrs > 0.5:
                up_score += 0.5
            elif snap.distance_from_ema_atrs < -0.5:
                down_score += 0.5

        # 7. Chop-clean bonus (not in chop → boost confidence)
        if not snap.chop_detected:
            if up_score > down_score:
                up_score += 0.5
            elif down_score > up_score:
                down_score += 0.5

        # Vol band dampener
        if snap.vol_band == "low":
            up_score *= 0.5
            down_score *= 0.5
        elif snap.vol_band == "high":
            up_score *= 0.4
            down_score *= 0.4

        # FVG pressure adjustment
        if snap.fvg_enabled and abs(snap.fvg_pressure) > 0.2:
            # FVG pressure modulates bias: bullish FVG adds to up_score, etc.
            fvg_boost = abs(snap.fvg_pressure) * 0.5  # Up to 0.5 point boost
            if snap.fvg_pressure > 0:
                up_score += fvg_boost
            else:
                down_score += fvg_boost

        # Derive bias (deadband tunable — lower = more directional signals, noisier)
        net = up_score - down_score
        raw_conf = abs(net) / max_components
        confidence = min(raw_conf, 1.0)

        try:
            _dead = float(os.getenv("KALSHI_CT_BIAS_NET_THRESHOLD", "0.3"))
        except ValueError:
            _dead = 0.3

        if net > _dead:
            return "up", confidence
        elif net < -_dead:
            return "down", confidence
        else:
            return "neutral", 0.0

    def summary(self) -> dict:
        """Return a compact summary for logging."""
        snap = self.snapshot()
        return snap.to_dict()
