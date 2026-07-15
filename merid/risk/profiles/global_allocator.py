"""
Global Allocator for Multi-Asset Position Sizing

Replaces per-asset caps with a top-N edge knapsack allocator under venue cap.

Core idea:
- Collect all candidates from all agents in a cycle
- Sort by edge (descending)
- Greedy fill under venue cap ($1.00)
- Only submit orders that fit under the cap

This ensures:
- Best edges get prioritized
- Total exposure ≤ venue cap (shared $1 pool across all assets)
- No artificial per-asset limits
- Concentration on highest expected returns
- 1 contract per asset per window
- Entry prices in 10c-75c range (expanded for current market conditions - YES prices 60-97c observed)
- Confidence ≥ 50% (matches agent grid: 0.5 + edge/100), edge ≥ 2.0% (actual percentage)
"""

import time
from typing import List, Dict, Any, Optional

from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger("merid.risk.profiles.global_allocator")


@dataclass
class OrderCandidate:
    """Represents a potential order from an agent."""
    asset: str
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    count: int
    edge_pct: float
    confidence: float
    model_prob: float
    agent_name: str
    
    @property
    def notional_usd(self) -> float:
        """Calculate order notional in USD."""
        return (self.price_cents * self.count) / 100.0
    
    @property
    def edge_score(self) -> float:
        """
        Composite edge score for ranking.
        Combines edge_pct and confidence.
        """
        return self.edge_pct * self.confidence


