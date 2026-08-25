"""
Agent Exit Intelligence

Provides interface for agents to generate exit signals with aggregation logic.
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
class ExitSignal:
    """Exit signal from an agent."""
    action: ExitAction
    confidence: float  # 0-1
    reasoning: str
    suggested_price_cents: Optional[int] = None
    urgency: float = 0.5  # 0-1, higher = more urgent
    agent_id: str = ""


class ExitIntelligenceAggregator:
    """Combines exit signals from multiple agents."""
    
    def __init__(self, consensus_threshold: float = 0.6):
        """
        Initialize exit intelligence aggregator.
        
        Args:
            consensus_threshold: Minimum confidence threshold for consensus
        """
        self._consensus_threshold = consensus_threshold
        logger.info("[EXIT-INTELLIGENCE-AGGREGATOR] Initialized with consensus_threshold=%.2f", consensus_threshold)
    
    def aggregate_signals(
        self,
        agent_signals: List[ExitSignal],
        rule_based_exit: ExitAction
    ) -> ExitAction:
        """
        Combine agent signals with rule-based exit.
        
        Args:
            agent_signals: List of agent exit signals
            rule_based_exit: Exit action from rule-based evaluation
        
        Returns:
            Final exit action
        """
        if not agent_signals:
            # No agent signals, defer to rules
            return rule_based_exit
        
        # Separate exit and hold signals
        exit_signals = [s for s in agent_signals if s.action == ExitAction.EXIT_MARKET]
        hold_signals = [s for s in agent_signals if s.action == ExitAction.HOLD]
        
        if not exit_signals:
            # All agents say hold
            return ExitAction.HOLD
        
        if not hold_signals:
            # All agents say exit
            # Check if high confidence
            avg_confidence = sum(s.confidence for s in exit_signals) / len(exit_signals)
            if avg_confidence >= self._consensus_threshold:
                logger.info(
                    "[EXIT-INTELLIGENCE-AGGREGATOR] All agents exit with high confidence: %.2f",
                    avg_confidence
                )
                return ExitAction.EXIT_MARKET
            else:
                # Low confidence, defer to rules
                return rule_based_exit
        
        # Mixed signals - use weighted voting
        exit_weight = sum(s.confidence * s.urgency for s in exit_signals)
        hold_weight = sum(s.confidence * (1.0 - s.urgency) for s in hold_signals)
        
        if exit_weight > hold_weight and exit_weight >= self._consensus_threshold:
            logger.info(
                "[EXIT-INTELLIGENCE-AGGREGATOR] Weighted exit: exit_weight=%.2f hold_weight=%.2f",
                exit_weight,
                hold_weight
            )
            return ExitAction.EXIT_MARKET
        
        # Otherwise, defer to rule-based exit
        return rule_based_exit
    
    def get_aggregated_signal(
        self,
        agent_signals: List[ExitSignal]
    ) -> Optional[ExitSignal]:
        """
        Get aggregated signal from multiple agents.
        
        Args:
            agent_signals: List of agent exit signals
        
        Returns:
            Aggregated signal or None if no consensus
        """
        if not agent_signals:
            return None
        
        # Separate by action
        exit_signals = [s for s in agent_signals if s.action == ExitAction.EXIT_MARKET]
        hold_signals = [s for s in agent_signals if s.action == ExitAction.HOLD]
        adjust_signals = [s for s in agent_signals if s.action in (ExitAction.ADJUST_TP, ExitAction.ADJUST_SL)]
        
        if not exit_signals and not hold_signals and not adjust_signals:
            return None
        
        # If all agree on same action
        if len(exit_signals) == len(agent_signals):
            avg_confidence = sum(s.confidence for s in exit_signals) / len(exit_signals)
            avg_urgency = sum(s.urgency for s in exit_signals) / len(exit_signals)
            
            return ExitSignal(
                action=ExitAction.EXIT_MARKET,
                confidence=avg_confidence,
                reasoning=f"All {len(exit_signals)} agents recommend exit",
                urgency=avg_urgency,
            )
        
        if len(hold_signals) == len(agent_signals):
            avg_confidence = sum(s.confidence for s in hold_signals) / len(hold_signals)
            
            return ExitSignal(
                action=ExitAction.HOLD,
                confidence=avg_confidence,
                reasoning=f"All {len(hold_signals)} agents recommend hold",
                urgency=0.0,
            )
        
        # Mixed signals - return highest confidence signal
        best_signal = max(agent_signals, key=lambda s: s.confidence * s.urgency)
        
        return ExitSignal(
            action=best_signal.action,
            confidence=best_signal.confidence,
            reasoning=f"Best signal from {len(agent_signals)} agents: {best_signal.reasoning}",
            urgency=best_signal.urgency,
            suggested_price_cents=best_signal.suggested_price_cents,
        )
