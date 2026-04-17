"""
Unified Decision Layer for MERID
Aggregates agent outputs with audit trail and explainability.
"""
from __future__ import annotations

import threading
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.agent_framework import Agent, AgentRole, get_agent_registry
from agents.quorum_hardening import (
    QuorumFailure,
    ValidatedQuorumConfig,
    require_quorum,
    format_quorum_alert,
    get_validated_quorum_config,
)
from agents.quorum_failure_tracker import get_quorum_failure_tracker
from agents.swarm_coordination import get_swarm_coordinator
from config.crypto_universe import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_TIMEFRAMES,
    get_quorum_config,
    parse_asset_timeframe_from_identifier,
)
from core.decision_log import AgentDecision, DecisionOutcome, get_decision_log
from core.environment import get_environment_flags
from core.explainability import (
    ExplanationContext,
    ExplanationType,
    get_explainability_service,
)
from utils.logger import get_logger

logger = get_logger("agents.unified_decision")


class DecisionPriority(Enum):
    """Decision priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AgentContribution:
    """Contribution from an agent to a decision."""
    agent_id: str
    agent_role: AgentRole
    recommendation: str
    confidence: float
    weight: float
    reasoning: str
    evidence: Dict[str, Any]
    timestamp: float


@dataclass
class UnifiedDecision:
    """Unified decision from swarm."""
    decision_id: str
    decision_type: str
    final_decision: str
    confidence: float
    priority: DecisionPriority
    contributions: List[AgentContribution]
    aggregation_method: str
    reasoning_summary: str
    timestamp: float
    metadata: Dict[str, Any]


class DecisionAggregator:
    """Aggregates decisions from multiple agents with hardened quorum handling."""
    
    def __init__(self):
        self._decision_counter = 0
        self._quorum_config = get_validated_quorum_config()
    
    def aggregate(
        self,
        decision_type: str,
        agent_decisions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> UnifiedDecision:
        """Aggregate agent decisions into unified decision."""
        self._decision_counter += 1
        decision_id = f"decision_{self._decision_counter}_{int(time.time())}"
        
        # Extract contributions
        contributions = []
        for decision in agent_decisions:
            contribution = AgentContribution(
                agent_id=decision.get("agent_id", "unknown"),
                agent_role=decision.get("agent_role", AgentRole.RESEARCH_SIGNAL),
                recommendation=decision.get("recommendation", ""),
                confidence=decision.get("confidence", 0.5),
                weight=decision.get("weight", 1.0),
                reasoning=decision.get("reasoning", ""),
                evidence=decision.get("evidence", {}),
                timestamp=time.time()
            )
            contributions.append(contribution)
        
        # Extract assets/timeframes from context for targeted quorum checking
        affected_assets = context.get("assets", [])
        affected_timeframes = context.get("timeframes", [])
        if not affected_assets:
            # Try to infer from decision_type or symbol
            symbol = context.get("symbol", "")
            if symbol:
                # Parse symbol like "KXBTC15M" or "BTC-15M"
                affected_assets = self._extract_assets_from_symbol(symbol)
                affected_timeframes = self._extract_timeframes_from_symbol(symbol)
        
        # T-010: Hardened quorum enforcement with explicit QuorumFailure
        effective_quorum = self._quorum_config.get_effective_quorum(
            affected_assets,
            affected_timeframes,
            emergency_override=context.get("emergency_override", False)
        )
        
        if len(contributions) < effective_quorum:
            # Use QuorumFailureTracker to prevent event storms (Finding 6.2)
            tracker = get_quorum_failure_tracker()
            
            should_alert, context = tracker.record_failure(
                asset=affected_assets[0] if affected_assets else "unknown",
                timeframe=affected_timeframes[0] if affected_timeframes else "unknown",
                decision_type=decision_type,
                agents_available=[c.agent_id for c in contributions],
                agents_required=effective_quorum,
            )
            
            # Only proceed with alert/action if not throttled
            if not should_alert:
                logger.warning(
                    f"Quorum failure throttled for {decision_type}: "
                    f"{context['consecutive_count']} consecutive failures, "
                    f"next alert in {context.get('seconds_until_next_alert', 'unknown')}s"
                )
            
            # Raise explicit QuorumFailure instead of silent NO_ACTION
            quorum_fail = QuorumFailure(
                message=f"Quorum not met for {decision_type}: {len(contributions)}/{effective_quorum} agents",
                min_quorum=effective_quorum,
                actual_contributions=len(contributions),
                decision_type=decision_type,
                affected_assets=affected_assets,
                affected_timeframes=affected_timeframes,
                contributing_agents=[c.agent_id for c in contributions],
                missing_agent_roles=[],
                metadata={
                    "context": context,
                    "quorum_config": self._quorum_config.to_dict(),
                    "throttled": not should_alert,
                }
            )
            
            # Log with full context
            logger.error(quorum_fail._format_human_readable())
            
            # Return QUORUM_FAILED decision (not NO_ACTION) for visibility
            return UnifiedDecision(
                decision_id=quorum_fail.event_id,
                decision_type=decision_type,
                final_decision="QUORUM_FAILED",
                confidence=0.0,
                priority=DecisionPriority.CRITICAL,  # Elevated from LOW
                contributions=contributions,
                aggregation_method="quorum_failed",
                reasoning_summary=quorum_fail._format_human_readable(),
                timestamp=time.time(),
                metadata={
                    **context,
                    "quorum_failure": quorum_fail.to_dict(),
                    "alert_payload": format_quorum_alert(quorum_fail),
                    "throttled": not should_alert,
                }
            )

        # Determine aggregation method
        if self._has_high_agreement(contributions):
            method = "consensus"
            final_decision, confidence = self._consensus_decision(contributions)
        else:
            method = "weighted_voting"
            final_decision, confidence = self._weighted_decision(contributions)
        
        # Generate reasoning summary
        reasoning_summary = self._generate_reasoning_summary(contributions, final_decision)
        
        # Determine priority
        priority = self._determine_priority(decision_type, confidence, context)
        
        return UnifiedDecision(
            decision_id=decision_id,
            decision_type=decision_type,
            final_decision=final_decision,
            confidence=confidence,
            priority=priority,
            contributions=contributions,
            aggregation_method=method,
            reasoning_summary=reasoning_summary,
            timestamp=time.time(),
            metadata=context
        )
    
    def _extract_assets_from_symbol(self, symbol: str) -> List[str]:
        """Extract asset symbols from market symbol using crypto_universe config."""
        assets = []
        symbol_upper = symbol.upper()
        for asset in ACTIVE_CRYPTO_ASSETS:  # Use config instead of hardcoded list
            if asset in symbol_upper:
                assets.append(asset)
        return assets
    
    def _extract_timeframes_from_symbol(self, symbol: str) -> List[str]:
        """Extract timeframe from market symbol using crypto_universe config."""
        symbol_upper = symbol.upper()
        
        # Check canonical names first from config
        for tf in ACTIVE_CRYPTO_TIMEFRAMES:
            tf_upper = tf.upper()
            if tf_upper == "15M" and ("15M" in symbol_upper or "SCALP" in symbol_upper):
                return ["15m"]
            elif tf_upper == "1H" and ("1H" in symbol_upper or "HOURLY" in symbol_upper or "INTRADAY" in symbol_upper):
                return ["1h"]
            elif tf_upper == "DAILY" and ("DAILY" in symbol_upper or "SWING" in symbol_upper or "D1" in symbol_upper):
                return ["daily"]
            elif tf_upper == "WEEKLY" and ("WEEKLY" in symbol_upper or "W1" in symbol_upper or "TACTICAL" in symbol_upper):
                return ["weekly"]
            elif tf_upper == "MONTHLY" and ("MONTHLY" in symbol_upper or "1M" in symbol_upper or "STRATEGIC" in symbol_upper):
                return ["monthly"]
        
        return []

    def _has_high_agreement(self, contributions: List[AgentContribution]) -> bool:
        """Check if agents have high agreement."""
        if not contributions:
            return False
        
        recommendations = [c.recommendation for c in contributions]
        most_common = max(set(recommendations), key=recommendations.count)
        agreement_rate = recommendations.count(most_common) / len(recommendations)
        
        return agreement_rate >= 0.7
    
    def _consensus_decision(
        self,
        contributions: List[AgentContribution]
    ) -> tuple[str, float]:
        """Get consensus decision."""
        recommendations = [c.recommendation for c in contributions]
        most_common = max(set(recommendations), key=recommendations.count)
        
        supporting = [c for c in contributions if c.recommendation == most_common]
        avg_confidence = sum(c.confidence for c in supporting) / len(supporting)
        
        return most_common, avg_confidence
    
    def _weighted_decision(
        self,
        contributions: List[AgentContribution]
    ) -> tuple[str, float]:
        """Get weighted decision."""
        decision_weights: Dict[str, float] = {}
        decision_confidences: Dict[str, List[float]] = {}
        
        for contrib in contributions:
            weighted_vote = contrib.weight * contrib.confidence
            decision_weights[contrib.recommendation] = \
                decision_weights.get(contrib.recommendation, 0.0) + weighted_vote
            
            if contrib.recommendation not in decision_confidences:
                decision_confidences[contrib.recommendation] = []
            decision_confidences[contrib.recommendation].append(contrib.confidence)
        
        winning_decision = max(decision_weights.items(), key=lambda x: x[1])[0]
        avg_confidence = sum(decision_confidences[winning_decision]) / \
                        len(decision_confidences[winning_decision])
        
        return winning_decision, avg_confidence
    
    def _generate_reasoning_summary(
        self,
        contributions: List[AgentContribution],
        final_decision: str
    ) -> str:
        """Generate human-readable reasoning summary."""
        supporting = [c for c in contributions if c.recommendation == final_decision]
        opposing = [c for c in contributions if c.recommendation != final_decision]
        
        summary_parts = []
        
        # Supporting reasoning
        if supporting:
            summary_parts.append(f"{len(supporting)} agents support '{final_decision}':")
            for contrib in supporting[:3]:  # Top 3
                summary_parts.append(
                    f"  - {contrib.agent_role.value}: {contrib.reasoning} "
                    f"(confidence: {contrib.confidence:.2f})"
                )
        
        # Opposing reasoning
        if opposing:
            summary_parts.append(f"\n{len(opposing)} agents have different views:")
            for contrib in opposing[:2]:  # Top 2
                summary_parts.append(
                    f"  - {contrib.agent_role.value}: {contrib.reasoning} "
                    f"(confidence: {contrib.confidence:.2f})"
                )
        
        return "\n".join(summary_parts)
    
    def _determine_priority(
        self,
        decision_type: str,
        confidence: float,
        context: Dict[str, Any]
    ) -> DecisionPriority:
        """Determine decision priority."""
        # High-stakes decision types
        critical_types = {"emergency_stop", "risk_breach", "system_failure"}
        high_types = {"large_trade", "portfolio_rebalance", "strategy_change"}
        
        if decision_type in critical_types:
            return DecisionPriority.CRITICAL
        elif decision_type in high_types:
            return DecisionPriority.HIGH
        elif confidence < 0.5:
            return DecisionPriority.HIGH  # Low confidence = needs attention
        else:
            return DecisionPriority.MEDIUM


class DecisionAuditTrail:
    """Maintains audit trail of all decisions."""
    
    def __init__(self):
        self._decisions: List[UnifiedDecision] = []
        self._max_history = 10000
    
    def record(self, decision: UnifiedDecision) -> None:
        """Record a decision."""
        self._decisions.append(decision)
        
        if len(self._decisions) > self._max_history:
            self._decisions = self._decisions[-self._max_history:]
        
        logger.info(
            f"Recorded decision {decision.decision_id}: {decision.final_decision} "
            f"(confidence: {decision.confidence:.2f}, priority: {decision.priority.value})"
        )
    
    def get_decision(self, decision_id: str) -> Optional[UnifiedDecision]:
        """Get a specific decision."""
        for decision in self._decisions:
            if decision.decision_id == decision_id:
                return decision
        return None
    
    def get_recent_decisions(
        self,
        decision_type: Optional[str] = None,
        priority: Optional[DecisionPriority] = None,
        limit: int = 100
    ) -> List[UnifiedDecision]:
        """Get recent decisions."""
        decisions = self._decisions
        
        if decision_type:
            decisions = [d for d in decisions if d.decision_type == decision_type]
        if priority:
            decisions = [d for d in decisions if d.priority == priority]
        
        return decisions[-limit:]
    
    def get_agent_contributions(
        self,
        agent_id: str,
        limit: int = 100
    ) -> List[tuple[UnifiedDecision, AgentContribution]]:
        """Get all contributions from a specific agent."""
        results = []
        
        for decision in self._decisions[-limit:]:
            for contrib in decision.contributions:
                if contrib.agent_id == agent_id:
                    results.append((decision, contrib))
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get audit trail statistics."""
        if not self._decisions:
            return {
                "total_decisions": 0,
                "by_type": {},
                "by_priority": {},
                "average_confidence": 0.0
            }
        
        return {
            "total_decisions": len(self._decisions),
            "by_type": self._count_by_field("decision_type"),
            "by_priority": self._count_by_field("priority"),
            "by_method": self._count_by_field("aggregation_method"),
            "average_confidence": sum(d.confidence for d in self._decisions) / len(self._decisions),
            "average_contributions": sum(len(d.contributions) for d in self._decisions) / len(self._decisions)
        }
    
    def _count_by_field(self, field: str) -> Dict[str, int]:
        """Count decisions by field."""
        counts: Dict[str, int] = {}
        for decision in self._decisions:
            value = getattr(decision, field)
            if hasattr(value, "value"):
                value = value.value
            counts[str(value)] = counts.get(str(value), 0) + 1
        return counts


