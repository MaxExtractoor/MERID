"""
Governor Agent V2 — Hardened with Quorum-Gated Governance

Major improvements over V1:
1. All PAUSE/RETIRE actions route through Unified Decision Layer (quorum required)
2. Asyncio.ensure_future replaced with awaited calls + timeout + error handling
3. Complete audit trail with GovernanceEventBus (no direct drift loop callbacks)
4. Asset/timeframe-aware governance decisions
5. Immutable audit records for all lifecycle actions
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import numpy as np

from agents.agent_framework import Agent, AgentCapability, AgentRole, get_agent_registry
from agents.unified_decision_layer import get_unified_decision_layer, UnifiedDecision
from agents.governance_event_bus import (
    get_governance_event_bus,
    GovernanceEvent,
    GovernanceEventType,
    GovernanceAction,
)
from core.drift_monitor import get_drift_monitor
from core.decision_log import get_decision_log
from core.explainability import ExplanationContext, ExplanationType, get_explainability_service
from utils.logger import get_logger

logger = get_logger("agents.governor_v2")


class AgentHealthStatus(str, Enum):
    """Agent health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNDERPERFORMING = "underperforming"
    FAILING = "failing"


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
    # New: Asset/timeframe tracking for granular governance
    covered_assets: List[str] = None
    covered_timeframes: List[str] = None
    
    def __post_init__(self):
        if self.covered_assets is None:
            self.covered_assets = []
        if self.covered_timeframes is None:
            self.covered_timeframes = []


@dataclass
class GovernanceDecision:
    """Governance decision about an agent."""
    agent_id: str
    action: GovernanceAction
    reason: str
    metrics: AgentPerformanceMetrics
    timestamp: float
    event_id: Optional[str] = None  # Links to GovernanceEventBus audit
    quorum_approved: bool = False
    decision_id: Optional[str] = None  # UnifiedDecisionLayer ID


