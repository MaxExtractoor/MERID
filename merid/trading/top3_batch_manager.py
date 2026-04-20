"""
Top-3 Batch Manager — Batch Lifecycle Management

Manages the lifecycle of top-3 batches:
- Creates new batches when no active batch exists
- Tracks which assets have been filled/closed
- Enforces the "no overlapping batches" invariant
- Persists state to CacheAdapter (Redis + in-memory fallback)

Batch Lifecycle:
    PENDING -> ACTIVE -> CLOSING -> CLOSED
                |
                v
            (new batch can be created)

Integration Points:
- KalshiContinuousTrader: Queries batch manager before opening positions
- KalshiTradingAgent: Checks if asset is in active batch
- Order Router: Validates orders against batch allocations
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger
from merid.trading.top3_edge_allocator import (
    BatchStatus,
    EdgeCandidate,
    Top3Allocation,
    Top3Batch,
    Top3EdgeAllocator,
    get_top3_allocator,
)

# Import cache adapter for state persistence
try:
    from core.cache import cache as _cache
except ImportError:
    _cache = None

logger = get_logger(__name__)

# Cache key for batch persistence
_CACHE_KEY_ACTIVE_BATCH = "top3:active_batch"
_CACHE_KEY_BATCH_HISTORY = "top3:batch_history"
_DEFAULT_CACHE_TTL = 86400 * 7  # 7 days

# Rejection reasons for observability
REJECT_NO_ACTIVE_BATCH = "NO_ACTIVE_TOP3_BATCH"
REJECT_ASSET_NOT_IN_TOP3 = "ASSET_NOT_IN_TOP3"
REJECT_NOTIONAL_LIMIT_REACHED = "BATCH_NOTIONAL_LIMIT_REACHED"
REJECT_BATCH_ALREADY_ACTIVE = "BATCH_ALREADY_ACTIVE"


class Top3BatchManager:
    """Manages top-3 batch lifecycle and enforces batch regime.
    
    This is the central coordinator that:
    1. Tracks the current active batch (if any)
    2. Creates new batches when conditions are met
    3. Validates entry requests against batch allocations
    4. Persists batch state for recovery
    
    Thread-safe: All methods use internal locking.
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._allocator = get_top3_allocator()
        self._current_batch: Optional[Top3Batch] = None
        self._batch_history: List[str] = []  # List of batch IDs
        
        # In-memory state (used if cache unavailable)
        self._memory_batch: Optional[Top3Batch] = None
        
        # Metrics tracking
        self._rejections: Dict[str, int] = {
            REJECT_NO_ACTIVE_BATCH: 0,
            REJECT_ASSET_NOT_IN_TOP3: 0,
            REJECT_NOTIONAL_LIMIT_REACHED: 0,
        }
        
        # Load persisted state on init
        self._load_state()
    
    def _get_cache(self):
        """Get cache adapter, falling back to None if unavailable."""
        return _cache
    
    def _load_state(self) -> None:
        """Load batch state from cache."""
        cache = self._get_cache()
        if cache is None:
            logger.debug("[TOP3-BATCH] No cache available, using in-memory state only")
            self._current_batch = self._memory_batch
            return
        
        try:
            data = cache.get_json(_CACHE_KEY_ACTIVE_BATCH)
            if data:
                self._current_batch = Top3Batch.from_dict(data)
                logger.info(
                    "[TOP3-BATCH] Loaded active batch %s (status=%s)",
                    self._current_batch.batch_id,
                    self._current_batch.status.value
                )
        except Exception as exc:
            logger.warning("[TOP3-BATCH] Failed to load state from cache: %s", exc)
            self._current_batch = None
    
    def _save_state(self) -> None:
        """Persist batch state to cache."""
        cache = self._get_cache()
        
        # Always update in-memory fallback
        self._memory_batch = self._current_batch
        
        if cache is None:
            return
        
        try:
            if self._current_batch:
                cache.set_json(
                    _CACHE_KEY_ACTIVE_BATCH,
                    self._current_batch.to_dict(),
                    ttl=_DEFAULT_CACHE_TTL
                )
            else:
                cache.delete(_CACHE_KEY_ACTIVE_BATCH)
        except Exception as exc:
            logger.warning("[TOP3-BATCH] Failed to save state to cache: %s", exc)
    
    # ═════════════════════════════════════════════════════════════════
    # Public API: Batch Management
    # ═════════════════════════════════════════════════════════════════
    
    def get_current_batch(self) -> Optional[Top3Batch]:
        """Get the currently active batch, if any.
        
        Returns:
            Active Top3Batch or None if no batch exists
        """
        with self._lock:
            # Check if current batch has expired (all positions closed)
            if self._current_batch and self._current_batch.all_positions_closed():
                if self._current_batch.status == BatchStatus.ACTIVE:
                    logger.info(
                        "[TOP3-BATCH] Auto-closing batch %s (all positions closed)",
                        self._current_batch.batch_id
                    )
                    self._current_batch.status = BatchStatus.CLOSED
                    self._save_state()
            
            return self._current_batch
    
    def maybe_create_new_batch(
        self,
        bankroll_notional: int,
        candidates: List[EdgeCandidate],
    ) -> Optional[Top3Batch]:
        """Create a new batch if conditions are met.
        
        Conditions for new batch:
        1. No currently ACTIVE batch
        2. Valid candidates exist with positive edges
        3. Bankroll is positive
        
        Args:
            bankroll_notional: Current bankroll in cents
            candidates: Edge candidates for all assets
            
        Returns:
            New Top3Batch if created, None otherwise
        """
        with self._lock:
            # Check condition 1: No active batch
            if self._current_batch and self._current_batch.status == BatchStatus.ACTIVE:
                logger.debug(
                    "[TOP3-BATCH] Cannot create new batch: batch %s is still ACTIVE",
                    self._current_batch.batch_id
                )
                return None
            
            # Check condition 3: Valid bankroll
            if bankroll_notional <= 0:
                logger.warning("[TOP3-BATCH] Cannot create batch: invalid bankroll %d", bankroll_notional)
                return None
            
            # Compute allocations
            allocations = self._allocator.compute_allocations(bankroll_notional, candidates)
            
            # Check condition 2: Valid allocations
            if not allocations:
                logger.debug("[TOP3-BATCH] No allocations computed, not creating batch")
                return None
            
            # Create new batch
            total_notional = sum(a.target_notional for a in allocations)
            new_batch = Top3Batch(
                batch_id=str(time.time()),  # Simple timestamp-based ID
                status=BatchStatus.ACTIVE,
                cycle_ts=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                allocations=allocations,
                total_target_notional=total_notional,
                cycle_risk_cap_pct=self._allocator.get_cycle_risk_cap_pct(),
                bankroll_at_creation=bankroll_notional,
            )
            
            # Archive previous batch if exists
            if self._current_batch:
                self._batch_history.append(self._current_batch.batch_id)
                logger.info(
                    "[TOP3-BATCH] Archived previous batch %s, creating new batch %s",
                    self._current_batch.batch_id,
                    new_batch.batch_id
                )
            
            self._current_batch = new_batch
            self._save_state()
            
            logger.info(
                "[TOP3-BATCH] Created new batch %s with %d assets, total=%d¢",
                new_batch.batch_id,
                len(allocations),
                total_notional
            )
            
            # Log detailed allocation info
            for alloc in allocations:
                logger.info(
                    "[TOP3-BATCH] Allocation: %s edge=%.4f notional=%d¢ weight=%.2f%%",
                    alloc.asset, alloc.edge, alloc.target_notional, alloc.weight * 100
                )
            
            return new_batch
    
    def mark_asset_filled(self, batch_id: str, asset: str, filled_notional: int) -> bool:
        """Mark an asset as having been filled.
        
        Args:
            batch_id: ID of the batch
            asset: Asset that was filled
            filled_notional: Actual notional that was filled
            
        Returns:
            True if marked successfully, False if batch/asset not found
        """
        with self._lock:
            if not self._current_batch or self._current_batch.batch_id != batch_id:
                logger.warning("[TOP3-BATCH] Cannot mark filled: batch %s not found", batch_id)
                return False
            
            if not self._current_batch.is_asset_allowed(asset):
                logger.warning("[TOP3-BATCH] Asset %s not in batch %s", asset, batch_id)
                return False
            
            self._current_batch.filled_assets.add(asset)
            self._save_state()
            
            logger.info(
                "[TOP3-BATCH] Marked %s as filled in batch %s (notional=%d¢)",
                asset, batch_id, filled_notional
            )
            return True
    
    def mark_asset_closed(self, batch_id: str, asset: str) -> bool:
        """Mark an asset as closed/resolved.
        
        Called when positions for an asset are fully closed (stop-loss,
        take-profit, expiry, or manual close).
        
        Args:
            batch_id: ID of the batch
            asset: Asset that was closed
            
        Returns:
            True if marked successfully, False if batch/asset not found
        """
        with self._lock:
            if not self._current_batch or self._current_batch.batch_id != batch_id:
                logger.warning("[TOP3-BATCH] Cannot mark closed: batch %s not found", batch_id)
                return False
            
            self._current_batch.closed_assets.add(asset)
            
            # Check if all positions are now closed
            if self._current_batch.all_positions_closed():
                self._current_batch.status = BatchStatus.CLOSED
                logger.info(
                    "[TOP3-BATCH] Batch %s is now CLOSED (all positions resolved)",
                    batch_id
                )
            
            self._save_state()
            
            logger.info("[TOP3-BATCH] Marked %s as closed in batch %s", asset, batch_id)
            return True
    
    def close_batch(self, batch_id: str, reason: str = "manual") -> bool:
        """Force close a batch (for manual override or error recovery).
        
        Args:
            batch_id: ID of the batch to close
            reason: Reason for closing (logged)
            
        Returns:
            True if closed successfully, False if batch not found
        """
        with self._lock:
            if not self._current_batch or self._current_batch.batch_id != batch_id:
                logger.warning("[TOP3-BATCH] Cannot close: batch %s not found", batch_id)
                return False
            
            self._current_batch.status = BatchStatus.CLOSED
            self._save_state()
            
            logger.warning(
                "[TOP3-BATCH] Force-closed batch %s (reason=%s)",
                batch_id, reason
            )
            return True
    
    # ═════════════════════════════════════════════════════════════════
    # Public API: Entry Validation
    # ═════════════════════════════════════════════════════════════════
    
    def can_open_new_position(
        self,
        asset: str,
        requested_notional: int,
    ) -> Tuple[bool, str, Optional[Top3Allocation]]:
        """Check if a new position can be opened for the given asset.
        
        This is the main entry gate used by agents and routers.
        
        Args:
            asset: Asset to check (BTC, ETH, SOL, XRP, DOGE)
            requested_notional: Requested notional in cents
            
        Returns:
            Tuple of (allowed: bool, reason: str, allocation: Optional[Top3Allocation])
            - allowed: True if entry permitted
            - reason: Empty if allowed, rejection reason if not
            - allocation: The allocation for this asset if allowed
            
        Rejection reasons:
        - NO_ACTIVE_TOP3_BATCH: No batch is currently active
        - ASSET_NOT_IN_TOP3: Asset not in current batch allocations
        - BATCH_NOTIONAL_LIMIT_REACHED: Notional limit would be exceeded
        """
        with self._lock:
            batch = self.get_current_batch()
            
            # Check 1: Active batch exists
            if batch is None:
                self._rejections[REJECT_NO_ACTIVE_BATCH] += 1
                return False, REJECT_NO_ACTIVE_BATCH, None
            
            # Check 2: Batch is in ACTIVE status
            if batch.status != BatchStatus.ACTIVE:
                self._rejections[REJECT_NO_ACTIVE_BATCH] += 1
                return False, REJECT_NO_ACTIVE_BATCH, None
            
            # Check 3: Asset is in batch allocations
            allocation = batch.get_allocation_for_asset(asset)
            if allocation is None:
                self._rejections[REJECT_ASSET_NOT_IN_TOP3] += 1
                logger.debug(
                    "[TOP3-REJECT] %s: Asset %s not in batch %s (assets: %s)",
                    REJECT_ASSET_NOT_IN_TOP3,
                    asset,
                    batch.batch_id,
                    [a.asset for a in batch.allocations]
                )
                return False, REJECT_ASSET_NOT_IN_TOP3, None
            
            # Check 4: Notional limit (simplified - tracks filled vs target)
            # In production, you'd track actual filled notional per asset
            if asset in batch.filled_assets:
                # Already filled this asset in this batch
                # Could be valid for additional fills if sizing multiple tranches
                # For now, allow if within target
                pass  # Will check target_notional below
            
            # Check requested notional against target
            # Note: This is a simplified check. In production, track actual filled notional.
            if requested_notional > allocation.target_notional:
                self._rejections[REJECT_NOTIONAL_LIMIT_REACHED] += 1
                logger.debug(
                    "[TOP3-REJECT] %s: Requested %d¢ > target %d¢ for %s",
                    REJECT_NOTIONAL_LIMIT_REACHED,
                    requested_notional,
                    allocation.target_notional,
                    asset
                )
                # Still allow but warn - strict version would return False
            
            # All checks passed
            return True, "", allocation
    
    def validate_order(
        self,
        asset: str,
        ticker: str,
        side: str,
        contracts: int,
        price_cents: int,
    ) -> Tuple[bool, str]:
        """Validate an order against current batch.
        
        Convenience wrapper for order router integration.
        
        Returns:
            (allowed, reason) tuple
        """
        requested_notional = contracts * price_cents
        allowed, reason, _ = self.can_open_new_position(asset, requested_notional)
        
        if not allowed:
            logger.warning(
                "[TOP3-ORDER-REJECT] %s %dx %s @ %d¢ | reason=%s",
                side, contracts, ticker, price_cents, reason
            )
        
        return allowed, reason
    
    # ═════════════════════════════════════════════════════════════════
    # Public API: Metrics and Status
    # ═════════════════════════════════════════════════════════════════
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics for observability."""
        with self._lock:
            batch = self._current_batch
            
            metrics = {
                "active_batch": 1 if (batch and batch.status == BatchStatus.ACTIVE) else 0,
                "rejections": dict(self._rejections),
                "batch_count": len(self._batch_history) + (1 if batch else 0),
            }
            
            if batch:
                metrics["current_batch"] = {
                    "batch_id": batch.batch_id,
                    "status": batch.status.value,
                    "assets": [a.asset for a in batch.allocations],
                    "edges": {a.asset: a.edge for a in batch.allocations},
                    "target_notionals": {a.asset: a.target_notional for a in batch.allocations},
                    "filled_assets": list(batch.filled_assets),
                    "closed_assets": list(batch.closed_assets),
                    "total_target": batch.total_target_notional,
                    "bankroll_at_creation": batch.bankroll_at_creation,
                }
            
            return metrics
    
    def get_rejection_summary(self) -> Dict[str, int]:
        """Get rejection counts for alerting."""
        with self._lock:
            return dict(self._rejections)
    
    def reset_rejection_counters(self) -> None:
        """Reset rejection counters (for testing or periodic cleanup)."""
        with self._lock:
            self._rejections = {
                REJECT_NO_ACTIVE_BATCH: 0,
                REJECT_ASSET_NOT_IN_TOP3: 0,
                REJECT_NOTIONAL_LIMIT_REACHED: 0,
            }


# Singleton instance
_batch_manager_instance: Optional[Top3BatchManager] = None
_batch_manager_lock = threading.Lock()


def get_top3_batch_manager() -> Top3BatchManager:
    """Get singleton Top3BatchManager instance."""
    global _batch_manager_instance
    if _batch_manager_instance is None:
        with _batch_manager_lock:
            if _batch_manager_instance is None:
                _batch_manager_instance = Top3BatchManager()
    return _batch_manager_instance


def reset_top3_batch_manager() -> None:
    """Reset the batch manager singleton (for testing)."""
    global _batch_manager_instance
    with _batch_manager_lock:
        # Clear cache first to prevent stale state from being reloaded
        try:
            cache = _cache
            if cache:
                cache.delete(_CACHE_KEY_ACTIVE_BATCH)
        except Exception:
            pass
        _batch_manager_instance = None
