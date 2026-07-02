"""
Order Lifecycle Tracker

Tracks the full lifecycle of orders from creation to fill/cancellation/expiration.
This provides visibility into execution quality, fill rates, and time-on-book metrics.

Key features:
- Order state tracking: created → submitted → filled/partial/cancelled/expired
- Per-asset and per-price-band breakdowns
- Time-on-book metrics for GTC orders
- Prometheus-compatible metrics
- Session-level fill statistics

This helps distinguish between risk-model rejections vs execution-quality issues.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict
import json
import time

logger = logging.getLogger(__name__)


class OrderState(Enum):
    """Order lifecycle states."""
    CREATED = "created"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FULLY_FILLED = "fully_filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class PriceBand(Enum):
    """Price band categories for analysis."""
    DEEP_OTM = "deep_otm"  # < 40c
    OTM = "otm"  # 40-47c
    NEAR_MONEY = "near_money"  # 48-52c
    ITM = "itm"  # 53-60c
    DEEP_ITM = "deep_itm"  # > 60c


@dataclass
class OrderEvent:
    """Single order lifecycle event."""
    timestamp: str
    order_id: str
    client_order_id: str
    state: OrderState
    price_cents: int
    count: int
    filled_count: int
    asset: str
    price_band: str
    side: str
    seconds_on_book: Optional[float] = None
    notes: Optional[str] = None


class OrderLifecycleTracker:
    """Tracks order lifecycle events and computes fill statistics."""

    def __init__(self):
        self._events: List[OrderEvent] = []
        self._order_states: Dict[str, OrderState] = {}
        self._order_start_times: Dict[str, float] = {}
        self._counters: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record_event(
        self,
        order_id: str,
        client_order_id: str,
        state: OrderState,
        price_cents: int,
        count: int,
        filled_count: int = 0,
        asset: str = "UNKNOWN",
        side: str = "UNKNOWN",
        notes: Optional[str] = None,
    ):
        """
        Record an order lifecycle event.

        Args:
            order_id: Kalshi order ID
            client_order_id: Client order ID (merid-*)
            state: Current order state
            price_cents: Order price in cents
            count: Total contract count
            filled_count: Number of contracts filled so far
            asset: Asset symbol (BTC, ETH, etc.)
            side: Order side (yes/no)
            notes: Optional notes about the event
        """
        # Determine price band
        price_band = self._classify_price_band(price_cents)

        # Calculate time on book for terminal states
        seconds_on_book = None
        if state in [OrderState.FULLY_FILLED, OrderState.CANCELLED, OrderState.EXPIRED]:
            if order_id in self._order_start_times:
                seconds_on_book = time.time() - self._order_start_times[order_id]

        # Create event
        event = OrderEvent(
            timestamp=datetime.utcnow().isoformat(),
            order_id=order_id,
            client_order_id=client_order_id,
            state=state,
            price_cents=price_cents,
            count=count,
            filled_count=filled_count,
            asset=asset,
            price_band=price_band,
            side=side,
            seconds_on_book=seconds_on_book,
            notes=notes,
        )

        # Store event
        self._events.append(event)
        self._order_states[order_id] = state

        # Track start time for submitted orders
        if state == OrderState.SUBMITTED and order_id not in self._order_start_times:
            self._order_start_times[order_id] = time.time()

        # Update counters
        self._counters["total"][state.value] += 1
        self._counters[asset][state.value] += 1
        self._counters[f"band_{price_band}"][state.value] += 1

        # Log event
        logger.info(
            "[ORDER-LIFECYCLE] order_id=%s | client_id=%s | state=%s | "
            "asset=%s | band=%s | price=%dc | count=%d | filled=%d | on_book=%.2fs | notes=%s",
            order_id,
            client_order_id,
            state.value,
            asset,
            price_band,
            price_cents,
            count,
            filled_count,
            seconds_on_book or 0.0,
            notes or "",
        )

    def get_fill_statistics(self) -> Dict:
        """
        Get comprehensive fill statistics.

        Returns:
            Dict with fill statistics by asset and price band
        """
        total_submitted = self._counters["total"].get("submitted", 0)
        total_filled = self._counters["total"].get("fully_filled", 0)
        total_partial = self._counters["total"].get("partially_filled", 0)
        total_cancelled = self._counters["total"].get("cancelled", 0)
        total_expired = self._counters["total"].get("expired", 0)
        total_rejected = self._counters["total"].get("rejected", 0)

        # Calculate fill rate (fully filled / submitted)
        fill_rate = (total_filled / total_submitted * 100) if total_submitted > 0 else 0.0

        # Calculate average time on book for filled orders
        filled_events = [e for e in self._events if e.state == OrderState.FULLY_FILLED and e.seconds_on_book is not None]
        avg_time_on_book = sum(e.seconds_on_book for e in filled_events) / len(filled_events) if filled_events else 0.0

        # Per-asset breakdown
        asset_breakdown = {}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if asset in self._counters:
                asset_submitted = self._counters[asset].get("submitted", 0)
                asset_filled = self._counters[asset].get("fully_filled", 0)
                asset_fill_rate = (asset_filled / asset_submitted * 100) if asset_submitted > 0 else 0.0

                asset_breakdown[asset] = {
                    "submitted": asset_submitted,
                    "filled": asset_filled,
                    "partial": self._counters[asset].get("partially_filled", 0),
                    "cancelled": self._counters[asset].get("cancelled", 0),
                    "expired": self._counters[asset].get("expired", 0),
                    "fill_rate_pct": asset_fill_rate,
                }

        # Per-price-band breakdown
        band_breakdown = {}
        for band in PriceBand:
            band_key = f"band_{band.value}"
            if band_key in self._counters:
                band_submitted = self._counters[band_key].get("submitted", 0)
                band_filled = self._counters[band_key].get("fully_filled", 0)
                band_fill_rate = (band_filled / band_submitted * 100) if band_submitted > 0 else 0.0

                band_breakdown[band.value] = {
                    "submitted": band_submitted,
                    "filled": band_filled,
                    "partial": self._counters[band_key].get("partially_filled", 0),
                    "cancelled": self._counters[band_key].get("cancelled", 0),
                    "expired": self._counters[band_key].get("expired", 0),
                    "fill_rate_pct": band_fill_rate,
                }

        return {
            "total": {
                "submitted": total_submitted,
                "filled": total_filled,
                "partial": total_partial,
                "cancelled": total_cancelled,
                "expired": total_expired,
                "rejected": total_rejected,
                "fill_rate_pct": fill_rate,
                "avg_time_on_book_seconds": avg_time_on_book,
            },
            "by_asset": asset_breakdown,
            "by_price_band": band_breakdown,
        }

    def get_recent_events(self, limit: int = 20) -> List[Dict]:
        """
        Get the most recent order events.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of event dicts
        """
        recent = self._events[-limit:] if self._events else []
        return [asdict(e) for e in recent]

    def reset(self):
        """Reset all tracking data."""
        self._events.clear()
        self._order_states.clear()
        self._order_start_times.clear()
        self._counters.clear()
        logger.info("[ORDER-LIFECYCLE] Reset all tracking data")

    def _classify_price_band(self, price_cents: int) -> str:
        """Classify price into band category."""
        if price_cents < 40:
            return PriceBand.DEEP_OTM.value
        elif price_cents < 48:
            return PriceBand.OTM.value
        elif price_cents <= 52:
            return PriceBand.NEAR_MONEY.value
        elif price_cents <= 60:
            return PriceBand.ITM.value
        else:
            return PriceBand.DEEP_ITM.value

    def _extract_asset(self, market_id: str) -> str:
        """Extract asset symbol from market ID."""
        if market_id.startswith("KX"):
            ticker = market_id.split("-")[0]
            if ticker.startswith("KX"):
                ticker = ticker[2:]
            import re
            ticker = re.sub(r'(15M|H1|D1|W1|1M|Y)$', '', ticker)
            return ticker
        return "UNKNOWN"


# Global singleton instance
_tracker: Optional[OrderLifecycleTracker] = None


def get_order_lifecycle_tracker() -> OrderLifecycleTracker:
    """Get the global order lifecycle tracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = OrderLifecycleTracker()
        logger.info("[ORDER-LIFECYCLE] Initialized global tracker")
    return _tracker


