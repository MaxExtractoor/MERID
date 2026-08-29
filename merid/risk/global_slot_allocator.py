"""
Global Slot Allocator for 15m Kalshi Crypto Trading

Enforces hard $1 exposure cap across all 5 assets with slot-based position management.
Each contract consumes its entry price from the $1 cap, and slots free up on exit.

Key Rules:
- Max 2 contracts per trade (hard cap, still bounded by the $1 exposure cap)
- Entry price must be 10-75c (hard enforcement)
- Total exposure across all 5 assets ≤ $1 (hard enforcement)
- Sequential trading: new entries blocked until $1 frees up
- Re-entry allowed when positions close (slot recycling)
- Portfolio-level optimization using numerical methods for optimal allocation
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import numpy as np

from utils.logger import get_logger

logger = get_logger("merid.risk.global_slot_allocator")


def _get_resolved_or_default() -> Optional[Any]:
    """Return the resolved live config if available, otherwise None."""
    try:
        from merid.config.live_config import get_resolved_live_config

        resolved = get_resolved_live_config(allow_unresolved=True)
        if resolved.resolved:
            return resolved
    except Exception:
        pass
    return None


# Maximum contracts per order under the fixed $2 exposure cap.
# 2026-08-22: Raised from 1 to 2 to double per-asset exposure while keeping total ≤ $2.
MAX_CONTRACTS_PER_ORDER = 2


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
    count: int = 1  # number of contracts represented by this slot

    @property
    def exposure_usd(self) -> float:
        """Exposure in USD for this slot."""
        return (self.count * self.entry_price_cents) / 100.0


# Backwards-compatible alias used by legacy test suites.
Slot = PositionSlot


@dataclass
class AllocationRequest:
    """Request for slot allocation."""
    agent_id: str
    asset: str
    ticker: str
    entry_price_cents: int
    edge_pct: float
    spread_cents: int
    confidence: float = 0.5  # Model confidence (0.0-1.0) for priority/tiebreaker
    is_exit_order: bool = False  # CRITICAL: Exit orders bypass slot allocation
    count: int = 1  # Contract count (default 1, used for validation)
    request_time: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Validate request parameters."""
        resolved = _get_resolved_or_default()
        max_contracts = resolved.max_contracts_per_order if resolved else MAX_CONTRACTS_PER_ORDER
        min_entry_cents = resolved.min_entry_cents if resolved else 10
        max_entry_cents = resolved.max_entry_cents if resolved else 75

        if self.count < 1:
            raise ValueError(f"count>0 required, got count={self.count}")
        # Only validate entry price and per-order count cap for entry orders.
        # Exit orders can be at any price and may exceed 2 contracts to close a position.
        if not self.is_exit_order:
            if not (1 <= self.count <= max_contracts):
                raise ValueError(
                    f"Entry orders must have count between 1 and {max_contracts}, got count={self.count}"
                )
            if self.entry_price_cents < min_entry_cents or self.entry_price_cents > max_entry_cents:
                raise ValueError(
                    f"Entry price {self.entry_price_cents}c outside allowed range [{min_entry_cents}, {max_entry_cents}]"
                )
            # Validate confidence range
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError(
                    f"Confidence {self.confidence} outside allowed range [0.0, 1.0]"
                )


