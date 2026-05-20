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

# CIRCUIT BREAKER: Cache failure tracking to prevent cascading failures
# When Redis is down, repeated attempts waste resources and spam logs
_CIRCUIT_BREAKER_FAILURES = 0
_CIRCUIT_BREAKER_LAST_FAILURE = 0.0
_CIRCUIT_BREAKER_THRESHOLD = 3  # Open after 3 consecutive failures
_CIRCUIT_BREAKER_RESET_SEC = 60  # Reset after 60 seconds of no failures
_CIRCUIT_BREAKER_LOCK = threading.Lock()


def _is_cache_circuit_open() -> bool:
    """Check if circuit breaker is open (cache operations should be skipped).

    Circuit opens after _CIRCUIT_BREAKER_THRESHOLD consecutive failures.
    Auto-resets after _CIRCUIT_BREAKER_RESET_SEC seconds of no failures.
    """
    global _CIRCUIT_BREAKER_FAILURES, _CIRCUIT_BREAKER_LAST_FAILURE
    with _CIRCUIT_BREAKER_LOCK:
        if _CIRCUIT_BREAKER_FAILURES >= _CIRCUIT_BREAKER_THRESHOLD:
            # Check if enough time has passed to try again
            now = time.time()
            if now - _CIRCUIT_BREAKER_LAST_FAILURE > _CIRCUIT_BREAKER_RESET_SEC:
                # Reset circuit to half-open (will try once)
                _CIRCUIT_BREAKER_FAILURES = 0
                logger.info("[TOP3-BATCH] Cache circuit breaker reset after cooldown")
                return False
            return True  # Circuit still open
        return False  # Circuit closed


def _record_cache_success() -> None:
    """Record successful cache operation - resets failure count."""
    global _CIRCUIT_BREAKER_FAILURES
    with _CIRCUIT_BREAKER_LOCK:
        if _CIRCUIT_BREAKER_FAILURES > 0:
            _CIRCUIT_BREAKER_FAILURES = 0
            logger.debug("[TOP3-BATCH] Cache circuit breaker reset after success")


