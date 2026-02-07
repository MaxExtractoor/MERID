"""
MERID Agent Explainability Framework
Constitutional requirement: All agent decisions must be explainable
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import json

from utils.logger import get_logger

logger = get_logger("agents.explainability")


class DecisionType(Enum):
    """Types of agent decisions"""
    SIGNAL = "signal"
    VOTE = "vote"
    ANALYSIS = "analysis"
    RECOMMENDATION = "recommendation"
    ACTION = "action"


@dataclass
class DecisionReasoning:
    """Structured reasoning for an agent decision"""
    decision_id: str
    agent_id: str
    decision_type: DecisionType
    timestamp: float
    
    # Core decision
    decision: str
    confidence: float
    
    # Reasoning components
    primary_reason: str
    supporting_factors: List[str]
    contrary_factors: List[str]
    data_sources: List[str]
    
    # Context
    market_context: Dict[str, Any] = field(default_factory=dict)
    risk_assessment: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    processing_time_ms: float = 0.0
    model_version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "decision_id": self.decision_id,
            "agent_id": self.agent_id,
            "decision_type": self.decision_type.value,
            "timestamp": self.timestamp,
            "decision": self.decision,
            "confidence": round(self.confidence, 4),
            "primary_reason": self.primary_reason,
            "supporting_factors": self.supporting_factors,
            "contrary_factors": self.contrary_factors,
            "data_sources": self.data_sources,
            "market_context": self.market_context,
            "risk_assessment": self.risk_assessment,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "model_version": self.model_version
        }
    
    def to_human_readable(self) -> str:
        """Convert to human-readable explanation"""
        lines = [
            f"Decision: {self.decision} (Confidence: {self.confidence:.1%})",
            f"Agent: {self.agent_id}",
            f"",
            f"Primary Reason:",
            f"  {self.primary_reason}",
            f"",
            f"Supporting Factors:",
        ]
        
        for factor in self.supporting_factors:
            lines.append(f"  + {factor}")
        
        if self.contrary_factors:
            lines.append("")
            lines.append("Contrary Factors:")
            for factor in self.contrary_factors:
                lines.append(f"  - {factor}")
        
        lines.append("")
        lines.append(f"Data Sources: {', '.join(self.data_sources)}")
        
        if self.risk_assessment:
            lines.append("")
            lines.append("Risk Assessment:")
            for key, value in self.risk_assessment.items():
                lines.append(f"  {key}: {value}")
        
        return "\n".join(lines)


class ExplainabilityTracker:
    """Tracks and stores agent decision reasoning"""
    
    def __init__(self, max_history: int = 10000):
        self.max_history = max_history
        self.decisions: List[DecisionReasoning] = []
        self._decisions_by_agent: Dict[str, List[DecisionReasoning]] = {}
        
        logger.info("Explainability tracker initialized")
    
    def record_decision(self, reasoning: DecisionReasoning) -> None:
        """Record a decision with reasoning"""
        self.decisions.append(reasoning)
        
        # Index by agent
        if reasoning.agent_id not in self._decisions_by_agent:
            self._decisions_by_agent[reasoning.agent_id] = []
        self._decisions_by_agent[reasoning.agent_id].append(reasoning)
        
        # Trim history
        if len(self.decisions) > self.max_history:
            oldest = self.decisions.pop(0)
            agent_list = self._decisions_by_agent.get(oldest.agent_id, [])
            if oldest in agent_list:
                agent_list.remove(oldest)
        
        logger.debug(
            f"Recorded decision: {reasoning.agent_id} -> {reasoning.decision} "
            f"(confidence: {reasoning.confidence:.2f})"
        )
    
    def get_agent_decisions(
        self,
        agent_id: str,
        limit: int = 50
    ) -> List[DecisionReasoning]:
        """Get recent decisions for an agent"""
        decisions = self._decisions_by_agent.get(agent_id, [])
        return decisions[-limit:]
    
    def get_decision_by_id(self, decision_id: str) -> Optional[DecisionReasoning]:
        """Get specific decision by ID"""
        for decision in reversed(self.decisions):
            if decision.decision_id == decision_id:
                return decision
        return None
    
    def get_recent_decisions(self, limit: int = 100) -> List[DecisionReasoning]:
        """Get recent decisions across all agents"""
        return self.decisions[-limit:]
    
    def get_decision_stats(self) -> Dict[str, Any]:
        """Get decision statistics"""
        total = len(self.decisions)
        
        if total == 0:
            return {
                "total_decisions": 0,
                "agents_active": 0,
                "avg_confidence": 0.0
            }
        
        avg_confidence = sum(d.confidence for d in self.decisions) / total
        
        decision_types = {}
        for d in self.decisions:
            dt = d.decision_type.value
            decision_types[dt] = decision_types.get(dt, 0) + 1
        
        return {
            "total_decisions": total,
            "agents_active": len(self._decisions_by_agent),
            "avg_confidence": round(avg_confidence, 4),
            "decision_types": decision_types,
            "recent_decisions": [d.to_dict() for d in self.decisions[-10:]]
        }


class ReasoningBuilder:
    """Helper to build decision reasoning"""
    
    def __init__(self, agent_id: str, decision_type: DecisionType):
        self.agent_id = agent_id
        self.decision_type = decision_type
        self.start_time = time.time()
        
        self.decision: Optional[str] = None
        self.confidence: float = 0.0
        self.primary_reason: str = ""
        self.supporting_factors: List[str] = []
        self.contrary_factors: List[str] = []
        self.data_sources: List[str] = []
        self.market_context: Dict[str, Any] = {}
        self.risk_assessment: Dict[str, Any] = {}
    
    def set_decision(self, decision: str, confidence: float) -> 'ReasoningBuilder':
        """Set the core decision"""
        self.decision = decision
        self.confidence = confidence
        return self
    
    def set_primary_reason(self, reason: str) -> 'ReasoningBuilder':
        """Set primary reasoning"""
        self.primary_reason = reason
        return self
    
    def add_supporting_factor(self, factor: str) -> 'ReasoningBuilder':
        """Add supporting factor"""
        self.supporting_factors.append(factor)
        return self
    
    def add_contrary_factor(self, factor: str) -> 'ReasoningBuilder':
        """Add contrary factor"""
        self.contrary_factors.append(factor)
        return self
    
    def add_data_source(self, source: str) -> 'ReasoningBuilder':
        """Add data source"""
        if source not in self.data_sources:
            self.data_sources.append(source)
        return self
    
    def set_market_context(self, context: Dict[str, Any]) -> 'ReasoningBuilder':
        """Set market context"""
        self.market_context = context
        return self
    
    def set_risk_assessment(self, assessment: Dict[str, Any]) -> 'ReasoningBuilder':
        """Set risk assessment"""
        self.risk_assessment = assessment
        return self
    
    def build(self) -> DecisionReasoning:
        """Build the reasoning object"""
        if not self.decision:
            raise ValueError("Decision must be set")
        
        processing_time = (time.time() - self.start_time) * 1000
        
        return DecisionReasoning(
            decision_id=str(uuid.uuid4()),
            agent_id=self.agent_id,
            decision_type=self.decision_type,
            timestamp=time.time(),
            decision=self.decision,
            confidence=self.confidence,
            primary_reason=self.primary_reason,
            supporting_factors=self.supporting_factors,
            contrary_factors=self.contrary_factors,
            data_sources=self.data_sources,
            market_context=self.market_context,
            risk_assessment=self.risk_assessment,
            processing_time_ms=processing_time
        )


# Global tracker instance
_explainability_tracker: Optional[ExplainabilityTracker] = None


def get_explainability_tracker() -> ExplainabilityTracker:
    """Get global explainability tracker"""
    global _explainability_tracker
    if _explainability_tracker is None:
        _explainability_tracker = ExplainabilityTracker()
    return _explainability_tracker


def create_reasoning_builder(
    agent_id: str,
    decision_type: DecisionType
) -> ReasoningBuilder:
    """Create a new reasoning builder"""
    return ReasoningBuilder(agent_id, decision_type)
