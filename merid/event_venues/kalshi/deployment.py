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

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

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
    require_readiness_check: bool = True
    min_paper_trades: int = 200
    min_profit_factor: float = 1.4
    min_expectancy_cents: float = 5.0
    max_drawdown_pct: float = 12.0
    max_error_rate_pct: float = 5.0

    # Shadow mode
    min_shadow_trades_before_full_live: int = 5

    # Auto-rollback thresholds
    auto_rollback_on_pf_below: float = 0.9
    auto_rollback_on_drawdown_above_pct: float = 15.0
    auto_rollback_on_consecutive_losses: int = 10

    # Max simultaneous live agents
    max_live_agents: int = 3


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

    @property
    def config(self) -> DeploymentConfig:
        return self._config

    # ── Agent registration ───────────────────────────────────────────

    def register_agent(self, agent_name: str) -> AgentDeployment:
        """Register an agent (starts in PAPER mode)."""
        if agent_name not in self._agents:
            self._agents[agent_name] = AgentDeployment(agent_name=agent_name)
        return self._agents[agent_name]

    def get_mode(self, agent_name: str) -> AgentMode:
        """Get current mode for an agent."""
        dep = self._agents.get(agent_name)
        return dep.mode if dep else AgentMode.PAPER

    def is_live(self, agent_name: str) -> bool:
        return self.get_mode(agent_name) in (AgentMode.LIVE, AgentMode.SHADOW)

    # ── Promotion ────────────────────────────────────────────────────

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
        return True, "OK"

    def promote_to_live(
        self,
        agent_name: str,
        readiness: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """Promote agent to full LIVE mode.

        If agent is in PAPER, goes through shadow check.
        If agent is in SHADOW, checks min shadow trades.

        Args:
            agent_name: Agent to promote.
            readiness: Readiness verdict dict.

        Returns:
            (success, reason)
        """
        dep = self.register_agent(agent_name)

        if dep.mode == AgentMode.LIVE:
            return False, f"Agent {agent_name} is already LIVE"

        # From PAPER → must pass readiness
        if dep.mode in (AgentMode.PAPER, AgentMode.HALTED):
            if self._config.require_readiness_check:
                ok, reason = self._check_readiness(readiness)
                if not ok:
                    return False, reason

        # From SHADOW → check min shadow trades
        if dep.mode == AgentMode.SHADOW:
            if dep.shadow_trades < self._config.min_shadow_trades_before_full_live:
                return False, (
                    f"Insufficient shadow trades: {dep.shadow_trades} "
                    f"< {self._config.min_shadow_trades_before_full_live}"
                )

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
        return True, "OK"

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

        return True, "OK"

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
                _aio.get_running_loop().create_task(tg_send(
                    f"{icon} [DeploymentController] <b>{agent_name}</b>: "
                    f"{from_mode} \u2192 {to_mode}\nReason: {reason}"
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


def get_deployment_controller() -> DeploymentController:
    """Return the module-level DeploymentController singleton."""
    global _controller
    if _controller is None:
        _controller = DeploymentController()
    return _controller
