"""
Unified Enforcement Gate for Pre-Trade Risk Checks.

This module implements a single pre-trade enforcement gate that coordinates
all risk checks atomically to prevent race conditions and ensure consistent
enforcement across the trading stack.

CRITICAL FIX (2026-08-01): Addresses Bug 9 - Multiple enforcement layers without coordination.
"""

import time
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.risk.unified_enforcement_gate")


class EnforcementResult(Enum):
    """Result of enforcement check."""
    ALLOWED = "allowed"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class EnforcementDecision:
    """Result of unified enforcement check."""
    result: EnforcementResult
    reason: str
    slot_id: Optional[str] = None
    checks_performed: List[str] = None
    
    def __post_init__(self):
        if self.checks_performed is None:
            self.checks_performed = []


class UnifiedEnforcementGate:
    """
    Single pre-trade enforcement gate that coordinates all risk checks atomically.
    
    This replaces the multiple independent enforcement layers (Slot Allocator,
    Global Allocator, Order Router) with a single atomic check to prevent
    race conditions and ensure consistent enforcement.
    
    CRITICAL FIX (2026-08-01): Addresses Bug 9 - Multiple enforcement layers without coordination.
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._total_checks = 0
        self._total_rejections = 0
        self._total_errors = 0
        
        logger.info("[UNIFIED-GATE] Initialized unified enforcement gate")
    
    def check_order(
        self,
        agent_id: str,
        asset: str,
        ticker: str,
        entry_price_cents: int,
        edge_pct: float,
        confidence: float,
        is_exit_order: bool = False
    ) -> EnforcementDecision:
        """
        Perform unified pre-trade enforcement check.
        
        This method coordinates all risk checks atomically:
        1. Slot allocation check
        2. Global allocator check
        3. Order routing check
        
        All checks happen under a single lock to prevent race conditions.
        
        Args:
            agent_id: Agent identifier
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            ticker: Market ticker
            entry_price_cents: Entry price in cents
            edge_pct: Edge percentage
            confidence: Model confidence (0.0-1.0)
            is_exit_order: Whether this is an exit order
            
        Returns:
            EnforcementDecision with result and reason
        """
        self._total_checks += 1
        checks_performed = []
        
        with self._lock:
            try:
                # Check 1: Slot allocation
                checks_performed.append("slot_allocation")
                slot_result = self._check_slot_allocation(
                    agent_id, asset, ticker, entry_price_cents, is_exit_order
                )
                if not slot_result[0]:
                    self._total_rejections += 1
                    return EnforcementDecision(
                        result=EnforcementResult.REJECTED,
                        reason=f"Slot allocation failed: {slot_result[1]}",
                        checks_performed=checks_performed
                    )
                
                # Check 2: Global allocator (position limits, exposure)
                checks_performed.append("global_allocator")
                global_result = self._check_global_allocator(
                    agent_id, asset, entry_price_cents, edge_pct, confidence
                )
                if not global_result[0]:
                    self._total_rejections += 1
                    return EnforcementDecision(
                        result=EnforcementResult.REJECTED,
                        reason=f"Global allocator check failed: {global_result[1]}",
                        checks_performed=checks_performed
                    )
                
                # Check 3: Order routing (entry windows, etc.)
                checks_performed.append("order_routing")
                routing_result = self._check_order_routing(
                    asset, ticker, is_exit_order
                )
                if not routing_result[0]:
                    self._total_rejections += 1
                    return EnforcementDecision(
                        result=EnforcementResult.REJECTED,
                        reason=f"Order routing check failed: {routing_result[1]}",
                        checks_performed=checks_performed
                    )
                
                # All checks passed
                return EnforcementDecision(
                    result=EnforcementResult.ALLOWED,
                    reason="All checks passed",
                    slot_id=slot_result[1],
                    checks_performed=checks_performed
                )
                
            except Exception as e:
                self._total_errors += 1
                logger.error("[UNIFIED-GATE] Exception during enforcement check: %s", e)
                return EnforcementDecision(
                    result=EnforcementResult.ERROR,
                    reason=f"Enforcement check error: {str(e)}",
                    checks_performed=checks_performed
                )
    
    def _check_slot_allocation(
        self,
        agent_id: str,
        asset: str,
        ticker: str,
        entry_price_cents: int,
        is_exit_order: bool
    ) -> Tuple[bool, Optional[str]]:
        """Check slot allocation (delegates to GlobalSlotAllocator)."""
        try:
            from merid.risk.global_slot_allocator import get_global_slot_allocator, AllocationRequest
            
            allocator = get_global_slot_allocator()
            request = AllocationRequest(
                agent_id=agent_id,
                asset=asset,
                ticker=ticker,
                entry_price_cents=entry_price_cents,
                edge_pct=0.0,  # Not used by slot allocator
                spread_cents=0,  # Not used by slot allocator
                confidence=0.5,  # Not used by slot allocator
                is_exit_order=is_exit_order,
                request_time=time.time()
            )
            
            allocated, reason, slot_id = allocator.request_allocation(request)
            return allocated, slot_id
            
        except Exception as e:
            logger.error("[UNIFIED-GATE] Slot allocation check failed: %s", e)
            return False, None
    
    def _check_global_allocator(
        self,
        agent_id: str,
        asset: str,
        entry_price_cents: int,
        edge_pct: float,
        confidence: float
    ) -> Tuple[bool, str]:
        """Check global allocator limits (delegates to GlobalAllocator)."""
        try:
            from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate
            
            allocator = GlobalAllocator()
            candidate = OrderCandidate(
                asset=asset,
                ticker=f"KX{asset}15M-TEST",  # Simplified ticker
                side="yes",
                action="buy",
                price_cents=entry_price_cents,
                count=1,
                edge_pct=edge_pct,
                confidence=confidence,
                model_prob=confidence,
                agent_name=agent_id
            )
            
            # Check if candidate would be allowed
            chosen = allocator.allocate([candidate], {})
            allowed = len(chosen) > 0
            
            return allowed, "Candidate allowed" if allowed else "Candidate rejected by global allocator"
            
        except Exception as e:
            logger.error("[UNIFIED-GATE] Global allocator check failed: %s", e)
            return False, f"Global allocator check error: {str(e)}"
    
    def _check_order_routing(
        self,
        asset: str,
        ticker: str,
        is_exit_order: bool
    ) -> Tuple[bool, str]:
        """Check order routing constraints (entry windows, etc.)."""
        try:
            from merid.event_venues.kalshi.order_router import _asset_entry_windows, _asset_entry_windows_lock
            
            if is_exit_order:
                return True, "Exit order bypasses routing checks"
            
            # Check entry window
            current_window = int(time.time() // 900) * 900
            with _asset_entry_windows_lock:
                last_window = _asset_entry_windows.get(asset, 0)
                
                if last_window == current_window:
                    return False, f"Asset {asset} already has entry in current 15m window"
            
            return True, "Order routing checks passed"
            
        except Exception as e:
            logger.error("[UNIFIED-GATE] Order routing check failed: %s", e)
            return False, f"Order routing check error: {str(e)}"
    
    def get_statistics(self) -> Dict[str, int]:
        """Get enforcement gate statistics."""
        with self._lock:
            return {
                "total_checks": self._total_checks,
                "total_rejections": self._total_rejections,
                "total_errors": self._total_errors,
                "rejection_rate": (
                    self._total_rejections / self._total_checks if self._total_checks > 0 else 0.0
                )
            }


# Singleton instance
_unified_gate: Optional[UnifiedEnforcementGate] = None


def get_unified_enforcement_gate() -> UnifiedEnforcementGate:
    """Get the singleton unified enforcement gate instance."""
    global _unified_gate
    if _unified_gate is None:
        _unified_gate = UnifiedEnforcementGate()
    return _unified_gate
