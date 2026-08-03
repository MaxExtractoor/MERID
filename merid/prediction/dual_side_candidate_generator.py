"""
Dual-Side Candidate Generation for Kalshi 15m Crypto Trading

Implements per-asset dual-side candidate generation with edge-aware selection.
For each asset (BTC, ETH, SOL, XRP, DOGE), generates both YES and NO candidates,
computes executable edge for each side, and selects the best side based on edge-aware logic.

Key features:
- Per-asset dual-side candidate generation
- Executable edge computation using spread_edge_analytics
- Edge-aware filtering (spread/edge ratio, minimum executable edge)
- Best side selection per asset
- Liquidity sanity checks
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from utils.logger import get_logger

logger = get_logger("merid.prediction.dual_side_candidate_generator")


@dataclass
class DualSideCandidate:
    """Represents a candidate with both YES and NO side metrics."""
    market_id: str
    asset: str
    series_ticker: str
    ticker: str
    
    # YES side metrics
    yes_edge_exec_cents: float
    yes_spread_cents: int
    yes_raw_edge_cents: float
    yes_spread_to_edge_ratio: float
    
    # NO side metrics
    no_edge_exec_cents: float
    no_spread_cents: int
    no_raw_edge_cents: float
    no_spread_to_edge_ratio: float
    
    # Depth metrics
    yes_depth: int
    no_depth: int
    total_depth: int
    
    # Selected side
    selected_side: Optional[str] = None  # "yes", "no", or None if neither passes
    selected_edge_exec_cents: float = 0.0
    
    # Metadata
    p_hat_yes_cents: float = 0.0
    p_hat_no_cents: float = 0.0  # 2026-07-25: Added for dual-side edge-aware gating
    minutes_to_expiry: float = 0.0
    timestamp: float = 0.0
    
    # Rejection reasons
    yes_rejection_reason: Optional[str] = None
    no_rejection_reason: Optional[str] = None


@dataclass
class PerAssetCandidateSummary:
    """Summary of candidates for a single asset."""
    asset: str
    total_markets_scanned: int
    yes_candidates: int
    no_candidates: int
    dual_side_candidates: int  # Markets where both sides passed
    best_candidate: Optional[DualSideCandidate] = None


class DualSideCandidateGenerator:
    """
    Generates dual-side candidates per asset with edge-aware selection.
    
    For each asset (BTC, ETH, SOL, XRP, DOGE):
    1. For each eligible 15m market, compute YES and NO executable edges
    2. Filter sides where edge_exec <= 0 or spread/edge > 0.4
    3. Select best side per market based on executable edge
    4. Return top N candidates per asset
    """
    
    def __init__(
        self,
        min_executable_edge_cents: float = 3.0,
        max_spread_to_edge_ratio: float = 0.4,
        max_spread_cents: Optional[int] = None,
        min_yes_depth: int = 1,
        min_no_depth: int = 1,
        min_total_depth: int = 25,
        max_candidates_per_asset: int = 3
    ):
        self.min_executable_edge_cents = min_executable_edge_cents
        self.max_spread_to_edge_ratio = max_spread_to_edge_ratio
        self.max_spread_cents = max_spread_cents
        self.min_yes_depth = min_yes_depth
        self.min_no_depth = min_no_depth
        self.min_total_depth = min_total_depth
        self.max_candidates_per_asset = max_candidates_per_asset
        
        logger.info(
            "[DUAL-SIDE-GEN] Initialized with min_exec_edge=%.1fc, max_spread/edge=%.2f, "
            "max_spread=%s, min_depth=(%d,%d,%d), max_per_asset=%d",
            min_executable_edge_cents, max_spread_to_edge_ratio,
            max_spread_cents, min_yes_depth, min_no_depth, min_total_depth,
            max_candidates_per_asset
        )
    
    def generate_dual_side_candidates(
        self,
        markets: List[Dict[str, Any]],
        asset: str,
        market_state_store: Any,
        spot_service: Any,
        signal_service: Any
    ) -> Tuple[List[DualSideCandidate], PerAssetCandidateSummary]:
        """
        Generate dual-side candidates for a single asset.
        
        Args:
            markets: List of market dictionaries for the asset
            asset: Asset identifier (BTC, ETH, SOL, XRP, DOGE)
            market_state_store: Market state store instance
            spot_service: Spot price service instance
            signal_service: Signal service for p_hat_yes estimates
        
        Returns:
            Tuple of (candidates, summary)
        """
        summary = PerAssetCandidateSummary(
            asset=asset,
            total_markets_scanned=len(markets),
            yes_candidates=0,
            no_candidates=0,
            dual_side_candidates=0
        )
        
        candidates = []
        
        for market in markets:
            try:
                candidate = self._create_dual_side_candidate(
                    market, asset, market_state_store, spot_service, signal_service
                )
                if candidate:
                    candidates.append(candidate)
                    
                    # Update summary counts
                    if candidate.yes_rejection_reason is None:
                        summary.yes_candidates += 1
                    if candidate.no_rejection_reason is None:
                        summary.no_candidates += 1
                    if (candidate.yes_rejection_reason is None and 
                        candidate.no_rejection_reason is None):
                        summary.dual_side_candidates += 1
                        
            except Exception as e:
                logger.error(
                    "[DUAL-SIDE-GEN] Error creating candidate for market %s: %s",
                    market.get("market_id", "unknown"), e, exc_info=True
                )
                continue
        
        # Select best candidate per asset
        if candidates:
            # Sort by selected edge (descending)
            candidates_with_selection = [c for c in candidates if c.selected_side is not None]
            candidates_with_selection.sort(
                key=lambda c: c.selected_edge_exec_cents,
                reverse=True
            )
            
            # Take top N
            top_candidates = candidates_with_selection[:self.max_candidates_per_asset]
            if top_candidates:
                summary.best_candidate = top_candidates[0]
            
            candidates = top_candidates
        
        logger.info(
            "[DUAL-SIDE-GEN] asset=%s scanned=%d yes=%d no=%d dual=%d final=%d",
            asset, summary.total_markets_scanned, summary.yes_candidates,
            summary.no_candidates, summary.dual_side_candidates, len(candidates)
        )
        
        return candidates, summary
    
    def _create_dual_side_candidate(
        self,
        market: Dict[str, Any],
        asset: str,
        market_state_store: Any,
        spot_service: Any,
        signal_service: Any
    ) -> Optional[DualSideCandidate]:
        """Create a dual-side candidate for a single market."""
        market_id = market.get("market_id")
        if not market_id:
            return None
        
        # Get market state
        state = market_state_store.get(market_id)
        if not state or not getattr(state, 'book_initialized', False):
            return None
        
        # Extract orderbook data
        yes_bid_cents = getattr(state, 'best_bid_cents', 0)
        no_bid_cents = getattr(state, 'best_ask_cents', 0)  # NO bid is stored as ask in some implementations
        
        # Handle different state representations
        # Some implementations store NO bid separately
        if hasattr(state, 'no_bid_cents'):
            no_bid_cents = state.no_bid_cents
        
        # Depth
        yes_depth = getattr(state, 'depth_yes', 0)
        no_depth = getattr(state, 'depth_no', 0)
        
        # Get probability estimate from signal service
        p_hat_yes_cents = self._get_probability_estimate(
            signal_service, market_id, asset, spot_service
        )
        if p_hat_yes_cents is None:
            return None
        
        # Import edge analytics
        try:
            from merid.event_venues.kalshi.spread_edge_analytics import (
                compute_canonical_spreads,
                compute_per_side_edges,
                edge_aware_microstructure_gate
            )
        except ImportError:
            logger.warning("[DUAL-SIDE-GEN] spread_edge_analytics not available")
            return None
        
        # Compute spreads and edges
        spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
        # CRITICAL FIX 2026-07-28: Pass order_side parameter for correct price usage
        # In dual-side candidate generation, we're not placing an order yet, so use None (market bids)
        yes_edge, no_edge = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_side=None)
        
        # Check YES side
        yes_passes, yes_reason = edge_aware_microstructure_gate(
            edge_metrics=yes_edge,
            min_executable_edge_cents=self.min_executable_edge_cents,
            max_spread_to_edge_ratio=self.max_spread_to_edge_ratio,
            max_spread_cents=self.max_spread_cents
        )
        
        # Check NO side
        no_passes, no_reason = edge_aware_microstructure_gate(
            edge_metrics=no_edge,
            min_executable_edge_cents=self.min_executable_edge_cents,
            max_spread_to_edge_ratio=self.max_spread_to_edge_ratio,
            max_spread_cents=self.max_spread_cents
        )
        
        # Check depth
        depth_passes = (
            yes_depth >= self.min_yes_depth and
            no_depth >= self.min_no_depth and
            (yes_depth + no_depth) >= self.min_total_depth
        )
        
        if not depth_passes:
            yes_reason = yes_reason or "depth_too_low"
            no_reason = no_reason or "depth_too_low"
            yes_passes = False
            no_passes = False
        
        # Select best side
        selected_side = None
        selected_edge_exec = 0.0
        
        if yes_passes and no_passes:
            # Both pass - select by higher executable edge
            if yes_edge.executable_edge_cents >= no_edge.executable_edge_cents:
                selected_side = "yes"
                selected_edge_exec = yes_edge.executable_edge_cents
            else:
                selected_side = "no"
                selected_edge_exec = no_edge.executable_edge_cents
        elif yes_passes:
            selected_side = "yes"
            selected_edge_exec = yes_edge.executable_edge_cents
        elif no_passes:
            selected_side = "no"
            selected_edge_exec = no_edge.executable_edge_cents
        
        # Create candidate
        # 2026-07-25: Compute p_hat_no_cents as complement to p_hat_yes_cents
        p_hat_no_cents = 100.0 - p_hat_yes_cents
        candidate = DualSideCandidate(
            market_id=market_id,
            asset=asset,
            series_ticker=market.get("series_ticker", ""),
            ticker=market.get("ticker", ""),
            yes_edge_exec_cents=yes_edge.executable_edge_cents,
            yes_spread_cents=yes_edge.spread_cents,
            yes_raw_edge_cents=yes_edge.raw_edge_cents,
            yes_spread_to_edge_ratio=yes_edge.spread_to_edge_ratio,
            no_edge_exec_cents=no_edge.executable_edge_cents,
            no_spread_cents=no_edge.spread_cents,
            no_raw_edge_cents=no_edge.raw_edge_cents,
            no_spread_to_edge_ratio=no_edge.spread_to_edge_ratio,
            yes_depth=yes_depth,
            no_depth=no_depth,
            total_depth=yes_depth + no_depth,
            selected_side=selected_side,
            selected_edge_exec_cents=selected_edge_exec,
            p_hat_yes_cents=p_hat_yes_cents,
            p_hat_no_cents=p_hat_no_cents,
            minutes_to_expiry=market.get("minutes_to_expiry", 0.0),
            yes_rejection_reason=None if yes_passes else yes_reason,
            no_rejection_reason=None if no_passes else no_reason,
            timestamp=state.last_update_ts if hasattr(state, 'last_update_ts') else 0.0
        )
        
        return candidate
    
    def _get_probability_estimate(
        self,
        signal_service: Any,
        market_id: str,
        asset: str,
        spot_service: Any
    ) -> Optional[float]:
        """Get probability estimate (p_hat_yes) from signal service.
        
        This is a placeholder - the actual implementation depends on your
        signal service API. You may need to adapt this to your specific
        signal service interface.
        """
        try:
            # Try to get probability from signal service
            # This is a generic implementation - adapt to your actual API
            if hasattr(signal_service, 'get_probability'):
                prob = signal_service.get_probability(market_id)
                if prob is not None:
                    return prob * 100.0  # Convert to cents
            
            # Fallback: use spot price to estimate probability
            # This is a simplified placeholder - real implementation should use your signal model
            if spot_service:
                spot = spot_service.get(asset)
                if spot and hasattr(spot, 'price'):
                    # Very rough placeholder - replace with actual signal logic
                    # This just returns 50c (neutral) as a fallback
                    logger.warning(
                        "[DUAL-SIDE-GEN] Using neutral probability (50c) for %s - implement actual signal logic",
                        market_id
                    )
                    return 50.0
            
            return None
            
        except Exception as e:
            logger.error(
                "[DUAL-SIDE-GEN] Error getting probability estimate for %s: %s",
                market_id, e, exc_info=True
            )
            return None


def format_dual_side_candidate_table(candidates: List[DualSideCandidate]) -> str:
    """Format dual-side candidates as a table for logging/analysis.
    
    Example output:
    | Asset | Market | YES Edge | NO Edge | Selected | Selected Edge |
    |-------|--------|---------|---------|----------|---------------|
    | BTC   | m1     | 6.5c    | 0.5c    | YES      | 6.5c          |
    | ETH   | m2     | 5.5c    | -2.0c   | YES      | 5.5c          |
    | SOL   | m3     | -1.0c   | 9.0c    | NO       | 9.0c          |
    """
    if not candidates:
        return "No dual-side candidates"
    
    lines = [
        "| Asset | Market | YES Edge | NO Edge | Selected | Selected Edge |",
        "|-------|--------|---------|---------|----------|---------------|",
    ]
    
    for c in candidates:
        lines.append(
            f"| {c.asset} | {c.ticker} | "
            f"{c.yes_edge_exec_cents:.1f}c | "
            f"{c.no_edge_exec_cents:.1f}c | "
            f"{c.selected_side or 'N/A'} | "
            f"{c.selected_edge_exec_cents:.1f}c |"
        )
    
    return "\n".join(lines)


# Global generator instance
_generator_instance: Optional[DualSideCandidateGenerator] = None


def get_dual_side_generator() -> DualSideCandidateGenerator:
    """Get the global dual-side candidate generator instance."""
    global _generator_instance
    
    if _generator_instance is None:
        _generator_instance = DualSideCandidateGenerator()
    
    return _generator_instance


def reset_dual_side_generator() -> None:
    """Reset the global dual-side candidate generator instance."""
    global _generator_instance
    _generator_instance = None
