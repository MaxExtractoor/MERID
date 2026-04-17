"""
MERID Trust Score Transparency System
Constitutional requirement: Trust scores must be verifiable and explainable
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import json

from utils.logger import get_logger

logger = get_logger("core.trust_transparency")


class TrustAdjustmentReason(Enum):
    """Reasons for trust score adjustments"""
    ACCURATE_PREDICTION = "accurate_prediction"
    INACCURATE_PREDICTION = "inaccurate_prediction"
    CONSISTENT_PERFORMANCE = "consistent_performance"
    INCONSISTENT_PERFORMANCE = "inconsistent_performance"
    TIMELY_RESPONSE = "timely_response"
    DELAYED_RESPONSE = "delayed_response"
    CONSENSUS_ALIGNMENT = "consensus_alignment"
    CONSENSUS_DIVERGENCE = "consensus_divergence"
    MANUAL_ADJUSTMENT = "manual_adjustment"
    INITIALIZATION = "initialization"


@dataclass
class TrustAdjustmentEvent:
    """Record of a trust score adjustment"""
    event_id: str
    agent_id: str
    timestamp: float
    
    # Trust change
    old_score: float
    new_score: float
    delta: float
    
    # Reason and context
    reason: TrustAdjustmentReason
    explanation: str
    contributing_factors: Dict[str, float]
    
    # Supporting data
    accuracy_metric: Optional[float] = None
    consistency_metric: Optional[float] = None
    timeliness_metric: Optional[float] = None
    alignment_metric: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "old_score": round(self.old_score, 4),
            "new_score": round(self.new_score, 4),
            "delta": round(self.delta, 4),
            "reason": self.reason.value,
            "explanation": self.explanation,
            "contributing_factors": {
                k: round(v, 4) for k, v in self.contributing_factors.items()
            },
            "accuracy_metric": round(self.accuracy_metric, 4) if self.accuracy_metric else None,
            "consistency_metric": round(self.consistency_metric, 4) if self.consistency_metric else None,
            "timeliness_metric": round(self.timeliness_metric, 4) if self.timeliness_metric else None,
            "alignment_metric": round(self.alignment_metric, 4) if self.alignment_metric else None
        }


@dataclass
class TrustFormula:
    """Trust score calculation formula"""
    accuracy_weight: float = 0.4
    consistency_weight: float = 0.3
    timeliness_weight: float = 0.2
    alignment_weight: float = 0.1
    
    def calculate(
        self,
        accuracy: float,
        consistency: float,
        timeliness: float,
        alignment: float
    ) -> float:
        """Calculate trust score from components"""
        score = (
            accuracy * self.accuracy_weight +
            consistency * self.consistency_weight +
            timeliness * self.timeliness_weight +
            alignment * self.alignment_weight
        )
        return max(0.0, min(1.0, score))
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "accuracy_weight": self.accuracy_weight,
            "consistency_weight": self.consistency_weight,
            "timeliness_weight": self.timeliness_weight,
            "alignment_weight": self.alignment_weight
        }


@dataclass
class AgentTrustProfile:
    """Complete trust profile for an agent"""
    agent_id: str
    current_score: float
    
    # Component metrics
    accuracy: float = 0.0
    consistency: float = 0.0
    timeliness: float = 0.0
    alignment: float = 0.0
    
    # Historical data
    adjustment_history: List[TrustAdjustmentEvent] = field(default_factory=list)
    
    # Performance tracking
    total_predictions: int = 0
    correct_predictions: int = 0
    total_response_time_ms: float = 0.0
    consensus_agreements: int = 0
    consensus_disagreements: int = 0
    
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def get_accuracy_rate(self) -> float:
        """Get prediction accuracy rate"""
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions
    
    def get_avg_response_time(self) -> float:
        """Get average response time in ms"""
        if self.total_predictions == 0:
            return 0.0
        return self.total_response_time_ms / self.total_predictions
    
    def get_consensus_alignment_rate(self) -> float:
        """Get consensus alignment rate"""
        total = self.consensus_agreements + self.consensus_disagreements
        if total == 0:
            return 0.0
        return self.consensus_agreements / total
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "current_score": round(self.current_score, 4),
            "accuracy": round(self.accuracy, 4),
            "consistency": round(self.consistency, 4),
            "timeliness": round(self.timeliness, 4),
            "alignment": round(self.alignment, 4),
            "performance": {
                "total_predictions": self.total_predictions,
                "correct_predictions": self.correct_predictions,
                "accuracy_rate": round(self.get_accuracy_rate(), 4),
                "avg_response_time_ms": round(self.get_avg_response_time(), 2),
                "consensus_alignment_rate": round(self.get_consensus_alignment_rate(), 4)
            },
            "recent_adjustments": [
                e.to_dict() for e in self.adjustment_history[-10:]
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class TrustScoreManager:
    """Manages trust scores with full transparency"""
    
    def __init__(self):
        self.formula = TrustFormula()
        self.profiles: Dict[str, AgentTrustProfile] = {}
        self.all_adjustments: List[TrustAdjustmentEvent] = []
        
        logger.info("Trust score manager initialized")
        logger.info(f"Trust formula: {self.formula.to_dict()}")
    
    def initialize_agent(self, agent_id: str, initial_score: float = 1.0) -> None:
        """Initialize trust profile for new agent"""
        if agent_id in self.profiles:
            return
        
        profile = AgentTrustProfile(
            agent_id=agent_id,
            current_score=initial_score,
            accuracy=initial_score,
            consistency=initial_score,
            timeliness=initial_score,
            alignment=initial_score
        )
        
        self.profiles[agent_id] = profile
        
        # Record initialization event
        event = TrustAdjustmentEvent(
            event_id=str(uuid.uuid4()),
            agent_id=agent_id,
            timestamp=time.time(),
            old_score=0.0,
            new_score=initial_score,
            delta=initial_score,
            reason=TrustAdjustmentReason.INITIALIZATION,
            explanation=f"Agent {agent_id} initialized with trust score {initial_score}",
            contributing_factors={}
        )
        
        profile.adjustment_history.append(event)
        self.all_adjustments.append(event)
        
        logger.info(f"Trust profile initialized for {agent_id}: {initial_score}")
    
    def adjust_trust(
        self,
        agent_id: str,
        reason: TrustAdjustmentReason,
        explanation: str,
        accuracy: Optional[float] = None,
        consistency: Optional[float] = None,
        timeliness: Optional[float] = None,
        alignment: Optional[float] = None
    ) -> float:
        """Adjust trust score with full transparency"""
        if agent_id not in self.profiles:
            self.initialize_agent(agent_id)
        
        profile = self.profiles[agent_id]
        old_score = profile.current_score
        
        # Update component metrics if provided
        if accuracy is not None:
            profile.accuracy = accuracy
        if consistency is not None:
            profile.consistency = consistency
        if timeliness is not None:
            profile.timeliness = timeliness
        if alignment is not None:
            profile.alignment = alignment
        
        # Recalculate trust score
        new_score = self.formula.calculate(
            profile.accuracy,
            profile.consistency,
            profile.timeliness,
            profile.alignment
        )
        
        profile.current_score = new_score
        profile.updated_at = time.time()
        
        # Record adjustment event
        event = TrustAdjustmentEvent(
            event_id=str(uuid.uuid4()),
            agent_id=agent_id,
            timestamp=time.time(),
            old_score=old_score,
            new_score=new_score,
            delta=new_score - old_score,
            reason=reason,
            explanation=explanation,
            contributing_factors={
                "accuracy": profile.accuracy,
                "consistency": profile.consistency,
                "timeliness": profile.timeliness,
                "alignment": profile.alignment
            },
            accuracy_metric=accuracy,
            consistency_metric=consistency,
            timeliness_metric=timeliness,
            alignment_metric=alignment
        )
        
        profile.adjustment_history.append(event)
        self.all_adjustments.append(event)
        
        logger.info(
            f"Trust adjusted for {agent_id}: {old_score:.4f} -> {new_score:.4f} "
            f"(delta: {event.delta:+.4f}, reason: {reason.value})"
        )
        
        return new_score
    
    def record_prediction_outcome(
        self,
        agent_id: str,
        correct: bool,
        response_time_ms: float
    ) -> None:
        """Record prediction outcome and update trust"""
        if agent_id not in self.profiles:
            self.initialize_agent(agent_id)
        
        profile = self.profiles[agent_id]
        profile.total_predictions += 1
        profile.total_response_time_ms += response_time_ms
        
        if correct:
            profile.correct_predictions += 1
        
        # Update accuracy metric
        accuracy = profile.get_accuracy_rate()
        
        # Update timeliness metric (faster is better, normalize to 0-1)
        avg_response = profile.get_avg_response_time()
        timeliness = max(0.0, min(1.0, 1.0 - (avg_response / 10000)))  # 10s = 0 score
        
        # Adjust trust
        reason = TrustAdjustmentReason.ACCURATE_PREDICTION if correct else TrustAdjustmentReason.INACCURATE_PREDICTION
        explanation = f"Prediction {'correct' if correct else 'incorrect'}. Accuracy: {accuracy:.1%}, Response time: {response_time_ms:.0f}ms"
        
        self.adjust_trust(
            agent_id=agent_id,
            reason=reason,
            explanation=explanation,
            accuracy=accuracy,
            timeliness=timeliness
        )
    
    def record_consensus_participation(
        self,
        agent_id: str,
        aligned_with_consensus: bool
    ) -> None:
        """Record consensus participation and update trust"""
        if agent_id not in self.profiles:
            self.initialize_agent(agent_id)
        
        profile = self.profiles[agent_id]
        
        if aligned_with_consensus:
            profile.consensus_agreements += 1
        else:
            profile.consensus_disagreements += 1
        
        # Update alignment metric
        alignment = profile.get_consensus_alignment_rate()
        
        # Adjust trust
        reason = TrustAdjustmentReason.CONSENSUS_ALIGNMENT if aligned_with_consensus else TrustAdjustmentReason.CONSENSUS_DIVERGENCE
        explanation = f"{'Aligned with' if aligned_with_consensus else 'Diverged from'} consensus. Alignment rate: {alignment:.1%}"
        
        self.adjust_trust(
            agent_id=agent_id,
            reason=reason,
            explanation=explanation,
            alignment=alignment
        )
    
    def get_trust_score(self, agent_id: str) -> float:
        """Get current trust score"""
        if agent_id not in self.profiles:
            self.initialize_agent(agent_id)
        return self.profiles[agent_id].current_score
    
    def get_trust_profile(self, agent_id: str) -> Optional[AgentTrustProfile]:
        """Get complete trust profile"""
        return self.profiles.get(agent_id)
    
    def get_adjustment_history(
        self,
        agent_id: str,
        limit: int = 50
    ) -> List[TrustAdjustmentEvent]:
        """Get trust adjustment history for agent"""
        profile = self.profiles.get(agent_id)
        if not profile:
            return []
        return profile.adjustment_history[-limit:]
    
    def get_all_profiles(self) -> List[AgentTrustProfile]:
        """Get all agent trust profiles"""
        return list(self.profiles.values())
    
    def get_trust_stats(self) -> Dict[str, Any]:
        """Get trust system statistics"""
        if not self.profiles:
            return {
                "total_agents": 0,
                "avg_trust": 0.0,
                "total_adjustments": 0
            }
        
        scores = [p.current_score for p in self.profiles.values()]
        
        return {
            "total_agents": len(self.profiles),
            "avg_trust": round(sum(scores) / len(scores), 4),
            "min_trust": round(min(scores), 4),
            "max_trust": round(max(scores), 4),
            "total_adjustments": len(self.all_adjustments),
            "formula": self.formula.to_dict(),
            "top_agents": [
                {"agent_id": p.agent_id, "score": round(p.current_score, 4)}
                for p in sorted(self.profiles.values(), key=lambda x: x.current_score, reverse=True)[:10]
            ]
        }


# Global trust score manager
_trust_manager: Optional[TrustScoreManager] = None
_trust_manager_lock = threading.Lock()


def get_trust_manager() -> TrustScoreManager:
    """Get global trust score manager"""
    global _trust_manager
    if _trust_manager is None:
        with _trust_manager_lock:
            if _trust_manager is None:
                _trust_manager = TrustScoreManager()
    return _trust_manager