class UnifiedDecisionLayer:
    """Unified decision layer coordinating all agents."""
    
    def __init__(self):
        self._aggregator = DecisionAggregator()
        self._audit_trail = DecisionAuditTrail()
        self._coordinator = get_swarm_coordinator()
        self._decision_log = get_decision_log()
        self._explainability = get_explainability_service()
    
    async def make_decision(
        self,
        decision_type: str,
        context: Dict[str, Any],
        agent_roles: Optional[List[AgentRole]] = None
    ) -> UnifiedDecision:
        """Make a unified decision using swarm intelligence."""
        logger.info(f"Making decision: {decision_type}")
        decision_start = time.time()
        
        # Get relevant agents
        registry = get_agent_registry()
        if agent_roles:
            agents = []
            for role in agent_roles:
                agents.extend(registry.get_agents_by_role(role))
        else:
            agents = registry.get_all_agents()
        
        # Collect agent decisions
        agent_decisions = []
        for agent in agents:
            try:
                decision = await agent.make_decision({
                    "decision_type": decision_type,
                    **context
                })
                
                # Performance-based weight: blend win-rate and inverse Brier score.
                # Brier score ranges 0 (perfect) to 1 (worst); no-skill baseline = 0.25.
                # Weight = win_rate * (1 - brier) clamped to [0.1, 2.0], default 1.0.
                weight = 1.0
                try:
                    from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                    _tracker = get_agent_performance_tracker()
                    _metrics = _tracker.get_agent_metrics(agent.agent_id)
                    if _metrics.total_closes >= 5:
                        _brier = _tracker.compute_brier_score(agent.agent_id)
                        _brier = _brier if _brier is not None else 0.25
                        weight = max(0.1, min(2.0, _metrics.win_rate * (1.0 - _brier) * 4.0))
                except Exception as _wt_exc:
                    logger.debug("Agent weight lookup failed for %s: %s", agent.agent_id, _wt_exc)

                agent_decisions.append({
                    "agent_id": agent.agent_id,
                    "agent_role": agent.role,
                    "recommendation": decision.get("decision", ""),
                    "confidence": decision.get("confidence", 0.5),
                    "weight": weight,
                    "reasoning": decision.get("reasoning", ""),
                    "evidence": decision.get("evidence", {})
                })
            except Exception as exc:
                logger.error(f"Failed to get decision from {agent.agent_id}: {exc}")
        
        # Aggregate decisions
        unified_decision = self._aggregator.aggregate(
            decision_type,
            agent_decisions,
            context
        )
        
        # Record in audit trail
        self._audit_trail.record(unified_decision)
        
        # Log to decision log
        for contrib in unified_decision.contributions:
            agent_decision = AgentDecision(
                decision_id=unified_decision.decision_id,
                timestamp=contrib.timestamp,
                agent_id=contrib.agent_id,
                agent_type=contrib.agent_role.value,
                decision_type=decision_type,
                inputs=context,
                outputs={"recommendation": contrib.recommendation},
                confidence=contrib.confidence,
                reasoning=contrib.reasoning,
                context=contrib.evidence
            )
            self._decision_log.log_agent_decision(agent_decision)
        
        self._record_explanation(unified_decision, decision_start)

        return unified_decision
        
    def get_audit_trail(self) -> DecisionAuditTrail:
        """Get the audit trail."""
        return self._audit_trail
        
    def explain_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed explanation of a decision."""
        decision = self._audit_trail.get_decision(decision_id)
        if not decision:
            return None
        
        return {
            "decision_id": decision.decision_id,
            "type": decision.decision_type,
            "final_decision": decision.final_decision,
            "confidence": decision.confidence,
            "priority": decision.priority.value,
            "method": decision.aggregation_method,
            "reasoning": decision.reasoning_summary,
            "contributions": [
                {
                    "agent": contrib.agent_id,
                    "role": contrib.agent_role.value,
                    "recommendation": contrib.recommendation,
                    "confidence": contrib.confidence,
                    "reasoning": contrib.reasoning
                }
                for contrib in decision.contributions
            ],
            "timestamp": decision.timestamp
        }
        
    def _record_explanation(self, decision: UnifiedDecision, start_time: float) -> None:
        """Record explainability entry for a decision."""
        try:
            flags = get_environment_flags()
            env_dict = {
                "online": flags.online,
                "routing_profile": flags.enforced_routing_profile.value,
                "vpn_only": flags.vpn_only,
                "privacy_mode": flags.privacy_mode,
            }
            summary = decision.reasoning_summary.splitlines()[0] if decision.reasoning_summary else decision.final_decision
            context = ExplanationContext(
                inputs=decision.metadata or {},
                agent_id="unified_decision_layer",
                strategy=decision.metadata.get("strategy"),
                constraints={
                    "priority": decision.priority.value,
                    "aggregation_method": decision.aggregation_method,
                    "agent_contributors": len(decision.contributions),
                },
                expected_effect={
                    "decision": decision.final_decision,
                    "confidence": decision.confidence,
                },
                environment_flags=env_dict,
            )
            exp_type = self._map_explanation_type(decision.decision_type)
            record = self._explainability.record_explanation(
                explanation_type=exp_type,
                summary=summary,
                context=context,
                expert_notes=decision.reasoning_summary or "no_additional_notes",
            )
            latency = time.time() - start_time
            self._explainability.record_latency(latency)
            logger.debug("Explainability record %s stored (latency %.3fs)", record.record_id, latency)
        except Exception as exc:
            logger.error("Failed to record decision explanation: %s", exc)
        
    def _map_explanation_type(self, decision_type: str) -> ExplanationType:
        """Map decision type to explanation type."""
        lower = decision_type.lower()
        if "order" in lower or "trade" in lower:
            return ExplanationType.ORDER
        if "cancel" in lower:
            return ExplanationType.CANCEL
        if "payment" in lower or "x402" in lower:
            return ExplanationType.X402_PAYMENT
        if "promotion" in lower:
            return ExplanationType.PROMOTION
        if "demotion" in lower:
            return ExplanationType.DEMOTION
        if "safe" in lower:
            return ExplanationType.SAFE_MODE
        return ExplanationType.PARAM_CHANGE


# Global unified decision layer
_unified_decision_layer: Optional[UnifiedDecisionLayer] = None
_unified_decision_layer_lock = threading.Lock()


def get_unified_decision_layer() -> UnifiedDecisionLayer:
    """Get the global unified decision layer."""
    global _unified_decision_layer
    if _unified_decision_layer is None:
        with _unified_decision_layer_lock:
            if _unified_decision_layer is None:
                _unified_decision_layer = UnifiedDecisionLayer()
    return _unified_decision_layer
