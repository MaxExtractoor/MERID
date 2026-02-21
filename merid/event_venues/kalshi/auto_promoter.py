"""Auto Phase Promoter — Autonomous paper → shadow → live promotion engine.

Runs as a background task, periodically evaluating each registered agent's
performance against configurable gates.  When gates pass, it promotes
automatically.  When live performance degrades, it rolls back.

Architecture
------------
- Reads performance metrics from the KalshiAgentGrid's per-agent PaperSession
- Evaluates against DeploymentConfig gates (PF, expectancy, drawdown, trades)
- Promotes PAPER → SHADOW when paper gates pass
- Promotes SHADOW → LIVE when shadow gates pass + min shadow trades met
- Rolls back LIVE/SHADOW → PAPER when auto-rollback thresholds are breached
- Emits Telegram alerts on every transition
- Exposes `status()` for the deployment API

Usage::

    promoter = get_auto_promoter()
    await promoter.start()          # background loop
    await promoter.stop()
    promoter.status()               # dict for API
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.auto_promoter")


# ── Promotion gate result ─────────────────────────────────────────────────

@dataclass
class GateResult:
    """Result of evaluating one promotion gate."""
    passed: bool
    gate: str
    actual: float
    required: float
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "actual": round(self.actual, 4),
            "required": round(self.required, 4),
            "detail": self.detail,
        }


@dataclass
class PromotionEvaluation:
    """Full evaluation result for one agent at one phase transition."""
    agent_name: str
    from_phase: str
    to_phase: str
    timestamp: str
    gates: List[GateResult] = field(default_factory=list)
    promoted: bool = False
    blocked_by: Optional[str] = None

    @property
    def all_passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent_name,
            "from_phase": self.from_phase,
            "to_phase": self.to_phase,
            "timestamp": self.timestamp,
            "gates": [g.to_dict() for g in self.gates],
            "promoted": self.promoted,
            "blocked_by": self.blocked_by,
        }


# ── Auto Promoter ─────────────────────────────────────────────────────────

class AutoPromoter:
    """Background engine that autonomously promotes and rolls back agents.

    Evaluation cadence (default 60 s) is intentionally slow — promotions
    should be deliberate, not reactive to a single good/bad candle.
    """

    def __init__(
        self,
        eval_interval_seconds: float = 60.0,
        on_transition: Optional[Callable[[str, str, str, str], None]] = None,
    ) -> None:
        self._interval = eval_interval_seconds
        self._on_transition = on_transition  # (agent, from, to, reason)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._eval_history: List[PromotionEvaluation] = []
        self._max_history = 500
        self._last_eval_ts: float = 0.0
        self._eval_count: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[auto-promoter] started (interval=%.0fs)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[auto-promoter] stopped")

    # ── Main loop ─────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._evaluate_all()
            except Exception as exc:
                logger.error("[auto-promoter] evaluation error: %s", exc, exc_info=True)
            await asyncio.sleep(self._interval)

    async def _evaluate_all(self) -> None:
        """Evaluate every registered agent and act on results."""
        self._last_eval_ts = time.time()
        self._eval_count += 1

        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
            ctrl = get_deployment_controller()
        except Exception as exc:
            logger.debug("[auto-promoter] deployment controller unavailable: %s", exc)
            return

        # Collect agent metrics from the grid
        agent_metrics = self._collect_agent_metrics()
        if not agent_metrics:
            return

        for agent_name, metrics in agent_metrics.items():
            dep = ctrl.register_agent(agent_name)
            mode = dep.mode

            if mode == AgentMode.PAPER:
                eval_ = self._evaluate_paper_to_shadow(agent_name, metrics, ctrl)
                self._record(eval_)
                if eval_.promoted:
                    logger.info("[auto-promoter] %s: PAPER → SHADOW (auto)", agent_name)

            elif mode == AgentMode.SHADOW:
                # First check for rollback
                rollback_reason = ctrl.check_auto_rollback(
                    agent_name,
                    profit_factor=metrics.get("profit_factor", 0.0),
                    drawdown_pct=metrics.get("max_drawdown_pct", 0.0),
                    consecutive_losses=metrics.get("consecutive_losses", 0),
                )
                if rollback_reason:
                    logger.warning("[auto-promoter] %s: SHADOW → PAPER (auto-rollback: %s)", agent_name, rollback_reason)
                    self._fire_transition(agent_name, "SHADOW", "PAPER", rollback_reason)
                else:
                    eval_ = self._evaluate_shadow_to_live(agent_name, metrics, dep, ctrl)
                    self._record(eval_)
                    if eval_.promoted:
                        logger.info("[auto-promoter] %s: SHADOW → LIVE (auto)", agent_name)

            elif mode == AgentMode.LIVE:
                rollback_reason = ctrl.check_auto_rollback(
                    agent_name,
                    profit_factor=metrics.get("profit_factor", 0.0),
                    drawdown_pct=metrics.get("max_drawdown_pct", 0.0),
                    consecutive_losses=metrics.get("consecutive_losses", 0),
                )
                if rollback_reason:
                    logger.warning("[auto-promoter] %s: LIVE → PAPER (auto-rollback: %s)", agent_name, rollback_reason)
                    self._fire_transition(agent_name, "LIVE", "PAPER", rollback_reason)

    # ── Gate evaluations ──────────────────────────────────────────────

    def _evaluate_paper_to_shadow(
        self,
        agent_name: str,
        metrics: Dict[str, Any],
        ctrl: Any,
    ) -> PromotionEvaluation:
        """Evaluate PAPER → SHADOW gates."""
        cfg = ctrl.config
        ts = datetime.now(timezone.utc).isoformat()
        eval_ = PromotionEvaluation(
            agent_name=agent_name,
            from_phase="PAPER",
            to_phase="SHADOW",
            timestamp=ts,
        )

        gates = [
            GateResult(
                passed=metrics.get("total_trades", 0) >= cfg.min_paper_trades,
                gate="min_paper_trades",
                actual=float(metrics.get("total_trades", 0)),
                required=float(cfg.min_paper_trades),
                detail=f"{metrics.get('total_trades', 0)} trades vs {cfg.min_paper_trades} required",
            ),
            GateResult(
                passed=metrics.get("profit_factor", 0.0) >= cfg.min_profit_factor,
                gate="min_profit_factor",
                actual=metrics.get("profit_factor", 0.0),
                required=cfg.min_profit_factor,
                detail=f"PF {metrics.get('profit_factor', 0.0):.2f} vs {cfg.min_profit_factor:.2f} required",
            ),
            GateResult(
                passed=metrics.get("expectancy_cents", 0.0) >= cfg.min_expectancy_cents,
                gate="min_expectancy_cents",
                actual=metrics.get("expectancy_cents", 0.0),
                required=cfg.min_expectancy_cents,
                detail=f"E[x] {metrics.get('expectancy_cents', 0.0):.1f}¢ vs {cfg.min_expectancy_cents:.1f}¢ required",
            ),
            GateResult(
                passed=metrics.get("max_drawdown_pct", 100.0) <= cfg.max_drawdown_pct,
                gate="max_drawdown_pct",
                actual=metrics.get("max_drawdown_pct", 100.0),
                required=cfg.max_drawdown_pct,
                detail=f"DD {metrics.get('max_drawdown_pct', 0.0):.1f}% vs {cfg.max_drawdown_pct:.1f}% max",
            ),
        ]

        # Optional error rate gate
        if "error_rate_pct" in metrics:
            gates.append(GateResult(
                passed=metrics["error_rate_pct"] <= cfg.max_error_rate_pct,
                gate="max_error_rate_pct",
                actual=metrics["error_rate_pct"],
                required=cfg.max_error_rate_pct,
                detail=f"Error rate {metrics['error_rate_pct']:.1f}% vs {cfg.max_error_rate_pct:.1f}% max",
            ))

        eval_.gates = gates

        if eval_.all_passed:
            readiness = {"ready": True, "details": {g.gate: g.actual for g in gates}}
            ok, reason = ctrl.promote_to_shadow(agent_name, readiness)
            eval_.promoted = ok
            if not ok:
                eval_.blocked_by = reason
            else:
                self._fire_transition(agent_name, "PAPER", "SHADOW", "auto-promotion gates passed")
        else:
            failed = [g for g in gates if not g.passed]
            eval_.blocked_by = "; ".join(g.detail for g in failed)

        return eval_

    def _evaluate_shadow_to_live(
        self,
        agent_name: str,
        metrics: Dict[str, Any],
        dep: Any,
        ctrl: Any,
    ) -> PromotionEvaluation:
        """Evaluate SHADOW → LIVE gates."""
        cfg = ctrl.config
        ts = datetime.now(timezone.utc).isoformat()
        eval_ = PromotionEvaluation(
            agent_name=agent_name,
            from_phase="SHADOW",
            to_phase="LIVE",
            timestamp=ts,
        )

        gates = [
            GateResult(
                passed=dep.shadow_trades >= cfg.min_shadow_trades_before_full_live,
                gate="min_shadow_trades",
                actual=float(dep.shadow_trades),
                required=float(cfg.min_shadow_trades_before_full_live),
                detail=f"{dep.shadow_trades} shadow trades vs {cfg.min_shadow_trades_before_full_live} required",
            ),
            GateResult(
                passed=metrics.get("profit_factor", 0.0) >= cfg.min_profit_factor,
                gate="min_profit_factor",
                actual=metrics.get("profit_factor", 0.0),
                required=cfg.min_profit_factor,
                detail=f"PF {metrics.get('profit_factor', 0.0):.2f} vs {cfg.min_profit_factor:.2f} required",
            ),
            GateResult(
                passed=metrics.get("max_drawdown_pct", 100.0) <= cfg.max_drawdown_pct,
                gate="max_drawdown_pct",
                actual=metrics.get("max_drawdown_pct", 100.0),
                required=cfg.max_drawdown_pct,
                detail=f"DD {metrics.get('max_drawdown_pct', 0.0):.1f}% vs {cfg.max_drawdown_pct:.1f}% max",
            ),
        ]

        eval_.gates = gates

        if eval_.all_passed:
            readiness = {"ready": True, "details": {g.gate: g.actual for g in gates}}
            ok, reason = ctrl.promote_to_live(agent_name, readiness)
            eval_.promoted = ok
            if not ok:
                eval_.blocked_by = reason
            else:
                self._fire_transition(agent_name, "SHADOW", "LIVE", "auto-promotion gates passed")
        else:
            failed = [g for g in gates if not g.passed]
            eval_.blocked_by = "; ".join(g.detail for g in failed)

        return eval_

    # ── Metrics collection ────────────────────────────────────────────

    def _collect_agent_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Pull current performance metrics from the KalshiAgentGrid."""
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            raw = grid.get_performance_summary() if hasattr(grid, "get_performance_summary") else {}
            if not raw:
                return {}
            # Normalise: grid returns {agent_name: {metrics...}}
            result: Dict[str, Dict[str, Any]] = {}
            for name, data in raw.items():
                if isinstance(data, dict):
                    result[name] = data
            return result
        except Exception as exc:
            logger.debug("[auto-promoter] metrics collection failed: %s", exc)
            return {}

    # ── Helpers ───────────────────────────────────────────────────────

    def _record(self, eval_: PromotionEvaluation) -> None:
        self._eval_history.append(eval_)
        if len(self._eval_history) > self._max_history:
            self._eval_history = self._eval_history[-self._max_history:]

    def _fire_transition(
        self, agent_name: str, from_phase: str, to_phase: str, reason: str
    ) -> None:
        if self._on_transition:
            try:
                self._on_transition(agent_name, from_phase, to_phase, reason)
            except Exception as exc:
                logger.debug("[auto-promoter] transition callback error: %s", exc)

    # ── Public API ────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Status dict for the deployment API."""
        recent = [e.to_dict() for e in self._eval_history[-20:]]
        promotions = [e for e in self._eval_history if e.promoted]
        return {
            "running": self._running,
            "eval_interval_seconds": self._interval,
            "eval_count": self._eval_count,
            "last_eval_ts": self._last_eval_ts,
            "last_eval_ago_seconds": round(time.time() - self._last_eval_ts, 1) if self._last_eval_ts else None,
            "total_promotions": len(promotions),
            "recent_evaluations": recent,
        }

    def recent_promotions(self, limit: int = 10) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._eval_history if e.promoted][-limit:]


# ── Singleton ─────────────────────────────────────────────────────────────

_promoter: Optional[AutoPromoter] = None


def get_auto_promoter(
    eval_interval_seconds: float = 60.0,
) -> AutoPromoter:
    """Return the module-level AutoPromoter singleton."""
    global _promoter
    if _promoter is None:
        _promoter = AutoPromoter(eval_interval_seconds=eval_interval_seconds)
    return _promoter