def record_order_event(
    order_id: str,
    client_order_id: str,
    state: OrderState,
    price_cents: int,
    count: int,
    filled_count: int = 0,
    asset: str = "UNKNOWN",
    side: str = "UNKNOWN",
    notes: Optional[str] = None,
):
    """
    Convenience function to record an order lifecycle event.

    This is the main entry point for recording order events
    from the order router and Kalshi client.
    """
    tracker = get_order_lifecycle_tracker()
    tracker.record_event(
        order_id=order_id,
        client_order_id=client_order_id,
        state=state,
        price_cents=price_cents,
        count=count,
        filled_count=filled_count,
        asset=asset,
        side=side,
        notes=notes,
    )


# Prometheus metrics (if prometheus_client is available)
try:
    from prometheus_client import Counter, Histogram, Gauge, REGISTRY

    # Helper to get or create metric safely
    def _get_or_create_counter(name, documentation, labels):
        """Get existing counter or create new one."""
        for collector in REGISTRY._collector_to_names:
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        return Counter(name, documentation, labels)

    def _get_or_create_histogram(name, documentation, labels, buckets):
        """Get existing histogram or create new one."""
        for collector in REGISTRY._collector_to_names:
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        return Histogram(name, documentation, labels, buckets=buckets)

    def _get_or_create_gauge(name, documentation, labels):
        """Get existing gauge or create new one."""
        for collector in REGISTRY._collector_to_names:
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        return Gauge(name, documentation, labels)

    # Order lifecycle counters
    orders_submitted_total = _get_or_create_counter(
        'merid_orders_submitted_total',
        'Total orders submitted to Kalshi',
        ['asset', 'price_band', 'side', 'execution_mode']
    )

    orders_filled_total = _get_or_create_counter(
        'merid_orders_filled_total',
        'Total orders fully filled',
        ['asset', 'price_band', 'side', 'execution_mode']
    )

    orders_partial_fill_total = _get_or_create_counter(
        'merid_orders_partial_fill_total',
        'Total orders partially filled',
        ['asset', 'price_band', 'side', 'execution_mode']
    )

    orders_cancelled_total = _get_or_create_counter(
        'merid_orders_cancelled_total',
        'Total orders cancelled',
        ['asset', 'price_band', 'side', 'execution_mode']
    )

    orders_expired_total = _get_or_create_counter(
        'merid_orders_expired_total',
        'Total orders expired (GTC timeout)',
        ['asset', 'price_band', 'side', 'execution_mode']
    )

    orders_rejected_total = _get_or_create_counter(
        'merid_orders_rejected_total',
        'Total orders rejected by Kalshi',
        ['asset', 'price_band', 'side', 'execution_mode']
    )

    # Dry-run specific counters
    dry_run_orders_total = _get_or_create_counter(
        'merid_dry_run_orders_total',
        'Total dry-run orders (simulated submission)',
        ['asset', 'price_band', 'side']
    )

    simulated_fills_total = _get_or_create_counter(
        'merid_simulated_fills_total',
        'Total simulated fills (dry-run mode with fill simulation)',
        ['asset', 'price_band', 'side']
    )

    # Time on book histogram
    order_time_on_book_seconds = _get_or_create_histogram(
        'merid_order_time_on_book_seconds',
        'Time orders spent on the book before fill/cancel/expire',
        ['asset', 'price_band', 'side', 'execution_mode'],
        buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600]
    )

    # P2 Task 8: Per-asset PnL and cycle tracking
    pnl_by_asset = _get_or_create_gauge(
        'merid_pnl_by_asset',
        'Realized PnL by asset in USD',
        ['asset']
    )

    cycles_profitable_total = _get_or_create_counter(
        'merid_cycles_profitable_total',
        'Total profitable trading cycles by asset',
        ['asset']
    )

    cycles_unprofitable_total = _get_or_create_counter(
        'merid_cycles_unprofitable_total',
        'Total unprofitable trading cycles by asset',
        ['asset']
    )

    # P2 Task 9: Decision reason counters
    no_valid_contract_rejections_total = _get_or_create_counter(
        'merid_no_valid_contract_rejections_total',
        'Total rejections due to no valid contracts passing filters',
        ['asset']
    )

    PROMETHEUS_AVAILABLE = True
    logger.info("[ORDER-LIFECYCLE] Prometheus metrics initialized")
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("[ORDER-LIFECYCLE] prometheus_client not available - metrics disabled")


