"""
Global Slot Allocator for 15m Kalshi Crypto Trading

Enforces hard $1 exposure cap across all 5 assets with slot-based position management.
Each contract consumes its entry price from the $1 cap, and slots free up on exit.

Key Rules:
- Max 1 contract per trade (hard enforcement)
- Entry price must be 10-50c (hard enforcement)
- Total exposure across all 5 assets ≤ $1 (hard enforcement)
- Sequential trading: new entries blocked until $1 frees up
- Re-entry allowed when positions close (slot recycling)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.risk.global_slot_allocator")


class SlotStatus(Enum):
    """Status of a position slot."""
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    PENDING_EXIT = "pending_exit"


@dataclass
class PositionSlot:
    """A single position slot in the global allocator."""
    slot_id: str
    agent_id: str
    asset: str
    ticker: str
    entry_price_cents: int
    entry_time: float
    status: SlotStatus = SlotStatus.OCCUPIED
    
    @property
    def exposure_usd(self) -> float:
        """Exposure in USD for this slot."""
        return self.entry_price_cents / 100.0


@dataclass
class AllocationRequest:
    """Request for slot allocation."""
    agent_id: str
    asset: str
    ticker: str
    entry_price_cents: int
    edge_pct: float
    spread_cents: int
    is_exit_order: bool = False  # CRITICAL: Exit orders bypass slot allocation
    request_time: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Validate request parameters."""
        # Only validate entry price for entry orders
        # Exit orders can be at any price (market orders to close positions)
        if not self.is_exit_order:
            if self.entry_price_cents < 10 or self.entry_price_cents > 50:
                raise ValueError(
                    f"Entry price {self.entry_price_cents}c outside allowed range [10, 50]"
                )


