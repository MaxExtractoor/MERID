"""
Window-Based Allocator for 15m Kalshi Crypto Trading

Implements a 15-minute portfolio allocator that sits above per-asset agents:
- Global budget: $1.00 per 15-minute window
- At most 1 contract per asset live at any time
- Greedy knapsack selection by edge ranking
- Window rollover logic aligned with Kalshi 15-minute markets

Architecture:
1. Per-asset signal generators (every 5s) output "candidates"
2. Global allocator (single-threaded critical section) filters, ranks, selects
3. Order execution router sends approved orders to Kalshi

This prevents spamming multiple contracts for the same asset and enforces
the $1 cap before orders reach the venue.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
from collections import deque
import heapq

from utils.logger import get_logger

logger = get_logger("merid.risk.profiles.window_allocator")


# =============================================================================
# Data Structures
# =============================================================================

class PendingOrderStatus(Enum):
    """Status of a pending order in the allocator."""
    PENDING = "pending"  # Submitted, waiting for ACK
    ACKED = "acked"  # Acknowledged by venue
    FILLED = "filled"  # Filled (moved to open_positions)
    REJECTED = "rejected"  # Rejected by venue
    CANCELLED = "cancelled"  # Cancelled
    TIMEOUT = "timeout"  # No response within timeout


@dataclass
class OpenPosition:
    """Tracks an open position in the current 15-minute window."""
    asset: str  # btc/eth/sol/xrp/doge
    contract_id: str  # Kalshi market id
    side: str  # "yes" or "no"
    entry_price: float  # Entry price in USD
    size: int  # Number of contracts (typically 1)
    opened_at: float  # Unix timestamp
    window_id: int  # 15-minute window ID


@dataclass
class PendingOrder:
    """Tracks an order that has been submitted but not yet confirmed."""
    order_id: str
    asset: str
    contract_id: str
    side: str
    price: float
    size: int
    status: PendingOrderStatus
    submitted_at: float
    window_id: int


@dataclass
class AssetState:
    """Per-asset state tracking."""
    asset: str
    open_position: Optional[OpenPosition] = None
    last_order_ts: float = 0.0  # Anti-spam/anti-duplicate
    last_fill_ts: float = 0.0
    pending_order: Optional[PendingOrder] = None


@dataclass
class Candidate:
    """A trading candidate from a per-asset agent."""
    asset: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    contract_id: str  # Kalshi market ticker
    edge: float  # Edge percentage (e.g., 0.012 for 1.2%)
    fair_price: float  # Fair price in USD
    target_price: float  # Target entry price in USD
    confidence: float  # Model confidence (0.0-1.0)
    agent_id: str  # Agent that generated this candidate
    timestamp: float = field(default_factory=time.time)
    
    @property
    def price_cents(self) -> int:
        """Price in cents for order submission."""
        return int(round(self.target_price * 100))
    
    @property
    def notional_usd(self) -> float:
        """Notional value in USD."""
        return self.target_price * 1  # Always 1 contract per order


@dataclass
class GlobalState:
    """Global allocation state keyed by 15-minute window."""
    total_cost_used: float = 0.0  # Sum of prices of all open positions
    remaining_budget: float = 1.0  # $1.00 - total_cost_used
    open_positions: Dict[str, OpenPosition] = field(default_factory=dict)  # asset -> OpenPosition
    pending_orders: Dict[str, PendingOrder] = field(default_factory=dict)  # asset -> PendingOrder
    last_window_id: int = 0
    window_start_ts: float = 0.0
    
    def reset_for_new_window(self, window_id: int) -> None:
        """Reset state for a new 15-minute window."""
        self.total_cost_used = 0.0
        self.remaining_budget = 1.0
        self.open_positions.clear()
        self.pending_orders.clear()
        self.last_window_id = window_id
        self.window_start_ts = time.time()
        logger.info(
            "[WINDOW-ALLOCATOR] Reset for new window_id=%d at ts=%.0f",
            window_id, self.window_start_ts
        )


# =============================================================================
# Window Allocator
# =============================================================================

class WindowAllocator:
    """
    15-minute portfolio allocator with global $1 budget and per-asset limits.
    
    Thread-safe singleton that:
    - Maintains global state per 15-minute window
    - Filters candidates by thresholds and constraints
    - Ranks candidates by edge
    - Selects budget-constrained subset (greedy knapsack)
    - Tracks pending orders to prevent double-fire
    """
    
    # Constants
    WINDOW_SECONDS = 900  # 15 minutes
    GLOBAL_BUDGET_USD = 1.00
    MIN_PRICE_CENTS = 10
    MAX_PRICE_CENTS = 75
    MAX_POSITIONS_PER_ASSET = 1
    ORDER_TIMEOUT_SECONDS = 30  # Timeout for pending orders
    
    # Singleton
    _instance: Optional[WindowAllocator] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._state_lock = threading.RLock()
        self._state = GlobalState()
        self._asset_states: Dict[str, AssetState] = {}
        
        # Candidate queue (thread-safe)
        self._candidate_queue: deque = deque()
        self._queue_lock = threading.Lock()
        
        # Statistics
        self._stats = {
            "candidates_received": 0,
            "candidates_dropped": 0,
            "candidates_selected": 0,
            "orders_submitted": 0,
            "orders_filled": 0,
            "orders_rejected": 0,
        }
        
        logger.info(
            "[WINDOW-ALLOCATOR] Initialized: budget=$%.2f, window=%ds, "
            "price_range=[%dc-%dc], max_positions_per_asset=%d",
            self.GLOBAL_BUDGET_USD, self.WINDOW_SECONDS,
            self.MIN_PRICE_CENTS, self.MAX_PRICE_CENTS,
            self.MAX_POSITIONS_PER_ASSET
        )
    
    def _get_current_window_id(self) -> int:
        """Get current 15-minute window ID."""
        return int(time.time() // self.WINDOW_SECONDS)
    
    def _check_window_rollover(self) -> bool:
        """Check if we need to roll over to a new window."""
        current_window_id = self._get_current_window_id()
        
        with self._state_lock:
            if current_window_id != self._state.last_window_id:
                logger.info(
                    "[WINDOW-ALLOCATOR] Window rollover: %d -> %d",
                    self._state.last_window_id, current_window_id
                )
                self._state.reset_for_new_window(current_window_id)
                
                # Reset asset states
                for asset_state in self._asset_states.values():
                    asset_state.open_position = None
                    asset_state.pending_order = None
                
                return True
        
        return False
    
    def _get_or_create_asset_state(self, asset: str) -> AssetState:
        """Get or create asset state."""
        with self._state_lock:
            if asset not in self._asset_states:
                self._asset_states[asset] = AssetState(asset=asset)
            return self._asset_states[asset]
    
    def _is_exit_order(self, candidate: Candidate) -> bool:
        """Check if candidate is an exit order."""
        # Exit orders are sell actions that close existing positions
        action_lower = candidate.action.lower()
        if action_lower != "sell":
            return False
        
        asset_state = self._get_or_create_asset_state(candidate.asset)
        return asset_state.open_position is not None
    
    def _filter_candidate(self, candidate: Candidate) -> Tuple[bool, str]:
        """
        Filter a candidate by thresholds and constraints.
        
        Returns:
            (allowed, reason) tuple
        """
        # Check window rollover
        self._check_window_rollover()
        
        # Exit orders bypass most checks (always allowed to close positions)
        if self._is_exit_order(candidate):
            return True, "exit_order"
        
        # Check price range
        price_cents = candidate.price_cents
        if price_cents < self.MIN_PRICE_CENTS:
            return False, f"price_below_min:{price_cents}c<{self.MIN_PRICE_CENTS}c"
        
        if price_cents > self.MAX_PRICE_CENTS:
            return False, f"price_above_max:{price_cents}c>{self.MAX_PRICE_CENTS}c"
        
        # Check per-asset position limit
        asset_state = self._get_or_create_asset_state(candidate.asset)
        
        if asset_state.open_position is not None:
            return False, f"asset_has_position:{candidate.asset}"
        
        if asset_state.pending_order is not None:
            # Check if pending order is stale (timeout)
            time_since_submit = time.time() - asset_state.pending_order.submitted_at
            if time_since_submit < self.ORDER_TIMEOUT_SECONDS:
                return False, f"pending_order_exists:{candidate.asset}"
            else:
                # Stale pending order - clear it
                logger.warning(
                    "[WINDOW-ALLOCATOR] Clearing stale pending order for %s: %.1fs old",
                    candidate.asset, time_since_submit
                )
                asset_state.pending_order = None
        
        # Check edge threshold (use unified 2.5% from profile edge_bands - industry standard)
        # 2026-07-14: Raised to 2.5% based on industry research (Market Math, Beatpoly)
        # Industry standard for Kalshi: 3% raw edge minimum
        # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
        if candidate.edge < 0.025:
            return False, f"edge_below_threshold:{candidate.edge:.4f}<0.025"
        
        # Check budget fit
        with self._state_lock:
            if candidate.notional_usd > self._state.remaining_budget:
                return False, f"insufficient_budget:${candidate.notional_usd:.2f}>${self._state.remaining_budget:.2f}"
        
        return True, "ok"
    
    def _rank_candidates(self, candidates: List[Candidate]) -> List[Candidate]:
        """
        Rank candidates by edge (descending) with tie-breakers.
        
        Tie-breakers (in order):
        1. Proximity to sweet spot price (40-60c)
        2. Confidence (higher is better)
        3. Diversity (prefer assets not yet traded this window)
        """
        def score(candidate: Candidate) -> float:
            """Primary score: edge (higher is better)."""
            return candidate.edge
        
        def tiebreaker(candidate: Candidate) -> Tuple[float, float, int]:
            """Tie-breaker score."""
            # 1. Price proximity to sweet spot (42c - midpoint of 10-75c canonical range)
            price_score = 1.0 - abs(candidate.target_price - 0.42) / 0.42
            
            # 2. Confidence
            conf_score = candidate.confidence
            
            # 3. Diversity (0 if asset already traded, 1 if not)
            asset_state = self._get_or_create_asset_state(candidate.asset)
            diversity_score = 0.0 if asset_state.open_position else 1.0
            
            return (price_score, conf_score, diversity_score)
        
        # Sort by edge descending, then by tie-breakers
        return sorted(
            candidates,
            key=lambda c: (-score(c), -tiebreaker(c)[0], -tiebreaker(c)[1], -tiebreaker(c)[2])
        )
    
    def _select_candidates(
        self,
        candidates: List[Candidate]
    ) -> List[Candidate]:
        """
        Select candidates using greedy knapsack under budget constraint.
        
        Algorithm:
        1. Start with remaining budget
        2. Iterate through ranked candidates
        3. Select if asset has no position and cost fits in budget
        4. Update budget after each selection
        """
        with self._state_lock:
            remaining_budget = self._state.remaining_budget
            selected = []
            
            for candidate in candidates:
                # Skip if asset already has position
                if candidate.asset in self._state.open_positions:
                    continue
                
                # Skip if asset has pending order
                if candidate.asset in self._state.pending_orders:
                    continue
                
                # Check budget fit
                cost = candidate.notional_usd
                if cost <= remaining_budget:
                    selected.append(candidate)
                    remaining_budget -= cost
                    logger.debug(
                        "[WINDOW-ALLOCATOR] Selected %s: edge=%.3f%%, price=$%.2f, "
                        "remaining_budget=$%.2f",
                        candidate.asset, candidate.edge * 100,
                        candidate.target_price, remaining_budget
                    )
            
            return selected
    
    def submit_candidate(self, candidate: Candidate) -> Tuple[bool, str]:
        """
        Submit a candidate to the allocator.
        
        This is the main entry point for per-asset agents.
        
        Args:
            candidate: Candidate from per-asset agent
            
        Returns:
            (accepted, reason) tuple
        """
        self._stats["candidates_received"] += 1
        
        # Filter candidate
        allowed, reason = self._filter_candidate(candidate)
        
        if not allowed:
            self._stats["candidates_dropped"] += 1
            logger.debug(
                "[WINDOW-ALLOCATOR] Dropped candidate %s: %s",
                candidate.asset, reason
            )
            return False, reason
        
        # Add to queue for batch processing
        with self._queue_lock:
            self._candidate_queue.append(candidate)
        
        return True, "queued"
    
    def process_candidates(self) -> List[Candidate]:
        """
        Process all queued candidates and return selected ones.
        
        This should be called on a 5-second cadence (or event-driven).
        
        Returns:
            List of selected candidates to convert to orders
        """
        # Check window rollover
        self._check_window_rollover()
        
        # Drain queue
        with self._queue_lock:
            candidates = list(self._candidate_queue)
            self._candidate_queue.clear()
        
        if not candidates:
            return []
        
        logger.info(
            "[WINDOW-ALLOCATOR] Processing %d candidates from queue",
            len(candidates)
        )
        
        # Rank candidates
        ranked = self._rank_candidates(candidates)
        
        # Select candidates (greedy knapsack)
        selected = self._select_candidates(ranked)
        
        self._stats["candidates_selected"] += len(selected)
        
        logger.info(
            "[WINDOW-ALLOCATOR] Selected %d/%d candidates for execution",
            len(selected), len(candidates)
        )
        
        return selected
    
    def record_order_submitted(self, candidate: Candidate, order_id: str) -> None:
        """Record that an order was submitted for a candidate."""
        asset_state = self._get_or_create_asset_state(candidate.asset)
        
        pending_order = PendingOrder(
            order_id=order_id,
            asset=candidate.asset,
            contract_id=candidate.contract_id,
            side=candidate.side,
            price=candidate.target_price,
            size=candidate.size if hasattr(candidate, 'size') else 1,
            status=PendingOrderStatus.PENDING,
            submitted_at=time.time(),
            window_id=self._get_current_window_id()
        )
        
        asset_state.pending_order = pending_order
        
        with self._state_lock:
            self._state.pending_orders[candidate.asset] = pending_order
        
        self._stats["orders_submitted"] += 1
        
        logger.info(
            "[WINDOW-ALLOCATOR] Order submitted: asset=%s order_id=%s price=$%.2f",
            candidate.asset, order_id, candidate.target_price
        )
    
    def record_order_filled(
        self,
        asset: str,
        order_id: str,
        fill_price: float,
        size: int = 1
    ) -> None:
        """Record that an order was filled."""
        asset_state = self._get_or_create_asset_state(asset)
        
        # Remove from pending orders
        if asset_state.pending_order:
            asset_state.pending_order.status = PendingOrderStatus.FILLED
        
        with self._state_lock:
            if asset in self._state.pending_orders:
                self._state.pending_orders[asset].status = PendingOrderStatus.FILLED
                del self._state.pending_orders[asset]
        
        # Create open position
        open_position = OpenPosition(
            asset=asset,
            contract_id=order_id,  # Use order_id as contract_id for tracking
            side="yes",  # Simplified - actual side from order
            entry_price=fill_price,
            size=size,
            opened_at=time.time(),
            window_id=self._get_current_window_id()
        )
        
        asset_state.open_position = open_position
        
        with self._state_lock:
            self._state.open_positions[asset] = open_position
            self._state.total_cost_used += fill_price * size
            self._state.remaining_budget = self.GLOBAL_BUDGET_USD - self._state.total_cost_used
        
        asset_state.last_fill_ts = time.time()
        self._stats["orders_filled"] += 1
        
        logger.info(
            "[WINDOW-ALLOCATOR] Order filled: asset=%s price=$%.2f "
            "total_exposure=$%.2f remaining=$%.2f",
            asset, fill_price, self._state.total_cost_used,
            self._state.remaining_budget
        )
    
    def record_order_rejected(self, asset: str, order_id: str) -> None:
        """Record that an order was rejected."""
        asset_state = self._get_or_create_asset_state(asset)
        
        # Remove from pending orders
        if asset_state.pending_order:
            asset_state.pending_order.status = PendingOrderStatus.REJECTED
            asset_state.pending_order = None
        
        with self._state_lock:
            if asset in self._state.pending_orders:
                self._state.pending_orders[asset].status = PendingOrderStatus.REJECTED
                del self._state.pending_orders[asset]
        
        self._stats["orders_rejected"] += 1
        
        logger.warning(
            "[WINDOW-ALLOCATOR] Order rejected: asset=%s order_id=%s",
            asset, order_id
        )
    
    def get_state(self) -> Dict:
        """Get current allocator state for monitoring."""
        with self._state_lock:
            return {
                "window_id": self._state.last_window_id,
                "total_cost_used": self._state.total_cost_used,
                "remaining_budget": self._state.remaining_budget,
                "open_positions": {
                    asset: {
                        "contract_id": pos.contract_id,
                        "entry_price": pos.entry_price,
                        "size": pos.size,
                        "opened_at": pos.opened_at,
                    }
                    for asset, pos in self._state.open_positions.items()
                },
                "pending_orders": {
                    asset: {
                        "order_id": order.order_id,
                        "status": order.status.value,
                        "submitted_at": order.submitted_at,
                    }
                    for asset, order in self._state.pending_orders.items()
                },
                "stats": self._stats.copy(),
            }


# =============================================================================
# Singleton Accessor
# =============================================================================

def get_window_allocator() -> WindowAllocator:
    """Get the window allocator singleton."""
    return WindowAllocator()
