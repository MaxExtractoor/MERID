"""
Stage 4: UMA oracle integration helper methods for simulation engine.
Provides _propose_uma_assertion and related methods for MeridSimulationChain.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any

from utils.logger import get_logger

logger = get_logger("simulation.uma_integration")


def propose_uma_assertion(
    market_slug: str,
    consensus_probability: float,
    block_index: int,
    confidence: float,
) -> Optional[str]:
    """
    Propose consensus probability to UMA Optimistic Oracle.
    
    Args:
        market_slug: Market identifier
        consensus_probability: Swarm consensus probability (0-1)
        block_index: MERID block index
        confidence: Consensus confidence score
    
    Returns:
        UMA assertion ID if successful, None otherwise
    """
    from oracles.uma import get_uma_client
    
    # Only propose if confidence is high enough
    if confidence < 0.8:
        logger.debug(
            "Skipping UMA assertion for %s: confidence %.3f below threshold",
            market_slug,
            confidence,
        )
        return None
    
    uma_client = get_uma_client()
    
    # Generate unique assertion ID
    assertion_id = f"merid_block_{block_index}_{market_slug}_{int(time.time())}"
    
    # Propose to UMA oracle
    result = uma_client.propose_price(
        assertion_id=assertion_id,
        proposed_price=consensus_probability,
        bond=100.0,  # 100 UMA bond
        currency="UMA",
        block_index=block_index,
        claim=f"MERID swarm consensus for {market_slug}: {consensus_probability:.4f}",
    )
    
    if result.get("status") == "success":
        logger.info(
            "UMA assertion proposed: %s for market %s (probability=%.4f, confidence=%.3f)",
            assertion_id,
            market_slug,
            consensus_probability,
            confidence,
        )
        return assertion_id
    else:
        logger.error(
            "UMA assertion proposal failed for %s: %s",
            market_slug,
            result.get("detail"),
        )
        return None


def get_uma_assertions_for_block(block_index: int) -> Dict[str, Any]:
    """Get all UMA assertions associated with a block."""
    from oracles.uma import get_uma_client
    
    uma_client = get_uma_client()
    assertions = uma_client.get_assertions_for_block(block_index)
    
    return {
        "block_index": block_index,
        "assertions": [a.to_dict() for a in assertions],
        "count": len(assertions),
    }