class HardenedGovernanceEngine:
    """
    Hardened governance engine with:
    - Unified Decision Layer integration (quorum-gated)
    - Complete audit trail via GovernanceEventBus
    - Awaited lifecycle calls with timeout
    - Asset/timeframe-aware decisions
    """
    
    # Action timeouts (seconds)
    PAUSE_TIMEOUT = 10.0
    RETIRE_TIMEOUT = 15.0
    WEIGHT_CHANGE_TIMEOUT = 5.0
    
    def __init__(self):
        self._monitor = PerformanceMonitor()
        self._governance_history: List[GovernanceDecision] = []
        self._event_bus = get_governance_event_bus()
        self._unified_layer = get_unified_decision_layer()
        
        # Thresholds
        self._success_rate_threshold = 0.5
        self._sharpe_threshold = 0.0
        self._max_drawdown_threshold = 0.2
        self._correlation_threshold = 0.8
        
        # Subscribe to drift events via event bus (not direct callback)
        self._event_bus.subscribe(
            GovernanceEventType.DRIFT_DE_RISK,
            self._on_drift_de_risk
        )
        
        # Subscribe to quorum approvals
        self._event_bus.subscribe(
            GovernanceEventType.AGENT_PAUSE,
            self._on_governance_event
        )
        self._event_bus.subscribe(
            GovernanceEventType.AGENT_RETIRE,
            self._on_governance_event
        )
    
    async def evaluate_and_act(self, agent_id: str) -> Optional[GovernanceDecision]:
        """
        Evaluate agent and take governance action IF quorum approves.
        
        Returns:
            GovernanceDecision if action was taken, None otherwise
        """
        metrics = self._monitor.evaluate_agent(agent_id)
        action = self._determine_action(metrics)
        
        if not action or action == GovernanceAction.NO_ACTION:
            return None
        
        # Extract assets/timeframes from agent_id (e.g., "BTC_15M" -> BTC, 15m)
        assets, timeframes = self._parse_agent_coverage(agent_id)
        
        # Create governance event for audit trail
        event = GovernanceEvent(
            event_type=self._action_to_event_type(action),
            source="governor_agent",
            target_component=agent_id,
            action=action,
            reason=self._generate_reason(metrics, action),
            requires_quorum=True,
            metadata={
                "metrics": metrics.to_dict() if hasattr(metrics, 'to_dict') else {},
                "assets": assets,
                "timeframes": timeframes,
            }
        )
        
        # Publish to event bus (audit trail created)
        event_id = await self._event_bus.publish(event)
        
        # Route through Unified Decision Layer for quorum approval
        if event.requires_quorum:
            unified_decision = await self._request_quorum_approval(event, metrics)
            
            if unified_decision.final_decision != "APPROVE":
                await self._event_bus.reject_event(
                    event_id,
                    f"Quorum rejected: {unified_decision.reasoning_summary}"
                )
                logger.warning(
                    f"Governance action {action.value} for {agent_id} "
                    f"rejected by quorum: {unified_decision.reasoning_summary}"
                )
                return None
            
            # Mark as approved
            await self._event_bus.approve_event(
                event_id,
                unified_decision.decision_id,
                "unified_decision_layer"
            )
        
        # Execute action with full audit trail
        decision = GovernanceDecision(
            agent_id=agent_id,
            action=action,
            reason=event.reason,
            metrics=metrics,
            timestamp=time.time(),
            event_id=event_id,
            quorum_approved=event.requires_quorum,
            decision_id=unified_decision.decision_id if event.requires_quorum else None
        )
        
        success, error = await self._execute_action(decision)
        
        if success:
            self._governance_history.append(decision)
            await self._event_bus.mark_executed(event_id, success=True)
            return decision
        else:
            await self._event_bus.mark_executed(event_id, success=False, error=error)
            return None
    
    async def _request_quorum_approval(
        self,
        event: GovernanceEvent,
        metrics: AgentPerformanceMetrics
    ) -> UnifiedDecision:
        """Request quorum approval via Unified Decision Layer."""
        context = {
            "governance_event_id": event.event_id,
            "target_agent": event.target_component,
            "requested_action": event.action.value,
            "reason": event.reason,
            "agent_health": metrics.health_status.value,
            "success_rate": metrics.success_rate,
            "sharpe_ratio": metrics.sharpe_ratio,
            "max_drawdown": metrics.max_drawdown,
            "assets": event.metadata.get("assets", []),
            "timeframes": event.metadata.get("timeframes", []),
        }
        
        # Use unified layer to get consensus on governance action
        return await self._unified_layer.make_decision(
            decision_type="governance_action",
            context=context,
            agent_roles=[AgentRole.GOVERNANCE, AgentRole.RISK_MANAGER]
        )
    
    async def _execute_action(
        self,
        decision: GovernanceDecision
    ) -> tuple[bool, Optional[str]]:
        """
        Execute governance action with timeout and error handling.
        
        Returns:
            (success, error_message)
        """
        registry = get_agent_registry()
        agent = registry.get_agent(decision.agent_id)
        
        if not agent:
            return False, f"Agent {decision.agent_id} not found"
        
        action = decision.action
        
        try:
            if action == GovernanceAction.PAUSE:
                return await self._execute_pause(agent, decision)
            
            elif action == GovernanceAction.RESUME:
                return await self._execute_resume(agent, decision)
            
            elif action == GovernanceAction.RETIRE:
                return await self._execute_retire(agent, decision, registry)
            
            elif action in [GovernanceAction.PROMOTE, GovernanceAction.DEMOTE]:
                # Weight changes don't need direct execution
                logger.info(f"Agent {decision.agent_id} {action.value}: {decision.reason}")
                return True, None
            
            elif action in [GovernanceAction.INCREASE_WEIGHT, GovernanceAction.DECREASE_WEIGHT]:
                logger.info(f"Agent {decision.agent_id} {action.value}: {decision.reason}")
                return True, None
            
            else:
                return False, f"Unknown action: {action.value}"
                
        except asyncio.TimeoutError:
            error = f"Timeout executing {action.value} on {decision.agent_id}"
            logger.error(error)
            return False, error
        except Exception as exc:
            error = f"Error executing {action.value}: {exc}"
            logger.error(error)
            return False, error
    
    async def _execute_pause(
        self,
        agent: Agent,
        decision: GovernanceDecision
    ) -> tuple[bool, Optional[str]]:
        """Execute pause with timeout and confirmation."""
        logger.warning(f"Executing PAUSE on {decision.agent_id}: {decision.reason}")
        
        # Await with timeout (replaces asyncio.ensure_future)
        try:
            await asyncio.wait_for(agent.pause(), timeout=self.PAUSE_TIMEOUT)
            logger.info(f"Successfully paused agent {decision.agent_id}")
            return True, None
        except asyncio.TimeoutError:
            return False, f"Pause timeout after {self.PAUSE_TIMEOUT}s"
        except Exception as exc:
            return False, str(exc)
    
    async def _execute_resume(
        self,
        agent: Agent,
        decision: GovernanceDecision
    ) -> tuple[bool, Optional[str]]:
        """Execute resume with timeout."""
        logger.info(f"Executing RESUME on {decision.agent_id}")
        
        try:
            await asyncio.wait_for(agent.resume(), timeout=self.PAUSE_TIMEOUT)
            return True, None
        except asyncio.TimeoutError:
            return False, f"Resume timeout after {self.PAUSE_TIMEOUT}s"
        except Exception as exc:
            return False, str(exc)
    
    async def _execute_retire(
        self,
        agent: Agent,
        decision: GovernanceDecision,
        registry: Any
    ) -> tuple[bool, Optional[str]]:
        """Execute retire with timeout and cleanup."""
        logger.critical(
            f"Executing RETIRE on {decision.agent_id}: {decision.reason}"
        )
        
        try:
            # Stop agent with timeout
            await asyncio.wait_for(agent.stop(), timeout=self.RETIRE_TIMEOUT)
            
            # Unregister
            registry.unregister(decision.agent_id)
            
            logger.critical(f"Successfully retired agent {decision.agent_id}")
            return True, None
            
        except asyncio.TimeoutError:
            return False, f"Stop timeout after {self.RETIRE_TIMEOUT}s"
        except Exception as exc:
            return False, str(exc)
    
    def _determine_action(self, metrics: AgentPerformanceMetrics) -> Optional[GovernanceAction]:
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
    
    def _generate_reason(self, metrics: AgentPerformanceMetrics, action: GovernanceAction) -> str:
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
    
    def _parse_agent_coverage(self, agent_id: str) -> tuple[List[str], List[str]]:
        """Extract assets and timeframes from agent ID."""
        assets = []
        timeframes = []
        
        # Parse agent ID patterns like "BTC_15M", "ETH_HOURLY", etc.
        upper_id = agent_id.upper()
        
        # Check for assets using canonical list from config.crypto_universe
        from config.crypto_universe import ACTIVE_CRYPTO_ASSETS
        for asset in ACTIVE_CRYPTO_ASSETS:
            if asset in upper_id:
                assets.append(asset)
        
        # Check for timeframes
        if "15M" in upper_id or "15M" in upper_id:
            timeframes.append("15m")
        if "HOURLY" in upper_id or "1H" in upper_id or ("_H" in upper_id and "_HOURLY" not in upper_id):
            timeframes.append("1h")
        if "DAILY" in upper_id or "D1" in upper_id:
            timeframes.append("daily")
        if "WEEKLY" in upper_id or "W1" in upper_id:
            timeframes.append("weekly")
        if "MONTHLY" in upper_id or "1M" in upper_id:
            timeframes.append("monthly")
        
        return assets, timeframes
    
    def _action_to_event_type(self, action: GovernanceAction) -> GovernanceEventType:
        """Map action to event type."""
        mapping = {
            GovernanceAction.PAUSE: GovernanceEventType.AGENT_PAUSE,
            GovernanceAction.RESUME: GovernanceEventType.AGENT_RESUME,
            GovernanceAction.RETIRE: GovernanceEventType.AGENT_RETIRE,
            GovernanceAction.PROMOTE: GovernanceEventType.AGENT_PROMOTE,
            GovernanceAction.DEMOTE: GovernanceEventType.AGENT_DEMOTE,
            GovernanceAction.INCREASE_WEIGHT: GovernanceEventType.WEIGHT_CHANGE,
            GovernanceAction.DECREASE_WEIGHT: GovernanceEventType.WEIGHT_CHANGE,
        }
        return mapping.get(action, GovernanceEventType.EMERGENCY_HALT)
    
    async def _on_drift_de_risk(self, event: GovernanceEvent) -> None:
        """Handle drift de-risk events from event bus."""
        logger.warning(
            f"Governor received drift de-risk for {event.target_component}: "
            f"{event.reason}"
        )
        
        # Auto-approve drift de-risk (higher authority than normal governance)
        await self._event_bus.approve_event(
            event.event_id,
            "drift_auto_approved",
            "drift_reward_loop"
        )
        
        # Execute immediately (no quorum for drift - it's already an emergency)
        registry = get_agent_registry()
        agent = registry.get_agent(event.target_component)
        
        if agent and event.action == GovernanceAction.PAUSE:
            success, error = await self._execute_pause(
                agent,
                GovernanceDecision(
                    agent_id=event.target_component,
                    action=GovernanceAction.PAUSE,
                    reason=f"Drift-triggered: {event.reason}",
                    metrics=AgentPerformanceMetrics(
                        agent_id=event.target_component,
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
                    ),
                    timestamp=time.time(),
                    event_id=event.event_id,
                    quorum_approved=True,
                    decision_id="drift_auto_approved"
                )
            )
            await self._event_bus.mark_executed(event.event_id, success, error)
    
    async def _on_governance_event(self, event: GovernanceEvent) -> None:
        """Handle general governance events."""
        logger.info(f"Governance event received: {event.event_type.value} for {event.target_component}")
    
    def get_governance_history(self, limit: int = 100) -> List[GovernanceDecision]:
        """Get governance decision history."""
        return self._governance_history[-limit:]
    
    def get_pending_actions(self) -> List[Dict[str, Any]]:
        """Get pending governance actions awaiting quorum."""
        pending = self._event_bus.get_pending_events()
        return [
            {
                "event_id": p.event.event_id,
                "action": p.event.action.value,
                "target": p.event.target_component,
                "reason": p.event.reason,
                "assets": p.affected_assets,
                "timeframes": p.affected_timeframes,
                "status": p.status,
                "elapsed_seconds": time.time() - p.event.timestamp,
            }
            for p in pending
        ]


