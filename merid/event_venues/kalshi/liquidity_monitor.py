"""Kalshi Liquidity Monitor — Real-time orderbook health alerting.

Processes orderbook snapshots and emits structured alerts when:
  - Spread exceeds threshold (wide_spread)
  - Total depth drops below minimum (thin_book)
  - Spread widens sharply vs rolling average (spread_spike)
  - Depth drops sharply vs rolling average (depth_drop)

Plugs into KalshiWebSocketBridge via ``process()`` or the event bus
via ``attach_to_bridge()``.

Usage::

    monitor = LiquidityMonitor(max_spread=0.08, min_depth=50)
    >>> monitor.on_alert(lambda a: print(a))

    # From WS bridge callback:
    monitor.process(OrderBookSnapshot(...))

    # Or attach to event bus:
    await monitor.attach_to_bridge(bridge)
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.liquidity_monitor")


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class OrderBookSnapshot:
    """Point-in-time orderbook top-of-book for a Kalshi market."""
    market_id: str
    best_bid: float
    best_ask: float
    bid_size: int
    ask_size: int
    ts: float = field(default_factory=time.time)

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def depth(self) -> int:
        return self.bid_size + self.ask_size

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2


@dataclass
class LiquidityAlert:
    """Structured alert emitted when liquidity degrades."""
    market_id: str
    kind: str        # wide_spread | thin_book | spread_spike | depth_drop
    severity: str    # info | warning | critical
    msg: str
    ts: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "kind": self.kind,
            "severity": self.severity,
            "msg": self.msg,
            "ts": self.ts,
            "details": self.details,
        }


# ── Alert Callback Type ─────────────────────────────────────────────────────

AlertCallback = Callable[[LiquidityAlert], None]


# ── LiquidityMonitor ─────────────────────────────────────────────────────────


class LiquidityMonitor:
    """Monitors Kalshi orderbook health and emits liquidity alerts.

    Args:
        max_spread: Absolute spread threshold (in probability units, e.g. 0.08 = 8¢).
        min_depth: Minimum total depth (bid_size + ask_size) before thin_book alert.
        spike_mult: Rolling-average multiplier for spread_spike detection.
        drop_mult: Rolling-average multiplier for depth_drop detection.
        window: Number of snapshots in rolling window per market.
        cooldown_s: Minimum seconds between alerts of the same kind for the same market.
        flicker_window: Number of consecutive ticks to look back for flickering detection.
        flicker_threshold: Fraction of ticks that must oscillate to trigger flicker alert.
    """

    def __init__(
        self,
        max_spread: float = 0.08,
        min_depth: int = 50,
        spike_mult: float = 2.0,
        drop_mult: float = 0.5,
        window: int = 20,
        cooldown_s: float = 30.0,
        flicker_window: int = 10,
        flicker_threshold: float = 0.7,
    ):
        self.max_spread = max_spread
        self.min_depth = min_depth
        self.spike_mult = spike_mult
        self.drop_mult = drop_mult
        self.window = window
        self.cooldown_s = cooldown_s
        self.flicker_window = flicker_window
        self.flicker_threshold = flicker_threshold

        self._buffers: Dict[str, Deque[OrderBookSnapshot]] = {}
        self._callbacks: List[AlertCallback] = []
        self._last_alert_ts: Dict[str, float] = {}  # key = f"{market_id}:{kind}"
        self._alert_log: Deque[LiquidityAlert] = deque(maxlen=500)
        self._snapshots_processed: int = 0
        self._wire_prediction_alert_manager()

    # ── PredictionAlertManager bridge ───────────────────────────────────

    def _wire_prediction_alert_manager(self) -> None:
        """Register a callback that forwards LiquidityAlerts to the main
        PredictionAlertManager so they appear on the Telegram sink and
        in the PM alert history alongside risk/kill-switch alerts."""
        def _pm_bridge(alert: LiquidityAlert) -> None:
            try:
                from merid.prediction.alerts import get_alert_manager
                from config.kalshi_crypto_config import kalshi_ticker_to_asset

                mgr = get_alert_manager()
                details = dict(alert.details or {})
                sym = kalshi_ticker_to_asset(alert.market_id)
                if sym:
                    details.setdefault("symbol", sym)
                if alert.severity == "critical" or alert.kind in ("wide_spread", "thin_book", "zero_depth"):
                    mgr.fire_risk_breach(
                        market_id=alert.market_id,
                        message=f"[liquidity/{alert.kind}] {alert.msg}",
                        data=details,
                    )
                else:
                    mgr.fire_risk_warning(
                        market_id=alert.market_id,
                        message=f"[liquidity/{alert.kind}] {alert.msg}",
                        data=details,
                    )
            except Exception as exc:
                logger.debug("PM alert bridge error (non-fatal): %s", exc)

        self._callbacks.append(_pm_bridge)

    # ── Callback registration ────────────────────────────────────────────

    def on_alert(self, callback: AlertCallback) -> None:
        """Register a callback invoked on each alert."""
        self._callbacks.append(callback)

    # ── Core processing ──────────────────────────────────────────────────

    def process(self, ob: OrderBookSnapshot) -> List[LiquidityAlert]:
        """Process an orderbook snapshot and return any alerts generated."""
        buf = self._buffers.setdefault(ob.market_id, deque(maxlen=self.window))
        buf.append(ob)
        self._snapshots_processed += 1

        alerts: List[LiquidityAlert] = []

        spread = ob.spread
        depth = ob.depth

        # 1. Absolute spread check
        if spread > self.max_spread:
            sev = "critical" if spread > self.max_spread * 1.5 else "warning"
            alerts.append(LiquidityAlert(
                market_id=ob.market_id,
                kind="wide_spread",
                severity=sev,
                msg=f"Spread {spread:.3f} > {self.max_spread:.3f}",
                ts=ob.ts,
                details={"spread": spread, "threshold": self.max_spread,
                         "bid": ob.best_bid, "ask": ob.best_ask},
            ))

        # 2. Absolute depth check (zero-depth is always critical)
        if depth == 0:
            alerts.append(LiquidityAlert(
                market_id=ob.market_id,
                kind="zero_depth",
                severity="critical",
                msg=f"Zero depth — book is completely empty (bid=0, ask=0)",
                ts=ob.ts,
                details={"depth": 0, "bid_size": ob.bid_size, "ask_size": ob.ask_size},
            ))
        elif depth < self.min_depth:
            sev = "critical" if depth < self.min_depth // 2 else "warning"
            alerts.append(LiquidityAlert(
                market_id=ob.market_id,
                kind="thin_book",
                severity=sev,
                msg=f"Depth {depth} < {self.min_depth}",
                ts=ob.ts,
                details={"depth": depth, "threshold": self.min_depth,
                         "bid_size": ob.bid_size, "ask_size": ob.ask_size},
            ))

        # 3. Spread spike vs rolling average
        if len(buf) >= 5:
            avg_spread = sum(s.spread for s in buf) / len(buf)
            if avg_spread > 0 and spread > avg_spread * self.spike_mult:
                alerts.append(LiquidityAlert(
                    market_id=ob.market_id,
                    kind="spread_spike",
                    severity="warning",
                    msg=f"Spread {spread:.3f} is {spread/avg_spread:.1f}x rolling avg {avg_spread:.3f}",
                    ts=ob.ts,
                    details={"spread": spread, "avg_spread": avg_spread,
                             "multiplier": spread / avg_spread},
                ))

        # 4. Depth drop vs rolling average
        if len(buf) >= 5:
            avg_depth = sum(s.depth for s in buf) / len(buf)
            if avg_depth > 0 and depth < avg_depth * self.drop_mult:
                alerts.append(LiquidityAlert(
                    market_id=ob.market_id,
                    kind="depth_drop",
                    severity="warning",
                    msg=f"Depth {depth} dropped to {depth/avg_depth:.0%} of rolling avg {avg_depth:.0f}",
                    ts=ob.ts,
                    details={"depth": depth, "avg_depth": avg_depth,
                             "ratio": depth / avg_depth},
                ))

        # 5. Flickering: best bid oscillates rapidly over the last N ticks
        if len(buf) >= self.flicker_window:
            recent = list(buf)[-self.flicker_window:]
            bids = [s.best_bid for s in recent]
            alternations = sum(
                1 for i in range(1, len(bids)) if bids[i] != bids[i - 1]
            )
            if alternations / (self.flicker_window - 1) >= self.flicker_threshold:
                alerts.append(LiquidityAlert(
                    market_id=ob.market_id,
                    kind="flickering",
                    severity="warning",
                    msg=(
                        f"Bid flickering: {alternations}/{self.flicker_window - 1} "
                        f"ticks changed ({alternations / (self.flicker_window - 1):.0%})"
                    ),
                    ts=ob.ts,
                    details={"alternations": alternations, "window": self.flicker_window,
                             "ratio": alternations / (self.flicker_window - 1)},
                ))

        # Apply cooldown and emit
        emitted: List[LiquidityAlert] = []
        for alert in alerts:
            key = f"{alert.market_id}:{alert.kind}"
            last = self._last_alert_ts.get(key, 0)
            if alert.ts - last >= self.cooldown_s:
                self._last_alert_ts[key] = alert.ts
                self._alert_log.append(alert)
                emitted.append(alert)
                self._emit(alert)

        return emitted

    def _emit(self, alert: LiquidityAlert) -> None:
        """Fire all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(alert)
            except Exception as exc:
                logger.warning(f"Liquidity alert callback error: {exc}")

    # ── Event bus integration ────────────────────────────────────────────

    async def attach_to_bridge(self, bridge: Any) -> None:
        """Subscribe to orderbook events from KalshiWebSocketBridge.

        Listens for ``kalshi:price_update`` events (which carry bid/ask)
        and converts them to ``OrderBookSnapshot`` for processing.
        """
        from core.event_bus import event_stream

        async def _handler(event: Dict[str, Any]) -> None:
            if event.get("type") != "kalshi:price_update":
                return
            payload = event.get("payload", {})
            bid = payload.get("bid")
            ask = payload.get("ask")
            if bid is None or ask is None:
                return
            ob = OrderBookSnapshot(
                market_id=payload.get("market_id", ""),
                best_bid=float(bid),
                best_ask=float(ask),
                bid_size=int(payload.get("bid_size", 100)),
                ask_size=int(payload.get("ask_size", 100)),
                ts=time.time(),
            )
            self.process(ob)

        await event_stream.subscribe("kalshi:price_update", _handler)
        logger.info("LiquidityMonitor attached to WS bridge event bus")

    # ── Status / Reporting ───────────────────────────────────────────────

    def recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return most recent alerts as dicts."""
        return [a.to_dict() for a in list(self._alert_log)[-limit:]]

    def market_health(self, market_id: str) -> Dict[str, Any]:
        """Current health snapshot for a single market."""
        buf = self._buffers.get(market_id)
        if not buf:
            return {"market_id": market_id, "status": "no_data"}

        latest = buf[-1]
        avg_spread = sum(s.spread for s in buf) / len(buf) if buf else 0
        avg_depth = sum(s.depth for s in buf) / len(buf) if buf else 0

        status = "healthy"
        if latest.spread > self.max_spread:
            status = "degraded"
        if latest.depth < self.min_depth:
            status = "thin"
        if latest.spread > self.max_spread and latest.depth < self.min_depth:
            status = "critical"

        return {
            "market_id": market_id,
            "status": status,
            "spread": latest.spread,
            "depth": latest.depth,
            "avg_spread": avg_spread,
            "avg_depth": avg_depth,
            "mid": latest.mid,
            "snapshots": len(buf),
        }

    def summary(self) -> Dict[str, Any]:
        """JSON-serializable monitor summary."""
        return {
            "markets_tracked": len(self._buffers),
            "snapshots_processed": self._snapshots_processed,
            "alerts_total": len(self._alert_log),
            "alerts_recent": self.recent_alerts(10),
            "thresholds": {
                "max_spread": self.max_spread,
                "min_depth": self.min_depth,
                "spike_mult": self.spike_mult,
                "drop_mult": self.drop_mult,
            },
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_monitor: Optional[LiquidityMonitor] = None
_monitor_lock = threading.Lock()


def get_liquidity_monitor() -> LiquidityMonitor:
    """Get or create the singleton LiquidityMonitor."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = LiquidityMonitor()
    return _monitor
