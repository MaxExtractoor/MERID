"""
Top-N Edge Allocator — Production Implementation with Fixed Fractional Risk

Implements the cross-agent "Top-N Edge Selector & Allocator" that:
1. Selects top N edges across 5 assets (BTC, ETH, SOL, XRP, DOGE) with N dynamically determined
2. Allocates at most 1-2% of bankroll in TOTAL across all new positions per cycle (fixed fractional)
3. Dynamically steps down N (3→2→1→0) based on affordability and risk constraints
4. Sizes positions by max loss per trade, respecting stop distances
5. Enforces min contracts and notional constraints

Key invariants:
- len(selected_assets) ∈ {0, 1, 2, 3} determined by affordability
- sum(max_loss_usd for selected) ≤ cycle_risk_usd (hard cap)
- Each trade ≥ min_contracts and ≥ min_notional_usd
- All trades route through this allocator (no bypasses)

Reference: https://www.quantifiedstrategies.com/fixed-fractional-method-money-management/
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TopNAllocatorConfig:
    """Configuration for Top-N Edge Allocator.
    
    All percentage fields are in decimal form (e.g., 0.01 = 1%).
    """
    # Risk budget per cycle (fixed fractional)
    min_cycle_risk_pct: float = 0.01  # 1% minimum
    max_cycle_risk_pct: float = 0.02  # 2% maximum
    
    # Dynamic N limits
    max_edges_per_cycle: int = 3
    min_edges_per_cycle: int = 0
    
    # Sizing constraints
    min_contracts: int = 1  # Minimum contracts per trade
    min_notional_usd: float = 1.00  # Minimum $1.00 per trade
    
    # Edge tie handling
    edge_epsilon: float = 1e-6  # Edges within this are considered equal
    
    # Max loss calculation
    default_stop_distance_pct: float = 0.02  # 2% default stop if not provided
    
    # Valid assets
    valid_assets: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")
    
    @classmethod
    def from_env(cls) -> "TopNAllocatorConfig":
        """Load configuration from environment variables."""
        return cls(
            min_cycle_risk_pct=float(os.getenv("TOPN_MIN_CYCLE_RISK_PCT", "0.01")),
            max_cycle_risk_pct=float(os.getenv("TOPN_MAX_CYCLE_RISK_PCT", "0.02")),
            max_edges_per_cycle=int(os.getenv("TOPN_MAX_EDGES", "3")),
            min_edges_per_cycle=int(os.getenv("TOPN_MIN_EDGES", "0")),
            min_contracts=int(os.getenv("TOPN_MIN_CONTRACTS", "1")),
            min_notional_usd=float(os.getenv("TOPN_MIN_NOTIONAL_USD", "1.00")),
            edge_epsilon=float(os.getenv("TOPN_EDGE_EPSILON", "1e-6")),
            default_stop_distance_pct=float(os.getenv("TOPN_DEFAULT_STOP_PCT", "0.02")),
        )
    
    @classmethod
    def from_yaml(cls, config_dict: Dict[str, Any]) -> "TopNAllocatorConfig":
        """Load configuration from YAML dict."""
        return cls(
            min_cycle_risk_pct=config_dict.get("min_cycle_risk_pct", 0.01),
            max_cycle_risk_pct=config_dict.get("max_cycle_risk_pct", 0.02),
            max_edges_per_cycle=config_dict.get("max_edges_per_cycle", 3),
            min_edges_per_cycle=config_dict.get("min_edges_per_cycle", 0),
            min_contracts=config_dict.get("min_contracts", 1),
            min_notional_usd=config_dict.get("min_notional_usd", 1.00),
            edge_epsilon=config_dict.get("edge_epsilon", 1e-6),
            default_stop_distance_pct=config_dict.get("default_stop_distance_pct", 0.02),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EdgeCandidate:
    """A candidate asset with computed edge for selection.
    
    Args:
        asset: One of the 5 crypto assets
        edge: Expected edge (model probability - market implied probability)
        direction: Long or short
        entry_price_cents: Intended entry price in cents
        stop_price_cents: Stop level for max loss calculation in cents
        max_notional_cap: Per-asset cap from existing risk models (in cents)
        metadata: Additional contract details (ticker, expiry, etc.)
    """
    asset: Literal["BTC", "ETH", "SOL", "XRP", "DOGE"]
    edge: float
    direction: Literal["long", "short"]
    entry_price_cents: int
    stop_price_cents: int  # For max loss calculation
    max_notional_cap: int  # cents
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def compute_max_loss_per_contract(self) -> int:
        """Compute max loss in cents per contract.
        
        For Kalshi binary contracts:
        - Long: max loss = entry price (lose full price if wrong)
        - Short: max loss = 100 - entry price (lose remainder if wrong)
        
        Returns:
            Max loss in cents per contract
        """
        if self.direction == "long":
            # Long YES: lose entry price if NO settles
            return self.entry_price_cents
        else:
            # Short YES (Long NO): lose (100 - entry) if YES settles
            return 100 - self.entry_price_cents
    
    def compute_contracts_for_risk_budget(self, risk_budget_cents: int) -> int:
        """Compute max contracts that fit within risk budget.
        
        Args:
            risk_budget_cents: Max loss budget in cents
            
        Returns:
            Number of contracts that can be purchased
        """
        max_loss_per_contract = self.compute_max_loss_per_contract()
        if max_loss_per_contract <= 0:
            return 0
        return risk_budget_cents // max_loss_per_contract


@dataclass(frozen=True)
class TradeAllocation:
    """Single asset allocation within a top-N batch.
    
    Args:
        asset: Selected asset
        edge: Edge value used for ranking
        direction: Long or short
        target_contracts: Number of contracts to trade
        entry_price_cents: Entry price in cents
        stop_price_cents: Stop price in cents
        max_loss_usd: Maximum loss in dollars (cents / 100)
        weight: Relative weight (edge / sum(edges))
        risk_budget_usd: Risk budget allocated to this trade
        metadata: Additional contract details
    """
    asset: str
    edge: float
    direction: str
    target_contracts: int
    entry_price_cents: int
    stop_price_cents: int
    max_loss_usd: float  # dollars
    weight: float
    risk_budget_usd: float  # dollars
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/metrics."""
        return {
            "asset": self.asset,
            "edge": self.edge,
            "direction": self.direction,
            "target_contracts": self.target_contracts,
            "entry_price_cents": self.entry_price_cents,
            "stop_price_cents": self.stop_price_cents,
            "max_loss_usd": self.max_loss_usd,
            "weight": self.weight,
            "risk_budget_usd": self.risk_budget_usd,
        }


