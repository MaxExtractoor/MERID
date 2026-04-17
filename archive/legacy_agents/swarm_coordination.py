"""
Swarm Coordination Mechanisms for MERID
Voting, expert panels, graph workflows, and conflict resolution.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from agents.agent_framework import Agent, AgentMessage, AgentRole, get_agent_registry
from utils.logger import get_logger

logger = get_logger("agents.swarm_coordination")


class VotingProtocol(Enum):
    """Voting protocols for swarm decisions."""
    SIMPLE_MAJORITY = "simple_majority"
    WEIGHTED = "weighted"
    QUORUM_BASED = "quorum_based"
    UNANIMOUS = "unanimous"


class ConflictResolution(Enum):
    """Conflict resolution strategies."""
    HIGHEST_CONFIDENCE = "highest_confidence"
    EXPERT_OVERRIDE = "expert_override"
    WEIGHTED_AVERAGE = "weighted_average"
    GOVERNANCE_DECISION = "governance_decision"


@dataclass
class Vote:
    """A vote from an agent."""
    agent_id: str
    agent_role: AgentRole
    decision: str
    confidence: float
    weight: float
    reasoning: str
    timestamp: float


@dataclass
class VotingResult:
    """Result of a voting round."""
    decision: str
    total_votes: int
    confidence: float
    agreement_score: float
    votes: List[Vote]
    timestamp: float


@dataclass
class ExpertOpinion:
    """Opinion from an expert agent."""
    agent_id: str
    agent_role: AgentRole
    recommendation: str
    confidence: float
    evidence: Dict[str, Any]
    timestamp: float


class SwarmVoting:
    """Voting mechanism for swarm decisions."""
    
    def __init__(
        self,
        protocol: VotingProtocol = VotingProtocol.WEIGHTED,
        quorum_threshold: float = 0.5,
        confidence_threshold: float = 0.6
    ):
        self.protocol = protocol
        self.quorum_threshold = quorum_threshold
        self.confidence_threshold = confidence_threshold
    
    async def collect_votes(
        self,
        agents: List[Agent],
        question: str,
        context: Dict[str, Any]
    ) -> List[Vote]:
        """Collect votes from agents."""
        votes = []
        
        for agent in agents:
            try:
                # Get agent's decision
                decision_result = await agent.make_decision({
                    "question": question,
                    **context
                })
                
                vote = Vote(
                    agent_id=agent.agent_id,
                    agent_role=agent.role,
                    decision=decision_result.get("decision", "abstain"),
                    confidence=decision_result.get("confidence", 0.5),
                    weight=self._calculate_weight(agent, context),
                    reasoning=decision_result.get("reasoning", ""),
                    timestamp=time.time()
                )
                
                votes.append(vote)
                
            except Exception as exc:
                logger.error(f"Failed to collect vote from {agent.agent_id}: {exc}")
        
        return votes
    
    def tally_votes(self, votes: List[Vote]) -> VotingResult:
        """Tally votes and determine outcome."""
        if not votes:
            return VotingResult(
                decision="no_decision",
                total_votes=0,
                confidence=0.0,
                agreement_score=0.0,
                votes=[],
                timestamp=time.time()
            )
        
        if self.protocol == VotingProtocol.SIMPLE_MAJORITY:
            return self._simple_majority(votes)
        elif self.protocol == VotingProtocol.WEIGHTED:
            return self._weighted_voting(votes)
        elif self.protocol == VotingProtocol.QUORUM_BASED:
            return self._quorum_based(votes)
        elif self.protocol == VotingProtocol.UNANIMOUS:
            return self._unanimous(votes)
        else:
            return self._weighted_voting(votes)
    
    def _simple_majority(self, votes: List[Vote]) -> VotingResult:
        """Simple majority voting."""
        decision_counts: Dict[str, int] = {}
        
        for vote in votes:
            decision_counts[vote.decision] = decision_counts.get(vote.decision, 0) + 1
        
        winning_decision = max(decision_counts.items(), key=lambda x: x[1])[0]
        winning_votes = [v for v in votes if v.decision == winning_decision]
        
        agreement_score = decision_counts[winning_decision] / len(votes)
        avg_confidence = np.mean([v.confidence for v in winning_votes])
        
        return VotingResult(
            decision=winning_decision,
            total_votes=len(votes),
            confidence=avg_confidence,
            agreement_score=agreement_score,
            votes=votes,
            timestamp=time.time()
        )
    
    def _weighted_voting(self, votes: List[Vote]) -> VotingResult:
        """Weighted voting based on agent weights."""
        decision_weights: Dict[str, float] = {}
        decision_confidences: Dict[str, List[float]] = {}
        
        for vote in votes:
            weighted_vote = vote.weight * vote.confidence
            decision_weights[vote.decision] = decision_weights.get(vote.decision, 0.0) + weighted_vote
            
            if vote.decision not in decision_confidences:
                decision_confidences[vote.decision] = []
            decision_confidences[vote.decision].append(vote.confidence)
        
        total_weight = sum(v.weight for v in votes)
        winning_decision = max(decision_weights.items(), key=lambda x: x[1])[0]
        
        agreement_score = decision_weights[winning_decision] / total_weight if total_weight > 0 else 0
        avg_confidence = np.mean(decision_confidences[winning_decision])
        
        return VotingResult(
            decision=winning_decision,
            total_votes=len(votes),
            confidence=avg_confidence,
            agreement_score=agreement_score,
            votes=votes,
            timestamp=time.time()
        )
    
    def _quorum_based(self, votes: List[Vote]) -> VotingResult:
        """Quorum-based voting."""
        result = self._weighted_voting(votes)
        
        if result.agreement_score < self.quorum_threshold:
            result.decision = "no_quorum"
            result.confidence = 0.0
        
        return result
    
    def _unanimous(self, votes: List[Vote]) -> VotingResult:
        """Unanimous voting."""
        decisions = set(v.decision for v in votes)
        
        if len(decisions) == 1:
            decision = list(decisions)[0]
            avg_confidence = np.mean([v.confidence for v in votes])
            
            return VotingResult(
                decision=decision,
                total_votes=len(votes),
                confidence=avg_confidence,
                agreement_score=1.0,
                votes=votes,
                timestamp=time.time()
            )
        else:
            return VotingResult(
                decision="no_consensus",
                total_votes=len(votes),
                confidence=0.0,
                agreement_score=0.0,
                votes=votes,
                timestamp=time.time()
            )
    
    def _calculate_weight(self, agent: Agent, context: Dict[str, Any]) -> float:
        """Calculate agent weight based on role and performance."""
        # Base weight by role
        role_weights = {
            AgentRole.GOVERNANCE: 2.0,
            AgentRole.RISK: 1.5,
            AgentRole.RESEARCH_SIGNAL: 1.2,
            AgentRole.EXECUTION: 1.0,
            AgentRole.ROUTING: 1.0,
            AgentRole.ANOMALY_DETECTION: 1.3,
            AgentRole.SNIPER_ARBITRAGE: 1.0,
            AgentRole.DEFI: 1.0,
            AgentRole.MEMECOIN: 0.8,
            AgentRole.XSTOCKS: 1.0,
            AgentRole.WALLET_REBALANCING: 1.0
        }
        
        base_weight = role_weights.get(agent.role, 1.0)
        
        # Adjust by performance
        metrics = agent.get_metrics()
        performance_multiplier = metrics.success_rate
        
        return base_weight * performance_multiplier


class ExpertPanel:
    """Expert panel for specialist consensus."""
    
    def __init__(self, expert_roles: List[AgentRole]):
        self.expert_roles = expert_roles
    
    async def consult_experts(
        self,
        question: str,
        context: Dict[str, Any]
    ) -> List[ExpertOpinion]:
        """Consult expert agents."""
        registry = get_agent_registry()
        opinions = []
        
        for role in self.expert_roles:
            experts = registry.get_agents_by_role(role)
            
            for expert in experts:
                try:
                    result = await expert.make_decision({
                        "question": question,
                        **context
                    })
                    
                    opinion = ExpertOpinion(
                        agent_id=expert.agent_id,
                        agent_role=expert.role,
                        recommendation=result.get("decision", ""),
                        confidence=result.get("confidence", 0.5),
                        evidence=result.get("evidence", {}),
                        timestamp=time.time()
                    )
                    
                    opinions.append(opinion)
                    
                except Exception as exc:
                    logger.error(f"Failed to consult expert {expert.agent_id}: {exc}")
        
        return opinions
    
    def synthesize_opinions(
        self,
        opinions: List[ExpertOpinion]
    ) -> Dict[str, Any]:
        """Synthesize expert opinions into a recommendation."""
        if not opinions:
            return {
                "recommendation": "insufficient_data",
                "confidence": 0.0,
                "consensus": False
            }
        
        # Group by recommendation
        rec_groups: Dict[str, List[ExpertOpinion]] = {}
        for opinion in opinions:
            if opinion.recommendation not in rec_groups:
                rec_groups[opinion.recommendation] = []
            rec_groups[opinion.recommendation].append(opinion)
        
        # Find strongest recommendation
        best_rec = max(
            rec_groups.items(),
            key=lambda x: sum(o.confidence for o in x[1])
        )
        
        recommendation = best_rec[0]
        supporting_opinions = best_rec[1]
        
        avg_confidence = np.mean([o.confidence for o in supporting_opinions])
        consensus = len(supporting_opinions) / len(opinions) > 0.6
        
        return {
            "recommendation": recommendation,
            "confidence": avg_confidence,
            "consensus": consensus,
            "supporting_experts": len(supporting_opinions),
            "total_experts": len(opinions),
            "evidence": [o.evidence for o in supporting_opinions]
        }


class WorkflowGraph:
    """DAG-based workflow for agent coordination."""
    
    def __init__(self):
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: Dict[str, List[str]] = {}
    
    def add_node(
        self,
        node_id: str,
        agent_role: AgentRole,
        task: str,
        inputs: List[str]
    ) -> None:
        """Add a node to the workflow."""
        self._nodes[node_id] = {
            "agent_role": agent_role,
            "task": task,
            "inputs": inputs,
            "status": "pending",
            "result": None
        }
        
        self._edges[node_id] = []
    
    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add an edge between nodes."""
        if from_node not in self._edges:
            self._edges[from_node] = []
        
        self._edges[from_node].append(to_node)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the workflow."""
        results = {}
        
        # Topological sort
        execution_order = self._topological_sort()
        
        if not execution_order:
            logger.error("Workflow has cycles, cannot execute")
            return {}
        
        registry = get_agent_registry()
        
        for node_id in execution_order:
            node = self._nodes[node_id]
            
            # Get agents for this role
            agents = registry.get_agents_by_role(node["agent_role"])
            
            if not agents:
                logger.warning(f"No agents available for role {node['agent_role'].value}")
                continue
            
            # Execute task with first available agent
            agent = agents[0]
            
            try:
                # Prepare inputs
                task_context = {**context}
                for input_node in node["inputs"]:
                    if input_node in results:
                        task_context[input_node] = results[input_node]
                
                # Execute
                result = await agent.make_decision({
                    "task": node["task"],
                    **task_context
                })
                
                node["status"] = "completed"
                node["result"] = result
                results[node_id] = result
                
            except Exception as exc:
                logger.error(f"Failed to execute node {node_id}: {exc}")
                node["status"] = "failed"
        
        return results
    
    def _topological_sort(self) -> List[str]:
        """Topological sort of workflow nodes."""
        in_degree = {node: 0 for node in self._nodes}
        
        for node in self._edges:
            for neighbor in self._edges[node]:
                in_degree[neighbor] = in_degree.get(neighbor, 0) + 1
        
        queue = [node for node in self._nodes if in_degree[node] == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            
            for neighbor in self._edges.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        if len(result) != len(self._nodes):
            return []  # Cycle detected
        
        return result


class ConflictResolver:
    """Resolves conflicts between agent decisions."""
    
    def __init__(self, strategy: ConflictResolution = ConflictResolution.WEIGHTED_AVERAGE):
        self.strategy = strategy
    
    async def resolve(
        self,
        decisions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve conflicting decisions."""
        if not decisions:
            return {"decision": "no_input", "confidence": 0.0}
        
        if len(decisions) == 1:
            return decisions[0]
        
        if self.strategy == ConflictResolution.HIGHEST_CONFIDENCE:
            return max(decisions, key=lambda d: d.get("confidence", 0.0))
        
        elif self.strategy == ConflictResolution.WEIGHTED_AVERAGE:
            return self._weighted_average(decisions)
        
        elif self.strategy == ConflictResolution.EXPERT_OVERRIDE:
            return self._expert_override(decisions, context)
        
        elif self.strategy == ConflictResolution.GOVERNANCE_DECISION:
            return await self._governance_decision(decisions, context)
        
        else:
            return decisions[0]
    
    def _weighted_average(self, decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Weighted average of numeric decisions."""
        total_weight = sum(d.get("confidence", 0.5) for d in decisions)
        
        if total_weight == 0:
            return decisions[0]
        
        # For numeric decisions, compute weighted average
        if all(isinstance(d.get("value"), (int, float)) for d in decisions):
            weighted_sum = sum(
                d.get("value", 0) * d.get("confidence", 0.5)
                for d in decisions
            )
            
            return {
                "value": weighted_sum / total_weight,
                "confidence": total_weight / len(decisions),
                "method": "weighted_average"
            }
        
        # For categorical decisions, use highest confidence
        return max(decisions, key=lambda d: d.get("confidence", 0.0))
    
    def _expert_override(
        self,
        decisions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Expert agents override others."""
        expert_roles = {AgentRole.GOVERNANCE, AgentRole.RISK, AgentRole.RESEARCH_SIGNAL}
        
        expert_decisions = [
            d for d in decisions
            if d.get("agent_role") in expert_roles
        ]
        
        if expert_decisions:
            return max(expert_decisions, key=lambda d: d.get("confidence", 0.0))
        
        return max(decisions, key=lambda d: d.get("confidence", 0.0))
    
    async def _governance_decision(
        self,
        decisions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Escalate to governance agent."""
        registry = get_agent_registry()
        governance_agents = registry.get_agents_by_role(AgentRole.GOVERNANCE)
        
        if not governance_agents:
            return self._weighted_average(decisions)
        
        gov_agent = governance_agents[0]
        
        try:
            result = await gov_agent.make_decision({
                "conflicting_decisions": decisions,
                **context
            })
            
            return result
            
        except Exception as exc:
            logger.error(f"Governance decision failed: {exc}")
            return self._weighted_average(decisions)


class SwarmCoordinator:
    """Coordinates swarm intelligence mechanisms."""
    
    def __init__(self):
        self._voting = SwarmVoting()
        self._conflict_resolver = ConflictResolver()
    
    async def coordinate_decision(
        self,
        question: str,
        context: Dict[str, Any],
        agent_roles: Optional[List[AgentRole]] = None
    ) -> Dict[str, Any]:
        """Coordinate a swarm decision."""
        registry = get_agent_registry()
        
        # Get relevant agents
        if agent_roles:
            agents = []
            for role in agent_roles:
                agents.extend(registry.get_agents_by_role(role))
        else:
            agents = registry.get_all_agents()
        
        # Collect votes
        votes = await self._voting.collect_votes(agents, question, context)
        
        # Tally votes
        result = self._voting.tally_votes(votes)
        
        return {
            "decision": result.decision,
            "confidence": result.confidence,
            "agreement_score": result.agreement_score,
            "total_votes": result.total_votes,
            "method": "swarm_voting"
        }
    
    async def consult_experts(
        self,
        question: str,
        context: Dict[str, Any],
        expert_roles: List[AgentRole]
    ) -> Dict[str, Any]:
        """Consult expert panel."""
        panel = ExpertPanel(expert_roles)
        opinions = await panel.consult_experts(question, context)
        return panel.synthesize_opinions(opinions)
    
    async def execute_workflow(
        self,
        workflow: WorkflowGraph,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a workflow graph."""
        return await workflow.execute(context)
    
    async def resolve_conflict(
        self,
        decisions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve conflicting decisions."""
        return await self._conflict_resolver.resolve(decisions, context)


# Global coordinator
_swarm_coordinator: Optional[SwarmCoordinator] = None
_swarm_coordinator_lock = threading.Lock()


def get_swarm_coordinator() -> SwarmCoordinator:
    """Get the global swarm coordinator."""
    global _swarm_coordinator
    if _swarm_coordinator is None:
        with _swarm_coordinator_lock:
            if _swarm_coordinator is None:
                _swarm_coordinator = SwarmCoordinator()
    return _swarm_coordinator
