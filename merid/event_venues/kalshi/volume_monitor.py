"""Kalshi Volume Monitor — Track volume changes across markets.

Polls the market catalog periodically, diffs volume against last-known
values, stores time-series history, fires alerts on spikes, and exposes
changes for the REST API and event bus.

Usage::

    monitor = get_volume_monitor()
    monitor.poll()  # snapshot current volumes
    # ... time passes ...
    monitor.poll()  # detect changes + fire alerts
    changes = monitor.get_changes(min_delta=100)
    history = monitor.get_history("KXBTC15M_1", limit=50)
"""

from __future__ import annotations

import math
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.volume_monitor")

# Type alias for alert callbacks: (ticker, old_vol, new_vol, delta) -> None
VolumeAlertCallback = Callable[[str, float, float, float], None]

MAX_HISTORY_PER_TICKER = 500


class Kalman1D:
    """Minimal 1-D Kalman filter for smoothing volume time-series.

    Args:
        process_var: Process noise variance (higher = more responsive)
        meas_var: Measurement noise variance (higher = more smoothing)
    """

    def __init__(self, process_var: float = 1.0, meas_var: float = 10.0) -> None:
        self.x: float = 0.0   # state (smoothed volume)
        self.P: float = 1.0   # state covariance
        self.Q: float = process_var
        self.R: float = meas_var
        self.initialized: bool = False

    def update(self, z: float) -> float:
        """Feed a new measurement and return the smoothed estimate."""
        if not self.initialized:
            self.x = z
            self.initialized = True
            return self.x

        # Predict
        x_pred = self.x
        P_pred = self.P + self.Q

        # Update
        K = P_pred / (P_pred + self.R)
        self.x = x_pred + K * (z - x_pred)
        self.P = (1 - K) * P_pred
        return self.x

    def reset(self) -> None:
        """Reset filter state."""
        self.x = 0.0
        self.P = 1.0
        self.initialized = False


class PriceKalman:
    """1-D Kalman filter tuned for Kalshi price series (cents).

    Lower default noise than ``Kalman1D`` because price movements are
    smaller and more structured than volume changes.

    Args:
        process_var: How fast the underlying price can move (default 0.01)
        meas_var: Noise level of observed prices (default 0.1)
    """

    def __init__(self, process_var: float = 1e-2, meas_var: float = 1e-1) -> None:
        self.x: float = 0.0   # estimated price
        self.P: float = 1.0   # estimate covariance
        self.Q: float = process_var
        self.R: float = meas_var
        self.initialized: bool = False

    def update(self, z: float) -> float:
        """Feed a new price observation and return the smoothed estimate."""
        if not self.initialized:
            self.x = z
            self.initialized = True
            return self.x

        # Predict
        x_pred = self.x
        P_pred = self.P + self.Q

        # Update
        K = P_pred / (P_pred + self.R)
        self.x = x_pred + K * (z - x_pred)
        self.P = (1 - K) * P_pred
        return self.x

    def reset(self) -> None:
        """Reset filter state."""
        self.x = 0.0
        self.P = 1.0
        self.initialized = False


def tune_kalman_params(
    prices: List[float],
    q_values: Optional[List[float]] = None,
    r_values: Optional[List[float]] = None,
) -> Tuple[float, float, float]:
    """Grid-search (Q, R) to minimize 1-step-ahead prediction error.

    Args:
        prices: Historical price series (cents or dollars)
        q_values: Process variance candidates (default: logspace)
        r_values: Measurement variance candidates (default: logspace)

    Returns:
        (best_q, best_r, best_mse)
    """
    if q_values is None:
        q_values = [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
    if r_values is None:
        r_values = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]

    best_q, best_r = q_values[0], r_values[0]
    best_err = float("inf")

    for q in q_values:
        for r in r_values:
            kf = PriceKalman(process_var=q, meas_var=r)
            preds: List[float] = []
            for z in prices:
                pred_before = kf.x if kf.initialized else z
                kf.update(z)
                preds.append(pred_before)
            # MSE on 1-step-ahead predictions (skip first)
            if len(prices) > 1:
                err = sum(
                    (a - b) ** 2 for a, b in zip(prices[1:], preds[1:])
                ) / (len(prices) - 1)
            else:
                err = 0.0
            if err < best_err:
                best_err, best_q, best_r = err, q, r

    return best_q, best_r, best_err


@dataclass
class VolumeSnapshot:
    """Single point-in-time volume reading."""
    ts: str           # ISO timestamp
    volume: float
    delta: float = 0  # change from previous snapshot