class GlobalAllocator:
    """
    Global allocator for multi-asset position sizing.
    
    Implements top-N edge knapsack under venue cap with shared $1 pool.
    
    CRITICAL RULES:
    - $1 total exposure cap across ALL assets (shared pool, not per-asset)
    - 1 contract per asset per window
    - Entry price must be in 5c-95c range (expanded for skewed markets)
    - Confidence must be ≥ 50% (matches agent grid: 0.5 + edge/100)
    - Edge must be ≥ 2.5% (matches profile edge_bands - industry standard)
    - Assets compete for capital (no per-asset budgets)
    """
    
    def __init__(
        self,
        venue_cap_usd: float = 1.00,
        min_edge_pct: float = 0.025,  # 2026-07-14: Changed to 2.5% to match profile edge_bands (industry standard)
        min_confidence: float = 0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence calculation (0.5 + edge/100)
        min_price_cents: int = 10,  # 2026-07-12: Lower bound (10c) maintained for low-profit trap prevention
        max_price_cents: int = 75,  # 2026-07-12: Expanded to 75c - YES prices consistently 60-97c in current market conditions
        max_single_asset_fraction: float = 1.00,  # Max 100% of cap per asset (allows single order to use full venue cap)
        enable_correlation_control: bool = False,
        # 2026-07-14: Per-asset edge thresholds aligned with profile edge_bands (2.5% unified - industry standard)
        # This ensures global allocator doesn't filter candidates that pass validate_edge()
        per_asset_min_edge_pct: dict = None,
    ):
        self.venue_cap_usd = venue_cap_usd
        self.min_edge_pct = min_edge_pct
        self.min_confidence = min_confidence
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.max_single_asset_fraction = max_single_asset_fraction
        self.enable_correlation_control = enable_correlation_control
        
        # Per-asset edge thresholds (aligned with profile edge_bands - single source of truth)
        # CRITICAL FIX 2026-07-14: Updated to use unified 2.5% threshold from profile edge_bands
        # Industry standard for Kalshi: 3% raw edge minimum (Market Math, Beatpoly)
        # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
        # Edge threshold hierarchy (from profile YAML):
        # 1. edge_bands.*.min_edge_pct - PRIMARY: Used for trade execution (2.5% minimum)
        # 2. Per-asset min_edge_early/mid/late/terminal - IGNORED: Legacy fields, not used
        if per_asset_min_edge_pct is None:
            self.per_asset_min_edge_pct = {
                "BTC": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
                "ETH": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
                "SOL": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
                "XRP": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
                "DOGE": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
            }
        else:
            self.per_asset_min_edge_pct = per_asset_min_edge_pct
        
        # 2026-07-13: Add per-asset position and pending order tracking
        # This prevents multiple contracts per asset (the core issue)
        self._asset_positions: Dict[str, float] = {}  # asset -> current notional
        self._pending_orders: Dict[str, str] = {}  # asset -> order_id (pending submission)
        self._pending_order_timestamps: Dict[str, float] = {}  # asset -> submission timestamp
        self._pending_order_timeout = 30.0  # 30 seconds timeout for pending orders
        
        logger.info(
            "[GLOBAL-ALLOCATOR] Initialized: venue_cap=$%.2f, min_edge=%.3f%%, min_conf=%.0f%%, price_range=[%dc-%dc], max_single=%.1f%%",
            venue_cap_usd, min_edge_pct, min_confidence * 100, min_price_cents, max_price_cents, max_single_asset_fraction * 100
        )
        logger.info(
            "[GLOBAL-ALLOCATOR] Per-asset edge thresholds: %s",
            ", ".join(f"{k}={v}%" for k, v in self.per_asset_min_edge_pct.items())
        )
    
    def allocate(
        self,
        candidates: List[OrderCandidate],
        current_positions: Optional[Dict[str, float]] = None
    ) -> List[OrderCandidate]:
        """
        Allocate orders based on edge ranking under venue cap with shared $1 pool.
        
        CRITICAL: This implements the shared $1 pool model where assets compete for capital.
        No per-asset budgets - total exposure across all assets must be ≤ $1.00.
        
        Args:
            candidates: List of all potential orders from agents
            current_positions: Current position notional per asset (optional)
        
        Returns:
            List of chosen orders that fit under venue cap
        """
        if not candidates:
            logger.info("[GLOBAL-ALLOCATOR] No candidates to allocate")
            return []
        
        current_positions = current_positions or {}
        
        # CRITICAL FIX: Sync internal _asset_positions with authoritative current_positions
        # This ensures lifecycle callbacks don't drift from actual position cache state
        self._asset_positions = current_positions.copy()
        
        # Filter by minimum edge (per-asset thresholds aligned with risk_parameters.py)
        filtered = []
        for c in candidates:
            asset_min_edge = self.per_asset_min_edge_pct.get(c.asset, self.min_edge_pct)
            if c.edge_pct >= asset_min_edge:
                filtered.append(c)
            else:
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: edge=%.3f%% < per_asset_min_edge=%.3f%%",
                    c.asset, c.edge_pct, asset_min_edge
                )
        
        if len(filtered) < len(candidates):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates below per-asset min edge thresholds",
                len(candidates) - len(filtered), len(candidates)
            )
        
        # Filter by minimum confidence (50%)
        conf_filtered = [c for c in filtered if c.confidence >= self.min_confidence]
        if len(conf_filtered) < len(filtered):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates below min confidence %.0f%%",
                len(filtered) - len(conf_filtered), len(filtered), self.min_confidence * 100
            )
        
        # Filter by price range (10c-75c canonical range)
        price_filtered = [c for c in conf_filtered if self.min_price_cents <= c.price_cents <= self.max_price_cents]
        if len(price_filtered) < len(conf_filtered):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates outside price range [%dc-%dc]",
                len(conf_filtered) - len(price_filtered), len(conf_filtered), self.min_price_cents, self.max_price_cents
            )
        
        # 2026-07-13: Filter by per-asset position and pending order status
        # This prevents multiple contracts per asset (the core issue)
        position_filtered = []
        for c in price_filtered:
            # CRITICAL FIX: Use current_positions from position cache instead of internal _asset_positions
            # The internal dict is only for lifecycle tracking and may be stale
            # current_positions is the authoritative source from the actual position cache
            if c.asset in current_positions and current_positions[c.asset] > 0:
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: asset has existing position ($%.2f)",
                    c.asset, current_positions[c.asset]
                )
                continue
            
            # Check if asset has pending order (and not stale)
            if c.asset in self._pending_orders:
                time_since_submit = time.time() - self._pending_order_timestamps.get(c.asset, 0)
                if time_since_submit < self._pending_order_timeout:
                    logger.info(
                        "[GLOBAL-ALLOCATOR] SKIP %s: asset has pending order %s (%.1fs old)",
                        c.asset, self._pending_orders[c.asset], time_since_submit
                    )
                    continue
                else:
                    # Stale pending order - clear it
                    logger.warning(
                        "[GLOBAL-ALLOCATOR] Clearing stale pending order for %s: %.1fs old",
                        c.asset, time_since_submit
                    )
                    del self._pending_orders[c.asset]
                    del self._pending_order_timestamps[c.asset]
            
            position_filtered.append(c)
        
        if len(position_filtered) < len(price_filtered):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates due to existing positions/pending orders",
                len(price_filtered) - len(position_filtered), len(price_filtered)
            )
        
        if not position_filtered:
            logger.info("[GLOBAL-ALLOCATOR] No candidates passed all filters (edge, confidence, price, position)")
            return []
        
        # Optimal knapsack-style allocation under $1 cap
        # For small asset universe (5 assets), brute-force all combinations to find optimal
        # This ensures we get the best combination of edges that fits under cap
        from itertools import combinations
        
        # Group candidates by asset (1 per asset max)
        asset_candidates = {}
        for candidate in position_filtered:
            if candidate.asset not in asset_candidates:
                asset_candidates[candidate.asset] = candidate  # Keep best per asset (already sorted by edge)
        
        unique_candidates = list(asset_candidates.values())
        logger.info(
            "[GLOBAL-ALLOCATOR] Evaluating %d unique candidates (1 per asset) for optimal $1 cap allocation",
            len(unique_candidates)
        )
        
        best_combination = []
        best_total_edge = 0.0
        best_total_notional = float('inf')  # Initialize to infinity so first valid combo is selected
        
        # Try all combinations (2^n where n=5, so max 32 combinations)
        for r in range(1, len(unique_candidates) + 1):
            for combo in combinations(unique_candidates, r):
                total_notional = sum(c.notional_usd for c in combo)
                
                # Skip if exceeds cap
                if total_notional > self.venue_cap_usd:
                    continue
                
                # Check per-asset concentration limit
                combo_valid = True
                for candidate in combo:
                    asset_current = current_positions.get(candidate.asset, 0.0)
                    asset_with_order = candidate.notional_usd
                    max_asset_notional = self.venue_cap_usd * self.max_single_asset_fraction
                    if asset_with_order > max_asset_notional:
                        combo_valid = False
                        break
                
                if not combo_valid:
                    continue
                
                # Calculate total edge score for this combination
                total_edge = sum(c.edge_score for c in combo)
                
                # 2026-07-13: Prefer higher edge first, then cheaper price for tiebreaker
                # Primary: Higher total edge for better expected returns
                # Secondary: Lower notional (cheaper) to maximize position count under $1 cap
                # This allows more assets to trade within the $1 cap (e.g., 35c + 55c + 10c = $1)
                if total_edge > best_total_edge or (total_edge == best_total_edge and total_notional < best_total_notional):
                    best_combination = list(combo)
                    best_total_edge = total_edge
                    best_total_notional = total_notional
        
        chosen = best_combination
        used_notional = best_total_notional
        
        # Log chosen orders
        for candidate in chosen:
            logger.info(
                "[GLOBAL-ALLOCATOR] CHOOSE %s: edge=%.3f%%, conf=%.0f%%, price=%dc, notional=$%.2f",
                candidate.asset, candidate.edge_pct, candidate.confidence * 100, candidate.price_cents, candidate.notional_usd
            )
        
        logger.info(
            "[GLOBAL-ALLOCATOR] Allocation complete: %d/%d chosen, total_notional=$%.2f/$%.2f (%.1f%% utilization)",
            len(chosen), len(candidates), used_notional, self.venue_cap_usd, (used_notional / self.venue_cap_usd) * 100
        )
        
        return chosen
    
    def get_allocation_summary(
        self,
        chosen: List[OrderCandidate]
    ) -> Dict[str, Any]:
        """
        Get summary of allocation decisions.
        
        Args:
            chosen: List of chosen orders
        
        Returns:
            Summary dict with allocation statistics
        """
        if not chosen:
            return {
                "total_orders": 0,
                "total_notional": 0.0,
                "asset_breakdown": {},
                "avg_edge": 0.0,
                "utilization_pct": 0.0
            }
        
        total_notional = sum(c.notional_usd for c in chosen)
        asset_breakdown = {}
        for c in chosen:
            asset_breakdown[c.asset] = asset_breakdown.get(c.asset, 0.0) + c.notional_usd
        
        avg_edge = sum(c.edge_pct for c in chosen) / len(chosen)
        
        return {
            "total_orders": len(chosen),
            "total_notional": total_notional,
            "asset_breakdown": asset_breakdown,
            "avg_edge": avg_edge,
            "utilization_pct": (total_notional / self.venue_cap_usd) * 100
        }
    
    def record_order_submitted(self, asset: str, order_id: str, notional_usd: float) -> None:
        """
        Record that an order was submitted for an asset.
        
        This should be called after order_router.route_order_async() returns success.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            order_id: Order ID from order router
            notional_usd: Order notional in USD
        """
        self._pending_orders[asset] = order_id
        self._pending_order_timestamps[asset] = time.time()
        logger.info(
            "[GLOBAL-ALLOCATOR] Order submitted: asset=%s order_id=%s notional=$%.2f",
            asset, order_id, notional_usd
        )
    
    def record_order_filled(self, asset: str, order_id: str, fill_notional_usd: float) -> None:
        """
        Record that an order was filled for an asset.
        
        This should be called from position_cache.on_fill or order_router on fill.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            order_id: Order ID
            fill_notional_usd: Fill notional in USD
        """
        # Remove from pending orders
        if asset in self._pending_orders:
            del self._pending_orders[asset]
            del self._pending_order_timestamps[asset]
        
        # Update position
        self._asset_positions[asset] = fill_notional_usd
        
        logger.info(
            "[GLOBAL-ALLOCATOR] Order filled: asset=%s order_id=%s notional=$%.2f position=$%.2f",
            asset, order_id, fill_notional_usd, self._asset_positions[asset]
        )
    
    def record_order_rejected(self, asset: str, order_id: str) -> None:
        """
        Record that an order was rejected for an asset.
        
        This should be called from order_router on rejection.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            order_id: Order ID
        """
        # Remove from pending orders
        if asset in self._pending_orders:
            del self._pending_orders[asset]
            del self._pending_order_timestamps[asset]
        
        logger.warning(
            "[GLOBAL-ALLOCATOR] Order rejected: asset=%s order_id=%s",
            asset, order_id
        )
    
    def record_position_closed(self, asset: str) -> None:
        """
        Record that a position was closed for an asset.
        
        This should be called when a position is fully closed (sell fill).
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
        """
        if asset in self._asset_positions:
            del self._asset_positions[asset]
            logger.info(
                "[GLOBAL-ALLOCATOR] Position closed: asset=%s",
                asset
            )
    
    def get_asset_positions(self) -> Dict[str, float]:
        """Get current asset positions."""
        return self._asset_positions.copy()
    
    def get_pending_orders(self) -> Dict[str, str]:
        """Get current pending orders."""
        return self._pending_orders.copy()
    
    def has_pending_order(self, asset: str) -> bool:
        """
        Check if an asset has a pending order (non-stale).
        
        This is used for pre-submission enforcement to prevent multiple orders
        for the same asset from being submitted before fills occur.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            
        Returns:
            True if asset has a non-stale pending order, False otherwise
        """
        if asset not in self._pending_orders:
            return False
        
        # Check if pending order is stale
        time_since_submit = time.time() - self._pending_order_timestamps.get(asset, 0)
        if time_since_submit >= self._pending_order_timeout:
            # Stale pending order - clear it
            logger.warning(
                "[GLOBAL-ALLOCATOR] Clearing stale pending order for %s: %.1fs old",
                asset, time_since_submit
            )
            del self._pending_orders[asset]
            del self._pending_order_timestamps[asset]
            return False
        
        return True


