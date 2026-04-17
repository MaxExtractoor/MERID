"""
Emergent behavior detection and safeguards for multi-agent swarms.

Detects and constrains harmful emergent behaviors including coordinated market
manipulation, runaway risk-taking, and self-reinforcing feedback loops.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum
import numpy as np
import threading

from core.info_theory_metrics import get_info_theory_metrics
from observability.neo4j_integration import get_neo4j_integration

logger = get_logger(__name__)


class EmergentBehaviorType(Enum):
    """Type of emergent behavior detected."""
    COORDINATED_MANIPULATION = "coordinated_manipulation"
    FEEDBACK_LOOP = "feedback_loop"
    RUNAWAY_RISK = "runaway_risk"
    CORRELATED_STACKING = "correlated_stacking"
    NOVEL_COORDINATION = "novel_coordination"
    REGIME_SHIFT = "regime_shift"
    INTERACTION_ANOMALY = "interaction_anomaly"


class SafeguardAction(Enum):
    """Action taken by safeguard."""
    MONITOR = "monitor"
    THROTTLE = "throttle"
    PAUSE = "pause"
    REQUIRE_REVIEW = "require_review"
    BLOCK = "block"
    TRIGGER_SIMULATION = "trigger_simulation"


@dataclass
class GlobalInvariant:
    """Global invariant constraint for swarm."""
    invariant_id: str
    name: str
    description: str
    check_function: Any
    threshold: float
    current_value: float = 0.0
    violated: bool = False
    violation_count: int = 0
    last_violation: Optional[datetime] = None


@dataclass
class BehavioralAnomaly:
    """Detected behavioral anomaly in swarm."""
    anomaly_id: str
    timestamp: datetime
    behavior_type: EmergentBehaviorType
    severity: str
    
    agents_involved: List[str]
    description: str
    evidence: Dict[str, Any]
    
    safeguard_action: SafeguardAction
    action_taken: str
    
    requires_review: bool = False
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None
    
    resolved: bool = False
    resolved_at: Optional[datetime] = None


@dataclass
class InteractionPattern:
    """Agent interaction pattern for analysis."""
    pattern_id: str
    agents: List[str]
    interaction_type: str
    frequency: int
    first_seen: datetime
    last_seen: datetime
    is_novel: bool
    approved: bool = False


@dataclass
class SwarmState:
    """Current state of swarm for anomaly detection."""
    timestamp: datetime
    active_agents: int
    total_positions: float
    aggregate_leverage: float
    correlation_score: float
    action_entropy: float
    interaction_graph_metrics: Dict[str, float]
    regime: str


class EmergentBehaviorSafeguards:
    """
    Emergent behavior detection and safeguards for multi-agent swarms.
    
    Implements:
    - Global invariants (aggregate exposure, leverage, turnover caps)
    - Behavioral anomaly detection (KL spikes, novel patterns, regime shifts)
    - Interaction throttles for coordination channels
    - Human/governor review for novel behaviors
    - Simulation gates for new swarm-level behaviors
    """
    
    def __init__(self):
        self.info_metrics = get_info_theory_metrics()
        self.neo4j = get_neo4j_integration()
        
        self._global_invariants: Dict[str, GlobalInvariant] = {}
        self._anomalies: List[BehavioralAnomaly] = []
        self._interaction_patterns: Dict[str, InteractionPattern] = {}
        self._swarm_history: deque = deque(maxlen=1000)
        
        self._agent_actions: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._coordination_topics: Dict[str, Dict[str, Any]] = {}
        
        self._throttled_channels: Set[str] = set()
        self._paused_agents: Set[str] = set()
        
        self._lock = threading.Lock()
        
        self._initialize_global_invariants()
    
    def _initialize_global_invariants(self) -> None:
        """Initialize global invariants for swarm safety."""
        self.register_global_invariant(
            invariant_id="aggregate_exposure",
            name="Aggregate Exposure Cap",
            description="Total notional exposure across all agents",
            check_function=lambda state: state.total_positions,
            threshold=1000000.0,
        )
        
        self.register_global_invariant(
            invariant_id="aggregate_leverage",
            name="Aggregate Leverage Cap",
            description="Total leverage across all agents",
            check_function=lambda state: state.aggregate_leverage,
            threshold=5.0,
        )
        
        self.register_global_invariant(
            invariant_id="correlation_limit",
            name="Agent Correlation Limit",
            description="Maximum correlation between agent actions",
            check_function=lambda state: state.correlation_score,
            threshold=0.85,
        )
        
        self.register_global_invariant(
            invariant_id="action_diversity",
            name="Action Diversity Minimum",
            description="Minimum entropy in agent action distribution",
            check_function=lambda state: state.action_entropy,
            threshold=0.3,
        )
        
        logger.info("Initialized global invariants for emergent behavior safeguards")
    
    def register_global_invariant(
        self,
        invariant_id: str,
        name: str,
        description: str,
        check_function: Any,
        threshold: float,
    ) -> GlobalInvariant:
        """Register a global invariant constraint."""
        invariant = GlobalInvariant(
            invariant_id=invariant_id,
            name=name,
            description=description,
            check_function=check_function,
            threshold=threshold,
        )
        
        self._global_invariants[invariant_id] = invariant
        
        logger.info(f"Registered global invariant '{invariant_id}': {name}")
        
        return invariant
    
    def record_agent_action(
        self,
        agent_id: str,
        action_type: str,
        action_data: Dict[str, Any],
    ) -> None:
        """Record agent action for behavioral analysis."""
        with self._lock:
            self._agent_actions[agent_id].append({
                "timestamp": datetime.utcnow(),
                "action_type": action_type,
                "action_data": action_data,
            })
    
    def check_swarm_state(
        self,
        active_agents: List[str],
        positions: Dict[str, float],
        leverages: Dict[str, float],
        regime: str,
    ) -> Tuple[bool, List[BehavioralAnomaly]]:
        """
        Check current swarm state for emergent behaviors and invariant violations.
        
        Returns:
            (safe, anomalies_detected)
        """
        with self._lock:
            # Compute swarm state
            state = self._compute_swarm_state(
                active_agents, positions, leverages, regime
            )
            
            self._swarm_history.append(state)
            
            # Check global invariants
            invariant_violations = self._check_global_invariants(state)
            
            # Detect behavioral anomalies
            behavioral_anomalies = self._detect_behavioral_anomalies(state)
            
            # Detect novel interaction patterns
            novel_patterns = self._detect_novel_patterns(active_agents)
            
            # Combine all anomalies
            all_anomalies = invariant_violations + behavioral_anomalies + novel_patterns
            
            # Take safeguard actions
            for anomaly in all_anomalies:
                self._take_safeguard_action(anomaly)
            
            safe = len([a for a in all_anomalies if a.severity in ["CRITICAL", "HIGH"]]) == 0
            
            return safe, all_anomalies
    
    def _compute_swarm_state(
        self,
        active_agents: List[str],
        positions: Dict[str, float],
        leverages: Dict[str, float],
        regime: str,
    ) -> SwarmState:
        """Compute current swarm state."""
        total_positions = sum(abs(p) for p in positions.values())
        aggregate_leverage = sum(leverages.values())
        
        # Compute correlation score
        correlation_score = self._compute_action_correlation(active_agents)
        
        # Compute action entropy
        action_entropy = self._compute_action_entropy(active_agents)
        
        # Get interaction graph metrics
        graph_metrics = self._get_interaction_graph_metrics(active_agents)
        
        return SwarmState(
            timestamp=datetime.utcnow(),
            active_agents=len(active_agents),
            total_positions=total_positions,
            aggregate_leverage=aggregate_leverage,
            correlation_score=correlation_score,
            action_entropy=action_entropy,
            interaction_graph_metrics=graph_metrics,
            regime=regime,
        )
    
    def _check_global_invariants(
        self,
        state: SwarmState,
    ) -> List[BehavioralAnomaly]:
        """Check global invariants and detect violations."""
        anomalies = []
        
        for invariant_id, invariant in self._global_invariants.items():
            current_value = invariant.check_function(state)
            invariant.current_value = current_value
            
            # Check for violation
            if invariant_id == "action_diversity":
                # For diversity, lower is worse
                violated = current_value < invariant.threshold
            else:
                # For caps, higher is worse
                violated = current_value > invariant.threshold
            
            if violated:
                if not invariant.violated:
                    # New violation
                    invariant.violated = True
                    invariant.violation_count += 1
                    invariant.last_violation = datetime.utcnow()
                    
                    anomaly = self._create_anomaly(
                        behavior_type=EmergentBehaviorType.RUNAWAY_RISK,
                        severity="CRITICAL" if invariant.violation_count > 3 else "HIGH",
                        agents_involved=[],
                        description=f"Global invariant violated: {invariant.name}",
                        evidence={
                            "invariant_id": invariant_id,
                            "current_value": current_value,
                            "threshold": invariant.threshold,
                            "violation_count": invariant.violation_count,
                        },
                        safeguard_action=SafeguardAction.PAUSE if invariant.violation_count > 3 else SafeguardAction.THROTTLE,
                    )
                    
                    anomalies.append(anomaly)
            else:
                invariant.violated = False
        
        return anomalies
    
    def _detect_behavioral_anomalies(
        self,
        state: SwarmState,
    ) -> List[BehavioralAnomaly]:
        """Detect behavioral anomalies using KL divergence and pattern analysis."""
        anomalies = []
        
        if len(self._swarm_history) < 10:
            return anomalies
        
        # Check for KL spike in action distribution
        recent_actions = self._get_recent_action_distribution(window_seconds=300)
        baseline_actions = self._get_baseline_action_distribution()
        
        if recent_actions is not None and baseline_actions is not None:
            kl_result = self.info_metrics.compute_kl_divergence(
                recent_data=recent_actions,
                baseline_name="swarm_actions",
            )
            
            if kl_result and kl_result.threshold_breached:
                anomaly = self._create_anomaly(
                    behavior_type=EmergentBehaviorType.REGIME_SHIFT,
                    severity="HIGH",
                    agents_involved=[],
                    description=f"KL divergence spike in swarm actions: {kl_result.kl_divergence:.3f}",
                    evidence={
                        "kl_divergence": kl_result.kl_divergence,
                        "js_divergence": kl_result.js_divergence,
                    },
                    safeguard_action=SafeguardAction.REQUIRE_REVIEW,
                )
                anomalies.append(anomaly)
        
        # Check for coordinated manipulation patterns
        coordinated = self._detect_coordinated_manipulation(state)
        if coordinated:
            anomalies.append(coordinated)
        
        # Check for feedback loops
        feedback_loop = self._detect_feedback_loop(state)
        if feedback_loop:
            anomalies.append(feedback_loop)
        
        return anomalies
    
    def _detect_coordinated_manipulation(
        self,
        state: SwarmState,
    ) -> Optional[BehavioralAnomaly]:
        """Detect coordinated manipulation patterns."""
        # Check for high correlation + high volume
        if state.correlation_score > 0.8 and state.total_positions > 500000:
            # Get agents with similar recent actions
            coordinated_agents = self._find_coordinated_agents(threshold=0.8)
            
            if len(coordinated_agents) >= 3:
                return self._create_anomaly(
                    behavior_type=EmergentBehaviorType.COORDINATED_MANIPULATION,
                    severity="CRITICAL",
                    agents_involved=coordinated_agents,
                    description=f"Potential coordinated manipulation: {len(coordinated_agents)} agents with high correlation",
                    evidence={
                        "correlation_score": state.correlation_score,
                        "total_positions": state.total_positions,
                        "coordinated_agents": coordinated_agents,
                    },
                    safeguard_action=SafeguardAction.BLOCK,
                )
        
        return None
    
    def _detect_feedback_loop(
        self,
        state: SwarmState,
    ) -> Optional[BehavioralAnomaly]:
        """Detect self-reinforcing feedback loops."""
        if len(self._swarm_history) < 20:
            return None
        
        # Check for accelerating correlation
        recent_states = list(self._swarm_history)[-20:]
        correlations = [s.correlation_score for s in recent_states]
        
        # Simple trend detection
        first_half_avg = np.mean(correlations[:10])
        second_half_avg = np.mean(correlations[10:])
        
        if second_half_avg > first_half_avg + 0.2 and second_half_avg > 0.7:
            return self._create_anomaly(
                behavior_type=EmergentBehaviorType.FEEDBACK_LOOP,
                severity="HIGH",
                agents_involved=[],
                description="Self-reinforcing feedback loop detected: accelerating correlation",
                evidence={
                    "first_half_correlation": first_half_avg,
                    "second_half_correlation": second_half_avg,
                    "current_correlation": state.correlation_score,
                },
                safeguard_action=SafeguardAction.THROTTLE,
            )
        
        return None
    
    def _detect_novel_patterns(
        self,
        active_agents: List[str],
    ) -> List[BehavioralAnomaly]:
        """Detect novel interaction patterns requiring review."""
        anomalies = []
        
        # Analyze interaction patterns
        current_patterns = self._analyze_interaction_patterns(active_agents)
        
        for pattern in current_patterns:
            if pattern.is_novel and not pattern.approved:
                anomaly = self._create_anomaly(
                    behavior_type=EmergentBehaviorType.NOVEL_COORDINATION,
                    severity="MEDIUM",
                    agents_involved=pattern.agents,
                    description=f"Novel interaction pattern detected: {pattern.interaction_type}",
                    evidence={
                        "pattern_id": pattern.pattern_id,
                        "agents": pattern.agents,
                        "frequency": pattern.frequency,
                        "first_seen": pattern.first_seen.isoformat(),
                    },
                    safeguard_action=SafeguardAction.REQUIRE_REVIEW,
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _compute_action_correlation(
        self,
        active_agents: List[str],
    ) -> float:
        """Compute correlation score between agent actions."""
        if len(active_agents) < 2:
            return 0.0
        
        # Get recent actions for each agent
        recent_actions = {}
        for agent_id in active_agents:
            actions = list(self._agent_actions[agent_id])[-10:]
            if actions:
                recent_actions[agent_id] = actions
        
        if len(recent_actions) < 2:
            return 0.0
        
        # Compute pairwise correlation
        correlations = []
        agents = list(recent_actions.keys())
        
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                agent1_actions = recent_actions[agents[i]]
                agent2_actions = recent_actions[agents[j]]
                
                # Simple correlation based on action type similarity
                similarity = self._compute_action_similarity(agent1_actions, agent2_actions)
                correlations.append(similarity)
        
        return np.mean(correlations) if correlations else 0.0
    
    def _compute_action_similarity(
        self,
        actions1: List[Dict[str, Any]],
        actions2: List[Dict[str, Any]],
    ) -> float:
        """Compute similarity between two action sequences."""
        if not actions1 or not actions2:
            return 0.0
        
        # Count matching action types
        types1 = [a["action_type"] for a in actions1]
        types2 = [a["action_type"] for a in actions2]
        
        # Jaccard similarity
        set1 = set(types1)
        set2 = set(types2)
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    def _compute_action_entropy(
        self,
        active_agents: List[str],
    ) -> float:
        """Compute entropy of action distribution across agents."""
        action_counts = defaultdict(int)
        
        for agent_id in active_agents:
            actions = list(self._agent_actions[agent_id])[-10:]
            for action in actions:
                action_counts[action["action_type"]] += 1
        
        if not action_counts:
            return 1.0
        
        total = sum(action_counts.values())
        probs = np.array([count / total for count in action_counts.values()])
        
        entropy = -np.sum(probs * np.log2(probs + 1e-10))
        max_entropy = np.log2(len(action_counts)) if len(action_counts) > 1 else 1.0
        
        return entropy / max_entropy if max_entropy > 0 else 0.0
    
    def _get_interaction_graph_metrics(
        self,
        active_agents: List[str],
    ) -> Dict[str, float]:
        """Get metrics from agent interaction graph."""
        # This would query Neo4j for graph metrics
        # For now, return placeholder
        return {
            "avg_degree": 0.0,
            "clustering_coefficient": 0.0,
            "max_betweenness": 0.0,
        }
    
    def _get_recent_action_distribution(
        self,
        window_seconds: int,
    ) -> Optional[np.ndarray]:
        """Get recent action distribution for KL divergence."""
        cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)
        
        action_counts = defaultdict(int)
        for agent_actions in self._agent_actions.values():
            for action in agent_actions:
                if action["timestamp"] >= cutoff:
                    action_counts[action["action_type"]] += 1
        
        if not action_counts:
            return None
        
        total = sum(action_counts.values())
        return np.array([count / total for count in action_counts.values()])
    
    def _get_baseline_action_distribution(self) -> Optional[np.ndarray]:
        """Get baseline action distribution."""
        # This would load from stored baseline
        # For now, return uniform distribution
        return None
    
    def _find_coordinated_agents(
        self,
        threshold: float,
    ) -> List[str]:
        """Find agents with coordinated actions."""
        coordinated = []
        
        # Simple implementation: find agents with similar recent actions
        agent_signatures = {}
        for agent_id, actions in self._agent_actions.items():
            if actions:
                recent = list(actions)[-10:]
                signature = tuple(sorted([a["action_type"] for a in recent]))
                agent_signatures[agent_id] = signature
        
        # Group by signature
        signature_groups = defaultdict(list)
        for agent_id, signature in agent_signatures.items():
            signature_groups[signature].append(agent_id)
        
        # Find largest coordinated group
        for agents in signature_groups.values():
            if len(agents) >= 3:
                coordinated.extend(agents)
        
        return coordinated
    
    def _analyze_interaction_patterns(
        self,
        active_agents: List[str],
    ) -> List[InteractionPattern]:
        """Analyze interaction patterns between agents."""
        patterns = []
        
        # This would analyze message patterns, coordination topics, etc.
        # For now, return empty list
        
        return patterns
    
    def _create_anomaly(
        self,
        behavior_type: EmergentBehaviorType,
        severity: str,
        agents_involved: List[str],
        description: str,
        evidence: Dict[str, Any],
        safeguard_action: SafeguardAction,
    ) -> BehavioralAnomaly:
        """Create behavioral anomaly record."""
        import hashlib
        anomaly_id = hashlib.md5(
            f"{behavior_type.value}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        anomaly = BehavioralAnomaly(
            anomaly_id=anomaly_id,
            timestamp=datetime.utcnow(),
            behavior_type=behavior_type,
            severity=severity,
            agents_involved=agents_involved,
            description=description,
            evidence=evidence,
            safeguard_action=safeguard_action,
            action_taken="",
            requires_review=safeguard_action == SafeguardAction.REQUIRE_REVIEW,
        )
        
        self._anomalies.append(anomaly)
        
        logger.warning(
            f"Emergent behavior anomaly detected: {behavior_type.value} "
            f"(severity={severity}, anomaly_id={anomaly_id})"
        )
        
        return anomaly
    
    def _take_safeguard_action(
        self,
        anomaly: BehavioralAnomaly,
    ) -> None:
        """Take safeguard action for detected anomaly."""
        action = anomaly.safeguard_action
        
        if action == SafeguardAction.THROTTLE:
            # Throttle coordination channels
            for agent_id in anomaly.agents_involved:
                self._throttled_channels.add(f"coord_{agent_id}")
            anomaly.action_taken = f"Throttled {len(anomaly.agents_involved)} coordination channels"
        
        elif action == SafeguardAction.PAUSE:
            # Pause involved agents
            for agent_id in anomaly.agents_involved:
                self._paused_agents.add(agent_id)
            anomaly.action_taken = f"Paused {len(anomaly.agents_involved)} agents"
        
        elif action == SafeguardAction.BLOCK:
            # Block all agents involved
            for agent_id in anomaly.agents_involved:
                self._paused_agents.add(agent_id)
            anomaly.action_taken = f"Blocked {len(anomaly.agents_involved)} agents"
        
        elif action == SafeguardAction.REQUIRE_REVIEW:
            # Flag for human review
            anomaly.action_taken = "Flagged for human/governor review"
        
        elif action == SafeguardAction.TRIGGER_SIMULATION:
            # Trigger simulation gate
            anomaly.action_taken = "Triggered simulation gate for new behavior"
        
        logger.info(f"Safeguard action taken for {anomaly.anomaly_id}: {anomaly.action_taken}")
    
    def is_agent_paused(self, agent_id: str) -> bool:
        """Check if agent is paused by safeguards."""
        return agent_id in self._paused_agents
    
    def is_channel_throttled(self, channel: str) -> bool:
        """Check if coordination channel is throttled."""
        return channel in self._throttled_channels
    
    def review_anomaly(
        self,
        anomaly_id: str,
        reviewer: str,
        approved: bool,
        notes: str,
    ) -> BehavioralAnomaly:
        """Review and approve/reject anomaly."""
        anomaly = next((a for a in self._anomalies if a.anomaly_id == anomaly_id), None)
        if not anomaly:
            raise ValueError(f"Anomaly '{anomaly_id}' not found")
        
        anomaly.reviewed = True
        anomaly.reviewed_by = reviewer
        anomaly.review_notes = notes
        
        if approved:
            # Unpause agents or unthrottle channels
            for agent_id in anomaly.agents_involved:
                self._paused_agents.discard(agent_id)
                self._throttled_channels.discard(f"coord_{agent_id}")
            
            anomaly.resolved = True
            anomaly.resolved_at = datetime.utcnow()
        
        logger.info(
            f"Anomaly '{anomaly_id}' reviewed by {reviewer}: "
            f"{'approved' if approved else 'rejected'}"
        )
        
        return anomaly
    
    def get_pending_reviews(self) -> List[BehavioralAnomaly]:
        """Get anomalies pending review."""
        return [
            a for a in self._anomalies
            if a.requires_review and not a.reviewed
        ]
    
    def get_anomalies(
        self,
        behavior_type: Optional[EmergentBehaviorType] = None,
        severity: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[BehavioralAnomaly]:
        """Query behavioral anomalies."""
        anomalies = self._anomalies
        
        if behavior_type:
            anomalies = [a for a in anomalies if a.behavior_type == behavior_type]
        
        if severity:
            anomalies = [a for a in anomalies if a.severity == severity]
        
        if since:
            anomalies = [a for a in anomalies if a.timestamp >= since]
        
        return anomalies[-limit:]
    
    def get_safeguards_summary(self) -> Dict[str, Any]:
        """Get safeguards system summary."""
        return {
            "global_invariants": {
                inv_id: {
                    "name": inv.name,
                    "current_value": inv.current_value,
                    "threshold": inv.threshold,
                    "violated": inv.violated,
                    "violation_count": inv.violation_count,
                }
                for inv_id, inv in self._global_invariants.items()
            },
            "anomalies": {
                "total": len(self._anomalies),
                "pending_review": len(self.get_pending_reviews()),
                "by_severity": {
                    "CRITICAL": len([a for a in self._anomalies if a.severity == "CRITICAL"]),
                    "HIGH": len([a for a in self._anomalies if a.severity == "HIGH"]),
                    "MEDIUM": len([a for a in self._anomalies if a.severity == "MEDIUM"]),
                },
            },
            "paused_agents": len(self._paused_agents),
        }


_emergent_behavior_safeguards: Optional[EmergentBehaviorSafeguards] = None
_emergent_behavior_safeguards_lock = threading.Lock()


def get_emergent_behavior_safeguards() -> EmergentBehaviorSafeguards:
    """Get global EmergentBehaviorSafeguards instance."""
    global _emergent_behavior_safeguards
    if _emergent_behavior_safeguards is None:
        with _emergent_behavior_safeguards_lock:
            if _emergent_behavior_safeguards is None:
                _emergent_behavior_safeguards = EmergentBehaviorSafeguards()
    return _emergent_behavior_safeguards
