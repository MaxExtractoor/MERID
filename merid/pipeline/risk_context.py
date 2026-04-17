"""RiskContext — System-state struct that consensus and risk must respect.

Aggregates caps, CQI, drawdown, and exposure from ExecutionGuard,
OperatorSession, paper engine, and DrawdownGovernor into a single
read-only snapshot.  Consensus uses this as *constraints*, not targets.

Usage:
    ctx = build_risk_context()
    # Feed into GlobalRiskManager or ConsensusCoordinatorAgent
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.pipeline.risk_context")


@dataclass
class DomainRiskSnapshot:
    """Per-domain slice of the risk context."""
    domain: str
    cqi_score: float = 0.5              # Latest CQI (0–1)
    cap_remaining_usd: float = 0.0      # Remaining daily notional
    cap_max_usd: float = 0.0            # Max daily notional
    cap_used_pct: float = 0.0           # cap usage ratio (0–1)
    kill_switch: bool = False
    enabled: bool = True
    exposure_usd: float = 0.0           # Current notional exposure
    daily_loss_usd: float = 0.0         # Realized loss today

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "cqi_score": round(self.cqi_score, 4),
            "cap_remaining_usd": round(self.cap_remaining_usd, 2),
            "cap_max_usd": round(self.cap_max_usd, 2),
            "cap_used_pct": round(self.cap_used_pct, 4),
            "kill_switch": self.kill_switch,
            "enabled": self.enabled,
            "exposure_usd": round(self.exposure_usd, 2),
            "daily_loss_usd": round(self.daily_loss_usd, 2),
        }


@dataclass
class RiskContext:
    """Immutable snapshot of system risk state.

    Consumed by:
    - GlobalRiskManager.check_proposal()  → scale order sizes
    - ConsensusCoordinatorAgent.aggregate() → adjust approval threshold
    - TradeRouter (indirectly via the above)

    NOT persisted itself — it's computed on demand from existing stores.
    """
    timestamp: float = 0.0

    # Global state
    global_kill_switch: bool = False
    total_capital_usd: float = 50000.0
    portfolio_exposure_usd: float = 0.0  # Sum of all domain exposures
    portfolio_exposure_pct: float = 0.0  # exposure / total capital

    # Drawdown
    drawdown_pct: float = 0.0            # Current drawdown from peak (0–1)
    drawdown_level: str = "normal"       # normal / caution / warning / critical

    # Average CQI across all domains
    avg_cqi: float = 0.5

    # Per-domain snapshots
    domains: Dict[str, DomainRiskSnapshot] = field(default_factory=dict)

    # Session activity
    session_elapsed_seconds: float = 0.0
    total_executions: int = 0
    total_blocks: int = 0
    total_usd_executed: float = 0.0

    # Derived adjustment factors (0.0–1.0)
    size_scale_factor: float = 1.0       # Multiply order sizes by this
    approval_threshold_boost: float = 0.0 # Add this to consensus threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "global_kill_switch": self.global_kill_switch,
            "total_capital_usd": round(self.total_capital_usd, 2),
            "portfolio_exposure_usd": round(self.portfolio_exposure_usd, 2),
            "portfolio_exposure_pct": round(self.portfolio_exposure_pct, 4),
            "drawdown_pct": round(self.drawdown_pct, 4),
            "drawdown_level": self.drawdown_level,
            "avg_cqi": round(self.avg_cqi, 4),
            "domains": {k: v.to_dict() for k, v in self.domains.items()},
            "session_elapsed_seconds": round(self.session_elapsed_seconds, 1),
            "total_executions": self.total_executions,
            "total_blocks": self.total_blocks,
            "total_usd_executed": round(self.total_usd_executed, 2),
            "size_scale_factor": round(self.size_scale_factor, 4),
            "approval_threshold_boost": round(self.approval_threshold_boost, 4),
        }

    def domain_snapshot(self, domain: str) -> Optional[DomainRiskSnapshot]:
        return self.domains.get(domain)


# ── Builder ────────────────────────────────────────────────────────────

def build_risk_context() -> RiskContext:
    """Build a RiskContext snapshot from live system singletons.

    Pulls from:
    - ExecutionGuard  → CQI, caps, kill switch
    - OperatorSession → execution/block counts, CQI history
    - GlobalRiskManager → domain exposure, daily loss
    - DrawdownGovernor → drawdown % and level
    - PaperTradingEngine → portfolio value
    """
    ctx = RiskContext(timestamp=time.time())

    # ── ExecutionGuard ────────────────────────────────────────────────
    try:
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        ctx.global_kill_switch = guard.kill_switch_active

        cqi_values = []
        for domain_name, cap in guard._domain_caps.items():
            snap = DomainRiskSnapshot(domain=domain_name)
            snap.cqi_score = guard.get_cqi(domain_name)
            cqi_values.append(snap.cqi_score)
            cap.reset_if_new_day()
            snap.cap_max_usd = cap.max_daily_notional_usd
            snap.cap_remaining_usd = cap.remaining_notional()
            snap.cap_used_pct = (
                1.0 - (snap.cap_remaining_usd / snap.cap_max_usd)
                if snap.cap_max_usd > 0 else 0.0
            )
            snap.kill_switch = cap.kill_switch
            snap.enabled = cap.enabled
            ctx.domains[domain_name] = snap

        ctx.avg_cqi = sum(cqi_values) / len(cqi_values) if cqi_values else 0.5
    except Exception as exc:
        logger.debug(f"risk_context_guard_error: {exc}")

    # ── GlobalRiskManager → domain exposure + daily loss ──────────────
    try:
        from merid.pipeline.risk_manager import get_global_risk_manager
        rm = get_global_risk_manager()
        ctx.total_capital_usd = float(rm.total_capital_usd)

        from merid.pipeline.proposal import TradeDomain
        for td in TradeDomain:
            dname = td.value
            snap = ctx.domains.get(dname) or DomainRiskSnapshot(domain=dname)
            snap.exposure_usd = float(rm.domain_notional(dname))
            snap.daily_loss_usd = float(rm.domain_daily_loss(dname))
            ctx.domains[dname] = snap

        ctx.portfolio_exposure_usd = float(rm.portfolio_notional())
        ctx.portfolio_exposure_pct = (
            ctx.portfolio_exposure_usd / ctx.total_capital_usd
            if ctx.total_capital_usd > 0 else 0.0
        )
    except Exception as exc:
        logger.debug(f"risk_context_rm_error: {exc}")

    # ── DrawdownGovernor ──────────────────────────────────────────────
    try:
        from treasury import get_drawdown_governor
        gov = get_drawdown_governor()
        status = gov.get_status()
        ctx.drawdown_pct = status.get("current_drawdown_pct", 0.0)
        ctx.drawdown_level = status.get("level", "normal")
    except Exception as exc:
        logger.debug(f"risk_context_drawdown_error: {exc}")

    # ── OperatorSession ───────────────────────────────────────────────
    try:
        from merid.tick_log import get_operator_session
        session = get_operator_session()
        summary = session.summary()
        ctx.session_elapsed_seconds = summary.get("elapsed_seconds", 0.0)
        ctx.total_executions = sum(summary.get("domain_executions", {}).values())
        ctx.total_blocks = sum(summary.get("domain_blocks", {}).values())
        ctx.total_usd_executed = sum(summary.get("domain_usd_executed", {}).values())
    except Exception as exc:
        logger.debug(f"risk_context_session_error: {exc}")

    # ── Compute derived adjustment factors ────────────────────────────
    ctx.size_scale_factor = _compute_size_scale(ctx)
    ctx.approval_threshold_boost = _compute_threshold_boost(ctx)

    return ctx


def _compute_size_scale(ctx: RiskContext) -> float:
    """Compute a multiplicative scale factor for order sizing.

    Reduces size when:
    - CQI is degraded (below 0.65 → linear scale-down to 0.25 at 0.35)
    - Drawdown is elevated (caution → 0.75, warning → 0.50, critical → 0.25)
    - Cap usage is high (>80% used → proportional reduction)
    """
    factor = 1.0

    # CQI-based reduction (mirrors ExecutionGuard throttle)
    if ctx.avg_cqi < 0.65:
        if ctx.avg_cqi <= 0.35:
            factor = min(factor, 0.25)
        else:
            raw = (ctx.avg_cqi - 0.35) / 0.30  # 0..1 over [0.35, 0.65]
            factor = min(factor, max(0.25, raw))

    # Drawdown-based reduction
    drawdown_scales = {
        "caution": 0.75,
        "warning": 0.50,
        "critical": 0.25,
        "emergency": 0.0,
    }
    dd_factor = drawdown_scales.get(ctx.drawdown_level, 1.0)
    factor = min(factor, dd_factor)

    # Exposure-based reduction (>80% of capital deployed → start reducing)
    if ctx.portfolio_exposure_pct > 0.80:
        excess = (ctx.portfolio_exposure_pct - 0.80) / 0.20  # 0..1 over [80%, 100%]
        factor = min(factor, max(0.10, 1.0 - excess))

    return round(max(0.0, min(1.0, factor)), 4)


def _compute_threshold_boost(ctx: RiskContext) -> float:
    """Compute an additive boost to the consensus approval threshold.

    Raises the bar when system state is stressed:
    - Poor CQI → +0.10
    - Drawdown elevated → +0.05 to +0.15
    - High cap usage → +0.05
    """
    boost = 0.0

    # CQI below healthy → raise threshold
    if ctx.avg_cqi < 0.50:
        boost += 0.10
    elif ctx.avg_cqi < 0.65:
        boost += 0.05

    # Drawdown levels
    drawdown_boosts = {
        "caution": 0.05,
        "warning": 0.10,
        "critical": 0.15,
        "emergency": 0.20,
    }
    boost += drawdown_boosts.get(ctx.drawdown_level, 0.0)

    # High capital utilization
    if ctx.portfolio_exposure_pct > 0.80:
        boost += 0.05

    return round(min(boost, 0.30), 4)  # Cap at +0.30


# ── Singleton cache (refreshed per-call, no stale data) ───────────────

def get_risk_context() -> RiskContext:
    """Build and return a fresh RiskContext snapshot."""
    return build_risk_context()
