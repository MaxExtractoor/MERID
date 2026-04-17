"""
Governor/Meta-Agent for MERID
Monitors agent performance, correlations, risk usage, and failure modes.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import numpy as np

from agents.agent_framework import Agent, AgentCapability, AgentRole, get_agent_registry
from agents.unified_decision_layer import get_unified_decision_layer
from core.drift_monitor import get_drift_monitor
from core.decision_log import get_decision_log
from core.explainability import ExplanationContext, ExplanationType, get_explainability_service
from utils.logger import get_logger

logger = get_logger("agents.governor")


def _get_drift_reward_loop():
    """Lazy import to avoid circular dependency."""
    from core.drift_reward_loop import get_drift_reward_loop, DeRiskDecision, DeRiskAction
    return get_drift_reward_loop(), DeRiskDecision, DeRiskAction


class AgentHealthStatus(Enum):
    """Agent health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNDERPERFORMING = "underperforming"
    FAILING = "failing"


class GovernanceAction(Enum):
    """Governance actions."""
    PROMOTE = "promote"
    DEMOTE = "demote"
    PAUSE = "pause"
    RETIRE = "retire"
    INCREASE_WEIGHT = "increase_weight"
    DECREASE_WEIGHT = "decrease_weight"


@dataclass
class AgentPerformanceMetrics:
    """Performance metrics for an agent."""
    agent_id: str
    agent_role: AgentRole
    decisions_made: int
    success_rate: float
    average_confidence: float
    sharpe_ratio: float
    max_drawdown: float
    correlation_with_others: Dict[str, float]
    risk_usage: float
    failure_count: int
    last_active: float
    health_status: AgentHealthStatus


@dataclass
class GovernanceDecision:
    """Governance decision about an agent."""
    agent_id: str
    action: GovernanceAction
    reason: str
    metrics: AgentPerformanceMetrics
    timestamp: float


