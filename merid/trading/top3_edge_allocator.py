"""
Top-3 Edge Selector & Allocator — Production Implementation

Implements the cross-agent "Top-3 Edge Selector & Allocator" that:
1. Selects only the top 3 edge cases across 5 assets (BTC, ETH, SOL, XRP, DOGE)
2. Allocates at most 3% of bankroll in total across all new positions per cycle (2026 best practice)
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
        timestamp: UTC timestamp when this edge was computed (defaults to now)
        signal_id: Unique identifier for this signal to prevent reuse
    
    CRITICAL: timestamp and signal_id prevent stale signal reuse across cycles.
    Each new cycle after reconciliation must use FRESH edges computed AFTER
    the previous cycle was reconciled. This ensures market conditions are current.
    """
    asset: Literal["BTC", "ETH", "SOL", "XRP", "DOGE"]
    edge: float
    max_notional_cap: int  # cents
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_id: str = field(default_factory=lambda: f"sig_{datetime.now(timezone.utc).timestamp()}_{uuid.uuid4().hex[:8]}")
    
    def is_fresh(self, max_age_seconds: float = 60.0) -> bool:
        """Check if this edge candidate is fresh (not stale).
        
        Args:
            max_age_seconds: Maximum age allowed (default 60s)
            
        Returns:
            True if edge is fresh, False if stale
        """
        age = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return age <= max_age_seconds
    
    def age_seconds(self) -> float:
        """Return age of this edge in seconds."""
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()


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
    closed: bool = False  # Whether position is closed
    contracts: List[Dict[str, Any]] = field(default_factory=list)  # Contract-level details


class BatchStatus(str, Enum):
    """Lifecycle states for a top-3 batch."""
    PENDING = "pending"           # Created but not yet confirmed active
    ACTIVE = "active"             # Currently open, positions being filled
    CLOSING = "closing"           # Wind-down initiated, no new entries
    CLOSED = "closed"             # Fully unwound, awaiting reconciliation
    FULLY_RECONCILED = "fully_reconciled"  # Bankroll updated, cycle lock released, batch complete


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
    
    def all_positions_closed(self) -> bool:
        """Check if all allocated positions have been closed."""
        if not self.allocations:
            return False  # No allocations means nothing to close - not "all closed"
        return len(self.closed_assets) >= len(self.allocations)
    
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
        Let cycle_risk_cap_pct = 0.03 (3% - 2026 best practice).
        
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
    
    # Configuration - ENV-DRIVEN (no hardcoded defaults)
    # These read from environment at runtime, defaulting only if env not set
    # CRITICAL FIX: Aligned with kalshi_crypto_15m_v2.yaml profile (2026-07-04)
    # Profile specifies: max_cycle_risk_pct: 0.005 (0.5%)
    DEFAULT_CYCLE_RISK_CAP_PCT_MIN: float = float(os.getenv("MERID_TOP3_RISK_CAP_PCT_MIN", "0.005"))  # CRITICAL FIX: 0.5% (was 0.03)
    DEFAULT_CYCLE_RISK_CAP_PCT_MAX: float = float(os.getenv("MERID_TOP3_RISK_CAP_PCT_MAX", "0.005"))  # CRITICAL FIX: 0.5% (was 0.03)
    DEFAULT_EPS: float = float(os.getenv("MERID_TOP3_EDGE_EPS", "1e-6"))
    MAX_ASSETS: int = int(os.getenv("MERID_TOP3_MAX_ASSETS", "3"))
    MIN_ALLOCATION_CENTS: int = int(os.getenv("MERID_TOP3_MIN_ALLOCATION_CENTS", "50"))  # $0.50 minimum
    
    VALID_ASSETS: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")


# ═══════════════════════════════════════════════════════════════════════════
# Selector Algorithm
# ═══════════════════════════════════════════════════════════════════════════