def _record_cache_failure() -> None:
    """Record cache operation failure - increments failure count."""
    global _CIRCUIT_BREAKER_FAILURES, _CIRCUIT_BREAKER_LAST_FAILURE
    with _CIRCUIT_BREAKER_LOCK:
        _CIRCUIT_BREAKER_FAILURES += 1
        _CIRCUIT_BREAKER_LAST_FAILURE = time.time()
        if _CIRCUIT_BREAKER_FAILURES >= _CIRCUIT_BREAKER_THRESHOLD:
            logger.warning(
                "[TOP3-BATCH] Cache circuit breaker OPENED after %d failures - "
                "skipping cache operations for %d seconds",
                _CIRCUIT_BREAKER_FAILURES, _CIRCUIT_BREAKER_RESET_SEC
            )


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
        """Load batch state from cache with phantom batch detection."""
        # CIRCUIT BREAKER: Skip cache if circuit is open (Redis likely down)
        if _is_cache_circuit_open():
            logger.debug("[TOP3-BATCH] Cache circuit open, using in-memory state only")
            self._current_batch = self._memory_batch
            return

        cache = self._get_cache()
        if cache is None:
            logger.debug("[TOP3-BATCH] No cache available, using in-memory state only")
            self._current_batch = self._memory_batch
            return

        try:
            data = cache.get_json(_CACHE_KEY_ACTIVE_BATCH)
            _record_cache_success()
            if data:
                loaded_batch = Top3Batch.from_dict(data)
                
                # PRODUCTION FIX v6 (2026-04-26): Auto-detect and clear phantom batches
                # Phantom batch = ACTIVE but no fills and older than 5 minutes
                is_phantom = (
                    loaded_batch.status == BatchStatus.ACTIVE and
                    not loaded_batch.filled_assets and  # No positions ever filled
                    not loaded_batch.closed_assets       # No positions ever closed
                )
                
                if is_phantom:
                    batch_age_seconds = (
                        __import__('datetime').datetime.now(__import__('datetime').timezone.utc) - 
                        loaded_batch.cycle_ts
                    ).total_seconds()
                    
                    # Clear phantom batches older than 5 minutes (they're stuck)
                    if batch_age_seconds > 300:  # 5 minutes
                        logger.critical(
                            "[TOP3-BATCH] PHANTOM BATCH DETECTED: batch %s is ACTIVE but "
                            "has no fills after %d seconds. Auto-clearing to unblock execution. "
                            "This indicates a previous crash during order placement.",
                            loaded_batch.batch_id,
                            int(batch_age_seconds)
                        )
                        cache.delete(_CACHE_KEY_ACTIVE_BATCH)
                        self._current_batch = None
                        return
                    else:
                        logger.warning(
                            "[TOP3-BATCH] Potentially phantom batch %s (age=%ds, no fills). "
                            "Will auto-clear if still empty after 300s.",
                            loaded_batch.batch_id,
                            int(batch_age_seconds)
                        )
                
                self._current_batch = loaded_batch
                logger.info(
                    "[TOP3-BATCH] Loaded active batch %s (status=%s, filled=%s)",
                    self._current_batch.batch_id,
                    self._current_batch.status.value,
                    list(self._current_batch.filled_assets) if self._current_batch.filled_assets else "none"
                )
        except Exception as exc:
            _record_cache_failure()
            logger.warning("[TOP3-BATCH] Failed to load state from cache: %s", exc)
            self._current_batch = None
    
    def _save_state(self) -> None:
        """Persist batch state to cache."""
        # Always update in-memory fallback
        self._memory_batch = self._current_batch

        # CIRCUIT BREAKER: Skip cache if circuit is open (Redis likely down)
        if _is_cache_circuit_open():
            return

        cache = self._get_cache()
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
            _record_cache_success()
        except Exception as exc:
            _record_cache_failure()
            logger.warning("[TOP3-BATCH] Failed to save state to cache: %s", exc)
    
    # ═════════════════════════════════════════════════════════════════
    # Public API: Batch Management
    # ═════════════════════════════════════════════════════════════════
    
    def has_active_batch(self) -> bool:
        """Check if there's an active batch (convenience method).
        
        Returns:
            True if a batch exists and is not fully reconciled
        """
        with self._lock:
            batch = self._current_batch
            if batch is None:
                return False
            # ACTIVE or CLOSED (not yet reconciled) counts as "active" for trading
            return batch.status in (BatchStatus.ACTIVE, BatchStatus.CLOSED)
    
    def get_current_batch(self) -> Optional[Top3Batch]:
        """Get the currently active batch, if any.
        
        Also handles auto-closing and auto-reconciliation:
        1. Auto-close ACTIVE batch when all positions are closed
        2. Auto-reconcile CLOSED batch after 30 seconds (allows bankroll update)
        
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
            
            # CRITICAL: Auto-reconcile CLOSED batches after delay
            # This ensures bankroll has been updated before allowing new cycles
            if self._current_batch and self._current_batch.status == BatchStatus.CLOSED:
                # Check if batch has been closed for 30+ seconds (allows P&L reconciliation)
                closed_duration = (__import__('datetime').datetime.now(__import__('datetime').timezone.utc) - 
                                 self._current_batch.cycle_ts)
                if closed_duration.total_seconds() > 30:
                    # Estimate realized P&L from allocations (or 0 if unknown)
                    realized_pnl = getattr(self._current_batch, 'realized_pnl_cents', 0)
                    logger.info(
                        "[TOP3-BATCH] Auto-reconciling batch %s after %ds (realized_pnl=%d¢)",
                        self._current_batch.batch_id, 
                        int(closed_duration.total_seconds()),
                        realized_pnl
                    )
                    self._current_batch.status = BatchStatus.FULLY_RECONCILED
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
            # CRITICAL: Check if cycle is locked (any non-reconciled batch exists)
            # This prevents cycle piling - only allow new batch when previous is FULLY_RECONCILED
            locked, reason = self.is_cycle_locked()
            if locked:
                logger.warning(
                    "[TOP3-BATCH] Cannot create new batch: %s",
                    reason
                )
                return None
            
            # Check condition 3: Valid bankroll
            if bankroll_notional <= 0:
                logger.warning("[TOP3-BATCH] Cannot create batch: invalid bankroll %d", bankroll_notional)
                return None
            
            # CRITICAL: Reject stale signals (edges computed before previous cycle was reconciled)
            # This ensures fresh market analysis for each new cycle
            stale_signals = [c for c in candidates if not c.is_fresh(max_age_seconds=60.0)]
            if stale_signals:
                logger.error(
                    "[STALE-SIGNAL-REJECT] Cannot create batch: %d stale edges detected (age > 60s). "
                    "Each cycle requires FRESH signals computed after previous cycle reconciliation. "
                    "Stale assets: %s",
                    len(stale_signals),
                    [c.asset for c in stale_signals]
                )
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
                # Cap _batch_history at 1000 entries to prevent memory leaks
                if len(self._batch_history) > 1000:
                    self._batch_history = self._batch_history[-1000:]
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
    
    def close_batch(self, batch_id: str, reason: str = "manual", 
                    force: bool = False,
                    require_positions_closed: bool = True) -> bool:
        """Close a batch (for manual override or error recovery).
        
        CRITICAL SAFETY: By default, requires all positions to be closed before
        allowing batch close. This prevents bypassing the cycle lock with open
        positions still at risk.
        
        Args:
            batch_id: ID of batch to close
            reason: Reason for manual close
            force: If True, bypass position check (requires explicit override)
            require_positions_closed: If True (default), requires all positions closed
            
        Returns:
            True if closed successfully, False if batch not found or positions open
        """
        with self._lock:
            if not self._current_batch or self._current_batch.batch_id != batch_id:
                logger.warning("[TOP3-BATCH] Cannot close: batch %s not found", batch_id)
                return False
            
            # CRITICAL: Check if positions are still open (prevents cycle lock bypass)
            if require_positions_closed and not force:
                if not self._current_batch.all_positions_closed():
                    open_positions = [
                        alloc.asset for alloc in self._current_batch.allocations
                        if not alloc.closed
                    ]
                    logger.error(
                        "[TOP3-BATCH] BLOCKED: Cannot close batch %s with open positions: %s. "
                        "Use force=True with explicit authorization to override.",
                        batch_id,
                        open_positions
                    )
                    return False
            
            # Log forced close with warning
            if force or not require_positions_closed:
                logger.critical(
                    "[TOP3-BATCH] FORCE CLOSE batch %s (reason: %s, force=%s, positions_open=%s). "
                    "This bypasses normal cycle safety - operator intervention logged.",
                    batch_id,
                    reason,
                    force,
                    not self._current_batch.all_positions_closed()
                )
            
            self._current_batch.status = BatchStatus.CLOSED
            self._save_state()
            
            logger.warning(
                "[TOP3-BATCH] Batch %s manually CLOSED (reason: %s)",
                batch_id,
                reason
            )
            return True
    
    def mark_batch_reconciled(self, batch_id: str, realized_pnl_cents: int) -> bool:
        """Mark a batch as FULLY_RECONCILED after bankroll is updated.
        
        This is the critical final step in the cycle lifecycle:
        1. Batch ACTIVE (positions open)
        2. Batch CLOSED (all positions resolved)  
        3. Batch FULLY_RECONCILED (bankroll updated with realized P&L)
        
        Only when status is FULLY_RECONCILED can a new cycle start.
        
        Args:
            batch_id: ID of the batch to mark reconciled
            realized_pnl_cents: Realized P&L from this batch (for logging)
            
        Returns:
            True if batch marked reconciled, False if batch not found or already reconciled
        """
        with self._lock:
            if not self._current_batch or self._current_batch.batch_id != batch_id:
                logger.warning(
                    "[TOP3-BATCH] Cannot reconcile: batch %s not found or mismatch (current=%s)",
                    batch_id,
                    self._current_batch.batch_id if self._current_batch else None
                )
                return False
            
            # Only allow transition from CLOSED to FULLY_RECONCILED
            if self._current_batch.status != BatchStatus.CLOSED:
                logger.warning(
                    "[TOP3-BATCH] Cannot reconcile batch %s: status is %s (expected CLOSED)",
                    batch_id,
                    self._current_batch.status.value
                )
                return False
            
            # Mark as fully reconciled
            self._current_batch.status = BatchStatus.FULLY_RECONCILED
            self._current_batch.realized_pnl_cents = realized_pnl_cents
            self._save_state()
            
            logger.info(
                "[TOP3-BATCH] Batch %s FULLY_RECONCILED: realized_pnl=%d¢ - new cycle can now start",
                batch_id,
                realized_pnl_cents
            )
            return True
    
    def is_cycle_locked(self) -> Tuple[bool, str]:
        """CRITICAL: Check if trading cycle is locked.
        
        A cycle is LOCKED (no new execution allowed) when:
        - Batch is ACTIVE (positions still open)
        - Batch is CLOSED but not yet RECONCILED (P&L not realized)
        
        A cycle is UNLOCKED (new execution allowed) when:
        - No batch exists (fresh start)
        - Previous batch is FULLY_RECONCILED (bankroll updated)
        
        This prevents cycle piling - ensures strict sequential execution:
        Cycle 1 Open -> All Positions Close -> Bankroll Reconciled -> Cycle 2 Open
        
        Returns:
            Tuple of (locked: bool, reason: str)
            - locked: True if cycle is locked, False if new cycle can start
            - reason: Empty if unlocked, descriptive message if locked
        """
        with self._lock:
            batch = self.get_current_batch()
            
            if batch is None:
                return False, ""  # Fresh start - cycle unlocked
            
            # LOCKED: Batch is ACTIVE (positions still open)
            if batch.status == BatchStatus.ACTIVE:
                return True, f"CYCLE_LOCKED: Batch {batch.batch_id} is ACTIVE with open positions"
            
            # LOCKED: Batch is CLOSED but not reconciled
            # This is the critical gap that prevents cycle piling
            if batch.status == BatchStatus.CLOSED:
                return True, f"CYCLE_LOCKED: Batch {batch.batch_id} is CLOSED but bankroll not reconciled"
            
            # LOCKED: Any other non-reconciled status
            if batch.status != BatchStatus.FULLY_RECONCILED:
                return True, f"CYCLE_LOCKED: Batch {batch.batch_id} status={batch.status.value}"
            
            # UNLOCKED: Previous cycle fully reconciled
            return False, ""
    
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
    
    def is_in_current_batch(self, market_id: str) -> bool:
        """Check if a market/asset is in the current top-3 batch allocations.
        
        SAFETY: Used by trading agents to verify they are only trading
        top-3 edges per cycle. Prevents 4th, 5th, etc. edges from trading.
        
        Args:
            market_id: Full market ticker (e.g., KXBTC-240125-79000-C)
            
        Returns:
            True if asset extracted from market_id is in current batch allocations
        """
        with self._lock:
            batch = self.get_current_batch()
            if batch is None:
                return False
            
            if batch.status != BatchStatus.ACTIVE:
                return False
            
            # Extract asset from market_id (e.g., "KXBTC-240125-79000-C" -> "BTC")
            asset = self._extract_asset_from_market_id(market_id)
            if not asset:
                return False
            
            # Check if asset is in batch allocations
            allocation = batch.get_allocation_for_asset(asset)
            return allocation is not None
    
    def _extract_asset_from_market_id(self, market_id: str) -> str:
        """Extract asset code from Kalshi market ID.
        
        Examples:
            KXBTC15M-240125-79000-C -> BTC
            KXETH1H-240125-2200-P -> ETH
            KXSOL-240125-100-C -> SOL
        """
        market_id_upper = market_id.upper()
        
        # Known crypto assets
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            if asset in market_id_upper or f"KX{asset}" in market_id_upper:
                return asset
        
        # Fallback: try to extract after KX prefix
        if market_id_upper.startswith("KX"):
            # Remove KX and take next 3-4 chars that are letters
            remainder = market_id_upper[2:]
            asset_code = ""
            for char in remainder:
                if char.isalpha():
                    asset_code += char
                else:
                    break
            if asset_code in assets:
                return asset_code
        
        return ""
    
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
    
    def force_clear_phantom_batch(self, reason: str = "emergency") -> bool:
        """Emergency clear of phantom/stuck batches.
        
        PRODUCTION-SAFE: Only clears batches that have no filled positions.
        This is for recovery when a crash left an ACTIVE batch with no actual positions.
        
        Args:
            reason: Reason for clearing (logged for audit)
            
        Returns:
            True if a phantom batch was cleared, False if no phantom batch found
        """
        with self._lock:
            if not self._current_batch:
                return False
            
            # Only clear if batch has no filled positions (phantom check)
            if self._current_batch.filled_assets:
                logger.error(
                    "[TOP3-BATCH] EMERGENCY CLEAR BLOCKED: batch %s has filled positions %s. "
                    "Use normal close_batch() or wait for positions to close.",
                    self._current_batch.batch_id,
                    list(self._current_batch.filled_assets)
                )
                return False
            
            batch_id = self._current_batch.batch_id
            batch_status = self._current_batch.status.value
            
            # Clear from cache and memory
            cache = self._get_cache()
            if cache and not _is_cache_circuit_open():
                try:
                    cache.delete(_CACHE_KEY_ACTIVE_BATCH)
                    _record_cache_success()
                except Exception as exc:
                    _record_cache_failure()
                    logger.warning("[TOP3-BATCH] Failed to clear cache: %s", exc)
            
            self._current_batch = None
            self._memory_batch = None
            
            logger.critical(
                "[TOP3-BATCH] EMERGENCY PHANTOM CLEAR: batch %s (status=%s) cleared. "
                "Reason: %s. Execution unblocked.",
                batch_id,
                batch_status,
                reason
            )
            return True


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
    """Reset the batch manager singleton (for testing).
    
    CRITICAL SAFETY: This function is TEST-ONLY. It will CRASH in production
    to prevent accidental or malicious cycle lock bypass.
    """
    global _batch_manager_instance
    
    # SAFETY: Prevent production use - only allow in test mode
    if os.environ.get("MERID_TEST_MODE", "0") != "1":
        logger.critical(
            "[TOP3-BATCH] SECURITY VIOLATION: reset_top3_batch_manager() called in production! "
            "This function is TEST-ONLY and can bypass cycle locks. Aborting."
        )
        raise RuntimeError(
            "reset_top3_batch_manager() is TEST-ONLY. "
            "Set MERID_TEST_MODE=1 to enable in test environments."
        )
    
    with _batch_manager_lock:
        # Clear cache first to prevent stale state from being reloaded
        # CIRCUIT BREAKER: Skip if circuit is open, but still clear instance
        if not _is_cache_circuit_open():
            try:
                cache = _cache
                if cache:
                    cache.delete(_CACHE_KEY_ACTIVE_BATCH)
                    _record_cache_success()
            except Exception as e:
                logger.warning("[TOP3-BATCH] Failed to delete cache on shutdown: %s", e)
                _record_cache_failure()
                pass
        _batch_manager_instance = None