class GlobalSlotAllocator:
    """
    Global slot allocator for 15m Kalshi crypto trading.

    Manages an exposure cap across all 5 assets using slot-based allocation.
    Each position consumes its entry price from the cap, and slots are recycled
    when positions exit.

    Thread-safe for concurrent access from multiple agents.

    2026-08-28: Hard limits are now env-overridable so the $2/2-contract defaults
    can be lowered without code changes while the account is small.
    """

    # Hard limits (env-overridable; default to legacy $2 / 2-contract values)
    MAX_EXPOSURE_USD = float(os.getenv("MERID_MAX_EXPOSURE_USD", "2.00"))
    MIN_ENTRY_CENTS = int(os.getenv("MERID_MIN_ENTRY_CENTS", "10"))
    MAX_ENTRY_CENTS = int(os.getenv("MERID_MAX_ENTRY_CENTS", "75"))
    MAX_CONTRACTS_PER_ORDER = int(os.getenv("MERID_MAX_CONTRACTS_PER_ORDER", "2"))
    MAX_POSITIONS_PER_ASSET = int(os.getenv("MERID_MAX_POSITIONS_PER_ASSET", "1"))

    def __init__(self):
        self._lock = threading.RLock()  # Use reentrant lock to prevent deadlock

        # Active position slots
        self._slots: Dict[str, PositionSlot] = {}  # slot_id -> PositionSlot

        # Allocation statistics
        self._total_requests = 0
        self._total_allocations = 0
        self._total_rejections = 0
        self._total_releases = 0

        # Prefer the resolved live config; fall back to class defaults.
        resolved = _get_resolved_or_default()
        if resolved is not None:
            self.max_exposure_usd = float(resolved.fixed_exposure_cap_usd)
            self.min_entry_cents = int(resolved.min_entry_cents)
            self.max_entry_cents = int(resolved.max_entry_cents)
            self.max_contracts_per_order = int(resolved.max_contracts_per_order)
            self.max_positions_per_asset = int(resolved.max_positions_per_asset)
        else:
            self.max_exposure_usd = self.MAX_EXPOSURE_USD
            self.min_entry_cents = self.MIN_ENTRY_CENTS
            self.max_entry_cents = self.MAX_ENTRY_CENTS
            self.max_contracts_per_order = self.MAX_CONTRACTS_PER_ORDER
            self.max_positions_per_asset = self.MAX_POSITIONS_PER_ASSET

        logger.info(
            "[SLOT-ALLOCATOR] Initialized with max_exposure=$%.2f, "
            "entry_range=[%dc-%dc], max_contracts=%d",
            self.max_exposure_usd, self.min_entry_cents,
            self.max_entry_cents, self.max_contracts_per_order
        )
    
    def get_available_exposure(self) -> float:
        """Get available exposure in USD."""
        with self._lock:
            total_exposure = round(sum(slot.exposure_usd for slot in self._slots.values()), 2)
            available = round(self.max_exposure_usd - total_exposure, 2)
            return max(0.0, available)
    
    def get_total_exposure(self) -> float:
        """Get total current exposure in USD."""
        with self._lock:
            return round(sum(slot.exposure_usd for slot in self._slots.values()), 2)
    
    def get_slot_count(self) -> int:
        """Get number of active position slots."""
        with self._lock:
            return len(self._slots)
    
    def sync_with_position_cache(self) -> int:
        """
        Sync slot allocator with the canonical position cache.

        This method does three things:
        1. Removes slots for positions that no longer exist (orphans).
        2. Updates existing slots to the actual fill price / contract count.
        3. Creates new slots for positions that exist but have no slot.

        Keeping slot exposure in sync with real position notional is the only
        way the hard $1 cap can be enforced on filled, not requested, prices.

        Returns:
            Number of slots changed (added + updated + removed)
        """
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            from merid.event_venues.kalshi.market_filter import (
                extract_asset_from_ticker,
                parse_expiry_from_ticker,
            )

            position_cache = get_position_cache()
            actual_positions = position_cache.get_all_positions()
            now = time.time()
            # 2026-08-22: Allow 10-minute buffer after a 15m market's parsed expiry
            # before treating a slot as stale.  This prevents us from holding
            # exposure for contracts that should have settled/closed.
            EXPIRY_BUFFER_SECONDS = 600.0

            def _slot_market_expired(ticker: str) -> bool:
                expiry_ts = parse_expiry_from_ticker(ticker)
                return expiry_ts > 0.0 and now > expiry_ts + EXPIRY_BUFFER_SECONDS

            with self._lock:
                changed = 0

                # Map actual positions by ticker for slot matching.
                # Defensive: position_cache.get_all_positions() returns either a dict
                # mapping market_id -> position, or a list of positions.
                if actual_positions is None:
                    actual_positions = []
                if isinstance(actual_positions, dict):
                    position_list = list(actual_positions.values())
                else:
                    position_list = list(actual_positions)

                position_by_ticker = {
                    pos.market_id: pos for pos in position_list
                }

                # Track which positions have a matching slot.
                tickers_with_slot = set()

                # 1. Reconcile / remove existing slots.
                for slot_id, slot in list(self._slots.items()):
                    pos = position_by_ticker.get(slot.ticker)

                    # CRITICAL FIX (2026-08-22): Remove slots for markets that have
                    # already expired and passed the settlement buffer.  15m crypto
                    # contracts should not leave exposure allocated after expiry; the
                    # fills_ledger and position cache alone cannot always clean these
                    # up because settlement does not generate a closing fill.  This
                    # prevents phantom exposure from blocking new entries.
                    if _slot_market_expired(slot.ticker):
                        logger.warning(
                            "[SLOT-ALLOCATOR] Removed expired-market slot: slot_id=%s "
                            "ticker=%s agent=%s age=%.0fs",
                            slot_id, slot.ticker, slot.agent_id,
                            now - slot.entry_time
                        )
                        del self._slots[slot_id]
                        self._total_releases += 1
                        changed += 1
                        continue

                    if pos is None:
                        logger.info(
                            "[SLOT-ALLOCATOR] Removed orphaned slot: slot_id=%s ticker=%s agent=%s",
                            slot_id, slot.ticker, slot.agent_id
                        )
                        del self._slots[slot_id]
                        self._total_releases += 1
                        changed += 1
                        continue

                    tickers_with_slot.add(pos.market_id)

                    # Derive the actual fill price from position cache.
                    pos_count = max(int(pos.contracts), 1)
                    if pos.avg_price_cents is not None and pos.avg_price_cents > 0:
                        fill_price_cents = int(pos.avg_price_cents)
                    elif pos.notional_usd and pos_count > 0:
                        fill_price_cents = int(
                            round(float(pos.notional_usd) * 100.0 / pos_count)
                        )
                    else:
                        fill_price_cents = slot.entry_price_cents

                    if (slot.entry_price_cents != fill_price_cents or
                            slot.count != pos_count):
                        old_price = slot.entry_price_cents
                        old_count = slot.count
                        slot.entry_price_cents = fill_price_cents
                        slot.count = pos_count
                        logger.info(
                            "[SLOT-ALLOCATOR] Updated slot from position cache: "
                            "slot_id=%s ticker=%s old_price=%dc old_count=%d "
                            "new_price=%dc new_count=%d",
                            slot_id, slot.ticker, old_price, old_count,
                            fill_price_cents, pos_count
                        )
                        changed += 1

                # 2. Create slots for positions that do not have one.
                for ticker, pos in position_by_ticker.items():
                    if ticker in tickers_with_slot:
                        continue

                    # Do not allocate slots for positions in already-expired markets.
                    # The position cache may still hold a settled/phantom position;
                    # creating a slot for it would consume the $1 cap unnecessarily.
                    if _slot_market_expired(ticker):
                        logger.warning(
                            "[SLOT-ALLOCATOR] Skipping expired-market position: ticker=%s agent=%s",
                            ticker, pos.agent_id if pos else "unknown"
                        )
                        continue

                    pos_count = max(int(pos.contracts), 1)
                    if pos.avg_price_cents is not None and pos.avg_price_cents > 0:
                        fill_price_cents = int(pos.avg_price_cents)
                    elif pos.notional_usd and pos_count > 0:
                        fill_price_cents = int(
                            round(float(pos.notional_usd) * 100.0 / pos_count)
                        )
                    else:
                        fill_price_cents = 50

                    asset = extract_asset_from_ticker(ticker) or "UNKNOWN"
                    new_slot_id = (
                        f"{pos.agent_id or asset}_{asset}_{int(time.time() * 1000)}"
                    )
                    new_slot = PositionSlot(
                        slot_id=new_slot_id,
                        agent_id=pos.agent_id or f"{asset}_15M",
                        asset=asset,
                        ticker=ticker,
                        entry_price_cents=fill_price_cents,
                        entry_time=time.time(),
                        status=SlotStatus.OCCUPIED,
                        count=pos_count,
                    )
                    self._slots[new_slot_id] = new_slot
                    self._total_allocations += 1
                    logger.info(
                        "[SLOT-ALLOCATOR] Created slot from position cache: "
                        "slot_id=%s ticker=%s agent=%s price=%dc count=%d",
                        new_slot_id, ticker, new_slot.agent_id,
                        fill_price_cents, pos_count
                    )
                    changed += 1

                if changed > 0:
                    total_exposure = self.get_total_exposure()
                    available = self.get_available_exposure()
                    logger.info(
                        "[SLOT-ALLOCATOR] sync_with_position_cache: %d slot changes, "
                        "total_exposure=$%.2f available=$%.2f slot_count=%d",
                        changed, total_exposure, available, len(self._slots)
                    )

                return changed

        except Exception as e:
            logger.warning(
                "[SLOT-ALLOCATOR] sync_with_position_cache failed: %s",
                e
            )
            return 0

    def clear_stale_slots(self, max_age_seconds: float = 1800.0) -> int:
        """
        Remove slots that have been occupied longer than ``max_age_seconds``.

        This is a safety net for slots that were not released when a position
        closed (e.g. crashed orders, network failures, partial fills). Removing
        stale slots frees exposure budget for new entries.

        Args:
            max_age_seconds: Maximum age in seconds before a slot is considered stale.

        Returns:
            Number of stale slots removed.
        """
        with self._lock:
            now = time.time()
            cleared = 0
            for slot_id in list(self._slots.keys()):
                slot = self._slots[slot_id]
                if now - slot.entry_time > max_age_seconds:
                    logger.warning(
                        "[SLOT-ALLOCATOR] Removed stale slot: slot_id=%s ticker=%s "
                        "agent=%s age=%.0fs",
                        slot_id, slot.ticker, slot.agent_id,
                        now - slot.entry_time
                    )
                    del self._slots[slot_id]
                    self._total_releases += 1
                    cleared += 1

            if cleared > 0:
                total_exposure = self.get_total_exposure()
                available = self.get_available_exposure()
                logger.info(
                    "[SLOT-ALLOCATOR] clear_stale_slots: removed %d stale slots, "
                    "total_exposure=$%.2f available=$%.2f slot_count=%d",
                    cleared, total_exposure, available, len(self._slots)
                )

            return cleared

    def get_slots_by_asset(self, asset: str) -> List[PositionSlot]:
        """Get all slots for a specific asset."""
        with self._lock:
            return [slot for slot in self._slots.values() if slot.asset == asset]
    
    def can_allocate(
        self,
        entry_price_cents: int,
        asset: Optional[str] = None,
        count: int = 1
    ) -> Tuple[bool, str]:
        """
        Check if a slot can be allocated for the given entry price.

        Args:
            entry_price_cents: Entry price in cents
            asset: Optional asset symbol for per-asset checks
            count: Number of contracts (default 1)

        Returns:
            Tuple of (allowed, reason)
        """
        # Check entry price range
        if entry_price_cents < self.min_entry_cents:
            return False, f"Entry price {entry_price_cents}c below minimum {self.min_entry_cents}c"

        if entry_price_cents > self.max_entry_cents:
            return False, f"Entry price {entry_price_cents}c above maximum {self.max_entry_cents}c"

        if count > self.max_contracts_per_order:
            return False, (
                f"Contract count {count} exceeds max {self.max_contracts_per_order} "
                f"per order"
            )

        # Check per-asset position limit (2026-07-13: Only 1 position per asset)
        if asset is not None:
            existing_asset_slots = self.get_slots_by_asset(asset)
            if len(existing_asset_slots) >= self.max_positions_per_asset:
                return False, (
                    f"Asset {asset} already has {len(existing_asset_slots)} position(s), "
                    f"max {self.max_positions_per_asset} allowed"
                )

        # Check available exposure
        # CRITICAL FIX (2026-08-24): Round to 2 decimals to avoid floating-point
        # epsilon causing false "Insufficient exposure" rejections when
        # required and available are equal to the cent.
        required_exposure = round((count * entry_price_cents) / 100.0, 2)
        available = round(self.get_available_exposure(), 2)

        if required_exposure > available:
            return False, (
                f"Insufficient exposure: required ${required_exposure:.2f}, "
                f"available ${available:.2f}, total ${self.get_total_exposure():.2f}"
            )

        # 2026-07-13: DISABLED correlation discount to simplify multi-asset position management
        # The correlation discount was causing excessive rejections and interfering with
        # the per-asset position limit and cheapest-price-first selection logic.
        # Re-enable if needed with proper configuration and testing.

        # Check if enough room for minimum entry (10c)
        if round(available - required_exposure, 2) < round(self.min_entry_cents / 100.0, 2):
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
            if request.entry_price_cents < self.min_entry_cents:
                self._total_rejections += 1
                return False, f"Entry price {request.entry_price_cents}c below minimum", None
            
            if request.entry_price_cents > self.max_entry_cents:
                self._total_rejections += 1
                return False, f"Entry price {request.entry_price_cents}c above maximum", None
        except ValueError as e:
            self._total_rejections += 1
            return False, str(e), None
        
        # Check if allocation is possible
        can_allocate, reason = self.can_allocate(
            request.entry_price_cents, request.asset, count=request.count
        )

        if not can_allocate:
            self._total_rejections += 1
            logger.info(
                "[SLOT-ALLOCATOR] Rejected allocation: agent=%s asset=%s "
                "price=%dc count=%d edge=%.2f%% spread=%dc confidence=%.2f - %s",
                request.agent_id, request.asset, request.entry_price_cents,
                request.count, request.edge_pct, request.spread_cents,
                request.confidence, reason
            )
            return False, reason, None

        # Allocate slot
        # CRITICAL FIX (2026-08-01): Add try-finally to ensure slot cleanup on exceptions
        slot_id = None
        with self._lock:
            try:
                slot_id = f"{request.agent_id}_{request.asset}_{int(time.time() * 1000)}"

                slot = PositionSlot(
                    slot_id=slot_id,
                    agent_id=request.agent_id,
                    asset=request.asset,
                    ticker=request.ticker,
                    entry_price_cents=request.entry_price_cents,
                    entry_time=request.request_time,
                    status=SlotStatus.OCCUPIED,
                    count=request.count,
                )

                self._slots[slot_id] = slot
                self._total_allocations += 1
                
                total_exposure = self.get_total_exposure()
                available = self.get_available_exposure()
                
                logger.info(
                    "[SLOT-ALLOCATOR] Allocated slot: slot_id=%s agent=%s asset=%s "
                    "ticker=%s price=%dc count=%d edge=%.2f%% spread=%dc confidence=%.2f "
                    "total_exposure=$%.2f available=$%.2f slot_count=%d",
                    slot_id, request.agent_id, request.asset, request.ticker,
                    request.entry_price_cents, request.count, request.edge_pct,
                    request.spread_cents, request.confidence, total_exposure, available,
                    len(self._slots)
                )
                
                return True, "", slot_id
                
            except Exception as e:
                # CRITICAL FIX (2026-08-01): Ensure slot cleanup on exception
                logger.error("[SLOT-ALLOCATOR] Exception during allocation: %s", e)
                if slot_id and slot_id in self._slots:
                    del self._slots[slot_id]
                    logger.warning("[SLOT-ALLOCATOR] Cleaned up partially allocated slot: %s", slot_id)
                return False, f"Allocation failed: {str(e)}", None
    
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
                pnl_cents = (exit_price_cents - slot.entry_price_cents) * slot.count
            
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

    def update_slot_fill_price(
        self,
        slot_id: str,
        fill_price_cents: int,
        filled_count: int = 1,
    ) -> bool:
        """
        Update an allocated slot to the actual fill price and filled count.

        The slot is created at request time using the intended limit price, but
        the actual notional consumed by a position is ``filled_count *
        fill_price_cents``.  If the slot is not updated after a fill, the $1
        exposure cap is enforced on stale (too low) prices and the account can
        end up with more than $1 of real exposure.

        Args:
            slot_id: Slot identifier returned by request_allocation.
            fill_price_cents: Confirmed fill price in cents.
            filled_count: Number of contracts actually filled (default 1).

        Returns:
            True if the slot was updated, False if not found.
        """
        with self._lock:
            slot = self._slots.get(slot_id)
            if slot is None:
                logger.debug(
                    "[SLOT-ALLOCATOR] update_slot_fill_price: slot_id=%s not found",
                    slot_id
                )
                return False

            old_price = slot.entry_price_cents
            old_count = slot.count
            slot.entry_price_cents = int(fill_price_cents)
            slot.count = int(filled_count)

            total_exposure = self.get_total_exposure()
            available = self.get_available_exposure()
            logger.info(
                "[SLOT-ALLOCATOR] Updated slot to fill price: slot_id=%s "
                "ticker=%s old_price=%dc old_count=%d new_price=%dc new_count=%d "
                "total_exposure=$%.2f available=$%.2f slot_count=%d",
                slot_id, slot.ticker, old_price, old_count,
                slot.entry_price_cents, slot.count,
                total_exposure, available, len(self._slots)
            )
            return True

    def update_slot_by_ticker(
        self,
        ticker: str,
        fill_price_cents: int,
        filled_count: int = 1,
    ) -> bool:
        """
        Update the first matching slot by ticker to the actual fill price.

        Used when a fill arrives without the original slot_id (e.g. via WS/HTTP
        fill pollers) or as a defensive fallback for order-router updates.

        Args:
            ticker: Market ticker.
            fill_price_cents: Confirmed fill price in cents.
            filled_count: Number of contracts actually filled (default 1).

        Returns:
            True if a matching slot was updated, False otherwise.
        """
        if not ticker:
            logger.debug(
                "[SLOT-ALLOCATOR] update_slot_by_ticker called with empty ticker; ignoring"
            )
            return False

        normalized = ticker.strip().upper()
        with self._lock:
            for slot_id, slot in list(self._slots.items()):
                slot_ticker = (slot.ticker or "").strip().upper()
                if slot_ticker == normalized or slot_ticker.startswith(normalized + "-"):
                    return self.update_slot_fill_price(slot_id, fill_price_cents, filled_count)

        logger.debug(
            "[SLOT-ALLOCATOR] update_slot_by_ticker: no slot for ticker=%s", ticker
        )
        return False

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
    
    def release_slot_by_ticker(self, ticker: Optional[str], exit_price_cents: Optional[int] = None) -> bool:
        """
        Release a slot by ticker (for exit orders).

        This method is used by exit orders to release the original entry slot
        when the exit order fills and closes the position. It finds the slot
        by ticker and releases it, tracking PnL if exit price is provided.

        Args:
            ticker: Market ticker (e.g., "KXBTC15M-26JUL312200-00")
            exit_price_cents: Optional exit price for PnL tracking

        Returns:
            True if slot was released, False if not found
        """
        # CRITICAL FIX (2026-08-21): Guard against empty/None tickers.  Callers such
        # as the order-router cleanup path were passing ``None`` for exits that had
        # no ticker, producing noisy "Failed to release slot by ticker:" warnings
        # and leaking slots because the lookup never matched.
        if not ticker:
            logger.debug(
                "[SLOT-ALLOCATOR] release_slot_by_ticker called with empty ticker; ignoring"
            )
            return False

        # Normalize full-ticker vs. strip.  A slot is always keyed by the full
        # market ticker used at entry, but some callers pass a series strip.
        normalized = ticker.strip().upper()

        with self._lock:
            for slot_id, slot in list(self._slots.items()):
                slot_ticker = (slot.ticker or "").strip().upper()
                if slot_ticker == normalized or slot_ticker.startswith(normalized + "-"):
                    # Calculate PnL if exit price provided
                    pnl_cents = None
                    if exit_price_cents is not None:
                        pnl_cents = (exit_price_cents - slot.entry_price_cents) * slot.count

                    # Log the release
                    total_exposure = sum(s.exposure_usd for s in self._slots.values())
                    available = self.max_exposure_usd - total_exposure

                    logger.info(
                        "[SLOT-ALLOCATOR] Released slot by ticker: slot_id=%s agent=%s asset=%s ticker=%s "
                        "entry_price=%dc exit_price=%s pnl=%s total_exposure=$%.2f available=$%.2f slot_count=%d",
                        slot_id, slot.agent_id, slot.asset, slot.ticker,
                        slot.entry_price_cents,
                        f"{exit_price_cents}c" if exit_price_cents else "N/A",
                        f"{pnl_cents}c" if pnl_cents is not None else "N/A",
                        total_exposure, available, len(self._slots)
                    )

                    # Remove the slot
                    del self._slots[slot_id]
                    self._total_releases += 1
                    return True

            # Ticker not found
            logger.warning(
                "[SLOT-ALLOCATOR] Failed to release slot by ticker: ticker=%s not found in %d slots",
                ticker, len(self._slots)
            )
            return False
    
    def reset_all(self) -> None:
        """Reset all slots (emergency recovery)."""
        with self._lock:
            count = len(self._slots)
            self._slots.clear()
            logger.warning(
                "[SLOT-ALLOCATOR] Emergency reset: released %d slots", count
            )
    
    def clear_slots_on_empty_positions(self, position_count: int) -> None:
        """Clear all slots when position cache shows no open positions.
        
        CRITICAL FIX (2026-07-13): This prevents phantom exposure from previous sessions
        when slots were not properly released (e.g., shutdown before closure events).
        Should be called when position cache sync returns zero open positions.
        
        Args:
            position_count: Number of open positions from position cache
        """
        if position_count > 0:
            return  # Don't clear if there are actual positions
        
        with self._lock:
            if not self._slots:
                return  # Nothing to clear
            
            count = len(self._slots)
            total_exposure = self.get_total_exposure()
            self._slots.clear()
            logger.warning(
                "[SLOT-ALLOCATOR] Cleared %d phantom slots (position_count=%d, phantom_exposure=$%.2f)",
                count, position_count, total_exposure
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
                        "count": slot.count,
                        "exposure_usd": slot.exposure_usd,
                        "status": slot.status.value,
                        "entry_time": slot.entry_time,
                    }
                    for slot in self._slots.values()
                ]
            }
    
    def optimize_portfolio_allocation(
        self,
        opportunities: List[Dict[str, any]],
        correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None
    ) -> Dict[str, float]:
        """
        Calculate optimal portfolio allocation using numerical optimization.
        
        Uses mean-variance optimization with correlation-adjusted risk to find
        the optimal allocation across available opportunities within the $1 cap.
        
        Args:
            opportunities: List of opportunity dicts with keys:
                - asset: Asset symbol (e.g., "BTC")
                - entry_price_cents: Entry price in cents
                - edge_pct: Expected edge percentage
                - confidence: Model confidence (0.0-1.0)
            correlation_matrix: Optional correlation matrix for risk adjustment
        
        Returns:
            Dict mapping asset symbols to optimal exposure in USD
        """
        if not opportunities:
            return {}
        
        # Use default correlation matrix if not provided
        if correlation_matrix is None:
            try:
                from merid.risk.correlation_matrix import get_correlation_matrix
                correlation_matrix = get_correlation_matrix()
            except Exception as e:
                logger.warning("[SLOT-ALLOCATOR] Failed to get correlation matrix: %s", e)
                # Fall back to identity matrix (no correlation)
                assets = [opp["asset"] for opp in opportunities]
                correlation_matrix = {asset: {a: 1.0 if asset == a else 0.0 for a in assets} for asset in assets}
        
        # Extract assets and expected returns
        assets = [opp["asset"] for opp in opportunities]
        n = len(assets)
        
        # Expected returns based on edge and confidence
        expected_returns = np.array([
            opp["edge_pct"] * opp["confidence"] for opp in opportunities
        ])
        
        # Build correlation matrix as numpy array
        corr_matrix = np.zeros((n, n))
        for i, asset_i in enumerate(assets):
            for j, asset_j in enumerate(assets):
                corr_matrix[i, j] = correlation_matrix.get(asset_i, {}).get(asset_j, 0.0)
        
        # Portfolio variance: w^T * Sigma * w
        # Using correlation matrix as proxy for covariance (simplified)
        def portfolio_variance(weights):
            return np.sqrt(weights.T @ corr_matrix @ weights)
        
        # Portfolio return: w^T * mu
        def portfolio_return(weights):
            return np.sum(weights * expected_returns)
        
        # Objective: Maximize Sharpe ratio (return / risk)
        def negative_sharpe_ratio(weights):
            portfolio_vol = portfolio_variance(weights)
            if portfolio_vol < 1e-6:
                return -portfolio_return(weights)  # Avoid division by zero
            return -portfolio_return(weights) / portfolio_vol
        
        # Constraints
        constraints = [
            # Sum of weights = 1 (full allocation of available capital)
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            # Each weight >= 0 (no short selling)
            {"type": "ineq", "fun": lambda w: w}
        ]
        
        # Initial guess: equal weights
        initial_weights = np.ones(n) / n
        
        # Bounds: 0 <= weight <= 1
        bounds = [(0.0, 1.0) for _ in range(n)]
        
        try:
            from scipy.optimize import minimize
            
            result = minimize(
                negative_sharpe_ratio,
                initial_weights,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 100, "ftol": 1e-6}
            )
            
            if result.success:
                optimal_weights = result.x
            else:
                logger.warning(
                    "[SLOT-ALLOCATOR] Optimization failed: %s, using equal weights",
                    result.message
                )
                optimal_weights = initial_weights
        except ImportError:
            logger.warning("[SLOT-ALLOCATOR] scipy not available, using equal weights")
            optimal_weights = initial_weights
        except Exception as e:
            logger.warning("[SLOT-ALLOCATOR] Optimization error: %s, using equal weights", e)
            optimal_weights = initial_weights
        
        # Convert weights to USD exposure based on available capital
        available_capital = self.get_available_exposure()
        optimal_exposure = {}
        
        for i, asset in enumerate(assets):
            # Exposure = weight * available_capital
            # But cap at opportunity's entry price (max 1 contract per trade)
            entry_price_usd = opportunities[i]["entry_price_cents"] / 100.0
            max_for_asset = min(optimal_weights[i] * available_capital, entry_price_usd)
            optimal_exposure[asset] = max_for_asset
        
        logger.info(
            "[SLOT-ALLOCATOR] Portfolio optimization: %d opportunities, "
            "available_capital=$%.2f, optimal_allocation=%s",
            n, available_capital, optimal_exposure
        )
        
        return optimal_exposure
    
    def suggest_allocations(
        self,
        opportunities: List[Dict[str, any]]
    ) -> List[Tuple[str, float, str]]:
        """
        Suggest which allocations to make based on portfolio optimization.
        
        Args:
            opportunities: List of opportunity dicts with keys:
                - asset: Asset symbol
                - entry_price_cents: Entry price in cents
                - edge_pct: Expected edge percentage
                - confidence: Model confidence
        
        Returns:
            List of (asset, suggested_exposure_usd, reason) tuples sorted by priority
        """
        if not opportunities:
            return []
        
        # Get optimal portfolio allocation
        optimal_exposure = self.optimize_portfolio_allocation(opportunities)
        
        # Build suggestions with priority based on edge * confidence
        suggestions = []
        for opp in opportunities:
            asset = opp["asset"]
            suggested = optimal_exposure.get(asset, 0.0)
            entry_price_usd = opp["entry_price_cents"] / 100.0
            
            # Priority score: edge * confidence
            priority = opp["edge_pct"] * opp["confidence"]
            
            if suggested >= entry_price_usd * 0.5:  # At least 50% of entry price
                reason = f"High priority (edge={opp['edge_pct']:.1%}, conf={opp['confidence']:.2f})"
                suggestions.append((asset, suggested, reason, priority))
            elif suggested > 0:
                reason = f"Medium priority (edge={opp['edge_pct']:.1%}, conf={opp['confidence']:.2f})"
                suggestions.append((asset, suggested, reason, priority))
        
        # Sort by priority (descending)
        suggestions.sort(key=lambda x: x[3], reverse=True)
        
        # Return without priority score
        return [(asset, exposure, reason) for asset, exposure, reason, _ in suggestions]


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