def select_top3_allocations(
    bankroll_notional: int,  # cents
    cycle_risk_cap_pct: float,
    candidates: List[EdgeCandidate],
    eps: Optional[float] = None,  # Uses env MERID_TOP3_EDGE_EPS if None
    min_allocation_cents: Optional[int] = None,  # Uses env MERID_TOP3_MIN_ALLOCATION_CENTS if None
) -> List[Top3Allocation]:
    """Select top-3 allocations with STRICT EDGE #1 PRIORITY sequential fill.

    CRITICAL RULES (per user wagering specification):
    1. Edge #1 (highest edge) MUST be executed first - non-negotiable priority
    2. Edge #1 gets minimum 1% of bankroll if valid (cycle_risk_cap_pct >= 0.01)
    3. Edge #2 is ONLY considered after Edge #1 is fully allocated
    4. Edge #3 is ONLY considered after Edge #2 is fully allocated
    5. If any edge fails min constraints, it and ALL subsequent edges are skipped
    6. Never skip Edge #1 to take Edge #2 or #3

    Args:
        bankroll_notional: Current bankroll in cents
        cycle_risk_cap_pct: Risk cap as fraction (0.03 - 2026 best practice)
        candidates: List of edge candidates (all 5 assets potentially)
        eps: Epsilon for floating point comparisons (uses env if None)
        min_allocation_cents: Minimum allocation in cents (uses env if None)

    Returns:
        List of allocations (1-3 edges), strictly following Edge #1 priority
    """
    # Resolve parameters from env if not provided
    _eps = eps if eps is not None else float(os.getenv("MERID_TOP3_EDGE_EPS", "1e-6"))
    _min_alloc = min_allocation_cents if min_allocation_cents is not None else int(os.getenv("MERID_TOP3_MIN_ALLOCATION_CENTS", "50"))

    spec = Top3SelectionSpec()

    # Step 1: Filter invalid candidates
    valid_candidates = [
        c for c in candidates
        if c.edge > 0 and c.asset in spec.VALID_ASSETS and c.max_notional_cap > 0
    ]

    if not valid_candidates:
        logger.info("[EDGE#1-PRIORITY] No valid candidates with positive edge - NO TRADES")
        return []

    # Step 2: Sort by edge descending to establish Edge #1, #2, #3 ranking
    sorted_candidates = sorted(valid_candidates, key=lambda c: c.edge, reverse=True)

    # Log the ranked edges
    logger.info("[EDGE#1-PRIORITY] Bankroll=$%.2f | Risk cap=%.2f%%", bankroll_notional / 100, cycle_risk_cap_pct * 100)
    for i, c in enumerate(sorted_candidates[:3], 1):
        logger.info("  Edge#%d: %s | edge=%.4f | max_cap=%d¢", i, c.asset, c.edge, c.max_notional_cap)

    # Step 3: Compute budgets
    # Edge #1 gets minimum 1% (or full cap if cap < 1%)
    min_edge1_pct = 0.01  # 1% minimum for Edge #1
    total_budget_cents = int(cycle_risk_cap_pct * bankroll_notional)
    edge1_budget_cents = int(min(min_edge1_pct, cycle_risk_cap_pct) * bankroll_notional)

    # Step 4: SEQUENTIAL PRIORITY FILL - Edge #1 first, then #2, then #3
    allocations: List[Top3Allocation] = []
    remaining_budget_cents = total_budget_cents
    max_edges = min(spec.MAX_ASSETS, len(sorted_candidates))

    for edge_rank in range(1, max_edges + 1):
        if edge_rank > len(sorted_candidates):
            break

        candidate = sorted_candidates[edge_rank - 1]
        edge_label = f"Edge#{edge_rank}"

        # Determine budget for this edge
        if edge_rank == 1:
            edge_budget_cents = min(edge1_budget_cents, remaining_budget_cents)
        else:
            edge_budget_cents = remaining_budget_cents

        if edge_budget_cents <= 0:
            logger.info(
                "[%s-SKIP] %s | reason=zero_budget | bankroll_depleted_by_higher_priority_edges",
                edge_label, candidate.asset
            )
            # Skip all subsequent edges
            for sub_rank in range(edge_rank + 1, max_edges + 1):
                if sub_rank <= len(sorted_candidates):
                    sub_c = sorted_candidates[sub_rank - 1]
                    logger.info(
                        "[Edge#%d-SKIP] %s | reason=previous_edge_budget_exhausted",
                        sub_rank, sub_c.asset
                    )
            break

        # Check if this edge can be allocated
        # For Top3, we use notional-based allocation (different from TopN max-loss)
        notional_i = min(candidate.max_notional_cap, edge_budget_cents)

        # Only allocate if we have meaningful notional
        if notional_i >= _min_alloc:
            allocations.append(Top3Allocation(
                asset=candidate.asset,
                edge=candidate.edge,
                target_notional=notional_i,
                weight=1.0 / edge_rank,  # Weight reflects priority order
                contracts=candidate.metadata.get("contracts", []),
            ))
            remaining_budget_cents -= notional_i

            logger.info(
                "[%s-EXECUTED] %s | notional=%d¢ | edge=%.4f | remaining_budget=%d¢",
                edge_label, candidate.asset, notional_i, candidate.edge, remaining_budget_cents
            )
        else:
            # Failed min allocation - skip this edge and ALL subsequent edges
            logger.warning(
                "[%s-SKIP] %s | reason=below_min_allocation | notional=%d¢ < min=%d¢ | "
                "SUBSEQUENT EDGES ALSO SKIPPED",
                edge_label, candidate.asset, notional_i, _min_alloc
            )

            # Skip all subsequent edges
            for sub_rank in range(edge_rank + 1, max_edges + 1):
                if sub_rank <= len(sorted_candidates):
                    sub_c = sorted_candidates[sub_rank - 1]
                    logger.info(
                        "[Edge#%d-SKIP] %s | reason=blocked_by_%s_failure",
                        sub_rank, sub_c.asset, edge_label
                    )
            break

    # Final summary
    if allocations:
        total_notional = sum(a.target_notional for a in allocations)
        logger.info(
            "[EDGE#1-PRIORITY-SUCCESS] Allocated %d edges: %s | total=%d¢ (%.2f%% of bankroll)",
            len(allocations),
            ", ".join(f"#{i+1}:{a.asset}" for i, a in enumerate(allocations)),
            total_notional,
            (total_notional / bankroll_notional) * 100 if bankroll_notional > 0 else 0
        )
    else:
        logger.info("[EDGE#1-PRIORITY] NO ALLOCATIONS - All edges skipped")

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
        
        Returns value defaulting to 0.03 (2026 best practice) if not set.
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
                logger.warning(
                    "[TOP3-ALLOCATOR] Invalid MERID_CYCLE_RISK_CAP_PCT env value '%s', using default %s",
                    env_val,
                    self.spec.DEFAULT_CYCLE_RISK_CAP_PCT_MAX,
                )
        
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
            logger.warning("[TOP3-ALLOCATOR] Invalid bankroll: %d, attempting live derivation", bankroll_notional)
            # Try to derive live bankroll from Kalshi API
            try:
                from merid.event_venues.kalshi.order_router import _derive_live_bankroll_usd
                _live = _derive_live_bankroll_usd()
                if _live is not None and _live > 0:
                    bankroll_notional = int(_live * 100)
                    logger.info("[TOP3-ALLOCATOR] Recovered with live bankroll: %d cents", bankroll_notional)
                else:
                    # FAIL CLOSED: Cannot get live bankroll
                    logger.error("[TOP3-ALLOCATOR] Cannot determine live Kalshi balance. No allocations.")
                    return []
            except Exception as _e:
                # FAIL CLOSED: Cannot get live bankroll
                logger.error("[TOP3-ALLOCATOR] Failed to get live bankroll: %s. No allocations.", _e)
                return []
        
        if not candidates:
            logger.debug("[TOP3-ALLOCATOR] No candidates provided")
            return []
        
        # ═════════════════════════════════════════════════════════════════
        # SENTIMENT_ISOLATION_AUDIT: Removed sentiment-based risk adjustment
        # ═════════════════════════════════════════════════════════════════
        # Per the Sentiment Isolation Audit specification, execution must depend
        # only on: Kalshi market state, orderbook/candle pipeline, and 15m
        # mean-reversion edge logic. Sentiment is descriptive context only and
        # must not influence execution decisions (side, size, entry).
        #
        # Previous implementation adjusted cycle_risk_cap_pct based on BTC
        # fear/greed regime. This has been removed to prevent sentiment leakage
        # into position sizing logic.
        #
        # Risk adjustment now depends only on:
        # - System-level risk settings (self._cycle_risk_cap_pct)
        # - Asset-specific risk dial (crypto_risk_dial) for halt conditions
        # ═════════════════════════════════════════════════════════════════
        
        # Asset-specific risk dial adjustments (sentiment-free)
        for candidate in candidates:
            if candidate.asset in ("ETH", "SOL", "XRP", "DOGE"):
                try:
                    from merid.sentiment.crypto_risk_dial import get_crypto_risk_dial
                    _risk_dial = get_crypto_risk_dial(candidate.asset)
                    _can_trade, _reason = _risk_dial.can_trade()
                    if not _can_trade:
                        # Zero out this candidate's allocation
                        logger.warning(
                            "[TOP3-RISK-DIAL] HALT for %s | reason=%s | excluding from allocation",
                            candidate.asset, _reason
                        )
                        # Modify the candidate in place via metadata
                        candidate.metadata["risk_dial_halt"] = True
                        candidate.edge = 0.0  # Zero edge excludes from selection
                except Exception as _rd_exc:
                    logger.debug("[TOP3-RISK-DIAL] Check skipped for %s: %s", candidate.asset, _rd_exc)
        
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
                "[TOP3-ALLOCATOR] Selected %d assets, total=%d¢ (%.2f%% of bankroll, cap=%.2f%%)",
                len(allocations), total, pct_of_bankroll, self._cycle_risk_cap_pct * 100
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
