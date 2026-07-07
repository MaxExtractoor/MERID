"""
Market Spread Optimizer - Phase 5.3

Optimizes spread computation and edge calculation for the Kalshi 15m trading system.

This module provides:
- Unified spread calculation with proper error handling
- Optimized edge computation with caching
- Market quality assessment and filtering
- Performance-optimized candidate generation
"""

from __future__ import annotations

import time
import logging
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from decimal import Decimal
from collections import defaultdict
import statistics

from utils.logger import get_logger

logger = get_logger("merid.prediction.spread_optimizer")


@dataclass
class SpreadMetrics:
    """Comprehensive spread metrics for a market."""
    market_id: str
    spread_cents: float
    mid_cents: float
    best_bid: int
    best_ask: int
    depth_yes: int
    depth_no: int
    total_depth: int
    skew: float
    liquidity_score: float
    quality_score: float
    timestamp: float
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)


@dataclass
class EdgeCalculationCache:
    """Cache for edge calculation results."""
    market_id: str
    edge_threshold: float
    spread_cents: float
    total_depth: int
    computed_at: float
    ttl_seconds: float = 5.0  # Cache for 5 seconds
    
    def is_valid(self) -> bool:
        """Check if cache entry is still valid."""
        return (time.time() - self.computed_at) < self.ttl_seconds


