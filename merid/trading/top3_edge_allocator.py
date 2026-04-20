"""
Top-3 Edge Selector & Allocator — Production Implementation

Implements the cross-agent "Top-3 Edge Selector & Allocator" that:
1. Selects only the top 3 edge cases across 5 assets (BTC, ETH, SOL, XRP, DOGE)
2. Allocates at most 1-2% of bankroll in total across all new positions per cycle
3. Dynamically sizes positions by relative edge (highest edge gets largest size)
4. Enforces a position batch regime: no new trades until current top-3 are closed

Invariants (see Top3SelectionSpec class docstring for formal contract):
- len(selected_assets(t)) <= 3
- sum(position_notional_for_new_entries(t)) <= cycle_risk_cap_pct * bankroll_notional(t)
- At most one "open batch" can be ACTIVE at any time

Uses existing infrastructure:
- CacheAdapter (Redis + in-memory) for batch state persistence
- BankrollManager/KalshiRiskEngine for bankroll tracking
- Existing agent grid for execution
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EdgeCandidate:
    """A candidate asset with computed edge for selection.
    
    Args:
        asset: One of the 5 crypto assets
        edge: Expected edge (model probability - market implied probability)
        max_notional_cap: Per-asset cap from existing risk models (in cents)
        metadata: Contract details (ticker, expiry, etc.)
    """
    asset: Literal["BTC", "ETH", "SOL", "XRP", "DOGE"]
    edge: float
    max_notional_cap: int  # cents
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Top3Allocation:
    """Single asset allocation within a top-3 batch.
    
    Args:
        asset: Selected asset
        edge: Edge value used for ranking
        target_notional: Target notional in cents
        weight: Relative weight (edge / sum(edges))
    """
    asset: str
    edge: float
    target_notional: int  # cents
    weight: float
    contracts: List[Dict[str, Any]] = field(default_factory=list)  # Contract-level details


class BatchStatus(str, Enum):
    """Lifecycle states for a top-3 batch."""
    PENDING = "pending"      # Created but not yet confirmed active
    ACTIVE = "active"        # Currently open, positions being filled
    CLOSING = "closing"      # Positions being closed/exited
    CLOSED = "closed"        # All positions resolved, batch complete


@dataclass
class Top3Batch:
    """A batch of top-3 allocations.
    
    Args:
        batch_id: Unique identifier
        status: Current lifecycle status
        cycle_ts: When the batch was created
        allocations: List of asset allocations
        total_target_notional: Sum of all allocation targets
        cycle_risk_cap_pct: The risk cap used for this batch
        bankroll_at_creation: Bankroll value when batch was created
    """
    batch_id: str
    status: BatchStatus
    cycle_ts: datetime
    allocations: List[Top3Allocation]
    total_target_notional: int  # cents
    cycle_risk_cap_pct: float
    bankroll_at_creation: int  # cents
    
    # Track which assets have been filled/closed
    filled_assets: set = field(default_factory=set)
    closed_assets: set = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for persistence."""
        return {
            "batch_id": self.batch_id,
            "status": self.status.value,
            "cycle_ts": self.cycle_ts.isoformat(),
            "allocations": [
                {
                    "asset": a.asset,
                    "edge": a.edge,
                    "target_notional": a.target_notional,
                    "weight": a.weight,
                    "contracts": a.contracts,
                }
                for a in self.allocations
            ],
            "total_target_notional": self.total_target_notional,
            "cycle_risk_cap_pct": self.cycle_risk_cap_pct,
            "bankroll_at_creation": self.bankroll_at_creation,
            "filled_assets": list(self.filled_assets),
            "closed_assets": list(self.closed_assets),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Top3Batch":
        """Deserialize from dict."""
        allocations = [
            Top3Allocation(
                asset=a["asset"],
                edge=a["edge"],
                target_notional=a["target_notional"],
                weight=a["weight"],
                contracts=a.get("contracts", []),
            )
            for a in data.get("allocations", [])
        ]
        return cls(
            batch_id=data["batch_id"],
            status=BatchStatus(data.get("status", "pending")),
            cycle_ts=datetime.fromisoformat(data["cycle_ts"]),
            allocations=allocations,
            total_target_notional=data.get("total_target_notional", 0),
            cycle_risk_cap_pct=data.get("cycle_risk_cap_pct", 0.01),
            bankroll_at_creation=data.get("bankroll_at_creation", 0),
            filled_assets=set(data.get("filled_assets", [])),
            closed_assets=set(data.get("closed_assets", [])),
        )
    
    def is_asset_allowed(self, asset: str) -> bool:
        """Check if asset is in this batch's allocations."""
        return any(a.asset == asset for a in self.allocations)
    
    def get_allocation_for_asset(self, asset: str) -> Optional[Top3Allocation]:
        """Get allocation for specific asset."""
        for a in self.allocations:
            if a.asset == asset:
                return a
        return None
    
    def all_positions_closed(self) -> bool:
        """Check if all allocated assets have been closed."""
        allocated_assets = {a.asset for a in self.allocations}
        return allocated_assets.issubset(self.closed_assets)
    
    def can_create_new_batch(self) -> bool:
        """Check if this batch allows a new batch to be created."""
        return self.status in (BatchStatus.CLOSED,) or (
            self.status == BatchStatus.ACTIVE and self.all_positions_closed()
        )


# ═══════════════════════════════════════════════════════════════════════════
# Selection Specification (Formal Contract)
# ═══════════════════════════════════════════════════════════════════════════


class Top3SelectionSpec:
    """Formal specification of the top-3 selection invariants.
    
    This is the ground truth for implementation and tests.
    
    Invariant 1 (Top-3 asset selection):
        On each decision cycle t, compute candidate edges E_a(t) for each
        asset a ∈ {BTC, ETH, SOL, XRP, DOGE}. Rank assets by edge descending
        and select at most 3 assets with strictly positive, valid edges.
        
        Formal: len(selected_assets(t)) <= 3
        
    Invariant 2 (Bankroll allocation cap per cycle):
        Let bankroll_notional(t) be live account equity (or configured bankroll).
        Let cycle_risk_cap_pct ∈ [0.01, 0.02] (1-2%).
        
        Formal: sum(position_notional_for_new_entries(t)) <= cycle_risk_cap_pct * bankroll_notional(t)
        
    Invariant 3 (Dynamic size by relative edge):
        Given 3 selected edges [e_1, e_2, e_3] > 0:
        - Compute weights w_i = e_i / (e_1 + e_2 + e_3)
        - Compute notional_i = total_cycle_notional * w_i
        If edges equal (within epsilon), split notional evenly.
        
        Formal: sum(notional_i) == total_cycle_notional (within rounding)
        
    Invariant 4 (Batch regime - no overlapping batches):
        Define a batch id per top-3 selection cycle. Once a batch is opened,
        no new entries allowed until all batch positions are closed/resolved
        AND a new top-3 computation is performed with fresh state.
        
        Formal: at most one "open batch" in status ACTIVE at any time;
                new batch creation requires prior batch CLOSED
                
    Invariant 5 (System-wide alignment):
        All agents receive top-down directives from a single selector.
        No agent may open new positions unless explicitly allowed by batch.
        
        Formal: new_entry_allowed(agent_a) iff batch.exists AND batch.contains(asset_a)
    """
    
    # Configuration defaults
    DEFAULT_CYCLE_RISK_CAP_PCT_MIN: float = 0.01  # 1%
    DEFAULT_CYCLE_RISK_CAP_PCT_MAX: float = 0.02  # 2%
    DEFAULT_EPS: float = 1e-6  # For edge equality comparison
    MAX_ASSETS: int = 3
    
    VALID_ASSETS: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")


# ═══════════════════════════════════════════════════════════════════════════
# Selector Algorithm
# ═══════════════════════════════════════════════════════════════════════════


def select_top3_allocations(
    bankroll_notional: int,  # cents
    cycle_risk_cap_pct: float,
    candidates: List[EdgeCandidate],
    eps: float = 1e-6,
) -> List[Top3Allocation]:
    """Select top-3 allocations by edge with proportional sizing.
    
    Args:
        bankroll_notional: Current bankroll in cents
        cycle_risk_cap_pct: Risk cap as fraction (0.01-0.02)
        candidates: List of edge candidates (all 5 assets potentially)
        eps: Epsilon for floating point comparisons
        
    Returns:
        List of up to 3 allocations, sorted by edge descending
        
    Implements the algorithm from Top3SelectionSpec:
    1. Filter out candidates with edge <= 0 or invalid
    2. Sort by edge descending
    3. Take at most 3: top = sorted_candidates[:3]
    4. Compute total_cycle_notional = min(cap * bankroll, sum(max_notional_cap_i))
    5. If total_cycle_notional <= 0, return empty
    6. Compute edge weights (equal split if edges within eps)
    7. Return allocations
    """
    spec = Top3SelectionSpec()
    
    # Step 1: Filter invalid candidates
    valid_candidates = [
        c for c in candidates 
        if c.edge > 0 and c.asset in spec.VALID_ASSETS and c.max_notional_cap > 0
    ]
    
    if not valid_candidates:
        logger.debug("[TOP3-SELECT] No valid candidates with positive edge")
        return []
    
    # Step 2: Sort by edge descending
    sorted_candidates = sorted(valid_candidates, key=lambda c: c.edge, reverse=True)
    
    # Step 3: Take at most 3
    top = sorted_candidates[:spec.MAX_ASSETS]
    
    # Step 4: Compute total cycle notional (respect caps)
    max_possible_notional = sum(c.max_notional_cap for c in top)
    cap_notional = int(cycle_risk_cap_pct * bankroll_notional)
    total_cycle_notional = min(cap_notional, max_possible_notional)
    
    # Step 5: Check if we have any notional to allocate
    if total_cycle_notional <= 0:
        logger.debug("[TOP3-SELECT] Total cycle notional is zero (cap=%d, max_possible=%d)",
                     cap_notional, max_possible_notional)
        return []
    
    # Step 6: Compute edge weights
    edges = [c.edge for c in top]
    edge_sum = sum(edges)
    
    # Check if all edges are equal (within epsilon)
    max_edge = max(edges)
    min_edge = min(edges)
    edges_equal = (max_edge - min_edge) < eps
    
    allocations: List[Top3Allocation] = []
    
    if edges_equal:
        # Equal split among tied edges
        notional_per_asset = total_cycle_notional // len(top)
        remainder = total_cycle_notional - (notional_per_asset * len(top))
        
        for i, candidate in enumerate(top):
            # Distribute remainder to first assets
            extra = 1 if i < remainder else 0
            allocations.append(Top3Allocation(
                asset=candidate.asset,
                edge=candidate.edge,
                target_notional=notional_per_asset + extra,
                weight=1.0 / len(top),
                contracts=candidate.metadata.get("contracts", []),
            ))
        
        logger.info(
            "[TOP3-SELECT] Equal split for %d assets (edges ~%.6f), notional=%d each",
            len(top), edges[0], notional_per_asset
        )
    else:
        # Proportional by edge
        remaining_notional = total_cycle_notional
        
        for i, candidate in enumerate(top):
            is_last = (i == len(top) - 1)
            
            if is_last:
                # Last asset gets remainder to ensure sum equals total
                notional_i = remaining_notional
            else:
                # Weighted allocation
                weight = candidate.edge / edge_sum
                notional_i = int(total_cycle_notional * weight)
                # Clamp to per-asset cap
                notional_i = min(notional_i, candidate.max_notional_cap)
            
            allocations.append(Top3Allocation(
                asset=candidate.asset,
                edge=candidate.edge,
                target_notional=notional_i,
                weight=candidate.edge / edge_sum,
                contracts=candidate.metadata.get("contracts", []),
            ))
            
            remaining_notional -= notional_i
        
        logger.info(
            "[TOP3-SELECT] Weighted split: %s",
            ", ".join(f"{a.asset}={a.target_notional}c (w={a.weight:.2f})" for a in allocations)
        )
    
    return allocations


# ═══════════════════════════════════════════════════════════════════════════
# Top3EdgeAllocator (Main Component)
# ═══════════════════════════════════════════════════════════════════════════


class Top3EdgeAllocator:
    """Cross-agent top-3 edge selector and allocator.
    
    This is the ONLY place where cross-asset selection and sizing logic lives.
    All agents must query this component before opening new positions.
    
    Usage:
        allocator = Top3EdgeAllocator()
        
        # Create candidates from your computed edges
        candidates = [
            EdgeCandidate("BTC", edge=0.08, max_notional_cap=500),
            EdgeCandidate("ETH", edge=0.06, max_notional_cap=400),
            ...
        ]
        
        # Compute allocations
        allocations = allocator.compute_allocations(
            bankroll_notional=bankroll_cents,
            candidates=candidates
        )
        
        # allocations now contains up to 3 assets with target notionals
    """
    
    def __init__(self):
        self.spec = Top3SelectionSpec()
        self._cycle_risk_cap_pct = self._load_cycle_risk_cap_pct()
    
    def _load_cycle_risk_cap_pct(self) -> float:
        """Load cycle risk cap from environment/config.
        
        Returns value in [0.01, 0.02] defaulting to 0.02 if not set.
        """
        env_val = os.getenv("TOP3_CYCLE_RISK_CAP_PCT", "")
        if env_val:
            try:
                pct = float(env_val)
                # Clamp to valid range
                return max(
                    self.spec.DEFAULT_CYCLE_RISK_CAP_PCT_MIN,
                    min(pct, self.spec.DEFAULT_CYCLE_RISK_CAP_PCT_MAX)
                )
            except ValueError:
                pass
        
        # Default to 2%
        return self.spec.DEFAULT_CYCLE_RISK_CAP_PCT_MAX
    
    def compute_allocations(
        self,
        bankroll_notional: int,
        candidates: List[EdgeCandidate],
    ) -> List[Top3Allocation]:
        """Compute top-3 allocations given bankroll and candidates.
        
        This is a pure function - no side effects, no state changes.
        For stateful batch management, use Top3BatchManager.
        
        Args:
            bankroll_notional: Current bankroll in cents
            candidates: List of edge candidates (typically 5 assets)
            
        Returns:
            List of up to 3 allocations with target notionals
        """
        if bankroll_notional <= 0:
            logger.warning("[TOP3-ALLOCATOR] Invalid bankroll: %d", bankroll_notional)
            return []
        
        if not candidates:
            logger.debug("[TOP3-ALLOCATOR] No candidates provided")
            return []
        
        allocations = select_top3_allocations(
            bankroll_notional=bankroll_notional,
            cycle_risk_cap_pct=self._cycle_risk_cap_pct,
            candidates=candidates,
            eps=self.spec.DEFAULT_EPS,
        )
        
        # Log the selection
        if allocations:
            total = sum(a.target_notional for a in allocations)
            pct_of_bankroll = (total / bankroll_notional) * 100
            logger.info(
                "[TOP3-ALLOCATOR] Selected %d assets, total=%d¢ (%.2f%% of bankroll)",
                len(allocations), total, pct_of_bankroll
            )
        else:
            logger.info("[TOP3-ALLOCATOR] No allocations selected")
        
        return allocations
    
    def get_cycle_risk_cap_pct(self) -> float:
        """Get current cycle risk cap percentage."""
        return self._cycle_risk_cap_pct
    
    def validate_invariants(self, allocations: List[Top3Allocation], bankroll: int) -> bool:
        """Validate that allocations respect all invariants.
        
        Returns True if valid, logs warnings and returns False if invalid.
        """
        spec = Top3SelectionSpec()
        
        # Invariant 1: At most 3 assets
        if len(allocations) > spec.MAX_ASSETS:
            logger.error(
                "[TOP3-INVARIANT-VIOLATION] Too many assets: %d > %d",
                len(allocations), spec.MAX_ASSETS
            )
            return False
        
        # Invariant 2: Total notional within cap
        total = sum(a.target_notional for a in allocations)
        max_allowed = int(self._cycle_risk_cap_pct * bankroll)
        if total > max_allowed:
            logger.error(
                "[TOP3-INVARIANT-VIOLATION] Notional exceeds cap: %d > %d (%.2f%% of bankroll)",
                total, max_allowed, self._cycle_risk_cap_pct * 100
            )
            return False
        
        # All invariants satisfied
        return True


# Singleton instance
_allocator_instance: Optional[Top3EdgeAllocator] = None


def get_top3_allocator() -> Top3EdgeAllocator:
    """Get singleton Top3EdgeAllocator instance."""
    global _allocator_instance
    if _allocator_instance is None:
        _allocator_instance = Top3EdgeAllocator()
    return _allocator_instance
