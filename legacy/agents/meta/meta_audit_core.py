"""
MetaAuditAgent - System health monitoring per MASTER_SPEC v1.0

Agent ID: meta-audit-agent-01
Role: System health and audit
Expertise: 0.86
Risk Factor: 0.3

This agent:
- Monitors overall system health
- Audits agent behavior and consensus
- Detects anomalies and drift
- Ensures governance compliance

Reference: MASTER_SPEC.md Section 4.1
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from agents.interface import (
    AgentInterface,
    AgentVote,
    VoteDecision,
    MarketState,
    Proposal,
    Outcome,
    AgentState,
    AgentHealth,
)
from utils.logger import get_logger

logger = get_logger("agents.meta_audit")


@dataclass
class AuditFinding:
    """An audit finding or anomaly."""
    finding_id: str
    finding_type: str
    severity: str
    description: str
    affected_component: str
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False


@dataclass
class SystemHealthSnapshot:
    """Snapshot of overall system health."""
    timestamp: float
    healthy_agents: int
    total_agents: int
    consensus_success_rate: float
    avg_latency_ms: float
    error_rate: float
    anomaly_count: int


class MetaAuditAgent(AgentInterface):
    """
    Meta Audit Agent - System health and governance auditor.
    
    Capabilities:
    - Monitors agent health and heartbeats
    - Audits consensus decisions for anomalies
    - Detects behavioral drift in agents
    - Ensures governance rules are followed
    - Triggers alerts for system issues
    
    This agent acts as the system's internal auditor,
    ensuring all components operate within spec.
    """
    
    AGENT_ID = "meta-audit-agent-01"
    EXPERTISE_SCORE = 0.86
    RISK_FACTOR = 0.3
    
    HEALTH_CHECK_INTERVAL = 30.0
    ANOMALY_THRESHOLD = 0.3
    MAX_LATENCY_MS = 1000.0
    MAX_ERROR_RATE = 0.1
    
    def __init__(self) -> None:
        """Initialize meta audit agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._agent_health_cache: Dict[str, AgentHealth] = {}
        self._findings: List[AuditFinding] = []
        self._health_history: List[SystemHealthSnapshot] = []
        self._consensus_outcomes: List[Dict[str, object]] = []
        self._last_analysis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
        
        self._monitored_agents: Set[str] = {
            "market-analyst-01",
            "news-analyst-01",
            "risk-agent-01",
            "skeptic-agent-01",
            "synthesizer-agent-01",
            "strategy-agent-01",
            "archivist-agent-01",
        }
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Observe system state.
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        self.set_working_memory("last_observation", time.time())
    
    def update_agent_health(self, health: AgentHealth) -> None:
        """
        Update cached health for an agent.
        
        Args:
            health: Agent health status
        """
        self._agent_health_cache[health.agent_id] = health
        
        if not health.is_healthy():
            self._record_finding(
                finding_type="unhealthy_agent",
                severity="warning",
                description=f"Agent {health.agent_id} is unhealthy: state={health.state.value}",
                affected_component=health.agent_id,
            )
    
    def record_consensus_outcome(
        self,
        round_id: str,
        state: str,
        vote_count: int,
        approval_ratio: float,
        duration_ms: float,
    ) -> None:
        """
        Record a consensus outcome for auditing.
        
        Args:
            round_id: Consensus round ID
            state: Final state
            vote_count: Number of votes
            approval_ratio: Approval ratio
            duration_ms: Round duration
        """
        self._consensus_outcomes.append({
            "round_id": round_id,
            "state": state,
            "vote_count": vote_count,
            "approval_ratio": approval_ratio,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })
        
        if len(self._consensus_outcomes) > 200:
            self._consensus_outcomes = self._consensus_outcomes[-200:]
        
        if duration_ms > self.MAX_LATENCY_MS:
            self._record_finding(
                finding_type="slow_consensus",
                severity="warning",
                description=f"Consensus round {round_id} took {duration_ms:.0f}ms (threshold: {self.MAX_LATENCY_MS}ms)",
                affected_component="consensus_engine",
            )
        
        if vote_count < 5:
            self._record_finding(
                finding_type="low_quorum",
                severity="warning",
                description=f"Consensus round {round_id} had only {vote_count} votes",
                affected_component="consensus_engine",
            )
    
    async def analyze(self) -> Dict[str, object]:
        """
        Analyze system health and generate audit report.
        
        Returns:
            Audit analysis results
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        healthy_count = sum(
            1 for h in self._agent_health_cache.values()
            if h.is_healthy()
        )
        total_count = len(self._agent_health_cache)
        
        consensus_success_rate = self._calculate_consensus_success_rate()
        avg_latency = self._calculate_avg_consensus_latency()
        error_rate = self._calculate_error_rate()
        
        active_findings = [f for f in self._findings if not f.resolved]
        
        snapshot = SystemHealthSnapshot(
            timestamp=time.time(),
            healthy_agents=healthy_count,
            total_agents=total_count,
            consensus_success_rate=consensus_success_rate,
            avg_latency_ms=avg_latency,
            error_rate=error_rate,
            anomaly_count=len(active_findings),
        )
        self._health_history.append(snapshot)
        if len(self._health_history) > 100:
            self._health_history = self._health_history[-100:]
        
        if healthy_count < total_count * 0.6:
            system_status = "degraded"
        elif len(active_findings) > 5:
            system_status = "warning"
        elif error_rate > self.MAX_ERROR_RATE:
            system_status = "warning"
        else:
            system_status = "healthy"
        
        self._last_analysis = {
            "timestamp": time.time(),
            "system_status": system_status,
            "healthy_agents": healthy_count,
            "total_agents": total_count,
            "agent_health_ratio": healthy_count / max(total_count, 1),
            "consensus_success_rate": consensus_success_rate,
            "avg_latency_ms": avg_latency,
            "error_rate": error_rate,
            "active_findings": len(active_findings),
            "findings_by_severity": self._group_findings_by_severity(active_findings),
            "recommendations": self._generate_recommendations(system_status, active_findings),
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Audit: status=%s, healthy=%d/%d, findings=%d",
            system_status, healthy_count, total_count, len(active_findings)
        )
        
        return self._last_analysis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote based on system health assessment.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with audit reasoning
        """
        self._state = AgentState.VOTING
        self.heartbeat()
        
        if proposal.is_expired():
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.0,
                reasoning="Proposal expired before vote could be cast",
            )
        
        if self._last_analysis is None:
            await self.analyze()
        
        decision, confidence, reasoning = self._evaluate_proposal(
            proposal.proposal_type, proposal.payload
        )
        
        self._prediction_history.append({
            "proposal_id": proposal.proposal_id,
            "decision": decision.value,
            "confidence": confidence,
            "timestamp": time.time(),
            "system_status": self._last_analysis.get("system_status") if self._last_analysis else "unknown",
        })
        
        if len(self._prediction_history) > 100:
            self._prediction_history = self._prediction_history[-100:]
        
        self._state = AgentState.READY
        
        return AgentVote(
            agent_id=self._agent_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
        )
    
    async def reflect(self, outcome: Outcome) -> None:
        """
        Update internal state based on outcome.
        
        Args:
            outcome: Outcome of the proposal
        """
        self._state = AgentState.REFLECTING
        self.heartbeat()
        self._state = AgentState.READY
    
    def _record_finding(
        self,
        finding_type: str,
        severity: str,
        description: str,
        affected_component: str,
    ) -> None:
        """Record an audit finding."""
        finding = AuditFinding(
            finding_id=f"{finding_type}_{int(time.time())}",
            finding_type=finding_type,
            severity=severity,
            description=description,
            affected_component=affected_component,
        )
        
        self._findings.append(finding)
        
        if len(self._findings) > 500:
            self._findings = self._findings[-500:]
        
        self._logger.warning(
            "Audit finding: [%s] %s - %s",
            severity.upper(), finding_type, description
        )
    
    def _calculate_consensus_success_rate(self) -> float:
        """Calculate consensus success rate."""
        if not self._consensus_outcomes:
            return 1.0
        
        recent = self._consensus_outcomes[-50:]
        successes = sum(
            1 for o in recent
            if o.get("state") in ("approved", "rejected")
        )
        
        return successes / len(recent)
    
    def _calculate_avg_consensus_latency(self) -> float:
        """Calculate average consensus latency."""
        if not self._consensus_outcomes:
            return 0.0
        
        recent = self._consensus_outcomes[-50:]
        latencies = [o.get("duration_ms", 0) for o in recent]
        
        return sum(latencies) / len(latencies)
    
    def _calculate_error_rate(self) -> float:
        """Calculate system error rate."""
        total_errors = sum(
            h.error_count for h in self._agent_health_cache.values()
        )
        total_processed = sum(
            h.processed_count for h in self._agent_health_cache.values()
        )
        
        if total_processed == 0:
            return 0.0
        
        return total_errors / total_processed
    
    def _group_findings_by_severity(
        self,
        findings: List[AuditFinding],
    ) -> Dict[str, int]:
        """Group findings by severity."""
        groups: Dict[str, int] = defaultdict(int)
        for finding in findings:
            groups[finding.severity] += 1
        return dict(groups)
    
    def _generate_recommendations(
        self,
        system_status: str,
        active_findings: List[AuditFinding],
    ) -> List[str]:
        """Generate recommendations based on findings."""
        recommendations = []
        
        if system_status == "degraded":
            recommendations.append("CRITICAL: System is degraded. Consider pausing trading operations.")
        
        unhealthy_findings = [f for f in active_findings if f.finding_type == "unhealthy_agent"]
        if unhealthy_findings:
            recommendations.append(
                f"Investigate {len(unhealthy_findings)} unhealthy agent(s). "
                f"Consider triggering resurrection protocol."
            )
        
        slow_findings = [f for f in active_findings if f.finding_type == "slow_consensus"]
        if slow_findings:
            recommendations.append(
                "Consensus latency is elevated. Check agent processing times."
            )
        
        if not recommendations:
            recommendations.append("System operating within normal parameters.")
        
        return recommendations
    
    def _evaluate_proposal(
        self,
        proposal_type: str,
        payload: Dict[str, object],
    ) -> tuple[VoteDecision, float, str]:
        """Evaluate proposal from system health perspective."""
        if self._last_analysis is None:
            return (VoteDecision.ABSTAIN, 0.3, "No audit analysis available")
        
        system_status = self._last_analysis.get("system_status", "unknown")
        active_findings = self._last_analysis.get("active_findings", 0)
        error_rate = self._last_analysis.get("error_rate", 0)
        
        if system_status == "degraded":
            return (
                VoteDecision.REJECT,
                0.90,
                f"System is DEGRADED. All proposals should be rejected until system health is restored. "
                f"Active findings: {active_findings}.",
            )
        
        if system_status == "warning" and proposal_type in ("buy", "sell", "long", "short"):
            return (
                VoteDecision.ABSTAIN,
                0.6,
                f"System has warnings ({active_findings} findings). "
                f"Recommend caution on trading proposals.",
            )
        
        if error_rate > self.MAX_ERROR_RATE:
            return (
                VoteDecision.ABSTAIN,
                0.5,
                f"Error rate ({error_rate:.1%}) exceeds threshold ({self.MAX_ERROR_RATE:.1%}). "
                f"System reliability concerns.",
            )
        
        return (
            VoteDecision.ABSTAIN,
            0.4,
            f"System status: {system_status}. No system-level objections to proposal.",
        )
    
    def resolve_finding(self, finding_id: str) -> bool:
        """Mark a finding as resolved."""
        for finding in self._findings:
            if finding.finding_id == finding_id:
                finding.resolved = True
                return True
        return False


_meta_audit_agent: Optional[MetaAuditAgent] = None
_meta_audit_agent_lock = threading.Lock()


def get_meta_audit_agent() -> MetaAuditAgent:
    """Get or create meta audit agent singleton."""
    global _meta_audit_agent
    if _meta_audit_agent is None:
        with _meta_audit_agent_lock:
            if _meta_audit_agent is None:
                _meta_audit_agent = MetaAuditAgent()
    return _meta_audit_agent
