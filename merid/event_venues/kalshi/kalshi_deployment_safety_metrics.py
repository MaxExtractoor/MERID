"""Kalshi Deployment Safety Metrics — Prometheus counters for safety enforcement.

Tracks:
- Deep OTM/ITM order rejections
- Deep OTM/ITM fills (runtime monitoring)
- Model probability distance violations
- Emergency override usage

Usage::

    from merid.event_venues.kalshi.kalshi_deployment_safety_metrics import (
        inc_deep_otm_order_rejected,
        inc_deep_itm_order_rejected,
        inc_deep_otm_fill,
        inc_deep_itm_fill,
        inc_model_prob_distance_violation,
        inc_emergency_override,
    )

    # Track a deep OTM order rejection
    inc_deep_otm_order_rejected(ticker="KXBTCD-25JUN-T100000", agent_id="trading_agent")

    # Track a deep OTM fill
    inc_deep_otm_fill(ticker="KXBTCD-25JUN-T100000", source="websocket")
"""

from __future__ import annotations

from typing import Optional

try:
    from prometheus_client import Counter, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = None
    Histogram = None

from merid.event_venues.kalshi.invariants import get_kalshi_metrics_labels

# ============================================================================
# Metrics Definitions
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # Deep OTM/ITM order rejections
    KALSHI_DEEP_OTM_ORDER_REJECTED_TOTAL = Counter(
        "kalshi_deep_otm_order_rejected_total",
        "Total count of orders rejected due to deep OTM price (< 5¢)",
        ["kalshi_env", "kalshi_host", "ticker", "agent_id", "price_cents"]
    )
    
    KALSHI_DEEP_ITM_ORDER_REJECTED_TOTAL = Counter(
        "kalshi_deep_itm_order_rejected_total",
        "Total count of orders rejected due to deep ITM price (> 95¢)",
        ["kalshi_env", "kalshi_host", "ticker", "agent_id", "price_cents"]
    )
    
    # Deep OTM/ITM fills (runtime monitoring)
    KALSHI_DEEP_OTM_FILL_TOTAL = Counter(
        "kalshi_deep_otm_fill_total",
        "Total count of fills at deep OTM prices (< 5¢)",
        ["kalshi_env", "kalshi_host", "ticker", "source", "price_cents"]
    )
    
    KALSHI_DEEP_ITM_FILL_TOTAL = Counter(
        "kalshi_deep_itm_fill_total",
        "Total count of fills at deep ITM prices (> 95¢)",
        ["kalshi_env", "kalshi_host", "ticker", "source", "price_cents"]
    )
    
    # Model probability distance violations
    KALSHI_MODEL_PROB_DISTANCE_HISTOGRAM = Histogram(
        "kalshi_model_prob_distance_histogram",
        "Histogram of abs(model_prob - price_cents/100) for all orders",
        ["kalshi_env", "kalshi_host"],
        buckets=(0.01, 0.02, 0.03, 0.05, 0.10, 0.20, 0.50, 1.0)
    )
    
    KALSHI_MODEL_PROB_DISTANCE_VIOLATION_TOTAL = Counter(
        "kalshi_model_prob_distance_violation_total",
        "Total count of orders with model probability distance > threshold",
        ["kalshi_env", "kalshi_host", "ticker", "agent_id", "distance"]
    )
    
    # Emergency override usage
    KALSHI_EMERGENCY_OVERRIDE_TOTAL = Counter(
        "kalshi_emergency_override_total",
        "Total count of emergency overrides for deployment safety checks",
        ["kalshi_env", "kalshi_host", "check_name", "ticket_id"]
    )
else:
    # Fallback no-op metrics when prometheus_client is not available
    KALSHI_DEEP_OTM_ORDER_REJECTED_TOTAL = None
    KALSHI_DEEP_ITM_ORDER_REJECTED_TOTAL = None
    KALSHI_DEEP_OTM_FILL_TOTAL = None
    KALSHI_DEEP_ITM_FILL_TOTAL = None
    KALSHI_MODEL_PROB_DISTANCE_HISTOGRAM = None
    KALSHI_MODEL_PROB_DISTANCE_VIOLATION_TOTAL = None
    KALSHI_EMERGENCY_OVERRIDE = None


# ============================================================================
# Metric Increment Functions
# ============================================================================

def _get_labels() -> dict:
    """Get base Prometheus labels for Kalshi metrics."""
    return get_kalshi_metrics_labels()


