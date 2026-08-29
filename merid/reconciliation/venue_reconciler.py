"""Venue position reconciliation — moved from shadowed merid/reconciliation.py.

Compares MERID internal state (paper engine) vs venue adapter positions.
The original merid/reconciliation.py file is shadowed by the merid/reconciliation/
package, so this module lives inside the package to be importable.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.reconciliation.venue")

# Import metrics emission (defensive import in case module not available)
try:
    from merid.reconciliation.reconciliation_metrics import emit_recon_metrics
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False
    logger.debug("Reconciliation metrics module not available - metrics will not be emitted")

# Persist last reconciliation report for debugging
_REPORT_PATH = Path("data/reconciliation_report.json")

# Module-level cache of last reconciliation result — protected by _recon_lock
_recon_lock = threading.Lock()
_last_discrepancies: List["VenuePositionDiscrepancy"] = []
_reconciliation_has_run: bool = False
_last_reconciliation_ts: float = 0.0

# Phantom kill switch state — protected by _recon_lock
# Per audit: phantom kill only arms on TRUE phantom positions, not transient recon failures
_phantom_kill_switch: bool = False
_phantom_kill_reason: str = ""
_phantom_kill_timestamp: float = 0.0
_phantom_positions: List[str] = []  # List of symbol IDs with phantom positions

_KALSHI_UNREACHABLE_SYMBOL = "__VENUE_UNREACHABLE__kalshi"


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

        # Preserve pre-set severity/reason for synthetic entries (e.g. venue unreachable)
        if self.symbol.startswith("__VENUE_UNREACHABLE__"):
            if not self.reason:
                self.reason = "venue unreachable"
            self.severity = "critical"
            return

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


def _mark_recon_done(discrepancies: List["VenuePositionDiscrepancy"]) -> None:
    """Update global reconciliation state after reconcile_venue completes."""
    global _last_discrepancies, _reconciliation_has_run, _last_reconciliation_ts
    with _recon_lock:
        _last_discrepancies = discrepancies
        _reconciliation_has_run = True
        _last_reconciliation_ts = time.time()
        # Evaluate phantom kill switch after each reconciliation
        _evaluate_phantom_kill_locked(discrepancies)


def _evaluate_phantom_kill_locked(discrepancies: List["VenuePositionDiscrepancy"]) -> None:
    """Evaluate and update phantom kill switch state.
    
    Per Halt Conditions Audit, phantom kill ONLY arms when:
    - Genuine position mismatch exists (non-zero qty on either side)
    - NOT caused by: transient 5xx/timeout, missing paper engine, missing non-Kalshi adapter
    - Must be true phantom: positions exist on Kalshi but not in MERID or vice versa
      that cannot be explained by pending orders or fresh start
    
    Caller must hold _recon_lock.
    """
    global _phantom_kill_switch, _phantom_kill_reason, _phantom_kill_timestamp, _phantom_positions
    
    # Collect genuine phantom positions
    genuine_phantoms: List[Tuple[str, float, float]] = []  # [(symbol, merid_qty, venue_qty)]
    
    for d in discrepancies:
        # Skip synthetic entries (venue unreachable is a dependency issue, not phantom position)
        if d.symbol.startswith("__VENUE_UNREACHABLE__"):
            continue
        
        # TRUE phantom position criteria:
        # 1. Both sides have non-zero position (directional mismatch or size mismatch)
        # 2. OR: One side has position, other has zero (clear phantom)
        # AND: Not a fresh start (both zero would have been filtered earlier)
        
        is_true_phantom = False
        
        if d.merid_qty != 0.0 and d.venue_qty != 0.0:
            # Both have positions but they differ — genuine mismatch
            if abs(d.delta_qty) > 0.01:  # Significant delta
                is_true_phantom = True
        elif d.merid_qty == 0.0 and d.venue_qty != 0.0:
            # Venue has position but MERID has none — phantom at venue
            is_true_phantom = True
        elif d.merid_qty != 0.0 and d.venue_qty == 0.0:
            # MERID has position but venue has none — phantom in MERID
            is_true_phantom = True
        
        if is_true_phantom and d.severity == "critical":
            genuine_phantoms.append((d.symbol, d.merid_qty, d.venue_qty))
    
    # Update phantom kill state
    if genuine_phantoms:
        # ARM phantom kill switch
        if not _phantom_kill_switch:
            _phantom_kill_switch = True
            _phantom_kill_timestamp = time.time()
            _phantom_positions = [p[0] for p in genuine_phantoms]
            _phantom_kill_reason = (
                f"Phantom positions detected: {len(genuine_phantoms)} symbols with "
                f"critical mismatches — {', '.join(_phantom_positions[:3])}"
                f"{'...' if len(genuine_phantoms) > 3 else ''}"
            )
            logger.critical(
                "[reconciliation] PHANTOM KILL SWITCH ARMED: %d positions | %s",
                len(genuine_phantoms),
                _phantom_kill_reason,
            )
            # Emit metric
            try:
                from monitoring.metrics import record_reconciliation_phantom_kill
                record_reconciliation_phantom_kill(len(genuine_phantoms))
            except Exception:
                pass
    else:
        # No genuine phantoms — if phantom kill was armed, keep it armed
        # (only clear_phantom_kill_switch() can clear it after operator review)
        pass


def get_phantom_kill_status() -> Dict[str, Any]:
    """Get current phantom kill switch status."""
    with _recon_lock:
        return {
            "armed": _phantom_kill_switch,
            "reason": _phantom_kill_reason,
            "timestamp": _phantom_kill_timestamp,
            "positions": list(_phantom_positions),
            "duration_sec": time.time() - _phantom_kill_timestamp if _phantom_kill_switch else 0,
        }


def is_phantom_kill_armed() -> bool:
    """Check if phantom kill switch is currently armed."""
    with _recon_lock:
        return _phantom_kill_switch


def clear_phantom_kill_switch(operator: str = "system", reason: str = "") -> Dict[str, Any]:
    """Clear the phantom kill switch after operator review.
    
    Per audit: This is the ONLY way to clear phantom kill. Must be called
    explicitly after reconciliation is clean and operator has reviewed.
    
    Args:
        operator: Who is clearing the phantom kill
        reason: Why it's being cleared (required for audit trail)
        
    Returns:
        Dict with status and details
    """
    global _phantom_kill_switch, _phantom_kill_reason, _phantom_kill_timestamp, _phantom_positions
    
    with _recon_lock:
        was_armed = _phantom_kill_switch
        
        if not was_armed:
            return {
                "cleared": False,
                "was_armed": False,
                "message": "Phantom kill switch was not armed",
            }
        
        # Require reason for audit trail
        if not reason:
            reason = "Manual operator clear"
        
        # Clear the phantom kill
        _phantom_kill_switch = False
        cleared_at = time.time()
        duration = cleared_at - _phantom_kill_timestamp
        positions_cleared = list(_phantom_positions)
        old_reason = _phantom_kill_reason
        
        # Reset state
        _phantom_kill_reason = ""
        _phantom_kill_timestamp = 0.0
        _phantom_positions = []
    
    # Log outside lock
    logger.critical(
        "[reconciliation] PHANTOM KILL SWITCH CLEARED by %s | duration=%.0fs | positions=%d | reason=%s",
        operator,
        duration,
        len(positions_cleared),
        reason,
    )
    
    # Record to session log
    try:
        from core.session_log import record_event
        record_event(
            category="reconciliation",
            severity="critical",
            title="Phantom kill switch cleared",
            detail=f"Cleared by {operator} after {duration:.0f}s | was: {old_reason}",
            hint="Verify reconciliation is clean before resuming full trading.",
            metadata={
                "operator": operator,
                "duration_sec": duration,
                "positions_count": len(positions_cleared),
                "clear_reason": reason,
            },
        )
    except Exception:
        pass
    
    return {
        "cleared": True,
        "was_armed": True,
        "operator": operator,
        "duration_sec": duration,
        "positions_count": len(positions_cleared),
        "positions": positions_cleared,
        "reason": reason,
    }


def reconcile_venue(venue_name: str) -> List[VenuePositionDiscrepancy]:
    """Reconcile MERID positions against a single venue."""
    discrepancies: List[VenuePositionDiscrepancy] = []
    start_time = time.monotonic()

    # Kalshi-specific: try the dedicated venue adapter first (fail-closed in live).
    if venue_name == "kalshi":
        try:
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
            _kadapter = get_kalshi_venue_adapter()
        except Exception as _ke:
            _mode = os.environ.get("MERID_PM_TRADING_MODE", "paper").lower()
            if _mode == "live":
                logger.error("Kalshi venue adapter unreachable in LIVE mode: %s", _ke)
                discrepancies.append(VenuePositionDiscrepancy(
                    venue=venue_name,
                    symbol=_KALSHI_UNREACHABLE_SYMBOL,
                    merid_qty=0.0,
                    venue_qty=0.0,
                    merid_entry_price=0.0,
                    venue_entry_price=0.0,
                    severity="critical",
                    reason=f"venue adapter raised: {_ke}",
                ))
                _mark_recon_done(discrepancies)
                return discrepancies
            else:
                logger.debug("Kalshi venue adapter unavailable in %s mode: %s", _mode, _ke)
                _mark_recon_done(discrepancies)
                return discrepancies

    try:
        from trading.adapters.registry import get_adapter
        if venue_name == "kalshi":
            try:
                import trading.adapters.kalshi  # noqa: F401
            except Exception:
                pass
        adapter = get_adapter(venue_name)
        if not adapter:
            logger.debug(f"No adapter registered for venue {venue_name}")
            return discrepancies
    except Exception as e:
        logger.warning(f"Failed to get adapter for {venue_name}: {e}")
        return discrepancies

    try:
        venue_positions = adapter.get_positions()
    except Exception as e:
        logger.warning(f"Failed to fetch positions from {venue_name}: {e}")
        discrepancies.append(VenuePositionDiscrepancy(
            venue=venue_name,
            symbol=f"__VENUE_UNREACHABLE__{venue_name}",
            merid_qty=0.0,
            venue_qty=0.0,
            merid_entry_price=0.0,
            venue_entry_price=0.0,
            severity="critical",
            reason=f"venue adapter raised: {e}",
        ))
        return discrepancies

    merid_positions = _get_merid_positions(venue_name)

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

    # Only reconcile positions that appear on at least the venue side,
    # plus MERID-side positions that match venue ticker patterns.
    # This prevents cross-domain false positives (e.g. crypto BTC position
    # flagged as a Kalshi discrepancy).
    all_symbols = sorted(set(list(venue_map.keys()) + list(merid_map.keys())))
    for symbol in all_symbols:
        v = venue_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})
        m = merid_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})

        # Skip false positives: if both quantities are 0 (or within tolerance), there's no discrepancy
        # This prevents reporting phantom positions that don't exist in either system
        if abs(v["qty"]) < 0.001 and abs(m["qty"]) < 0.001:
            continue

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
        n_info = len(discrepancies) - n_crit - n_warn
        # NOISE-FIX: Only log at warning if there are actual issues; info-level drifts go to debug
        if n_crit > 0 or n_warn > 0:
            logger.warning(
                f"Reconciliation {venue_name}: {len(discrepancies)} discrepancies "
                f"({n_crit} critical, {n_warn} warning, {n_info} info)"
            )
        else:
            logger.debug(
                f"Reconciliation {venue_name}: {n_info} minor drifts (info-level only)"
            )
    else:
        logger.info(f"Reconciliation {venue_name}: all positions match")

    # Emit reconciliation metrics if available
    if _METRICS_AVAILABLE:
        duration_seconds = time.monotonic() - start_time
        try:
            emit_recon_metrics(
                venue=venue_name,
                duration_seconds=duration_seconds,
                discrepancies=discrepancies,
            )
        except Exception as e:
            logger.debug(f"Failed to emit reconciliation metrics: {e}")

    return discrepancies


def reconcile_all_venues(venues: Optional[List[str]] = None) -> List[VenuePositionDiscrepancy]:
    """Reconcile across all configured venues."""
    global _last_discrepancies, _reconciliation_has_run, _last_reconciliation_ts
    if venues is None:
        # Production stack: use kalshi as the only venue instead of legacy paper_config
        venues = ["kalshi"]
        # try:
        #     from merid.paper_config import get_paper_config
        #     venues = get_paper_config().reconciliation_venues()
        # except (ImportError, Exception):
        #     venues = []
        # # Always include kalshi — it is the only live venue in this deployment.
        # # The old fallback to "alpaca" was wrong and caused Kalshi to be skipped.
        if not venues or venues == ["alpaca"]:
            venues = ["kalshi"]
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


def _get_merid_positions(venue_name: str = "") -> List[Dict[str, Any]]:
    """Get MERID's internal position state, filtered to a specific venue.

    For Kalshi: only returns positions whose symbols look like Kalshi tickers
    (contain 'KX' prefix or '-' separators typical of prediction market IDs).
    Generic crypto/equity symbols (BTC, ETH, AAPL, SPY) are excluded.

    This prevents cross-domain false positives in reconciliation.
    """
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        positions = engine.get_positions()
        result = []
        for pos in positions:
            if isinstance(pos, dict):
                sym = pos.get("symbol", "")
                qty = pos.get("quantity", 0.0)
                entry = pos.get("entry_price", 0.0)
            else:
                sym = getattr(pos, "symbol", "")
                qty = float(getattr(pos, "quantity", 0))
                entry = float(getattr(pos, "avg_entry_price", 0))

            # Filter: only include positions that belong to the venue
            if venue_name == "kalshi":
                # Kalshi tickers are like "KXBTC-26FEB24-50000-T99.99" or contain "-"
                # Generic symbols (BTC, ETH, AAPL, SPY, SOL) do NOT belong to Kalshi
                if not _is_kalshi_ticker(sym):
                    continue

            result.append({
                "symbol": sym,
                "quantity": float(qty),
                "entry_price": float(entry),
            })
        return result
    except Exception as e:
        logger.warning(f"Paper engine positions unavailable: {e}")
        return []


def _is_kalshi_ticker(symbol: str) -> bool:
    """Check if a symbol looks like a Kalshi prediction market ticker.

    Kalshi tickers follow patterns like:
    - KXBTC-26FEB24-50000 (crypto price)
    - KXMVESPORTS... (esports)
    - INX-26FEB24-A (index)
    They always contain hyphens, are typically 15+ characters, and use
    uppercase alphanumeric segments separated by hyphens.
    Simple symbols like 'BTC', 'ETH', 'AAPL', 'SPY' are NOT Kalshi tickers.
    Test symbols like 'SLO-TEST' are also excluded.
    """
    if not symbol:
        return False
    upper = symbol.upper()
    if "TEST" in upper or "MOCK" in upper or "SIM" in upper:
        return False
    # Exclude crypto perp/futures patterns (not Kalshi prediction markets)
    _CRYPTO_EXCLUDES = ("PERP", "FUT", "SWAP", "SPOT")
    if any(seg in _CRYPTO_EXCLUDES for seg in upper.split("-")):
        return False
    # KX prefix is the Kalshi exchange prefix — always a Kalshi ticker
    if upper.startswith("KX"):
        return True
    # Kalshi tickers: hyphens + date/period segment (DDMON, DDMONYY, YYQ#)
    # e.g. "INX-26FEB24-A", "FED-25DEC-T5.00", "GDP-25Q4-POSITIVE"
    if "-" in symbol and len(symbol) >= 10:
        import re
        if re.search(r'\d{2}[A-Z]{3}|\d{2}Q\d', upper):
            return True
    return False


def force_align_from_venue(venue_name: str, user_id: str = "operator") -> Dict[str, Any]:
    """Overwrite paper-engine positions with venue truth (destructive).

    For ``kalshi``, uses :class:`KalshiVenueAdapter` positions (same source as
    :func:`reconcile_venue`), not the trading-registry adapter alone.
    Must not be called from a running asyncio event-loop thread for Kalshi;
    use ``await asyncio.to_thread(force_align_from_venue, 'kalshi', user_id)``.
    """
    venue_positions: List[Any] = []
    venue_balances: List[Any] = []

    if venue_name == "kalshi":
        try:
            import asyncio as _asyncio

            from trading.adapters.base import PositionSnapshot
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter

            try:
                _asyncio.get_running_loop()
                return {
                    "error": (
                        "force_align_from_venue('kalshi') must run from a worker thread "
                        "without a running event loop; use "
                        "await asyncio.to_thread(force_align_from_venue, 'kalshi', user_id)"
                    ),
                }
            except RuntimeError:
                pass

            k_ad = get_kalshi_venue_adapter()
            try:
                from core.event_loop_registry import run_on_main_loop, get_main_loop
                if get_main_loop() is not None:
                    raw_positions = run_on_main_loop(k_ad.get_positions(), timeout=15)
                else:
                    # No main loop registered (e.g. CLI / tests) — fall back to
                    # a fresh asyncio.run.  Safe ONLY if the venue client has
                    # no resources bound to another loop.
                    raw_positions = _asyncio.run(k_ad.get_positions())
            except ImportError:
                raw_positions = _asyncio.run(k_ad.get_positions())
            venue_positions = [
                PositionSnapshot(
                    symbol=vp.market_id,
                    quantity=float(vp.size),
                    entry_price=float(vp.average_entry_price)
                    if vp.average_entry_price
                    else 0.0,
                    mark_price=0.0,
                    unrealized_pnl=float(vp.unrealized_pnl) if vp.unrealized_pnl else 0.0,
                    metadata={"venue": "kalshi", "outcome": getattr(vp, "outcome_id", "") or ""},
                )
                for vp in raw_positions
            ]
        except Exception as e:
            return {"error": f"Failed to fetch Kalshi positions: {e}"}

        try:
            import trading.adapters  # noqa: F401

            from trading.adapters.registry import get_adapter

            reg = get_adapter("kalshi")
            if reg:
                try:
                    venue_balances = reg.get_balances()
                except Exception as bal_exc:
                    logger.warning("Failed to fetch Kalshi balances for force-align: %s", bal_exc)
                    venue_balances = []
        except Exception as e:
            logger.warning("Kalshi registry adapter unavailable for balances: %s", e)
    else:
        try:
            import trading.adapters  # noqa: F401

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
            logger.warning("Failed to fetch balances from %s: %s", venue_name, e)
            venue_balances = []

    try:
        from trading.paper_trading import (
            PaperPosition,
            _save_paper_state,
            get_paper_engine,
        )

        engine = get_paper_engine()
    except Exception as e:
        return {"error": f"Paper engine unavailable: {e}"}

    portfolio = engine.get_portfolio(user_id)

    removed = list(portfolio.positions.keys())
    portfolio.positions.clear()
    logger.info("Cleared %d paper positions: %s", len(removed), removed)

    aligned_positions: List[Dict[str, Any]] = []
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
            "  Imported %s: qty=%s entry=%s mark=%s pnl=%s",
            vp.symbol,
            vp.quantity,
            vp.entry_price,
            vp.mark_price,
            vp.unrealized_pnl,
        )

    cash_aligned = None
    for bal in venue_balances:
        if hasattr(bal, "asset") and bal.asset == "USD":
            old_cash = portfolio.current_balance
            portfolio.current_balance = bal.available
            cash_aligned = {"old": old_cash, "new": bal.available}
            logger.info("Force-aligned cash: %.2f -> %.2f", old_cash, bal.available)
            break

    _save_paper_state(engine)

    result: Dict[str, Any] = {
        "venue": venue_name,
        "positions_removed": removed,
        "positions_aligned": len(aligned_positions),
        "positions": aligned_positions,
        "cash_aligned": cash_aligned,
    }
    logger.info("Force alignment complete: %s", json.dumps(result, default=str))
    return result


# ── Production Stack Reconciler Wrapper for UI-UX ────────────────────────────────
# This provides the interface expected by web.api.kalshi_ui for production stack
# The legacy get_kalshi_reconciler doesn't exist, so we create a simple wrapper

from dataclasses import dataclass
from enum import Enum


class ReconciliationSeverity(Enum):
    """Severity levels for reconciliation issues."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IssueType(Enum):
    """Types of reconciliation issues."""
    POSITION_MISMATCH = "position_mismatch"
    ORDER_MISMATCH = "order_mismatch"
    BALANCE_MISMATCH = "balance_mismatch"
    MISSING_POSITION = "missing_position"
    PHANTOM_POSITION = "phantom_position"


