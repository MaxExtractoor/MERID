"""Momentum Forecaster — Volume/OI trends and price momentum signals.

Methodology:
1. Volume surge detection: high recent volume relative to baseline → trend continuation
2. OI growth: rising OI suggests new money entering, confirms trend
3. Price momentum: if YES price has been rising (implied from bid/ask vs mid),
   momentum predicts continuation
4. Time-to-expiry scaling: momentum signals weaken near expiry (mean reversion dominates)

This forecaster is intentionally different from EdgeModel's spot-relative approach.
It doesn't use external price feeds — only Kalshi orderbook data.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Optional

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.momentum")

# Rolling window for momentum tracking (per market)
_momentum_history: Dict[str, list] = defaultdict(list)
_MAX_HISTORY = 20


class MomentumForecaster(Forecaster):
    """Forecaster based on volume/OI momentum and price trend continuation."""

    @property
    def forecaster_id(self) -> str:
        return "momentum_v1"

    def predict(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float,
        open_interest: float,
        minutes_to_expiry: Optional[float],
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        category: Optional[str] = None,
        **kwargs,
    ) -> Optional[ForecastResult]:
        # Need at least implied probability to work with
        if implied_yes <= 0 or implied_yes >= 1:
            return None

        components: Dict[str, float] = {}
        signals = []
        weights = []

        # ── 1. Volume momentum ──────────────────────────────────────────
        vol_signal = self._volume_momentum(market_id, volume)
        if vol_signal is not None:
            components["volume_momentum"] = vol_signal
            signals.append(vol_signal)
            weights.append(0.3)

        # ── 2. OI growth signal ─────────────────────────────────────────
        oi_signal = self._oi_growth(market_id, open_interest)
        if oi_signal is not None:
            components["oi_growth"] = oi_signal
            signals.append(oi_signal)
            weights.append(0.2)

        # ── 3. Price momentum (bid/ask trend) ───────────────────────────
        price_signal = self._price_momentum(market_id, implied_yes, bid, ask)
        if price_signal is not None:
            components["price_momentum"] = price_signal
            signals.append(price_signal)
            weights.append(0.35)

        # ── 4. Spread tightness → trend confidence ─────────────────────
        spread_signal = self._spread_signal(bid, ask)
        if spread_signal is not None:
            components["spread_quality"] = spread_signal
            signals.append(spread_signal)
            weights.append(0.15)

        if not signals:
            return None

        # Weighted average of signals (each is a probability adjustment)
        total_w = sum(weights)
        adjustment = sum(s * w for s, w in zip(signals, weights)) / total_w

        # Apply adjustment to implied probability
        # adjustment > 0 → bullish momentum (push YES prob up)
        # adjustment < 0 → bearish momentum (push YES prob down)
        p_model = implied_yes + adjustment * 0.15  # Scale: max ±15% shift
        p_model = max(0.02, min(0.98, p_model))

        # Time decay: weaken momentum signal near expiry
        time_factor = 1.0
        if minutes_to_expiry is not None and minutes_to_expiry > 0:
            if minutes_to_expiry < 5:
                time_factor = 0.2  # Very weak near expiry
            elif minutes_to_expiry < 15:
                time_factor = 0.5
            elif minutes_to_expiry < 60:
                time_factor = 0.8

        # Blend toward implied based on time factor
        p_model = implied_yes + (p_model - implied_yes) * time_factor

        # Confidence: based on signal agreement and data quality
        signal_agreement = 1.0 - self._signal_dispersion(signals)
        data_quality = min(1.0, len(signals) / 3.0)
        confidence = signal_agreement * data_quality * time_factor * 0.7  # Cap at 0.7

        # Store current observation for next cycle's momentum calc
        self._record_observation(market_id, implied_yes, volume, open_interest)

        return ForecastResult(
            forecaster_id=self.forecaster_id,
            p_model=round(p_model, 4),
            confidence=round(max(0.05, min(0.9, confidence)), 3),
            components=components,
        )

    # ── Signal generators ────────────────────────────────────────────────

    def _volume_momentum(self, market_id: str, volume: float) -> Optional[float]:
        """Detect volume surges relative to recent history.

        Returns: positive if volume surging (bullish momentum), negative if declining.
        """
        history = _momentum_history.get(market_id, [])
        if len(history) < 3:
            return None

        recent_vols = [h.get("volume", 0) for h in history[-5:]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 0

        if avg_vol <= 0:
            return None

        vol_ratio = volume / avg_vol
        # Normalize: ratio of 2.0 → strong signal (1.0), ratio of 1.0 → neutral (0)
        return max(-1.0, min(1.0, (vol_ratio - 1.0)))

    def _oi_growth(self, market_id: str, open_interest: float) -> Optional[float]:
        """Detect OI growth (new money entering)."""
        history = _momentum_history.get(market_id, [])
        if len(history) < 2:
            return None

        prev_oi = history[-1].get("oi", 0)
        if prev_oi <= 0:
            return None

        oi_change = (open_interest - prev_oi) / prev_oi
        # Growing OI = positive signal, shrinking = negative
        return max(-1.0, min(1.0, oi_change * 5.0))  # Scale up small changes

    def _price_momentum(
        self,
        market_id: str,
        implied_yes: float,
        bid: Optional[float],
        ask: Optional[float],
    ) -> Optional[float]:
        """Track YES price trend over recent observations."""
        history = _momentum_history.get(market_id, [])
        if len(history) < 3:
            return None

        recent_prices = [h.get("implied_yes", 0.5) for h in history[-5:]]
        if not recent_prices:
            return None

        # Simple linear trend: compare current to average of recent
        avg_price = sum(recent_prices) / len(recent_prices)
        trend = implied_yes - avg_price

        # Normalize: ±10% move is a strong signal
        return max(-1.0, min(1.0, trend * 10.0))

    def _spread_signal(
        self,
        bid: Optional[float],
        ask: Optional[float],
    ) -> Optional[float]:
        """Tight spread = more confidence in momentum, wide spread = less."""
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None

        spread = ask - bid
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return None

        spread_pct = spread / mid
        # Tight spread (< 3%) → positive (1.0), wide (> 15%) → negative (-1.0)
        quality = 1.0 - (spread_pct / 0.15)
        return max(-1.0, min(1.0, quality))

    def _signal_dispersion(self, signals: list) -> float:
        """Measure how much signals disagree (0 = perfect agreement, 1 = max disagreement)."""
        if len(signals) < 2:
            return 0.0
        avg = sum(signals) / len(signals)
        variance = sum((s - avg) ** 2 for s in signals) / len(signals)
        return min(1.0, math.sqrt(variance))

    def _record_observation(
        self, market_id: str, implied_yes: float, volume: float, oi: float,
    ) -> None:
        """Store current market observation for momentum tracking."""
        _momentum_history[market_id].append({
            "implied_yes": implied_yes,
            "volume": volume,
            "oi": oi,
        })
        if len(_momentum_history[market_id]) > _MAX_HISTORY:
            _momentum_history[market_id] = _momentum_history[market_id][-_MAX_HISTORY:]
