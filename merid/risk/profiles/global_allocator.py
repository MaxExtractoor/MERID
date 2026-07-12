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
        min_price_cents: int = 10,  # 2026-07-12: Lower bound (10c) maintained for low-profit trap prevention
        max_price_cents: int = 75,  # 2026-07-12: Expanded to 75c - YES prices consistently 60-97c in current market conditions
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
        
        # Filter by price range (10c-75c canonical range)
        price_filtered = [c for c in conf_filtered if self.min_price_cents <= c.price_cents <= self.max_price_cents]
        if len(price_filtered) < len(conf_filtered):
            logger.info(
                "[GLOBAL-ALLOCATOR] Filtered %d/%d candidates outside price range [%dc-%dc]",
                len(conf_filtered) - len(price_filtered), len(conf_filtered), self.min_price_cents, self.max_price_cents
            )
        
        if not price_filtered:
            logger.info("[GLOBAL-ALLOCATOR] No candidates passed all filters (edge, confidence, price)")
            return []
        
        # Optimal knapsack-style allocation under $1 cap
        # For small asset universe (5 assets), brute-force all combinations to find optimal
        # This ensures we get the best combination of edges that fits under cap
        from itertools import combinations
        
        # Group candidates by asset (1 per asset max)
        asset_candidates = {}
        for candidate in price_filtered:
            if candidate.asset not in asset_candidates:
                asset_candidates[candidate.asset] = candidate  # Keep best per asset (already sorted by edge)
        
        unique_candidates = list(asset_candidates.values())
        logger.info(
            "[GLOBAL-ALLOCATOR] Evaluating %d unique candidates (1 per asset) for optimal $1 cap allocation",
            len(unique_candidates)
        )
        
        best_combination = []
        best_total_edge = 0.0
        best_total_notional = 0.0
        
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
                
                # Prefer combination with higher total edge
                # If tied, prefer lower notional (cheaper)
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
    min_price_cents = 10  # 2026-07-12: Lower bound (10c) maintained for low-profit trap prevention
    max_price_cents = 75  # 2026-07-12: Expanded to 75c - YES prices consistently 60-97c in current market conditions
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
