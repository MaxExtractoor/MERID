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
not as predictions of settlement values.

Reference: https://www.cfbenchmarks.com/blog/kalshi-leads-surging-crypto-event-contract-market-powered-by-cf-benchmarks

The stack outputs an ``IndicatorSnapshot`` dataclass consumed by the strategy
layer to adjust edge thresholds, filter trades, and size positions.

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

from utils.logger import get_logger

logger = get_logger("merid.signals.crypto_15m_indicators")


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class IndicatorConfig:
    """Tunable parameters for the 15-minute indicator stack."""

    # ── Trend baseline ────────────────────────────────────────────────
    # EMA(50) = primary trend filter (price above/below = regime)
    # EMA(5)/EMA(20) = crossover signal for timing entries
    ema_trend_period: int = 50
    ema_fast_period: int = 5
    ema_slow_period: int = 20

    # ── Momentum / overextension ──────────────────────────────────────
    rsi_period: int = 8
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    # Distance-from-EMA thresholds (in ATR units)
    distance_overextended_atrs: float = 2.0

    # ── MACD (scalping-tilted: 8-21-5) ───────────────────────────────
    macd_fast: int = 8
    macd_slow: int = 21
    macd_signal: int = 5

    # ── Chop filters ─────────────────────────────────────────────────
    # Consecutive closes above/below EMA to confirm trend (min 3)
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
    # (dead market → odds cluster at 0.5 → poor EV after fees)
    atr_min_move_pct: float = 0.0003   # 0.03% of price = minimum ATR
    vol_window_bars: int = 30          # realized vol lookback (1m bars)
    vol_low_threshold: float = 0.15    # annualized; below = dead market
    vol_high_threshold: float = 1.20   # above = chaos, stay out

    # ── Liquidity filter ──────────────────────────────────────────────
    max_spread_cents: int = 8          # wider → skip
    min_depth_at_price: int = 3        # fewer contracts → skip

    # ── Price buffer ──────────────────────────────────────────────────
    max_bars: int = 120                # keep ~2 hours of 1m bars
    min_bars_required: int = 52        # need 50+ for EMA(50) trend
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
    price_above_trend_ema: bool = False # price > EMA(50) = bullish regime
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    ema_cross: str = "neutral"         # "bullish", "bearish", "neutral"
    trend_strength: float = 0.0        # |ema_fast - ema_slow| / ema_slow

    # ── Momentum ──────────────────────────────────────────────────────
    rsi: float = 50.0
    rsi_zone: str = "neutral"          # "oversold", "overbought", "neutral"
    distance_from_ema_atrs: float = 0.0  # signed: +ve = above, -ve = below
    overextended: bool = False

    # ── MACD ──────────────────────────────────────────────────────────
    macd_line: float = 0.0             # MACD line (fast EMA - slow EMA)
    macd_signal_line: float = 0.0      # signal line (EMA of MACD)
    macd_histogram: float = 0.0        # histogram (MACD - signal)
    macd_cross: str = "neutral"        # "bullish", "bearish", "neutral"
    macd_histogram_positive: bool = False

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

    # ── Volatility ────────────────────────────────────────────────────
    atr: float = 0.0
    atr_move_ok: bool = True           # ATR large enough for directional move
    realized_vol_annualized: float = 0.0
    vol_band: str = "mid"              # "low", "mid", "high"

    # ── Liquidity (set externally from WS data) ───────────────────────
    spread_cents: Optional[int] = None
    depth_at_price: Optional[int] = None
    liquidity_ok: bool = True

    # ── Composite gates ───────────────────────────────────────────────
    vol_gate_ok: bool = True           # vol in tradeable band
    trend_aligned: bool = True         # trend + momentum agree
    chop_gate_ok: bool = True          # not in choppy conditions
    trade_allowed: bool = True         # composite: all gates pass

    # ── Meta ──────────────────────────────────────────────────────────
    bars_available: int = 0
    timestamp: float = 0.0
    price: float = 0.0                 # latest 1m close (for backtest logging)

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
            "price_above_trend_ema": self.price_above_trend_ema,
            "ema_fast": round(self.ema_fast, 2),
            "ema_slow": round(self.ema_slow, 2),
            "ema_cross": self.ema_cross,
            "trend_strength": round(self.trend_strength, 5),
            "rsi": round(self.rsi, 2),
            "rsi_zone": self.rsi_zone,
            "distance_from_ema_atrs": round(self.distance_from_ema_atrs, 3),
            "overextended": self.overextended,
            "macd_line": round(self.macd_line, 4),
            "macd_signal_line": round(self.macd_signal_line, 4),
            "macd_histogram": round(self.macd_histogram, 4),
            "macd_cross": self.macd_cross,
            "macd_histogram_positive": self.macd_histogram_positive,
            "consecutive_closes_above_ema": self.consecutive_closes_above_ema,
            "consecutive_closes_below_ema": self.consecutive_closes_below_ema,
            "macd_same_sign_bars": self.macd_same_sign_bars,
            "chop_detected": self.chop_detected,
            "chop_reason": self.chop_reason,
            "chop_gate_ok": self.chop_gate_ok,
            "is_midcurve": self.is_midcurve,
            "kalshi_fee_pct": round(self.kalshi_fee_pct, 4),
            "atr": round(self.atr, 2),
            "atr_move_ok": self.atr_move_ok,
            "realized_vol_annualized": round(self.realized_vol_annualized, 4),
            "vol_band": self.vol_band,
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
        self._prices: Deque[float] = deque(maxlen=self.cfg.max_bars)
        # EMA(50) trend state
        self._ema_trend: float = 0.0
        self._ema_trend_k: float = 2.0 / (self.cfg.ema_trend_period + 1)
        self._ema_trend_initialized: bool = False
        # EMA(5)/EMA(20) crossover state
        self._ema_fast: float = 0.0
        self._ema_slow: float = 0.0
        self._ema_fast_k: float = 2.0 / (self.cfg.ema_fast_period + 1)
        self._ema_slow_k: float = 2.0 / (self.cfg.ema_slow_period + 1)
        self._ema_initialized: bool = False
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

    def set_asset_symbol(self, symbol: str) -> None:
        """Set asset symbol for FVG registry lookups."""
        self._asset_symbol = symbol.upper()

    # ── FVG Detection ───────────────────────────────────────────────

    def _detect_fvg(self, window: List[Dict[str, float]], atr: float) -> Optional[FVGZone]:
        """Detect Fair Value Gap from 3-candle window.
        
        Uses close prices as proxy for OHLC (limited by 1m feed).
        
        Bullish FVG: Candle 2 low > Candle 1 high (gap up between them)
        Bearish FVG: Candle 2 high < Candle 1 low (gap down between them)
        
        We approximate:
        - "high" = max(close, prev_close)  
        - "low" = min(close, prev_close)
        """
        if len(window) < 3 or atr <= 0:
            return None
        
        if not self.cfg.fvg_enabled:
            return None

        # Extract candles (0=oldest, 1=middle, 2=newest)
        c0, c1, c2 = window[0], window[1], window[2]
        
        # Approximate OHLC from close prices
        h0 = max(c0["price"], c1["price"])  # Prev candle high approx
        l0 = min(c0["price"], c1["price"])  # Prev candle low approx
        h1 = max(c1["price"], c2["price"])  # Current candle high approx
        l1 = min(c1["price"], c2["price"])  # Current candle low approx
        
        # Bullish FVG: gap between c1 low and c2 high
        # Actually: gap between c0 high and c1 low (displacement up)
        if l1 > h0:
            gap_size = l1 - h0
            gap_size_atr = gap_size / atr
            gap_pct = gap_size / c1["price"] if c1["price"] > 0 else 0
            
            # Check minimum thresholds
            if gap_size_atr >= self.cfg.fvg_min_gap_size_atr or gap_pct >= self.cfg.fvg_min_gap_size_pct:
                # Check immediate fill (next candle fills the gap)
                if self.cfg.fvg_ignore_immediate_fill:
                    if c2["price"] <= h0:  # Filled
                        return None
                
                zone = FVGZone(
                    top=l1,
                    bottom=h0,
                    direction="bullish",
                    created_at=datetime.now(timezone.utc),
                    timeframe="15m",
                    strength=gap_size_atr,
                )
                return zone
        
        # Bearish FVG: gap between c0 low and c1 high (displacement down)
        if h1 < l0:
            gap_size = l0 - h1
            gap_size_atr = gap_size / atr
            gap_pct = gap_size / c1["price"] if c1["price"] > 0 else 0
            
            if gap_size_atr >= self.cfg.fvg_min_gap_size_atr or gap_pct >= self.cfg.fvg_min_gap_size_pct:
                if self.cfg.fvg_ignore_immediate_fill:
                    if c2["price"] >= l0:  # Filled
                        return None
                
                zone = FVGZone(
                    top=l0,
                    bottom=h1,
                    direction="bearish",
                    created_at=datetime.now(timezone.utc),
                    timeframe="15m",
                    strength=gap_size_atr,
                )
                return zone
        
        return None

    def _check_fvg_fills(self, price: float) -> None:
        """Check if current price fills any active FVG zones."""
        for zone in self._fvg_zones:
            if not zone.is_filled and zone.contains_price(price):
                zone.filled_at = datetime.now(timezone.utc)
                zone.fill_price = price
                logger.debug("FVG filled: %s at %.2f", zone.direction, price)

    def _compute_fvg_context(self, price: float, atr: float) -> FVGContext:
        """Compute complete FVG context for current price."""
        ctx = FVGContext()
        
        if not self.cfg.fvg_enabled or atr <= 0:
            return ctx
        
        # Filter to active (unfilled) zones within relevance distance
        active_zones = []
        for zone in self._fvg_zones:
            if zone.is_filled:
                continue
            # Check age
            age_bars = zone._approx_age_bars()
            if age_bars > self.cfg.fvg_max_age_bars:
                continue
            # Check distance
            dist_atr = abs(zone.distance_to_price(price)) / atr
            if dist_atr > self.cfg.fvg_relevance_distance_atr:
                continue
            active_zones.append(zone)
        
        ctx.zones = active_zones
        ctx.unfilled_count = len(active_zones)
        
        if not active_zones:
            return ctx
        
        # Find nearest zone
        nearest = min(active_zones, key=lambda z: abs(z.distance_to_price(price)))
        ctx.nearest_distance_atr = nearest.distance_to_price(price) / atr
        
        # Compute pressure: weighted by zone strength and proximity
        total_pressure = 0.0
        total_weight = 0.0
        bull_count = 0
        bear_count = 0
        
        for zone in active_zones:
            dist = abs(zone.distance_to_price(price))
            proximity_weight = 1.0 / (1.0 + dist / atr)  # Closer = higher weight
            direction_sign = 1.0 if zone.direction == "bullish" else -1.0
            
            total_pressure += direction_sign * zone.strength * proximity_weight
            total_weight += zone.strength * proximity_weight
            
            if zone.direction == "bullish":
                bull_count += 1
            else:
                bear_count += 1
        
        if total_weight > 0:
            ctx.fvg_pressure = max(-1.0, min(1.0, total_pressure / total_weight))
        
        # Dominant direction
        if bull_count > bear_count:
            ctx.dominant_direction = "bullish"
        elif bear_count > bull_count:
            ctx.dominant_direction = "bearish"
        else:
            ctx.dominant_direction = "neutral"
        
        return ctx

    def _check_fvg_confluence(self, snap: IndicatorSnapshot, ctx: FVGContext) -> bool:
        """Check if FVG aligns with trend/Fib for enhanced signals."""
        if not ctx.zones:
            return False
        
        # Trend confluence: bullish FVG in bullish trend or bearish FVG in bearish trend
        for zone in ctx.zones:
            if zone.is_filled:
                continue
            
            # Bullish FVG + bullish trend alignment
            if zone.direction == "bullish" and snap.price_above_trend_ema:
                return True
            
            # Bearish FVG + bearish trend alignment
            if zone.direction == "bearish" and not snap.price_above_trend_ema:
                return True
            
            # RSI confluence: bullish FVG at oversold levels
            if zone.direction == "bullish" and snap.rsi_zone == "oversold":
                return True
            
            # RSI confluence: bearish FVG at overbought levels
            if zone.direction == "bearish" and snap.rsi_zone == "overbought":
                return True
        
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
        import math
        if price is None or not math.isfinite(price) or price <= 0:
            return
        prev = self._prices[-1] if self._prices else price
        self._prices.append(price)

        n = len(self._prices)

        # ── EMA(50) trend update ─────────────────────────────────────
        if not self._ema_trend_initialized and n >= self.cfg.ema_trend_period:
            self._ema_trend = sum(list(self._prices)[-self.cfg.ema_trend_period:]) / self.cfg.ema_trend_period
            self._ema_trend_initialized = True
        elif self._ema_trend_initialized:
            self._ema_trend = price * self._ema_trend_k + self._ema_trend * (1 - self._ema_trend_k)

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
                            logger.debug(
                                "FVG detected: %s %s zone at %.2f-%.2f (strength=%.2f)",
                                self._asset_symbol or "unknown",
                                zone.direction,
                                zone.bottom,
                                zone.top,
                                zone.strength,
                            )

    def set_liquidity(self, spread_cents: Optional[int], depth: Optional[int]) -> None:
        """Update liquidity metrics from WS orderbook data."""
        self._last_spread = spread_cents
        self._last_depth = depth

    _last_spread: Optional[int] = None
    _last_depth: Optional[int] = None

    def snapshot(self) -> IndicatorSnapshot:
        """Compute and return the full indicator feature vector."""
        snap = IndicatorSnapshot(timestamp=time.time())
        n = len(self._prices)
        snap.bars_available = n

        if n < self.cfg.min_bars_required:
            snap.trade_allowed = False
            snap.bias = "neutral"
            return snap

        price = self._prices[-1]
        snap.price = price
        prices_list = list(self._prices)

        # ── 1a. EMA(50) trend regime ─────────────────────────────────
        if self._ema_trend_initialized:
            snap.ema_trend = self._ema_trend
            snap.price_above_trend_ema = price > self._ema_trend

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

        # ── 2. RSI ────────────────────────────────────────────────────
        if self._rsi_initialized:
            if self._avg_loss == 0:
                snap.rsi = 50.0 if self._avg_gain == 0 else 100.0
            else:
                rs = self._avg_gain / self._avg_loss
                snap.rsi = 100.0 - (100.0 / (1.0 + rs))
        if snap.rsi < self.cfg.rsi_oversold:
            snap.rsi_zone = "oversold"
        elif snap.rsi > self.cfg.rsi_overbought:
            snap.rsi_zone = "overbought"
        else:
            snap.rsi_zone = "neutral"

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
        if price > 0 and snap.atr > 0:
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
        if snap.realized_vol_annualized < self.cfg.vol_low_threshold:
            snap.vol_band = "low"
            snap.vol_gate_ok = False  # dead market
        elif snap.realized_vol_annualized > self.cfg.vol_high_threshold:
            snap.vol_band = "high"
            snap.vol_gate_ok = False  # chaos
        else:
            snap.vol_band = "mid"
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
        snap.trade_allowed = (
            snap.vol_gate_ok
            and snap.atr_move_ok
            and snap.liquidity_ok
            and snap.chop_gate_ok
            and snap.bars_available >= self.cfg.min_bars_required
        )

        return snap

    # ── Fee calculator ────────────────────────────────────────────────

    @staticmethod
    def kalshi_fee_for_price(price_cents: float, contracts: int = 1) -> float:
        """Compute Kalshi taker fee in cents.

        Formula: ceil(0.07 * contracts * P * (1-P))
        where P = price_cents / 100.

        Returns fee in cents.
        """
        p = price_cents / 100.0
        raw = 0.07 * contracts * p * (1.0 - p)
        return math.ceil(raw)

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
        fee_cents = math.ceil(0.07 * contracts * p * (1.0 - p))
        fee_pct = fee_cents / 100.0  # as fraction of $1 payout

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

    _implied_prob: Optional[float] = None

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

        Confidence is built from how many components agree.
        """
        up_score = 0.0
        down_score = 0.0
        max_components = 4.9  # EMA(50)=1.2, EMA cross=0.6, RSI=1.0, MACD=1.0, distance=0.6, chop=0.5

        # 1. EMA(50) trend regime (primary — strongest weight)
        if snap.price_above_trend_ema:
            up_score += 1.2
        else:
            down_score += 1.2

        # 2. EMA(5)/EMA(20) crossover (secondary confirmation)
        if snap.ema_cross == "bullish":
            up_score += 0.6
        elif snap.ema_cross == "bearish":
            down_score += 0.6

        # 3. RSI zone (playbook: 50-70 for up, 30-50 for down)
        if 50.0 <= snap.rsi <= 70.0:
            up_score += 1.0
        elif 30.0 <= snap.rsi <= 50.0:
            down_score += 1.0
        # Mean-reversion: oversold = up bias, overbought = down bias
        elif snap.rsi < 30.0:
            up_score += 0.8
        elif snap.rsi > 70.0:
            down_score += 0.8

        # 4. MACD histogram direction
        if snap.macd_histogram_positive:
            up_score += 1.0
        else:
            down_score += 1.0

        # 5. Distance from EMA (trend-following when moderate, contrarian when extreme)
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

        # 6. Chop-clean bonus (not in chop → boost confidence)
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
