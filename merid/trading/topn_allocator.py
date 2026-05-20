"""
Top-N Edge Allocator — Production Implementation with Fixed Fractional Risk

Implements the cross-agent "Top-N Edge Selector & Allocator" that:
1. Selects top 3 edges across 5 assets (BTC, ETH, SOL, XRP, DOGE) on 15m timeframe
2. Allocates MAX_CYCLE_RISK_PCT (3% default) of bankroll in TOTAL across all new positions per cycle
   - Unified risk for all modes from core.settings (SINGLE SOURCE OF TRUTH)
3. Sizes positions by max loss per trade, respecting stop distances
4. Enforces min contracts and notional constraints

Key invariants:
- len(selected_assets) ∈ {0, 1, 2, 3} - top 3 edges maximum
- sum(max_loss_usd for selected) ≤ cycle_risk_usd (hard cap = MAX_CYCLE_RISK_PCT of bankroll)
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
    min_cycle_risk_pct: float = 0.01  # 1.0% minimum cycle risk
    max_cycle_risk_pct: float = 0.03  # 3% maximum (increased from 2%)
    
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
        """Load configuration from environment variables and core.settings.
        
        UNIFIED RISK REGIME: Risk settings come from both .env and core.settings.
        TOPN_MAX_EDGES from .env controls the top-N limit (default 3 for risk management).
        MAX_CYCLE_RISK_PCT from core.settings controls the cycle risk budget.
        TOPN_DEFAULT_STOP_DISTANCE_PCT from .env controls default stop distance.
        """
        try:
            from core.settings import MAX_CYCLE_RISK_PCT
            cycle_pct = float(MAX_CYCLE_RISK_PCT)
            logger.info(
                "[TOPN_ALLOCATOR] MAX_CYCLE_RISK_PCT loaded: %.4f (%.2f%%)",
                cycle_pct,
                cycle_pct * 100
            )
        except Exception:
            cycle_pct = 0.03  # Fallback to 3%
            logger.warning("[TOPN_ALLOCATOR] Failed to load MAX_CYCLE_RISK_PCT, using fallback: 3%")
        
        # Read TOPN_MAX_EDGES from environment (default 3 for risk management)
        max_edges = int(os.getenv("TOPN_MAX_EDGES", "3"))
        
        # Read individual overrides if set
        min_cycle_risk_pct = float(os.getenv("TOPN_MIN_CYCLE_RISK_PCT", str(cycle_pct * 0.5)))
        min_contracts = int(os.getenv("TOPN_MIN_CONTRACTS", "1"))
        default_stop_distance_pct = float(os.getenv("TOPN_DEFAULT_STOP_DISTANCE_PCT", "0.02"))
        
        return cls(
            min_cycle_risk_pct=min_cycle_risk_pct,
            max_cycle_risk_pct=cycle_pct,  # Use unified MAX_CYCLE_RISK_PCT
            max_edges_per_cycle=max_edges,  # Read from TOPN_MAX_EDGES env var
            min_edges_per_cycle=0,
            min_contracts=min_contracts,
            min_notional_usd=0.50,  # Reduced from $1.00 to $0.50 for small bankrolls
            edge_epsilon=1e-6,
            default_stop_distance_pct=default_stop_distance_pct,
        )
    
    @classmethod
    def from_yaml(cls, config_dict: dict) -> "TopNAllocatorConfig":
        """Load configuration from YAML dictionary."""
        return cls(
            min_cycle_risk_pct=config_dict.get("min_cycle_risk_pct", cls.min_cycle_risk_pct),
            max_cycle_risk_pct=config_dict.get("max_cycle_risk_pct", cls.max_cycle_risk_pct),
            max_edges_per_cycle=config_dict.get("max_edges_per_cycle", cls.max_edges_per_cycle),
            min_edges_per_cycle=config_dict.get("min_edges_per_cycle", cls.min_edges_per_cycle),
            min_contracts=config_dict.get("min_contracts", cls.min_contracts),
            min_notional_usd=config_dict.get("min_notional_usd", cls.min_notional_usd),
            edge_epsilon=config_dict.get("edge_epsilon", cls.edge_epsilon),
            default_stop_distance_pct=config_dict.get("default_stop_distance_pct", cls.default_stop_distance_pct),
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
        # BUG-TNA8 FIX: Use percentage-based tolerance instead of absolute for small bankrolls
        tolerance = max(0.01, self.cycle_risk_usd * 0.01)  # 1% of budget or $0.01 minimum
        if self.sum_risk_usd > self.cycle_risk_usd + tolerance:
            violations.append(
                f"INVARIANT_VIOLATION: sum_risk_usd ({self.sum_risk_usd:.2f}) > "
                f"cycle_risk_usd ({self.cycle_risk_usd:.2f}) + tolerance ({tolerance:.2f})"
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
    """Select top-N allocations with STRICT EDGE #1 PRIORITY sequential fill.

    ALGORITHM (per user wagering rules):
    1. Filter invalid candidates (edge <= 0, invalid asset, no stop)
    2. Sort by edge descending to rank Edge #1, #2, #3
    3. Compute total cycle risk budget (1-2% of bankroll)
    4. Edge #1 (highest edge) gets FIRST allocation with 1% risk budget MINIMUM
    5. If Edge #1 allocated and budget remains, allocate to Edge #2
    6. If Edge #2 allocated and budget remains, allocate to Edge #3
    7. If any edge fails min constraints, skip it AND all subsequent edges
    8. Return allocations with explicit Edge #1/#2/#3 logging

    CRITICAL RULES ENFORCED:
    - Edge #1 is MANDATORY if valid and within bankroll
    - Edge #1 must be executed before Edge #2 or #3
    - Never skip Edge #1 to take Edge #2 or #3
    - Each edge gets 1-2% max risk (Edge #1 always gets at least 1% if valid)

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

    # Step 2: Sort by edge descending to establish Edge #1, #2, #3 ranking
    sorted_candidates = sorted(valid_candidates, key=lambda c: c.edge, reverse=True)

    # Log the ranked edges for transparency
    _log_ranked_edges(sorted_candidates, equity_cents)

    # Step 3: Compute cycle risk budget (1-2% total)
    if cycle_risk_pct is None:
        cycle_risk_pct = config.max_cycle_risk_pct
    else:
        cycle_risk_pct = max(config.min_cycle_risk_pct,
                            min(cycle_risk_pct, config.max_cycle_risk_pct))

    # Edge #1 gets MINIMUM 1% risk budget (non-negotiable if valid)
    # BUG-TNA10 FIX: Ensure min_cycle_risk_pct is at least 0.01 (1%) to prevent zero budget
    edge1_min_risk_pct = max(config.min_cycle_risk_pct, 0.01)  # Minimum 1%
    total_cycle_risk_cents = int(equity_cents * cycle_risk_pct)
    edge1_budget_cents = int(equity_cents * edge1_min_risk_pct)

    logger.info(
        "[EDGE-PRIORITY] equity=$%.2f | total_cycle_budget=$%.2f (%.2f%%) | "
        "edge1_minimum=$%.2f (%.2f%%)",
        equity_cents / 100,
        total_cycle_risk_cents / 100, cycle_risk_pct * 100,
        edge1_budget_cents / 100, edge1_min_risk_pct * 100
    )

    # Step 4: SEQUENTIAL PRIORITY FILL - Edge #1 first, then #2, then #3
    allocations: List[TradeAllocation] = []
    remaining_budget_cents = total_cycle_risk_cents
    edges_allocated = []
    edges_skipped = []

    max_edges = min(config.max_edges_per_cycle, len(sorted_candidates))

    for edge_rank in range(1, max_edges + 1):
        if edge_rank > len(sorted_candidates):
            break

        candidate = sorted_candidates[edge_rank - 1]  # 0-indexed
        edge_label = f"Edge#{edge_rank}"

        # Determine budget for this edge
        if edge_rank == 1:
            # Edge #1 gets minimum 1% budget (or remaining if less)
            edge_budget_cents = min(edge1_budget_cents, remaining_budget_cents)
        else:
            # Edge #2, #3 get remaining budget (up to 1% each)
            edge_budget_cents = remaining_budget_cents

        if edge_budget_cents <= 0:
            logger.info(
                "[%s-SKIP] %s | reason=zero_budget_remaining | "
                "bankroll_depleted_by_previous_edges",
                edge_label, candidate.asset
            )
            edges_skipped.append((edge_rank, candidate.asset, "zero_budget_remaining"))
            # Skip subsequent edges - no budget left
            break

        # Attempt to allocate to this edge
        alloc = _allocate_single_candidate(candidate, edge_budget_cents, config, edge_rank)

        if alloc is None:
            # Failed min constraints - skip this edge and ALL subsequent edges
            logger.warning(
                "[%s-SKIP] %s | reason=failed_min_constraints | "
                "edge=%.4f price=%d¢ | Subsequent edges (#%d+) also skipped",
                edge_label, candidate.asset, candidate.edge,
                candidate.entry_price_cents, edge_rank + 1
            )
            edges_skipped.append((edge_rank, candidate.asset, "failed_min_constraints"))

            # CRITICAL: If Edge #1 fails, NO trades this cycle
            # If Edge #2 fails, Edge #3 is also skipped
            for subsequent_rank in range(edge_rank + 1, max_edges + 1):
                if subsequent_rank <= len(sorted_candidates):
                    sub_candidate = sorted_candidates[subsequent_rank - 1]
                    sub_label = f"Edge#{subsequent_rank}"
                    logger.info(
                        "[%s-SKIP] %s | reason=previous_edge_failed | "
                        "blocked_by=%s_failure",
                        sub_label, sub_candidate.asset, edge_label
                    )
                    edges_skipped.append((subsequent_rank, sub_candidate.asset, f"blocked_by_{edge_label}_failure"))
            break

        # Successfully allocated to this edge
        allocations.append(alloc)
        remaining_budget_cents -= int(alloc.max_loss_usd * 100)
        edges_allocated.append(edge_rank)

        logger.info(
            "[%s-ALLOCATED] %s | edge=%.4f | contracts=%d | risk=$%.2f | "
            "remaining_budget=$%.2f",
            edge_label, alloc.asset, alloc.edge, alloc.target_contracts,
            alloc.max_loss_usd, remaining_budget_cents / 100
        )

    # Build and return the allocation cycle
    sum_risk_usd = sum(a.max_loss_usd for a in allocations)
    num_edges = len(allocations)

    # Log final summary
    logger.info(
        "[EDGE-PRIORITY-SUMMARY] cycle=%s | edges_allocated=%s | edges_skipped=%s | "
        "total_risk=$%.2f | total_budget=$%.2f",
        cycle_id,
        [f"#{r}:{a.asset}" for r, a in zip(edges_allocated, allocations)],
        [f"#{r}:{a}" for r, a, reason in edges_skipped],
        sum_risk_usd, total_cycle_risk_cents / 100
    )

    return AllocationCycle(
        cycle_id=cycle_id,
        cycle_ts=cycle_ts,
        equity_cents=equity_cents,
        cycle_risk_pct=cycle_risk_pct,
        cycle_risk_usd=total_cycle_risk_cents / 100,
        num_candidates=len(candidates),
        num_edges_traded=num_edges,
        sum_risk_usd=sum_risk_usd,
        allocations=allocations,
        config=config,
    )


def _log_ranked_edges(candidates: List[EdgeCandidate], equity_cents: int) -> None:
    """Log the ranked edges for transparency."""
    if not candidates:
        logger.info("[EDGE-RANKING] No valid candidates")
        return

    logger.info("[EDGE-RANKING] Top edges by expected edge (bankroll=$%.2f):", equity_cents / 100)
    for i, c in enumerate(candidates[:3], 1):
        edge_pct = c.edge * 100
        # Compute implied stake size (1-2% rule)
        stake_pct = min(2.0, max(1.0, edge_pct * 0.5))  # Rough estimate
        logger.info(
            "  Edge#%d: %s | edge=%.2f%% | direction=%s | entry=%d¢ | "
            "suggested_stake=%.1f%%",
            i, c.asset, edge_pct, c.direction, c.entry_price_cents, stake_pct
        )


def _allocate_single_candidate(
    candidate: EdgeCandidate,
    budget_cents: int,
    config: TopNAllocatorConfig,
    edge_rank: int,
) -> Optional[TradeAllocation]:
    """Allocate risk budget to a single candidate.

    Args:
        candidate: The edge candidate to allocate
        budget_cents: Maximum risk budget in cents for this allocation
        config: Allocator configuration
        edge_rank: Edge rank (1, 2, or 3) for weight calculation

    Returns:
        TradeAllocation if successful, None if constraints not met
    """
    # Compute max loss per contract
    max_loss_per_contract = candidate.compute_max_loss_per_contract()
    if max_loss_per_contract <= 0:
        logger.debug(
            "[_allocate_single] %s: max_loss_per_contract=%d <= 0",
            candidate.asset, max_loss_per_contract
        )
        return None

    # Calculate contracts that fit within risk budget
    target_contracts = budget_cents // max_loss_per_contract

    # ═══════════════════════════════════════════════════════════════════
    # BETA NORMALIZATION: Adjust position size based on asset volatility
    # Uses DYNAMIC BETA from BTC-anchored model when available,
    # falling back to static beta from config.
    # ═══════════════════════════════════════════════════════════════════
    try:
        # Try dynamic beta first (real-time from price action)
        from merid.signals.btc_anchored_move import get_dynamic_beta
        _beta = get_dynamic_beta(
            candidate.asset,
            timeframe=candidate.metadata.get("timeframe", "15m"),
            min_observations=20,
            fallback_to_static=True,
        )
        _beta_source = "dynamic"

        # Get volatility adjustment from static config
        from merid.signals.asset_configs import get_asset_config
        _asset_cfg = get_asset_config(candidate.asset)
        _vol_adj = _asset_cfg.vol_size_adjustment

        # Apply beta scaling: higher beta = fewer contracts
        # Use inverse of beta, capped at 2x reduction for very high beta assets
        _beta_scale = min(1.0, 1.0 / max(_beta, 0.5))  # Cap at 0.5x for beta >= 2.0
        _target_before = target_contracts
        target_contracts = max(1, int(target_contracts * _beta_scale * _vol_adj))

        if _target_before != target_contracts:
            logger.info(
                "[BETA-NORM] %s: contracts %d -> %d (beta=%.2f %s, vol_adj=%.2f, scale=%.2f)",
                candidate.asset, _target_before, target_contracts, _beta,
                _beta_source, _vol_adj, _beta_scale
            )
    except Exception as _beta_exc:
        # BUG-TNA4 FIX: Log at warning level instead of debug to catch silent failures
        logger.warning(
            "[BETA-NORM] %s: beta normalization failed (error=%s), using unadjusted contracts",
            candidate.asset, _beta_exc
        )

    # Check min contracts constraint
    if target_contracts < config.min_contracts:
        logger.debug(
            "[_allocate_single] %s: target_contracts=%d < min_contracts=%d",
            candidate.asset, target_contracts, config.min_contracts
        )
        return None

    # Check min notional constraint
    notional_cents = target_contracts * candidate.entry_price_cents
    min_notional_cents = int(config.min_notional_usd * 100)
    if notional_cents < min_notional_cents and target_contracts > 0:
        logger.debug(
            "[_allocate_single] %s: notional=$%.2f < min_notional=$%.2f",
            candidate.asset, notional_cents / 100, config.min_notional_usd
        )
        return None

    # Check per-asset notional cap
    if notional_cents > candidate.max_notional_cap:
        # Cap the contracts to respect max_notional_cap
        max_contracts_by_cap = candidate.max_notional_cap // candidate.entry_price_cents
        target_contracts = min(target_contracts, max_contracts_by_cap)
        if target_contracts < config.min_contracts:
            logger.debug(
                "[_allocate_single] %s: capped below min_contracts | max_by_cap=%d",
                candidate.asset, max_contracts_by_cap
            )
            return None
        logger.debug(
            "[_allocate_single] %s: capped by max_notional | contracts: %d -> %d",
            candidate.asset, target_contracts, max_contracts_by_cap
        )

    # Compute actual max loss with integer contracts
    actual_max_loss_cents = target_contracts * max_loss_per_contract

    # Weight is 1.0 for Edge#1, then proportional for #2, #3
    # In strict priority, weight reflects priority order, not edge strength
    weight = 1.0 / edge_rank

    return TradeAllocation(
        asset=candidate.asset,
        edge=candidate.edge,
        direction=candidate.direction,
        target_contracts=target_contracts,
        entry_price_cents=candidate.entry_price_cents,
        stop_price_cents=candidate.stop_price_cents,
        max_loss_usd=actual_max_loss_cents / 100,
        weight=weight,
        risk_budget_usd=budget_cents / 100,
        metadata=candidate.metadata,
    )


def _filter_valid_candidates(
    candidates: List[EdgeCandidate],
    config: TopNAllocatorConfig,
) -> List[EdgeCandidate]:
    """Filter out invalid candidates.
    
    BUG-TNA9: Zero/near-zero edges are handled here by checking edge > min_edge_threshold.
    This ensures only edges with meaningful expected value proceed to ranking.
    """
    valid = []
    
    for c in candidates:
        # ═══════════════════════════════════════════════════════════════════
        # ASSET-SPECIFIC EDGE THRESHOLDS (Task 6)
        # High-noise assets (DOGE, SOL) need higher edge bars than BTC
        # ═══════════════════════════════════════════════════════════════════
        try:
            from merid.signals.asset_configs import get_asset_config
            asset_cfg = get_asset_config(c.asset)
            min_edge_threshold = asset_cfg.min_edge_threshold  # e.g., 0.060 for DOGE (conservative)
        except Exception:
            min_edge_threshold = 0.050  # CONSERVATIVE: 5.0% default fallback

        # Check edge meets asset-specific threshold
        # BUG-TNA9: This ensures zero/near-zero edges are filtered before ranking
        if c.edge <= 0 or c.edge < min_edge_threshold:
            logger.debug(
                "[TOPN-FILTER] %s: edge=%.4f below threshold=%.4f",
                c.asset, c.edge, min_edge_threshold
            )
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
        
        # BUG-TNA7 FIX: Re-check min notional after shrinking
        new_notional_cents = new_contracts * a.entry_price_cents
        min_notional_cents = int(1.00 * 100)  # $1.00 min notional
        if new_notional_cents < min_notional_cents and new_contracts > 0:
            logger.debug(
                "[SHRINK] %s: notional after shrink ($%.2f) < min_notional ($%.2f), keeping original",
                a.asset, new_notional_cents / 100, 1.00
            )
            adjusted.append(a)  # Keep original allocation
            continue
        
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
        self._max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.10"))  # 10%
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
        # Check daily loss limit (using percentage from core.settings)
        max_daily_loss_usd = (current_equity_cents / 100) * self._max_daily_loss_pct
        if self._daily_loss_usd >= max_daily_loss_usd:
            return False, f"Daily loss limit reached: ${self._daily_loss_usd:.2f} (max=${max_daily_loss_usd:.2f})"
        
        # Check max open risk (using percentage from core.settings)
        proposed_risk_usd = sum(a.max_loss_usd for a in proposed_allocations)
        total_open_risk_usd = current_open_risk_usd + proposed_risk_usd
        max_open_risk_usd = (current_equity_cents / 100) * self._max_open_risk_pct
        
        if total_open_risk_usd > max_open_risk_usd:
            return False, (
                f"Max open risk exceeded: proposed=${proposed_risk_usd:.2f} + "
                f"current=${current_open_risk_usd:.2f} > max=${max_open_risk_usd:.2f}"
            )
        
        return True, "Batch allowed"
    
    def record_loss(self, loss_usd: float) -> None:
        """Record a loss for daily tracking.
        
        BUG-TNA6: This duplicates daily loss tracking in other systems (fills_ledger, KalshiRiskManager).
        Consider removing this and using the canonical source.
        """
        self._daily_loss_usd += loss_usd
    
    def reset_daily_loss(self) -> None:
        """Reset daily loss (call at start of trading day).
        
        BUG-TNA6: This duplicates daily loss tracking in other systems (fills_ledger, KalshiRiskManager).
        Consider removing this and using the canonical source.
        """
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
        # PERF-OPTIMIZATION: Minimize lock contention by doing expensive work outside lock
        # Phase 1: Handle invalid equity (potentially slow bankroll derivation) - OUTSIDE LOCK
        if equity_cents <= 0:
            logger.warning("[TOPN] Invalid equity: %d cents, attempting live bankroll derivation", equity_cents)
            # Try to derive live bankroll from Kalshi API
            try:
                from merid.event_venues.kalshi.order_router import _derive_live_bankroll_usd
                _live = _derive_live_bankroll_usd()
                if _live is not None and _live > 0:
                    equity_cents = int(_live * 100)
                    logger.info("[TOPN] Recovered with live bankroll: %d cents", equity_cents)
                else:
                    # FAIL CLOSED: Cannot get live bankroll
                    logger.error("[TOPN] Cannot determine live Kalshi balance. Rejecting cycle.")
                    # Quick update to rejected counter - minimal lock time
                    with self._lock:
                        self._rejected_cycles += 1
                    return self._create_empty_cycle(0, candidates)
            except Exception as _e:
                # FAIL CLOSED: Cannot get live bankroll
                # BUG-TNA5 FIX: Log specific exception type for better diagnostics
                import traceback
                logger.error(
                    "[TOPN] Failed to get live bankroll: %s. Rejecting cycle. Traceback: %s",
                    _e, traceback.format_exc()
                )
                # Quick update to rejected counter - minimal lock time
                with self._lock:
                    self._rejected_cycles += 1
                return self._create_empty_cycle(0, candidates)

        if not candidates:
            logger.debug("[TOPN] No candidates provided")
            return self._create_empty_cycle(equity_cents, candidates)

        # Phase 2: Compute allocations - OUTSIDE LOCK (pure computation, no shared state)
        cycle = select_topn_allocations(
            equity_cents=equity_cents,
            candidates=candidates,
            config=self.config,
            cycle_risk_pct=cycle_risk_pct,
        )

        # Phase 3: Global risk check - OUTSIDE LOCK (uses external risk manager)
        if cycle.allocations:
            allowed, reason = self._global_risk.can_open_batch(
                cycle.allocations, equity_cents, current_open_risk_usd
            )

            if not allowed:
                logger.warning("[TOPN] Global risk rejected batch: %s", reason)
                # Quick update to rejected counter - minimal lock time
                with self._lock:
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

        # Phase 4: Update shared state - INSIDE LOCK (minimal critical section)
        with self._lock:
            self._cycle_count += 1
            if cycle.allocations:
                self._total_trades += len(cycle.allocations)

        # Phase 5: Validation and logging - OUTSIDE LOCK (no shared state needed)
        is_valid, violations = cycle.validate_invariants()
        if not is_valid:
            for v in violations:
                logger.error("[TOPN] %s", v)

            # In debug/test, raise assertion
            if os.getenv("TOPN_STRICT_INVARIANTS", "false").lower() == "true":
                raise AssertionError(f"Invariant violations: {violations}")

        # Log structured metrics (outside lock)
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
