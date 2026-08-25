"""
Exit Feedback Handler

Handles exit feedback to agents for learning and adaptation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)


class ExitReason(Enum):
    """
    Exit reason types - synchronized with position_management.exit_policy.ExitReason.
    
    NOTE: This is a legacy module - new code should use position_management.exit_policy.ExitReason
    as the single source of truth. This enum is kept for backward compatibility.
    """
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAIL = "trail"  # Changed from TRAILING_STOP to match unified enum
    TIME_STOP = "time_stop"
    EDGE_DECAY = "edge_decay"
    RISK = "risk"  # Changed from RISK_KILL_SWITCH to match unified enum
    STALE_DATA = "stale_data"
    MANUAL = "manual"
    SETTLEMENT_GUARD = "settlement_guard"


@dataclass
class ExitFeedback:
    """Feedback data for agents after exit."""
    position_id: str
    agent_id: str
    exit_reason: ExitReason
    exit_price_cents: int
    realized_pnl_cents: int
    hold_time_seconds: float
    entry_edge_pct: float
    exit_edge_pct: Optional[float] = None
    r_multiple_at_exit: float = 0.0
    timestamp: float = field(default_factory=time.time)


class AgentExitFeedbackHandler:
    """Handles exit feedback to agents."""
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize exit feedback handler.
        
        Args:
            max_history: Maximum number of feedback records to keep
        """
        self._agents: Dict[str, Any] = {}
        self._feedback_history: List[ExitFeedback] = []
        self._max_history = max_history
        logger.info("[EXIT-FEEDBACK-HANDLER] Initialized with max_history=%d", max_history)
    
    def register_agent(self, agent_id: str, agent: Any) -> None:
        """
        Register agent for exit feedback.
        
        Args:
            agent_id: Agent identifier
            agent: Agent instance
        """
        self._agents[agent_id] = agent
        logger.info("[EXIT-FEEDBACK-HANDLER] Registered agent=%s", agent_id)
    
    def unregister_agent(self, agent_id: str) -> None:
        """
        Unregister agent from exit feedback.
        
        Args:
            agent_id: Agent identifier
        """
        if agent_id in self._agents:
            del self._agents[agent_id]
            logger.info("[EXIT-FEEDBACK-HANDLER] Unregistered agent=%s", agent_id)
    
    def send_exit_feedback(self, feedback: ExitFeedback) -> None:
        """
        Send exit feedback to originating agent.
        
        Args:
            feedback: Exit feedback data
        """
        # Store feedback in history
        self._feedback_history.append(feedback)
        
        # Trim history if needed
        if len(self._feedback_history) > self._max_history:
            self._feedback_history = self._feedback_history[-self._max_history:]
        
        # Send feedback to agent
        agent = self._agents.get(feedback.agent_id)
        if agent and hasattr(agent, 'on_exit_feedback'):
            try:
                agent.on_exit_feedback(feedback)
                logger.debug(
                    "[EXIT-FEEDBACK-HANDLER] Sent feedback to agent=%s position=%s reason=%s pnl=%d",
                    feedback.agent_id,
                    feedback.position_id[:8],
                    feedback.exit_reason.value,
                    feedback.realized_pnl_cents
                )
            except Exception as e:
                logger.error(
                    "[EXIT-FEEDBACK-HANDLER] Failed to send feedback to agent=%s: %s",
                    feedback.agent_id,
                    e,
                    exc_info=True
                )
        else:
            logger.debug(
                "[EXIT-FEEDBACK-HANDLER] Agent=%s not registered or no feedback handler",
                feedback.agent_id
            )
    
    def get_feedback_history(self, agent_id: Optional[str] = None) -> List[ExitFeedback]:
        """
        Get feedback history.
        
        Args:
            agent_id: Optional agent ID to filter by
        
        Returns:
            List of feedback records
        """
        if agent_id:
            return [f for f in self._feedback_history if f.agent_id == agent_id]
        return self._feedback_history.copy()
    
    def get_agent_performance(self, agent_id: str) -> Dict[str, Any]:
        """
        Get performance metrics for an agent.
        
        Args:
            agent_id: Agent identifier
        
        Returns:
            Dictionary with performance metrics
        """
        agent_feedback = self.get_feedback_history(agent_id)
        
        if not agent_feedback:
            return {
                "agent_id": agent_id,
                "total_exits": 0,
                "total_pnl_cents": 0,
                "avg_pnl_cents": 0.0,
                "win_rate": 0.0,
                "avg_hold_time_seconds": 0.0,
            }
        
        total_pnl = sum(f.realized_pnl_cents for f in agent_feedback)
        wins = sum(1 for f in agent_feedback if f.realized_pnl_cents > 0)
        total_hold_time = sum(f.hold_time_seconds for f in agent_feedback)
        
        return {
            "agent_id": agent_id,
            "total_exits": len(agent_feedback),
            "total_pnl_cents": total_pnl,
            "avg_pnl_cents": total_pnl / len(agent_feedback),
            "win_rate": wins / len(agent_feedback),
            "avg_hold_time_seconds": total_hold_time / len(agent_feedback),
        }
    
    def get_exit_reason_distribution(self, agent_id: Optional[str] = None) -> Dict[str, int]:
        """
        Get distribution of exit reasons.
        
        Args:
            agent_id: Optional agent ID to filter by
        
        Returns:
            Dictionary mapping exit reasons to counts
        """
        feedback = self.get_feedback_history(agent_id)
        distribution = {}
        
        for f in feedback:
            reason = f.exit_reason.value
            distribution[reason] = distribution.get(reason, 0) + 1
        
        return distribution
