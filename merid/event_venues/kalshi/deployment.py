"""Live Deployment Controller — Config-driven paper → live switching.

Manages the promotion of individual agents from PAPER to LIVE mode with:
- Per-agent mode tracking (PAPER / LIVE / SHADOW)
- Readiness gate enforcement before promotion
- Shadow mode: run live + paper side-by-side for comparison
- Automatic rollback on degradation alerts
- Audit log of all mode transitions

Usage::

    ctrl = DeploymentController()
    ctrl.promote_to_live("BTC_HOURLY", readiness_verdict)
    ctrl.enable_shadow("ETH_HOURLY")
    ctrl.rollback("BTC_HOURLY", reason="PF collapsed")
    status = ctrl.status()
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

def _state_file_path() -> Path:
    """Resolve persistence path at call time so tests can set MERID_DEPLOYMENT_STATE."""
    return Path(os.environ.get(
        "MERID_DEPLOYMENT_STATE",
        Path(__file__).parent.parent.parent.parent / "data" / "deployment_state.json",
    ))

logger = get_logger("merid.event_venues.kalshi.deployment")


class AgentMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    SHADOW = "SHADOW"   # Live orders + parallel paper tracking
    HALTED = "HALTED"   # Demoted, no orders


@dataclass
class AgentDeployment:
    """Deployment state for a single agent."""
    agent_name: str
    mode: AgentMode = AgentMode.PAPER
    promoted_at: Optional[str] = None
    rollback_count: int = 0
    last_rollback_reason: Optional[str] = None
    last_rollback_at: Optional[str] = None
    live_trades: int = 0
    shadow_trades: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "mode": self.mode.value,
            "promoted_at": self.promoted_at,
            "rollback_count": self.rollback_count,
            "last_rollback_reason": self.last_rollback_reason,
            "last_rollback_at": self.last_rollback_at,
            "live_trades": self.live_trades,
            "shadow_trades": self.shadow_trades,
        }


@dataclass
class DeploymentConfig:
    """Configuration for deployment controller."""
    # Readiness gates
    # DISABLED FOR LIVE TRADING (2026-05-14): Set to False to allow direct promotion without paper trading requirements
    require_readiness_check: bool = False
    min_paper_trades: int = 200
    min_profit_factor: float = 1.4
    min_expectancy_cents: float = 5.0
    max_drawdown_pct: float = 12.0
    max_error_rate_pct: float = 5.0

    # Shadow mode
    min_shadow_trades_before_full_live: int = 100
    min_shadow_hours_before_full_live: float = 48.0  # Minimum wall-clock hours in SHADOW

    # Auto-rollback thresholds
    auto_rollback_on_pf_below: float = 0.9
    auto_rollback_on_drawdown_above_pct: float = 15.0
    auto_rollback_on_consecutive_losses: int = 10

    # Max simultaneous live agents
    # INCREASED FOR LIVE TRADING (2026-05-14): Set to 10 to allow all 5 crypto agents (BTC/ETH/SOL/XRP/DOGE) to run live simultaneously
    max_live_agents: int = 10

    # Operator acknowledgement required after restart before re-promoting to LIVE
    # DISABLED FOR LIVE TRADING (2026-05-14): Set to False to allow automatic re-promotion after restart
    require_operator_ack_after_restart: bool = False

    # Require backtest validate_before_lift() before SHADOW → LIVE (fail-closed in prod)
    # DISABLED FOR LIVE TRADING (2026-05-14): Set to False to allow direct PAPER → LIVE promotion
    require_backtest_lift_gate: bool = False


DEFAULT_DEPLOYMENT_CONFIG = DeploymentConfig()


@dataclass
class TransitionLog:
    """Audit log entry for a mode transition."""
    ts: str
    agent_name: str
    from_mode: str
    to_mode: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "agent": self.agent_name,
            "from": self.from_mode,
            "to": self.to_mode,
            "reason": self.reason,
        }


class DeploymentController:
    """Manages paper → shadow → live promotion and rollback."""

    _MAX_LOG = 200

    def __init__(self, config: Optional[DeploymentConfig] = None) -> None:
        self._config = config or DEFAULT_DEPLOYMENT_CONFIG
        self._agents: Dict[str, AgentDeployment] = {}
        self._log: List[TransitionLog] = []
        self._restart_pending_ack: set = set()  # agent names awaiting operator ack after restart
        self._load_persisted_state()

    @property
    def config(self) -> DeploymentConfig:
        return self._config

    # ── Agent registration ───────────────────────────────────────────

    def register_agent(self, agent_name: str) -> AgentDeployment:
        """Register an agent (starts in PAPER mode unless persisted state exists)."""
        if agent_name not in self._agents:
            self._agents[agent_name] = AgentDeployment(agent_name=agent_name)
            # New registration after a restart: if it was previously LIVE it will
            # have been loaded from persisted state already; fresh agents start PAPER.
        return self._agents[agent_name]

    def get_mode(self, agent_name: str) -> AgentMode:
        """Get current mode for an agent."""
        dep = self._agents.get(agent_name)
        return dep.mode if dep else AgentMode.PAPER

    def is_live(self, agent_name: str) -> bool:
        return self.get_mode(agent_name) in (AgentMode.LIVE, AgentMode.SHADOW)

    # ── Promotion ────────────────────────────────────────────────────

    def acknowledge_restart(self, agent_name: str) -> None:
        """Operator acknowledgement that a previously-live agent may be re-promoted.

        Must be called before AutoPromoter can advance this agent past PAPER
        when ``require_operator_ack_after_restart`` is True.
        """
        self._restart_pending_ack.discard(agent_name)
        logger.info("[deploy] %s: restart ack received — eligible for re-promotion", agent_name)
        self._persist_state()

    def needs_restart_ack(self, agent_name: str) -> bool:
        """Return True if this agent is waiting for operator ack before re-promotion."""
        return agent_name in self._restart_pending_ack

    def promote_to_shadow(
        self,
        agent_name: str,
        readiness: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """Promote agent from PAPER to SHADOW mode.

        Shadow mode runs live orders alongside paper tracking for
        side-by-side comparison before full live promotion.

        Args:
            agent_name: Agent to promote.
            readiness: Readiness verdict dict (from PaperSession.check_readiness).

        Returns:
            (success, reason)
        """
        dep = self.register_agent(agent_name)

        if dep.mode not in (AgentMode.PAPER, AgentMode.HALTED):
            return False, f"Agent {agent_name} is already {dep.mode.value}"

        # Operator ack gate after restart
        if self._config.require_operator_ack_after_restart and self.needs_restart_ack(agent_name):
            return False, (
                f"Agent {agent_name} requires operator acknowledgement after restart "
                f"before re-promotion (call acknowledge_restart())"
            )

        # Readiness gate
        if self._config.require_readiness_check:
            ok, reason = self._check_readiness(readiness)
            if not ok:
                return False, reason

        # Max live agents check
        live_count = sum(
            1 for d in self._agents.values()
            if d.mode in (AgentMode.LIVE, AgentMode.SHADOW)
        )
        if live_count >= self._config.max_live_agents:
            return False, f"Max live agents ({self._config.max_live_agents}) reached"

        old_mode = dep.mode
        dep.mode = AgentMode.SHADOW
        dep.promoted_at = datetime.now(timezone.utc).isoformat()
        self._log_transition(agent_name, old_mode.value, "SHADOW", "Promoted to shadow")
        logger.info(f"[deploy] {agent_name}: {old_mode.value} → SHADOW")
        self._persist_state()
        return True, "OK"

    def promote_to_live(
        self,
        agent_name: str,
        readiness: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """Promote agent to full LIVE mode.

        Agents MUST pass through SHADOW first.  Direct PAPER → LIVE is blocked.
        From SHADOW, checks min shadow trades AND min shadow wall-clock time.

        Args:
            agent_name: Agent to promote.
            readiness: Readiness verdict dict.

        Returns:
            (success, reason)
        """
        dep = self.register_agent(agent_name)

        if dep.mode == AgentMode.LIVE:
            return False, f"Agent {agent_name} is already LIVE"

        # BUG-8 fix: PAPER/HALTED → LIVE is blocked. Must go through SHADOW first.
        if dep.mode in (AgentMode.PAPER, AgentMode.HALTED):
            return False, (
                f"Agent {agent_name} is in {dep.mode.value} mode. "
                f"Promote to SHADOW first via promote_to_shadow(), then to LIVE after "
                f"{self._config.min_shadow_trades_before_full_live} shadow trades and "
                f"{self._config.min_shadow_hours_before_full_live:.0f}h in shadow."
            )

        # From SHADOW → check min shadow trades
        if dep.shadow_trades < self._config.min_shadow_trades_before_full_live:
            return False, (
                f"Insufficient shadow trades: {dep.shadow_trades} "
                f"< {self._config.min_shadow_trades_before_full_live}"
            )

        # BUG-fix-m3: check minimum wall-clock time in SHADOW mode
        if dep.promoted_at:
            try:
                shadow_since = datetime.fromisoformat(dep.promoted_at)
                hours_in_shadow = (
                    datetime.now(timezone.utc) - shadow_since
                ).total_seconds() / 3600.0
                if hours_in_shadow < self._config.min_shadow_hours_before_full_live:
                    return False, (
                        f"Insufficient time in SHADOW: {hours_in_shadow:.1f}h "
                        f"< {self._config.min_shadow_hours_before_full_live:.0f}h required"
                    )
            except Exception as exc:
                logger.warning("[deploy] shadow time check failed: %s", exc)

        # BUG-7 fix: require validate_before_lift() to pass before LIVE promotion
        if self._config.require_backtest_lift_gate:
            ok, lift_reason = self._check_backtest_lift_gate(agent_name)
            if not ok:
                return False, f"backtest_lift_gate: {lift_reason}"

        # Readiness gate
        if self._config.require_readiness_check:
            ok, reason = self._check_readiness(readiness)
            if not ok:
                return False, reason

        # Max live agents check
        live_count = sum(
            1 for d in self._agents.values()
            if d.mode in (AgentMode.LIVE, AgentMode.SHADOW) and d.agent_name != agent_name
        )
        if live_count >= self._config.max_live_agents:
            return False, f"Max live agents ({self._config.max_live_agents}) reached"

        old_mode = dep.mode
        dep.mode = AgentMode.LIVE
        dep.promoted_at = datetime.now(timezone.utc).isoformat()
        self._log_transition(agent_name, old_mode.value, "LIVE", "Promoted to live")
        logger.info(f"[deploy] {agent_name}: {old_mode.value} → LIVE")
        self._persist_state()
        return True, "OK"

    def force_live_for_production_profile(
        self,
        agent_name: str,
        *,
        reason: str = "MERID_PM_PROFILE=production crypto PM",
    ) -> None:
        """Set agent to LIVE without shadow/readiness/backtest gates.

        Used only when production PM live is enabled so DeploymentController
        bookkeeping matches VenueGate (agents default-register as PAPER).
        Bypasses ``max_live_agents`` so the full 5×6 crypto grid can execute.
        """
        dep = self.register_agent(agent_name)
        old_mode = dep.mode.value
        dep.mode = AgentMode.LIVE
        dep.promoted_at = datetime.now(timezone.utc).isoformat()
        self._log_transition(agent_name, old_mode, "LIVE", reason)
        logger.info("[deploy] FORCE-LIVE-PRODUCTION %s: %s → LIVE (%s)", agent_name, old_mode, reason)
        self._persist_state()

    # ── Rollback ─────────────────────────────────────────────────────

    def rollback(self, agent_name: str, reason: str = "manual") -> tuple[bool, str]:
        """Demote agent back to PAPER mode.

        Args:
            agent_name: Agent to rollback.
            reason: Reason for rollback (logged).

        Returns:
            (success, message)
        """
        dep = self._agents.get(agent_name)
        if dep is None:
            return False, f"Agent {agent_name} not registered"

        if dep.mode == AgentMode.PAPER:
            return False, f"Agent {agent_name} is already in PAPER mode"

        old_mode = dep.mode
        dep.mode = AgentMode.PAPER
        dep.rollback_count += 1
        dep.last_rollback_reason = reason
        dep.last_rollback_at = datetime.now(timezone.utc).isoformat()
        self._log_transition(agent_name, old_mode.value, "PAPER", f"Rollback: {reason}")
        logger.warning(f"[deploy] ROLLBACK {agent_name}: {old_mode.value} → PAPER ({reason})")
        self._persist_state()
        return True, f"Rolled back to PAPER: {reason}"

    def halt(self, agent_name: str, reason: str = "manual") -> tuple[bool, str]:
        """Halt agent (no orders, requires explicit re-promotion)."""
        dep = self._agents.get(agent_name)
        if dep is None:
            return False, f"Agent {agent_name} not registered"

        old_mode = dep.mode
        dep.mode = AgentMode.HALTED
        self._log_transition(agent_name, old_mode.value, "HALTED", f"Halted: {reason}")
        logger.warning(f"[deploy] HALTED {agent_name}: {reason}")
        self._persist_state()
        return True, f"Halted: {reason}"

    # ── Auto-rollback check ──────────────────────────────────────────

    def check_auto_rollback(
        self,
        agent_name: str,
        profit_factor: float = 0.0,
        drawdown_pct: float = 0.0,
        consecutive_losses: int = 0,
    ) -> Optional[str]:
        """Check if auto-rollback should trigger for a live agent.

        Returns rollback reason if triggered, None otherwise.
        """
        dep = self._agents.get(agent_name)
        if dep is None or dep.mode not in (AgentMode.LIVE, AgentMode.SHADOW):
            return None

        cfg = self._config

        if profit_factor > 0 and profit_factor < cfg.auto_rollback_on_pf_below:
            reason = f"PF {profit_factor:.2f} < {cfg.auto_rollback_on_pf_below}"
            self.rollback(agent_name, reason)
            return reason

        if drawdown_pct > cfg.auto_rollback_on_drawdown_above_pct:
            reason = f"Drawdown {drawdown_pct:.1f}% > {cfg.auto_rollback_on_drawdown_above_pct}%"
            self.rollback(agent_name, reason)
            return reason

        if consecutive_losses >= cfg.auto_rollback_on_consecutive_losses:
            reason = f"Consecutive losses {consecutive_losses} >= {cfg.auto_rollback_on_consecutive_losses}"
            self.rollback(agent_name, reason)
            return reason

        return None

    # ── Trade recording ──────────────────────────────────────────────

    def record_live_trade(self, agent_name: str) -> None:
        """Increment live trade counter for an agent."""
        dep = self._agents.get(agent_name)
        if dep:
            dep.live_trades += 1

    def record_shadow_trade(self, agent_name: str) -> None:
        """Increment shadow trade counter for an agent."""
        dep = self._agents.get(agent_name)
        if dep:
            dep.shadow_trades += 1

    # ── Backtest lift gate ────────────────────────────────────────────

    def _check_backtest_lift_gate(self, agent_name: str) -> tuple[bool, str]:
        """BUG-7 fix: call validate_before_lift() before any LIVE promotion.

        Tries to source a BacktestReport for this agent from the backtesting
        subsystem.  If no report is available the gate fails closed.
        """
        try:
            from merid.risk.btc_promotion_config import validate_before_lift, BacktestReport
            from merid.backtesting.kalshi_backtest import get_latest_backtest_report
            report: Optional[BacktestReport] = get_latest_backtest_report(agent_name)
            if report is None:
                return False, f"no_backtest_report_for_{agent_name}"
            result = validate_before_lift(report)
            if not result["ok"]:
                return False, result["reason"]
            return True, "ok"
        except ImportError:
            # Backtest module not available — fail closed for live promotions
            logger.warning(
                "[deploy] validate_before_lift: backtest module unavailable for %s — "
                "blocking LIVE promotion (fail-closed)", agent_name
            )
            return False, "backtest_module_unavailable"
        except Exception as exc:
            logger.warning("[deploy] validate_before_lift error for %s: %s", agent_name, exc)
            return False, f"backtest_check_error: {exc}"

    # ── Readiness check ──────────────────────────────────────────────

    def _check_readiness(self, readiness: Optional[Dict[str, Any]]) -> tuple[bool, str]:
        """Validate readiness verdict against deployment gates.

        Accepts either a ReadinessVerdict dataclass or its ``to_dict()`` output.
        """
        if readiness is None:
            return False, "No readiness verdict provided"

        # Support both dict and dataclass
        ready = getattr(readiness, "ready", None) or (readiness.get("ready") if isinstance(readiness, dict) else None)
        checks = getattr(readiness, "checks", None) or (readiness.get("checks", {}) if isinstance(readiness, dict) else {})
        details = getattr(readiness, "details", None) or (readiness.get("details", {}) if isinstance(readiness, dict) else {})

        if not ready:
            # Enumerate which checks failed for actionable diagnostics
            failing = [k for k, v in (checks or {}).items() if not v]
            detail_msgs = [f"{k}: {details.get(k, '?')}" for k in failing] if details else failing
            return False, f"Agent not ready — failing: {', '.join(detail_msgs) or str(details)}"

        # Validate that the readiness dict has meaningful structure, not just {"ready": True}
        if not checks and not details:
            logger.warning(
                "[deploy] _check_readiness: readiness dict has no checks/details — "
                "accepting but recommend passing structured verdict"
            )
        return True, "OK"

    # ── Persistence ───────────────────────────────────────────────────

    def _persist_state(self) -> None:
        """Write current agent states and transition log to disk."""
        try:
            path = _state_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "agents": {
                    name: dep.to_dict()
                    for name, dep in self._agents.items()
                },
                "restart_pending_ack": sorted(self._restart_pending_ack),
                "log": [e.to_dict() for e in self._log[-self._MAX_LOG:]],
                "persisted_at": datetime.now(timezone.utc).isoformat(),
            }
            path.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            logger.error("[deploy] failed to persist state: %s", exc)

    def _load_persisted_state(self) -> None:
        """Reload agent deployment states from disk on startup.

        Previously LIVE agents are loaded in their persisted mode but flagged
        in ``_restart_pending_ack`` so AutoPromoter cannot re-promote them to
        LIVE without explicit operator acknowledgement.
        """
        path = _state_file_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            logger.warning("[deploy] failed to load persisted state: %s", exc)
            return

        for name, d in data.get("agents", {}).items():
            try:
                mode = AgentMode(d.get("mode", AgentMode.PAPER.value))
                dep = AgentDeployment(
                    agent_name=name,
                    mode=AgentMode.PAPER,  # Always restart in PAPER regardless of persisted mode
                    promoted_at=d.get("promoted_at"),
                    rollback_count=d.get("rollback_count", 0),
                    last_rollback_reason=d.get("last_rollback_reason"),
                    last_rollback_at=d.get("last_rollback_at"),
                    live_trades=d.get("live_trades", 0),
                    shadow_trades=d.get("shadow_trades", 0),
                )
                self._agents[name] = dep
                # Flag previously LIVE/SHADOW agents for operator ack
                if mode in (AgentMode.LIVE, AgentMode.SHADOW):
                    if self._config.require_operator_ack_after_restart:
                        self._restart_pending_ack.add(name)
                        logger.warning(
                            "[deploy] %s was %s before restart — holding in PAPER until "
                            "operator calls acknowledge_restart()", name, mode.value
                        )
            except Exception as exc:
                logger.warning("[deploy] failed to restore agent %s: %s", name, exc)

        for ack_name in data.get("restart_pending_ack", []):
            self._restart_pending_ack.add(ack_name)

        logger.info(
            "[deploy] loaded %d agents from persisted state (%d awaiting ack)",
            len(self._agents),
            len(self._restart_pending_ack),
        )

    # ── Audit log ────────────────────────────────────────────────────

    def _log_transition(
        self, agent_name: str, from_mode: str, to_mode: str, reason: str,
    ) -> None:
        entry = TransitionLog(
            ts=datetime.now(timezone.utc).isoformat(),
            agent_name=agent_name,
            from_mode=from_mode,
            to_mode=to_mode,
            reason=reason,
        )
        self._log.append(entry)
        if len(self._log) > self._MAX_LOG:
            self._log = self._log[-self._MAX_LOG:]

        # Telegram alert for high-stakes transitions (LIVE promotions and rollbacks)
        if to_mode in ("LIVE", "SHADOW") or from_mode in ("LIVE", "SHADOW"):
            try:
                import asyncio as _aio
                from merid.alerts.webhook_client import tg_send
                icon = "\U0001f7e2" if to_mode == "LIVE" else ("\U0001f7e1" if to_mode == "SHADOW" else "\U0001f534")
                _tg_task = _aio.get_running_loop().create_task(tg_send(
                    f"{icon} [DeploymentController] <b>{agent_name}</b>: "
                    f"{from_mode} \u2192 {to_mode}\nReason: {reason}"
                ))
                _tg_task.add_done_callback(lambda t: (
                    logger.warning("[deployment] Telegram task failed: %s", t.exception())
                    if not t.cancelled() and t.exception() else None
                ))
            except RuntimeError:
                pass  # No running loop — Telegram notification skipped
            except Exception as _tg_exc:
                logger.debug("[deployment] Telegram notification failed: %s", _tg_exc)

    # ── Status ───────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Full deployment status."""
        agents = {name: dep.to_dict() for name, dep in self._agents.items()}
        live = [n for n, d in self._agents.items() if d.mode == AgentMode.LIVE]
        shadow = [n for n, d in self._agents.items() if d.mode == AgentMode.SHADOW]
        paper = [n for n, d in self._agents.items() if d.mode == AgentMode.PAPER]
        halted = [n for n, d in self._agents.items() if d.mode == AgentMode.HALTED]

        return {
            "agents": agents,
            "live": live,
            "shadow": shadow,
            "paper": paper,
            "halted": halted,
            "live_count": len(live),
            "shadow_count": len(shadow),
            "total_agents": len(self._agents),
            "max_live_agents": self._config.max_live_agents,
            "recent_transitions": [e.to_dict() for e in self._log[-10:]],
        }

    @property
    def transition_log(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._log]


# ── Singleton ─────────────────────────────────────────────────────────

_controller: Optional[DeploymentController] = None
_controller_lock = threading.Lock()


def get_deployment_controller() -> DeploymentController:
    """Return the module-level DeploymentController singleton."""
    global _controller
    if _controller is None:
        with _controller_lock:
            if _controller is None:
                _controller = DeploymentController()
    return _controller
