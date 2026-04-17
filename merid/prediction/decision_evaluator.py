"""Decision Evaluator — centralised trade-vs-hold pipeline.

Replaces scattered boolean checks throughout ``trading_agent._run_cycle_body``
with a single function that maps pipeline state → ``Decision``.

The evaluator is **stateless** — all context is passed in.  It never reads
global singletons; the caller (``KalshiTradingAgent``) injects them.

Usage in the agent cycle::

    from merid.prediction.decision_evaluator import evaluate_cycle_decision, CycleContext

    ctx = CycleContext(...)
    decision = evaluate_cycle_decision(ctx)
    if decision.action == DecisionAction.TRADE:
        await self._execute_signal(...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.prediction.decision import (
    Decision,
    DecisionAction,
    DecisionTimer,
    HoldReason,
)
from merid.prediction.trade_hold_config import TradeHoldConfig, get_trade_hold_config

from utils.logger import get_logger

logger = get_logger("merid.prediction.decision_evaluator")


@dataclass
class CycleContext:
    """Everything the evaluator needs to decide for one market in one cycle.

    Populated by ``KalshiTradingAgent`` before calling ``evaluate_cycle_decision``.
    """
    # Identity
    agent_name: str = ""
    cycle_number: int = 0
    market_id: Optional[str] = None

    # Lifecycle
    lifecycle_state: str = "active"     # LifecycleState value
    agent_enabled: bool = True
    kill_switch_active: bool = False
    kill_switch_reason: str = ""

    # Session
    session_allowed: bool = True
    session_block_reason: str = ""

    # Markets resolved?
    has_resolved_markets: bool = False

    # Entry window
    in_entry_window: bool = True
    is_new_entry: bool = True
    seconds_to_expiry: Optional[float] = None

    # Strategy signal
    signal_action: str = "no_action"      # SignalAction.value
    signal_reason: str = ""
    signal_contracts: int = 0
    signal_edge: Optional[float] = None
    signal_phase: Optional[str] = None

    # Consensus
    consensus_status: Optional[str] = None   # "ready", "forming", "conflicted", None
    consensus_direction_matches: bool = True
    consensus_bypassed: bool = False
    solo_seconds: float = 0.0
    swarm_degraded: bool = False
    solo_trades_this_session: int = 0

    # Risk check
    risk_allowed: bool = True
    risk_reason: str = ""
    risk_action: str = "allow"    # RiskAction.value

    # Order limit
    orders_this_window: int = 0
    max_orders_per_window: int = 10

    # Config (injected)
    config: Optional[TradeHoldConfig] = None

    # Timer
    timer: Optional[DecisionTimer] = None


def _signal_is_actionable(action_str: str) -> bool:
    return action_str not in ("no_action", "hold")


def _classify_signal_hold(reason: str) -> HoldReason:
    """Map strategy NO_ACTION reason string to a specific HoldReason."""
    r = (reason or "").lower()
    # pm_spot_gate must be checked before generic "stale" to avoid false match
    if "pm_spot_gate" in r or "missing_or_stale_spot" in r:
        return HoldReason.PM_SPOT_GATE
    if "stale" in r:
        return HoldReason.STALE_DATA
    if "expiry unknown" in r or "unknown expiry" in r:
        return HoldReason.NO_EDGE
    if "not tradeable" in r or "not trading" in r:
        return HoldReason.NO_EDGE
    if "spot_strike" in r and "veto" in r:
        return HoldReason.SPOT_STRIKE_VETO
    if "liquidity" in r:
        return HoldReason.LIQUIDITY_GUARD
    if "conviction" in r and ("veto" in r or "low" in r):
        return HoldReason.CONVICTION_VETO
    if "confidence" in r and "below" in r:
        return HoldReason.CONFIDENCE_TOO_LOW
    if "edge" in r and ("below" in r or "threshold" in r):
        return HoldReason.EDGE_BELOW_THRESHOLD
    if "no actionable edge" in r:
        return HoldReason.NO_EDGE
    return HoldReason.NO_EDGE


def _classify_risk_hold(risk_action: str, reason: str) -> HoldReason:
    """Map risk check rejection to HoldReason."""
    if risk_action == "halt":
        return HoldReason.RISK_HALT
    if risk_action == "reduce_size":
        return HoldReason.RISK_REDUCE
    r = (reason or "").lower()
    if "rate limit" in r:
        return HoldReason.RATE_LIMIT
    return HoldReason.RISK_LIMIT


def _build_config_snapshot(cfg: TradeHoldConfig) -> Dict[str, Any]:
    """Compact config snapshot for decision logging."""
    return {
        "warmup_min_s": cfg.warmup.min_seconds,
        "warmup_max_s": cfg.warmup.max_seconds,
        "min_edge_early": str(cfg.strategy.min_edge_early),
        "min_confidence": str(cfg.strategy.min_confidence),
        "solo_wait_s": cfg.consensus.solo_wait_seconds,
        "solo_cap": cfg.consensus.solo_trades_cap,
    }


def evaluate_cycle_decision(ctx: CycleContext) -> Decision:
    """Run the full trade-vs-hold pipeline and return a single Decision.

    Pipeline stages (earliest exit wins):

    1. Config disabled / agent disabled
    2. Kill switch
    3. Session guard
    4. Warmup lifecycle
    5. No markets resolved
    6. Order window limit
    7. Entry window / expiry proximity
    8. Strategy signal (NO_ACTION → HOLD)
    9. Consensus gates
    10. Risk pre-trade check
    11. All passed → TRADE

    Every HOLD has a mandatory reason.  There are **no silent holds**.
    """
    cfg = ctx.config or get_trade_hold_config()
    timer = ctx.timer or DecisionTimer()
    _elapsed = lambda: timer.elapsed_ms()
    _cfg_snap = lambda: _build_config_snapshot(cfg) if cfg.logging.log_config_snapshot else {}

    # ── 1. Config / agent disabled ────────────────────────────────────
    if not cfg.enabled:
        return Decision.hold(
            HoldReason.CONFIG_DISABLED,
            "trade_hold pipeline disabled in config",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            market_id=ctx.market_id,
            config_snapshot=_cfg_snap(),
            elapsed_ms=_elapsed(),
        )

    if not ctx.agent_enabled:
        return Decision.hold(
            HoldReason.CONFIG_DISABLED,
            "agent disabled (enabled=false or paused)",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            market_id=ctx.market_id,
            elapsed_ms=_elapsed(),
        )

    # ── 2. Kill switch ────────────────────────────────────────────────
    if ctx.kill_switch_active:
        return Decision.hold(
            HoldReason.KILL_SWITCH,
            f"kill switch active: {ctx.kill_switch_reason}",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            market_id=ctx.market_id,
            elapsed_ms=_elapsed(),
        )

    # ── 3. Session guard ──────────────────────────────────────────────
    if not ctx.session_allowed:
        return Decision.hold(
            HoldReason.SESSION_CLOSED,
            ctx.session_block_reason or "outside trading session",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            elapsed_ms=_elapsed(),
        )

    # ── 4. Warmup ─────────────────────────────────────────────────────
    if ctx.lifecycle_state == "warming_up":
        return Decision.hold(
            HoldReason.WARMUP,
            f"agent in WARMING_UP lifecycle (cycle {ctx.cycle_number})",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            market_id=ctx.market_id,
            elapsed_ms=_elapsed(),
        )

    # ── 5. No markets ─────────────────────────────────────────────────
    if not ctx.has_resolved_markets:
        return Decision.hold(
            HoldReason.NO_MARKETS,
            "no markets resolved for this agent/cycle",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            elapsed_ms=_elapsed(),
        )

    # ── 6. Order window limit ─────────────────────────────────────────
    if ctx.orders_this_window >= ctx.max_orders_per_window:
        return Decision.hold(
            HoldReason.ORDER_LIMIT,
            f"window order limit reached ({ctx.orders_this_window}/{ctx.max_orders_per_window})",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            market_id=ctx.market_id,
            elapsed_ms=_elapsed(),
        )

    # ── 7. Entry window / expiry proximity ────────────────────────────
    if ctx.is_new_entry:
        guard_s = cfg.entry_window.expiry_proximity_guard_seconds
        if ctx.seconds_to_expiry is not None and ctx.seconds_to_expiry <= guard_s:
            return Decision.hold(
                HoldReason.EXPIRY_PROXIMITY,
                f"expiry proximity guard: {ctx.seconds_to_expiry:.0f}s ≤ {guard_s:.0f}s",
                agent_name=ctx.agent_name,
                cycle_number=ctx.cycle_number,
                market_id=ctx.market_id,
                elapsed_ms=_elapsed(),
            )
        if not ctx.in_entry_window:
            return Decision.hold(
                HoldReason.OUTSIDE_ENTRY_WINDOW,
                "market outside configured entry window",
                agent_name=ctx.agent_name,
                cycle_number=ctx.cycle_number,
                market_id=ctx.market_id,
                elapsed_ms=_elapsed(),
            )

    # ── 8. Strategy signal ────────────────────────────────────────────
    if not _signal_is_actionable(ctx.signal_action):
        reason = _classify_signal_hold(ctx.signal_reason)
        return Decision.hold(
            reason,
            ctx.signal_reason or "strategy returned NO_ACTION",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            market_id=ctx.market_id,
            signal_summary={
                "action": ctx.signal_action,
                "edge": ctx.signal_edge,
                "phase": ctx.signal_phase,
                "reason": (ctx.signal_reason or "")[:300],
            },
            elapsed_ms=_elapsed(),
        )

    # ── 9. Consensus gates ────────────────────────────────────────────
    if not ctx.consensus_bypassed:
        cs = ctx.consensus_status

        if cs == "ready":
            if not ctx.consensus_direction_matches:
                return Decision.hold(
                    HoldReason.CONSENSUS_DIRECTION_MISMATCH,
                    "signal direction != consensus direction",
                    agent_name=ctx.agent_name,
                    cycle_number=ctx.cycle_number,
                    market_id=ctx.market_id,
                    signal_summary={"action": ctx.signal_action, "edge": ctx.signal_edge},
                    elapsed_ms=_elapsed(),
                )

        elif cs == "forming":
            return Decision.hold(
                HoldReason.CONSENSUS_FORMING,
                "swarm consensus still forming",
                agent_name=ctx.agent_name,
                cycle_number=ctx.cycle_number,
                market_id=ctx.market_id,
                elapsed_ms=_elapsed(),
            )

        elif cs == "conflicted":
            return Decision.hold(
                HoldReason.CONSENSUS_CONFLICTED,
                "swarm agents disagree (conflicted)",
                agent_name=ctx.agent_name,
                cycle_number=ctx.cycle_number,
                market_id=ctx.market_id,
                elapsed_ms=_elapsed(),
            )

        elif cs is None:
            # No consensus at all
            max_solo = cfg.consensus.solo_wait_seconds
            if ctx.solo_seconds < max_solo:
                return Decision.hold(
                    HoldReason.SOLO_WINDOW,
                    f"no consensus yet ({ctx.solo_seconds:.0f}s < {max_solo:.0f}s threshold)",
                    agent_name=ctx.agent_name,
                    cycle_number=ctx.cycle_number,
                    market_id=ctx.market_id,
                    elapsed_ms=_elapsed(),
                )
            # Degraded checks
            if ctx.solo_trades_this_session >= cfg.consensus.solo_trades_cap:
                return Decision.hold(
                    HoldReason.SOLO_CAP_REACHED,
                    f"solo trade cap ({cfg.consensus.solo_trades_cap}) reached in degraded mode",
                    agent_name=ctx.agent_name,
                    cycle_number=ctx.cycle_number,
                    market_id=ctx.market_id,
                    elapsed_ms=_elapsed(),
                )

    # ── 10. Risk pre-trade check ──────────────────────────────────────
    if not ctx.risk_allowed:
        reason = _classify_risk_hold(ctx.risk_action, ctx.risk_reason)
        return Decision.hold(
            reason,
            ctx.risk_reason or "risk check rejected",
            agent_name=ctx.agent_name,
            cycle_number=ctx.cycle_number,
            market_id=ctx.market_id,
            risk_summary={
                "action": ctx.risk_action,
                "reason": (ctx.risk_reason or "")[:300],
            },
            signal_summary={
                "action": ctx.signal_action,
                "edge": ctx.signal_edge,
                "contracts": ctx.signal_contracts,
            },
            elapsed_ms=_elapsed(),
        )

    # ── 11. All checks passed → TRADE ────────────────────────────────
    return Decision.trade(
        market_id=ctx.market_id or "",
        agent_name=ctx.agent_name,
        cycle_number=ctx.cycle_number,
        detail="all_checks_passed",
        signal_summary={
            "action": ctx.signal_action,
            "edge": ctx.signal_edge,
            "contracts": ctx.signal_contracts,
            "phase": ctx.signal_phase,
        },
        risk_summary={
            "action": ctx.risk_action,
            "reason": ctx.risk_reason[:200] if ctx.risk_reason else "allowed",
        },
        config_snapshot=_cfg_snap(),
        elapsed_ms=_elapsed(),
    )
