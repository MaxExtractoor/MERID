"""§2 Position Reconciliation — compares MERID internal state vs venue reality.

Fetches positions from each venue adapter and compares against
the paper trading engine's internal positions. Reports discrepancies.

Usage:
    from merid.reconciliation import reconcile_all_venues, reconcile_venue
    discrepancies = reconcile_all_venues()

    # Gate execution on clean reconciliation
    from merid.reconciliation import has_critical_discrepancies
    if has_critical_discrepancies():
        raise RuntimeError("Cannot execute: critical reconciliation discrepancies")

    # Force-align paper engine to venue truth
    from merid.reconciliation import force_align_from_venue
    force_align_from_venue("alpaca")
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.reconciliation")

# Persist last reconciliation report for debugging
_REPORT_PATH = Path("data/reconciliation_report.json")

# Module-level cache of last reconciliation result — protected by _recon_lock
_recon_lock = threading.Lock()
_last_discrepancies: List["PositionDiscrepancy"] = []
_reconciliation_has_run: bool = False
_last_reconciliation_ts: float = 0.0


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


def reconcile_venue(venue_name: str) -> List[PositionDiscrepancy]:
    """Reconcile MERID positions against a single venue.

    Returns list of discrepancies found. Logs a detailed diff for each.
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

    # Build lookup: symbol -> data
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
    all_symbols = sorted(set(list(venue_map.keys()) + list(merid_map.keys())))
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

    # Log detailed diff for each discrepancy
    if discrepancies:
        n_crit = sum(1 for d in discrepancies if d.severity == "critical")
        n_warn = sum(1 for d in discrepancies if d.severity == "warning")
        logger.warning(
            f"Reconciliation {venue_name}: {len(discrepancies)} discrepancies "
            f"({n_crit} critical, {n_warn} warning)"
        )
        for d in discrepancies:
            logger.warning(
                f"  [{d.severity.upper()}] {d.symbol}: "
                f"merid_qty={d.merid_qty:.4f} venue_qty={d.venue_qty:.4f} "
                f"delta_qty={d.delta_qty:+.4f} | "
                f"merid_price={d.merid_entry_price:.2f} venue_price={d.venue_entry_price:.2f} "
                f"delta_price={d.delta_price:+.2f} | "
                f"{d.reason}"
            )
    else:
        logger.info(f"Reconciliation {venue_name}: all positions match")

    return discrepancies


def reconcile_all_venues(venues: Optional[List[str]] = None) -> List[PositionDiscrepancy]:
    """Reconcile across all configured venues (driven by paper_config matrix)."""
    global _last_discrepancies, _reconciliation_has_run, _last_reconciliation_ts
    if venues is None:
        try:
            from merid.paper_config import get_paper_config
            venues = get_paper_config().reconciliation_venues()
        except ImportError:
            venues = ["alpaca"]
        if not venues:
            venues = ["alpaca"]
    all_discrepancies: List[PositionDiscrepancy] = []
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

    Used as a hard gate before enabling execution.
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


def get_last_discrepancies() -> List[PositionDiscrepancy]:
    """Return the cached result of the most recent reconciliation."""
    with _recon_lock:
        return list(_last_discrepancies)