def update_prometheus_metrics(
    state: OrderState,
    asset: str,
    price_band: str,
    side: str,
    seconds_on_book: Optional[float] = None,
    execution_mode: str = "normal",
):
    """
    Update Prometheus metrics for an order event.

    Args:
        state: Order state
        asset: Asset symbol
        price_band: Price band category
        side: Order side
        seconds_on_book: Time on book (for terminal states)
        execution_mode: Execution mode (normal, dry_run, simulate)
    """
    if not PROMETHEUS_AVAILABLE:
        return

    if state == OrderState.SUBMITTED:
        orders_submitted_total.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).inc()
        if execution_mode in ("dry_run", "simulate"):
            dry_run_orders_total.labels(asset=asset, price_band=price_band, side=side).inc()
    elif state == OrderState.FULLY_FILLED:
        orders_filled_total.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).inc()
        if seconds_on_book is not None:
            order_time_on_book_seconds.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).observe(seconds_on_book)
        if execution_mode == "simulate":
            simulated_fills_total.labels(asset=asset, price_band=price_band, side=side).inc()
    elif state == OrderState.PARTIALLY_FILLED:
        orders_partial_fill_total.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).inc()
    elif state == OrderState.CANCELLED:
        orders_cancelled_total.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).inc()
        if seconds_on_book is not None:
            order_time_on_book_seconds.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).observe(seconds_on_book)
    elif state == OrderState.EXPIRED:
        orders_expired_total.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).inc()
        if seconds_on_book is not None:
            order_time_on_book_seconds.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).observe(seconds_on_book)
    elif state == OrderState.REJECTED:
        orders_rejected_total.labels(asset=asset, price_band=price_band, side=side, execution_mode=execution_mode).inc()


def update_pnl_metrics(asset: str, pnl_usd: float) -> None:
    """
    Update per-asset PnL gauge (P2 Task 8).

    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        pnl_usd: Realized PnL in USD
    """
    if not PROMETHEUS_AVAILABLE:
        return
    pnl_by_asset.labels(asset=asset).set(pnl_usd)


def record_cycle_result(asset: str, profitable: bool) -> None:
    """
    Record cycle profitability (P2 Task 8).

    Args:
        asset: Asset symbol
        profitable: True if cycle was profitable, False otherwise
    """
    if not PROMETHEUS_AVAILABLE:
        return
    if profitable:
        cycles_profitable_total.labels(asset=asset).inc()
    else:
        cycles_unprofitable_total.labels(asset=asset).inc()


def record_no_valid_contract_rejection(asset: str) -> None:
    """
    Record rejection due to no valid contracts passing filters (P2 Task 9).

    Args:
        asset: Asset symbol
    """
    if not PROMETHEUS_AVAILABLE:
        return
    no_valid_contract_rejections_total.labels(asset=asset).inc()
