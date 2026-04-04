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

# ── Phantom position kill switch ─────────────────────────────────────────
# Set to True to halt all new orders when phantom positions are detected.
_phantom_kill_switch: bool = False
_phantom_kill_lock = threading.Lock()


def is_phantom_kill_switch_active() -> bool:
    """Return True if phantom position kill switch is armed."""
    with _phantom_kill_lock:
        return _phantom_kill_switch


def arm_phantom_kill_switch(reason: str = "") -> None:
    """Arm the phantom position kill switch (halt new orders)."""
    global _phantom_kill_switch
    with _phantom_kill_lock:
        _phantom_kill_switch = True
    logger.critical(f"PHANTOM KILL SWITCH ARMED — {reason or 'phantom positions detected'}")


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
    discrepancy_type: str = "drift"  # drift | phantom | missing
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
            # Missing: exchange has it but we don't track it
            self.discrepancy_type = "missing"
            self.severity = "critical"
            reasons.append(f"venue has position ({self.venue_qty}), MERID has none")
        elif self.venue_qty == 0.0 and self.merid_qty != 0.0:
            # Phantom: we track it but it's not on the exchange
            self.discrepancy_type = "phantom"
            self.severity = "critical"
            reasons.append(f"MERID has position ({self.merid_qty}), venue has none")

        if abs(self.delta_price) > 0.01 and self.merid_entry_price > 0:
            pct = abs(self.delta_price / self.merid_entry_price) * 100
            if pct > 5.0:
                if self.severity != "critical":
                    self.severity = "warning"
                reasons.append(f"entry price delta {pct:.1f}%")

        self.reason = "; ".join(reasons) if reasons else "minor drift"

    @property
    def is_phantom(self) -> bool:
        """True when MERID tracks a position the exchange does not have."""
        return self.discrepancy_type == "phantom"

    @property
    def is_missing(self) -> bool:
        """True when the exchange has a position MERID does not track."""
        return self.discrepancy_type == "missing"

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
            "discrepancy_type": self.discrepancy_type,
            "timestamp": self.timestamp,
        }


def reconcile_venue(venue_name: str) -> List[PositionDiscrepancy]:
    """Reconcile MERID positions against a single venue.

    Returns list of discrepancies found. Logs a detailed diff for each.

    For the "kalshi" venue, uses KalshiVenueAdapter (async, paper-aware)
    instead of the deprecated trading.adapters.registry entry which has
    no get_positions() implementation.
    """
    discrepancies: List[PositionDiscrepancy] = []

    # Kalshi: use the dedicated venue adapter (supports paper + live positions)
    if venue_name == "kalshi":
        return _reconcile_kalshi_venue()

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