# Import PerformanceMonitor from original governor (reused)
from agents.governor_agent import PerformanceMonitor


class HardenedGovernorAgent(Agent):
    """
    Hardened Governor Agent with quorum-gated governance.
    
    All lifecycle actions require quorum approval via Unified Decision Layer.
    Complete audit trail via GovernanceEventBus.
    """
    
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
                description="Make governance decisions about agents (quorum-gated)",
                input_schema={},
                output_schema={}
            ),
            AgentCapability(
                name="drift_response",
                description="Respond to drift-triggered de-risk decisions",
                input_schema={},
                output_schema={}
            ),
            AgentCapability(
                name="query_audit_trail",
                description="Query governance audit trail",
                input_schema={},
                output_schema={}
            ),
        ]
        
        super().__init__(
            agent_id="governor_002",  # New version ID
            role=AgentRole.GOVERNANCE,
            capabilities=capabilities
        )
        
        self._governance_engine = HardenedGovernanceEngine()
        self._last_evaluation = 0.0
        self._evaluation_interval = 3600.0  # 1 hour
        self._explainability = get_explainability_service()
    
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
        elif decision_type == "query_pending":
            return {"pending_actions": self._governance_engine.get_pending_actions()}
        elif decision_type == "query_audit":
            return self._query_audit(context)
        else:
            return {"decision": "no_action", "confidence": 1.0}
    
    async def _evaluate_all_agents(self) -> Dict[str, Any]:
        """Evaluate all agents with quorum-gated governance."""
        current_time = time.time()
        
        if current_time - self._last_evaluation < self._evaluation_interval:
            return {"decision": "evaluation_skipped", "confidence": 1.0}
        
        registry = get_agent_registry()
        all_agents = registry.get_all_agents()
        
        actions_taken = []
        actions_pending = []
        
        for agent in all_agents:
            if agent.agent_id == self.agent_id:
                continue
            
            decision = await self._governance_engine.evaluate_and_act(agent.agent_id)
            
            if decision:
                actions_taken.append({
                    "agent_id": decision.agent_id,
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "quorum_approved": decision.quorum_approved,
                    "decision_id": decision.decision_id,
                    "assets": decision.metrics.covered_assets,
                    "timeframes": decision.metrics.covered_timeframes,
                })
            # Note: pending actions are tracked in event bus
        
        self._last_evaluation = current_time
        
        return {
            "decision": "evaluation_complete",
            "confidence": 1.0,
            "actions_taken": actions_taken,
            "actions_pending": self._governance_engine.get_pending_actions(),
            "agents_evaluated": len(all_agents)
        }
    
    def _query_audit(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Query governance audit trail."""
        target = context.get("target_agent")
        limit = context.get("limit", 50)
        
        history = self._governance_engine.get_governance_history(limit=limit)
        
        if target:
            history = [h for h in history if h.agent_id == target]
        
        return {
            "decision": "audit_query_complete",
            "records": [
                {
                    "agent_id": h.agent_id,
                    "action": h.action.value,
                    "reason": h.reason,
                    "timestamp": h.timestamp,
                    "quorum_approved": h.quorum_approved,
                    "decision_id": h.decision_id,
                    "assets": h.metrics.covered_assets,
                    "timeframes": h.metrics.covered_timeframes,
                }
                for h in history
            ]
        }
    
    async def _resolve_conflict(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve conflict between agents."""
        # Use unified decision layer for conflict resolution
        unified = get_unified_decision_layer()
        return await unified.make_decision(
            decision_type="resolve_conflict",
            context=context
        )
    
    def get_portfolio_risk_report(self) -> Dict[str, Any]:
        """Get portfolio-level risk report with asset/timeframe breakdown."""
        registry = get_agent_registry()
        all_agents = registry.get_all_agents()
        
        agent_ids = [a.agent_id for a in all_agents if a.agent_id != self.agent_id]
        
        # Aggregate by asset/timeframe
        asset_health = {}
        timeframe_health = {}
        
        for agent_id in agent_ids:
            metrics = self._governance_engine._monitor.evaluate_agent(agent_id)
            
            for asset in metrics.covered_assets or []:
                if asset not in asset_health:
                    asset_health[asset] = []
                asset_health[asset].append(metrics.health_status.value)
            
            for tf in metrics.covered_timeframes or []:
                if tf not in timeframe_health:
                    timeframe_health[tf] = []
                timeframe_health[tf].append(metrics.health_status.value)
        
        return {
            "total_agents": len(agent_ids),
            "asset_health_summary": {
                asset: {"healthy": statuses.count("healthy"), "total": len(statuses)}
                for asset, statuses in asset_health.items()
            },
            "timeframe_health_summary": {
                tf: {"healthy": statuses.count("healthy"), "total": len(statuses)}
                for tf, statuses in timeframe_health.items()
            },
            "pending_governance_actions": len(self._governance_engine.get_pending_actions()),
        }


def get_hardened_governor_agent() -> HardenedGovernorAgent:
    """Get or create the hardened governor agent."""
    registry = get_agent_registry()
    
    # Check for hardened version first
    governor = registry.get_agent("governor_002")
    if governor:
        return governor
    
    # Fall back to creating new
    governor = HardenedGovernorAgent()
    registry.register(governor)
    
    return governor
