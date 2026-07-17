"""
Centralized exit resolver for merging position-level and policy-level exit decisions.

Provides single source of truth for exit precedence across the entire system.
"""

import logging
from typing import Optional, List
from merid.position_management.exit_decision import ExitDecision, ExitPriority, ExitSourceLayer

logger = logging.getLogger(__name__)


class ExitResolver:
    """
    Centralized exit resolver that merges multiple exit decisions.
    
    Takes ExitDecision objects from both position-level (extreme profit, ratchets, TP/SL)
    and policy-layer (risk, stale data, timing, edge) sources and resolves to a single
    decision based on priority.
    """
    
    def __init__(self):
        """Initialize exit resolver."""
        self._decision_history: List[dict] = []
    
    def resolve(
        self,
        decisions: List[ExitDecision],
        position_id: Optional[str] = None
    ) -> Optional[ExitDecision]:
        """
        Resolve multiple exit decisions to a single decision based on priority.
        
        Args:
            decisions: List of ExitDecision objects from various sources
            position_id: Position ID for logging (optional)
            
        Returns:
            Highest priority ExitDecision, or None if no decisions
        """
        if not decisions:
            return None
        
        # Sort by priority (highest first)
        sorted_decisions = sorted(decisions, key=lambda d: d.priority.value, reverse=True)
        
        # Get highest priority decision
        winning_decision = sorted_decisions[0]
        
        # Log resolution for debugging
        self._log_resolution(sorted_decisions, winning_decision, position_id)
        
        # Record decision history
        self._record_decision(sorted_decisions, winning_decision, position_id)
        
        return winning_decision
    
    def _log_resolution(
        self,
        all_decisions: List[ExitDecision],
        winning_decision: ExitDecision,
        position_id: Optional[str]
    ) -> None:
        """
        Log exit decision resolution for debugging.
        
        Args:
            all_decisions: All decisions considered
            winning_decision: The winning decision
            position_id: Position ID for logging
        """
        pos_str = position_id[:8] if position_id else "unknown"
        
        if len(all_decisions) == 1:
            logger.info(
                "[EXIT-RESOLVER] position=%s single_decision reason=%s priority=%d source=%s",
                pos_str,
                winning_decision.reason.value,
                winning_decision.priority.value,
                winning_decision.source_layer.value
            )
        else:
            # Log all decisions for debugging
            decisions_str = ", ".join([
                f"{d.reason.value}(prio={d.priority.value},src={d.source_layer.value})"
                for d in all_decisions
            ])
            
            logger.info(
                "[EXIT-RESOLVER] position=%s resolved reason=%s priority=%d source=%s "
                "from [%s]",
                pos_str,
                winning_decision.reason.value,
                winning_decision.priority.value,
                winning_decision.source_layer.value,
                decisions_str
            )
        
        # Log metadata for STALE_DATA decisions (important for debugging)
        if winning_decision.reason.value == "stale_data":
            md_age_ms = winning_decision.metadata.get("md_age_ms")
            max_age_ms = winning_decision.metadata.get("max_age_ms")
            time_to_expiry = winning_decision.metadata.get("time_to_expiry_seconds")
            
            logger.warning(
                "[EXIT-RESOLVER] STALE_DATA exit: position=%s md_age_ms=%s max_age_ms=%s "
                "time_to_expiry=%s metadata=%s",
                pos_str,
                md_age_ms,
                max_age_ms,
                time_to_expiry,
                winning_decision.metadata
            )
    
    def _record_decision(
        self,
        all_decisions: List[ExitDecision],
        winning_decision: ExitDecision,
        position_id: Optional[str]
    ) -> None:
        """
        Record decision history for analysis.
        
        Args:
            all_decisions: All decisions considered
            winning_decision: The winning decision
            position_id: Position ID
        """
        record = {
            "position_id": position_id,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "all_decisions": [
                {
                    "reason": d.reason.value,
                    "priority": d.priority.value,
                    "source_layer": d.source_layer.value,
                    "metadata": d.metadata
                }
                for d in all_decisions
            ],
            "winning_decision": {
                "reason": winning_decision.reason.value,
                "priority": winning_decision.priority.value,
                "source_layer": winning_decision.source_layer.value,
                "metadata": winning_decision.metadata
            }
        }
        
        self._decision_history.append(record)
        
        # Keep history manageable (last 1000 decisions)
        if len(self._decision_history) > 1000:
            self._decision_history = self._decision_history[-1000:]
    
    def get_decision_history(self, position_id: Optional[str] = None) -> List[dict]:
        """
        Get decision history for analysis.
        
        Args:
            position_id: Filter by position ID (optional)
            
        Returns:
            List of decision records
        """
        if position_id:
            return [r for r in self._decision_history if r.get("position_id") == position_id]
        return self._decision_history.copy()
    
    def clear_history(self) -> None:
        """Clear decision history."""
        self._decision_history = []
        logger.info("[EXIT-RESOLVER] Decision history cleared")


# Global singleton instance
_resolver_instance: Optional[ExitResolver] = None


def get_exit_resolver() -> ExitResolver:
    """
    Get global exit resolver singleton.
    
    Returns:
        ExitResolver instance
    """
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = ExitResolver()
        logger.info("[EXIT-RESOLVER] Created global singleton")
    return _resolver_instance
