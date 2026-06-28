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
    monitor.process(OrderbookSnapshot(...))

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

# Import canonical OrderbookSnapshot and microstructure utilities
# This is the single source of truth for order book representation
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
from merid.event_venues.kalshi.microstructure import (
    compute_side_microstructure,
    cents_to_dollars,
    dollars_to_cents,
)

logger = get_logger("merid.event_venues.kalshi.liquidity_monitor")


# ── Data Models ──────────────────────────────────────────────────────────────


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

    Uses canonical OrderbookSnapshot from unified_market_state.
    Thresholds are in probability units (e.g. 0.08 = 8¢).

    Args:
        max_spread: Absolute spread threshold (in probability units, e.g. 0.08 = 8¢).
        min_depth: Minimum total depth (yes + no) before thin_book alert.
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

        self._buffers: Dict[str, Deque[OrderbookSnapshot]] = {}
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

    def process(self, ob: OrderbookSnapshot) -> List[LiquidityAlert]:
        """Process an orderbook snapshot and return any alerts generated.
        
        Uses canonical OrderbookSnapshot from unified_market_state.
        Converts cents to probability units for threshold comparisons.
        """
        buf = self._buffers.setdefault(ob.ticker, deque(maxlen=self.window))
        buf.append(ob)
        self._snapshots_processed += 1

        alerts: List[LiquidityAlert] = []

        # Convert canonical snapshot's spread_cents to probability units
        spread_cents = ob.spread_cents if ob.spread_cents is not None else 0
        spread = cents_to_dollars(spread_cents) if spread_cents else 0.0
        
        # Use microstructure utility for depth calculation
        micro = compute_side_microstructure(ob, side="yes", size=1, depth_window_cents=10)
        depth = micro.depth_yes_at_best + micro.depth_no_at_best
        
        # Get best bid/ask from canonical snapshot (YES-centric)
        best_yes_bid = cents_to_dollars(ob.best_yes_bid) if ob.best_yes_bid else 0.0
        best_yes_ask = cents_to_dollars(ob.best_yes_ask) if ob.best_yes_ask else 0.0

        # 1. Absolute spread check
        if spread > self.max_spread:
            sev = "critical" if spread > self.max_spread * 1.5 else "warning"
            alerts.append(LiquidityAlert(
                market_id=ob.ticker,
                kind="wide_spread",
                severity=sev,
                msg=f"Spread {spread:.3f} > {self.max_spread:.3f}",
                ts=ob.ts,
                details={"spread": spread, "threshold": self.max_spread,
                         "bid": best_yes_bid, "ask": best_yes_ask},
            ))

        # 2. Absolute depth check (zero-depth is always critical)
        if depth == 0:
            alerts.append(LiquidityAlert(
                market_id=ob.ticker,
                kind="zero_depth",
                severity="critical",
                msg=f"Zero depth — book is completely empty",
                ts=ob.ts,
                details={"depth": 0, "depth_yes": micro.depth_yes_at_best, "depth_no": micro.depth_no_at_best},
            ))
        elif depth < self.min_depth:
            sev = "critical" if depth < self.min_depth // 2 else "warning"
            alerts.append(LiquidityAlert(
                market_id=ob.ticker,
                kind="thin_book",
                severity=sev,
                msg=f"Depth {depth} < {self.min_depth}",
                ts=ob.ts,
                details={"depth": depth, "threshold": self.min_depth,
                         "depth_yes": micro.depth_yes_at_best, "depth_no": micro.depth_no_at_best},
            ))

        # 3. Spread spike vs rolling average
        if len(buf) >= 5:
            avg_spread_cents = sum(
                s.spread_cents if s.spread_cents else 0 for s in buf
            ) / len(buf)
            avg_spread = cents_to_dollars(avg_spread_cents) if avg_spread_cents else 0.0
            if avg_spread > 0 and spread > avg_spread * self.spike_mult:
                alerts.append(LiquidityAlert(
                    market_id=ob.ticker,
                    kind="spread_spike",
                    severity="warning",
                    msg=f"Spread {spread:.3f} is {spread/avg_spread:.1f}x rolling avg {avg_spread:.3f}",
                    ts=ob.ts,
                    details={"spread": spread, "avg_spread": avg_spread,
                             "multiplier": spread / avg_spread},
                ))

        # 4. Depth drop vs rolling average
        if len(buf) >= 5:
            avg_depth = sum(
                (compute_side_microstructure(s, side="yes", size=1).depth_yes_at_best +
                 compute_side_microstructure(s, side="yes", size=1).depth_no_at_best)
                for s in buf
            ) / len(buf)
            if avg_depth > 0 and depth < avg_depth * self.drop_mult:
                alerts.append(LiquidityAlert(
                    market_id=ob.ticker,
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
            bids = [s.best_yes_bid for s in recent if s.best_yes_bid is not None]
            if len(bids) >= 2:
                alternations = sum(
                    1 for i in range(1, len(bids)) if bids[i] != bids[i - 1]
                )
                if alternations / (len(bids) - 1) >= self.flicker_threshold:
                    alerts.append(LiquidityAlert(
                        market_id=ob.ticker,
                        kind="flickering",
                        severity="warning",
                        msg=(
                            f"Bid flickering: {alternations}/{len(bids) - 1} "
                            f"ticks changed ({alternations / (len(bids) - 1):.0%})"
                        ),
                        ts=ob.ts,
                        details={"alternations": alternations, "window": len(bids),
                                 "ratio": alternations / (len(bids) - 1)},
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
        and converts them to canonical OrderbookSnapshot for processing.
        
        Note: The preferred path is to subscribe to KalshiMarketStateStore
        directly via the market state update callbacks. This method is
        maintained for backward compatibility with the event bus.
        """
        from core.event_bus import event_stream

        async def _handler(event: Dict[str, Any]) -> None:
            if event.get("type") != "kalshi:price_update":
                return
            payload = event.get("payload", {})
            
            # Extract YES/NO bid data from event
            yes_bid_cents = payload.get("yes_bid_cents")
            no_bid_cents = payload.get("no_bid_cents")
            yes_bid_size = payload.get("yes_bid_size", 0)
            no_bid_size = payload.get("no_bid_size", 0)
            
            if yes_bid_cents is None or no_bid_cents is None:
                return
            
            # Build canonical OrderbookSnapshot from event data
            yes_levels = (OrderbookLevel(price_cents=yes_bid_cents, size=yes_bid_size),)
            no_levels = (OrderbookLevel(price_cents=no_bid_cents, size=no_bid_size),)
            
            ob = OrderbookSnapshot(
                ticker=payload.get("market_id", ""),
                yes_bids=yes_levels,
                no_bids=no_levels,
                seq=payload.get("seq", 0),
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
        """Current health snapshot for a single market.
        
        Uses canonical OrderbookSnapshot from unified_market_state.
        """
        buf = self._buffers.get(market_id)
        if not buf:
            return {"market_id": market_id, "status": "no_data"}

        latest = buf[-1]
        
        # Convert spread_cents to probability units
        spread_cents = latest.spread_cents if latest.spread_cents else 0
        spread = cents_to_dollars(spread_cents) if spread_cents else 0.0
        
        # Use microstructure utility for depth calculation
        micro = compute_side_microstructure(latest, side="yes", size=1, depth_window_cents=10)
        depth = micro.depth_yes_at_best + micro.depth_no_at_best
        
        # Calculate rolling averages
        avg_spread_cents = sum(
            s.spread_cents if s.spread_cents else 0 for s in buf
        ) / len(buf) if buf else 0
        avg_spread = cents_to_dollars(avg_spread_cents) if avg_spread_cents else 0.0
        
        avg_depth = sum(
            (compute_side_microstructure(s, side="yes", size=1).depth_yes_at_best +
             compute_side_microstructure(s, side="yes", size=1).depth_no_at_best)
            for s in buf
        ) / len(buf) if buf else 0

        status = "healthy"
        if spread > self.max_spread:
            status = "degraded"
        if depth < self.min_depth:
            status = "thin"
        if spread > self.max_spread and depth < self.min_depth:
            status = "critical"

        return {
            "market_id": market_id,
            "status": status,
            "spread": spread,
            "depth": depth,
            "avg_spread": avg_spread,
            "avg_depth": avg_depth,
            "mid": cents_to_dollars(latest.mid_cents) if latest.mid_cents else 0.0,
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
