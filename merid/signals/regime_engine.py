"""
Regime Engine
=============
Global regime classification for trend, volatility, and correlation.
Slow-moving updates (15-60 min) that feed into dynamic thresholds.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

from .ta_models import IndicatorBundle, MarketStructure, GlobalRegime


@dataclass
class RegimeConfig:
    """Configuration for regime classification."""
    update_interval_seconds: int = 900  # 15 minutes

    # Volatility thresholds (annualized)
    vol_low: float = 0.15     # 15%
    vol_normal: float = 0.50  # 50%
    vol_high: float = 1.20    # 120%
    vol_extreme: float = 2.00  # 200%

    # Trend strength thresholds
    trend_strong_threshold: float = 0.7
    trend_weak_threshold: float = 0.3

    # Distance to fib levels
    near_level_tolerance_pct: float = 0.005  # 0.5%


class RegimeEngine:
    """
    Thread-safe regime engine with slow-moving updates.

    Maintains market structure state per asset, updated at configured intervals.
    Used for dynamic distance thresholds and sizing adjustments.
    """

    _instance: Optional[RegimeEngine] = None
    # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
    # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
    # _lock = threading.Lock()
    _lock = None  # Disabled to prevent startup hang

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            if cls._lock is not None:
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
            else:
                # Lock disabled - direct initialization (startup workaround)
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[RegimeConfig] = None):
        if hasattr(self, '_initialized'):
            return

        self.config = config or RegimeConfig()
        self._market_structures: Dict[str, MarketStructure] = {}
        self._global_regime: GlobalRegime = GlobalRegime(
            timestamp=time.time(),
            btc_dominant_trend="range",
            correlation_regime="normal",
            global_vol_regime="normal",
        )
        self._last_update: Dict[str, float] = {}
        self._initialized = True

    def get_market_structure(
        self,
        asset: str,
        bundles: Dict[str, IndicatorBundle],
    ) -> MarketStructure:
        """
        Get or compute market structure for an asset.

        Returns cached structure if within update interval, otherwise recomputes.
        """
        now = time.time()
        last_update = self._last_update.get(asset, 0)

        if now - last_update < self.config.update_interval_seconds and asset in self._market_structures:
            return self._market_structures[asset]

        # Recompute market structure
        structure = self._compute_market_structure(asset, bundles)
        self._market_structures[asset] = structure
        self._last_update[asset] = now
        return structure

    def _compute_market_structure(
        self,
        asset: str,
        bundles: Dict[str, IndicatorBundle],
    ) -> MarketStructure:
        """Compute market structure from multi-timeframe bundles."""
        # Use 1h or 4h for primary trend, 15m for immediate conditions
        trend_bundle = bundles.get("4h") or bundles.get("1h") or bundles.get("15m")
        current_bundle = bundles.get("15m") or trend_bundle

        if not trend_bundle:
            return MarketStructure(asset=asset, timestamp=time.time())

        # Trend regime
        trend_regime, trend_strength = self._classify_trend(trend_bundle)

        # Volatility regime
        vol_regime = self._classify_volatility(trend_bundle)

        # Liquidity regime (based on volume and spreads)
        liquidity_regime = self._classify_liquidity(current_bundle or trend_bundle)

        # ATR annualized
        atr_annual = trend_bundle.atr_pct * 365.25 if trend_bundle else 0.0

        # Fib support/resistance proximity
        nearest_support = None
        nearest_resistance = None
        near_support = False
        near_resistance = False

        if current_bundle and current_bundle.fib_pivots:
            fib = current_bundle.fib_pivots
            nearest_support = fib.nearest_support(current_bundle.close)
            nearest_resistance = fib.nearest_resistance(current_bundle.close)

            if nearest_support:
                dist = abs(current_bundle.close - nearest_support) / current_bundle.close
                near_support = dist < self.config.near_level_tolerance_pct

            if nearest_resistance:
                dist = abs(current_bundle.close - nearest_resistance) / current_bundle.close
                near_resistance = dist < self.config.near_level_tolerance_pct

        # Breakout detection
        breakout = False
        breakdown = False
        if current_bundle and current_bundle.fib_pivots:
            if current_bundle.close > current_bundle.fib_pivots.r1:
                breakout = True
            elif current_bundle.close < current_bundle.fib_pivots.s1:
                breakdown = True

        return MarketStructure(
            asset=asset,
            timestamp=time.time(),
            trend_regime=trend_regime,
            vol_regime=vol_regime,
            liquidity_regime=liquidity_regime,
            trend_strength=trend_strength,
            realized_vol_annualized=atr_annual * 16,  # Rough conversion
            atr_annualized_pct=atr_annual,
            nearest_support=nearest_support,
            nearest_resistance=nearest_resistance,
            distance_to_support_pct=abs(current_bundle.close - nearest_support) / current_bundle.close if nearest_support else 0.0,
            distance_to_resistance_pct=abs(current_bundle.close - nearest_resistance) / current_bundle.close if nearest_resistance else 0.0,
            near_support=near_support,
            near_resistance=near_resistance,
            breakout_detected=breakout,
            breakdown_detected=breakdown,
        )

    def _classify_trend(self, bundle: IndicatorBundle) -> tuple:
        """Classify trend regime and strength."""
        if bundle.bars_available < 50:
            return "range", 0.0

        # Score based on EMA alignment and slope
        ema_score = 0.0

        if bundle.close > bundle.ema_fast > bundle.ema_slow:
            ema_score = 1.0
        elif bundle.close > bundle.ema_fast:
            ema_score = 0.5
        elif bundle.close < bundle.ema_slow:
            ema_score = -1.0
        elif bundle.close < bundle.ema_fast:
            ema_score = -0.5

        # Add slope contribution
        slope_score = bundle.ema_trend_slope * 1000  # Normalize
        slope_score = max(-1, min(1, slope_score))

        # Combine
        total_score = ema_score * 0.6 + slope_score * 0.4
        strength = abs(total_score)

        if total_score > self.config.trend_strong_threshold:
            return "uptrend", strength
        elif total_score < -self.config.trend_strong_threshold:
            return "downtrend", strength
        elif strength < self.config.trend_weak_threshold:
            return "range", strength
        else:
            return "chop", strength

    def _classify_volatility(self, bundle: IndicatorBundle) -> str:
        """Classify volatility regime from ATR."""
        if bundle.bars_available < 30:
            return "normal"

        atr_annual = bundle.atr_pct * 365.25

        if atr_annual > self.config.vol_extreme:
            return "extreme"
        elif atr_annual > self.config.vol_high:
            return "high"
        elif atr_annual < self.config.vol_low:
            return "low"
        else:
            return "normal"

    def _classify_liquidity(self, bundle: IndicatorBundle) -> str:
        """Classify liquidity regime."""
        if bundle.bars_available < 20:
            return "normal"

        # Based on volume z-score and sweep detection
        if bundle.volume_zscore < -2:
            return "thin"
        elif bundle.sweep_strength > 0.7:
            return "stressed"
        else:
            return "normal"

    def get_dynamic_distance_multiplier(
        self,
        asset: str,
        base_distance_pct: float,
        cluster_quality: float,
        market_structure: MarketStructure,
    ) -> float:
        """
        Calculate dynamic max distance multiplier based on regime and signal quality.

        Higher quality + trend following + normal vol = 1.2-1.5x base distance
        Low quality + contra-trend + high vol = 0.5x base (or reject)
        """
        multiplier = 1.0

        # Quality adjustment
        if cluster_quality > 0.7:
            multiplier += 0.2
        elif cluster_quality < 0.4:
            multiplier -= 0.3

        # Vol regime adjustment
        if market_structure.vol_regime == "low":
            multiplier += 0.1
        elif market_structure.vol_regime in ("high", "extreme"):
            multiplier -= 0.3

        # Trend alignment adjustment
        if market_structure.trend_regime in ("uptrend", "downtrend"):
            multiplier += 0.1
        elif market_structure.trend_regime == "range":
            multiplier -= 0.1

        # Hard caps
        return min(1.5, max(0.4, multiplier))

    def update_global_regime(
        self,
        btc_structure: MarketStructure,
        all_structures: Dict[str, MarketStructure],
    ) -> GlobalRegime:
        """Update global cross-asset regime."""
        # BTC trend as anchor
        btc_trend = btc_structure.trend_regime

        # Correlation regime
        alt_trends = [s.trend_regime for asset, s in all_structures.items() if asset != "BTC"]
        if alt_trends:
            matching_btc = sum(1 for t in alt_trends if t == btc_trend)
            correlation = matching_btc / len(alt_trends)
            if correlation > 0.7:
                corr_regime = "high_correlation"
            elif correlation < 0.4:
                corr_regime = "divergent"
            else:
                corr_regime = "normal"
        else:
            corr_regime = "normal"

        # Global vol
        vols = [s.vol_regime for s in all_structures.values()]
        high_vol_count = sum(1 for v in vols if v in ("high", "extreme"))
        if high_vol_count > len(vols) / 2:
            global_vol = "high"
        else:
            global_vol = "normal"

        self._global_regime = GlobalRegime(
            timestamp=time.time(),
            btc_dominant_trend=btc_trend,
            correlation_regime=corr_regime,
            global_vol_regime=global_vol,
        )
        return self._global_regime

    def get_global_regime(self) -> GlobalRegime:
        """Get current global regime."""
        return self._global_regime


def get_regime_engine(config: Optional[RegimeConfig] = None) -> RegimeEngine:
    """Get or create the global RegimeEngine singleton."""
    return RegimeEngine(config)
