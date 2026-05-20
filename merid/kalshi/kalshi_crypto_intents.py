# merid/kalshi/kalshi_crypto_intents.py
"""Kalshi crypto intent builders for swarm integration."""

import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("merid.kalshi.kalshi_crypto_intents")


@dataclass
class KalshiCryptoOpinion:
    """Opinion from a Kalshi crypto agent."""
    agent_id: str
    market_id: str
    side: str  # "yes" or "no"
    size_pct: float
    edge_estimate: float
    confidence: float
    metadata: Optional[Dict[str, Any]] = None


def build_kalshi_crypto_intent(opinion: KalshiCryptoOpinion) -> Dict[str, Any]:
    """
    Build a standardized intent for Kalshi crypto trades.
    
    This intent shape is what the swarm orchestrator will inspect
    when we give it real teeth later.
    """
    # BUG-FIX: timestamp was assigned logger.info() return value (None)
    intent_timestamp = time.time()
    logger.info(f"Built crypto intent for {opinion.agent_id}")
    return {
        "venue": "kalshi",
        "lane": "crypto",
        "agent_id": opinion.agent_id,
        "market_id": opinion.market_id,
        "direction": opinion.side,
        "size_pct": opinion.size_pct,
        "edge_estimate": opinion.edge_estimate,
        "confidence": opinion.confidence,
        "metadata": opinion.metadata or {},
        "intent_type": "kalshi_crypto_trade",
        "timestamp": intent_timestamp  # BUG-FIX: Use actual timestamp
    }


async def maybe_execute_kalshi_opinion(opinion: KalshiCryptoOpinion) -> bool:
    """
    Execute a Kalshi crypto opinion through the swarm orchestrator.
    
    Returns True if the opinion was approved and should proceed to order creation.
    Returns False if the opinion was rejected by the swarm.
    """
    try:
        from merid.swarm.orchestrator import get_swarm_orchestrator
        
        orchestrator = get_swarm_orchestrator()
        intent = build_kalshi_crypto_intent(opinion)
        
        logger.debug(f"Submitting crypto opinion to swarm: {opinion.agent_id}")
        review = await orchestrator.review_intent(intent)
        
        if review.get("approved", True):
            logger.debug(f"Swarm approved crypto opinion: {opinion.agent_id}")
            return True
        else:
            reason = review.get("reason", "unknown")
            logger.info(f"Swarm rejected crypto opinion {opinion.agent_id}: {reason}")
            return False
            
    except Exception as exc:
        logger.warning(f"Swarm orchestrator error for crypto opinion {opinion.agent_id}: {exc}")
        # Fail open - allow the opinion to proceed if swarm is unavailable
        return True


def record_swarm_blocked_opinion(opinion: KalshiCryptoOpinion, reason: str) -> None:
    """
    Record a swarm-blocked opinion in the performance tracker.
    
    This helps with analytics and debugging of swarm behavior.
    """
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        
        tracker = get_agent_performance_tracker()
        
        # Create a blocked signal record
        blocked_signal = {
            "agent_id": opinion.agent_id,
            "market_id": opinion.market_id,
            "timestamp": time.time(),
            "blocked_reason": "swarm_guard",
            "predicted_edge": opinion.edge_estimate,
            "confidence": opinion.confidence,
            "metadata": {
                "swarm_reason": reason,
                "side": opinion.side,
                "size_pct": opinion.size_pct
            }
        }
        
        logger.info(f"Recorded swarm-blocked opinion: {opinion.agent_id} - {reason}")
        
    except Exception as exc:
        logger.error(f"Failed to record swarm-blocked opinion: {exc}")
