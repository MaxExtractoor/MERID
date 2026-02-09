"""§2 Position Reconciliation — compares MERID internal state vs venue reality.

Fetches positions from each venue adapter and compares against
the paper trading engine's internal positions. Reports discrepancies.

Usage:
    from merid.reconciliation import reconcile_all_venues, reconcile_venue
    discrepancies = reconcile_all_venues()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.reconciliation")


@dataclass
class PositionDiscrepancy:
    """A mismatch between MERID's internal state and a venue's reported position."""
    venue: str
    symbol: str
    merid_qty: float
    venue_qty: float
    merid_entry_price: float
    venue_entry_price: float
    delta_qty: float = 0.0
    delta_pnl: float = 0.0
    severity: str = "info"        # info, warning, critical
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        self.delta_qty = self.venue_qty - self.merid_qty
        if abs(self.delta_qty) > 0.01:
            self.severity = "warning"
        if abs(self.delta_qty) > 1.0:
            self.severity = "critical"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "merid_qty": self.merid_qty,
            "venue_qty": self.venue_qty,
            "delta_qty": round(self.delta_qty, 6),
            "merid_entry_price": self.merid_entry_price,
            "venue_entry_price": self.venue_entry_price,
            "severity": self.severity,
            "timestamp": self.timestamp,
        }


def reconcile_venue(venue_name: str) -> List[PositionDiscrepancy]:
    """Reconcile MERID positions against a single venue.

    Returns list of discrepancies found.
    """
    discrepancies: List[PositionDiscrepancy] = []

    try:
        from trading.adapters.registry import get_adapter
        adapter = get_adapter(venue_name)
        if not adapter:
            logger.warning(f"No adapter for venue {venue_name}")
            return discrepancies
    except Exception as e:
        logger.warning(f"Failed to get adapter for {venue_name}: {e}")
        return discrepancies

    # Get venue positions
    try:
        venue_positions = adapter.get_positions()
    except Exception as e:
        logger.error(f"Failed to fetch positions from {venue_name}: {e}")
        return discrepancies

    # Get MERID internal positions (from paper trading engine)
    merid_positions = _get_merid_positions()

    # Build lookup: symbol → qty
    venue_map: Dict[str, Any] = {}
    for vp in venue_positions:
        venue_map[vp.symbol] = {
            "qty": vp.quantity,
            "entry_price": vp.entry_price,
            "mark_price": vp.mark_price,
            "pnl": vp.unrealized_pnl,
        }

    merid_map: Dict[str, Any] = {}
    for mp in merid_positions:
        sym = mp.get("symbol", "")
        merid_map[sym] = {
            "qty": mp.get("quantity", 0.0),
            "entry_price": mp.get("entry_price", 0.0),
        }

    # Compare: check every venue position against MERID
    all_symbols = set(list(venue_map.keys()) + list(merid_map.keys()))
    for symbol in all_symbols:
        v = venue_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})
        m = merid_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})

        if abs(v["qty"] - m["qty"]) > 0.001 or symbol not in venue_map or symbol not in merid_map:
            disc = PositionDiscrepancy(
                venue=venue_name,
                symbol=symbol,
                merid_qty=m["qty"],
                venue_qty=v["qty"],
                merid_entry_price=m["entry_price"],
                venue_entry_price=v["entry_price"],
            )
            discrepancies.append(disc)

    if discrepancies:
        logger.warning(
            f"Reconciliation {venue_name}: {len(discrepancies)} discrepancies "
            f"({sum(1 for d in discrepancies if d.severity == 'critical')} critical)"
        )
    else:
        logger.info(f"Reconciliation {venue_name}: all positions match")

    return discrepancies


def reconcile_all_venues() -> List[PositionDiscrepancy]:
    """Reconcile across all configured venues."""
    venues = ["alpaca"]  # Start with Alpaca paper; extend as adapters are added
    all_discrepancies: List[PositionDiscrepancy] = []
    for venue in venues:
        all_discrepancies.extend(reconcile_venue(venue))
    return all_discrepancies


def _get_merid_positions() -> List[Dict[str, Any]]:
    """Get MERID's internal position state from the paper trading engine."""
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        positions = engine.get_positions()
        result = []
        for pos in positions:
            if isinstance(pos, dict):
                result.append(pos)
            else:
                result.append({
                    "symbol": getattr(pos, "symbol", ""),
                    "quantity": float(getattr(pos, "quantity", 0)),
                    "entry_price": float(getattr(pos, "avg_entry_price", 0)),
                })
        return result
    except Exception as e:
        logger.warning(f"Paper engine positions unavailable: {e}")
        return []
