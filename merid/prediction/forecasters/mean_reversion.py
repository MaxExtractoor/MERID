"""Mean Reversion Forecaster — Orderbook imbalance and reversion to fair value.

Methodology:
1. Orderbook imbalance: bid-heavy books → price likely to rise, ask-heavy → fall
2. Extreme price detection: prices far from 0.50 tend to revert (especially with time)
3. Spread-implied fair value: mid-price as anchor, deviance from mid = opportunity
4. Time-to-expiry amplifier: mean reversion strengthens as expiry approaches
   (contrarian to momentum, which weakens near expiry)

This is intentionally contrarian to the MomentumForecaster.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.mean_reversion")


class MeanReversionForecaster(Forecaster):
    """Forecaster based on orderbook imbalance and mean reversion dynamics."""

    @property
    def forecaster_id(self) -> str:
        return "mean_reversion_v1"

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
        if implied_yes <= 0 or implied_yes >= 1:
            return None

        components: Dict[str, float] = {}
        signals = []
        weights = []

        # ── 1. Orderbook imbalance ──────────────────────────────────────
        imbalance = self._orderbook_imbalance(bid, ask, implied_yes)
        if imbalance is not None:
            components["orderbook_imbalance"] = imbalance
            signals.append(imbalance)
            weights.append(0.35)

        # ── 2. Extreme price reversion ──────────────────────────────────
        extreme = self._extreme_price_signal(implied_yes)
        components["extreme_reversion"] = extreme
        signals.append(extreme)
        weights.append(0.30)

        # ── 3. Spread deviation from fair value ─────────────────────────
        spread_dev = self._spread_deviation(bid, ask, implied_yes)
        if spread_dev is not None:
            components["spread_deviation"] = spread_dev
            signals.append(spread_dev)
            weights.append(0.20)

        # ── 4. Volume exhaustion ────────────────────────────────────────
        exhaustion = self._volume_exhaustion(volume, open_interest, implied_yes)
        if exhaustion is not None:
            components["volume_exhaustion"] = exhaustion
            signals.append(exhaustion)
            weights.append(0.15)

        if not signals:
            return None

        # Weighted average adjustment
        total_w = sum(weights)
        adjustment = sum(s * w for s, w in zip(signals, weights)) / total_w

        # Apply adjustment — mean reversion shifts probability toward 0.50
        # adjustment > 0 → push YES up, adjustment < 0 → push YES down
        p_model = implied_yes + adjustment * 0.12  # Max ±12% shift
        p_model = max(0.02, min(0.98, p_model))

        # Time amplifier: mean reversion gets STRONGER near expiry
        # (opposite of momentum which weakens)
        time_factor = 1.0
        if minutes_to_expiry is not None and minutes_to_expiry > 0:
            if minutes_to_expiry < 5:
                time_factor = 1.5  # Strongest near expiry
            elif minutes_to_expiry < 15:
                time_factor = 1.3
            elif minutes_to_expiry < 60:
                time_factor = 1.1
            elif minutes_to_expiry > 1440:
                time_factor = 0.6  # Weak for long-dated contracts

        # Apply time factor to the adjustment portion
        p_model = implied_yes + (p_model - implied_yes) * time_factor
        p_model = max(0.02, min(0.98, p_model))

        # Confidence: higher when price is extreme and spread is tight
        extremeness = abs(implied_yes - 0.5) * 2.0  # 0 at center, 1 at extremes
        data_quality = min(1.0, len(signals) / 3.0)
        confidence = extremeness * data_quality * 0.6  # Cap at 0.6

        # Boost confidence if spread is very tight (reliable signal)
        if bid is not None and ask is not None and ask > bid:
            spread = ask - bid
            if spread < 0.03:
                confidence *= 1.2

        return ForecastResult(
            forecaster_id=self.forecaster_id,
            p_model=round(p_model, 4),
            confidence=round(max(0.05, min(0.85, confidence)), 3),
            components=components,
        )

    # ── Signal generators ────────────────────────────────────────────────

    def _orderbook_imbalance(
        self,
        bid: Optional[float],
        ask: Optional[float],
        implied_yes: float,
    ) -> Optional[float]:
        """Detect orderbook pressure from bid/ask asymmetry.

        Bid-heavy (bid close to mid, ask far) → buying pressure → bullish
        Ask-heavy (ask close to mid, bid far) → selling pressure → bearish
        """
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None

        mid = (bid + ask) / 2.0
        if mid <= 0:
            return None

        # Pressure: (ask - mid) vs (mid - bid)
        # If ask is further from mid → bid is closer → buying pressure → positive
        ask_dist = ask - mid
        bid_dist = mid - bid
        total_dist = ask_dist + bid_dist

        if total_dist <= 0:
            return 0.0

        # Imbalance: positive = bid pressure (bullish), negative = ask pressure
        imbalance = (ask_dist - bid_dist) / total_dist
        return max(-1.0, min(1.0, imbalance * 2.0))

    def _extreme_price_signal(self, implied_yes: float) -> float:
        """Prices far from 0.50 tend to revert.

        Returns positive if below 0.50 (expects rise), negative if above (expects fall).
        Stronger signal at extremes.
        """
        deviation = 0.5 - implied_yes  # Positive when below 0.5

        # Logistic scaling: stronger at extremes
        # At 0.10/0.90: strong reversion signal
        # At 0.40/0.60: weak signal
        if abs(deviation) < 0.05:
            return 0.0  # Too close to center

        strength = math.tanh(deviation * 4.0)  # Smooth, bounded [-1, 1]
        return strength

    def _spread_deviation(
        self,
        bid: Optional[float],
        ask: Optional[float],
        implied_yes: float,
    ) -> Optional[float]:
        """If last trade (implied) deviates from mid, expect reversion to mid."""
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None

        mid = (bid + ask) / 2.0
        deviation = mid - implied_yes  # Positive if implied is below mid

        # Normalize: ±5% deviation is a strong signal
        return max(-1.0, min(1.0, deviation * 20.0))

    def _volume_exhaustion(
        self,
        volume: float,
        open_interest: float,
        implied_yes: float,
    ) -> Optional[float]:
        """High volume with extreme price suggests exhaustion (reversal likely).

        Concept: if lots of volume has pushed price to an extreme, the move
        may be exhausted and mean reversion is likely.
        """
        if volume <= 0:
            return None

        # How extreme is the price?
        extremeness = abs(implied_yes - 0.5) * 2.0  # 0–1

        if extremeness < 0.3:
            return None  # Not extreme enough for exhaustion signal

        # Volume-to-OI ratio (turnover): high turnover at extremes = exhaustion
        turnover = volume / max(open_interest, 1.0)
        exhaustion_strength = min(1.0, turnover / 3.0) * extremeness

        # Direction: revert toward 0.5
        direction = 1.0 if implied_yes < 0.5 else -1.0
        return direction * exhaustion_strength
