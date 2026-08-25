"""
Agent Exit Recommendations

Provides interface for agents to recommend exits, along with aggregation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)


class ExitAction(Enum):
    """Exit action types."""
    HOLD = "hold"
    EXIT_MARKET = "exit_market"
    ADJUST_TP = "adjust_tp"
    ADJUST_SL = "adjust_sl"


@dataclass
class ExitRecommendation:
    """Exit recommendation from an agent."""
    should_exit: bool
    urgency: float  # 0.0-1.0, higher = more urgent
    reason: str
    suggested_price_cents: Optional[int] = None
    confidence: float = 0.0  # 0-1
    agent_id: str = ""


class ExitRecommendationAggregator:
    """Combines agent recommendations with rule-based exits."""
    
    def __init__(self, urgency_threshold: float = 0.7):
        """
        Initialize exit recommendation aggregator.
        
        Args:
            urgency_threshold: Minimum urgency to override rule-based exits
        """
        self._urgency_threshold = urgency_threshold
        logger.info("[EXIT-RECOMMENDATION-AGGREGATOR] Initialized with urgency_threshold=%.2f", urgency_threshold)
    
    def evaluate_exit(
        self,
        rule_based_exit: ExitAction,
        agent_recommendations: List[ExitRecommendation]
    ) -> ExitAction:
        """
        Combine rule-based exit with agent recommendations.
        
        Args:
            rule_based_exit: Exit action from rule-based evaluation
            agent_recommendations: List of agent exit recommendations
        
        Returns:
            Final exit action
        """
        if not agent_recommendations:
            # No agent recommendations, defer to rules
            return rule_based_exit
        
        # Check if any agent recommends urgent exit
        urgent_exits = [r for r in agent_recommendations if r.should_exit and r.urgency >= self._urgency_threshold]
        
        if urgent_exits:
            # Override rule-based exit with urgent agent recommendation
            logger.info(
                "[EXIT-RECOMMENDATION-AGGREGATOR] Override rule-based exit with urgent agent recommendation: %d agents",
                len(urgent_exits)
            )
            return ExitAction.EXIT_MARKET
        
        # Check if multiple agents agree on exit
        exit_recommendations = [r for r in agent_recommendations if r.should_exit]
        
        if len(exit_recommendations) >= 2:
            # Multiple agents agree, override rules
            logger.info(
                "[EXIT-RECOMMENDATION-AGGREGATOR] Override rule-based exit with multi-agent consensus: %d agents",
                len(exit_recommendations)
            )
            return ExitAction.EXIT_MARKET
        
        # Otherwise, defer to rule-based exit
        return rule_based_exit
    
    def get_aggregated_recommendation(
        self,
        agent_recommendations: List[ExitRecommendation]
    ) -> Optional[ExitRecommendation]:
        """
        Get aggregated recommendation from multiple agents.
        
        Args:
            agent_recommendations: List of agent exit recommendations
        
        Returns:
            Aggregated recommendation or None if no consensus
        """
        if not agent_recommendations:
            return None
        
        # Separate exit and hold recommendations
        exit_recs = [r for r in agent_recommendations if r.should_exit]
        hold_recs = [r for r in agent_recommendations if not r.should_exit]
        
        if not exit_recs:
            # All agents say hold
            return ExitRecommendation(
                should_exit=False,
                urgency=0.0,
                reason="All agents recommend hold",
                confidence=sum(r.confidence for r in hold_recs) / len(hold_recs) if hold_recs else 0.0,
            )
        
        if not hold_recs:
            # All agents say exit
            avg_urgency = sum(r.urgency for r in exit_recs) / len(exit_recs)
            avg_confidence = sum(r.confidence for r in exit_recs) / len(exit_recs)
            
            return ExitRecommendation(
                should_exit=True,
                urgency=avg_urgency,
                reason=f"All {len(exit_recs)} agents recommend exit",
                confidence=avg_confidence,
            )
        
        # Mixed recommendations - use weighted voting
        exit_weight = sum(r.confidence * r.urgency for r in exit_recs)
        hold_weight = sum(r.confidence * (1.0 - r.urgency) for r in hold_recs)
        
        if exit_weight > hold_weight:
            avg_urgency = sum(r.urgency for r in exit_recs) / len(exit_recs)
            avg_confidence = sum(r.confidence for r in exit_recs) / len(exit_recs)
            
            return ExitRecommendation(
                should_exit=True,
                urgency=avg_urgency,
                reason=f"Weighted exit: {len(exit_recs)} agents vs {len(hold_recs)} hold",
                confidence=avg_confidence,
            )
        else:
            avg_confidence = sum(r.confidence for r in hold_recs) / len(hold_recs)
            
            return ExitRecommendation(
                should_exit=False,
                urgency=0.0,
                reason=f"Weighted hold: {len(hold_recs)} agents vs {len(exit_recs)} exit",
                confidence=avg_confidence,
            )
