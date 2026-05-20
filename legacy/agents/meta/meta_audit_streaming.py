"""
Meta-Audit Agent - Streaming implementation.

Monitors agent performance and updates trust scores.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from collections import defaultdict
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class MetaAuditAgent(StreamingAgent):
    """
    Agent performance monitoring and trust updates.
    
    Tracks:
    - Agent output frequency
    - Confidence accuracy
    - Veto/challenge rates
    - Trust score adjustments
    """
    
    def __init__(self, agent_id: str = "meta-audit-agent-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.AGENT_OUTPUT, EventChannel.CONSENSUS],
            model="merid-interface:latest"
        )
        
        # Performance tracking
        self.agent_stats: Dict[str, Dict] = defaultdict(lambda: {
            "outputs": 0,
            "vetoes": 0,
            "challenges": 0,
            "avg_confidence": 0.0,
            "trust_score": 1.0
        })
        
        self.audit_interval = 10  # Emit audit every N events
        self.event_count = 0
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Track agent performance and emit trust updates.
        
        Emits:
        - trust_update: Updated trust scores for agents
        - performance_audit: Periodic performance summary
        """
        self.event_count += 1
        
        # Track agent outputs
        if event.channel == EventChannel.AGENT_OUTPUT:
            self._track_agent_output(event)
        
        # Track consensus outcomes
        if event.channel == EventChannel.CONSENSUS:
            self._track_consensus(event)
        
        # Emit periodic audit
        if self.event_count >= self.audit_interval:
            self.event_count = 0
            return self._generate_audit()
        
        return None
    
    def _track_agent_output(self, event: StreamEvent):
        """Track agent output statistics."""
        source = event.source
        data = event.data
        
        stats = self.agent_stats[source]
        stats["outputs"] += 1
        
        # Track confidence
        confidence = data.get("confidence", 0.5)
        n = stats["outputs"]
        stats["avg_confidence"] = (stats["avg_confidence"] * (n-1) + confidence) / n
        
        # Track vetoes and challenges
        event_type = event.event_type
        if event_type == "risk_veto":
            stats["vetoes"] += 1
        if event_type == "skeptic_challenge":
            stats["challenges"] += 1
    
    def _track_consensus(self, event: StreamEvent):
        """Track consensus outcomes for trust adjustment."""
        data = event.data
        
        # If consensus includes agent votes, adjust trust
        votes = data.get("votes", [])
        decision = data.get("decision", "")
        
        for vote in votes:
            agent_id = vote.get("agent_id")
            if not agent_id:
                continue
            
            # Adjust trust based on alignment with decision
            vote_signal = vote.get("signal", "")
            if decision and vote_signal:
                if self._signals_align(vote_signal, decision):
                    self._adjust_trust(agent_id, 0.01)  # Small increase
                else:
                    self._adjust_trust(agent_id, -0.02)  # Larger decrease
    
    def _signals_align(self, signal: str, decision: str) -> bool:
        """Check if signal aligns with decision."""
        signal = signal.lower()
        decision = decision.lower()
        
        if "bullish" in signal and ("long" in decision or "buy" in decision):
            return True
        if "bearish" in signal and ("short" in decision or "sell" in decision):
            return True
        return False
    
    def _adjust_trust(self, agent_id: str, delta: float):
        """Adjust agent trust score."""
        stats = self.agent_stats[agent_id]
        new_trust = stats["trust_score"] + delta
        stats["trust_score"] = max(0.1, min(2.0, new_trust))  # Bound [0.1, 2.0]
    
    def _generate_audit(self) -> Dict[str, Any]:
        """Generate performance audit."""
        agent_summaries = []
        
        for agent_id, stats in self.agent_stats.items():
            if stats["outputs"] > 0:
                agent_summaries.append({
                    "agent_id": agent_id,
                    "outputs": stats["outputs"],
                    "avg_confidence": round(stats["avg_confidence"], 3),
                    "trust_score": round(stats["trust_score"], 3),
                    "vetoes": stats["vetoes"],
                    "challenges": stats["challenges"]
                })
        
        return {
            "type": "performance_audit",
            "agent_count": len(agent_summaries),
            "agents": agent_summaries,
            "reasoning": f"Audit of {len(agent_summaries)} agents after {self.audit_interval} events"
        }