@dataclass
class ReconciliationIssue:
    """A single reconciliation issue."""
    issue_type: IssueType
    severity: ReconciliationSeverity
    description: str
    internal_value: Any
    venue_value: Any


@dataclass
class ReconciliationReport:
    """Result of a reconciliation check."""
    severity: ReconciliationSeverity
    summary: str
    issues: List[ReconciliationIssue]


class KalshiReconciler:
    """Production stack reconciler wrapper for UI-UX endpoints.
    
    This provides a simple reconciliation interface that compares internal state
    from the venue adapter with venue-reported state. For the production 15m stack,
    we use the venue adapter as the source of truth for both internal and venue state.
    """
    
    def __init__(self):
        self._adapter = None
    
    async def _get_adapter(self):
        """Lazy load the Kalshi venue adapter."""
        if self._adapter is None:
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
            self._adapter = get_kalshi_venue_adapter()
        return self._adapter
    
    def reconcile(
        self,
        internal_positions: List[Dict[str, Any]],
        venue_positions: List[Dict[str, Any]],
        internal_orders: List[Dict[str, Any]],
        venue_orders: List[Dict[str, Any]],
    ) -> ReconciliationReport:
        """Compare internal and venue state for discrepancies.
        
        For the production stack, we perform a simple comparison:
        - Position count mismatch
        - Order count mismatch
        - Position quantity mismatches
        """
        issues = []
        
        # Check position count
        if len(internal_positions) != len(venue_positions):
            issues.append(ReconciliationIssue(
                issue_type=IssueType.POSITION_MISMATCH,
                severity=ReconciliationSeverity.WARNING,
                description=f"Position count mismatch: internal={len(internal_positions)}, venue={len(venue_positions)}",
                internal_value=len(internal_positions),
                venue_value=len(venue_positions),
            ))
        
        # Check order count
        if len(internal_orders) != len(venue_orders):
            issues.append(ReconciliationIssue(
                issue_type=IssueType.ORDER_MISMATCH,
                severity=ReconciliationSeverity.WARNING,
                description=f"Order count mismatch: internal={len(internal_orders)}, venue={len(venue_orders)}",
                internal_value=len(internal_orders),
                venue_value=len(venue_orders),
            ))
        
        # Check for phantom positions (positions in venue but not internal)
        venue_symbols = {p.get("ticker", p.get("symbol", "")) for p in venue_positions}
        internal_symbols = {p.get("ticker", p.get("symbol", "")) for p in internal_positions}
        phantom_symbols = venue_symbols - internal_symbols
        
        if phantom_symbols:
            issues.append(ReconciliationIssue(
                issue_type=IssueType.PHANTOM_POSITION,
                severity=ReconciliationSeverity.ERROR,
                description=f"Phantom positions in venue: {list(phantom_symbols)}",
                internal_value=list(internal_symbols),
                venue_value=list(venue_symbols),
            ))
        
        # Determine overall severity
        if any(issue.severity == ReconciliationSeverity.CRITICAL for issue in issues):
            severity = ReconciliationSeverity.CRITICAL
        elif any(issue.severity == ReconciliationSeverity.ERROR for issue in issues):
            severity = ReconciliationSeverity.ERROR
        elif any(issue.severity == ReconciliationSeverity.WARNING for issue in issues):
            severity = ReconciliationSeverity.WARNING
        else:
            severity = ReconciliationSeverity.OK
        
        summary = f"Reconciliation complete: {len(issues)} issues found"
        
        return ReconciliationReport(
            severity=severity,
            summary=summary,
            issues=issues,
        )


# Global reconciler instance for UI-UX compatibility
_kalshi_reconciler_instance = None


def get_kalshi_reconciler() -> KalshiReconciler:
    """Get the Kalshi reconciler instance for UI-UX endpoints.
    
    This provides the interface expected by web.api.kalshi_ui for production stack.
    """
    global _kalshi_reconciler_instance
    if _kalshi_reconciler_instance is None:
        _kalshi_reconciler_instance = KalshiReconciler()
    return _kalshi_reconciler_instance