@dataclass
class AllocationCycle:
    """A complete allocation cycle with all trades.
    
    Args:
        cycle_id: Unique identifier for this cycle
        cycle_ts: Timestamp when cycle was created
        equity_cents: Account equity at cycle creation (cents)
        cycle_risk_pct: Risk percentage used for this cycle
        cycle_risk_usd: Total risk budget in dollars
        num_candidates: Number of candidates considered
        num_edges_traded: Number of edges actually traded (N)
        sum_risk_usd: Sum of max loss across all trades
        allocations: List of individual trade allocations
        config: Configuration used for this cycle
    """
    cycle_id: str
    cycle_ts: datetime
    equity_cents: int
    cycle_risk_pct: float
    cycle_risk_usd: float
    num_candidates: int
    num_edges_traded: int
    sum_risk_usd: float
    allocations: List[TradeAllocation]
    config: TopNAllocatorConfig
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/persistence."""
        return {
            "cycle_id": self.cycle_id,
            "cycle_ts": self.cycle_ts.isoformat(),
            "equity_cents": self.equity_cents,
            "equity_usd": self.equity_cents / 100,
            "cycle_risk_pct": self.cycle_risk_pct,
            "cycle_risk_usd": self.cycle_risk_usd,
            "num_candidates": self.num_candidates,
            "num_edges_traded": self.num_edges_traded,
            "sum_risk_usd": self.sum_risk_usd,
            "allocations": [a.to_dict() for a in self.allocations],
            "config": asdict(self.config),
        }
    
    def validate_invariants(self) -> Tuple[bool, List[str]]:
        """Validate that all invariants are satisfied.
        
        Returns:
            Tuple of (is_valid, list_of_violations)
        """
        violations = []
        
        # Invariant 1: N <= max_edges_per_cycle
        if self.num_edges_traded > self.config.max_edges_per_cycle:
            violations.append(
                f"INVARIANT_VIOLATION: num_edges_traded ({self.num_edges_traded}) > "
                f"max_edges_per_cycle ({self.config.max_edges_per_cycle})"
            )
        
        # Invariant 2: sum_risk_usd <= cycle_risk_usd
        if self.sum_risk_usd > self.cycle_risk_usd + 0.01:  # Small tolerance for float
            violations.append(
                f"INVARIANT_VIOLATION: sum_risk_usd ({self.sum_risk_usd:.2f}) > "
                f"cycle_risk_usd ({self.cycle_risk_usd:.2f})"
            )
        
        # Invariant 3: Each allocation respects min_contracts
        for alloc in self.allocations:
            if alloc.target_contracts < self.config.min_contracts:
                violations.append(
                    f"INVARIANT_VIOLATION: {alloc.asset} target_contracts ({alloc.target_contracts}) < "
                    f"min_contracts ({self.config.min_contracts})"
                )
        
        return len(violations) == 0, violations


# ═══════════════════════════════════════════════════════════════════════════
# Core Allocation Algorithm
# ═══════════════════════════════════════════════════════════════════════════


def select_topn_allocations(
    equity_cents: int,
    candidates: List[EdgeCandidate],
    config: TopNAllocatorConfig,
    cycle_risk_pct: Optional[float] = None,
) -> AllocationCycle:
    """Select top-N allocations with dynamic N stepping and max-loss sizing.
    
    Algorithm:
    1. Filter invalid candidates (edge <= 0, invalid asset, no stop)
    2. Sort by edge descending
    3. Determine cycle_risk_pct (use provided or default to max)
    4. Compute cycle_risk_usd = equity * cycle_risk_pct
    5. For N in [max_edges, ..., 1]:
       a. Take top N candidates
       b. Compute provisional risk allocation by edge weight
       c. Compute contracts for each based on max loss
       d. Check constraints: sum_risk <= cycle_risk_usd, min_contracts
       e. If valid, accept this N
    6. If no N valid, return N=0 (no trades)
    
    Args:
        equity_cents: Current account equity including open PnL
        candidates: List of edge candidates
        config: Allocator configuration
        cycle_risk_pct: Optional override for cycle risk % (else uses config.max)
        
    Returns:
        AllocationCycle with allocations and metadata
    """
    cycle_id = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
    cycle_ts = datetime.now(timezone.utc)
    
    # Step 1: Filter invalid candidates
    valid_candidates = _filter_valid_candidates(candidates, config)
    
    # Step 2: Sort by edge descending
    sorted_candidates = sorted(valid_candidates, key=lambda c: c.edge, reverse=True)
    
    # Step 3: Compute cycle risk budget
    if cycle_risk_pct is None:
        cycle_risk_pct = config.max_cycle_risk_pct
    else:
        # Clamp to valid range
        cycle_risk_pct = max(config.min_cycle_risk_pct, 
                            min(cycle_risk_pct, config.max_cycle_risk_pct))
    
    cycle_risk_cents = int(equity_cents * cycle_risk_pct)
    cycle_risk_usd = cycle_risk_cents / 100
    
    logger.info(
        "[TOPN-ALLOCATE] Starting allocation | equity=$%.2f | cycle_risk_pct=%.2f%% | "
        "cycle_risk_budget=$%.2f | candidates=%d",
        equity_cents / 100, cycle_risk_pct * 100, cycle_risk_usd, len(sorted_candidates)
    )
    
    # Step 4: Dynamic N stepping (3→2→1→0)
    max_n = min(config.max_edges_per_cycle, len(sorted_candidates))
    
    for n in range(max_n, config.min_edges_per_cycle - 1, -1):
        if n == 0:
            # No trades this cycle
            return AllocationCycle(
                cycle_id=cycle_id,
                cycle_ts=cycle_ts,
                equity_cents=equity_cents,
                cycle_risk_pct=cycle_risk_pct,
                cycle_risk_usd=cycle_risk_usd,
                num_candidates=len(candidates),
                num_edges_traded=0,
                sum_risk_usd=0.0,
                allocations=[],
                config=config,
            )
        
        # Try allocating to top N candidates
        top_n = sorted_candidates[:n]
        allocations = _allocate_to_candidates(top_n, cycle_risk_cents, config)
        
        if allocations is not None:
            # Valid allocation found
            sum_risk_usd = sum(a.max_loss_usd for a in allocations)
            
            logger.info(
                "[TOPN-ALLOCATE] N=%d accepted | sum_risk=$%.2f | budget=$%.2f | assets=%s",
                n, sum_risk_usd, cycle_risk_usd, [a.asset for a in allocations]
            )
            
            return AllocationCycle(
                cycle_id=cycle_id,
                cycle_ts=cycle_ts,
                equity_cents=equity_cents,
                cycle_risk_pct=cycle_risk_pct,
                cycle_risk_usd=cycle_risk_usd,
                num_candidates=len(candidates),
                num_edges_traded=n,
                sum_risk_usd=sum_risk_usd,
                allocations=allocations,
                config=config,
            )
        else:
            logger.debug("[TOPN-ALLOCATE] N=%d rejected (constraints not satisfied)", n)
    
    # No valid N found - return empty cycle
    return AllocationCycle(
        cycle_id=cycle_id,
        cycle_ts=cycle_ts,
        equity_cents=equity_cents,
        cycle_risk_pct=cycle_risk_pct,
        cycle_risk_usd=cycle_risk_usd,
        num_candidates=len(candidates),
        num_edges_traded=0,
        sum_risk_usd=0.0,
        allocations=[],
        config=config,
    )


def _filter_valid_candidates(
    candidates: List[EdgeCandidate],
    config: TopNAllocatorConfig,
) -> List[EdgeCandidate]:
    """Filter out invalid candidates."""
    valid = []
    
    for c in candidates:
        # Check edge > 0
        if c.edge <= 0:
            logger.debug("[TOPN-FILTER] %s: edge=%.4f <= 0", c.asset, c.edge)
            continue
        
        # Check valid asset
        if c.asset not in config.valid_assets:
            logger.debug("[TOPN-FILTER] %s: invalid asset", c.asset)
            continue
        
        # Check has max_notional_cap > 0
        if c.max_notional_cap <= 0:
            logger.debug("[TOPN-FILTER] %s: max_notional_cap <= 0", c.asset)
            continue
        
        # Check valid entry price
        if c.entry_price_cents <= 0:
            logger.debug("[TOPN-FILTER] %s: entry_price_cents <= 0", c.asset)
            continue
        
        # Check valid stop price (for Kalshi binary contracts, 0 and 100 are valid)
        # 0 = NO settlement boundary, 100 = YES settlement boundary
        if c.stop_price_cents < 0 or c.stop_price_cents > 100:
            logger.debug("[TOPN-FILTER] %s: stop_price_cents out of range [0,100]", c.asset)
            continue
        
        valid.append(c)
    
    return valid


def _allocate_to_candidates(
    candidates: List[EdgeCandidate],
    total_risk_cents: int,
    config: TopNAllocatorConfig,
) -> Optional[List[TradeAllocation]]:
    """Allocate risk budget to candidates with proportional sizing.
    
    Args:
        candidates: Top N candidates (already sorted)
        total_risk_cents: Total risk budget in cents
        config: Configuration
        
    Returns:
        List of TradeAllocation if valid, None if constraints violated
    """
    n = len(candidates)
    if n == 0:
        return []
    
    # Compute edge weights (handle ties)
    edges = [c.edge for c in candidates]
    edge_sum = sum(edges)
    
    if edge_sum <= 0:
        return None
    
    # Check for ties (edges within epsilon)
    max_edge = max(edges)
    min_edge = min(edges)
    edges_equal = (max_edge - min_edge) < config.edge_epsilon
    
    # Compute risk budget per candidate
    risk_budgets_cents: List[int] = []
    
    if edges_equal:
        # Equal split among tied edges
        base_budget = total_risk_cents // n
        remainder = total_risk_cents - (base_budget * n)
        
        for i in range(n):
            # Distribute remainder to first candidates
            extra = 1 if i < remainder else 0
            risk_budgets_cents.append(base_budget + extra)
    else:
        # Proportional by edge
        remaining_budget = total_risk_cents
        
        for i, c in enumerate(candidates):
            is_last = (i == n - 1)
            
            if is_last:
                # Last gets remainder
                budget_i = remaining_budget
            else:
                # Weighted allocation
                weight = c.edge / edge_sum
                budget_i = int(total_risk_cents * weight)
            
            risk_budgets_cents.append(budget_i)
            remaining_budget -= budget_i
    
    # Build allocations
    allocations: List[TradeAllocation] = []
    
    for i, c in enumerate(candidates):
        risk_budget_cents = risk_budgets_cents[i]
        
        # Compute contracts based on max loss per contract
        max_loss_per_contract = c.compute_max_loss_per_contract()
        
        if max_loss_per_contract <= 0:
            logger.debug("[TOPN-ALLOC] %s: max_loss_per_contract <= 0", c.asset)
            return None  # Constraint violated
        
        # Calculate contracts that fit within risk budget
        target_contracts = risk_budget_cents // max_loss_per_contract
        
        # Check min contracts constraint
        if target_contracts < config.min_contracts:
            logger.debug(
                "[TOPN-ALLOC] %s: target_contracts (%d) < min_contracts (%d)",
                c.asset, target_contracts, config.min_contracts
            )
            return None  # Constraint violated
        
        # Check min notional constraint
        notional_cents = target_contracts * c.entry_price_cents
        min_notional_cents = int(config.min_notional_usd * 100)
        if notional_cents < min_notional_cents and target_contracts > 0:
            logger.debug(
                "[TOPN-ALLOC] %s: notional ($%.2f) < min_notional ($%.2f)",
                c.asset, notional_cents / 100, config.min_notional_usd
            )
            return None  # Constraint violated
        
        # Compute actual max loss with integer contracts
        actual_max_loss_cents = target_contracts * max_loss_per_contract
        
        # Check per-asset notional cap
        if notional_cents > c.max_notional_cap:
            # Cap the contracts to respect max_notional_cap
            max_contracts_by_cap = c.max_notional_cap // c.entry_price_cents
            target_contracts = min(target_contracts, max_contracts_by_cap)
            actual_max_loss_cents = target_contracts * max_loss_per_contract
            logger.debug(
                "[TOPN-ALLOC] %s: capped by max_notional | contracts: %d -> %d",
                c.asset, target_contracts, max_contracts_by_cap
            )
            
            # Re-check min contracts after capping
            if target_contracts < config.min_contracts:
                return None
        
        # Compute weight
        weight = 1.0 / n if edges_equal else c.edge / edge_sum
        
        allocations.append(TradeAllocation(
            asset=c.asset,
            edge=c.edge,
            direction=c.direction,
            target_contracts=target_contracts,
            entry_price_cents=c.entry_price_cents,
            stop_price_cents=c.stop_price_cents,
            max_loss_usd=actual_max_loss_cents / 100,
            weight=weight,
            risk_budget_usd=risk_budget_cents / 100,
            metadata=c.metadata,
        ))
    
    # Final validation: sum of risk must be within budget
    sum_risk_cents = sum(int(a.max_loss_usd * 100) for a in allocations)
    
    if sum_risk_cents > total_risk_cents:
        # Shrink largest allocations to fit budget
        excess = sum_risk_cents - total_risk_cents
        allocations = _shrink_allocations_to_fit(allocations, excess)
        
        # Re-check after shrinking
        sum_risk_cents = sum(int(a.max_loss_usd * 100) for a in allocations)
        if sum_risk_cents > total_risk_cents:
            return None  # Still doesn't fit
    
    # Check all allocations have min contracts
    for a in allocations:
        if a.target_contracts < config.min_contracts:
            return None
    
    return allocations


def _shrink_allocations_to_fit(
    allocations: List[TradeAllocation],
    excess_cents: int,
) -> List[TradeAllocation]:
    """Shrink largest allocations to fit within budget.
    
    Args:
        allocations: Current allocations
        excess_cents: Amount to reduce by
        
    Returns:
        Adjusted allocations
    """
    if excess_cents <= 0:
        return allocations
    
    # Sort by max_loss descending to shrink largest first
    sorted_allocs = sorted(allocations, key=lambda a: a.max_loss_usd, reverse=True)
    
    adjusted = []
    remaining_excess = excess_cents
    
    for a in sorted_allocs:
        if remaining_excess <= 0:
            adjusted.append(a)
            continue
        
        # Shrink this allocation
        current_loss_cents = int(a.max_loss_usd * 100)
        max_loss_per_contract = current_loss_cents // max(a.target_contracts, 1)
        
        if max_loss_per_contract <= 0:
            adjusted.append(a)
            continue
        
        # Reduce contracts to cover excess
        contracts_to_remove = (remaining_excess + max_loss_per_contract - 1) // max_loss_per_contract
        new_contracts = max(a.target_contracts - contracts_to_remove, 1)  # Keep at least 1
        
        new_max_loss_cents = new_contracts * max_loss_per_contract
        reduced_by = current_loss_cents - new_max_loss_cents
        remaining_excess -= reduced_by
        
        # Create adjusted allocation
        adjusted.append(TradeAllocation(
            asset=a.asset,
            edge=a.edge,
            direction=a.direction,
            target_contracts=new_contracts,
            entry_price_cents=a.entry_price_cents,
            stop_price_cents=a.stop_price_cents,
            max_loss_usd=new_max_loss_cents / 100,
            weight=a.weight,
            risk_budget_usd=a.risk_budget_usd,
            metadata=a.metadata,
        ))
    
    return adjusted


# ═══════════════════════════════════════════════════════════════════════════
# Global Risk Manager Integration
# ═══════════════════════════════════════════════════════════════════════════


class GlobalRiskManager:
    """Global risk manager for batch-level checks.
    
    Placeholder for extensible global risk checks:
    - Daily loss limits
    - Max open risk caps
    - Kill switch integration
    """
    
    def __init__(self):
        self._daily_loss_usd: float = 0.0
        self._max_daily_loss_usd: float = float(os.getenv("MAX_DAILY_LOSS_USD", "100.0"))
        self._max_open_risk_pct: float = float(os.getenv("MAX_OPEN_RISK_PCT", "0.10"))  # 10%
    
    def can_open_batch(
        self,
        proposed_allocations: List[TradeAllocation],
        current_equity_cents: int,
        current_open_risk_usd: float = 0.0,
    ) -> Tuple[bool, str]:
        """Check if a new batch can be opened.
        
        Args:
            proposed_allocations: Proposed new trades
            current_equity_cents: Current account equity
            current_open_risk_usd: Current open risk from existing positions
            
        Returns:
            (allowed, reason) tuple
        """
        # Check daily loss limit
        if self._daily_loss_usd >= self._max_daily_loss_usd:
            return False, f"Daily loss limit reached: ${self._daily_loss_usd:.2f}"
        
        # Check max open risk
        proposed_risk_usd = sum(a.max_loss_usd for a in proposed_allocations)
        total_open_risk_usd = current_open_risk_usd + proposed_risk_usd
        max_open_risk_usd = (current_equity_cents / 100) * self._max_open_risk_pct
        
        if total_open_risk_usd > max_open_risk_usd:
            return False, (
                f"Max open risk exceeded: proposed=${proposed_risk_usd:.2f} + "
                f"current=${current_open_risk_usd:.2f} > max=${max_open_risk_usd:.2f}"
            )
        
        return True, ""
    
    def record_loss(self, loss_usd: float) -> None:
        """Record a loss for daily tracking."""
        self._daily_loss_usd += loss_usd
    
    def reset_daily_loss(self) -> None:
        """Reset daily loss (call at start of trading day)."""
        self._daily_loss_usd = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Main Allocator Class
# ═══════════════════════════════════════════════════════════════════════════


class TopNEdgeAllocator:
    """Cross-agent top-N edge selector and allocator with fixed fractional risk.
    
    This is the ONLY place where cross-asset selection and sizing logic lives.
    All agents must query this component before opening new positions.
    
    Features:
    - Dynamic N stepping (3→2→1→0) based on affordability
    - Fixed fractional risk per cycle (1-2%)
    - Max-loss-based sizing with stop distances
    - Respects min contracts and min notional constraints
    - Integrates with global risk manager
    
    Usage:
        allocator = TopNEdgeAllocator()
        
        # Create candidates with proper stop distances
        candidates = [
            EdgeCandidate(
                asset="BTC", edge=0.08, direction="long",
                entry_price_cents=55, stop_price_cents=0,  # 0 for binary
                max_notional_cap=5000,
                metadata={"ticker": "KXBTC-..."}
            ),
            ...
        ]
        
        # Compute allocations
        cycle = allocator.compute_allocations(
            equity_cents=bankroll_cents,
            candidates=candidates
        )
        
        # cycle.allocations contains up to 3 TradeAllocation objects
        # with target_contracts sized by max loss
    """
    
    def __init__(self, config: Optional[TopNAllocatorConfig] = None):
        self.config = config or TopNAllocatorConfig.from_env()
        self._global_risk = GlobalRiskManager()
        self._lock = threading.RLock()
        
        # Metrics tracking
        self._cycle_count = 0
        self._total_trades = 0
        self._rejected_cycles = 0
    
    def compute_allocations(
        self,
        equity_cents: int,
        candidates: List[EdgeCandidate],
        cycle_risk_pct: Optional[float] = None,
        current_open_risk_usd: float = 0.0,
    ) -> AllocationCycle:
        """Compute top-N allocations given equity and candidates.
        
        This is the main entry point for the allocator.
        
        Args:
            equity_cents: Current account equity in cents (including open PnL)
            candidates: List of edge candidates (typically 5 assets)
            cycle_risk_pct: Optional override for cycle risk %
            current_open_risk_usd: Current open risk from existing positions
            
        Returns:
            AllocationCycle with allocations and metadata
        """
        with self._lock:
            self._cycle_count += 1
            
            if equity_cents <= 0:
                logger.warning("[TOPN] Invalid equity: %d cents", equity_cents)
                self._rejected_cycles += 1
                return self._create_empty_cycle(equity_cents, candidates)
            
            if not candidates:
                logger.debug("[TOPN] No candidates provided")
                return self._create_empty_cycle(equity_cents, candidates)
            
            # Compute allocations with dynamic N stepping
            cycle = select_topn_allocations(
                equity_cents=equity_cents,
                candidates=candidates,
                config=self.config,
                cycle_risk_pct=cycle_risk_pct,
            )
            
            # Global risk check (if we have allocations)
            if cycle.allocations:
                allowed, reason = self._global_risk.can_open_batch(
                    cycle.allocations, equity_cents, current_open_risk_usd
                )
                
                if not allowed:
                    logger.warning("[TOPN] Global risk rejected batch: %s", reason)
                    self._rejected_cycles += 1
                    # Return empty cycle with same metadata
                    return AllocationCycle(
                        cycle_id=cycle.cycle_id,
                        cycle_ts=cycle.cycle_ts,
                        equity_cents=equity_cents,
                        cycle_risk_pct=cycle.cycle_risk_pct,
                        cycle_risk_usd=cycle.cycle_risk_usd,
                        num_candidates=len(candidates),
                        num_edges_traded=0,
                        sum_risk_usd=0.0,
                        allocations=[],
                        config=self.config,
                    )
                
                self._total_trades += len(cycle.allocations)
            
            # Validate invariants
            is_valid, violations = cycle.validate_invariants()
            if not is_valid:
                for v in violations:
                    logger.error("[TOPN] %s", v)
                
                # In debug/test, raise assertion
                if os.getenv("TOPN_STRICT_INVARIANTS", "false").lower() == "true":
                    raise AssertionError(f"Invariant violations: {violations}")
            
            # Log structured metrics
            self._log_cycle_metrics(cycle)
            
            return cycle
    
    def _create_empty_cycle(
        self,
        equity_cents: int,
        candidates: List[EdgeCandidate],
    ) -> AllocationCycle:
        """Create an empty allocation cycle."""
        return AllocationCycle(
            cycle_id=f"cycle_empty_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}",
            cycle_ts=datetime.now(timezone.utc),
            equity_cents=equity_cents,
            cycle_risk_pct=self.config.max_cycle_risk_pct,
            cycle_risk_usd=equity_cents * self.config.max_cycle_risk_pct / 100,
            num_candidates=len(candidates),
            num_edges_traded=0,
            sum_risk_usd=0.0,
            allocations=[],
            config=self.config,
        )
    
    def _log_cycle_metrics(self, cycle: AllocationCycle) -> None:
        """Log structured metrics for observability."""
        log_data = {
            "event": "TOPN_ALLOCATION_CYCLE",
            "cycle_id": cycle.cycle_id,
            "equity_usd": cycle.equity_cents / 100,
            "cycle_risk_pct": cycle.cycle_risk_pct,
            "cycle_risk_usd": cycle.cycle_risk_usd,
            "num_candidates": cycle.num_candidates,
            "num_edges_traded": cycle.num_edges_traded,
            "sum_risk_usd": cycle.sum_risk_usd,
            "allocations": [a.to_dict() for a in cycle.allocations],
        }
        
        logger.info("[TOPN-METRICS] %s", log_data)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get allocator metrics."""
        with self._lock:
            return {
                "cycle_count": self._cycle_count,
                "total_trades": self._total_trades,
                "rejected_cycles": self._rejected_cycles,
                "config": asdict(self.config),
            }
    
    def reset_metrics(self) -> None:
        """Reset metrics (for testing)."""
        with self._lock:
            self._cycle_count = 0
            self._total_trades = 0
            self._rejected_cycles = 0


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Instance
# ═══════════════════════════════════════════════════════════════════════════


_allocator_instance: Optional[TopNEdgeAllocator] = None
_allocator_lock = threading.Lock()


def get_topn_allocator() -> TopNEdgeAllocator:
    """Get singleton TopNEdgeAllocator instance."""
    global _allocator_instance
    if _allocator_instance is None:
        with _allocator_lock:
            if _allocator_instance is None:
                _allocator_instance = TopNEdgeAllocator()
    return _allocator_instance


def reset_topn_allocator() -> None:
    """Reset the allocator singleton (for testing)."""
    global _allocator_instance
    with _allocator_lock:
        _allocator_instance = None


def create_topn_allocator(config: TopNAllocatorConfig) -> TopNEdgeAllocator:
    """Create a new allocator instance with custom config (not singleton)."""
    return TopNEdgeAllocator(config)