# Singleton instance for lifecycle callbacks
_global_allocator_instance: Optional[GlobalAllocator] = None

def get_global_allocator() -> Optional[GlobalAllocator]:
    """Get the singleton GlobalAllocator instance for lifecycle callbacks."""
    return _global_allocator_instance

def set_global_allocator(allocator: GlobalAllocator) -> None:
    """Set the singleton GlobalAllocator instance."""
    global _global_allocator_instance
    _global_allocator_instance = allocator


def create_global_allocator_from_envelope(envelope: Any) -> GlobalAllocator:
    """
    Create GlobalAllocator from risk envelope configuration.
    
    CRITICAL: Uses shared $1 pool model with per-asset edge thresholds aligned with risk_parameters.py.
    
    Args:
        envelope: Risk envelope instance
    
    Returns:
        Configured GlobalAllocator with shared $1 pool parameters and per-asset edge thresholds
    """
    venue_cap = envelope.max_total_notional_usd if hasattr(envelope, 'max_total_notional_usd') else 1.00
    
    # CRITICAL: Use the shared $1 pool parameters (no per-asset rescaling)
    min_edge_pct = 0.025  # 2026-07-14: Changed from 0.5% to 2.5% to match profile edge_bands (industry standard)
    min_confidence = 0.50  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence calculation (0.5 + edge/100)
    min_price_cents = 10  # 2026-07-12: Lower bound (10c) maintained for low-profit trap prevention
    max_price_cents = 75  # 2026-07-12: Expanded to 75c - YES prices consistently 60-97c in current market conditions
    max_single_asset_fraction = 1.00  # 100% - allows single asset to use full venue cap (shared pool)
    
    # 2026-07-14: Per-asset edge thresholds aligned with profile edge_bands (2.5% unified)
    # CRITICAL FIX: Updated to use unified 2.5% threshold from profile edge_bands (industry standard)
    # Industry standard for Kalshi: 3% raw edge minimum (Market Math, Beatpoly)
    # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
    per_asset_min_edge_pct = {
        "BTC": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
        "ETH": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
        "SOL": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
        "XRP": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
        "DOGE": 0.025,  # Unified edge_bands threshold (2.5% - industry standard)
    }
    
    # Optional: read allocator knobs from envelope if available
    if hasattr(envelope, 'allocator_config'):
        config = envelope.allocator_config
        min_edge_pct = config.get('min_edge_pct', 0.05)
        min_confidence = config.get('min_confidence', 0.65)
        min_price_cents = config.get('min_price_cents', 10)
        max_price_cents = config.get('max_price_cents', 75)  # 2026-07-12: Default 75c to match current market conditions
        max_single_asset_fraction = config.get('max_single_asset_fraction', 1.00)
        # Allow envelope to override per-asset thresholds if provided
        if 'per_asset_min_edge_pct' in config:
            per_asset_min_edge_pct = config['per_asset_min_edge_pct']
    
    return GlobalAllocator(
        venue_cap_usd=venue_cap,
        min_edge_pct=min_edge_pct,
        min_confidence=min_confidence,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
        max_single_asset_fraction=max_single_asset_fraction,
        per_asset_min_edge_pct=per_asset_min_edge_pct
    )
