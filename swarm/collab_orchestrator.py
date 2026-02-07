"""
Collaboration orchestrator with capability-based discovery and matchmaking for MERID.

Implements:
- Capability-based agent discovery
- Task delegation to external swarms
- Reputation-based selection
- Collaboration patterns (task delegation, model exchange, tool marketplace)
- Safety and policy enforcement
"""

import logging
import time
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

from swarm.agent_registry import (
    AgentRegistry,
    AgentMetadata,
    Capability,
    SecurityLevel,
    get_agent_registry,
)
from swarm.secure_messaging import (
    SecureMessagingProtocol,
    MessageType,
    MessageEnvelope,
    get_secure_messaging_protocol,
)

logger = logging.getLogger(__name__)


class CollaborationPattern(Enum):
    """Collaboration pattern types."""
    TASK_DELEGATION = "task_delegation"  # Send sub-tasks, receive results
    MODEL_EXCHANGE = "model_exchange"  # Federated learning updates
    TOOL_INVOCATION = "tool_invocation"  # Call external tools/APIs
    KNOWLEDGE_SHARING = "knowledge_sharing"  # Share insights/research


class TaskStatus(Enum):
    """Task status."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class CollaborationScope(Enum):
    """Collaboration scope (governance-defined)."""
    RESEARCH_ONLY = "research_only"  # Research and analysis only
    STRATEGY_SUGGESTIONS = "strategy_suggestions"  # Can suggest strategies
    TOOL_ACCESS = "tool_access"  # Can use external tools
    MODEL_TRAINING = "model_training"  # Can participate in federated learning
    FULL_COLLABORATION = "full_collaboration"  # All collaboration types


@dataclass
class CollaborationTask:
    """Collaboration task."""
    task_id: str
    pattern: CollaborationPattern
    
    # Task definition
    capability_required: str
    task_description: str
    input_data: Dict[str, Any]
    
    # Assignment
    assigned_agent_did: Optional[str] = None
    assigned_at: Optional[datetime] = None
    
    # Status
    status: TaskStatus = TaskStatus.PENDING
    
    # Results
    output_data: Optional[Dict[str, Any]] = None
    error_message: str = ""
    
    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Requester
    requester_agent_id: str = ""
    purpose: str = ""


@dataclass
class CollaborationResult:
    """Collaboration result."""
    result_id: str
    task_id: str
    
    # Agent
    agent_did: str
    agent_name: str
    
    # Result
    success: bool
    output_data: Dict[str, Any]
    error_message: str = ""
    
    # Quality metrics
    latency_ms: float = 0.0
    accuracy_score: Optional[float] = None
    
    # Validation
    validated: bool = False
    validation_score: float = 0.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentSelection:
    """Agent selection for task."""
    agent_did: str
    agent_name: str
    
    # Scoring
    capability_match_score: float  # 0.0 to 1.0
    reputation_score: float
    latency_score: float
    cost_score: float
    
    # Composite
    total_score: float
    
    # Metadata
    selected: bool = False
    rejection_reason: str = ""


@dataclass
class CollaborationPolicy:
    """Collaboration policy (governance-defined)."""
    policy_id: str
    
    # Allowed scopes
    allowed_scopes: List[CollaborationScope] = field(default_factory=list)
    
    # Allowed networks
    allowed_networks: List[str] = field(default_factory=list)  # AgentConnect, ANP, etc.
    
    # Data sharing
    allow_raw_data_sharing: bool = False
    allow_model_updates_sharing: bool = True
    allow_synthetic_data_sharing: bool = True
    
    # Security
    min_agent_reputation: float = 0.5
    require_nda: bool = False
    require_audit: bool = True
    
    # Limits
    max_concurrent_collaborations: int = 10
    max_cost_per_task: Decimal = Decimal("100.0")
    
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


class CollaborationOrchestrator:
    """
    Collaboration orchestrator with capability-based discovery.
    
    Features:
    - Capability-based agent discovery
    - Multi-criteria agent selection
    - Task delegation and result validation
    - Reputation tracking
    - Policy enforcement
    """
    
    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        messaging: Optional[SecureMessagingProtocol] = None,
    ):
        self._registry = registry or get_agent_registry()
        self._messaging = messaging or get_secure_messaging_protocol()
        
        self._tasks: Dict[str, CollaborationTask] = {}
        self._results: List[CollaborationResult] = []
        self._policies: Dict[str, CollaborationPolicy] = {}
        
        # Scoring weights
        self._capability_weight = 0.3
        self._reputation_weight = 0.4
        self._latency_weight = 0.2
        self._cost_weight = 0.1
        
        self._initialize_default_policy()
    
    def _initialize_default_policy(self) -> None:
        """Initialize default collaboration policy."""
        policy = CollaborationPolicy(
            policy_id="default",
            allowed_scopes=[
                CollaborationScope.RESEARCH_ONLY,
                CollaborationScope.TOOL_ACCESS,
            ],
            allowed_networks=["AgentConnect", "ANP"],
            allow_raw_data_sharing=False,
            allow_model_updates_sharing=True,
            allow_synthetic_data_sharing=True,
            min_agent_reputation=0.5,
            require_audit=True,
            max_concurrent_collaborations=10,
        )
        
        self._policies["default"] = policy
        
        logger.info("Initialized default collaboration policy")
    
    def discover_agents_for_task(
        self,
        capability_required: str,
        task_description: str,
        scope: CollaborationScope,
        max_candidates: int = 5,
    ) -> List[AgentSelection]:
        """Discover and score agents for task."""
        
        # Check policy
        policy = self._policies.get("default")
        if not policy or scope not in policy.allowed_scopes:
            logger.warning(f"Scope {scope.value} not allowed by policy")
            return []
        
        # Discover agents with capability
        agents = self._registry.discover_agents(
            capability_name=capability_required,
            min_reputation=policy.min_agent_reputation,
            max_results=max_candidates * 2,  # Get more for filtering
        )
        
        if not agents:
            logger.warning(f"No agents found for capability '{capability_required}'")
            return []
        
        # Score each agent
        selections = []
        for agent in agents:
            selection = self._score_agent_for_task(
                agent=agent,
                capability_required=capability_required,
                task_description=task_description,
            )
            selections.append(selection)
        
        # Sort by total score (highest first)
        selections.sort(key=lambda s: s.total_score, reverse=True)
        
        # Take top candidates
        top_selections = selections[:max_candidates]
        
        logger.info(
            f"Discovered {len(top_selections)} agents for capability '{capability_required}'"
        )
        
        return top_selections
    
    def _score_agent_for_task(
        self,
        agent: AgentMetadata,
        capability_required: str,
        task_description: str,
    ) -> AgentSelection:
        """Score agent for task."""
        
        # Find matching capability
        matching_cap = None
        for cap in agent.capabilities:
            if cap.name == capability_required:
                matching_cap = cap
                break
        
        # Capability match score
        if matching_cap:
            # Higher score for stable vs beta/experimental
            if matching_cap.status.value == "stable":
                capability_match_score = 1.0
            elif matching_cap.status.value == "beta":
                capability_match_score = 0.8
            else:
                capability_match_score = 0.5
        else:
            capability_match_score = 0.0
        
        # Reputation score (already 0.0 to 1.0)
        reputation_score = agent.reputation_score
        
        # Latency score (based on capability latency profile)
        if matching_cap:
            if matching_cap.latency_profile == "low":
                latency_score = 1.0
            elif matching_cap.latency_profile == "medium":
                latency_score = 0.7
            else:
                latency_score = 0.4
        else:
            latency_score = 0.5
        
        # Cost score (based on capability cost profile)
        if matching_cap:
            if matching_cap.cost_profile == "low":
                cost_score = 1.0
            elif matching_cap.cost_profile == "medium":
                cost_score = 0.7
            else:
                cost_score = 0.4
        else:
            cost_score = 0.5
        
        # Weighted total score
        total_score = (
            capability_match_score * self._capability_weight +
            reputation_score * self._reputation_weight +
            latency_score * self._latency_weight +
            cost_score * self._cost_weight
        )
        
        return AgentSelection(
            agent_did=agent.agent_id,
            agent_name=agent.name,
            capability_match_score=capability_match_score,
            reputation_score=reputation_score,
            latency_score=latency_score,
            cost_score=cost_score,
            total_score=total_score,
        )
    
    def create_collaboration_task(
        self,
        pattern: CollaborationPattern,
        capability_required: str,
        task_description: str,
        input_data: Dict[str, Any],
        requester_agent_id: str,
        purpose: str,
        scope: CollaborationScope,
    ) -> CollaborationTask:
        """Create collaboration task."""
        task_id = f"task_{int(time.time() * 1000)}"
        
        task = CollaborationTask(
            task_id=task_id,
            pattern=pattern,
            capability_required=capability_required,
            task_description=task_description,
            input_data=input_data,
            requester_agent_id=requester_agent_id,
            purpose=purpose,
        )
        
        self._tasks[task_id] = task
        
        logger.info(
            f"Created collaboration task '{task_id}': {pattern.value} "
            f"for capability '{capability_required}'"
        )
        
        return task
    
    def delegate_task(
        self,
        task_id: str,
        scope: CollaborationScope,
        auto_select: bool = True,
    ) -> Optional[str]:
        """Delegate task to external agent."""
        task = self._tasks.get(task_id)
        
        if not task:
            logger.error(f"Task '{task_id}' not found")
            return None
        
        # Discover agents
        selections = self.discover_agents_for_task(
            capability_required=task.capability_required,
            task_description=task.task_description,
            scope=scope,
            max_candidates=5,
        )
        
        if not selections:
            task.status = TaskStatus.FAILED
            task.error_message = "No suitable agents found"
            return None
        
        # Select best agent
        best_selection = selections[0]
        
        if auto_select or best_selection.total_score >= 0.7:
            # Assign task
            task.assigned_agent_did = best_selection.agent_did
            task.assigned_at = datetime.utcnow()
            task.status = TaskStatus.ASSIGNED
            
            # Send task via secure messaging
            self._send_task_to_agent(task, best_selection.agent_did)
            
            logger.info(
                f"Delegated task '{task_id}' to agent '{best_selection.agent_name}' "
                f"(score: {best_selection.total_score:.2f})"
            )
            
            return best_selection.agent_did
        else:
            logger.warning(
                f"Best agent score too low ({best_selection.total_score:.2f}), "
                f"task '{task_id}' not delegated"
            )
            return None
    
    def _send_task_to_agent(
        self,
        task: CollaborationTask,
        agent_did: str,
    ) -> None:
        """Send task to agent via secure messaging."""
        
        # Create message
        message = self._messaging.create_message(
            message_type=MessageType.REQUEST,
            sender_did="did:web:merid.xyz",  # MERID's DID
            recipient_did=agent_did,
            payload={
                "task_id": task.task_id,
                "pattern": task.pattern.value,
                "capability": task.capability_required,
                "description": task.task_description,
                "input": task.input_data,
                "purpose": task.purpose,
            },
        )
        
        # Send message
        audit_log = self._messaging.send_message(message)
        
        if audit_log.status == "sent":
            task.status = TaskStatus.IN_PROGRESS
            logger.info(f"Sent task '{task.task_id}' to {agent_did}")
        else:
            task.status = TaskStatus.FAILED
            task.error_message = audit_log.error_message
            logger.error(f"Failed to send task '{task.task_id}': {audit_log.error_message}")
    
    def receive_task_result(
        self,
        task_id: str,
        agent_did: str,
        output_data: Dict[str, Any],
        latency_ms: float,
    ) -> CollaborationResult:
        """Receive and validate task result."""
        task = self._tasks.get(task_id)
        
        if not task:
            logger.error(f"Task '{task_id}' not found for result")
            raise ValueError(f"Task '{task_id}' not found")
        
        # Get agent metadata
        agent = self._registry.get_agent(agent_did)
        agent_name = agent.name if agent else agent_did
        
        # Create result
        result_id = f"result_{int(time.time() * 1000)}"
        
        result = CollaborationResult(
            result_id=result_id,
            task_id=task_id,
            agent_did=agent_did,
            agent_name=agent_name,
            success=True,
            output_data=output_data,
            latency_ms=latency_ms,
        )
        
        self._results.append(result)
        
        # Update task
        task.status = TaskStatus.COMPLETED
        task.output_data = output_data
        task.completed_at = datetime.utcnow()
        
        # Validate result
        self._validate_result(result)
        
        # Update agent reputation based on result
        if result.validated and result.validation_score >= 0.7:
            self._update_agent_reputation(agent_did, delta=0.05, reason="successful_task")
        elif not result.validated or result.validation_score < 0.5:
            self._update_agent_reputation(agent_did, delta=-0.05, reason="poor_result")
        
        logger.info(
            f"Received result for task '{task_id}' from {agent_name} "
            f"(latency: {latency_ms:.0f}ms, validated: {result.validated})"
        )
        
        return result
    
    def _validate_result(self, result: CollaborationResult) -> None:
        """Validate collaboration result."""
        # Simplified validation - in production would:
        # 1. Check output schema matches expected
        # 2. Run sanity checks on data
        # 3. Compare with known good results if available
        # 4. Check for suspicious patterns
        
        # Mock validation
        if result.output_data and "error" not in result.output_data:
            result.validated = True
            result.validation_score = 0.85
        else:
            result.validated = False
            result.validation_score = 0.3
    
    def _update_agent_reputation(
        self,
        agent_did: str,
        delta: float,
        reason: str,
    ) -> None:
        """Update agent reputation."""
        agent = self._registry.get_agent(agent_did)
        
        if not agent:
            return
        
        new_score = max(0.0, min(1.0, agent.reputation_score + delta))
        
        self._registry.update_reputation(
            agent_id=agent_did,
            new_score=new_score,
            reason=reason,
        )
    
    def get_collaboration_stats(self) -> Dict[str, Any]:
        """Get collaboration statistics."""
        total_tasks = len(self._tasks)
        
        completed_tasks = sum(
            1 for task in self._tasks.values()
            if task.status == TaskStatus.COMPLETED
        )
        
        failed_tasks = sum(
            1 for task in self._tasks.values()
            if task.status == TaskStatus.FAILED
        )
        
        validated_results = sum(
            1 for result in self._results
            if result.validated
        )
        
        avg_latency = (
            sum(result.latency_ms for result in self._results) / len(self._results)
            if self._results else 0.0
        )
        
        return {
            "tasks": {
                "total": total_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks,
                "in_progress": sum(
                    1 for task in self._tasks.values()
                    if task.status == TaskStatus.IN_PROGRESS
                ),
                "success_rate": (
                    completed_tasks / total_tasks
                    if total_tasks > 0 else 0.0
                ),
            },
            "results": {
                "total": len(self._results),
                "validated": validated_results,
                "validation_rate": (
                    validated_results / len(self._results)
                    if self._results else 0.0
                ),
                "avg_latency_ms": avg_latency,
            },
            "patterns": {
                pattern.value: sum(
                    1 for task in self._tasks.values()
                    if task.pattern == pattern
                )
                for pattern in CollaborationPattern
            },
        }


_collaboration_orchestrator: Optional[CollaborationOrchestrator] = None


def get_collaboration_orchestrator() -> CollaborationOrchestrator:
    """Get global CollaborationOrchestrator instance."""
    global _collaboration_orchestrator
    if _collaboration_orchestrator is None:
        _collaboration_orchestrator = CollaborationOrchestrator()
    return _collaboration_orchestrator
