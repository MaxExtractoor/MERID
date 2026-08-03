"""
Canonical TA Signal Models
============================
Standard data models for all technical analysis, market structure, and signal
generation across BTC/ETH/SOL/XRP/DOGE and all timeframes.

These models ensure consistent data shapes from OHLCV ingestion through
Kalshi contract selection, with no ad-hoc calculations or hidden gaps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class OHLCVSnapshot:
    """Single OHLCV bar for any asset/timeframe."""
    asset: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp_window_start: float
    timestamp_window_end: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "open": round(self.open, 2),
            "high": round(self.high, 2),
            "low": round(self.low, 2),
            "close": round(self.close, 2),
            "volume": self.volume,
            "ts_start": self.timestamp_window_start,
            "ts_end": self.timestamp_window_end,
        }


@dataclass
class PricePivot:
    """A swing high or low detected in price series."""
    pivot_type: str
    price: float
    index: int
    timestamp: float


@dataclass
class Divergence:
    """
    Bullish or bearish divergence between price and indicator.
    Bullish: price makes lower low, indicator makes higher low (RSI < oversold)
    Bearish: price makes higher high, indicator makes lower high (RSI > overbought)
    """
    div_type: str
    strength: float
    price_pivot: float
    indicator_pivot: float
    price_pivot_idx: int
    indicator_pivot_idx: int
    confirmed: bool
    rsi_at_pivot: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.div_type,
            "strength": round(self.strength, 3),
            "price_pivot": round(self.price_pivot, 2),
            "indicator_pivot": round(self.indicator_pivot, 4),
            "confirmed": self.confirmed,
            "rsi_at_pivot": round(self.rsi_at_pivot, 2) if self.rsi_at_pivot else None,
        }


@dataclass
class FibPivots:
    """Fibonacci pivot support/resistance levels."""
    s2: float
    s1: float
    pivot: float
    r1: float
    r2: float

    def nearest_support(self, price: float) -> Optional[float]:
        for level in [self.s1, self.s2]:
            if level < price:
                return level
        return None

    def nearest_resistance(self, price: float) -> Optional[float]:
        for level in [self.r1, self.r2]:
            if level > price:
                return level
        return None

    def to_dict(self) -> Dict[str, float]:
        return {
            "s2": round(self.s2, 2),
            "s1": round(self.s1, 2),
            "pivot": round(self.pivot, 2),
            "r1": round(self.r1, 2),
            "r2": round(self.r2, 2),
        }


@dataclass
class IndicatorBundle:
    """Complete indicator feature vector for one (asset, timeframe)."""
    asset: str
    timeframe: str
    timestamp: float
    close: float
    volume: float
    ema_fast: float
    ema_slow: float
    ema_trend: float
    ema_trend_slope: float
    sma_50: float
    sma_200: Optional[float] = None
    fib_pivots: Optional[FibPivots] = None
    rsi: float = 50.0
    rsi_zone: str = "neutral"
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    macd_histogram_slope: float = 0.0
    divergences: List[Divergence] = field(default_factory=list)
    atr: float = 0.0
    atr_pct: float = 0.0
    volume_zscore: float = 0.0
    liquidity_sweep_up: bool = False
    liquidity_sweep_down: bool = False
    sweep_strength: float = 0.0
    bars_available: int = 0

    def has_bullish_divergence(self, min_strength: float = 0.5) -> bool:
        return any(
            d.div_type in ("bullish_rsi", "bullish_macd")
            and d.strength >= min_strength
            and d.confirmed
            for d in self.divergences
        )

    def has_bearish_divergence(self, min_strength: float = 0.5) -> bool:
        return any(
            d.div_type in ("bearish_rsi", "bearish_macd")
            and d.strength >= min_strength
            and d.confirmed
            for d in self.divergences
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "close": round(self.close, 2),
            "ema_fast": round(self.ema_fast, 2),
            "ema_slow": round(self.ema_slow, 2),
            "ema_trend": round(self.ema_trend, 2),
            "ema_slope": round(self.ema_trend_slope, 6),
            "sma_50": round(self.sma_50, 2),
            "rsi": round(self.rsi, 2),
            "rsi_zone": self.rsi_zone,
            "macd_line": round(self.macd_line, 4),
            "macd_signal": round(self.macd_signal, 4),
            "macd_hist": round(self.macd_histogram, 4),
            "atr": round(self.atr, 2),
            "atr_pct": round(self.atr_pct, 4),
            "volume_zscore": round(self.volume_zscore, 2),
            "fib": self.fib_pivots.to_dict() if self.fib_pivots else None,
            "divergences": [d.to_dict() for d in self.divergences],
            "sweep_up": self.liquidity_sweep_up,
            "sweep_down": self.liquidity_sweep_down,
            "trade_ready": self.bars_available >= 50,
        }


@dataclass
class MarketStructure:
    """Regime classification for market conditions."""
    asset: str
    timestamp: float
    trend_regime: str = "range"
    vol_regime: str = "normal"
    liquidity_regime: str = "normal"
    trend_strength: float = 0.0
    realized_vol_annualized: float = 0.0
    atr_annualized_pct: float = 0.0
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    distance_to_support_pct: float = 0.0
    distance_to_resistance_pct: float = 0.0
    near_support: bool = False
    near_resistance: bool = False
    breakout_detected: bool = False
    breakdown_detected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "trend": self.trend_regime,
            "vol": self.vol_regime,
            "liquidity": self.liquidity_regime,
            "trend_strength": round(self.trend_strength, 3),
            "vol_ann": round(self.realized_vol_annualized, 4),
            "atr_pct": round(self.atr_annualized_pct, 4),
            "near_support": self.near_support,
            "near_resistance": self.near_resistance,
            "breakout": self.breakout_detected,
            "breakdown": self.breakdown_detected,
        }


@dataclass
class SignalScore:
    """Directional signal with confidence and rationale for one timeframe."""
    asset: str
    timeframe: str
    timestamp: float
    direction: str = "flat"
    confidence: float = 0.0
    quality_score: float = 0.0
    rationale_tags: List[str] = field(default_factory=list)
    primary_driver: str = ""
    trend_score: float = 0.0
    momentum_score: float = 0.0
    divergence_score: float = 0.0
    fib_confluence_score: float = 0.0
    volume_confirm_score: float = 0.0
    contra_trend: bool = False
    low_confidence_reason: Optional[str] = None

    def is_tradeable(self, min_confidence: float = 0.5, min_quality: float = 0.5) -> bool:
        return (
            self.direction in ("long", "short")
            and self.confidence >= min_confidence
            and self.quality_score >= min_quality
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "tf": self.timeframe,
            "direction": self.direction,
            "confidence": round(self.confidence, 3),
            "quality": round(self.quality_score, 3),
            "tags": self.rationale_tags,
            "primary": self.primary_driver,
            "trend": round(self.trend_score, 3),
            "momentum": round(self.momentum_score, 3),
            "divergence": round(self.divergence_score, 3),
            "fib": round(self.fib_confluence_score, 3),
            "volume": round(self.volume_confirm_score, 3),
            "contra_trend": self.contra_trend,
        }


@dataclass
class FusedClusterSignal:
    """Final fused signal for a (asset, primary_tf) cluster."""
    asset: str
    primary_tf: str
    timestamp: float
    direction: str = "flat"
    confidence: float = 0.0
    quality_score: float = 0.0
    higher_tf_alignment: float = 0.0
    lower_tf_confirmation: float = 0.0
    multi_tf_agreement: bool = False
    higher_tf_signal: Optional[SignalScore] = None
    primary_tf_signal: Optional[SignalScore] = None
    lower_tf_signal: Optional[SignalScore] = None
    rationale_tags: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    size_multiplier: float = 1.0

    def is_tradeable(self, min_confidence: float = 0.5, min_quality: float = 0.5) -> bool:
        if self.direction == "flat":
            return False
        if self.rejection_reason:
            return False
        return (
            self.confidence >= min_confidence
            and self.quality_score >= min_quality
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "primary_tf": self.primary_tf,
            "direction": self.direction,
            "confidence": round(self.confidence, 3),
            "quality": round(self.quality_score, 3),
            "alignment": round(self.higher_tf_alignment, 3),
            "confirmation": round(self.lower_tf_confirmation, 3),
            "agreement": self.multi_tf_agreement,
            "tags": self.rationale_tags,
            "rejection": self.rejection_reason,
            "size_mult": round(self.size_multiplier, 3),
        }


@dataclass
class GlobalRegime:
    """Cross-asset regime state for dynamic threshold adjustments."""
    timestamp: float
    btc_dominant_trend: str = "range"
    correlation_regime: str = "normal"
    global_vol_regime: str = "normal"
    macro_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "btc_trend": self.btc_dominant_trend,
            "correlation": self.correlation_regime,
            "global_vol": self.global_vol_regime,
            "macro": self.macro_context,
        }
