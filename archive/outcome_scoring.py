"""
MERID-ARCHIVE Outcome-Based Agent Scoring

Tracks agent performance based on actual outcomes:
- Did the agent's prediction come true?
- How accurate was the confidence level?
- Did the agent's advice lead to profit or loss?

This is how MERID learns which agents to trust more.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("archive.outcome_scoring")


class OutcomeType(Enum):
    """Types of outcomes to track."""
    PREDICTION = "prediction"      # Agent predicted something
    RECOMMENDATION = "recommendation"  # Agent recommended action
    RISK_ASSESSMENT = "risk_assessment"  # Agent assessed risk
    SIGNAL = "signal"              # Agent emitted signal
    VOTE = "vote"                  # Agent voted in consensus


class OutcomeResult(Enum):
    """Result of an outcome."""
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIALLY_CORRECT = "partially_correct"
    PENDING = "pending"
    INVALIDATED = "invalidated"


@dataclass
class AgentOutcome:
    """A tracked outcome for an agent."""
    outcome_id: str
    agent_id: str
    outcome_type: OutcomeType
    prediction: Any
    confidence: float
    timestamp: float
    
    # Resolution
    actual_result: Optional[Any] = None
    result: OutcomeResult = OutcomeResult.PENDING
    resolved_at: Optional[float] = None
    
    # Scoring
    accuracy_score: float = 0.0  # How accurate was the prediction
    calibration_score: float = 0.0  # How well-calibrated was confidence
    profit_impact: float = 0.0  # USD impact if acted upon
    
    # Context
    symbol: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    
    def resolve(
        self,
        actual_result: Any,
        result: OutcomeResult,
        profit_impact: float = 0.0,
    ) -> None:
        """Resolve this outcome with actual result."""
        self.actual_result = actual_result
        self.result = result
        self.resolved_at = time.time()
        self.profit_impact = profit_impact
        
        # Calculate accuracy score
        if result == OutcomeResult.CORRECT:
            self.accuracy_score = 1.0
        elif result == OutcomeResult.PARTIALLY_CORRECT:
            self.accuracy_score = 0.5
        elif result == OutcomeResult.INCORRECT:
            self.accuracy_score = 0.0
        else:
            self.accuracy_score = 0.0
        
        # Calculate calibration score
        # Perfect calibration: 80% confident predictions are correct 80% of the time
        # Score = 1 - |confidence - accuracy|
        self.calibration_score = 1.0 - abs(self.confidence - self.accuracy_score)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "agent_id": self.agent_id,
            "outcome_type": self.outcome_type.value,
            "prediction": self.prediction,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "actual_result": self.actual_result,
            "result": self.result.value,
            "resolved_at": self.resolved_at,
            "accuracy_score": round(self.accuracy_score, 3),
            "calibration_score": round(self.calibration_score, 3),
            "profit_impact": self.profit_impact,
            "symbol": self.symbol,
        }


@dataclass
class AgentScorecard:
    """Cumulative scorecard for an agent."""
    agent_id: str
    
    # Counts
    total_outcomes: int = 0
    correct_outcomes: int = 0
    incorrect_outcomes: int = 0
    pending_outcomes: int = 0
    
    # Scores
    accuracy_rate: float = 0.0
    avg_calibration: float = 0.0
    total_profit_impact: float = 0.0
    
    # Trust
    base_trust: float = 0.5
    current_trust: float = 0.5
    trust_trend: str = "stable"
    
    # Time tracking
    first_outcome: float = 0.0
    last_outcome: float = 0.0
    
    def update_from_outcomes(self, outcomes: List[AgentOutcome]) -> None:
        """Update scorecard from outcomes."""
        if not outcomes:
            return
        
        resolved = [o for o in outcomes if o.result != OutcomeResult.PENDING]
        
        self.total_outcomes = len(outcomes)
        self.pending_outcomes = len(outcomes) - len(resolved)
        
        if resolved:
            self.correct_outcomes = sum(1 for o in resolved if o.result == OutcomeResult.CORRECT)
            self.incorrect_outcomes = sum(1 for o in resolved if o.result == OutcomeResult.INCORRECT)
            
            self.accuracy_rate = self.correct_outcomes / len(resolved)
            self.avg_calibration = sum(o.calibration_score for o in resolved) / len(resolved)
            self.total_profit_impact = sum(o.profit_impact for o in resolved)
            
            # Update trust based on recent performance
            recent = sorted(resolved, key=lambda x: x.resolved_at or 0)[-20:]
            if recent:
                recent_accuracy = sum(1 for o in recent if o.result == OutcomeResult.CORRECT) / len(recent)
                
                # Blend base trust with recent performance
                self.current_trust = 0.3 * self.base_trust + 0.7 * recent_accuracy
                
                # Determine trend
                if len(recent) >= 10:
                    first_half = recent[:len(recent)//2]
                    second_half = recent[len(recent)//2:]
                    
                    first_acc = sum(1 for o in first_half if o.result == OutcomeResult.CORRECT) / len(first_half)
                    second_acc = sum(1 for o in second_half if o.result == OutcomeResult.CORRECT) / len(second_half)
                    
                    if second_acc > first_acc + 0.1:
                        self.trust_trend = "improving"
                    elif second_acc < first_acc - 0.1:
                        self.trust_trend = "declining"
                    else:
                        self.trust_trend = "stable"
        
        timestamps = [o.timestamp for o in outcomes]
        self.first_outcome = min(timestamps)
        self.last_outcome = max(timestamps)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_outcomes": self.total_outcomes,
            "correct_outcomes": self.correct_outcomes,
            "incorrect_outcomes": self.incorrect_outcomes,
            "pending_outcomes": self.pending_outcomes,
            "accuracy_rate": round(self.accuracy_rate, 3),
            "avg_calibration": round(self.avg_calibration, 3),
            "total_profit_impact": round(self.total_profit_impact, 2),
            "current_trust": round(self.current_trust, 3),
            "trust_trend": self.trust_trend,
            "days_active": (self.last_outcome - self.first_outcome) / 86400 if self.first_outcome else 0,
        }


class OutcomeScoringEngine:
    """
    Tracks and scores agent outcomes.
    
    This is how MERID learns which agents to trust.
    """
    
    def __init__(self):
        self._outcomes: Dict[str, AgentOutcome] = {}
        self._outcomes_by_agent: Dict[str, List[str]] = {}
        self._scorecards: Dict[str, AgentScorecard] = {}
        self._outcome_count = 0
        self._max_outcomes = 50000
        
        logger.info("Outcome scoring engine initialized")
    
    def record_outcome(
        self,
        agent_id: str,
        outcome_type: OutcomeType,
        prediction: Any,
        confidence: float,
        symbol: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentOutcome:
        """Record a new outcome to track."""
        self._outcome_count += 1
        outcome_id = f"out_{agent_id}_{self._outcome_count}_{int(time.time())}"
        
        outcome = AgentOutcome(
            outcome_id=outcome_id,
            agent_id=agent_id,
            outcome_type=outcome_type,
            prediction=prediction,
            confidence=min(1.0, max(0.0, confidence)),
            timestamp=time.time(),
            symbol=symbol,
            context=context or {},
        )
        
        self._outcomes[outcome_id] = outcome
        
        if agent_id not in self._outcomes_by_agent:
            self._outcomes_by_agent[agent_id] = []
        self._outcomes_by_agent[agent_id].append(outcome_id)
        
        # Cleanup if needed
        if len(self._outcomes) > self._max_outcomes:
            self._cleanup_old_outcomes()
        
        logger.debug("Recorded outcome %s for agent %s", outcome_id, agent_id)
        return outcome
    
    def resolve_outcome(
        self,
        outcome_id: str,
        actual_result: Any,
        result: OutcomeResult,
        profit_impact: float = 0.0,
    ) -> Optional[AgentOutcome]:
        """Resolve an outcome with actual result."""
        outcome = self._outcomes.get(outcome_id)
        if not outcome:
            return None
        
        outcome.resolve(actual_result, result, profit_impact)
        
        # Update scorecard
        self._update_scorecard(outcome.agent_id)
        
        logger.info(
            "Resolved outcome %s: %s (accuracy: %.2f, profit: $%.2f)",
            outcome_id, result.value, outcome.accuracy_score, profit_impact
        )
        
        return outcome
    
    def _update_scorecard(self, agent_id: str) -> None:
        """Update scorecard for an agent."""
        outcome_ids = self._outcomes_by_agent.get(agent_id, [])
        outcomes = [self._outcomes[oid] for oid in outcome_ids if oid in self._outcomes]
        
        if agent_id not in self._scorecards:
            self._scorecards[agent_id] = AgentScorecard(agent_id=agent_id)
        
        self._scorecards[agent_id].update_from_outcomes(outcomes)
    
    def _cleanup_old_outcomes(self) -> None:
        """Remove oldest outcomes."""
        if len(self._outcomes) <= self._max_outcomes:
            return
        
        # Sort by timestamp and remove oldest 10%
        sorted_outcomes = sorted(self._outcomes.values(), key=lambda x: x.timestamp)
        to_remove = sorted_outcomes[:len(sorted_outcomes) // 10]
        
        for outcome in to_remove:
            del self._outcomes[outcome.outcome_id]
            if outcome.agent_id in self._outcomes_by_agent:
                self._outcomes_by_agent[outcome.agent_id] = [
                    oid for oid in self._outcomes_by_agent[outcome.agent_id]
                    if oid != outcome.outcome_id
                ]
    
    def get_agent_scorecard(self, agent_id: str) -> Optional[AgentScorecard]:
        """Get scorecard for an agent."""
        self._update_scorecard(agent_id)
        return self._scorecards.get(agent_id)
    
    def get_all_scorecards(self) -> List[AgentScorecard]:
        """Get all agent scorecards."""
        for agent_id in self._outcomes_by_agent:
            self._update_scorecard(agent_id)
        return list(self._scorecards.values())
    
    def get_agent_outcomes(
        self,
        agent_id: str,
        limit: int = 50,
        include_pending: bool = True,
    ) -> List[AgentOutcome]:
        """Get outcomes for an agent."""
        outcome_ids = self._outcomes_by_agent.get(agent_id, [])
        outcomes = [self._outcomes[oid] for oid in outcome_ids if oid in self._outcomes]
        
        if not include_pending:
            outcomes = [o for o in outcomes if o.result != OutcomeResult.PENDING]
        
        return sorted(outcomes, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_pending_outcomes(self, max_age_hours: float = 24) -> List[AgentOutcome]:
        """Get pending outcomes that need resolution."""
        cutoff = time.time() - (max_age_hours * 3600)
        return [
            o for o in self._outcomes.values()
            if o.result == OutcomeResult.PENDING and o.timestamp > cutoff
        ]
    
    def get_leaderboard(self, min_outcomes: int = 10) -> List[Dict[str, Any]]:
        """Get agent leaderboard by accuracy."""
        scorecards = self.get_all_scorecards()
        
        # Filter by minimum outcomes
        qualified = [s for s in scorecards if s.total_outcomes >= min_outcomes]
        
        # Sort by accuracy
        ranked = sorted(qualified, key=lambda x: x.accuracy_rate, reverse=True)
        
        return [
            {
                "rank": i + 1,
                **s.to_dict(),
            }
            for i, s in enumerate(ranked)
        ]
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        all_outcomes = list(self._outcomes.values())
        resolved = [o for o in all_outcomes if o.result != OutcomeResult.PENDING]
        
        return {
            "total_outcomes": len(all_outcomes),
            "resolved_outcomes": len(resolved),
            "pending_outcomes": len(all_outcomes) - len(resolved),
            "tracked_agents": len(self._outcomes_by_agent),
            "overall_accuracy": (
                sum(1 for o in resolved if o.result == OutcomeResult.CORRECT) / len(resolved)
                if resolved else 0
            ),
            "total_profit_impact": sum(o.profit_impact for o in resolved),
        }


# Singleton
_scoring_engine: Optional[OutcomeScoringEngine] = None


def get_outcome_scoring() -> OutcomeScoringEngine:
    """Get the singleton outcome scoring engine."""
    global _scoring_engine
    if _scoring_engine is None:
        _scoring_engine = OutcomeScoringEngine()
    return _scoring_engine