def force_align_from_venue(venue_name: str, user_id: str = "operator") -> Dict[str, Any]:
    """Import venue positions as ground truth and overwrite paper engine state.

    This is a destructive operation: it replaces the paper engine's positions
    with whatever the venue reports. Use when reconciliation shows critical
    discrepancies and you trust the venue as the source of truth.

    Returns a summary of what was aligned.
    """
    try:
        from trading.adapters.registry import get_adapter
        adapter = get_adapter(venue_name)
        if not adapter:
            return {"error": f"No adapter for venue {venue_name}"}
    except Exception as e:
        return {"error": f"Failed to get adapter: {e}"}

    try:
        venue_positions = adapter.get_positions()
    except Exception as e:
        return {"error": f"Failed to fetch positions: {e}"}

    try:
        venue_balances = adapter.get_balances()
    except Exception as e:
        venue_balances = []

    try:
        from trading.paper_trading import (
            get_paper_engine, PaperPosition, _save_paper_state,
        )
        engine = get_paper_engine()
    except Exception as e:
        return {"error": f"Paper engine unavailable: {e}"}

    portfolio = engine.get_portfolio(user_id)

    # Record what we're removing
    removed = list(portfolio.positions.keys())
    portfolio.positions.clear()
    logger.info(f"Cleared {len(removed)} paper positions: {removed}")

    # Import venue positions as PaperPosition objects
    aligned_positions = []
    for vp in venue_positions:
        side = "long" if vp.quantity > 0 else "short"
        size_usd = abs(vp.quantity * vp.entry_price)
        pos_key = f"{vp.symbol}_{side}_perp"
        paper_pos = PaperPosition(
            position_id=f"aligned_{venue_name}_{int(time.time())}_{vp.symbol}",
            user_id=user_id,
            asset=vp.symbol,
            side=side,
            size_usd=size_usd,
            entry_price=vp.entry_price,
            current_price=vp.mark_price or vp.entry_price,
            leverage=1,
            unrealized_pnl=vp.unrealized_pnl or 0.0,
            realized_pnl=0.0,
            opened_at=time.time(),
            market_type="perp",
        )
        portfolio.positions[pos_key] = paper_pos
        aligned_positions.append({
            "symbol": vp.symbol,
            "quantity": vp.quantity,
            "entry_price": vp.entry_price,
            "mark_price": vp.mark_price,
            "unrealized_pnl": vp.unrealized_pnl,
            "pos_key": pos_key,
        })
        logger.info(
            f"  Imported {vp.symbol}: qty={vp.quantity} entry={vp.entry_price} "
            f"mark={vp.mark_price} pnl={vp.unrealized_pnl}"
        )

    # Align cash if available
    cash_aligned = None
    for bal in venue_balances:
        if hasattr(bal, "asset") and bal.asset == "USD":
            old_cash = portfolio.current_balance
            portfolio.current_balance = bal.available
            cash_aligned = {"old": old_cash, "new": bal.available}
            logger.info(f"Force-aligned cash: {old_cash:.2f} -> {bal.available:.2f}")
            break

    # Persist to disk
    _save_paper_state(engine)

    result = {
        "venue": venue_name,
        "positions_removed": removed,
        "positions_aligned": len(aligned_positions),
        "positions": aligned_positions,
        "cash_aligned": cash_aligned,
    }
    logger.info(f"Force alignment complete: {json.dumps(result, default=str)}")
    return result


def dump_reconciliation_report() -> str:
    """Return a human-readable reconciliation report from the last run."""
    with _recon_lock:
        snapshot = list(_last_discrepancies)

    if not snapshot:
        return "No discrepancies found (or reconciliation has not run yet)."

    lines = ["RECONCILIATION REPORT", "=" * 60]
    n_crit = sum(1 for d in snapshot if d.severity == "critical")
    n_warn = sum(1 for d in snapshot if d.severity == "warning")
    n_info = sum(1 for d in snapshot if d.severity == "info")
    lines.append(f"Total: {len(snapshot)} discrepancies ({n_crit} critical, {n_warn} warning, {n_info} info)")
    lines.append(f"Execution gate: {'BLOCKED' if n_crit > 0 else 'CLEAR'}")
    lines.append("")

    for d in snapshot:
        tag = d.severity.upper().ljust(8)
        lines.append(f"[{tag}] {d.venue}:{d.symbol}")
        lines.append(f"  Quantity:    MERID={d.merid_qty:.4f}  Venue={d.venue_qty:.4f}  Delta={d.delta_qty:+.4f}")
        lines.append(f"  Entry Price: MERID={d.merid_entry_price:.2f}  Venue={d.venue_entry_price:.2f}  Delta={d.delta_price:+.2f}")
        lines.append(f"  Reason: {d.reason}")
        lines.append("")

    return "\n".join(lines)


def _persist_report(discrepancies: List[PositionDiscrepancy]) -> None:
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
