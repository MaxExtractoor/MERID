"""Venue position reconciliation — moved from shadowed merid/reconciliation.py.

Compares MERID internal state (paper engine) vs venue adapter positions.
The original merid/reconciliation.py file is shadowed by the merid/reconciliation/
package, so this module lives inside the package to be importable.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.reconciliation.venue")

# Persist last reconciliation report for debugging
_REPORT_PATH = Path("data/reconciliation_report.json")

# Module-level cache of last reconciliation result — protected by _recon_lock
_recon_lock = threading.Lock()
_last_discrepancies: List["VenuePositionDiscrepancy"] = []
_reconciliation_has_run: bool = False
_last_reconciliation_ts: float = 0.0


@dataclass
class VenuePositionDiscrepancy:
    """A mismatch between MERID's internal state and a venue's reported position."""
    venue: str
    symbol: str
    merid_qty: float
    venue_qty: float
    merid_entry_price: float
    venue_entry_price: float
    delta_qty: float = 0.0
    delta_price: float = 0.0
    delta_pnl: float = 0.0
    severity: str = "info"        # info, warning, critical
    reason: str = ""              # human-readable explanation
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        self.delta_qty = self.venue_qty - self.merid_qty
        self.delta_price = self.venue_entry_price - self.merid_entry_price

        # Classify severity
        reasons = []
        if abs(self.delta_qty) > 1.0:
            self.severity = "critical"
            reasons.append(f"qty delta {self.delta_qty:+.4f} exceeds 1.0")
        elif abs(self.delta_qty) > 0.01:
            self.severity = "warning"
            reasons.append(f"qty delta {self.delta_qty:+.4f} exceeds 0.01")

        if self.merid_qty == 0.0 and self.venue_qty != 0.0:
            self.severity = "critical"
            reasons.append(f"venue has position ({self.venue_qty}), MERID has none")
        elif self.venue_qty == 0.0 and self.merid_qty != 0.0:
            self.severity = "critical"
            reasons.append(f"MERID has position ({self.merid_qty}), venue has none")

        if abs(self.delta_price) > 0.01 and self.merid_entry_price > 0:
            pct = abs(self.delta_price / self.merid_entry_price) * 100
            if pct > 5.0:
                if self.severity != "critical":
                    self.severity = "warning"
                reasons.append(f"entry price delta {pct:.1f}%")

        self.reason = "; ".join(reasons) if reasons else "minor drift"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "merid_qty": self.merid_qty,
            "venue_qty": self.venue_qty,
            "delta_qty": round(self.delta_qty, 6),
            "merid_entry_price": self.merid_entry_price,
            "venue_entry_price": self.venue_entry_price,
            "delta_price": round(self.delta_price, 4),
            "severity": self.severity,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


def reconcile_venue(venue_name: str) -> List[VenuePositionDiscrepancy]:
    """Reconcile MERID positions against a single venue."""
    discrepancies: List[VenuePositionDiscrepancy] = []

    try:
        from trading.adapters.registry import get_adapter
        adapter = get_adapter(venue_name)
        if not adapter:
            logger.warning(f"No adapter for venue {venue_name}")
            return discrepancies
    except Exception as e:
        logger.warning(f"Failed to get adapter for {venue_name}: {e}")
        return discrepancies

    try:
        venue_positions = adapter.get_positions()
    except Exception as e:
        logger.error(f"Failed to fetch positions from {venue_name}: {e}")
        return discrepancies

    merid_positions = _get_merid_positions()

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

    all_symbols = sorted(set(list(venue_map.keys()) + list(merid_map.keys())))
    for symbol in all_symbols:
        v = venue_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})
        m = merid_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})

        if abs(v["qty"] - m["qty"]) > 0.001 or symbol not in venue_map or symbol not in merid_map:
            disc = VenuePositionDiscrepancy(
                venue=venue_name,
                symbol=symbol,
                merid_qty=m["qty"],
                venue_qty=v["qty"],
                merid_entry_price=m["entry_price"],
                venue_entry_price=v["entry_price"],
            )
            discrepancies.append(disc)

    if discrepancies:
        n_crit = sum(1 for d in discrepancies if d.severity == "critical")
        n_warn = sum(1 for d in discrepancies if d.severity == "warning")
        logger.warning(
            f"Reconciliation {venue_name}: {len(discrepancies)} discrepancies "
            f"({n_crit} critical, {n_warn} warning)"
        )
    else:
        logger.info(f"Reconciliation {venue_name}: all positions match")

    return discrepancies


def reconcile_all_venues(venues: Optional[List[str]] = None) -> List[VenuePositionDiscrepancy]:
    """Reconcile across all configured venues."""
    global _last_discrepancies, _reconciliation_has_run, _last_reconciliation_ts
    if venues is None:
        try:
            from merid.paper_config import get_paper_config
            venues = get_paper_config().reconciliation_venues()
        except ImportError:
            venues = ["alpaca"]
        if not venues:
            venues = ["alpaca"]
    all_discrepancies: List[VenuePositionDiscrepancy] = []
    for venue in venues:
        all_discrepancies.extend(reconcile_venue(venue))
    with _recon_lock:
        _last_discrepancies = all_discrepancies
        _reconciliation_has_run = True
        _last_reconciliation_ts = time.time()
    _persist_report(all_discrepancies)
    return all_discrepancies


def has_critical_discrepancies() -> bool:
    """Check if the last reconciliation found any critical discrepancies.

    Returns True (fail-closed) if no reconciliation has ever completed.
    """
    with _recon_lock:
        if not _reconciliation_has_run:
            return True
        return any(d.severity == "critical" for d in _last_discrepancies)


def get_last_reconciliation_ts() -> float:
    """Return the timestamp of the last completed reconciliation (0.0 if never run)."""
    with _recon_lock:
        return _last_reconciliation_ts


def get_last_discrepancies() -> List[VenuePositionDiscrepancy]:
    """Return the cached result of the most recent reconciliation."""
    with _recon_lock:
        return list(_last_discrepancies)


def _persist_report(discrepancies: List[VenuePositionDiscrepancy]) -> None:
    """Save reconciliation report to disk for post-mortem analysis."""
    try:
        _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "timestamp": time.time(),
            "count": len(discrepancies),
            "critical": sum(1 for d in discrepancies if d.severity == "critical"),
            "discrepancies": [d.to_dict() for d in discrepancies],
        }
        _REPORT_PATH.write_text(json.dumps(report, indent=2))
    except Exception as e:
        logger.debug(f"Failed to persist reconciliation report: {e}")


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
