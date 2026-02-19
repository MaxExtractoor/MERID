"""Kalshi Trade Analytics — VWAP, large trade detection, and trade-level utilities.

Operates on lists of trade dicts as returned by ``GET /trades`` pages.

Usage::

    from merid.event_venues.kalshi.trade_analytics import (
        compute_vwap, detect_large_trades,
    )

    vwap = compute_vwap(trades)
    whales = detect_large_trades(trades, min_contracts=500)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.trade_analytics")


def compute_vwap(trades: List[Dict[str, Any]]) -> Optional[float]:
    """Compute volume-weighted average price from a list of trades.

    Args:
        trades: List of dicts with ``price`` (cents) and ``count`` keys.

    Returns:
        VWAP in cents, or None if no volume.
    """
    notional = 0
    total_qty = 0
    for tr in trades:
        px = tr.get("price", 0)
        qty = tr.get("count", 0)
        notional += px * qty
        total_qty += qty
    if total_qty == 0:
        return None
    return notional / total_qty


def detect_large_trades(
    trades: List[Dict[str, Any]],
    *,
    min_contracts: int = 500,
    min_notional_usd: float = 1000.0,
) -> List[Dict[str, Any]]:
    """Flag trades exceeding contract count or notional thresholds.

    Args:
        trades: List of trade dicts with ``price`` (cents) and ``count``.
        min_contracts: Minimum contract count to flag.
        min_notional_usd: Minimum notional (count × price/100) to flag.

    Returns:
        List of flagged trades with ``notional_usd`` added.
    """
    large: List[Dict[str, Any]] = []
    for tr in trades:
        qty = tr.get("count", 0)
        px_cents = tr.get("price", 0)
        notional = qty * (px_cents / 100.0)
        if qty >= min_contracts or notional >= min_notional_usd:
            flagged = dict(tr)
            flagged["notional_usd"] = round(notional, 2)
            large.append(flagged)
    return large
