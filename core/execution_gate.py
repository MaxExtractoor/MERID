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

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger("core.execution_gate")


class GateState(str, Enum):
    """Fine-grained execution gate state."""
    CLEAR = "clear"        # all checks pass — full trading
    LIMITED = "limited"    # warnings only — reduce/close positions OK, no new risk
    BLOCKED = "blocked"    # critical issues — no execution at all


# ── Remediation hints per source ──────────────────────────────────────
REMEDIATION_HINTS: dict[str, str] = {
    "kill_switch": "Reset via Mode & Safety panel after investigating the trigger cause.",
    "reconciliation": "Wait for the next reconciliation cycle or trigger a manual run from System settings.",
    "price_feed": "Check venue connectivity and data source health in Venue Health Grid.",
    "pnl_consistency": "Inspect PnL sources in the Consistency widget; look for missed fills or stale equity data.",
    "dependency_health": "Check /api/v1/dependencies/health for detailed subsystem status. Verify Kalshi WebSocket connection and market catalog are healthy.",
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


def _is_kalshi_demo_mode() -> bool:
    """Return True when running in Kalshi demo/paper mode.

    In this mode, reconciliation and PnL consistency checks reflect
    the crypto paper-trading subsystem which is irrelevant to Kalshi
    execution. Their severity is downgraded from critical → warning
    so they don't block the Kalshi trading path.
    """
    try:
        from merid.settings import settings
        return settings.KALSHI_USE_DEMO
    except Exception:
        import os
        return os.environ.get("KALSHI_USE_DEMO", "false").lower() in ("true", "1", "yes")


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
        logger.debug("Kill switch check failed: %s", exc)

    # ── 2. Reconciliation ───────────────────────────────────────────
    # In Kalshi demo mode, reconciliation discrepancies come from the
    # crypto paper matrix — downgrade to warning so they don't block.
    recon_severity = "warning" if kalshi_demo else "critical"
    try:
        from trading.reconciliation import has_critical_discrepancies, get_last_report, _has_ever_completed
        if has_critical_discrepancies():
            report = get_last_report()
            if not _has_ever_completed:
                reasons.append(BlockReason(
                    source="reconciliation",
                    severity=recon_severity,
                    message="Reconciliation has never completed",
                    details="Execution gated until first reconciliation run" if not kalshi_demo else "Crypto paper reconciliation pending (non-blocking in Kalshi mode)",
                    hint=REMEDIATION_HINTS["reconciliation"],
                ))
            elif report and not report.all_ok:
                reasons.append(BlockReason(
                    source="reconciliation",
                    severity=recon_severity,
                    message="Reconciliation found discrepancies",
                    details=f"{len([c for c in report.checks if c.status != 'OK'])} checks failed" + (" (crypto paper — non-blocking)" if kalshi_demo else ""),
                    hint=REMEDIATION_HINTS["reconciliation"],
                ))
            else:
                reasons.append(BlockReason(
                    source="reconciliation",
                    severity=recon_severity,
                    message="Reconciliation status unknown",
                    hint=REMEDIATION_HINTS["reconciliation"],
                ))
    except Exception as exc:
        logger.debug("Reconciliation check failed: %s", exc)

    # ── 2b. Kalshi venue reconciliation ──────────────────────────────
    try:
        from merid.reconciliation import has_critical_discrepancies as kalshi_has_critical
        if kalshi_has_critical():
            reasons.append(BlockReason(
                source="reconciliation",
                severity="critical",
                message="Kalshi venue reconciliation found critical discrepancies",
                details="Position or order mismatch between MERID and Kalshi venue",
                hint=REMEDIATION_HINTS["reconciliation"],
            ))
    except Exception as exc:
        logger.debug("Kalshi venue reconciliation check skipped: %s", exc)

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
        logger.debug("Price feed staleness check failed: %s", exc)

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
        logger.debug("PnL consistency check failed: %s", exc)

    # ── 5. Dependency health (WebSocket, catalog) ───────────────────
    try:
        from merid.monitoring.dependency_health import is_trading_ready
        ready, dep_issues = is_trading_ready()
        if not ready:
            for issue in dep_issues:
                reasons.append(BlockReason(
                    source="dependency_health",
                    severity="critical",
                    message=issue,
                    details="Critical subsystems must be healthy before trading",
                    hint="Check /api/v1/dependencies/health endpoint for detailed status",
                ))
    except Exception as exc:
        logger.debug("Dependency health check failed: %s", exc)

    has_critical = any(r.severity == "critical" for r in reasons)
    has_warning = any(r.severity == "warning" for r in reasons)
    blocked = has_critical

    if has_critical:
        gate_state = GateState.BLOCKED.value
    elif has_warning:
        gate_state = GateState.LIMITED.value
    else:
        gate_state = GateState.CLEAR.value

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
        except Exception:
            pass
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
        except Exception:
            pass

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


# ── Price feed staleness config ─────────────────────────────────────

@dataclass
class SymbolGroupConfig:
    """Staleness threshold for a group of symbols."""
    name: str
    symbols: set
    threshold_seconds: float
    critical: bool  # if True, stale symbols in this group block execution


# Default symbol groups — override via set_staleness_config()
_staleness_config: List["SymbolGroupConfig"] = [
    SymbolGroupConfig(
        name="major_crypto",
        symbols={"BTC/USDT", "ETH/USDT", "SOL/USDT", "BTC-USD", "ETH-USD", "SOL-USD"},
        threshold_seconds=60,
        critical=True,
    ),
    SymbolGroupConfig(
        name="alt_crypto",
        symbols={"AVAX/USDT", "ADA/USDT", "DOT/USDT", "ATOM/USDT", "NEAR/USDT",
                 "LINK/USDT", "UNI/USDT", "AAVE/USDT", "DOGE/USDT"},
        threshold_seconds=120,
        critical=False,
    ),
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
    """Compare PnL across paper engine and equity series.

    Returns:
        dict with keys: consistent, max_divergence_usd, threshold_usd, sources
    """
    sources = {}

    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        total_pnl = 0.0
        for _uid, portfolio in engine.portfolios.items():
            total_pnl += portfolio.total_pnl
        sources["paper_engine"] = round(total_pnl, 2)
    except Exception:
        pass

    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        if session.is_active:
            kalshi_pnl = sum(
                iv.net_pnl_cents / 100.0
                for iv in session._intervals.values()
                if iv.total_trades > 0
            )
            sources["kalshi_session"] = round(kalshi_pnl, 2)
    except Exception:
        pass

    try:
        from merid.risk.kill_switches import risk_controller
        sources["risk_controller"] = round(risk_controller._daily_pnl, 2)
    except Exception:
        pass

    try:
        from web.api.operator import _equity_buffer
        if _equity_buffer:
            sources["equity_series"] = _equity_buffer[-1].get("pnl", 0)
    except Exception:
        pass

    vals = list(sources.values())
    max_divergence = (max(vals) - min(vals)) if len(vals) >= 2 else 0.0
    consistent = max_divergence <= PNL_CONSISTENCY_THRESHOLD

    return {
        "consistent": consistent,
        "max_divergence_usd": round(max_divergence, 2),
        "threshold_usd": PNL_CONSISTENCY_THRESHOLD,
        "sources": sources,
    }