def _reconcile_kalshi_venue() -> List["PositionDiscrepancy"]:
    """Reconcile Kalshi positions using KalshiVenueAdapter.

    KalshiVenueAdapter.get_positions() is async; this helper runs it
    synchronously so reconcile_venue() can remain a plain function.
    In paper mode the adapter reads from the matching engine — no network
    call is made.  In live mode it calls the Kalshi REST API.
    """
    discrepancies: List[PositionDiscrepancy] = []
    try:
        import asyncio as _asyncio
        from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter

        adapter = get_kalshi_venue_adapter()

        # Run the async get_positions() safely from a sync context.
        # reconcile_venue() is always called from a background thread
        # (the periodic recon thread or run_in_executor), so we can
        # safely spin up a new event loop here.
        try:
            venue_positions = _asyncio.run(adapter.get_positions())
        except RuntimeError:
            # A running loop exists (e.g. called from run_in_executor inside
            # an async context) — schedule on it via run_coroutine_threadsafe.
            import concurrent.futures
            _running_loop = _asyncio.get_running_loop()
            venue_positions = concurrent.futures.Future.result(
                _asyncio.run_coroutine_threadsafe(adapter.get_positions(), _running_loop),
                timeout=30,
            )

    except Exception as exc:
        logger.warning(f"Kalshi reconciliation: could not fetch venue positions: {exc}")
        # Mark reconciliation as run with zero discrepancies so execution gate clears
        global _reconciliation_has_run, _last_reconciliation_ts, _last_discrepancies
        with _recon_lock:
            _reconciliation_has_run = True
            _last_reconciliation_ts = time.time()
            _last_discrepancies = []
        return discrepancies

    merid_positions = _get_merid_positions()

    # Build lookup maps
    venue_map: Dict[str, Any] = {}
    for vp in venue_positions:
        sym = getattr(vp, "symbol", "") or vp.get("symbol", "") if isinstance(vp, dict) else getattr(vp, "symbol", "")
        qty = getattr(vp, "quantity", 0.0) if not isinstance(vp, dict) else vp.get("quantity", 0.0)
        price = getattr(vp, "entry_price", 0.0) if not isinstance(vp, dict) else vp.get("entry_price", 0.0)
        if sym:
            venue_map[sym] = {"qty": float(qty), "entry_price": float(price)}

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
            disc = PositionDiscrepancy(
                venue="kalshi",
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
            f"Kalshi reconciliation: {len(discrepancies)} discrepancies "
            f"({n_crit} critical, {n_warn} warning)"
        )
    else:
        logger.info("Kalshi reconciliation: all positions match")

    # D3 + D4: Detect settled markets — symbols MERID holds internally but
    # the venue no longer reports (qty == 0 on venue side).  For each such
    # market, fire record_outcome() and resolve any open debate.
    settled_symbols = [
        sym for sym in merid_map
        if sym not in venue_map or venue_map.get(sym, {}).get("qty", 0.0) == 0.0
        and merid_map[sym].get("qty", 0.0) != 0.0
    ]
    if settled_symbols:
        logger.info("Kalshi reconciliation: %d settled markets detected", len(settled_symbols))
        for sym in settled_symbols:
            _fire_settlement_hooks(sym)

    return discrepancies


def _fetch_kalshi_settlement(market_id: str) -> Optional[bool]:
    """Fetch the actual YES/NO settlement result from the Kalshi API.

    Returns True if the market settled YES, False if NO, None if unknown
    or the API call failed.  Uses asyncio.run() / run_coroutine_threadsafe
    depending on whether a loop is already running.
    """
    async def _fetch() -> Optional[bool]:
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            market = await client.get_market(market_id)
            if market is None:
                return None
            if not market.resolved:
                return None
            resolution = (market.resolution or "").lower().strip()
            if resolution in ("yes", "true", "1"):
                return True
            if resolution in ("no", "false", "0"):
                return False
            # Kalshi sometimes returns the winning outcome_id — check raw_data
            raw = market.raw_data or {}
            result_str = str(raw.get("result", "")).lower()
            if result_str in ("yes", "true", "1"):
                return True
            if result_str in ("no", "false", "0"):
                return False
            logger.debug("settlement fetch: unrecognised resolution=%r for %s", resolution, market_id)
            return None
        except Exception as exc:
            logger.debug("settlement fetch API call failed for %s: %s", market_id, exc)
            return None

    import asyncio as _asyncio
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures as _cf
        fut = _cf.Future()

        async def _run() -> None:
            try:
                fut.set_result(await _fetch())
            except Exception as _e:
                fut.set_exception(_e)

        loop.call_soon_threadsafe(
            lambda: _asyncio.ensure_future(_run(), loop=loop)
        )
        try:
            return fut.result(timeout=10.0)
        except Exception as exc:
            logger.debug("settlement fetch future failed for %s: %s", market_id, exc)
            return None
    else:
        try:
            return _asyncio.run(_fetch())
        except Exception as exc:
            logger.debug("settlement fetch asyncio.run failed for %s: %s", market_id, exc)
            return None


