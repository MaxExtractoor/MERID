"""
Simulation/Paper Trading Pipeline for MERID

Integrates LLM proposals with Execution Guard, simulation, paper trading,
and live execution with full audit trails.

Flow:
1. LLM proposes action via tool schema
2. Execution Guard validates permissions, risk limits, environment flags
3. If sim mode: route to simulator
4. If paper mode: route to paper trading engine
5. If live mode: route to live execution (with additional guards)
6. Record audit trail with explainability

Promotion path: sim → paper → guarded_live → full_live
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.execution_guard import get_execution_guard
from core.explainability import ExplanationContext, ExplanationType, get_explainability_service
from core.environment_flags import get_environment_flags
from utils.logger import get_logger

logger = get_logger("core.simulation_pipeline")


class ExecutionMode(str, Enum):
    """Execution mode for proposals."""
    SIMULATION = "simulation"
    PAPER = "paper"
    GUARDED_LIVE = "guarded_live"
    FULL_LIVE = "full_live"


class ProposalStatus(str, Enum):
    """Status of a proposal."""
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    SIMULATED = "simulated"
    PAPER_EXECUTED = "paper_executed"
    LIVE_EXECUTED = "live_executed"
    FAILED = "failed"


@dataclass
class ProposalResult:
    """Result of proposal execution."""
    proposal_id: str
    status: ProposalStatus
    mode: ExecutionMode
    action_type: str
    parameters: Dict[str, Any]
    
    # Validation
    guard_approved: bool = False
    guard_reason: str = ""
    
    # Execution results
    sim_result: Optional[Dict[str, Any]] = None
    paper_result: Optional[Dict[str, Any]] = None
    live_result: Optional[Dict[str, Any]] = None
    
    # Metrics
    execution_time_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    
    # Audit
    audit_id: str = ""
    explanation_id: str = ""


@dataclass
class PromotionCriteria:
    """Criteria for promoting from one mode to another."""
    min_sim_runs: int = 10
    min_sim_success_rate: float = 0.7
    min_paper_runs: int = 5
    min_paper_success_rate: float = 0.6
    max_paper_drawdown: float = 0.1
    min_sharpe_ratio: float = 0.5
    human_approval_required: bool = True


@dataclass
class StrategyPromotion:
    """Track strategy promotion through modes."""
    strategy_id: str
    current_mode: ExecutionMode
    
    sim_runs: int = 0
    sim_successes: int = 0
    sim_pnl: float = 0.0
    
    paper_runs: int = 0
    paper_successes: int = 0
    paper_pnl: float = 0.0
    paper_max_drawdown: float = 0.0
    
    live_runs: int = 0
    live_pnl: float = 0.0
    
    promoted_at: Dict[str, float] = field(default_factory=dict)
    human_approved: bool = False


class SimulationPipeline:
    """
    Pipeline for routing LLM proposals through sim → paper → live.
    
    Responsibilities:
    - Validate proposals through Execution Guard
    - Route to appropriate execution mode
    - Track promotion criteria
    - Record audit trails with explainability
    - Enforce offline/VPN policies
    """
    
    def __init__(self):
        self._execution_guard = get_execution_guard()
        self._explainability = get_explainability_service()
        self._env_flags = get_environment_flags()
        
        # Execution handlers
        self._sim_handler: Optional[Callable] = None
        self._paper_handler: Optional[Callable] = None
        self._live_handler: Optional[Callable] = None
        
        # Strategy tracking
        self._strategy_promotions: Dict[str, StrategyPromotion] = {}
        self._promotion_criteria = PromotionCriteria()
        
        # Audit trail
        self._proposal_history: List[ProposalResult] = []
        self._proposal_counter = 0
        
        logger.info("SimulationPipeline initialized")
    
    def register_sim_handler(self, handler: Callable) -> None:
        """Register simulation execution handler."""
        self._sim_handler = handler
        logger.info("Simulation handler registered")
    
    def register_paper_handler(self, handler: Callable) -> None:
        """Register paper trading execution handler."""
        self._paper_handler = handler
        logger.info("Paper trading handler registered")
    
    def register_live_handler(self, handler: Callable) -> None:
        """Register live execution handler."""
        self._live_handler = handler
        logger.info("Live execution handler registered")
    
    def process_proposal(
        self,
        action_type: str,
        parameters: Dict[str, Any],
        agent_id: str,
        strategy_id: Optional[str] = None,
        force_mode: Optional[ExecutionMode] = None,
    ) -> ProposalResult:
        """
        Process an LLM proposal through the pipeline.
        
        Args:
            action_type: Type of action (e.g., "propose_order", "adjust_parameter")
            parameters: Action parameters
            agent_id: ID of the proposing agent
            strategy_id: Optional strategy ID for promotion tracking
            force_mode: Force a specific execution mode
            
        Returns:
            ProposalResult with execution details
        """
        self._proposal_counter += 1
        proposal_id = f"prop_{self._proposal_counter:08d}_{int(time.time())}"
        
        start_time = time.time()
        
        # Determine execution mode
        mode = force_mode or self._determine_mode(strategy_id)
        
        # Check offline mode
        if self._env_flags.offline_mode and mode in {ExecutionMode.GUARDED_LIVE, ExecutionMode.FULL_LIVE}:
            mode = ExecutionMode.SIMULATION
            logger.warning("Downgraded to simulation mode due to offline flag")
        
        result = ProposalResult(
            proposal_id=proposal_id,
            status=ProposalStatus.PENDING,
            mode=mode,
            action_type=action_type,
            parameters=parameters,
        )
        
        # Step 1: Validate through Execution Guard
        guard_result = self._validate_with_guard(action_type, parameters, agent_id, mode)
        result.guard_approved = guard_result["approved"]
        result.guard_reason = guard_result.get("reason", "")
        
        if not result.guard_approved:
            result.status = ProposalStatus.REJECTED
            self._record_audit(result, agent_id, "guard_rejected")
            return result
        
        result.status = ProposalStatus.VALIDATED
        
        # Step 2: Execute based on mode
        try:
            if mode == ExecutionMode.SIMULATION:
                result = self._execute_simulation(result, parameters)
            elif mode == ExecutionMode.PAPER:
                result = self._execute_paper(result, parameters)
            elif mode in {ExecutionMode.GUARDED_LIVE, ExecutionMode.FULL_LIVE}:
                result = self._execute_live(result, parameters, mode)
        except Exception as e:
            result.status = ProposalStatus.FAILED
            result.guard_reason = str(e)
            logger.error("Proposal execution failed: %s", e)
        
        # Step 3: Update promotion tracking
        if strategy_id:
            self._update_promotion_tracking(strategy_id, result)
        
        # Step 4: Record audit trail
        result.execution_time_ms = (time.time() - start_time) * 1000
        self._record_audit(result, agent_id, "executed")
        
        # Store in history
        self._proposal_history.append(result)
        if len(self._proposal_history) > 1000:
            self._proposal_history = self._proposal_history[-1000:]
        
        logger.info(
            "Proposal %s: mode=%s, status=%s, time=%.1fms",
            proposal_id,
            mode.value,
            result.status.value,
            result.execution_time_ms,
        )
        
        return result
    
    def _determine_mode(self, strategy_id: Optional[str]) -> ExecutionMode:
        """Determine execution mode based on strategy promotion status."""
        if not strategy_id:
            return ExecutionMode.SIMULATION
        
        if strategy_id not in self._strategy_promotions:
            self._strategy_promotions[strategy_id] = StrategyPromotion(
                strategy_id=strategy_id,
                current_mode=ExecutionMode.SIMULATION,
            )
        
        return self._strategy_promotions[strategy_id].current_mode
    
    def _validate_with_guard(
        self,
        action_type: str,
        parameters: Dict[str, Any],
        agent_id: str,
        mode: ExecutionMode,
    ) -> Dict[str, Any]:
        """Validate proposal with Execution Guard."""
        # Build context for guard
        context = {
            "action_type": action_type,
            "parameters": parameters,
            "agent_id": agent_id,
            "execution_mode": mode.value,
            "offline_mode": self._env_flags.offline_mode,
        }
        
        # Check with execution guard
        result = self._execution_guard.validate_action(
            action_type=action_type,
            agent_id=agent_id,
            parameters=parameters,
        )
        
        return {
            "approved": result.get("approved", False),
            "reason": result.get("reason", ""),
            "risk_score": result.get("risk_score", 0.0),
        }
    
    def _execute_simulation(
        self,
        result: ProposalResult,
        parameters: Dict[str, Any],
    ) -> ProposalResult:
        """Execute in simulation mode."""
        if self._sim_handler:
            sim_result = self._sim_handler(result.action_type, parameters)
            result.sim_result = sim_result
        else:
            # Default simulation
            result.sim_result = {
                "simulated": True,
                "mock_pnl": 0.0,
                "mock_fill_price": parameters.get("price", 0.0),
            }
        
        result.status = ProposalStatus.SIMULATED
        return result
    
    def _execute_paper(
        self,
        result: ProposalResult,
        parameters: Dict[str, Any],
    ) -> ProposalResult:
        """Execute in paper trading mode."""
        if self._paper_handler:
            paper_result = self._paper_handler(result.action_type, parameters)
            result.paper_result = paper_result
        else:
            # Default paper execution
            result.paper_result = {
                "paper_executed": True,
                "paper_order_id": f"paper_{result.proposal_id}",
            }
        
        result.status = ProposalStatus.PAPER_EXECUTED
        return result
    
    def _execute_live(
        self,
        result: ProposalResult,
        parameters: Dict[str, Any],
        mode: ExecutionMode,
    ) -> ProposalResult:
        """Execute in live mode (guarded or full)."""
        # Additional safety checks for live
        if mode == ExecutionMode.GUARDED_LIVE:
            # Apply additional risk limits
            size = parameters.get("size", 0.0)
            max_size = parameters.get("max_size", 1000.0)
            if size > max_size * 0.5:
                parameters["size"] = max_size * 0.5
                logger.warning("Reduced size due to guarded mode")
        
        if self._live_handler:
            live_result = self._live_handler(result.action_type, parameters)
            result.live_result = live_result
        else:
            # No live handler - reject
            result.status = ProposalStatus.REJECTED
            result.guard_reason = "No live handler registered"
            return result
        
        result.status = ProposalStatus.LIVE_EXECUTED
        return result
    
    def _update_promotion_tracking(
        self,
        strategy_id: str,
        result: ProposalResult,
    ) -> None:
        """Update promotion tracking for strategy."""
        promo = self._strategy_promotions.get(strategy_id)
        if not promo:
            return
        
        success = result.status in {
            ProposalStatus.SIMULATED,
            ProposalStatus.PAPER_EXECUTED,
            ProposalStatus.LIVE_EXECUTED,
        }
        
        if result.mode == ExecutionMode.SIMULATION:
            promo.sim_runs += 1
            if success:
                promo.sim_successes += 1
                pnl = (result.sim_result or {}).get("mock_pnl", 0.0)
                promo.sim_pnl += pnl
        
        elif result.mode == ExecutionMode.PAPER:
            promo.paper_runs += 1
            if success:
                promo.paper_successes += 1
                pnl = (result.paper_result or {}).get("pnl", 0.0)
                promo.paper_pnl += pnl
        
        elif result.mode in {ExecutionMode.GUARDED_LIVE, ExecutionMode.FULL_LIVE}:
            promo.live_runs += 1
            pnl = (result.live_result or {}).get("pnl", 0.0)
            promo.live_pnl += pnl
    
    def _record_audit(
        self,
        result: ProposalResult,
        agent_id: str,
        event_type: str,
    ) -> None:
        """Record audit trail with explainability."""
        context = ExplanationContext(
            inputs={
                "proposal_id": result.proposal_id,
                "action_type": result.action_type,
                "parameters": result.parameters,
                "mode": result.mode.value,
            },
            agent_id=agent_id,
            strategy=None,
            constraints={
                "guard_approved": result.guard_approved,
                "guard_reason": result.guard_reason,
            },
            expected_effect={
                "status": result.status.value,
                "execution_time_ms": result.execution_time_ms,
            },
            environment_flags={
                "offline_mode": self._env_flags.offline_mode,
            },
        )
        
        explanation_id = self._explainability.record_explanation(
            explanation_type=ExplanationType.TRADE_EXECUTION,
            summary=f"Pipeline {event_type}: {result.action_type} ({result.mode.value})",
            context=context,
            expert_notes=f"Status: {result.status.value}, Guard: {result.guard_reason}",
        )
        
        result.explanation_id = explanation_id
        result.audit_id = f"audit_{result.proposal_id}"
    
    def check_promotion_eligibility(
        self,
        strategy_id: str,
    ) -> Dict[str, Any]:
        """Check if strategy is eligible for promotion."""
        promo = self._strategy_promotions.get(strategy_id)
        if not promo:
            return {"eligible": False, "reason": "Strategy not tracked"}
        
        criteria = self._promotion_criteria
        current = promo.current_mode
        
        if current == ExecutionMode.SIMULATION:
            # Check for paper promotion
            if promo.sim_runs < criteria.min_sim_runs:
                return {
                    "eligible": False,
                    "reason": f"Need {criteria.min_sim_runs - promo.sim_runs} more sim runs",
                }
            
            success_rate = promo.sim_successes / promo.sim_runs if promo.sim_runs > 0 else 0
            if success_rate < criteria.min_sim_success_rate:
                return {
                    "eligible": False,
                    "reason": f"Sim success rate {success_rate:.1%} < {criteria.min_sim_success_rate:.1%}",
                }
            
            return {
                "eligible": True,
                "next_mode": ExecutionMode.PAPER.value,
                "metrics": {
                    "sim_runs": promo.sim_runs,
                    "sim_success_rate": success_rate,
                    "sim_pnl": promo.sim_pnl,
                },
            }
        
        elif current == ExecutionMode.PAPER:
            # Check for guarded live promotion
            if promo.paper_runs < criteria.min_paper_runs:
                return {
                    "eligible": False,
                    "reason": f"Need {criteria.min_paper_runs - promo.paper_runs} more paper runs",
                }
            
            success_rate = promo.paper_successes / promo.paper_runs if promo.paper_runs > 0 else 0
            if success_rate < criteria.min_paper_success_rate:
                return {
                    "eligible": False,
                    "reason": f"Paper success rate {success_rate:.1%} < {criteria.min_paper_success_rate:.1%}",
                }
            
            if promo.paper_max_drawdown > criteria.max_paper_drawdown:
                return {
                    "eligible": False,
                    "reason": f"Paper drawdown {promo.paper_max_drawdown:.1%} > {criteria.max_paper_drawdown:.1%}",
                }
            
            if criteria.human_approval_required and not promo.human_approved:
                return {
                    "eligible": False,
                    "reason": "Human approval required for live promotion",
                    "awaiting_approval": True,
                }
            
            return {
                "eligible": True,
                "next_mode": ExecutionMode.GUARDED_LIVE.value,
                "metrics": {
                    "paper_runs": promo.paper_runs,
                    "paper_success_rate": success_rate,
                    "paper_pnl": promo.paper_pnl,
                    "paper_max_drawdown": promo.paper_max_drawdown,
                },
            }
        
        elif current == ExecutionMode.GUARDED_LIVE:
            # Check for full live promotion
            if promo.live_runs < 10:
                return {
                    "eligible": False,
                    "reason": f"Need {10 - promo.live_runs} more guarded live runs",
                }
            
            return {
                "eligible": True,
                "next_mode": ExecutionMode.FULL_LIVE.value,
                "metrics": {
                    "live_runs": promo.live_runs,
                    "live_pnl": promo.live_pnl,
                },
            }
        
        return {"eligible": False, "reason": "Already at full live"}
    
    def promote_strategy(
        self,
        strategy_id: str,
        human_approved: bool = False,
    ) -> Dict[str, Any]:
        """Promote strategy to next execution mode."""
        eligibility = self.check_promotion_eligibility(strategy_id)
        
        if not eligibility.get("eligible"):
            return {
                "promoted": False,
                "reason": eligibility.get("reason"),
            }
        
        promo = self._strategy_promotions[strategy_id]
        old_mode = promo.current_mode
        new_mode = ExecutionMode(eligibility["next_mode"])
        
        # Update human approval if provided
        if human_approved:
            promo.human_approved = True
        
        # Check human approval for paper → live
        if old_mode == ExecutionMode.PAPER and not promo.human_approved:
            return {
                "promoted": False,
                "reason": "Human approval required",
            }
        
        promo.current_mode = new_mode
        promo.promoted_at[new_mode.value] = time.time()
        
        logger.info(
            "Strategy %s promoted: %s → %s",
            strategy_id,
            old_mode.value,
            new_mode.value,
        )
        
        # Record promotion in audit
        self._explainability.record_explanation(
            explanation_type=ExplanationType.GOVERNANCE_DECISION,
            summary=f"Strategy promotion: {strategy_id} → {new_mode.value}",
            context=ExplanationContext(
                inputs={"strategy_id": strategy_id, "old_mode": old_mode.value},
                agent_id="simulation_pipeline",
                strategy=strategy_id,
                constraints=eligibility.get("metrics", {}),
                expected_effect={"new_mode": new_mode.value},
                environment_flags={},
            ),
            expert_notes=f"Promoted based on metrics: {eligibility.get('metrics')}",
        )
        
        return {
            "promoted": True,
            "old_mode": old_mode.value,
            "new_mode": new_mode.value,
            "metrics": eligibility.get("metrics"),
        }
    
    def demote_strategy(
        self,
        strategy_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Demote strategy to lower execution mode."""
        promo = self._strategy_promotions.get(strategy_id)
        if not promo:
            return {"demoted": False, "reason": "Strategy not tracked"}
        
        old_mode = promo.current_mode
        
        # Determine demotion target
        demotion_map = {
            ExecutionMode.FULL_LIVE: ExecutionMode.GUARDED_LIVE,
            ExecutionMode.GUARDED_LIVE: ExecutionMode.PAPER,
            ExecutionMode.PAPER: ExecutionMode.SIMULATION,
            ExecutionMode.SIMULATION: ExecutionMode.SIMULATION,
        }
        
        new_mode = demotion_map[old_mode]
        
        if new_mode == old_mode:
            return {"demoted": False, "reason": "Already at lowest mode"}
        
        promo.current_mode = new_mode
        promo.human_approved = False  # Require re-approval
        
        logger.warning(
            "Strategy %s demoted: %s → %s (reason: %s)",
            strategy_id,
            old_mode.value,
            new_mode.value,
            reason,
        )
        
        return {
            "demoted": True,
            "old_mode": old_mode.value,
            "new_mode": new_mode.value,
            "reason": reason,
        }
    
    def get_strategy_status(self, strategy_id: str) -> Dict[str, Any]:
        """Get strategy promotion status."""
        promo = self._strategy_promotions.get(strategy_id)
        if not promo:
            return {"tracked": False}
        
        return {
            "tracked": True,
            "strategy_id": strategy_id,
            "current_mode": promo.current_mode.value,
            "sim_runs": promo.sim_runs,
            "sim_successes": promo.sim_successes,
            "sim_pnl": promo.sim_pnl,
            "paper_runs": promo.paper_runs,
            "paper_successes": promo.paper_successes,
            "paper_pnl": promo.paper_pnl,
            "live_runs": promo.live_runs,
            "live_pnl": promo.live_pnl,
            "human_approved": promo.human_approved,
            "promoted_at": promo.promoted_at,
        }
    
    def get_pipeline_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        total = len(self._proposal_history)
        
        by_status = {}
        by_mode = {}
        
        for result in self._proposal_history:
            status = result.status.value
            mode = result.mode.value
            
            by_status[status] = by_status.get(status, 0) + 1
            by_mode[mode] = by_mode.get(mode, 0) + 1
        
        avg_time = sum(r.execution_time_ms for r in self._proposal_history) / max(total, 1)
        
        return {
            "total_proposals": total,
            "by_status": by_status,
            "by_mode": by_mode,
            "avg_execution_time_ms": avg_time,
            "strategies_tracked": len(self._strategy_promotions),
        }
    
    def get_recent_proposals(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent proposals."""
        return [
            {
                "proposal_id": r.proposal_id,
                "status": r.status.value,
                "mode": r.mode.value,
                "action_type": r.action_type,
                "guard_approved": r.guard_approved,
                "execution_time_ms": r.execution_time_ms,
                "timestamp": r.timestamp,
            }
            for r in self._proposal_history[-limit:]
        ]


# Singleton instance
_simulation_pipeline: Optional[SimulationPipeline] = None
_simulation_pipeline_lock = threading.Lock()


def get_simulation_pipeline() -> SimulationPipeline:
    """Get the singleton simulation pipeline."""
    global _simulation_pipeline
    if _simulation_pipeline is None:
        with _simulation_pipeline_lock:
            if _simulation_pipeline is None:
                _simulation_pipeline = SimulationPipeline()
    return _simulation_pipeline
