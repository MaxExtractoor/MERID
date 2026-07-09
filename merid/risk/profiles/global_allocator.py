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
- Total exposure ≤ venue cap
- No artificial per-asset limits
- Concentration on highest expected returns
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
    
    Implements top-N edge knapsack under venue cap.
    """
    
    def __init__(
        self,
        venue_cap_usd: float = 1.00,
        min_edge_pct: float = 2.0,  # Minimum edge to be considered
        max_single_asset_fraction: float = 1.00,  # Max 100% of cap per asset (allows single order to use full venue cap)
        enable_correlation_control: bool = False,
    ):
        self.venue_cap_usd = venue_cap_usd
        self.min_edge_pct = min_edge_pct
        self.max_single_asset_fraction = max_single_asset_fraction
        self.enable_correlation_control = enable_correlation_control
        
        logger.info(
            "[GLOBAL-ALLOCATOR] Initialized: venue_cap=$%.2f, min_edge=%.1f%%, max_single=%.1f%%",
            venue_cap_usd, min_edge_pct, max_single_asset_fraction * 100
        )
    
    def allocate(
        self,
        candidates: List[OrderCandidate],
        current_positions: Optional[Dict[str, float]] = None
    ) -> List[OrderCandidate]:
        """
        Allocate orders based on edge ranking under venue cap.
        
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
        
        # Filter by minimum edge
        filtered = [c for c in candidates if c.edge_pct >= self.min_edge_pct]
        if len(filtered) < len(candidates):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates below min edge %.1f%%",
                len(candidates) - len(filtered), len(candidates), self.min_edge_pct
            )
        
        if not filtered:
            logger.info("[GLOBAL-ALLOCATOR] No candidates above minimum edge threshold")
            return []
        
        # Sort by edge score (descending)
        sorted_candidates = sorted(filtered, key=lambda c: c.edge_score, reverse=True)
        logger.info(
            "[GLOBAL-ALLOCATOR] Sorted %d candidates by edge score (best=%.1f%%, worst=%.1f%%)",
            len(sorted_candidates), sorted_candidates[0].edge_pct, sorted_candidates[-1].edge_pct
        )
        
        # Greedy fill under venue cap
        chosen = []
        used_notional = 0.0
        asset_allocation = {}
        
        for candidate in sorted_candidates:
            # Check if this order would exceed venue cap
            if used_notional + candidate.notional_usd > self.venue_cap_usd:
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: would exceed cap ($%.2f + $%.2f > $%.2f)",
                    candidate.asset, used_notional, candidate.notional_usd, self.venue_cap_usd
                )
                continue
            
            # Check per-asset concentration limit
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
            
            logger.info(
                "[GLOBAL-ALLOCATOR] CHOOSE %s: edge=%.1f%%, notional=$%.2f, total_used=$%.2f",
                candidate.asset, candidate.edge_pct, candidate.notional_usd, used_notional
            )
        
        logger.info(
            "[GLOBAL-ALLOCATOR] Allocation complete: %d/%d chosen, total_notional=$%.2f/%.2f",
            len(chosen), len(candidates), used_notional, self.venue_cap_usd
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
    
    Args:
        envelope: Risk envelope instance
    
    Returns:
        Configured GlobalAllocator
    """
    venue_cap = envelope.max_total_notional_usd if hasattr(envelope, 'max_total_notional_usd') else 1.00
    
    # Optional: read allocator knobs from envelope if available
    min_edge_pct = 2.0
    max_single_asset_fraction = 0.70
    
    if hasattr(envelope, 'allocator_config'):
        config = envelope.allocator_config
        min_edge_pct = config.get('min_edge_pct', 2.0)
        max_single_asset_fraction = config.get('max_single_asset_fraction', 0.70)
    
    return GlobalAllocator(
        venue_cap_usd=venue_cap,
        min_edge_pct=min_edge_pct,
        max_single_asset_fraction=max_single_asset_fraction
    )
