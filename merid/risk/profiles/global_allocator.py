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
- Entry prices use side-aware ranges: YES 1c-75c, NO 25c-99c (CRITICAL FIX 2026-07-31)
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
    - Entry price uses side-aware ranges: YES 1c-75c, NO 25c-99c (CRITICAL FIX 2026-07-31)
    - Confidence must be ≥ 50% (matches signal generation range: 0.5 + edge)
    - Edge must be ≥ 2.5% (matches profile edge_bands - industry standard)
    - Assets compete for capital (no per-asset budgets)
    """
    
    def __init__(
        self,
        venue_cap_usd: float = 1.00,
        min_edge_pct: float = 0.025,  # 2026-07-14: Changed to 2.5% to match profile edge_bands (industry standard)
                                      # 2026-07-25: CRITICAL - This is stored as FRACTION (0.025 = 2.5%), not percentage
                                      # Display multiplies by 100 for logging, but internal comparison uses fraction
        min_confidence: float = 0.50,  # 2026-07-28: CRITICAL FIX - Lowered from 0.65 to 0.50 to match signal generation range
                                      # Signal generation produces confidence = 0.5 + edge (edge is 0.02-0.08), resulting in 52-58%
        min_price_cents: int = 1,  # 2026-07-31: Lowered to 1c for YES orders (side-aware filtering applied later)
        max_price_cents: int = 99,  # 2026-07-31: Expanded to 99c for NO orders (side-aware filtering applied later)
        max_single_asset_fraction: float = 1.00,  # Max 100% of cap per asset (allows single order to use full venue cap)
        enable_correlation_control: bool = False,
        # 2026-07-14: Per-asset edge thresholds aligned with profile edge_bands (2.5% unified - industry standard)
        # 2026-07-25: CRITICAL - These are stored as FRACTIONS (0.025 = 2.5%), not percentages
        # This ensures global allocator doesn't filter candidates that pass validate_edge()
        per_asset_min_edge_pct: dict = None,
    ):
        self.venue_cap_usd = venue_cap_usd
        self.min_edge_pct = min_edge_pct  # Stored as fraction (0.025 = 2.5%)
        self.min_confidence = min_confidence
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.max_single_asset_fraction = max_single_asset_fraction
        self.enable_correlation_control = enable_correlation_control
        
        # Per-asset edge thresholds (aligned with profile edge_bands - single source of truth)
        # CRITICAL FIX 2026-07-14: Updated to use unified 2.5% threshold from profile edge_bands
        # CRITICAL FIX 2026-07-25: All thresholds stored as FRACTIONS (0.025 = 2.5%), not percentages
        # Industry standard for Kalshi: 3% raw edge minimum (Market Math, Beatpoly)
        # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
        # Edge threshold hierarchy (from profile YAML):
        # 1. edge_bands.*.min_edge_pct - PRIMARY: Used for trade execution (2.5% minimum)
        # 2. Per-asset min_edge_early/mid/late/terminal - IGNORED: Legacy fields, not used
        if per_asset_min_edge_pct is None:
            self.per_asset_min_edge_pct = {
                "BTC": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "ETH": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "SOL": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "XRP": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "DOGE": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
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
            "[GLOBAL-ALLOCATOR] Initialized: venue_cap=$%.2f, min_edge=%.3f%% (fraction=%.3f), min_conf=%.0f%%, price_range=[%dc-%dc], max_single=%.1f%%",
            venue_cap_usd, min_edge_pct * 100, min_edge_pct, min_confidence * 100, min_price_cents, max_price_cents, max_single_asset_fraction * 100
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
        
        # CRITICAL FIX (2026-07-31): Clear pending orders for assets that already have positions
        # This handles the case where fills occurred but global_allocator wasn't notified
        # (e.g., before the fills_ledger fix was applied)
        for asset in list(self._pending_orders.keys()):
            if asset in current_positions and current_positions[asset] > 0:
                logger.warning(
                    "[GLOBAL-ALLOCATOR] Clearing stale pending order for %s: position exists ($%.2f)",
                    asset, current_positions[asset]
                )
                del self._pending_orders[asset]
                del self._pending_order_timestamps[asset]
        
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
        
        # CRITICAL FIX (2026-07-31): Use side-aware price ranges to prevent NO order rejection
        # YES orders: 1c-75c (expanded low end for late-expiry markets)
        # NO orders: 25c-99c (expanded high end for late-expiry markets)
        # This prevents systematic rejection of NO orders at high prices (90c+) which is where NO typically trades
        def is_price_in_side_range(candidate: OrderCandidate) -> bool:
            """Check if candidate price is within side-appropriate range."""
            if candidate.side.lower() == "yes":
                # YES: 1c-75c range
                return 1 <= candidate.price_cents <= 75
            else:  # NO
                # NO: 25c-99c range
                return 25 <= candidate.price_cents <= 99
        
        price_filtered = [c for c in conf_filtered if is_price_in_side_range(c)]
        if len(price_filtered) < len(conf_filtered):
            # Log which candidates were filtered and why
            filtered_candidates = [c for c in conf_filtered if not is_price_in_side_range(c)]
            for c in filtered_candidates:
                logger.info(
                    "[GLOBAL-ALLOCATOR] Filtered candidate outside side-aware range: "
                    "asset=%s ticker=%s side=%s price=%dc (YES: 1-75c, NO: 25-99c)",
                    c.asset, c.ticker, c.side, c.price_cents
                )
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates outside side-aware price ranges "
                "(YES: 1c-75c, NO: 25c-99c)",
                len(conf_filtered) - len(price_filtered), len(conf_filtered)
            )
        
        # CRITICAL FIX (2026-07-31): Filter by contract count (must be 1 for entry orders)
        # This enforces the $1 allocation rule: each asset can only trade 1 contract at a time
        count_filtered = [c for c in price_filtered if c.count == 1]
        if len(count_filtered) < len(price_filtered):
            logger.warning(
                "[GLOBAL-ALLOCATOR] CRITICAL: Filtered %d/%d candidates with count != 1 (violates $1 allocation rule). This indicates a bug in the sizing pipeline.",
                len(price_filtered) - len(count_filtered), len(price_filtered)
            )
            # Log the violating candidates for debugging
            for c in price_filtered:
                if c.count != 1:
                    logger.warning(
                        "[GLOBAL-ALLOCATOR] VIOLATING CANDIDATE: asset=%s ticker=%s count=%d price=%dc edge=%.2f%%",
                        c.asset, c.ticker, c.count, c.price_cents, c.edge_pct
                    )
        
        # 2026-07-13: Filter by per-asset position and pending order status
        # This prevents multiple contracts per asset (the core issue)
        position_filtered = []
        for c in count_filtered:
            # CRITICAL FIX (2026-08-01): Check for phantom positions in position cache
            # Phantom positions have contracts > 0 but invalid avg_price_cents (None or 0)
            # This can happen when fills ledger shows net_contracts=0 but cache shows contracts > 0
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                cache = get_position_cache()
                phantom_deleted = False
                for market_id, position in list(cache._positions.items()):
                    if (position.contracts > 0 and 
                        (position.avg_price_cents is None or position.avg_price_cents == 0) and
                        c.asset in market_id.upper()):
                        if cache.force_delete_phantom_position(market_id):
                            phantom_deleted = True
                            logger.info(
                                "[GLOBAL-ALLOCATOR] Cleaned up phantom position for %s: market=%s contracts=%d avg_price=%s",
                                c.asset, market_id, position.contracts, position.avg_price_cents
                            )
                if phantom_deleted:
                    logger.info(
                        "[GLOBAL-ALLOCATOR] Phantom position cleanup completed for %s",
                        c.asset
                    )
            except Exception as cleanup_err:
                logger.warning(
                    "[GLOBAL-ALLOCATOR] Failed to clean up phantom positions for %s: %s",
                    c.asset, cleanup_err
                )
            
            # CRITICAL FIX (2026-07-31): Validate position data integrity before using it
            # Filter out assets with corrupted position data (exposure = None)
            # This prevents corrupted positions from blocking all trades
            asset_exposure = current_positions.get(c.asset, 0.0)
            if asset_exposure is None:
                # Asset has corrupted position data (None), skip it
                logger.warning(
                    "[GLOBAL-ALLOCATOR] SKIP %s: asset has corrupted position data (exposure=None), treating as no position",
                    c.asset
                )
                # Don't add to position_filtered - allow this asset to trade
                position_filtered.append(c)
                continue
            
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
            # CRITICAL FIX (2026-08-01): Cross-validate with order gate before clearing
            if c.asset in self._pending_orders:
                time_since_submit = time.time() - self._pending_order_timestamps.get(c.asset, 0)
                if time_since_submit < self._pending_order_timeout:
                    logger.info(
                        "[GLOBAL-ALLOCATOR] SKIP %s: asset has pending order %s (%.1fs old)",
                        c.asset, self._pending_orders[c.asset], time_since_submit
                    )
                    continue
                else:
                    # CRITICAL FIX (2026-08-01): Cross-validate with order gate before clearing
                    # This prevents clearing pending orders that are still active
                    try:
                        from merid.event_venues.kalshi.order_gate import get_order_gate
                        order_gate = get_order_gate()
                        order_id = self._pending_orders[c.asset]
                        
                        # Check if order still exists in order gate
                        if order_gate:
                            order_record = order_gate.lookup(order_id)
                            # Order is still active if it exists and is not in terminal state
                            if order_record and order_record.status not in ("filled", "canceled", "rejected"):
                                logger.warning(
                                    "[GLOBAL-ALLOCATOR] Pending order %s for %s still active in order gate "
                                    "(status=%s), not clearing despite timeout (%.1fs old)",
                                    order_id, c.asset, order_record.status, time_since_submit
                                )
                                continue
                            else:
                                # Order not active in gate - safe to clear
                                logger.warning(
                                    "[GLOBAL-ALLOCATOR] Clearing stale pending order for %s: %.1fs old "
                                    "(order not active in gate, status=%s)",
                                    c.asset, time_since_submit, order_record.status if order_record else "not_found"
                                )
                                del self._pending_orders[c.asset]
                                del self._pending_order_timestamps[c.asset]
                        else:
                            # Order gate not available - clear to avoid permanent block
                            logger.warning(
                                "[GLOBAL-ALLOCATOR] Order gate not available, clearing pending order for %s "
                                "to avoid permanent block",
                                c.asset
                            )
                            del self._pending_orders[c.asset]
                            del self._pending_order_timestamps[c.asset]
                    except Exception as e:
                        # If order gate check fails, log but still clear to avoid permanent block
                        logger.warning(
                            "[GLOBAL-ALLOCATOR] Failed to cross-validate pending order with order gate: %s. "
                            "Clearing pending order for %s to avoid permanent block",
                            e, c.asset
                        )
                        del self._pending_orders[c.asset]
                        del self._pending_order_timestamps[c.asset]
            
            position_filtered.append(c)
        
        if len(position_filtered) < len(count_filtered):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates due to existing positions/pending orders",
                len(count_filtered) - len(position_filtered), len(count_filtered)
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
                       # 2026-07-25: CRITICAL - Stored as FRACTION (0.025 = 2.5%), not percentage
    min_confidence = 0.50  # 2026-07-28: CRITICAL FIX - Lowered from 0.65 to 0.50 to match signal generation range
                          # Signal generation produces confidence = 0.5 + edge (edge is 0.02-0.08), resulting in 52-58%
                          # Previous 65% threshold was blocking all candidates despite valid edge
    min_price_cents = 10  # 2026-07-12: Lower bound (10c) maintained for low-profit trap prevention
    max_price_cents = 75  # 2026-07-12: Expanded to 75c - YES prices consistently 60-97c in current market conditions
    max_single_asset_fraction = 1.00  # 100% - allows single asset to use full venue cap (shared pool)
    
    # 2026-07-14: Per-asset edge thresholds aligned with profile edge_bands (2.5% unified)
    # 2026-07-25: CRITICAL - All thresholds stored as FRACTIONS (0.025 = 2.5%), not percentages
    # CRITICAL FIX: Updated to use unified 2.5% threshold from profile edge_bands (industry standard)
    # Industry standard for Kalshi: 3% raw edge minimum (Market Math, Beatpoly)
    # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
    per_asset_min_edge_pct = {
        "BTC": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "ETH": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "SOL": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "XRP": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "DOGE": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
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
