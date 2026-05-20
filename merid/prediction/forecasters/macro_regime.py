"""Macro Regime Forecaster — Sprint I.

Uses fear/greed index, cross-timeframe agreement, and volatility regime
to produce a macro-level probability adjustment. This forecaster captures
broader market sentiment that momentum and mean-reversion miss.

Signal components:
1. **Fear/Greed Index** — extreme fear → contrarian bullish, extreme greed → contrarian bearish
2. **Cross-Timeframe Agreement** — if 15m/1h/daily all agree, stronger signal
3. **Volatility Regime** — high vol → widen confidence bands, low vol → tighten
4. **Sentiment Composite** — aggregated social/news sentiment when available

Archetype: "macro_regime"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.macro_regime")


# Fear/Greed thresholds
EXTREME_FEAR = 20
FEAR = 35
GREED = 65
EXTREME_GREED = 80

# Volatility regime thresholds (annualized %)
LOW_VOL = 30
HIGH_VOL = 80


class MacroRegimeForecaster(Forecaster):
    """Forecaster that uses macro regime signals for probability adjustment.

    Unlike momentum (follows trends) and mean-reversion (fades extremes),
    this forecaster captures the broader market environment to modulate
    the ensemble probability.
    """

    def __init__(self):
        self._last_fg_value: Optional[float] = None
        self._last_vol_regime: str = "normal"
        self.model_type = "macro_regime"

    @property
    def forecaster_id(self) -> str:
        return "macro_regime"

    def predict(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float = 0.0,
        open_interest: float = 0.0,
        minutes_to_expiry: float = 0.0,
        asset: str = "",
        timeframe: str = "",
        bid: float = 0.0,
        ask: float = 0.0,
        category: str = "",
        **kwargs: Any,
    ) -> Optional[ForecastResult]:
        """Generate a macro-regime-adjusted probability forecast."""
        components: Dict[str, float] = {}
        adjustments = []
        confidence_factors = []

        # Start from implied probability as base
        base_p = implied_yes
        if base_p <= 0.01 or base_p >= 0.99:
            return None  # Can't meaningfully adjust extremes

        # ── 1. Fear/Greed Signal ────────────────────────────────────
        fg_signal = self._get_fear_greed_signal(asset, kwargs)
        components["fear_greed_signal"] = fg_signal
        if abs(fg_signal) > 0.01:
            adjustments.append(fg_signal)
            if fg_signal > 0:
                confidence_factors.append("contrarian_bullish")
            else:
                confidence_factors.append("contrarian_bearish")

        # ── 2. Cross-Timeframe Agreement ────────────────────────────
        xtf_signal = self._get_xtf_signal(asset, timeframe, kwargs)
        components["xtf_agreement"] = xtf_signal
        if abs(xtf_signal) > 0.01:
            adjustments.append(xtf_signal * 0.5)  # Half-weight

        # ── 3. Volatility Regime ────────────────────────────────────
        vol_regime = self._get_vol_regime(asset, kwargs)
        components["vol_regime"] = vol_regime
        vol_confidence_mult = 1.0
        if vol_regime > HIGH_VOL:
            vol_confidence_mult = 0.6  # Wide bands in high vol
            self._last_vol_regime = "high"
        elif vol_regime < LOW_VOL:
            vol_confidence_mult = 1.2  # Tighter in low vol
            self._last_vol_regime = "low"
        else:
            self._last_vol_regime = "normal"

        # ── 4. Sentiment Composite ──────────────────────────────────
        # PRODUCTION FIX (2026-05-10): Removed fake 0.0 fallback for sentiment
        # Require real sentiment data - if not available, skip sentiment adjustment
        sentiment = kwargs.get("sentiment_score")
        if sentiment is not None:
            components["sentiment"] = sentiment
            if abs(sentiment) > 0.1:
                adjustments.append(sentiment * 0.3)

        # ── Combine ─────────────────────────────────────────────────
        total_adjustment = sum(adjustments)
        # Clamp adjustment to ±10%
        total_adjustment = max(-0.10, min(0.10, total_adjustment))
        components["total_adjustment"] = total_adjustment

        p_model = base_p + total_adjustment
        p_model = max(0.02, min(0.98, p_model))

        # Confidence: based on signal strength and vol regime
        raw_confidence = min(1.0, len([a for a in adjustments if abs(a) > 0.01]) * 0.25 + 0.2)
        confidence = raw_confidence * vol_confidence_mult
        confidence = max(0.1, min(0.95, confidence))

        # Edge estimate
        edge_vs_implied = abs(p_model - implied_yes) * 100  # In cents

        components["edge_estimate"] = round(edge_vs_implied, 2)
        components["market_id"] = 0.0  # marker only

        return ForecastResult(
            forecaster_id=self.forecaster_id,
            p_model=round(p_model, 4),
            confidence=round(confidence, 3),
            components=components,
        )

    def _get_fear_greed_signal(self, asset: str, kwargs: Dict) -> float:
        """Get fear/greed-based contrarian signal.

        Returns positive for contrarian bullish (extreme fear → buy),
        negative for contrarian bearish (extreme greed → sell).
        """
        fg_value = kwargs.get("fear_greed_index", None)

        if fg_value is None:
            # Try to fetch from the sentiment system
            try:
                from merid.sentiment.market_mood_bus import get_market_mood_bus
                bus = get_market_mood_bus()
                context = bus.get_context(asset.upper(), "daily")
                if context and hasattr(context, "fg_index"):
                    fg_value = context.fg_index  # SentimentContext uses fg_index, not fear_greed
            except Exception:
                pass  # market_mood_bus unavailable — use kwargs default

        if fg_value is None:
            return 0.0

        self._last_fg_value = fg_value

        if fg_value <= EXTREME_FEAR:
            return 0.08  # Strong contrarian bullish
        elif fg_value <= FEAR:
            return 0.04  # Mild contrarian bullish
        elif fg_value >= EXTREME_GREED:
            return -0.08  # Strong contrarian bearish
        elif fg_value >= GREED:
            return -0.04  # Mild contrarian bearish
        return 0.0

    def _get_xtf_signal(self, asset: str, timeframe: str, kwargs: Dict) -> float:
        """Get cross-timeframe agreement signal.

        Checks whether 1h and 24h momentum agree on direction. When both
        timeframes point the same way the signal is stronger.
        """
        xtf_agreement = kwargs.get("xtf_agreement", None)

        if xtf_agreement is None:
            try:
                from merid.sentiment.market_mood_bus import get_market_mood_bus
                bus = get_market_mood_bus()
                context = bus.get_context(asset.upper(), "daily")
                if context:
                    m1h = getattr(context, "price_momentum_1h", 0.0) or 0.0
                    m24h = getattr(context, "price_momentum_24h", 0.0) or 0.0
                    if m1h != 0.0 and m24h != 0.0:
                        if (m1h > 0) == (m24h > 0):
                            # Both timeframes agree — average magnitude, capped at 1.0
                            # Normalise by 5% move = full signal
                            magnitude = min(1.0, (abs(m1h) + abs(m24h)) / 2.0 / 5.0)
                            xtf_agreement = magnitude if m1h > 0 else -magnitude
                        else:
                            xtf_agreement = 0.0  # Timeframes disagree — no signal
            except Exception:
                pass  # market_mood_bus unavailable — use kwargs default

        if xtf_agreement is None:
            return 0.0

        # agreement is -1 to +1 (all bearish to all bullish)
        return float(xtf_agreement) * 0.06  # Scale to ±6% max

    def _get_vol_regime(self, asset: str, kwargs: Dict) -> float:
        """Get current volatility regime (annualized %).

        Returns estimated annualized vol. Higher = more uncertain regime.
        Maps VolatilityRegime enum values to representative percentages:
          CALM → 15%  (below LOW_VOL=30 threshold → tighter confidence bands)
          NORMAL → 50%  (between thresholds → no adjustment)
          HOT → 90%   (above HIGH_VOL=80 threshold → wider confidence bands)
        """
        vol = kwargs.get("realized_vol_ann", None)

        if vol is None:
            try:
                from merid.sentiment.market_mood_bus import get_market_mood_bus, VolatilityRegime
                bus = get_market_mood_bus()
                context = bus.get_context(asset.upper(), "daily")
                if context and hasattr(context, "volatility_regime"):
                    regime = context.volatility_regime
                    if regime == VolatilityRegime.CALM:
                        vol = 15.0  # Below LOW_VOL (30%) → confidence boost
                    elif regime == VolatilityRegime.HOT:
                        vol = 90.0  # Above HIGH_VOL (80%) → confidence penalty
                    else:
                        vol = 50.0  # NORMAL — no regime adjustment
            except Exception:
                pass  # market_mood_bus unavailable — use default 50%

        if vol is None:
            return 50.0  # Default: neutral vol regime

        return float(vol)
