"""Unified Execution Gate — single source of truth for "can we trade?"

Aggregates all safety checks into one boolean + reasons list:
  1. Kill switch status
  2. Reconciliation status (fail-closed on fresh start)
  3. Price feed staleness
  4. PnL consistency

Every backend path that wants to execute a trade should call
`is_execution_blocked()` and respect the result.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("core.execution_gate")

# WS hysteresis state — must be at module level (used as globals in check_execution_gate)
_ws_stale_count: int = 0
_ws_healthy_count: int = 0
_ws_was_stale: bool = False

# Last logged (gate_state, critical sources, warning sources) — avoid log spam on hot paths
_gate_diag_last_sig: Optional[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = None


def reset_lag_halt_counter() -> None:
    """Legacy hook for Kalshi CT startup — loop lag no longer affects :func:`check_execution_gate`.

    Event-loop latency is still recorded by ``merid.diagnostics.loop_lag`` and health APIs;
    it is intentionally excluded from gate state (CLEAR / LIMITED / BLOCKED) so trading
    is not degraded by diagnostic lag measurements alone.
    """
    logger.debug("reset_lag_halt_counter: no-op (loop lag not a gate input)")


class GateState(str, Enum):
    """Fine-grained execution gate state."""
    CLEAR = "clear"        # all checks pass — full trading
    LIMITED = "limited"    # warnings only — reduce/close positions OK, no new risk
    BLOCKED = "blocked"    # critical issues — no execution at all


# ── Remediation hints per source ──────────────────────────────────────
REMEDIATION_HINTS: dict[str, str] = {
    "kill_switch": "Reset via Mode & Safety panel after investigating the trigger cause.",
    "reconciliation": "Wait for the next reconciliation cycle or trigger a manual run from System settings.",
    "fills_ledger_reconciliation": (
        "Inspect fills ledger divergences via GET /api/v1/kalshi/health/reconciliation. "
        "Trigger manual reconcile or restart fills poller."
    ),
    "price_feed": "Check venue connectivity and data source health in Venue Health Grid.",
    "pnl_consistency": "Inspect PnL sources in the Consistency widget; look for missed fills or stale equity data.",
    "news_feed": "Check FINNHUB_API_KEY in .env, verify API category (general vs crypto), and ensure symbols list is populated. Consider Polygon fallback if Finnhub is down.",
    "basis_misalignment": (
        "Spot/Kalshi basis is persistently offside for one or more assets. "
        "Check the Spot Basis panel in Operator Dashboard for per-asset details. "
        "New entries are not blocked, but signal quality may be degraded while offside."
    ),
    "kalshi_ws": (
        "Kalshi WebSocket is disconnected or not subscribed to any market tickers. "
        "Check the Venue Health Grid; the bridge restarts automatically — wait 15s and re-check. "
        "Set MERID_EXEC_GATE_REQUIRE_KALSHI_WS=0 to disable this gate in demo mode."
    ),
}


@dataclass
class BlockReason:
    """A single reason execution is blocked."""
    source: str          # e.g. "kill_switch", "reconciliation", "price_feed", "pnl_consistency"
    severity: str        # "critical" | "warning"
    message: str
    details: Optional[str] = None
    hint: Optional[str] = None


@dataclass
class ExecutionGateStatus:
    """Snapshot of the execution gate state."""
    blocked: bool
    safe_to_trade: bool
    gate_state: str = GateState.BLOCKED.value  # "clear" | "limited" | "blocked"
    reasons: List[BlockReason] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_limited(self) -> bool:
        """True when gate is in reduce-only mode (warnings but no critical)."""
        return self.gate_state == GateState.LIMITED.value

    def allows_reduce(self) -> bool:
        """True when closing/reducing positions is permitted (clear or limited)."""
        return self.gate_state in (GateState.CLEAR.value, GateState.LIMITED.value)

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "safe_to_trade": self.safe_to_trade,
            "gate_state": self.gate_state,
            "reasons": [
                {
                    "source": r.source,
                    "severity": r.severity,
                    "message": r.message,
                    "details": r.details,
                    "hint": r.hint,
                }
                for r in self.reasons
            ],
            "timestamp": self.timestamp,
        }


def live_execution_blocked(status: ExecutionGateStatus) -> bool:
    """True when live new-risk orders must not proceed.

    Centralizes the same predicate used by the Kalshi order router and tool paths:
    blocked critical issues, or ``safe_to_trade`` false (e.g. integrity overlay).
    """
    return bool(status.blocked or not status.safe_to_trade)


def _log_gate_state_diagnostic(gate_state: str, reasons: List[BlockReason]) -> None:
    """Emit a single INFO line when gate state or reason sources change (not every poll)."""
    global _gate_diag_last_sig
    crit = tuple(sorted({r.source for r in reasons if r.severity == "critical"}))
    warn = tuple(sorted({r.source for r in reasons if r.severity == "warning"}))
    sig: Tuple[str, Tuple[str, ...], Tuple[str, ...]] = (gate_state, crit, warn)
    if sig == _gate_diag_last_sig:
        return
    _gate_diag_last_sig = sig
    if gate_state == GateState.BLOCKED.value:
        logger.info(
            "Execution gate BLOCKED — critical sources: %s",
            ", ".join(crit) if crit else "(none)",
        )
        if crit == ("kill_switch",):
            logger.info(
                "Execution gate BLOCKED — sole critical cause is kill_switch "
                "(persisted or manual); venue reconciliation is not the primary blocker.",
            )
        elif crit == ("reconciliation",):
            logger.info(
                "Execution gate BLOCKED — sole critical cause is reconciliation "
                "(kill_switch is not engaged).",
            )
    elif gate_state == GateState.LIMITED.value:
        logger.info(
            "Execution gate LIMITED — warning sources: %s",
            ", ".join(warn) if warn else "(none)",
        )
    elif gate_state == GateState.CLEAR.value:
        logger.info("Execution gate CLEAR — no blocking or warning reasons")


def _is_kalshi_demo_mode() -> bool:
    """Return True when running in Kalshi demo/paper mode or kalshi-only profile.

    In this mode, reconciliation and PnL consistency checks reflect
    the crypto paper-trading subsystem which is irrelevant to Kalshi
    execution. Their severity is downgraded from critical → warning
    so they don't block the Kalshi trading path.
    """
    import os
    # Kalshi-only profile: paper matrix PnL divergence is expected
    if os.environ.get("MERID_PROFILE", "").lower() == "kalshi-only":
        return True
    try:
        from merid.settings import settings
        return settings.KALSHI_USE_DEMO
    except Exception:
        return os.environ.get("KALSHI_USE_DEMO", "true").lower() in ("true", "1", "yes")  # safe default: demo


def check_execution_gate() -> ExecutionGateStatus:
    """Run all safety checks and return unified gate status.

    This is the **only** function backend code should call to decide
    whether execution is allowed.
    """
    reasons: List[BlockReason] = []
    kalshi_demo = _is_kalshi_demo_mode()

    # ── 1. Kill switch ──────────────────────────────────────────────
    try:
        from merid.risk.kill_switches import risk_controller
        if risk_controller._global_kill:
            reasons.append(BlockReason(
                source="kill_switch",
                severity="critical",
                message="Kill switch is engaged",
                details=risk_controller._kill_details or str(risk_controller._kill_reason),
                hint=REMEDIATION_HINTS["kill_switch"],
            ))
    except Exception as exc:
        logger.error("Kill switch check failed: %s", exc, exc_info=True)
        # Fail-closed: if we can't verify kill switch, assume it's triggered
        reasons.append(BlockReason(
            source="kill_switch",
            severity="critical",
            message="Kill switch check failed - assuming triggered",
            details=f"Exception: {exc}",
            hint="Check risk_controller module and system health.",
        ))

    # ── 2. Kalshi venue reconciliation ───────────────────────────────
    # Legacy trading.reconciliation (crypto paper-truth) was removed; venue
    # truth lives in merid.reconciliation only. Critical in live mode.
    kalshi_recon_severity = "warning" if kalshi_demo else "critical"
    try:
        from merid.reconciliation import has_critical_discrepancies as kalshi_has_critical, get_last_discrepancies
        if kalshi_has_critical():
            discrepancies = get_last_discrepancies()

            if not discrepancies:
                # has_critical_discrepancies() is fail-closed: it returns True when
                # reconciliation has never run (empty list).  This is normal at startup
                # and should not hard-block trading — downgrade to a transient warning.
                reasons.append(BlockReason(
                    source="reconciliation",
                    severity="warning",
                    message="Kalshi reconciliation not yet run (normal at startup)",
                    details="First reconciliation cycle will clear this automatically",
                    hint=REMEDIATION_HINTS["reconciliation"],
                ))
            else:
                # Distinguish genuine discrepancies from benign zero-qty states
                genuine_critical = []
                for d in discrepancies:
                    if d.severity != "critical":
                        continue
                    # "both sides zero" is a fresh start, not a real mismatch
                    if d.merid_qty == 0.0 and d.venue_qty == 0.0:
                        continue
                    genuine_critical.append(d)

                if not genuine_critical:
                    reasons.append(BlockReason(
                        source="reconciliation",
                        severity="warning",
                        message="Kalshi venue reconciliation: no positions to reconcile (fresh start)",
                        details="Both MERID and venue report zero positions — benign state",
                        hint=REMEDIATION_HINTS["reconciliation"],
                    ))
                else:
                    reasons.append(BlockReason(
                        source="reconciliation",
                        severity=kalshi_recon_severity,
                        message="Kalshi venue reconciliation found critical discrepancies",
                        details=f"{len(genuine_critical)} genuine position mismatches between MERID and Kalshi venue",
                        hint=REMEDIATION_HINTS["reconciliation"],
                    ))
    except Exception as exc:
        logger.debug("Kalshi venue reconciliation check skipped: %s", exc)

    # ── 2b. Fills-ledger internal reconciliation status ───────────────
    # Separate from venue-level reconciliation: checks whether the fills
    # ledger's own fills-vs-REST-positions consistency is BROKEN.
    # BROKEN means the ledger cannot compute reliable net positions, making
    # risk calculations unsafe — must block execution in live mode.
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        _ledger = get_fills_ledger()
        _fl_recon = _ledger.get_reconciliation_status()
        _fl_status = str(_fl_recon.get("status", "unknown"))
        if _fl_status == "broken":
            _fl_severity = "warning" if kalshi_demo else "critical"
            reasons.append(BlockReason(
                source="fills_ledger_reconciliation",
                severity=_fl_severity,
                message="Fills ledger reconciliation BROKEN — positions unreliable",
                details=(
                    f"fills_ledger reports reconciliation_status=broken; "
                    f"last_run={_fl_recon.get('last_run', 'never')}"
                ),
                hint=REMEDIATION_HINTS["fills_ledger_reconciliation"],
            ))
        elif _fl_status == "degraded":
            reasons.append(BlockReason(
                source="fills_ledger_reconciliation",
                severity="warning",
                message="Fills ledger reconciliation degraded — minor divergences detected",
                details=f"divergences={_fl_recon.get('divergences', [])}",
                hint=REMEDIATION_HINTS["fills_ledger_reconciliation"],
            ))
    except Exception as _fl_exc:
        logger.debug("Fills-ledger reconciliation gate check skipped: %s", _fl_exc)

    # ── 3. Price feed staleness ─────────────────────────────────────
    # In Kalshi demo mode, crypto price feeds are non-critical.
    try:
        stale_result = check_price_feed_staleness()
        if not stale_result["safe_to_trade"]:
            stale_symbols = [s["symbol"] for s in stale_result["stale_symbols"]]
            if kalshi_demo:
                feed_severity = "warning"
            else:
                feed_severity = "critical" if stale_result["critical_count"] > 0 else "warning"
            reasons.append(BlockReason(
                source="price_feed",
                severity=feed_severity,
                message=f"{len(stale_symbols)} price feed(s) stale",
                details=", ".join(stale_symbols[:5]) + ("..." if len(stale_symbols) > 5 else ""),
                hint=REMEDIATION_HINTS["price_feed"],
            ))
    except Exception as exc:
        # Price feed check threw — warn only, never hard-block because of a
        # transient exception in the staleness checker itself.
        logger.warning("Price feed staleness check failed (non-blocking): %s", exc)
        reasons.append(BlockReason(
            source="price_feed",
            severity="warning",
            message="Price feed staleness check unavailable",
            details=f"Exception: {exc}",
            hint=REMEDIATION_HINTS["price_feed"],
        ))

    # ── 4. PnL consistency ──────────────────────────────────────────
    try:
        pnl_result = check_pnl_consistency()
        if not pnl_result["consistent"]:
            reasons.append(BlockReason(
                source="pnl_consistency",
                severity="warning",
                message=f"PnL sources diverge by ${pnl_result['max_divergence_usd']:.2f}",
                details=f"Threshold: ${pnl_result['threshold_usd']:.2f}",
                hint=REMEDIATION_HINTS["pnl_consistency"],
            ))
    except Exception as exc:
        logger.error("PnL consistency check failed: %s", exc, exc_info=True)
        # Fail-closed: if we can't verify PnL, flag as inconsistent
        reasons.append(BlockReason(
            source="pnl_consistency",
            severity="warning",
            message="PnL consistency check failed",
            details=f"Exception: {exc}",
            hint=REMEDIATION_HINTS["pnl_consistency"],
        ))

    # ── 5. Dependency health ─────────────────────────────────────
    try:
        from core.dependency_health import check_all_dependencies
        dep_summary = check_all_dependencies()
        if dep_summary["any_critical_down"]:
            down_deps = [
                d["name"] for d in dep_summary["dependencies"]
                if d["status"] == "down" and d["critical"]
            ]
            reasons.append(BlockReason(
                source="dependency_health",
                severity="critical",
                message=f"Critical dependency DOWN: {', '.join(down_deps)}",
                details=f"{dep_summary['down_count']}/{dep_summary['total']} dependencies down",
                hint="Check venue connectivity and service health in System Health panel.",
            ))
        elif dep_summary["degraded_count"] > 0:
            # Only gate on CRITICAL deps that are degraded — non-critical
            # degraded deps (smtp, twitter, neo4j, kalshi_websocket) are
            # informational and must not block new entries.
            critical_degraded = [
                d["name"] for d in dep_summary["dependencies"]
                if d["status"] == "degraded" and d["critical"]
            ]
            if critical_degraded:
                reasons.append(BlockReason(
                    source="dependency_health",
                    severity="warning",
                    message=f"Dependencies degraded: {', '.join(critical_degraded)}",
                    details=f"{dep_summary['degraded_count']} degraded ({len(critical_degraded)} critical)",
                ))
    except Exception as exc:
        logger.debug("Dependency health check failed: %s", exc)

    # ── 6. News feed health (warning only, non-blocking) ────────────
    # News starvation degrades signal quality but must NEVER block execution.
    # Finnhub is an inform/conviction input, not a hard dependency for order routing.
    try:
        from merid.signals.live_feeds import get_live_feed_manager
        mgr = get_live_feed_manager()
        feed_health = mgr.get_feed_health()
        news = feed_health.get("news", {})
        
        news_status = news.get("status", "unknown")
        # News feed status must only affect conviction, never block execution.
        # Even API errors are treated as "limited/warning" severity only.
        if news_status in ("error", "zero_data", "no_matches", "stale"):
            details = []
            if news.get("error"):
                details.append(f"Error: {news['error']}")
            if news.get("api_articles_last_fetch") is not None:
                details.append(f"API articles: {news['api_articles_last_fetch']}")
            if news.get("ingested_last_fetch") is not None:
                details.append(f"Ingested: {news['ingested_last_fetch']}")
            
            reasons.append(BlockReason(
                source="news_feed",
                severity="warning",  # ALWAYS warning - news can inform but never block
                message=f"News feed {news_status}: Finnhub",
                details="; ".join(details) if details else None,
                hint="Check FINNHUB_API_KEY in .env, verify API category (general vs crypto), and ensure symbols list is populated. Consider Polygon fallback if Finnhub is down.",
            ))
    except Exception as exc:
        logger.debug("News feed health check failed: %s", exc)

    # Event-loop lag: use ``merid.diagnostics.loop_lag`` + /health ``event_loop_lag`` only.
    # It is not a gate input — lag must not flip LIMITED/BLOCKED or appear in ``reasons``.

    # ── 6b. Kalshi WebSocket gate (opt-in via env var) ───────────────────
    # Only active when MERID_EXEC_GATE_REQUIRE_KALSHI_WS=1.  In live mode a
    # disconnected or stale WS means orderbook data is missing — BLOCKED.
    # Fail-open: any import/runtime error is silently skipped.
    _require_kalshi_ws = os.environ.get("MERID_EXEC_GATE_REQUIRE_KALSHI_WS", "0").strip() == "1"
    if _require_kalshi_ws:
        try:
            from merid.event_venues.kalshi.ws_bridge import get_kalshi_ws_status
            _ws_status = get_kalshi_ws_status()
            _ws_connected = bool(_ws_status.get("connected", False))
            _ws_tickers = int(_ws_status.get("subscribed_tickers", 0))
            if not _ws_connected:
                reasons.append(BlockReason(
                    source="kalshi_ws",
                    severity="critical",
                    message="kalshi_ws:not_connected — Kalshi WebSocket bridge disconnected",
                    details="WS bridge is not running or the underlying connection dropped",
                    hint=REMEDIATION_HINTS["kalshi_ws"],
                ))
            elif _ws_tickers == 0:
                reasons.append(BlockReason(
                    source="kalshi_ws",
                    severity="critical",
                    message="kalshi_ws:no_subscriptions — Kalshi WebSocket has 0 market subscriptions",
                    details="Bridge connected but no market tickers subscribed — orderbook is empty",
                    hint=REMEDIATION_HINTS["kalshi_ws"],
                ))
            else:
                # Staleness check: if ws_client.last_msg_ago_s > threshold → BLOCKED
                _stale_threshold_s = float(os.environ.get("MERID_EXEC_GATE_KALSHI_WS_STALE_S", "60"))
                _ws_client = _ws_status.get("ws_client", {})
                _last_msg_ago = _ws_client.get("last_msg_ago_s") if _ws_client else None
                if _last_msg_ago is not None and _last_msg_ago > _stale_threshold_s:
                    reasons.append(BlockReason(
                        source="kalshi_ws",
                        severity="critical",
                        message=f"kalshi_ws:stale — no Kalshi WS message for {_last_msg_ago:.0f}s (threshold {_stale_threshold_s:.0f}s)",
                        details=f"Last message {_last_msg_ago:.1f}s ago; stale threshold is {_stale_threshold_s:.0f}s",
                        hint=REMEDIATION_HINTS["kalshi_ws"],
                    ))
        except Exception as _ws_exc:
            logger.debug("Kalshi WS gate check skipped: %s", _ws_exc)

    # ── 7. Spot/Kalshi basis alignment (warning only — never blocks) ────
    # Fail-open: any exception in the basis check is silently skipped so that
    # a tracker startup race or import error never blocks trading.
    try:
        from merid.alignment import get_spot_basis_tracker
        from merid.alignment.spot_basis_tracker import AlignmentState
        _tracker = get_spot_basis_tracker()
        _offside = [
            a for a, ab in _tracker.get_all().items()
            if ab.alignment == AlignmentState.OFFSIDE
        ]
        if _offside:
            reasons.append(BlockReason(
                source="basis_misalignment",
                severity="warning",
                message=f"Spot/Kalshi basis offside: {', '.join(sorted(_offside))}",
                details=(
                    f"Basis has exceeded per-asset threshold for ≥ breach_count_threshold "
                    f"consecutive ticks. Assets: {', '.join(sorted(_offside))}"
                ),
                hint=REMEDIATION_HINTS["basis_misalignment"],
            ))
    except Exception as _basis_exc:
        logger.debug("Basis alignment check skipped: %s", _basis_exc)
        # Fail-open: never add a reason when the check itself fails

    has_critical = any(r.severity == "critical" for r in reasons)
    has_warning = any(r.severity == "warning" for r in reasons)
    blocked = has_critical

    if has_critical:
        gate_state = GateState.BLOCKED.value
    elif has_warning:
        gate_state = GateState.LIMITED.value
    else:
        gate_state = GateState.CLEAR.value

    _log_gate_state_diagnostic(gate_state, reasons)

    # ── Gate transition logging + session event ──
    if blocked and not _was_blocked:
        reasons_str = "; ".join(r.message for r in reasons)
        logger.warning("⛔ EXECUTION BLOCKED: %s", reasons_str)
        try:
            from core.session_log import record_event
            hints = [r.hint for r in reasons if r.hint]
            record_event(
                category="gate",
                severity="critical",
                title="Execution gate BLOCKED",
                detail=reasons_str,
                hint=hints[0] if hints else None,
                metadata={"reasons": [r.source for r in reasons], "gate_state": gate_state},
            )
        except Exception as _log_exc:
            logger.debug("session_log record_event failed (gate blocked): %s", _log_exc)
    elif not blocked and _was_blocked:
        logger.info("✅ Execution gate OPEN — all checks passed")
        try:
            from core.session_log import record_event
            record_event(
                category="gate",
                severity="info",
                title="Execution gate CLEAR",
                detail="All safety checks passed — trading permitted",
            )
        except Exception as _log_exc:
            logger.debug("session_log record_event failed (gate clear): %s", _log_exc)

    _update_blocked_state(blocked)

    return ExecutionGateStatus(
        blocked=blocked,
        safe_to_trade=not blocked,
        gate_state=gate_state,
        reasons=reasons,
    )


# ── Internal state tracking ─────────────────────────────────────────
_was_blocked: bool = True  # start blocked until first check passes


def _update_blocked_state(blocked: bool) -> None:
    global _was_blocked
    _was_blocked = blocked


# ── Gate Whitelist / ACL ─────────────────────────────────────────────
# Per audit: only whitelisted subsystems may move the gate to LIMITED or BLOCKED

# Whitelisted sources that can set gate=LIMITED
_GATE_LIMITED_WHITELIST: Set[str] = {
    "kill_switch",           # Risk controller
    "reconciliation",        # Venue reconciliation (fresh start)
    "phantom_kill",         # Phantom position kill
    "kalshi_ws",            # Kalshi WS disconnected/stale (live mode only)
    "price_feed",           # Major crypto feed stale
    "pnl_consistency",      # PnL divergence
    "ws_health",            # WS degraded (transitions to LIMITED before BLOCKED)
    "kalshi_client",        # Kalshi circuit breaker
    "kalshi_risk",          # Risk manager
    "dependency_health",    # Critical dependency down (if configured)
}

# Whitelisted sources that can set gate=BLOCKED
_GATE_BLOCKED_WHITELIST: Set[str] = {
    "kill_switch",           # Global kill
    "phantom_kill",         # Phantom position kill
    "reconciliation",        # Critical recon discrepancies
    "kalshi_ws",            # Kalshi WS disconnected/stale (live mode only)
    "price_feed",           # Major crypto feed failed
    "ws_health",            # WS failed after degraded
    "kalshi_client",        # Kalshi auth failure, circuit open
    "circuit_breaker",      # Venue circuit breaker
    "dependency_health",    # If explicitly configured to block
}

# Advisory-only sources that must NOT set BLOCKED (per audit)
_GATE_ADVISORY_ONLY: Set[str] = {
    "session_guard",        # Kalshi maintenance windows
    "event_loop_monitor",   # Loop lag is advisory only
    "observability",        # General observability warnings
    "alt_crypto_feed",      # Alt crypto stale is warning only
    "news_feed",            # News is informational only
    "basis_misalignment",   # Spot/Kalshi basis offside — advisory warning only, never blocks
}


def _check_gate_whitelist(
    source: str,
    requested_state: str,
    current_state: str,
) -> Tuple[bool, Optional[str]]:
    """Check if a source is allowed to set the requested gate state.
    
    Returns:
        (allowed, violation_reason) — allowed is True if whitelisted,
        violation_reason is set if not allowed.
    """
    # Always allow clearing to a less restrictive state
    if requested_state == GateState.CLEAR.value:
        return True, None
    if current_state == GateState.BLOCKED.value and requested_state == GateState.LIMITED.value:
        return True, None
    
    # Check BLOCKED whitelist
    if requested_state == GateState.BLOCKED.value:
        if source in _GATE_BLOCKED_WHITELIST:
            return True, None
        if source in _GATE_ADVISORY_ONLY:
            return False, f"GATE WHITELIST VIOLATION: advisory source '{source}' attempted BLOCKED"
        return False, f"GATE WHITELIST VIOLATION: source '{source}' not in BLOCKED whitelist"
    
    # Check LIMITED whitelist
    if requested_state == GateState.LIMITED.value:
        if source in _GATE_LIMITED_WHITELIST:
            return True, None
        if source in _GATE_ADVISORY_ONLY:
            return False, f"GATE WHITELIST VIOLATION: advisory source '{source}' attempted LIMITED"
        return False, f"GATE WHITELIST VIOLATION: source '{source}' not in LIMITED whitelist"
    
    # Unknown state
    return False, f"GATE WHITELIST VIOLATION: unknown state '{requested_state}'"


def can_source_set_gate(source: str, state: str) -> bool:
    """Public check if a source can set a gate state (for unit tests)."""
    allowed, _ = _check_gate_whitelist(source, state, GateState.CLEAR.value)
    return allowed


# ── Price feed staleness config ─────────────────────────────────────

@dataclass
class SymbolGroupConfig:
    """Staleness threshold for a group of symbols."""
    name: str
    symbols: set
    threshold_seconds: float
    critical: bool  # if True, stale symbols in this group block execution


# Default symbol groups — override via set_staleness_config()
# When KALSHI_ENV=live and KALSHI_USE_DEMO=false, CT fetches spot prices from CoinGecko REST
# on a 60-second cycle.  A hard 60s threshold means the previous cycle's price is always
# "stale" by the time the gate runs mid-cycle.  Use KALSHI_PRICE_FEED_CRITICAL_THRESHOLD_S
# (default 120) to give one full CT cycle of headroom before tripping BLOCKED.
_price_feed_critical_threshold_s = float(
    os.getenv("KALSHI_PRICE_FEED_CRITICAL_THRESHOLD_S", "120")
)
_staleness_config: List["SymbolGroupConfig"] = [
    SymbolGroupConfig(
        name="major_crypto",
        # Coinbase Advanced Trade stores prices under BTC/USD (slash, USD-denominated).
        # These are the only keys emitted by _coinbase_ticker_loop after USDT mirror removal.
        # Staleness in this group blocks execution (critical=True).
        symbols={
            "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD",
        },
        threshold_seconds=_price_feed_critical_threshold_s,
        critical=True,
    ),
    # alt_crypto group removed: AVAX/ADA/DOT/etc are not in our trading universe
    # and were all USDT-keyed (dead after USDT removal). Non-critical anyway.
]

DEFAULT_STALENESS_THRESHOLD = 120  # fallback for symbols not in any group


def set_staleness_config(configs: List["SymbolGroupConfig"]) -> None:
    """Replace staleness config (useful for tests and runtime tuning)."""
    global _staleness_config
    _staleness_config = list(configs)
    logger.info("Staleness config updated: %d groups", len(configs))


def get_staleness_config() -> List["SymbolGroupConfig"]:
    """Return current staleness config."""
    return list(_staleness_config)


def _get_threshold_for_symbol(symbol: str) -> tuple:
    """Return (threshold_seconds, is_critical, group_name) for a symbol."""
    for group in _staleness_config:
        if symbol in group.symbols:
            return group.threshold_seconds, group.critical, group.name
    return DEFAULT_STALENESS_THRESHOLD, False, "default"


# ── Price feed staleness check ──────────────────────────────────────


def check_price_feed_staleness() -> dict:
    """Check per-symbol price feed staleness.

    Returns:
        dict with keys: safe_to_trade, stale_symbols, critical_count, total_checked, groups
    """
    from data.live_price_feed import get_live_price_feed

    feed = get_live_price_feed()
    now = time.time()
    stale_symbols = []
    critical_count = 0
    total_checked = 0

    for symbol, price_data in feed.price_cache.items():
        total_checked += 1
        threshold, is_critical, group_name = _get_threshold_for_symbol(symbol)
        age = now - price_data.timestamp.timestamp() if hasattr(price_data.timestamp, 'timestamp') else now - float(price_data.timestamp)

        if age > threshold:
            stale_symbols.append({
                "symbol": symbol,
                "age_seconds": round(age, 1),
                "threshold_seconds": threshold,
                "group": group_name,
                "critical": is_critical,
            })
            if is_critical:
                critical_count += 1

    # Safe to trade if no critical-group symbols are stale
    safe = critical_count == 0

    return {
        "safe_to_trade": safe,
        "stale_symbols": stale_symbols,
        "critical_count": critical_count,
        "total_checked": total_checked,
        "timestamp": now,
        "groups": [
            {"name": g.name, "threshold_seconds": g.threshold_seconds, "critical": g.critical, "symbol_count": len(g.symbols)}
            for g in _staleness_config
        ],
    }


# ── PnL consistency check ──────────────────────────────────────────

PNL_CONSISTENCY_THRESHOLD = 5.0  # $5 tolerance


def check_pnl_consistency() -> dict:
    """Compare PnL across sources **within the same domain**.

    The paper_engine tracks crypto-sim portfolios while kalshi_session
    tracks Kalshi event-market intervals.  These are independent domains
    and must NOT be compared against each other.  Each domain is checked
    internally for self-consistency, and divergence is only flagged when
    two sources that genuinely track the *same* positions disagree.

    risk_controller tracks *daily* PnL that resets at midnight, so it is
    reported for visibility but excluded from the divergence calculation.

    Returns:
        dict with keys: consistent, max_divergence_usd, threshold_usd,
        sources (all), cumulative_sources (the subset used for comparison)
    """
    # ── Collect sources by domain ──────────────────────────────────
    kalshi_domain: dict[str, float] = {}
    crypto_domain: dict[str, float] = {}
    daily: dict[str, float] = {}

    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        total_pnl = 0.0
        for _uid, portfolio in engine.portfolios.items():
            total_pnl += portfolio.total_pnl
        crypto_domain["paper_engine"] = round(total_pnl, 2)
    except Exception as _pe_exc:
        logger.debug("paper_engine PnL lookup failed: %s", _pe_exc)

    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        if session.is_active:
            kalshi_pnl = sum(
                iv.net_pnl_cents / 100.0
                for iv in session._intervals.values()
                if iv.total_trades > 0
            )
            kalshi_domain["kalshi_session"] = round(kalshi_pnl, 2)
    except Exception as _ks_exc:
        logger.debug("kalshi_session PnL lookup failed: %s", _ks_exc)

    try:
        from merid.risk.kill_switches import risk_controller
        daily["risk_controller"] = round(risk_controller._daily_pnl, 2)
    except Exception as _rc_exc:
        logger.debug("risk_controller PnL lookup failed: %s", _rc_exc)

    try:
        from web.api.operator import _equity_buffer
        if _equity_buffer:
            crypto_domain["equity_series"] = _equity_buffer[-1].get("pnl", 0)
    except Exception as _eq_exc:
        logger.debug("equity_series PnL lookup failed: %s", _eq_exc)

    # ── Compare within each domain (not across) ───────────────────
    def _domain_divergence(d: dict[str, float]) -> float:
        vals = list(d.values())
        return (max(vals) - min(vals)) if len(vals) >= 2 else 0.0

    kalshi_div = _domain_divergence(kalshi_domain)
    crypto_div = _domain_divergence(crypto_domain)
    max_divergence = max(kalshi_div, crypto_div)
    consistent = max_divergence <= PNL_CONSISTENCY_THRESHOLD

    all_sources = {**crypto_domain, **kalshi_domain, **daily}
    cumulative = {**crypto_domain, **kalshi_domain}

    return {
        "consistent": consistent,
        "max_divergence_usd": round(max_divergence, 2),
        "threshold_usd": PNL_CONSISTENCY_THRESHOLD,
        "sources": all_sources,
        "cumulative_sources": cumulative,
    }


# ── Portfolio Integrity Check ──────────────────────────────────────────────

def check_portfolio_integrity(
    fills_ledger,
    portfolio_state,
    risk_state,
    settings,
) -> tuple[bool, str]:
    """Cross-check portfolio consistency across all subsystems.
    
    Run this periodically (e.g., every 30s in risk agent) to catch mismatches
    early before they compound into trading errors.
    
    Returns:
        (is_healthy, reason_string)
        - is_healthy: False means CRITICAL issues that should block in LIVE mode
        - reason_string: Description of issues found (empty if all clear)
    """
    import os
    issues = []
    warnings = []
    
    # 1. Fills vs Portfolio: Ledger position count vs portfolio market count
    try:
        if fills_ledger is not None:
            ledger_positions = fills_ledger.compute_net_positions()
            if portfolio_state is not None:
                portfolio_positions = getattr(portfolio_state, 'positions', {})
                n_ledger = len(ledger_positions)
                n_portfolio = len(portfolio_positions)
                # Ledger is keyed by market ticker, portfolio may be keyed by asset —
                # exact dict equality is invalid across key spaces.
                # Use count-based sanity: if portfolio reports markets but ledger is
                # empty, the ledger hasn't ingested fills yet (startup lag).
                if n_portfolio > 0 and n_ledger == 0:
                    warnings.append(
                        f"LEDGER_LAG: ledger has 0 positions but portfolio reports "
                        f"{n_portfolio} markets (fills not ingested yet?)"
                    )
                elif n_ledger > 0 and n_portfolio > 0 and abs(n_ledger - n_portfolio) > n_portfolio:
                    # Gross mismatch: ledger has >2× or <0.5× the portfolio count
                    warnings.append(
                        f"POS_COUNT_DRIFT: ledger={n_ledger} markets vs portfolio={n_portfolio} "
                        f"(may indicate missed fills or stale portfolio)"
                    )
    except Exception as exc:
        warnings.append(f"Fills-Portfolio check failed: {exc}")
    
    # 2. Portfolio vs Risk: Within limits? Bankroll match?
    try:
        if portfolio_state is not None:
            total_exposure = getattr(portfolio_state, 'total_exposure', 0)
            # Get the live-calibrated max from risk manager config
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                _rm = get_kalshi_risk()
                max_exposure = _rm._config.max_total_notional_usd if _rm else float('inf')
            except Exception:
                max_exposure = float('inf')
            if total_exposure > max_exposure:
                issues.append(
                    f"RISK_LIMIT_VIOLATION: exposure ${total_exposure:.2f} > limit ${max_exposure:.2f}"
                )
            
            # Check if risk manager's configured limit matches bankroll policy
            try:
                from merid.settings import settings as app_settings
                expected_max_usd = (
                    app_settings.KALSHI_PORTFOLIO_BANKROLL_CENTS
                    * app_settings.KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT
                ) / 100  # cents → USD
                # Get the live-calibrated limit from the risk manager config
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                risk_mgr = get_kalshi_risk()
                actual_max_usd = risk_mgr._config.max_total_notional_usd if risk_mgr else 0.0
                if actual_max_usd > 0 and abs(actual_max_usd - expected_max_usd) > 1.0:  # $1 tolerance
                    warnings.append(
                        f"RISK_POLICY_DRIFT: risk_config max_notional ${actual_max_usd:.2f} "
                        f"!= settings-derived ${expected_max_usd:.2f} "
                        f"(OK if calibrate_from_balance ran)"
                    )
            except Exception:
                pass  # Risk manager not initialized yet — not a problem
    except Exception as exc:
        warnings.append(f"Risk check failed: {exc}")
    
    # 3. Redis Health (if enabled)
    try:
        redis_enabled = os.environ.get("MERID_REDIS_ENABLED", "1").strip() != "0"
        if redis_enabled:
            from merid.infra.redis_resilient import redis_health
            redis_status = redis_health()
            if not redis_status.get("healthy", False):
                if redis_status.get("enabled", False):
                    warnings.append(f"REDIS_DEGRADED: {redis_status.get('reason', 'unhealthy')}")
                else:
                    warnings.append("REDIS_DISABLED: using in-memory fallback")
    except Exception as exc:
        warnings.append(f"Redis check failed: {exc}")
    
    # 4. Fills Ledger Strict Mode (derived fills pending)
    try:
        if fills_ledger is not None:
            summary = fills_ledger.summary()
            if summary.get("strict_mode") and summary.get("derived_fills_pending", 0) > 0:
                pending = summary["derived_fills_pending"]
                warnings.append(f"FILLS_PENDING_CONFIRMATION: {pending} derived fills awaiting REST confirmation")
    except Exception as exc:
        warnings.append(f"Fills strict mode check failed: {exc}")
    
    # Determine overall health
    is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
    
    if issues:
        # Critical issues found - block in live mode
        reason = "CRITICAL: " + "; ".join(issues)
        if warnings:
            reason += " | WARNINGS: " + "; ".join(warnings)
        return False, reason
    elif warnings:
        # Only warnings - healthy but degraded
        reason = "DEGRADED: " + "; ".join(warnings)
        return True, reason
    else:
        return True, ""


# ── Execution Gate Integration ──────────────────────────────────────────────

def check_execution_gate_with_integrity() -> ExecutionGateStatus:
    """Run standard execution gate checks + portfolio integrity.
    
    This is a stricter version that includes cross-subsystem consistency checks.
    Use this for high-confidence trading decisions.
    """
    # First run standard checks
    status = check_execution_gate()
    
    # Run integrity check
    try:
        fills_ledger = None
        portfolio_state = None
        risk_state = None
        
        # Try to get fills ledger
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            fills_ledger = get_fills_ledger()
        except Exception as e:
            logger.debug(f"Failed to get fills_ledger: {e}")
        
        # Try to get risk state
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk = get_kalshi_risk()
            risk_state = risk.state if risk else None
        except Exception as e:
            logger.debug(f"Failed to get risk state: {e}")
        
        # Run integrity check
        from merid.settings import settings
        healthy, reason = check_portfolio_integrity(
            fills_ledger=fills_ledger,
            portfolio_state=portfolio_state,
            risk_state=risk_state,
            settings=settings,
        )
        
        if not healthy:
            # Trigger unified kill switch in live mode for operator visibility
            is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
            if is_live:
                try:
                    from merid.risk.kill_switches import risk_controller
                    risk_controller.trigger_portfolio_integrity(reason)
                except Exception as exc:
                    logger.debug("Failed to trigger portfolio integrity kill switch: %s", exc)
            
            # Add to existing reasons
            status.reasons.append(BlockReason(
                source="portfolio_integrity",
                severity="critical",
                message="Portfolio integrity check failed",
                details=reason,
                hint="Review fills ledger reconciliation and risk state consistency.",
            ))
            status.blocked = True
            status.safe_to_trade = False
            status.gate_state = GateState.BLOCKED.value
            
        elif reason.startswith("DEGRADED"):
            # Degraded but not critical
            status.reasons.append(BlockReason(
                source="portfolio_integrity",
                severity="warning",
                message="Portfolio integrity degraded",
                details=reason.replace("DEGRADED: ", ""),
                hint="Monitor Redis and pending fill confirmations.",
            ))
            if status.gate_state == GateState.CLEAR.value:
                status.gate_state = GateState.LIMITED.value
                
    except Exception as exc:
        logger.debug(f"Portfolio integrity check failed: {exc}")
    
    return status
