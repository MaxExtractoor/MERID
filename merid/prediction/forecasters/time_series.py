"""Time-Series Forecaster — Sprint Q.

Dedicated ARIMA-style time-series forecaster that models price evolution
as a stochastic process. Unlike MomentumForecaster (which uses rolling
heuristics), this forecaster fits a proper autoregressive model with
GARCH-like volatility estimation.

Signal components:
1. **AR(p) Model** — Autoregressive fit on recent price history
2. **Volatility Regime** — EWMA volatility for confidence scaling
3. **Mean-Reversion Speed** — Ornstein-Uhlenbeck half-life estimate
4. **Trend Persistence** — Hurst exponent proxy (R/S analysis)

Archetype: "time_series"
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.time_series")

# Per-market rolling price history
_price_history: Dict[str, List[float]] = defaultdict(list)
_MAX_HISTORY = 60  # Keep 60 observations


class TimeSeriesForecaster(Forecaster):
    """Forecaster based on autoregressive time-series modeling.

    Fits a lightweight AR(2) model with EWMA volatility on rolling
    price observations. Produces directional probability forecasts
    with confidence scaled by volatility regime.
    """

    @property
    def forecaster_id(self) -> str:
        return "time_series_v1"

    def predict(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float = 0.0,
        open_interest: float = 0.0,
        minutes_to_expiry: Optional[float] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        category: Optional[str] = None,
        **kwargs,
    ) -> Optional[ForecastResult]:
        """Generate a time-series-based probability forecast."""
        if implied_yes <= 0.01 or implied_yes >= 0.99:
            return None

        # Record observation
        history = _price_history[market_id]
        history.append(implied_yes)
        if len(history) > _MAX_HISTORY:
            history[:] = history[-_MAX_HISTORY:]

        # Need minimum 10 observations for meaningful AR fit
        if len(history) < 10:
            return None

        components: Dict[str, float] = {}
        adjustments: List[float] = []

        # ── 1. AR(2) Model ──────────────────────────────────────────
        ar_forecast, ar_confidence = self._ar2_forecast(history)
        ar_shift = ar_forecast - implied_yes
        components["ar2_forecast"] = round(ar_forecast, 4)
        components["ar2_shift"] = round(ar_shift, 4)
        if abs(ar_shift) > 0.005:
            adjustments.append(ar_shift * 0.5)  # 50% weight on AR signal

        # ── 2. EWMA Volatility ──────────────────────────────────────
        vol = self._ewma_volatility(history)
        components["ewma_volatility"] = round(vol, 4)
        vol_regime = "high" if vol > 0.03 else "low" if vol < 0.01 else "normal"
        components["vol_regime"] = {"high": 1.0, "normal": 0.5, "low": 0.0}[vol_regime]

        # ── 3. Mean-Reversion Speed (OU half-life) ──────────────────
        half_life = self._ou_half_life(history)
        components["ou_half_life"] = round(half_life, 2)
        if half_life < 5.0:
            # Fast mean-reversion: price far from mean → revert
            mean_price = sum(history[-20:]) / len(history[-20:])
            mr_signal = (mean_price - implied_yes) * 0.3
            adjustments.append(mr_signal)
            components["mr_signal"] = round(mr_signal, 4)

        # ── 4. Trend Persistence (Hurst proxy) ─────────────────────
        hurst = self._hurst_proxy(history)
        components["hurst_proxy"] = round(hurst, 3)
        if hurst > 0.6:
            # Trending: amplify AR signal
            if adjustments:
                adjustments[-1] *= 1.3
        elif hurst < 0.4:
            # Anti-persistent: reduce AR, boost mean-reversion
            if len(adjustments) >= 1:
                adjustments[0] *= 0.6

        # ── Combine ─────────────────────────────────────────────────
        if not adjustments:
            return None

        total_adj = sum(adjustments)
        total_adj = max(-0.10, min(0.10, total_adj))  # Clamp ±10%
        components["total_adjustment"] = round(total_adj, 4)

        p_model = implied_yes + total_adj
        p_model = max(0.02, min(0.98, p_model))

        # Confidence: base from AR fit quality, scaled by volatility
        confidence = ar_confidence
        if vol_regime == "high":
            confidence *= 0.6  # Less certain in high-vol regime
        elif vol_regime == "low":
            confidence *= 1.1  # More certain in low-vol
        confidence = min(0.90, max(0.10, confidence))

        # Time decay: less confident near expiry for trend signals
        if minutes_to_expiry is not None and minutes_to_expiry < 30:
            confidence *= 0.7

        edge_estimate = abs(p_model - implied_yes) * 100
        components["edge_estimate"] = round(edge_estimate, 2)

        return ForecastResult(
            forecaster_id=self.forecaster_id,
            p_model=round(p_model, 4),
            confidence=round(confidence, 3),
            components=components,
        )

    def _ar2_forecast(self, history: List[float]) -> Tuple[float, float]:
        """Fit AR(2) and produce one-step-ahead forecast.

        Uses Yule-Walker estimation for speed. Returns (forecast, confidence).
        """
        n = len(history)
        if n < 5:
            return history[-1], 0.3

        # Compute autocovariances
        mean = sum(history) / n
        centered = [x - mean for x in history]

        c0 = sum(x * x for x in centered) / n
        if c0 < 1e-10:
            return history[-1], 0.5  # Nearly constant series

        c1 = sum(centered[i] * centered[i + 1] for i in range(n - 1)) / n
        c2 = sum(centered[i] * centered[i + 2] for i in range(n - 2)) / n

        # Yule-Walker for AR(2): solve [c0 c1; c1 c0] * [a1; a2] = [c1; c2]
        det = c0 * c0 - c1 * c1
        if abs(det) < 1e-10:
            # Degenerate: fall back to AR(1)
            a1 = c1 / c0 if c0 > 0 else 0
            a2 = 0
        else:
            a1 = (c0 * c1 - c1 * c2) / det
            a2 = (c0 * c2 - c1 * c1) / det

        # Clamp coefficients for stability
        a1 = max(-0.95, min(0.95, a1))
        a2 = max(-0.5, min(0.5, a2))

        # One-step-ahead forecast
        forecast = mean + a1 * centered[-1] + a2 * centered[-2]
        forecast = max(0.02, min(0.98, forecast))

        # Confidence from fit quality (R²-like)
        residuals = []
        for i in range(2, n):
            pred = mean + a1 * centered[i - 1] + a2 * centered[i - 2]
            residuals.append((centered[i] - (pred - mean)) ** 2)

        sse = sum(residuals)
        sst = sum(x * x for x in centered[2:])
        r_squared = 1 - (sse / sst) if sst > 1e-10 else 0.5
        confidence = max(0.15, min(0.85, 0.3 + r_squared * 0.5))

        return forecast, confidence

    def _ewma_volatility(self, history: List[float], decay: float = 0.94) -> float:
        """Compute EWMA (exponentially weighted) volatility of returns."""
        if len(history) < 3:
            return 0.02

        returns = [history[i] - history[i - 1] for i in range(1, len(history))]
        var = returns[0] ** 2
        for r in returns[1:]:
            var = decay * var + (1 - decay) * r * r

        return math.sqrt(max(var, 1e-10))

    def _ou_half_life(self, history: List[float]) -> float:
        """Estimate Ornstein-Uhlenbeck mean-reversion half-life.

        Uses linear regression of delta_x on x_{t-1}.
        Half-life = -ln(2) / theta where theta is the regression coefficient.
        """
        if len(history) < 5:
            return 50.0  # Default: slow mean-reversion

        dx = [history[i] - history[i - 1] for i in range(1, len(history))]
        x_lag = history[:-1]

        n = len(dx)
        mean_x = sum(x_lag) / n
        mean_dx = sum(dx) / n

        cov = sum((x_lag[i] - mean_x) * (dx[i] - mean_dx) for i in range(n)) / n
        var_x = sum((x - mean_x) ** 2 for x in x_lag) / n

        if var_x < 1e-10:
            return 50.0

        theta = cov / var_x

        if theta >= 0:
            return 50.0  # No mean-reversion detected

        half_life = -math.log(2) / theta
        return max(1.0, min(100.0, half_life))

    def _hurst_proxy(self, history: List[float]) -> float:
        """Quick Hurst exponent estimate via rescaled range (R/S).

        H > 0.5: trending (persistent)
        H = 0.5: random walk
        H < 0.5: anti-persistent (mean-reverting)
        """
        n = len(history)
        if n < 10:
            return 0.5

        # Use last 30 observations max
        series = history[-30:]
        n = len(series)

        mean = sum(series) / n
        centered = [x - mean for x in series]

        # Cumulative sum
        cumsum = []
        s = 0
        for c in centered:
            s += c
            cumsum.append(s)

        r = max(cumsum) - min(cumsum)
        std = math.sqrt(sum(c * c for c in centered) / n) if n > 0 else 1e-6

        if std < 1e-10:
            return 0.5

        rs = r / std
        if rs <= 0:
            return 0.5

        # H ≈ log(R/S) / log(n)
        hurst = math.log(rs) / math.log(n)
        return max(0.1, min(0.9, hurst))