def inc_deep_otm_order_rejected(
    ticker: str,
    agent_id: str,
    price_cents: int,
) -> None:
    """Increment deep OTM order rejection counter.
    
    Args:
        ticker: Market ticker
        agent_id: Agent ID that submitted the order
        price_cents: Price in cents
    """
    if not PROMETHEUS_AVAILABLE or KALSHI_DEEP_OTM_ORDER_REJECTED_TOTAL is None:
        return
    
    labels = _get_labels()
    labels.update({
        "ticker": ticker,
        "agent_id": agent_id,
        "price_cents": str(price_cents),
    })
    
    KALSHI_DEEP_OTM_ORDER_REJECTED_TOTAL.labels(**labels).inc()


def inc_deep_itm_order_rejected(
    ticker: str,
    agent_id: str,
    price_cents: int,
) -> None:
    """Increment deep ITM order rejection counter.
    
    Args:
        ticker: Market ticker
        agent_id: Agent ID that submitted the order
        price_cents: Price in cents
    """
    if not PROMETHEUS_AVAILABLE or KALSHI_DEEP_ITM_ORDER_REJECTED_TOTAL is None:
        return
    
    labels = _get_labels()
    labels.update({
        "ticker": ticker,
        "agent_id": agent_id,
        "price_cents": str(price_cents),
    })
    
    KALSHI_DEEP_ITM_ORDER_REJECTED_TOTAL.labels(**labels).inc()


def inc_deep_otm_fill(
    ticker: str,
    source: str,
    price_cents: int,
) -> None:
    """Increment deep OTM fill counter.
    
    Args:
        ticker: Market ticker
        source: Fill source (websocket or http_poller)
        price_cents: Price in cents
    """
    if not PROMETHEUS_AVAILABLE or KALSHI_DEEP_OTM_FILL_TOTAL is None:
        return
    
    labels = _get_labels()
    labels.update({
        "ticker": ticker,
        "source": source,
        "price_cents": str(price_cents),
    })
    
    KALSHI_DEEP_OTM_FILL_TOTAL.labels(**labels).inc()


def inc_deep_itm_fill(
    ticker: str,
    source: str,
    price_cents: int,
) -> None:
    """Increment deep ITM fill counter.
    
    Args:
        ticker: Market ticker
        source: Fill source (websocket or http_poller)
        price_cents: Price in cents
    """
    if not PROMETHEUS_AVAILABLE or KALSHI_DEEP_ITM_FILL_TOTAL is None:
        return
    
    labels = _get_labels()
    labels.update({
        "ticker": ticker,
        "source": source,
        "price_cents": str(price_cents),
    })
    
    KALSHI_DEEP_ITM_FILL_TOTAL.labels(**labels).inc()


def observe_model_prob_distance(
    distance: float,
) -> None:
    """Observe model probability distance in histogram.
    
    Args:
        distance: Absolute difference between model_prob and implied_prob
    """
    if not PROMETHEUS_AVAILABLE or KALSHI_MODEL_PROB_DISTANCE_HISTOGRAM is None:
        return
    
    labels = _get_labels()
    KALSHI_MODEL_PROB_DISTANCE_HISTOGRAM.labels(**labels).observe(distance)


def inc_model_prob_distance_violation(
    ticker: str,
    agent_id: str,
    distance: float,
) -> None:
    """Increment model probability distance violation counter.
    
    Args:
        ticker: Market ticker
        agent_id: Agent ID that submitted the order
        distance: Model probability distance
    """
    if not PROMETHEUS_AVAILABLE or KALSHI_MODEL_PROB_DISTANCE_VIOLATION_TOTAL is None:
        return
    
    labels = _get_labels()
    labels.update({
        "ticker": ticker,
        "agent_id": agent_id,
        "distance": f"{distance:.3f}",
    })
    
    KALSHI_MODEL_PROB_DISTANCE_VIOLATION_TOTAL.labels(**labels).inc()


def inc_emergency_override(
    check_name: str,
    ticket_id: Optional[str] = None,
) -> None:
    """Increment emergency override counter.
    
    Args:
        check_name: Name of the safety check that was overridden
        ticket_id: Ticket/incident reference for the override
    """
    if not PROMETHEUS_AVAILABLE or KALSHI_EMERGENCY_OVERRIDE_TOTAL is None:
        return
    
    labels = _get_labels()
    labels.update({
        "check_name": check_name,
        "ticket_id": ticket_id or "unknown",
    })
    
    KALSHI_EMERGENCY_OVERRIDE_TOTAL.labels(**labels).inc()