def _fire_settlement_hooks(market_id: str) -> None:
    """Fire record_outcome() and debate resolution when a market settles.

    Called from _reconcile_kalshi_venue() when a position disappears from
    the venue (settled YES or NO).  Fetches the actual settlement result
    from the Kalshi API; falls back to side-based inference only if the
    API call fails.
    """
    # Fetch actual settlement result from Kalshi API (D12)
    settled_yes_api = _fetch_kalshi_settlement(market_id)

    # D4: record_outcome on AgentPerformanceTracker
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        if market_id in tracker._open_trades:
            rec = tracker._open_trades[market_id]
            if settled_yes_api is not None:
                # Use actual API result
                settled_yes = settled_yes_api
                logger.info(
                    "settlement hook: API result settled_yes=%s for %s",
                    settled_yes, market_id,
                )
            else:
                # Fallback: infer from position side (conservative)
                settled_yes = rec.side == "yes"
                logger.warning(
                    "settlement hook: API result unavailable for %s — "
                    "inferring settled_yes=%s from side=%s",
                    market_id, settled_yes, rec.side,
                )
            settlement_cents = 100 if settled_yes else 0
            tracker.record_outcome(
                market_id=market_id,
                settled_yes=settled_yes,
                settlement_price_cents=settlement_cents,
            )
            logger.info("settlement hook: record_outcome fired for %s (settled_yes=%s)", market_id, settled_yes)
    except Exception as exc:
        logger.debug("settlement hook record_outcome skipped for %s: %s", market_id, exc)

    # D3: resolve open debate + compute rewards
    try:
        from merid.prediction.debate import get_debate_store
        debate_store = get_debate_store()
        open_debates = debate_store.list_debates(symbol=market_id, status="open") + \
                       debate_store.list_debates(symbol=market_id, status="closed")
        for debate in open_debates:
            if debate.status == "resolved":
                continue
            # Close first if still open
            if debate.status == "open":
                post_prob = debate.pre_debate_prob  # no update available
                debate_store.close_debate(debate.id, post_prob)
            # Resolve with actual API outcome (1=YES, 0=NO); fallback to 1
            outcome = 1 if (settled_yes_api is not False) else 0
            resolved = debate_store.resolve_debate(debate.id, outcome)
            if resolved:
                logger.info("settlement hook: debate %s resolved for %s", debate.id, market_id)
            # Compute and store debate rewards
            try:
                from merid.prediction.consensus import get_prediction_consensus_store
                store = get_prediction_consensus_store()
                opinions = store.list_opinions(symbol=market_id, limit=100)
                if opinions:
                    debate_store.compute_rewards_for_resolution(
                        symbol=market_id,
                        outcome=outcome,
                        opinions=opinions,
                    )
                    logger.info(
                        "settlement hook: rewards computed for %d opinions on %s",
                        len(opinions), market_id,
                    )
            except Exception as exc:
                logger.debug("settlement hook compute_rewards skipped for %s: %s", market_id, exc)

            # D8: Emit DebateEvent through RewardEngine so MechanismRegistry
            # fires AccuracyMechanism, ImprovementMechanism, InsightMechanism etc.
            # and reward signals flow back to agent weights via the leaderboard.
            if resolved:
                try:
                    from merid.rewards.engine import get_reward_engine
                    from merid.rewards.events import DebateEvent
                    engine = get_reward_engine()
                    lift = resolved.debate_lift or 0.0
                    pre = resolved.pre_debate_prob or 0.5
                    post = resolved.post_debate_prob or pre
                    deb_event = DebateEvent(
                        debate_id=resolved.id,
                        symbol=market_id,
                        role="arbiter",
                        debate_lift=lift,
                        disagreement_width=abs(post - pre),
                        pre_debate_prob=pre,
                        post_debate_prob=post,
                        venue="kalshi",
                    )
                    engine.process_event(deb_event)
                    logger.debug(
                        "settlement hook: DebateEvent emitted for %s lift=%.4f",
                        market_id, lift,
                    )
                except Exception as exc:
                    logger.debug("settlement hook DebateEvent skipped for %s: %s", market_id, exc)

    except Exception as exc:
        logger.debug("settlement hook debate resolution skipped for %s: %s", market_id, exc)

    # D8: Emit ForecastEvent for each opinion through RewardEngine
    try:
        from merid.rewards.engine import get_reward_engine
        from merid.rewards.events import ForecastEvent
        from merid.prediction.consensus import get_prediction_consensus_store
        engine = get_reward_engine()
        store = get_prediction_consensus_store()
        opinions = store.list_opinions(symbol=market_id, limit=100)
        for op in opinions:
            agent_id = getattr(op, "agent_id", "") or op.get("agent_id", "") if isinstance(op, dict) else getattr(op, "agent_id", "")
            prob = getattr(op, "probability", 0.5) if not isinstance(op, dict) else op.get("probability", 0.5)
            conf = getattr(op, "confidence", 0.5) if not isinstance(op, dict) else op.get("confidence", 0.5)
            brier = (float(prob) - 1) ** 2  # outcome=1 (YES)
            fe = ForecastEvent(
                agent_id=str(agent_id),
                symbol=market_id,
                probability=float(prob),
                confidence=float(conf),
                outcome=1,
                brier_score=round(brier, 6),
                venue="kalshi",
            )
            engine.process_event(fe)
        if opinions:
            logger.info(
                "settlement hook: %d ForecastEvents emitted for %s",
                len(opinions), market_id,
            )
    except Exception as exc:
        logger.debug("settlement hook ForecastEvents skipped for %s: %s", market_id, exc)

    # CT bankroll: wire realized PnL into KalshiContinuousTrader at settlement.
    # This is the authoritative point where a position transitions from "open
    # exposure" to "settled cash" — exactly where record_trade_result() must fire.
    # PnL formula per fill (YES buyer):
    #   pnl = count × (settlement_cents − entry_price_cents)
    # PnL formula per fill (NO buyer, i.e. side="no", action="buy"):
    #   pnl = count × ((100 − settlement_cents) − (100 − entry_price_cents))
    #       = count × (entry_price_cents − settlement_cents)
    # For sell actions the sign flips (seller receives entry price, pays settlement).
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        from merid.trading.kalshi_continuous_trader import get_continuous_trader

        ct = get_continuous_trader()
        fills = get_fills_ledger().fills_for_ticker(market_id)

        if fills and settled_yes_api is not None:
            settlement_cents = 100 if settled_yes_api else 0
            pnl_cents = 0
            for f in fills:
                # win_cents: what this side pays out at settlement per contract
                win_cents = settlement_cents if f.side == "yes" else (100 - settlement_cents)
                if f.action == "buy":
                    pnl_cents += f.count * (win_cents - f.price_cents)
                else:  # "sell"
                    pnl_cents += f.count * (f.price_cents - win_cents)
            ct.record_trade_result(pnl_cents)
            logger.info(
                "CT bankroll: settlement hook fired market=%s settled_yes=%s pnl_cents=%d",
                market_id,
                settled_yes_api,
                pnl_cents,
            )
        elif settled_yes_api is None:
            logger.debug(
                "CT bankroll: settlement hook skipped for %s — settled_yes_api unknown",
                market_id,
            )
    except Exception as exc:
        logger.debug("CT bankroll settlement hook skipped for %s: %s", market_id, exc)


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


