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
- Entry prices in 5c-95c range (expanded for skewed markets)
- Confidence ≥ 50% (matches agent grid: 0.5 + edge/100), edge ≥ 2.0% (actual percentage)
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
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
    - Edge must be ≥ 2.0% (matches agent grid edge units - actual percentage)
    - Assets compete for capital (no per-asset budgets)
    """
    
    def __init__(
        self,
        venue_cap_usd: float = 1.00,
        min_edge_pct: float = 2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units (actual percentage, not decimal)
        min_confidence: float = 0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence calculation (0.5 + edge/100)
        min_price_cents: int = 5,  # 2026-07-10: Minimum entry price (5c) - expanded for skewed markets
        max_price_cents: int = 95,  # 2026-07-10: Maximum entry price (95c) - expanded for skewed markets
        max_single_asset_fraction: float = 1.00,  # Max 100% of cap per asset (allows single order to use full venue cap)
        enable_correlation_control: bool = False,
        # 2026-07-10: Per-asset edge thresholds aligned with risk_parameters.py market entry thresholds
        # This ensures global allocator doesn't filter candidates that pass signal generation
        per_asset_min_edge_pct: dict = None,
    ):
        self.venue_cap_usd = venue_cap_usd
        self.min_edge_pct = min_edge_pct
        self.min_confidence = min_confidence
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.max_single_asset_fraction = max_single_asset_fraction
        self.enable_correlation_control = enable_correlation_control
        
        # Per-asset edge thresholds (aligned with risk_parameters.py market entry thresholds)
        # If not provided, use defaults aligned with market entry thresholds
        if per_asset_min_edge_pct is None:
            self.per_asset_min_edge_pct = {
                "BTC": 1.75,   # EDGE_MARKET_ENTRY_BTC
                "ETH": 2.0,    # EDGE_MARKET_ENTRY_ETH
                "SOL": 2.5,    # EDGE_MARKET_ENTRY_SOL
                "XRP": 3.0,    # EDGE_MARKET_ENTRY_XRP
                "DOGE": 3.5,   # EDGE_MARKET_ENTRY_DOGE
            }
        else:
            self.per_asset_min_edge_pct = per_asset_min_edge_pct
        
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
        
        # Filter by price range (5c-95c)
        price_filtered = [c for c in conf_filtered if self.min_price_cents <= c.price_cents <= self.max_price_cents]
        if len(price_filtered) < len(conf_filtered):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates outside price range [%dc-%dc]",
                len(conf_filtered) - len(price_filtered), len(conf_filtered), self.min_price_cents, self.max_price_cents
            )
        
        if not price_filtered:
            logger.info("[GLOBAL-ALLOCATOR] No candidates passed all filters (edge, confidence, price)")
            return []
        
        # Sort by edge score (descending), then by price (ascending) to prioritize cheaper orders with similar edges
        sorted_candidates = sorted(price_filtered, key=lambda c: (c.edge_score, -c.notional_usd), reverse=True)
        logger.info(
            "[GLOBAL-ALLOCATOR] Sorted %d candidates by edge then price (best=%.3f%%, worst=%.3f%%)",
            len(sorted_candidates), sorted_candidates[0].edge_pct, sorted_candidates[-1].edge_pct
        )
        
        # Greedy fill under venue cap (shared $1 pool)
        chosen = []
        used_notional = 0.0
        asset_allocation = {}
        asset_order_count = {}  # Track order count per asset to enforce 1 order per asset
        
        for candidate in sorted_candidates:
            # CRITICAL: Enforce 1 contract per asset per window
            if candidate.asset in asset_order_count:
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: already has order in this window (1 order per asset limit)",
                    candidate.asset
                )
                continue
            
            # Check if this order would exceed venue cap (shared $1 pool)
            # If this is the first order and no orders chosen yet, try to fit it anyway
            # to ensure at least one order executes if possible
            if used_notional + candidate.notional_usd > self.venue_cap_usd:
                if not chosen:
                    # No orders yet - try to find a cheaper candidate that fits
                    logger.info(
                        "[GLOBAL-ALLOCATOR] First candidate %s exceeds cap ($%.2f > $%.2f), looking for cheaper alternative",
                        candidate.asset, candidate.notional_usd, self.venue_cap_usd
                    )
                    # Try to find the cheapest candidate that fits under cap
                    for alt_candidate in sorted_candidates:
                        if alt_candidate.asset in asset_order_count:
                            continue
                        if alt_candidate.notional_usd <= self.venue_cap_usd:
                            logger.info(
                                "[GLOBAL-ALLOCATOR] Found cheaper alternative %s ($%.2f <= $%.2f)",
                                alt_candidate.asset, alt_candidate.notional_usd, self.venue_cap_usd
                            )
                            # Use this candidate instead
                            candidate = alt_candidate
                            break
                    else:
                        # No affordable candidate found
                        logger.info(
                            "[GLOBAL-ALLOCATOR] SKIP %s: no affordable candidates under $%.2f cap",
                            candidate.asset, self.venue_cap_usd
                        )
                        continue
                else:
                    # Already have orders, skip this one
                    logger.info(
                        "[GLOBAL-ALLOCATOR] SKIP %s: would exceed shared $1 cap ($%.2f + $%.2f > $%.2f)",
                        candidate.asset, used_notional, candidate.notional_usd, self.venue_cap_usd
                    )
                    continue
            
            # Check per-asset concentration limit (should be 1.0 for shared pool model)
            asset_current = current_positions.get(candidate.asset, 0.0)
            asset_with_order = asset_allocation.get(candidate.asset, 0.0) + candidate.notional_usd
            max_asset_notional = self.venue_cap_usd * self.max_single_asset_fraction
            
            if asset_with_order > max_asset_notional:
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: would exceed max single asset allocation ($%.2f > $%.2f)",
                    candidate.asset, asset_with_order, max_asset_notional
                )
                continue
            
            # Add to chosen
            chosen.append(candidate)
            used_notional += candidate.notional_usd
            asset_allocation[candidate.asset] = asset_allocation.get(candidate.asset, 0.0) + candidate.notional_usd
            asset_order_count[candidate.asset] = asset_order_count.get(candidate.asset, 0) + 1
            
            logger.info(
                "[GLOBAL-ALLOCATOR] CHOOSE %s: edge=%.3f%%, conf=%.0f%%, price=%dc, notional=$%.2f, total_used=$%.2f",
                candidate.asset, candidate.edge_pct, candidate.confidence * 100, candidate.price_cents, candidate.notional_usd, used_notional
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
    min_edge_pct = 2.0  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units (actual percentage)
    min_confidence = 0.50  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence calculation (0.5 + edge/100)
    min_price_cents = 5  # 2026-07-10: Expanded from 10c to 5c for skewed markets
    max_price_cents = 95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
    max_single_asset_fraction = 1.00  # 100% - allows single asset to use full venue cap (shared pool)
    
    # 2026-07-10: Per-asset edge thresholds aligned with risk_parameters.py market entry thresholds
    per_asset_min_edge_pct = {
        "BTC": 1.75,   # EDGE_MARKET_ENTRY_BTC
        "ETH": 2.0,    # EDGE_MARKET_ENTRY_ETH
        "SOL": 2.5,    # EDGE_MARKET_ENTRY_SOL
        "XRP": 3.0,    # EDGE_MARKET_ENTRY_XRP
        "DOGE": 3.5,   # EDGE_MARKET_ENTRY_DOGE
    }
    
    # Optional: read allocator knobs from envelope if available
    if hasattr(envelope, 'allocator_config'):
        config = envelope.allocator_config
        min_edge_pct = config.get('min_edge_pct', 0.05)
        min_confidence = config.get('min_confidence', 0.65)
        min_price_cents = config.get('min_price_cents', 10)
        max_price_cents = config.get('max_price_cents', 50)
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
