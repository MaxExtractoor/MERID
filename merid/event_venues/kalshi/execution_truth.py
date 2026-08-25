"""Single Source of Execution Truth

Defines the canonical source of truth for execution state:
- System state = f(ledger, REST snapshot)

REST = truth for snapshot (current positions)
Ledger = truth for history (fills, order lifecycle)
Cache = derived state (computed from ledger + REST)

This ensures all components converge to the same execution truth.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExecutionTruth:
    """Canonical execution state derived from ledger and REST snapshot."""
    timestamp: datetime
    ledger_fill_count: int
    rest_position_count: int
    derived_position_count: int
    cache_position_count: int
    is_consistent: bool
    divergences: List[str]


class ExecutionTruthManager:
    """
    Single source of execution truth.
    
    Truth definition:
    - REST API = truth for snapshot (current positions)
    - Fills ledger = truth for history (fills, order lifecycle)
    - Position cache = derived state (computed from ledger + REST)
    
    System state = f(ledger, REST snapshot)
    Everything else is derivable from these two sources.
    """
    
    _instance: Optional["ExecutionTruthManager"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "ExecutionTruthManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "ExecutionTruthManager":
        """Get singleton instance."""
        if not cls._initialized:
            cls._instance = cls()
            cls._initialized = True
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        logger.info("[EXECUTION-TRUTH] Initialized with REST=snapshot, Ledger=history, Cache=derived")
    
    async def compute_execution_truth(self) -> ExecutionTruth:
        """
        Compute the canonical execution truth from ledger and REST snapshot.
        
        Returns:
            ExecutionTruth with current state and consistency check
        """
        divergences = []
        
        try:
            # Get fills ledger state
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            ledger_fill_count = len(ledger._fills)
            
            # Get REST position state
            from merid.event_venues.kalshi.kalshi_rest_client import get_kalshi_rest_client
            rest_client = await get_kalshi_rest_client()
            positions_result = await rest_client.get_positions_with_filters({})
            
            rest_position_count = 0
            if positions_result.success:
                positions = positions_result.data or {}
                raw_positions = positions.get("market_positions") or positions.get("positions") or []
                rest_position_count = len([p for p in raw_positions if p.get("contracts", 0) > 0])
            
            # Get derived position state from ledger
            derived_positions = ledger.compute_net_positions(since_hours=24)
            derived_position_count = len(derived_positions)
            
            # Get cache position state
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            cache_positions = [p for p in cache._positions.values() if p.contracts > 0]
            cache_position_count = len(cache_positions)
            
            # Check consistency
            is_consistent = True
            
            # REST vs derived should match (within tolerance)
            if rest_position_count != derived_position_count:
                divergences.append(
                    f"REST position count ({rest_position_count}) != derived position count ({derived_position_count})"
                )
                is_consistent = False
            
            # Cache should match REST
            if cache_position_count != rest_position_count:
                divergences.append(
                    f"Cache position count ({cache_position_count}) != REST position count ({rest_position_count})"
                )
                is_consistent = False
            
            truth = ExecutionTruth(
                timestamp=datetime.now(timezone.utc),
                ledger_fill_count=ledger_fill_count,
                rest_position_count=rest_position_count,
                derived_position_count=derived_position_count,
                cache_position_count=cache_position_count,
                is_consistent=is_consistent,
                divergences=divergences
            )
            
            if not is_consistent:
                logger.warning(
                    "[EXECUTION-TRUTH] Execution state inconsistent: %s",
                    "; ".join(divergences)
                )
            else:
                logger.info(
                    "[EXECUTION-TRUTH] Execution state consistent: %d fills, %d positions",
                    ledger_fill_count, rest_position_count
                )
            
            return truth
            
        except Exception as e:
            logger.error("[EXECUTION-TRUTH] Failed to compute execution truth: %s", e, exc_info=True)
            # Return degraded truth
            return ExecutionTruth(
                timestamp=datetime.now(timezone.utc),
                ledger_fill_count=0,
                rest_position_count=0,
                derived_position_count=0,
                cache_position_count=0,
                is_consistent=False,
                divergences=[f"Failed to compute truth: {str(e)}"]
            )
    
    async def force_convergence(self) -> bool:
        """
        Force convergence of all sources to canonical truth.
        
        This is a recovery action when divergence is detected.
        
        Returns:
            True if convergence successful, False otherwise
        """
        logger.info("[EXECUTION-TRUTH] Forcing convergence to canonical truth")
        
        try:
            # 1. Rebuild position cache from fills ledger (canonical history)
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            await cache._rebuild_from_fills_ledger()
            
            # 2. Sync from REST to get latest snapshot
            from merid.event_venues.kalshi.kalshi_rest_client import get_kalshi_rest_client
            rest_client = await get_kalshi_rest_client()
            positions_result = await rest_client.get_positions_with_filters({})
            
            if positions_result.success:
                positions = positions_result.data or {}
                raw_positions = positions.get("market_positions") or positions.get("positions") or []
                await cache.sync_from_rest(raw_positions, force=True)
            
            # 3. Verify convergence
            truth = await self.compute_execution_truth()
            
            if truth.is_consistent:
                logger.info("[EXECUTION-TRUTH] Convergence successful")
                return True
            else:
                logger.error(
                    "[EXECUTION-TRUTH] Convergence failed: %s",
                    "; ".join(truth.divergences)
                )
                return False
                
        except Exception as e:
            logger.error("[EXECUTION-TRUTH] Convergence failed with error: %s", e, exc_info=True)
            return False


def get_execution_truth_manager() -> ExecutionTruthManager:
    """Get singleton instance of ExecutionTruthManager."""
    return ExecutionTruthManager.get_instance()