class PerformanceMonitor:
    """Monitors agent performance."""
    
    def __init__(self):
        self._decision_log = get_decision_log()
        self._performance_window = 3600.0 * 24  # 24 hours
        self._drift_monitor = get_drift_monitor()
    
    def evaluate_agent(self, agent_id: str) -> AgentPerformanceMetrics:
        """Evaluate agent performance."""
        # Get recent decisions
        decisions = self._decision_log.get_agent_decisions(
            agent_id=agent_id,
            start_time=time.time() - self._performance_window
        )
        
        if not decisions:
            return AgentPerformanceMetrics(
                agent_id=agent_id,
                agent_role=AgentRole.RESEARCH_SIGNAL,
                decisions_made=0,
                success_rate=0.0,
                average_confidence=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                correlation_with_others={},
                risk_usage=0.0,
                failure_count=0,
                last_active=0.0,
                health_status=AgentHealthStatus.FAILING
            )
        
        # Calculate metrics
        success_count = sum(1 for d in decisions if d.outcome.value == "success")
        success_rate = success_count / len(decisions)
        
        avg_confidence = np.mean([d.confidence for d in decisions])
        
        # Get PnL for Sharpe ratio calculation
        pnls = []
        for decision in decisions:
            if decision.outcome_metrics:
                pnl = decision.outcome_metrics.get("pnl", 0.0)
                pnls.append(pnl)
        
        sharpe_ratio = 0.0
        max_drawdown = 0.0
        if pnls:
            returns = np.array(pnls)
            sharpe_ratio = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)
            
            cumulative = np.cumsum(returns)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = running_max - cumulative
            max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0.0
        
        self._record_drift_signals(
            agent_id,
            sharpe_ratio,
            success_rate,
            max_drawdown,
        )
        
        # Determine health status
        health_status = self._determine_health_status(
            success_rate, sharpe_ratio, max_drawdown, len(decisions)
        )
        
        registry = get_agent_registry()
        agent = registry.get_agent(agent_id)
        
        return AgentPerformanceMetrics(
            agent_id=agent_id,
            agent_role=agent.role if agent else AgentRole.RESEARCH_SIGNAL,
            decisions_made=len(decisions),
            success_rate=success_rate,
            average_confidence=avg_confidence,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            correlation_with_others={},
            risk_usage=0.0,
            failure_count=len(decisions) - success_count,
            last_active=decisions[-1].timestamp if decisions else 0.0,
            health_status=health_status
        )
    
    def _record_drift_signals(
        self,
        agent_id: str,
        sharpe_ratio: float,
        success_rate: float,
        max_drawdown: float,
    ) -> None:
        metrics = {
            "sharpe_ratio": sharpe_ratio,
            "success_rate": success_rate,
            "max_drawdown": max_drawdown,
        }
        thresholds = {
            "sharpe_ratio": 0.5,
            "success_rate": 0.1,
            "max_drawdown": 0.1,
        }
        for metric_name, value in metrics.items():
            self._drift_monitor.record_metric(f"{agent_id}_{metric_name}", value)
        self._drift_monitor.evaluate(
            component=agent_id,
            component_type="agent",
            metrics=metrics,
            thresholds=thresholds,
        )
    
    def _determine_health_status(
        self,
        success_rate: float,
        sharpe_ratio: float,
        max_drawdown: float,
        decision_count: int
    ) -> AgentHealthStatus:
        """Determine agent health status."""
        if decision_count < 10:
            return AgentHealthStatus.DEGRADED
        
        if success_rate < 0.4 or sharpe_ratio < -0.5:
            return AgentHealthStatus.FAILING
        elif success_rate < 0.5 or sharpe_ratio < 0.0:
            return AgentHealthStatus.UNDERPERFORMING
        elif success_rate < 0.6 or sharpe_ratio < 0.5:
            return AgentHealthStatus.DEGRADED
        else:
            return AgentHealthStatus.HEALTHY
    
    def calculate_correlations(
        self,
        agent_ids: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """Calculate correlations between agents."""
        correlations: Dict[str, Dict[str, float]] = {}
        
        # Get decisions for all agents
        agent_decisions = {}
        for agent_id in agent_ids:
            decisions = self._decision_log.get_agent_decisions(
                agent_id=agent_id,
                start_time=time.time() - self._performance_window
            )
            agent_decisions[agent_id] = decisions
        
        # Calculate pairwise correlations
        for i, agent_id_1 in enumerate(agent_ids):
            correlations[agent_id_1] = {}
            
            for agent_id_2 in agent_ids[i+1:]:
                corr = self._calculate_pairwise_correlation(
                    agent_decisions[agent_id_1],
                    agent_decisions[agent_id_2]
                )
                correlations[agent_id_1][agent_id_2] = corr
        
        return correlations
    
    def _calculate_pairwise_correlation(
        self,
        decisions_1: List[Any],
        decisions_2: List[Any]
    ) -> float:
        """Calculate correlation between two agents' decisions."""
        if not decisions_1 or not decisions_2:
            return 0.0
        
        # Extract outcomes
        outcomes_1 = [1.0 if d.outcome.value == "success" else 0.0 for d in decisions_1]
        outcomes_2 = [1.0 if d.outcome.value == "success" else 0.0 for d in decisions_2]
        
        # Align by timestamp (simplified)
        min_len = min(len(outcomes_1), len(outcomes_2))
        outcomes_1 = outcomes_1[:min_len]
        outcomes_2 = outcomes_2[:min_len]
        
        if len(outcomes_1) < 2:
            return 0.0
        
        return float(np.corrcoef(outcomes_1, outcomes_2)[0, 1])


class GovernanceEngine:
    """Makes governance decisions about agents."""
    
    def __init__(self):
        self._monitor = PerformanceMonitor()
        self._governance_history: List[GovernanceDecision] = []
        
        # Thresholds
        self._success_rate_threshold = 0.5
        self._sharpe_threshold = 0.0
        self._max_drawdown_threshold = 0.2
        self._correlation_threshold = 0.8
    
    def evaluate_and_act(self, agent_id: str) -> Optional[GovernanceDecision]:
        """Evaluate agent and take governance action if needed."""
        metrics = self._monitor.evaluate_agent(agent_id)
        
        action = self._determine_action(metrics)
        
        if action:
            decision = GovernanceDecision(
                agent_id=agent_id,
                action=action,
                reason=self._generate_reason(metrics, action),
                metrics=metrics,
                timestamp=time.time()
            )
            
            self._governance_history.append(decision)
            if len(self._governance_history) > 5000:
                self._governance_history = self._governance_history[-2500:]
            self._execute_action(decision)
            
            return decision
        
        return None
    
    def _determine_action(
        self,
        metrics: AgentPerformanceMetrics
    ) -> Optional[GovernanceAction]:
        """Determine governance action based on metrics."""
        if metrics.health_status == AgentHealthStatus.FAILING:
            if metrics.decisions_made > 50:
                return GovernanceAction.RETIRE
            else:
                return GovernanceAction.PAUSE
        
        elif metrics.health_status == AgentHealthStatus.UNDERPERFORMING:
            return GovernanceAction.DEMOTE
        
        elif metrics.health_status == AgentHealthStatus.DEGRADED:
            return GovernanceAction.DECREASE_WEIGHT
        
        elif metrics.health_status == AgentHealthStatus.HEALTHY:
            if metrics.success_rate > 0.7 and metrics.sharpe_ratio > 1.0:
                return GovernanceAction.PROMOTE
        
        return None
    
    def _generate_reason(
        self,
        metrics: AgentPerformanceMetrics,
        action: GovernanceAction
    ) -> str:
        """Generate human-readable reason for action."""
        reasons = []
        
        if metrics.success_rate < self._success_rate_threshold:
            reasons.append(f"Low success rate: {metrics.success_rate:.2%}")
        
        if metrics.sharpe_ratio < self._sharpe_threshold:
            reasons.append(f"Negative Sharpe ratio: {metrics.sharpe_ratio:.2f}")
        
        if metrics.max_drawdown > self._max_drawdown_threshold:
            reasons.append(f"High drawdown: {metrics.max_drawdown:.2%}")
        
        if not reasons:
            reasons.append(f"High performance: {metrics.success_rate:.2%} success, {metrics.sharpe_ratio:.2f} Sharpe")
        
        return f"{action.value}: " + ", ".join(reasons)
    
    def _execute_action(self, decision: GovernanceDecision) -> None:
        """Execute governance action."""
        registry = get_agent_registry()
        agent = registry.get_agent(decision.agent_id)
        
        if not agent:
            logger.error(f"Agent {decision.agent_id} not found for governance action")
            return
        
        if decision.action == GovernanceAction.PAUSE:
            asyncio.ensure_future(agent.pause())
            logger.warning(f"Paused agent {decision.agent_id}: {decision.reason}")
        
        elif decision.action == GovernanceAction.RETIRE:
            asyncio.ensure_future(agent.stop())
            registry.unregister(decision.agent_id)
            logger.warning(f"Retired agent {decision.agent_id}: {decision.reason}")
        
        elif decision.action in [GovernanceAction.PROMOTE, GovernanceAction.DEMOTE]:
            logger.info(f"Agent {decision.agent_id} {decision.action.value}: {decision.reason}")
        
        elif decision.action in [GovernanceAction.INCREASE_WEIGHT, GovernanceAction.DECREASE_WEIGHT]:
            logger.info(f"Agent {decision.agent_id} {decision.action.value}: {decision.reason}")
    
    def get_governance_history(self, limit: int = 100) -> List[GovernanceDecision]:
        """Get governance decision history."""
        return self._governance_history[-limit:]


class GovernorAgent(Agent):
    """Governor/meta-agent that oversees all other agents."""
    
    def __init__(self):
        capabilities = [
            AgentCapability(
                name="monitor_performance",
                description="Monitor agent performance metrics",
                input_schema={},
                output_schema={}
            ),
            AgentCapability(
                name="governance_decision",
                description="Make governance decisions about agents",
                input_schema={},
                output_schema={}
            ),
            AgentCapability(
                name="drift_response",
                description="Respond to drift-triggered de-risk decisions",
                input_schema={},
                output_schema={}
            )
        ]
        
        super().__init__(
            agent_id="governor_001",
            role=AgentRole.GOVERNANCE,
            capabilities=capabilities
        )
        
        self._governance_engine = GovernanceEngine()
        self._monitor = PerformanceMonitor()
        self._last_evaluation = 0.0
        self._evaluation_interval = 3600.0  # 1 hour
        self._explainability = get_explainability_service()
        
        # Drift-triggered decisions
        self._drift_decisions: List[Dict[str, Any]] = []
        
        # Register with drift reward loop
        self._register_drift_callback()
    
    def _register_drift_callback(self) -> None:
        """Register callback with drift reward loop."""
        try:
            drift_loop, DeRiskDecision, DeRiskAction = _get_drift_reward_loop()
            drift_loop.register_governor_callback(self._handle_drift_decision)
            logger.info("Governor registered with drift reward loop")
        except Exception as e:
            logger.warning("Could not register drift callback: %s", e)
    
    def _handle_drift_decision(self, decision) -> None:
        """Handle de-risk decision from drift reward loop."""
        drift_loop, DeRiskDecision, DeRiskAction = _get_drift_reward_loop()
        
        decision_record = {
            "action": decision.action.value,
            "severity": decision.severity.value,
            "target": decision.target_component,
            "parameters": decision.parameters,
            "reason": decision.reason,
            "timestamp": decision.timestamp,
            "governor_response": None,
        }
        
        # Take governance action based on de-risk decision
        if decision.action.value == "pause_strategy":
            self._execute_pause(decision.target_component, decision.parameters)
            decision_record["governor_response"] = "paused"
        elif decision.action.value == "emergency_exit":
            self._execute_emergency_exit(decision.target_component)
            decision_record["governor_response"] = "emergency_exit_triggered"
        
        self._drift_decisions.append(decision_record)
        
        # Record explanation
        self._record_drift_response_explanation(decision, decision_record)
        
        logger.warning(
            "Governor handled drift decision: %s for %s",
            decision.action.value,
            decision.target_component,
        )
    
    def _execute_pause(self, component_id: str, parameters: Dict[str, Any]) -> None:
        """Execute pause action on component."""
        registry = get_agent_registry()
        agent = registry.get_agent(component_id)
        
        if agent:
            asyncio.ensure_future(agent.pause())
            logger.warning("Paused agent %s due to drift", component_id)
    
    def _execute_emergency_exit(self, component_id: str) -> None:
        """Execute emergency exit for component."""
        registry = get_agent_registry()
        agent = registry.get_agent(component_id)
        
        if agent:
            asyncio.ensure_future(agent.stop())
            logger.critical("Emergency exit triggered for %s", component_id)
    
    def _record_drift_response_explanation(
        self,
        decision,
        record: Dict[str, Any],
    ) -> None:
        """Record explanation for drift response."""
        context = ExplanationContext(
            inputs={
                "drift_action": decision.action.value,
                "severity": decision.severity.value,
                "target": decision.target_component,
            },
            agent_id=self.agent_id,
            strategy=None,
            constraints=decision.parameters,
            expected_effect={"governor_response": record["governor_response"]},
            environment_flags={},
        )
        
        self._explainability.record_explanation(
            explanation_type=ExplanationType.GOVERNANCE_DECISION,
            summary=f"Governor drift response: {record['governor_response']} for {decision.target_component}",
            context=context,
            expert_notes=decision.reason,
        )
    
    async def process_message(self, message: Any) -> Optional[Any]:
        """Process incoming message."""
        return None
    
    async def make_decision(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Make governance decision."""
        decision_type = context.get("decision_type", "")
        
        if decision_type == "evaluate_agents":
            return await self._evaluate_all_agents()
        elif decision_type == "resolve_conflict":
            return await self._resolve_conflict(context)
        else:
            return {"decision": "no_action", "confidence": 1.0}
    
    async def _evaluate_all_agents(self) -> Dict[str, Any]:
        """Evaluate all agents and take governance actions."""
        current_time = time.time()
        
        if current_time - self._last_evaluation < self._evaluation_interval:
            return {"decision": "evaluation_skipped", "confidence": 1.0}
        
        registry = get_agent_registry()
        all_agents = registry.get_all_agents()
        
        actions_taken = []
        
        for agent in all_agents:
            if agent.agent_id == self.agent_id:
                continue
            
            decision = self._governance_engine.evaluate_and_act(agent.agent_id)
            
            if decision:
                actions_taken.append({
                    "agent_id": decision.agent_id,
                    "action": decision.action.value,
                    "reason": decision.reason
                })
        
        self._last_evaluation = current_time
        
        return {
            "decision": "evaluation_complete",
            "confidence": 1.0,
            "actions_taken": actions_taken,
            "agents_evaluated": len(all_agents)
        }
    
    async def _resolve_conflict(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve conflict between agents."""
        conflicting_decisions = context.get("conflicting_decisions", [])
        
        if not conflicting_decisions:
            return {"decision": "no_conflict", "confidence": 1.0}
        
        # Evaluate performance of conflicting agents
        agent_scores = {}
        for decision in conflicting_decisions:
            agent_id = decision.get("agent_id")
            metrics = self._monitor.evaluate_agent(agent_id)
            
            score = metrics.success_rate * 0.5 + (metrics.sharpe_ratio + 1) * 0.3 + metrics.average_confidence * 0.2
            agent_scores[agent_id] = score
        
        # Select best agent's decision
        best_agent = max(agent_scores.items(), key=lambda x: x[1])[0]
        best_decision = next(d for d in conflicting_decisions if d.get("agent_id") == best_agent)
        
        return {
            "decision": best_decision.get("recommendation"),
            "confidence": agent_scores[best_agent],
            "reasoning": f"Selected decision from best-performing agent {best_agent}",
            "agent_scores": agent_scores
        }
    
    def get_portfolio_risk_report(self) -> Dict[str, Any]:
        """Get portfolio-level risk report."""
        registry = get_agent_registry()
        all_agents = registry.get_all_agents()
        
        agent_ids = [a.agent_id for a in all_agents if a.agent_id != self.agent_id]
        
        # Get performance metrics
        metrics_by_agent = {}
        for agent_id in agent_ids:
            metrics = self._monitor.evaluate_agent(agent_id)
            metrics_by_agent[agent_id] = metrics
        
        # Calculate correlations
        correlations = self._monitor.calculate_correlations(agent_ids)
        
        # Aggregate risk
        total_risk_usage = sum(m.risk_usage for m in metrics_by_agent.values())
        
        # Find high correlations
        high_correlations = []
        for agent_1, corr_dict in correlations.items():
            for agent_2, corr in corr_dict.items():
                if abs(corr) > 0.8:
                    high_correlations.append((agent_1, agent_2, corr))
        
        return {
            "total_agents": len(agent_ids),
            "healthy_agents": sum(1 for m in metrics_by_agent.values() if m.health_status == AgentHealthStatus.HEALTHY),
            "degraded_agents": sum(1 for m in metrics_by_agent.values() if m.health_status == AgentHealthStatus.DEGRADED),
            "failing_agents": sum(1 for m in metrics_by_agent.values() if m.health_status == AgentHealthStatus.FAILING),
            "total_risk_usage": total_risk_usage,
            "high_correlations": high_correlations,
            "average_success_rate": np.mean([m.success_rate for m in metrics_by_agent.values()]),
            "average_sharpe": np.mean([m.sharpe_ratio for m in metrics_by_agent.values()])
        }


    def get_drift_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get drift-triggered decisions history."""
        return self._drift_decisions[-limit:]
    
    def get_drift_status(self) -> Dict[str, Any]:
        """Get drift-related status."""
        try:
            drift_loop, _, _ = _get_drift_reward_loop()
            return {
                "drift_decisions_count": len(self._drift_decisions),
                "recent_decisions": self._drift_decisions[-5:],
                "loop_status": drift_loop.get_status(),
            }
        except Exception:
            return {"drift_decisions_count": len(self._drift_decisions)}


def get_governor_agent() -> GovernorAgent:
    """Get or create the governor agent."""
    registry = get_agent_registry()
    
    governor = registry.get_agent("governor_001")
    
    if not governor:
        governor = GovernorAgent()
        registry.register(governor)
    
    return governor