class GlobalSlotAllocator:
    """
    Global slot allocator for 15m Kalshi crypto trading.
    
    Manages a $1 exposure cap across all 5 assets using slot-based allocation.
    Each position consumes its entry price from the cap, and slots are recycled
    when positions exit.
    
    Thread-safe for concurrent access from multiple agents.
    """
    
    # Hard limits
    MAX_EXPOSURE_USD = 1.00
    MIN_ENTRY_CENTS = 10
    MAX_ENTRY_CENTS = 50
    MAX_CONTRACTS_PER_ORDER = 1
    
    def __init__(self):
        self._lock = threading.RLock()  # Use reentrant lock to prevent deadlock
        
        # Active position slots
        self._slots: Dict[str, PositionSlot] = {}  # slot_id -> PositionSlot
        
        # Allocation statistics
        self._total_requests = 0
        self._total_allocations = 0
        self._total_rejections = 0
        self._total_releases = 0
        
        logger.info(
            "[SLOT-ALLOCATOR] Initialized with max_exposure=$%.2f, "
            "entry_range=[%dc-%dc], max_contracts=%d",
            self.MAX_EXPOSURE_USD, self.MIN_ENTRY_CENTS, 
            self.MAX_ENTRY_CENTS, self.MAX_CONTRACTS_PER_ORDER
        )
    
    def get_available_exposure(self) -> float:
        """Get available exposure in USD."""
        with self._lock:
            total_exposure = sum(slot.exposure_usd for slot in self._slots.values())
            available = self.MAX_EXPOSURE_USD - total_exposure
            return max(0.0, available)
    
    def get_total_exposure(self) -> float:
        """Get total current exposure in USD."""
        with self._lock:
            return sum(slot.exposure_usd for slot in self._slots.values())
    
    def get_slot_count(self) -> int:
        """Get number of active position slots."""
        with self._lock:
            return len(self._slots)
    
    def get_slots_by_asset(self, asset: str) -> List[PositionSlot]:
        """Get all slots for a specific asset."""
        with self._lock:
            return [slot for slot in self._slots.values() if slot.asset == asset]
    
    def can_allocate(
        self, 
        entry_price_cents: int, 
        asset: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Check if a slot can be allocated for the given entry price.
        
        Args:
            entry_price_cents: Entry price in cents
            asset: Optional asset symbol for per-asset checks
            
        Returns:
            Tuple of (allowed, reason)
        """
        # Check entry price range
        if entry_price_cents < self.MIN_ENTRY_CENTS:
            return False, f"Entry price {entry_price_cents}c below minimum {self.MIN_ENTRY_CENTS}c"
        
        if entry_price_cents > self.MAX_ENTRY_CENTS:
            return False, f"Entry price {entry_price_cents}c above maximum {self.MAX_ENTRY_CENTS}c"
        
        # Check available exposure
        required_exposure = entry_price_cents / 100.0
        available = self.get_available_exposure()
        
        if required_exposure > available:
            return False, (
                f"Insufficient exposure: required ${required_exposure:.2f}, "
                f"available ${available:.2f}, total ${self.get_total_exposure():.2f}"
            )
        
        # Check if enough room for minimum entry (10c)
        if available - required_exposure < (self.MIN_ENTRY_CENTS / 100.0):
            # This is OK - we just won't be able to add another position after this one
            logger.debug(
                "[SLOT-ALLOCATOR] Allocation would leave <10c available: "
                "this is the last possible slot"
            )
        
        return True, ""
    
    def request_allocation(
        self, 
        request: AllocationRequest
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Request a slot allocation.
        
        Args:
            request: AllocationRequest with trade details
            
        Returns:
            Tuple of (allocated, reason, slot_id)
        """
        self._total_requests += 1
        
        # CRITICAL: Exit orders bypass slot allocation entirely
        # Exit orders reduce exposure, so they should always be allowed
        # This ensures positions can be closed to lock in profits even at full capacity
        if request.is_exit_order:
            logger.info(
                "[SLOT-ALLOCATOR] Exit order bypasses allocation: agent=%s asset=%s ticker=%s",
                request.agent_id, request.asset, request.ticker
            )
            # Return success without allocating a slot
            # Exit orders don't consume slots, they free them
            return True, "EXIT_ORDER_BYPASS", None
        
        # Validate request for entry orders
        try:
            if request.entry_price_cents < self.MIN_ENTRY_CENTS:
                self._total_rejections += 1
                return False, f"Entry price {request.entry_price_cents}c below minimum", None
            
            if request.entry_price_cents > self.MAX_ENTRY_CENTS:
                self._total_rejections += 1
                return False, f"Entry price {request.entry_price_cents}c above maximum", None
        except ValueError as e:
            self._total_rejections += 1
            return False, str(e), None
        
        # Check if allocation is possible
        can_allocate, reason = self.can_allocate(request.entry_price_cents, request.asset)
        
        if not can_allocate:
            self._total_rejections += 1
            logger.info(
                "[SLOT-ALLOCATOR] Rejected allocation: agent=%s asset=%s "
                "price=%dc edge=%.2f%% spread=%dc - %s",
                request.agent_id, request.asset, request.entry_price_cents,
                request.edge_pct, request.spread_cents, reason
            )
            return False, reason, None
        
        # Allocate slot
        with self._lock:
            slot_id = f"{request.agent_id}_{request.asset}_{int(time.time() * 1000)}"
            
            slot = PositionSlot(
                slot_id=slot_id,
                agent_id=request.agent_id,
                asset=request.asset,
                ticker=request.ticker,
                entry_price_cents=request.entry_price_cents,
                entry_time=request.request_time,
                status=SlotStatus.OCCUPIED
            )
            
            self._slots[slot_id] = slot
            self._total_allocations += 1
            
            total_exposure = self.get_total_exposure()
            available = self.get_available_exposure()
            
            logger.info(
                "[SLOT-ALLOCATOR] Allocated slot: slot_id=%s agent=%s asset=%s "
                "ticker=%s price=%dc edge=%.2f%% spread=%dc "
                "total_exposure=$%.2f available=$%.2f slot_count=%d",
                slot_id, request.agent_id, request.asset, request.ticker,
                request.entry_price_cents, request.edge_pct, request.spread_cents,
                total_exposure, available, len(self._slots)
            )
            
            return True, "", slot_id
    
    def release_slot(self, slot_id: str, exit_price_cents: Optional[int] = None) -> bool:
        """
        Release a slot (position closed).
        
        Args:
            slot_id: Slot identifier
            exit_price_cents: Optional exit price for PnL tracking
            
        Returns:
            True if slot was released, False if not found
        """
        with self._lock:
            if slot_id not in self._slots:
                logger.warning("[SLOT-ALLOCATOR] Slot not found for release: %s", slot_id)
                return False
            
            slot = self._slots.pop(slot_id)
            self._total_releases += 1
            
            total_exposure = self.get_total_exposure()
            available = self.get_available_exposure()
            
            pnl_cents = None
            if exit_price_cents is not None:
                pnl_cents = exit_price_cents - slot.entry_price_cents
            
            logger.info(
                "[SLOT-ALLOCATOR] Released slot: slot_id=%s agent=%s asset=%s "
                "ticker=%s entry=%dc exit=%s pnl=%s "
                "total_exposure=$%.2f available=$%.2f slot_count=%d",
                slot_id, slot.agent_id, slot.asset, slot.ticker,
                slot.entry_price_cents, 
                f"{exit_price_cents}c" if exit_price_cents else "N/A",
                f"{pnl_cents}c" if pnl_cents is not None else "N/A",
                total_exposure, available, len(self._slots)
            )
            
            return True
    
    def release_by_agent(self, agent_id: str) -> int:
        """
        Release all slots for a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Number of slots released
        """
        with self._lock:
            slots_to_release = [
                slot_id for slot_id, slot in self._slots.items()
                if slot.agent_id == agent_id
            ]
            
            for slot_id in slots_to_release:
                self._slots.pop(slot_id)
                self._total_releases += 1
            
            if slots_to_release:
                logger.info(
                    "[SLOT-ALLOCATOR] Released %d slots for agent=%s",
                    len(slots_to_release), agent_id
                )
            
            return len(slots_to_release)
    
    def release_by_asset(self, asset: str) -> int:
        """
        Release all slots for a specific asset.
        
        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")
            
        Returns:
            Number of slots released
        """
        with self._lock:
            slots_to_release = [
                slot_id for slot_id, slot in self._slots.items()
                if slot.asset == asset
            ]
            
            for slot_id in slots_to_release:
                self._slots.pop(slot_id)
                self._total_releases += 1
            
            if slots_to_release:
                logger.info(
                    "[SLOT-ALLOCATOR] Released %d slots for asset=%s",
                    len(slots_to_release), asset
                )
            
            return len(slots_to_release)
    
    def reset_all(self) -> None:
        """Reset all slots (emergency recovery)."""
        with self._lock:
            count = len(self._slots)
            self._slots.clear()
            logger.warning(
                "[SLOT-ALLOCATOR] Emergency reset: released %d slots", count
            )
    
    def get_summary(self) -> Dict:
        """Get allocator summary statistics."""
        with self._lock:
            return {
                "total_exposure_usd": self.get_total_exposure(),
                "available_exposure_usd": self.get_available_exposure(),
                "slot_count": len(self._slots),
                "total_requests": self._total_requests,
                "total_allocations": self._total_allocations,
                "total_rejections": self._total_rejections,
                "total_releases": self._total_releases,
                "slots": [
                    {
                        "slot_id": slot.slot_id,
                        "agent_id": slot.agent_id,
                        "asset": slot.asset,
                        "ticker": slot.ticker,
                        "entry_price_cents": slot.entry_price_cents,
                        "exposure_usd": slot.exposure_usd,
                        "status": slot.status.value,
                        "entry_time": slot.entry_time,
                    }
                    for slot in self._slots.values()
                ]
            }


# Singleton instance
_global_slot_allocator: Optional[GlobalSlotAllocator] = None
_allocator_lock = threading.Lock()


def get_global_slot_allocator() -> GlobalSlotAllocator:
    """Get the global slot allocator singleton."""
    global _global_slot_allocator
    
    with _allocator_lock:
        if _global_slot_allocator is None:
            _global_slot_allocator = GlobalSlotAllocator()
            logger.info("[SLOT-ALLOCATOR] Singleton created")
    
    return _global_slot_allocator


def reset_global_slot_allocator() -> None:
    """Reset the global slot allocator (testing/recovery only)."""
    global _global_slot_allocator
    
    with _allocator_lock:
        if _global_slot_allocator is not None:
            _global_slot_allocator.reset_all()
        _global_slot_allocator = None
        logger.info("[SLOT-ALLOCATOR] Singleton reset")