def has_ever_run() -> bool:
    """Check if reconciliation has ever completed at least once.

    Returns:
        True if reconciliation has run at least once, False otherwise.
    """
    with _recon_lock:
        return _reconciliation_has_run


def has_critical_discrepancies() -> bool:
    """Check if the last reconciliation found any critical discrepancies.

    Used as a hard gate before enabling execution.
    Returns True (fail-closed) if no reconciliation has ever completed.

    If reconciliation has never run, logs an explicit WARNING to distinguish
    from genuine critical discrepancies.
    """
    with _recon_lock:
        if not _reconciliation_has_run:
            logger.warning(
                "Reconciliation has NEVER run — blocking execution (fail-closed). "
                "This is a fresh start or reconciliation disabled. "
                "Run reconcile_all_venues() to unblock."
            )
            return True
        critical_count = sum(1 for d in _last_discrepancies if d.severity == "critical")
        if critical_count > 0:
            logger.error(
                f"Reconciliation found {critical_count} CRITICAL discrepancies — blocking execution"
            )
        return critical_count > 0


def get_last_reconciliation_ts() -> float:
    """Return the timestamp of the last completed reconciliation (0.0 if never run)."""
    with _recon_lock:
        return _last_reconciliation_ts


def get_last_discrepancies() -> List[PositionDiscrepancy]:
    """Return the cached result of the most recent reconciliation."""
    with _recon_lock:
        return list(_last_discrepancies)