class VolumeMonitor:
    """Tracks volume deltas, time-series, and alerts across Kalshi markets."""

    def __init__(self) -> None:
        self._last_volumes: Dict[str, float] = {}
        self._deltas: Dict[str, Dict[str, Any]] = {}
        self._last_poll: Optional[datetime] = None
        # Time-series: ticker -> deque of VolumeSnapshot
        self._history: Dict[str, Deque[VolumeSnapshot]] = {}
        # Alert system
        self._alert_callbacks: List[VolumeAlertCallback] = []
        self._alert_threshold: float = 0  # min absolute delta to fire alert
        self._alerts_fired: List[Dict[str, Any]] = []
        self._poll_count: int = 0

    # ── Alert registration ────────────────────────────────────────────────

    def register_alert(
        self,
        callback: VolumeAlertCallback,
        threshold: float = 1000.0,
    ) -> None:
        """Register a callback fired when volume delta >= threshold.

        Args:
            callback: ``(ticker, old_vol, new_vol, delta) -> None``
            threshold: Minimum absolute delta to trigger alert
        """
        self._alert_callbacks.append(callback)
        if threshold > self._alert_threshold:
            self._alert_threshold = threshold

    def _fire_alerts(self, ticker: str, old_vol: float, new_vol: float, delta: float) -> None:
        """Fire registered alert callbacks if delta meets threshold."""
        if abs(delta) < self._alert_threshold:
            return
        now = datetime.now(timezone.utc).isoformat()
        alert_record = {
            "ticker": ticker,
            "old_volume": old_vol,
            "new_volume": new_vol,
            "delta": delta,
            "fired_at": now,
        }
        self._alerts_fired.append(alert_record)
        # Keep last 200 alerts
        if len(self._alerts_fired) > 200:
            self._alerts_fired = self._alerts_fired[-200:]

        for cb in self._alert_callbacks:
            try:
                cb(ticker, old_vol, new_vol, delta)
            except Exception as exc:
                logger.warning(f"Volume alert callback error: {exc}")

    # ── Polling ───────────────────────────────────────────────────────────

    def poll(self) -> int:
        """Snapshot current catalog volumes, compute deltas, store history, fire alerts.

        Returns the number of markets with volume changes.
        """
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
        except Exception as exc:
            logger.warning(f"Volume monitor poll failed: {exc}")
            return 0

        changes = 0
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        new_deltas: Dict[str, Dict[str, Any]] = {}

        for cm in catalog.get_all_markets():
            ticker = cm.market.market_id
            vol = float(cm.market.volume) if cm.market.volume else 0.0
            prev = self._last_volumes.get(ticker, vol)
            delta = vol - prev

            # Store time-series
            if ticker not in self._history:
                self._history[ticker] = deque(maxlen=MAX_HISTORY_PER_TICKER)
            self._history[ticker].append(VolumeSnapshot(ts=now_iso, volume=vol, delta=delta))

            if delta != 0:
                new_deltas[ticker] = {
                    "ticker": ticker,
                    "question": cm.market.question,
                    "category": cm.category or "",
                    "asset": cm.asset or "",
                    "previous_volume": prev,
                    "current_volume": vol,
                    "delta": delta,
                    "pct_change": round(delta / prev * 100, 2) if prev > 0 else 0,
                    "detected_at": now_iso,
                }
                changes += 1
                # Fire alerts
                self._fire_alerts(ticker, prev, vol, delta)

            self._last_volumes[ticker] = vol

        self._deltas = new_deltas
        self._last_poll = now
        self._poll_count += 1

        if changes > 0:
            logger.info(f"Volume monitor: {changes} markets changed (poll #{self._poll_count})")

        return changes

    # ── Query ─────────────────────────────────────────────────────────────

    def get_changes(
        self,
        *,
        series_ticker: Optional[str] = None,
        min_delta: float = 0,
    ) -> List[Dict[str, Any]]:
        """Return volume changes, optionally filtered.

        Args:
            series_ticker: Filter by ticker prefix (e.g. "KXBTC")
            min_delta: Minimum absolute volume change to include
        """
        results = list(self._deltas.values())

        if series_ticker:
            st = series_ticker.upper()
            results = [c for c in results if c["ticker"].upper().startswith(st)]

        if min_delta > 0:
            results = [c for c in results if abs(c["delta"]) >= min_delta]

        # Sort by absolute delta descending
        results.sort(key=lambda c: abs(c["delta"]), reverse=True)
        return results

    def get_history(
        self,
        ticker: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return time-series volume history for a ticker.

        Args:
            ticker: Market ticker
            limit: Max number of snapshots to return (most recent first)
        """
        hist = self._history.get(ticker)
        if not hist:
            return []
        items = list(hist)[-limit:]
        items.reverse()
        return [{"ts": s.ts, "volume": s.volume, "delta": s.delta} for s in items]

    def get_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent volume alerts (most recent first)."""
        return list(reversed(self._alerts_fired[-limit:]))

    def get_smoothed_history(
        self,
        ticker: str,
        limit: int = 100,
        process_var: float = 1.0,
        meas_var: float = 10.0,
    ) -> List[Dict[str, Any]]:
        """Return Kalman-smoothed volume history for a ticker.

        Applies a 1-D Kalman filter over the raw volume series to produce
        a smoothed trend line suitable for charting.

        Args:
            ticker: Market ticker
            limit: Max snapshots to return (most recent first)
            process_var: Kalman process noise (higher = more responsive)
            meas_var: Kalman measurement noise (higher = more smoothing)
        """
        hist = self._history.get(ticker)
        if not hist:
            return []
        kf = Kalman1D(process_var=process_var, meas_var=meas_var)
        items = list(hist)
        results = []
        for s in items:
            smoothed = kf.update(s.volume)
            results.append({
                "ts": s.ts,
                "volume": s.volume,
                "smoothed": round(smoothed, 2),
                "delta": s.delta,
            })
        # Return most recent first, limited
        results = results[-limit:]
        results.reverse()
        return results

    # ── Anomaly detection ─────────────────────────────────────────────────

    def detect_anomalies(
        self,
        *,
        z_threshold: float = 3.0,
        min_window: int = 5,
    ) -> List[Dict[str, Any]]:
        """Detect volume anomalies using rolling z-score across all tracked tickers.

        For each ticker with enough history, compute the z-score of the
        latest volume reading against the rolling window. Return entries
        where ``|z| >= z_threshold``.

        Args:
            z_threshold: Minimum absolute z-score to flag as anomaly
            min_window: Minimum history points required before scoring
        """
        anomalies: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for ticker, hist in self._history.items():
            if len(hist) < min_window:
                continue
            vols = [s.volume for s in hist]
            mean = sum(vols) / len(vols)
            var = sum((v - mean) ** 2 for v in vols) / len(vols)
            std = math.sqrt(var)
            if std == 0:
                continue
            latest = vols[-1]
            z = (latest - mean) / std
            if abs(z) >= z_threshold:
                anomalies.append({
                    "ticker": ticker,
                    "volume": latest,
                    "mean": round(mean, 2),
                    "std": round(std, 2),
                    "z_score": round(z, 2),
                    "window_size": len(vols),
                    "detected_at": now_iso,
                })

        # Sort by absolute z-score descending
        anomalies.sort(key=lambda a: abs(a["z_score"]), reverse=True)
        return anomalies

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def tracked_count(self) -> int:
        """Number of markets being tracked."""
        return len(self._last_volumes)

    @property
    def last_poll_iso(self) -> Optional[str]:
        """ISO timestamp of last poll."""
        return self._last_poll.isoformat() if self._last_poll else None

    @property
    def poll_count(self) -> int:
        """Total number of polls executed."""
        return self._poll_count

    @property
    def alert_count(self) -> int:
        """Total alerts fired."""
        return len(self._alerts_fired)


# ── Singleton ────────────────────────────────────────────────────────────

_monitor: Optional[VolumeMonitor] = None


def get_volume_monitor() -> VolumeMonitor:
    """Get or create the singleton VolumeMonitor."""
    global _monitor
    if _monitor is None:
        _monitor = VolumeMonitor()
    return _monitor


# ── Alert sinks (Telegram / Discord) ─────────────────────────────────────

KALSHI_ADVANCED_API_FORM = "https://kalshi.typeform.com/advanced-api"


def make_telegram_sink(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> VolumeAlertCallback:
    """Create a Telegram alert callback for volume spikes.

    Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from env if not provided.
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    cid = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

    def _send(ticker: str, old_vol: float, new_vol: float, delta: float) -> None:
        if not token or not cid:
            logger.warning("Telegram sink: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
            return
        try:
            import requests as _req
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            msg = f"🔔 Kalshi {ticker} volume +{delta:.0f} (now {new_vol:.0f})"
            _req.post(url, json={"chat_id": cid, "text": msg}, timeout=5)
        except Exception as exc:
            logger.warning(f"Telegram send failed: {exc}")

    return _send


def make_discord_sink(
    webhook_url: Optional[str] = None,
) -> VolumeAlertCallback:
    """Create a Discord webhook alert callback for volume spikes.

    Reads ``DISCORD_WEBHOOK_URL`` from env if not provided.
    """
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")

    def _send(ticker: str, old_vol: float, new_vol: float, delta: float) -> None:
        if not url:
            logger.warning("Discord sink: DISCORD_WEBHOOK_URL not set")
            return
        try:
            import requests as _req
            msg = f"🔔 Kalshi {ticker} volume +{delta:.0f} (now {new_vol:.0f})"
            _req.post(url, json={"content": msg}, timeout=5)
        except Exception as exc:
            logger.warning(f"Discord send failed: {exc}")

    return _send
