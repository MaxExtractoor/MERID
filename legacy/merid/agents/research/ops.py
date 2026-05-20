"""§5 Dev, Infra, and Ops Agents.

- OpsRunbookAgent: map incidents/alerts to runbooks and concrete actions.
- BacktestAgent: continually evaluate strategy performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput, CanonicalAgent

from utils.logger import get_logger

logger = get_logger("merid.agents.ops")


# ======================================================================
# OpsRunbookAgent
# ======================================================================

@dataclass
class RunbookAction:
    """A concrete operational action recommended by the OpsRunbookAgent."""
    action_id: str = ""
    action_type: str = ""  # "pause_domain", "restart_service", "scale", "failover", "alert"
    target: str = ""       # venue, domain, service name
    description: str = ""
    severity: str = "info"
    auto_executable: bool = False
    runbook_ref: str = ""

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target": self.target,
            "description": self.description,
            "severity": self.severity,
            "auto_executable": self.auto_executable,
            "runbook_ref": self.runbook_ref,
        }


class OpsRunbookAgent(CanonicalAgent):
    """Maps incidents and alerts to runbooks and concrete actions.

    Reads alerts (metrics, logs, errors) and selects relevant runbooks.
    Proposes operational actions (scale, restart, failover, pause domains).
    """

    # Simple rule-based runbook mapping
    RUNBOOKS: Dict[str, Dict[str, Any]] = {
        "connectivity_loss": {
            "action_type": "pause_domain",
            "severity": "critical",
            "description": "Pause trading on affected venue until connectivity restored.",
            "auto_executable": True,
        },
        "stale_data": {
            "action_type": "pause_domain",
            "severity": "warning",
            "description": "Pause instruments with stale data feeds.",
            "auto_executable": True,
        },
        "daily_loss_breach": {
            "action_type": "pause_domain",
            "severity": "critical",
            "description": "Daily loss limit breached. Halt domain trading.",
            "auto_executable": True,
        },
        "high_latency": {
            "action_type": "alert",
            "severity": "warning",
            "description": "API latency elevated. Monitor and consider reducing order rate.",
            "auto_executable": False,
        },
        "circuit_breaker": {
            "action_type": "pause_domain",
            "severity": "critical",
            "description": "Circuit breaker tripped. Halt affected instruments.",
            "auto_executable": True,
        },
        "service_crash": {
            "action_type": "restart_service",
            "severity": "critical",
            "description": "Service crashed. Attempt restart.",
            "auto_executable": False,
        },
    }

    def __init__(self, agent_id: str = "ops-runbook-01"):
        super().__init__(agent_id, AgentCategory.OPS)
        self._actions: List[RunbookAction] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        alerts = context.get("alerts", [])
        actions = []
        for alert in alerts:
            action = self.map_alert(alert)
            if action:
                actions.append(action)
                self._actions.append(action)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="runbook_actions",
            payload={
                "actions": [a.to_dict() for a in actions],
                "count": len(actions),
                "auto_executable": sum(1 for a in actions if a.auto_executable),
            },
            confidence=0.8,
        )

    def map_alert(self, alert: Dict[str, Any]) -> Optional[RunbookAction]:
        """Map an alert to a runbook action."""
        alert_type = alert.get("type", alert.get("category", ""))
        target = alert.get("venue", alert.get("target", alert.get("domain", "")))

        runbook = self.RUNBOOKS.get(alert_type)
        if not runbook:
            # Try partial match
            for key, rb in self.RUNBOOKS.items():
                if key in alert_type.lower():
                    runbook = rb
                    break

        if not runbook:
            return None

        return RunbookAction(
            action_id=f"rb-{alert_type}-{target}",
            action_type=runbook["action_type"],
            target=target,
            description=runbook["description"],
            severity=runbook["severity"],
            auto_executable=runbook["auto_executable"],
            runbook_ref=alert_type,
        )

    def get_actions(self, limit: int = 50) -> List[RunbookAction]:
        return self._actions[-limit:]


# ======================================================================
# BacktestAgent
# ======================================================================

@dataclass
class BacktestResult:
    """Result of a strategy backtest."""
    strategy_id: str = ""
    domain: str = ""
    period: str = ""
    total_trades: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_pnl_usd: float = 0.0
    recommendation: str = "hold"  # promote, demote, hold, retire

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "domain": self.domain,
            "period": self.period,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "total_pnl_usd": round(self.total_pnl_usd, 2),
            "recommendation": self.recommendation,
        }


class BacktestAgent(CanonicalAgent):
    """Continually evaluates strategy performance.

    Runs backtests and forward-tests across domains.
    Produces reports comparing strategies and recommending promotion/demotion.
    """

    def __init__(self, agent_id: str = "backtest-01"):
        super().__init__(agent_id, AgentCategory.OPS)
        self._results: List[BacktestResult] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        strategies = context.get("strategies", [])
        results = []
        for strat in strategies:
            result = await self._evaluate_strategy(strat)
            results.append(result)
            self._results.append(result)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="backtest_results",
            payload={
                "results": [r.to_dict() for r in results],
                "count": len(results),
                "promote": sum(1 for r in results if r.recommendation == "promote"),
                "demote": sum(1 for r in results if r.recommendation == "demote"),
            },
            confidence=0.6,
        )

    async def _evaluate_strategy(self, strategy: Dict[str, Any]) -> BacktestResult:
        """Evaluate a strategy. Override for actual backtesting logic."""
        return BacktestResult(
            strategy_id=strategy.get("strategy_id", ""),
            domain=strategy.get("domain", ""),
            period=strategy.get("period", "30d"),
            recommendation="hold",
        )

    def get_results(self, limit: int = 50) -> List[BacktestResult]:
        return self._results[-limit:]
