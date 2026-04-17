"""Crypto Term Structure Model — RTI-based probability engine.

Polls CryptoRTIMonitor every second for BTC/ETH/SOL/XRP/DOGE, accumulates
1-minute close bars (30 days deep per asset), and exposes log-normal probability
and vol APIs consumed by SpotBasisFairValueStrategy and TrendMomentumOpinionStrategy.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.risk.crypto_term_structure")

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
MAX_BARS = 43_200           # 30d × 1 440 min/d
MINUTES_PER_YEAR = 525_600
MIN_BARS_READY = 30         # minimum bars before vol estimates are trusted

_FALLBACK_VOL: Dict[str, float] = {
    "BTC": 0.70, "ETH": 0.80, "SOL": 1.00, "XRP": 0.90, "DOGE": 1.20,
}


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via stdlib math.erfc — exact, no scipy needed."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


class CryptoTermStructureModel:
    """Stateful RTI-based vol and probability engine for all 5 Kalshi crypto assets."""

    def __init__(self) -> None:
        self._bars: Dict[str, deque] = {
            a: deque(maxlen=MAX_BARS) for a in ASSETS
        }
        # In-progress accumulator: asset → (minute_ts_epoch, latest_close)
        self._current_minute: Dict[str, Tuple[float, float]] = {}
        self._task: Optional[asyncio.Task] = None
        self._monitor = None  # set in start()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        from merid.risk.crypto_rti_monitor import get_global_crypto_rti_monitor
        self._monitor = get_global_crypto_rti_monitor()
        self._task = asyncio.create_task(self._poll_loop(), name="crypto-term-structure")
        def _task_done_cb(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("CryptoTermStructure task crashed: %s", task.exception())
        self._task.add_done_callback(_task_done_cb)
        logger.info("CryptoTermStructureModel started (assets=%s)", ASSETS)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("CryptoTermStructureModel stopped")

    async def _poll_loop(self) -> None:
        while True:
            ts = time.time()
            for asset in ASSETS:
                try:
                    metrics = self._monitor.get_rti_metrics(asset)
                    price = metrics.get("rti_current", 0.0)
                    if price > 0:
                        self._ingest_tick(asset, price, ts)
                except Exception as exc:
                    logger.debug("TSM poll error %s: %s", asset, exc)
            await asyncio.sleep(1.0)

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def _ingest_tick(self, asset: str, price: float, ts: float) -> None:
        """Roll a 1-second RTI tick into the 1-minute bar buffer.

        A bar closes when the new tick arrives >= 60 seconds after the bar's
        first tick.  This is a session-relative window rather than calendar-
        minute bucketing so that short test sequences behave predictably.
        """
        asset = asset.upper()
        if asset not in self._current_minute:
            self._current_minute[asset] = (ts, price)
            return
        bar_open_ts, prev_price = self._current_minute[asset]
        if ts - bar_open_ts >= 60:
            # Close the previous bar with its last known price
            self._bars[asset].append((bar_open_ts, prev_price))
            self._current_minute[asset] = (ts, price)
        else:
            # Still within the same 60-second window — update close only
            self._current_minute[asset] = (bar_open_ts, price)

    # ── Public accessors ──────────────────────────────────────────────────────

    def is_ready(self, asset: str) -> bool:
        return len(self._bars[asset.upper()]) >= MIN_BARS_READY

    def current_price(self, asset: str) -> float:
        if self._monitor is None:
            return 0.0
        try:
            return self._monitor.get_rti_metrics(asset.upper()).get("rti_current", 0.0)
        except Exception:
            return 0.0

    def get_returns(self, asset: str, window_minutes: int) -> List[float]:
        """Log returns of the last window_minutes closed bars."""
        buf = self._bars.get(asset.upper())
        if buf is None:
            return []
        bars = list(buf)[-window_minutes:]
        if len(bars) < 2:
            return []
        prices = [p for _, p in bars]
        result = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0 and prices[i] > 0:
                result.append(math.log(prices[i] / prices[i - 1]))
        return result

    def get_recent_prices(self, asset: str, n: int) -> List[float]:
        """Raw close prices of the last n bars (used by MA computation)."""
        buf = self._bars.get(asset.upper())
        if buf is None:
            return []
        return [p for _, p in list(buf)[-n:]]

    # ── Vol estimation ────────────────────────────────────────────────────────

    def _pick_vol_window(self, horizon_secs: float) -> int:
        if horizon_secs <= 15 * 60:
            return 15
        if horizon_secs <= 3_600:
            return 60
        if horizon_secs <= 4 * 3_600:
            return 240
        if horizon_secs <= 86_400:
            return 1_440
        if horizon_secs <= 604_800:
            return 10_080
        return 43_200

    def _realized_vol_annual(self, asset: str, window_minutes: int) -> float:
        returns = self.get_returns(asset, window_minutes)
        if len(returns) < 5:
            return _FALLBACK_VOL.get(asset.upper(), 0.90)
        n = len(returns)
        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
        return (variance ** 0.5) * (MINUTES_PER_YEAR ** 0.5)

    # ── Probability API ───────────────────────────────────────────────────────

    def fair_prob(
        self, asset: str, horizon_secs: float,
        strike: float, side: str = "above",
    ) -> float:
        """P(RTI_T side strike) under log-normal with realized vol.

        Returns 0.5 if the model is not ready or prices are invalid.
        Clipped to [1e-4, 1-1e-4].
        """
        S = self.current_price(asset)
        if S <= 0 or strike <= 0 or not self.is_ready(asset):
            return 0.5
        T = horizon_secs / (365.25 * 86_400)
        if T <= 0:
            return 1.0 if (side == "above" and S >= strike) else 0.0
        sigma = self._realized_vol_annual(asset, self._pick_vol_window(horizon_secs))
        if sigma <= 0:
            return 0.5
        d = (math.log(S / strike) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
        p = _norm_cdf(d) if side == "above" else _norm_cdf(-d)
        return max(1e-4, min(1 - 1e-4, p))

    def bracket_prob(
        self, asset: str, horizon_secs: float, low: float, high: float,
    ) -> float:
        """P(low <= RTI_T < high). Clipped to [1e-4, 1-1e-4]."""
        p = (self.fair_prob(asset, horizon_secs, low, "above")
             - self.fair_prob(asset, horizon_secs, high, "above"))
        return max(1e-4, min(1 - 1e-4, p))

    def up_prob(self, asset: str, horizon_secs: float) -> float:
        """P(RTI_T > RTI_now) for Up/Down markets, drift-adjusted with 0.5 damping."""
        short_window = max(5, min(30, int(horizon_secs / 60)))
        returns = self.get_returns(asset, short_window)
        if len(returns) < 2:
            return 0.5
        T = horizon_secs / (365.25 * 86_400)
        if T <= 0:
            return 0.5
        sigma = self._realized_vol_annual(asset, self._pick_vol_window(horizon_secs))
        if sigma <= 0:
            return 0.5
        mean_r = sum(returns) / len(returns)
        drift_z = (mean_r / (sigma * math.sqrt(T))) * 0.5  # 0.5 damping
        return max(1e-4, min(1 - 1e-4, _norm_cdf(drift_z)))

    def implied_move(self, asset: str, horizon_secs: float) -> float:
        """Expected fractional move: σ_annual × √T (T in years)."""
        sigma = self._realized_vol_annual(asset, self._pick_vol_window(horizon_secs))
        T = horizon_secs / (365.25 * 86_400)
        return sigma * math.sqrt(T)


# ── Singleton ─────────────────────────────────────────────────────────────────

_tsm_instance: Optional[CryptoTermStructureModel] = None


def get_global_crypto_tsm() -> CryptoTermStructureModel:
    global _tsm_instance
    if _tsm_instance is None:
        raise RuntimeError(
            "CryptoTermStructureModel not initialized — "
            "call set_global_crypto_tsm() first"
        )
    return _tsm_instance


def set_global_crypto_tsm(tsm: CryptoTermStructureModel) -> None:
    global _tsm_instance
    _tsm_instance = tsm