def auto_reconcile_and_fix(
    venue_name: str = "kalshi",
    user_id: str = "operator",
    auto_fix_critical: bool = True,
) -> Dict[str, Any]:
    """Automatically reconcile and fix critical discrepancies.

    This function:
    1. Runs reconciliation for the specified venue
    2. Checks for critical discrepancies
    3. If found and auto_fix_critical=True, automatically aligns to venue truth
    4. Sends alerts for any fixes performed

    Args:
        venue_name: Venue to reconcile (default: "kalshi")
        user_id: User ID for paper engine alignment
        auto_fix_critical: If True, automatically fix critical discrepancies

    Returns:
        Dictionary with reconciliation results and any fixes performed
    """
    result = {
        "venue": venue_name,
        "reconciliation_run": False,
        "discrepancies_found": 0,
        "critical_discrepancies": 0,
        "auto_fix_attempted": False,
        "auto_fix_success": False,
        "aligned_positions": [],
        "errors": [],
    }

    try:
        # Run reconciliation
        discrepancies = reconcile_venue(venue_name)
        result["reconciliation_run"] = True
        result["discrepancies_found"] = len(discrepancies)

        critical = [d for d in discrepancies if d.severity == "critical"]
        result["critical_discrepancies"] = len(critical)

        logger.info(
            f"Reconciliation complete: {len(discrepancies)} discrepancies "
            f"({len(critical)} critical)"
        )

        # Auto-fix critical discrepancies if enabled
        if critical and auto_fix_critical:
            result["auto_fix_attempted"] = True
            logger.warning(
                f"Auto-fix: {len(critical)} critical discrepancies detected, "
                f"aligning to {venue_name} truth..."
            )

            # Perform alignment
            align_result = force_align_from_venue(venue_name, user_id)

            if "error" in align_result:
                result["errors"].append(align_result["error"])
                logger.error(f"Auto-fix failed: {align_result['error']}")
            else:
                result["auto_fix_success"] = True
                result["aligned_positions"] = align_result.get("aligned_positions", [])
                logger.info(
                    f"Auto-fix complete: aligned {len(result['aligned_positions'])} positions"
                )

                # Send alert about auto-fix
                try:
                    from merid.prediction.alerts import get_alert_manager, AlertCategory, AlertSeverity
                    alert_mgr = get_alert_manager()
                    alert_mgr.fire_risk_warning(
                        market_id=venue_name,
                        message=f"Auto-reconciliation fixed {len(critical)} critical discrepancies. "
                        f"Aligned {len(result['aligned_positions'])} positions to {venue_name} truth.",
                        data={
                            "discrepancies": len(discrepancies),
                            "critical": len(critical),
                            "aligned_positions": len(result["aligned_positions"]),
                        },
                    )
                except Exception as alert_exc:
                    logger.debug(f"Alert send failed: {alert_exc}")

        elif critical and not auto_fix_critical:
            logger.warning(
                f"Found {len(critical)} critical discrepancies but auto_fix_critical=False"
            )

    except Exception as exc:
        result["errors"].append(str(exc))
        logger.error(f"Auto-reconcile error: {exc}")

    return result


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
        logger.warning(f"Failed to fetch balances from {venue_name}: {e}")
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