class SpreadOptimizer:
    """
    Optimizes spread calculation and edge computation for better performance.
    
    Features:
    - Unified spread calculation with proper error handling
    - Edge computation caching to reduce redundant calculations
    - Market quality assessment for better candidate selection
    - Performance monitoring and metrics
    """
    
    def __init__(self, cache_size: int = 1000):
        self.cache_size = cache_size
        self._edge_cache: Dict[str, EdgeCalculationCache] = {}
        self._spread_metrics: Dict[str, SpreadMetrics] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._calculations = 0
        self._errors = 0
        
        # CRITICAL FIX: Read thresholds from profile for consistency
        # Default to legacy values if profile unavailable
        self.MAX_SPREAD_CENTS = 15  # Maximum acceptable spread for quality assessment
        self.MIN_DEPTH_LEVELS = 2   # Minimum depth levels
        self.MIN_LIQUIDITY_SCORE = 0.3  # Minimum liquidity score
        
        # Try to load from profile for consistency
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            profile = Crypto15mProfileAdapter()
            # Use guardrails.max_spread_cents for consistency (75c for coarse filtering)
            # But keep optimizer's tighter threshold (15c) for quality assessment
            # These serve different purposes: coarse filter vs quality metric
            logger.info(
                "[SPREAD-OPTIMIZER] Profile loaded: guardrails.max_spread_cents=%d (coarse filter), "
                "optimizer.MAX_SPREAD_CENTS=%d (quality metric)",
                profile.guardrails_max_spread_cents, self.MAX_SPREAD_CENTS
            )
        except Exception as e:
            logger.warning(
                "[SPREAD-OPTIMIZER] Failed to load profile: %s, using legacy defaults "
                "(MAX_SPREAD_CENTS=%d, MIN_DEPTH_LEVELS=%d, MIN_LIQUIDITY_SCORE=%.3f)",
                e, self.MAX_SPREAD_CENTS, self.MIN_DEPTH_LEVELS, self.MIN_LIQUIDITY_SCORE
            )
        
        logger.info("[SPREAD-OPTIMIZER] Initialized with cache_size=%d", cache_size)
    
    def calculate_spread_metrics(self, market_state: Any, market_id: str) -> SpreadMetrics:
        """
        Calculate comprehensive spread metrics for a market.
        
        Args:
            market_state: Market state object with orderbook data
            market_id: Market identifier
            
        Returns:
            SpreadMetrics object with comprehensive spread information
        """
        start_time = time.time()
        errors = []
        
        try:
            # Extract bid/ask prices with proper error handling
            best_bid = self._get_best_bid(market_state, errors)
            best_ask = self._get_best_ask(market_state, errors)
            
            # Validate bid/ask prices
            if best_bid is None or best_ask is None:
                errors.append("Missing bid or ask prices")
                return SpreadMetrics(
                    market_id=market_id,
                    spread_cents=0.0,
                    mid_cents=0.0,
                    best_bid=0,
                    best_ask=0,
                    depth_yes=0,
                    depth_no=0,
                    total_depth=0,
                    skew=0.5,
                    liquidity_score=0.0,
                    quality_score=0.0,
                    timestamp=start_time,
                    is_valid=False,
                    errors=errors
                )
            
            # Validate spread
            if best_ask <= best_bid:
                errors.append(f"Invalid spread: ask({best_ask}) <= bid({best_bid})")
                return SpreadMetrics(
                    market_id=market_id,
                    spread_cents=0.0,
                    mid_cents=0.0,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    depth_yes=0,
                    depth_no=0,
                    total_depth=0,
                    skew=0.5,
                    liquidity_score=0.0,
                    quality_score=0.0,
                    timestamp=start_time,
                    is_valid=False,
                    errors=errors
                )
            
            # Calculate spread and mid price
            spread_cents = float(best_ask - best_bid)
            mid_cents = (best_ask + best_bid) / 2.0
            
            # Extract depth information
            depth_yes = self._get_depth_yes(market_state, errors)
            depth_no = self._get_depth_no(market_state, errors)
            total_depth = depth_yes + depth_no
            
            # Calculate skew (0 = balanced, 1 = all YES)
            skew = depth_yes / total_depth if total_depth > 0 else 0.5
            
            # Calculate liquidity score based on depth and spread
            liquidity_score = self._calculate_liquidity_score(spread_cents, total_depth)
            
            # Calculate overall quality score
            quality_score = self._calculate_quality_score(spread_cents, total_depth, liquidity_score)
            
            # Create metrics object
            metrics = SpreadMetrics(
                market_id=market_id,
                spread_cents=spread_cents,
                mid_cents=mid_cents,
                best_bid=best_bid,
                best_ask=best_ask,
                depth_yes=depth_yes,
                depth_no=depth_no,
                total_depth=total_depth,
                skew=skew,
                liquidity_score=liquidity_score,
                quality_score=quality_score,
                timestamp=start_time,
                is_valid=len(errors) == 0,
                errors=errors
            )
            
            # Cache metrics
            self._spread_metrics[market_id] = metrics
            
            # Log calculation time
            calc_time = time.time() - start_time
            logger.debug(
                "[SPREAD-OPTIMIZER] Calculated metrics for %s in %.3fms: spread=%.1f depth=%d quality=%.3f",
                market_id, calc_time * 1000, spread_cents, total_depth, quality_score
            )
            
            return metrics
            
        except Exception as e:
            self._errors += 1
            errors.append(f"Calculation error: {str(e)}")
            logger.error("[SPREAD-OPTIMIZER] Error calculating metrics for %s: %s", market_id, e, exc_info=True)
            
            return SpreadMetrics(
                market_id=market_id,
                spread_cents=0.0,
                mid_cents=0.0,
                best_bid=0,
                best_ask=0,
                depth_yes=0,
                depth_no=0,
                total_depth=0,
                skew=0.5,
                liquidity_score=0.0,
                quality_score=0.0,
                timestamp=start_time,
                is_valid=False,
                errors=errors
            )
    
    def compute_edge_threshold_cached(self, spread_cents: float, total_depth: int, market_id: str) -> float:
        """
        Compute edge threshold with caching to avoid redundant calculations.
        
        Args:
            spread_cents: Current spread in cents
            total_depth: Total book depth
            market_id: Market identifier for cache key
            
        Returns:
            Edge threshold as a float (0.0-1.0)
        """
        # Check cache first
        cache_key = f"{market_id}_{spread_cents}_{total_depth}"
        cached = self._edge_cache.get(cache_key)
        
        if cached and cached.is_valid():
            self._cache_hits += 1
            logger.debug(
                "[SPREAD-OPTIMIZER] Cache HIT for %s: edge=%.4f (age=%.1fs)",
                market_id, cached.edge_threshold, time.time() - cached.computed_at
            )
            return cached.edge_threshold
        
        # Cache miss - compute edge threshold
        self._cache_misses += 1
        self._calculations += 1
        
        edge_threshold = self._compute_edge_threshold_optimized(spread_cents, total_depth)
        
        # Cache the result
        self._edge_cache[cache_key] = EdgeCalculationCache(
            market_id=market_id,
            edge_threshold=edge_threshold,
            spread_cents=spread_cents,
            total_depth=total_depth,
            computed_at=time.time()
        )
        
        # Maintain cache size
        if len(self._edge_cache) > self.cache_size:
            # Remove oldest entry
            oldest_key = min(self._edge_cache.keys(), 
                           key=lambda k: self._edge_cache[k].computed_at)
            del self._edge_cache[oldest_key]
        
        logger.debug(
            "[SPREAD-OPTIMIZER] Cache MISS for %s: computed edge=%.4f spread=%.1f depth=%d",
            market_id, edge_threshold, spread_cents, total_depth
        )
        
        return edge_threshold
    
    def _compute_edge_threshold_optimized(self, spread_cents: float, total_depth: int) -> float:
        """
        Optimized edge threshold calculation with improved logic.
        
        Args:
            spread_cents: Current spread in cents
            total_depth: Total book depth
            
        Returns:
            Edge threshold as a float (0.0-1.0)
        """
        # Base edge
        base_edge = 0.01  # 1% base edge
        
        # Spread penalty: wider spreads require higher edge
        spread_pct = spread_cents / 100.0
        spread_penalty = spread_pct * 2.0  # 2x spread penalty
        
        # Liquidity penalty: thinner books require higher edge
        liquidity_penalty = 0.0
        if total_depth > 0:
            liquidity_penalty = max(0.0, (10.0 / total_depth) - 0.1)  # Scaled penalty
        
        # Combine penalties
        min_edge = max(base_edge, spread_penalty + liquidity_penalty)
        
        # Clamp to reasonable bounds
        min_edge = max(0.005, min(min_edge, 0.1))  # 0.5% to 10%
        
        return min_edge
    
    def assess_market_quality(self, market_id: str) -> Optional[float]:
        """
        Assess market quality based on spread metrics.
        
        Args:
            market_id: Market identifier
            
        Returns:
            Quality score (0.0-1.0) or None if metrics not available
        """
        metrics = self._spread_metrics.get(market_id)
        if metrics is None:
            return None
        
        return metrics.quality_score
    
    def filter_markets_by_quality(self, market_ids: List[str], min_quality: float = 0.5) -> List[str]:
        """
        Filter markets by quality score.
        
        Args:
            market_ids: List of market identifiers
            min_quality: Minimum quality score (0.0-1.0)
            
        Returns:
            Filtered list of market identifiers
        """
        filtered = []
        for market_id in market_ids:
            quality = self.assess_market_quality(market_id)
            if quality is not None and quality >= min_quality:
                filtered.append(market_id)
        
        logger.info(
            "[SPREAD-OPTIMIZER] Filtered %d markets by quality >= %.2f: %d passed",
            len(market_ids), min_quality, len(filtered)
        )
        
        return filtered
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics for the optimizer."""
        total_requests = self._cache_hits + self._cache_misses
        cache_hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0.0
        
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": cache_hit_rate,
            "calculations": self._calculations,
            "errors": self._errors,
            "cache_size": len(self._edge_cache),
            "metrics_cache_size": len(self._spread_metrics)
        }
    
    def reset_metrics(self) -> None:
        """Reset performance metrics."""
        self._cache_hits = 0
        self._cache_misses = 0
        self._calculations = 0
        self._errors = 0
        logger.info("[SPREAD-OPTIMIZER] Performance metrics reset")
    
    def clear_cache(self) -> None:
        """Clear all caches."""
        self._edge_cache.clear()
        self._spread_metrics.clear()
        logger.info("[SPREAD-OPTIMIZER] All caches cleared")
    
    # Private helper methods
    
    def _get_best_bid(self, market_state: Any, errors: List[str]) -> Optional[int]:
        """Extract best bid price from market state."""
        try:
            if hasattr(market_state, 'best_bid_cents'):
                return market_state.best_bid_cents
            elif hasattr(market_state, 'best_yes_bid'):
                return market_state.best_yes_bid
            elif hasattr(market_state, 'bid') and market_state.bid:
                return int(market_state.bid)
            else:
                errors.append("No bid price found")
                return None
        except (AttributeError, ValueError, TypeError) as e:
            errors.append(f"Bid extraction error: {str(e)}")
            return None
    
    def _get_best_ask(self, market_state: Any, errors: List[str]) -> Optional[int]:
        """Extract best ask price from market state."""
        try:
            if hasattr(market_state, 'best_ask_cents'):
                return market_state.best_ask_cents
            elif hasattr(market_state, 'best_yes_ask'):
                return market_state.best_yes_ask
            elif hasattr(market_state, 'ask') and market_state.ask:
                return int(market_state.ask)
            else:
                errors.append("No ask price found")
                return None
        except (AttributeError, ValueError, TypeError) as e:
            errors.append(f"Ask extraction error: {str(e)}")
            return None
    
    def _get_depth_yes(self, market_state: Any, errors: List[str]) -> int:
        """Extract YES side depth from market state."""
        try:
            if hasattr(market_state, 'yes_bids'):
                yes_bids = market_state.yes_bids
                if isinstance(yes_bids, list):
                    return len(yes_bids) if yes_bids else 0
                elif isinstance(yes_bids, int):
                    return yes_bids
                else:
                    return 0
            elif hasattr(market_state, 'depth_yes'):
                return market_state.depth_yes
            else:
                return 0
        except (AttributeError, TypeError) as e:
            errors.append(f"YES depth extraction error: {str(e)}")
            return 0
    
    def _get_depth_no(self, market_state: Any, errors: List[str]) -> int:
        """Extract NO side depth from market state."""
        try:
            if hasattr(market_state, 'no_bids'):
                no_bids = market_state.no_bids
                if isinstance(no_bids, list):
                    return len(no_bids) if no_bids else 0
                elif isinstance(no_bids, int):
                    return no_bids
                else:
                    return 0
            elif hasattr(market_state, 'depth_no'):
                return market_state.depth_no
            else:
                return 0
        except (AttributeError, TypeError) as e:
            errors.append(f"NO depth extraction error: {str(e)}")
            return 0
    
    def _calculate_liquidity_score(self, spread_cents: float, total_depth: int) -> float:
        """Calculate liquidity score based on spread and depth.
        
        CRITICAL FIX: More conservative depth scoring to prevent overestimation
        for low-liquidity markets. Previous formula gave 0.8 score for 10 depth,
        which is too optimistic for thin books.
        """
        # Spread component: lower spread = higher liquidity
        spread_score = max(0.0, 1.0 - (spread_cents / self.MAX_SPREAD_CENTS))
        
        # Depth component: more depth = higher liquidity
        # CRITICAL FIX: Normalize to 50 levels instead of 10 for more conservative scoring
        # This ensures thin books (10 depth) get lower scores (~0.2 instead of 1.0)
        depth_score = min(1.0, total_depth / 50.0)
        
        # Combine scores (weighted average)
        # CRITICAL FIX: Increase spread weight to 0.7, reduce depth weight to 0.3
        # Spread is more important for liquidity assessment in prediction markets
        liquidity_score = (spread_score * 0.7 + depth_score * 0.3)
        
        return max(0.0, min(1.0, liquidity_score))
    
    def _calculate_quality_score(self, spread_cents: float, total_depth: int, liquidity_score: float) -> float:
        """Calculate overall market quality score."""
        # Spread quality: tighter spread = higher quality
        spread_quality = max(0.0, 1.0 - (spread_cents / self.MAX_SPREAD_CENTS))
        
        # Depth quality: more depth = higher quality
        depth_quality = min(1.0, total_depth / 5.0)  # Normalize to 5 levels
        
        # Overall quality is weighted average
        quality_score = (spread_quality * 0.4 + depth_quality * 0.3 + liquidity_score * 0.3)
        
        return max(0.0, min(1.0, quality_score))


# Global optimizer instance
_optimizer_instance: Optional[SpreadOptimizer] = None


def get_spread_optimizer() -> SpreadOptimizer:
    """Get the global spread optimizer instance."""
    global _optimizer_instance
    
    if _optimizer_instance is None:
        _optimizer_instance = SpreadOptimizer()
    
    return _optimizer_instance


def reset_spread_optimizer() -> None:
    """Reset the global spread optimizer instance."""
    global _optimizer_instance
    _optimizer_instance = None
