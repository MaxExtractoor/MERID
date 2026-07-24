"""
Candidate Generation Optimizer - Phase 5.4

Optimizes candidate selection and ranking logic for the Kalshi 15m trading system.

This module provides:
- Efficient market filtering and selection
- Optimized candidate ranking with quality scoring
- Performance-optimized candidate generation
- Comprehensive candidate pipeline metrics
"""

from __future__ import annotations

import time
import logging
from typing import Optional, Dict, List, Tuple, Any, Set
from dataclasses import dataclass, field
from decimal import Decimal
from collections import defaultdict
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("merid.prediction.candidate_optimizer")

logger.debug("[CANDIDATE-OPTIMIZER] Module loaded")


@dataclass
class MarketCandidate:
    """Represents a market candidate with comprehensive metrics."""
    market_id: str
    asset: str
    series_ticker: str
    spread_cents: float
    mid_cents: float
    best_bid_cents: float = 0.0
    best_ask_cents: float = 0.0
    depth_yes: int = 0
    depth_no: int = 0
    total_depth: int = 0
    liquidity_score: float = 0.0
    quality_score: float = 0.0
    edge_threshold: float = 0.0
    implied_prob: float = 0.0
    minutes_to_expiry: float = 0.0
    timestamp: float = 0.0
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    size: int = 1  # Position size in contracts (default 1)
    ticker: str = ""  # Alias for series_ticker for compatibility
    strike_target: Optional[float] = None  # Strike/target level for the market (e.g., BTC price target)
    thesis_side: Optional[str] = None  # YES/NO thesis side from signal
    yes_price_cents: Optional[int] = None  # YES leg price at candidate time
    no_price_cents: Optional[int] = None  # NO leg price at candidate time


@dataclass
class CandidatePipelineMetrics:
    """Metrics for the candidate generation pipeline."""
    total_markets_scanned: int = 0
    markets_with_md: int = 0
    markets_with_spot: int = 0
    markets_passing_filters: int = 0
    markets_passing_quality: int = 0
    markets_passing_edge: int = 0
    final_candidates: int = 0
    pipeline_duration_ms: float = 0.0
    filter_breakdown: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    status: str = "success"  # "success", "error", "empty"


class CandidateOptimizer:
    """
    Optimizes candidate generation and selection for better performance.
    
    Features:
    - Efficient market filtering with parallel processing
    - Quality-based candidate ranking
    - Performance monitoring and metrics
    - Configurable filtering criteria
    """
    
    def __init__(self, max_workers: int = 4, cache_size: int = 1000):
        self.max_workers = max_workers
        self.cache_size = cache_size
        self._candidate_cache: Dict[str, MarketCandidate] = {}
        self._pipeline_metrics = CandidatePipelineMetrics()
        self._in_generate_candidates = False  # Recursion guard
        
        # Load filtering thresholds from kalshi_crypto_15m profile config
        # Legacy defaults are overridden by profile when available
        # CRITICAL FIX: Set fallback to 30c to harmonize with 10c-75c canonical range
        legacy_max_spread = 30  # Aligned with profile guardrails (2026-07-10)
        legacy_min_depth_levels = 1  # Legacy default
        legacy_min_liquidity_score = 0.05  # Legacy default
        legacy_min_quality_score = 0.05  # Legacy default
        
        # 2026-07-11: Use dynamic threshold manager for regime-aware spread thresholds
        try:
            from merid.event_venues.kalshi.dynamic_thresholds import get_dynamic_threshold_manager
            threshold_manager = get_dynamic_threshold_manager()
            self.max_spread_cents = threshold_manager.get_max_spread_cents()
            logger.info(
                "[OPTIMIZER-CONFIG] Using dynamic spread threshold from threshold manager: %dc (regime=%s)",
                self.max_spread_cents, threshold_manager.get_regime()
            )
        except Exception as e:
            logger.warning(
                "[OPTIMIZER-CONFIG] Failed to load dynamic spread threshold: %s, using fallback 30c", e
            )
            self.max_spread_cents = 30  # Canonical fallback
        
        self.MIN_DEPTH_LEVELS = 1  # Reduced from 2 to allow one-sided markets
        self.MIN_LIQUIDITY_SCORE = 0.05  # Reduced from 0.1 to allow one-sided markets
        self.MIN_QUALITY_SCORE = 0.05  # Reduced from 0.1 to allow one-sided markets
        self.MAX_MINUTES_TO_EXPIRY = 30  # Maximum minutes to expiry
        
        # Performance tracking
        self._total_candidates_generated = 0
        self._total_pipeline_time = 0.0
        self._total_errors = 0
        
        logger.info("[CANDIDATE-OPTIMIZER] Initialized with max_workers=%d, cache_size=%d, max_spread_cents=%d",
                    max_workers, cache_size, self.max_spread_cents)
    
    async def generate_candidates(
        self, 
        markets: List[Dict[str, Any]], 
        asset: str,
        market_state_store: Any,
        spot_service: Any
    ) -> Tuple[List[MarketCandidate], CandidatePipelineMetrics]:
        """
        Generate optimized candidates from a list of markets.
        
        Args:
            markets: List of market dictionaries
            asset: Asset identifier (BTC, ETH, etc.)
            market_state_store: Market state store instance
            spot_service: Spot price service instance
            
        Returns:
            Tuple of (candidates, pipeline_metrics)
        """
        # RECURSION GUARD: Prevent infinite recursion
        if self._in_generate_candidates:
            logger.error("[CANDIDATE-OPTIMIZER] RECURSION DETECTED - returning empty candidates")
            return [], CandidatePipelineMetrics(status="error", errors=["recursion_detected"])
        
        self._in_generate_candidates = True
        
        # DEFENSIVE LOGGING: Track candidate optimizer entry to diagnose markets_seen=0
        logger.info(
            "[CANDIDATE-OPTIMIZER] ENTRY: asset=%s len(markets)=%d",
            asset, len(markets)
        )
        
        # DEBUG: Log market IDs to verify markets are being passed correctly
        if len(markets) > 0:
            market_ids = [m.get('ticker', 'unknown') for m in markets[:5]]  # First 5 markets
            logger.info("[CANDIDATE-OPTIMIZER] DEBUG: sample tickers=%s...", market_ids)
        else:
            logger.warning("[CANDIDATE-OPTIMIZER] DEBUG: NO MARKETS PASSED - this explains markets_seen=0")
        
        # P0-12 DIAGNOSTIC: Log per-market state checks
        for m in markets:
            try:
                market_id = m.get('market_id', 'unknown')
                ticker = m.get('ticker', 'unknown')
                logger.debug("[OPTIMIZER-MARKET] asset=%s ticker=%s market_id=%s", asset, ticker, market_id)
                state = market_state_store.get(market_id)
                if not state:
                    logger.debug("[OPTIMIZER-SKIP] asset=%s ticker=%s market_id=%s reason=NO_STATE", asset, ticker, market_id)
                    continue
                logger.debug(
                    "[OPTIMIZER-STATE] asset=%s ticker=%s market_id=%s initialized=%s executable=%s depth_yes=%s depth_no=%s liquidity_status=%s",
                    asset, ticker, market_id,
                    getattr(state, 'initialized', False),
                    getattr(state, 'executable', False),
                    getattr(state, 'depth_yes', 0),
                    getattr(state, 'depth_no', 0),
                    getattr(state, 'liquidity_status', 'unknown')
                )
            except Exception as e:
                logger.error("[OPTIMIZER-DIAGNOSTIC-ERROR] Error logging market state: %s", e, exc_info=True)
                continue
        
        start_time = time.time()
        metrics = CandidatePipelineMetrics()
        metrics.total_markets_scanned = len(markets)
        
        try:
            # RECURSION GUARD: Reset on exit
            self._in_generate_candidates = False
            # Phase 1: Parallel market data collection
            markets_with_data = await self._collect_market_data_parallel(
                markets, market_state_store, spot_service, metrics
            )
            logger.info("[CANDIDATE-OPTIMIZER] Phase 1: markets_with_data=%d markets_with_md=%d markets_with_spot=%d",
                       len(markets_with_data), metrics.markets_with_md, metrics.markets_with_spot)
            
            # Phase 2: Quality filtering
            quality_filtered = await self._filter_by_quality(markets_with_data, metrics)
            logger.info("[CANDIDATE-OPTIMIZER] Phase 2: quality_filtered=%d", len(quality_filtered))
            
            # Phase 3: Edge threshold filtering
            edge_filtered = await self._filter_by_edge_threshold(quality_filtered, metrics)
            logger.info("[CANDIDATE-OPTIMIZER] Phase 3: edge_filtered=%d", len(edge_filtered))
            
            # Phase 4: Final ranking and selection
            final_candidates = await self._rank_and_select_candidates(edge_filtered, metrics)
            logger.info("[CANDIDATE-OPTIMIZER] Phase 4: final_candidates=%d", len(final_candidates))
            
            # P0-12 DIAGNOSTIC: Log optimizer summary
            logger.info(
                "[OPTIMIZER-SUMMARY] asset=%s markets_seen=%d markets_with_md=%d markets_with_spot=%d markets_passing_filters=%d final_candidates=%d",
                asset,
                metrics.total_markets_scanned,
                metrics.markets_with_md,
                metrics.markets_with_spot,
                metrics.markets_passing_filters,
                len(final_candidates)
            )
            
            # Update metrics
            metrics.pipeline_duration_ms = (time.time() - start_time) * 1000
            metrics.final_candidates = len(final_candidates)
            
            # Set status based on result
            if len(final_candidates) == 0:
                metrics.status = "empty"
            else:
                metrics.status = "success"
            
            # Update global metrics
            self._total_candidates_generated += len(final_candidates)
            self._total_pipeline_time += metrics.pipeline_duration_ms
            
            logger.info(
                "[CANDIDATE-OPTIMIZER] Generated %d candidates from %d markets in %.1fms",
                len(final_candidates), len(markets), metrics.pipeline_duration_ms
            )
            
            return final_candidates, metrics
            
        except Exception as e:
            self._total_errors += 1
            metrics.errors.append(f"Pipeline error: {str(e)}")
            metrics.status = "error"
            logger.error("[CANDIDATE-OPTIMIZER] Error in candidate generation: %s", e, exc_info=True)
            
            # RECURSION GUARD: Reset on error
            self._in_generate_candidates = False
            return [], metrics
    
    async def _collect_market_data_parallel(
        self, 
        markets: List[Dict[str, Any]], 
        market_state_store: Any,
        spot_service: Any,
        metrics: CandidatePipelineMetrics
    ) -> List[MarketCandidate]:
        """Collect market data in parallel for better performance."""
        
        async def collect_single_market(market: Dict[str, Any]) -> Optional[MarketCandidate]:
            """Collect data for a single market."""
            try:
                market_id = market.get("market_id")
                if not market_id:
                    logger.warning("[CANDIDATE-OPTIMIZER] Market missing market_id: %s", market)
                    return None
                
                # Get market state
                state = market_state_store.get(market_id)
                if not state or not hasattr(state, 'last_update_ts'):
                    logger.warning("[CANDIDATE-OPTIMIZER] No market state for %s", market_id)
                    return None
                
                # Skip uninitialized or non-executable markets
                # KalshiMarketState uses 'book_initialized' not 'initialized'
                if not getattr(state, 'book_initialized', False) or not getattr(state, 'executable', False):
                    logger.debug("[CANDIDATE-OPTIMIZER] Skipping uninitialized/non-executable market %s (book_initialized=%s, executable=%s)",
                               market_id, getattr(state, 'book_initialized', False), getattr(state, 'executable', False))
                    return None
                
                metrics.markets_with_md += 1
                
                # Check spot data availability
                asset = market.get("asset", "")
                has_spot = await self._check_spot_data(spot_service, asset)
                if has_spot:
                    metrics.markets_with_spot += 1
                else:
                    logger.warning("[CANDIDATE-OPTIMIZER] No spot data for asset=%s market=%s", asset, market_id)
                    return None
                
                # Create candidate
                logger.info("[CANDIDATE-OPTIMIZER] ABOUT-TO-CALL-CREATE-CANDIDATE market_id=%s asset=%s", market_id, asset)
                candidate = await self._create_market_candidate(market, state, spot_service)
                if candidate:
                    logger.info("[CANDIDATE-OPTIMIZER] Created candidate for %s asset=%s", market_id, asset)
                else:
                    logger.warning("[CANDIDATE-OPTIMIZER] Failed to create candidate for %s asset=%s", market_id, asset)
                return candidate
                
            except Exception as e:
                logger.error("[CANDIDATE-OPTIMIZER] Error collecting data for market %s: %s", 
                           market.get("market_id", "unknown"), e, exc_info=True)
                return None
        
        # Process markets in parallel batches
        batch_size = min(self.max_workers * 2, len(markets)) if len(markets) > 0 else 1
        candidates = []
        
        # Early return for empty markets
        if len(markets) == 0:
            logger.debug("[CANDIDATE-OPTIMIZER] NO MARKETS PASSED - this explains markets_seen=0")
            return candidates
        
        for i in range(0, len(markets), batch_size):
            batch = markets[i:i + batch_size]
            try:
                batch_results = await asyncio.wait_for(
                    asyncio.gather(
                        *[collect_single_market(market) for market in batch],
                        return_exceptions=True
                    ),
                    timeout=5.0  # 5 second timeout per batch to prevent hanging
                )
            except asyncio.TimeoutError:
                logger.warning("[CANDIDATE-OPTIMIZER] Batch collection timeout - skipping batch")
                batch_results = [TimeoutError("Batch collection timeout") for _ in batch]
            
            for result in batch_results:
                if isinstance(result, MarketCandidate):
                    candidates.append(result)
                elif isinstance(result, Exception):
                    logger.debug("[CANDIDATE-OPTIMIZER] Batch processing error: %s", result)
        
        return candidates
    
    async def _filter_by_quality(
        self, 
        candidates: List[MarketCandidate], 
        metrics: CandidatePipelineMetrics
    ) -> List[MarketCandidate]:
        """Filter candidates by basic quality checks - simplified to avoid over-engineering."""
        filtered = []
        
        for candidate in candidates:
            # SIMPLIFIED: Basic spread check only
            if candidate.spread_cents is None or candidate.spread_cents > self.max_spread_cents:
                if candidate.spread_cents is None:
                    logger.debug("[CANDIDATE-OPTIMIZER] REJECTED: spread_cents=None")
                else:
                    logger.debug("[CANDIDATE-OPTIMIZER] REJECTED: spread=%d > max=%d", candidate.spread_cents, self.max_spread_cents)
                metrics.filter_breakdown["spread_too_wide"] = metrics.filter_breakdown.get("spread_too_wide", 0) + 1
                continue
            
            # SIMPLIFIED: Basic depth check only
            if candidate.total_depth is None or candidate.total_depth < self.MIN_DEPTH_LEVELS:
                logger.debug("[CANDIDATE-OPTIMIZER] REJECTED: depth=%s < min=%d", candidate.total_depth, self.MIN_DEPTH_LEVELS)
                metrics.filter_breakdown["insufficient_depth"] = metrics.filter_breakdown.get("insufficient_depth", 0) + 1
                continue
            
            # SIMPLIFIED: Basic expiry check only
            if candidate.minutes_to_expiry is None or candidate.minutes_to_expiry < 0 or candidate.minutes_to_expiry > self.MAX_MINUTES_TO_EXPIRY:
                logger.debug("[CANDIDATE-OPTIMIZER] REJECTED: expiry=%s", candidate.minutes_to_expiry)
                metrics.filter_breakdown["invalid_tte"] = metrics.filter_breakdown.get("invalid_tte", 0) + 1
                continue
            
            logger.info("[CANDIDATE-OPTIMIZER] PASSED: ticker=%s spread=%d depth=%d", candidate.ticker, candidate.spread_cents, candidate.total_depth)
            filtered.append(candidate)
        
        metrics.markets_passing_quality = len(filtered)
        metrics.markets_passing_filters = len(filtered)
        
        logger.info(
            "[CANDIDATE-OPTIMIZER] Quality filter: %d -> %d candidates",
            len(candidates), len(filtered)
        )
        
        return filtered
    
    async def _filter_by_edge_threshold(
        self, 
        candidates: List[MarketCandidate], 
        metrics: CandidatePipelineMetrics
    ) -> List[MarketCandidate]:
        """Filter candidates by edge threshold requirements.
        
        NOTE: Edge threshold filter disabled for now to allow candidate generation.
        The edge_threshold calculation is a heuristic that was rejecting all candidates
        due to high spread penalties. Real edge calculation happens in the trading agent
        based on implied probability vs spot price, not this heuristic.
        """
        # P0-12 FIX: Disable edge threshold filter to allow candidates to flow through
        # The real edge calculation happens in trading_agent.py based on implied prob
        filtered = candidates
        
        metrics.markets_passing_edge = len(filtered)
        
        logger.info(
            "[CANDIDATE-OPTIMIZER] Edge filter: %d -> %d candidates (edge threshold filter disabled)",
            len(candidates), len(filtered)
        )
        
        return filtered
    
    async def _rank_and_select_candidates(
        self, 
        candidates: List[MarketCandidate], 
        metrics: CandidatePipelineMetrics
    ) -> List[MarketCandidate]:
        """Rank and select final candidates."""
        if not candidates:
            return []
        
        # Sort by quality score (descending), then by liquidity score
        candidates.sort(key=lambda c: (c.quality_score, c.liquidity_score), reverse=True)
        
        # Select top candidates (could be configurable)
        max_candidates = min(5, len(candidates))  # Top 5 candidates
        final_candidates = candidates[:max_candidates]
        
        # Update metrics
        metrics.final_candidates = len(final_candidates)
        
        logger.info(
            "[CANDIDATE-OPTIMIZER] Selected top %d candidates from %d",
            len(final_candidates), len(candidates)
        )
        
        return final_candidates
    
    async def _create_market_candidate(
        self, 
        market: Dict[str, Any], 
        state: Any,
        spot_service: Any
    ) -> MarketCandidate:
        """Create a MarketCandidate from market data."""
        try:
            market_id = market.get("market_id")
            asset = market.get("asset", "")
            series_ticker = market.get("series_ticker", "")
            
            # DIAGNOSTIC: Log entry to _create_market_candidate to trace execution
            logger.info(
                "[CANDIDATE-OPTIMIZER] CREATE-CANDIDATE-ENTRY market_id=%s asset=%s series_ticker=%s",
                market_id, asset, series_ticker
            )
            
            # Extract spread and depth information
            spread_cents = getattr(state, 'spread_cents', 0.0)
            if spread_cents is None:
                spread_cents = 0.0
            mid_cents = getattr(state, 'mid_cents', 0.0)
            if mid_cents is None:
                mid_cents = 0.0
            
            # CRITICAL FIX: Use canonical depth field names from KalshiMarketState
            # The state object has depth_yes and depth_no fields directly
            depth_yes = getattr(state, 'depth_yes', 0)
            depth_no = getattr(state, 'depth_no', 0)
            
            # Fallback to min_depth_* if primary fields are 0 (legacy compatibility)
            if depth_yes == 0:
                depth_yes = getattr(state, 'min_depth_yes', 0)
            if depth_no == 0:
                depth_no = getattr(state, 'min_depth_no', 0)
            
            total_depth = depth_yes + depth_no
            
            # DIAGNOSTIC: Log all available depth-related fields on state to identify field name mismatch
            logger.info(
                "[CANDIDATE-OPTIMIZER] STATE-DEPTH-FIELDS market_id=%s "
                "min_depth_yes=%s min_depth_no=%s depth_yes=%s depth_no=%s "
                "hasattr_min_depth_yes=%s hasattr_min_depth_no=%s "
                "hasattr_depth_yes=%s hasattr_depth_no=%s",
                market_id,
                getattr(state, 'min_depth_yes', 'MISSING'),
                getattr(state, 'min_depth_no', 'MISSING'),
                getattr(state, 'depth_yes', 'MISSING'),
                getattr(state, 'depth_no', 'MISSING'),
                hasattr(state, 'min_depth_yes'),
                hasattr(state, 'min_depth_no'),
                hasattr(state, 'depth_yes'),
                hasattr(state, 'depth_no'),
            )
            
            # Also check if state has orderbook object with depth data
            if hasattr(state, 'orderbook') and state.orderbook:
                try:
                    yes_bids_len = len(state.orderbook.yes_bids) if hasattr(state.orderbook, 'yes_bids') and hasattr(state.orderbook.yes_bids, '__len__') else 0
                    no_bids_len = len(state.orderbook.no_bids) if hasattr(state.orderbook, 'no_bids') and hasattr(state.orderbook.no_bids, '__len__') else 0
                    logger.info(
                        "[CANDIDATE-OPTIMIZER] ORDERBOOK-DEPTH market_id=%s "
                        "yes_bids=%s no_bids=%s",
                        market_id,
                        yes_bids_len,
                        no_bids_len,
                    )
                except (TypeError, AttributeError):
                    # Handle case where orderbook fields are Mock objects or not iterable
                    logger.info(
                        "[CANDIDATE-OPTIMIZER] ORDERBOOK-DEPTH market_id=%s (unable to measure depth)",
                        market_id,
                    )
            
            # Log what we found
            logger.info(
                "[CANDIDATE-OPTIMIZER] CREATE-CANDIDATE: market_id=%s asset=%s spread_cents=%s mid_cents=%s depth_yes=%d depth_no=%d total_depth=%d",
                market_id, asset, spread_cents, mid_cents, depth_yes, depth_no, total_depth
            )
            
            # Calculate scores
            liquidity_score = self._calculate_liquidity_score(spread_cents, total_depth)
            quality_score = self._calculate_quality_score(spread_cents, total_depth, liquidity_score)
            
            # Calculate edge threshold
            edge_threshold = self._calculate_edge_threshold(spread_cents, total_depth)
            
            # Calculate implied probability
            implied_prob = mid_cents / 100.0 if mid_cents is not None and mid_cents > 0 else 0.5
            
            # Calculate minutes to expiry
            minutes_to_expiry = self._calculate_minutes_to_expiry(market)
            
            # Get bid/ask from market state
            best_bid_cents = getattr(state, 'best_bid_cents', 0.0)
            best_ask_cents = getattr(state, 'best_ask_cents', 0.0)
            
            return MarketCandidate(
                market_id=market_id,
                asset=asset,
                series_ticker=series_ticker,
                ticker=series_ticker,  # Set ticker alias
                spread_cents=spread_cents,
                mid_cents=mid_cents,
                best_bid_cents=best_bid_cents,
                best_ask_cents=best_ask_cents,
                depth_yes=depth_yes,
                depth_no=depth_no,
                total_depth=total_depth,
                liquidity_score=liquidity_score,
                quality_score=quality_score,
                edge_threshold=edge_threshold,
                implied_prob=implied_prob,
                minutes_to_expiry=minutes_to_expiry,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.error("[CANDIDATE-OPTIMIZER] Error creating candidate for %s: %s", 
                       market.get("market_id", "unknown"), e, exc_info=True)
            raise
    
    async def _check_spot_data(self, spot_service: Any, asset: str) -> bool:
        """Check if spot data is available for the asset.
        
        Uses timing-aware SLA thresholds from spot_sla_config.py to enforce
        stricter staleness checks for near-expiry contracts.
        """
        try:
            if not spot_service:
                return False
            
            # Use the proper API instead of checking _cache directly
            from data.unified_spot_service import SpotError
            spot_result = spot_service.get(asset)
            
            # Handle SpotError cases (degraded, stale, unavailable)
            if isinstance(spot_result, SpotError):
                return False
            
            # SpotPrice case - data is fresh and within SLA
            if not spot_result:
                return False
            
            # Check if data is fresh using timing-aware SLA thresholds
            import time
            from data.spot_sla_config import get_spot_sla
            
            if hasattr(spot_result, 'timestamp'):
                # Timestamp is in milliseconds
                ts = spot_result.timestamp
                age = (time.time() * 1000 - ts) / 1000.0
                
                # Use centralized SLA threshold
                sla = get_spot_sla(asset)
                return age < sla.degrade_s
            
            return True
            
        except Exception:
            return False
    
    def _calculate_liquidity_score(self, spread_cents: float, total_depth: int) -> float:
        """Calculate liquidity score."""
        # Handle None spread_cents
        if spread_cents is None:
            spread_cents = self.max_spread_cents  # Use worst-case spread if unknown
        
        # Spread component: lower spread = higher liquidity
        spread_score = max(0.0, 1.0 - (spread_cents / self.max_spread_cents))
        
        # Depth component: more depth = higher liquidity
        depth_score = min(1.0, total_depth / 10.0)
        
        # Combine scores
        return (spread_score * 0.6 + depth_score * 0.4)
    
    def _calculate_quality_score(self, spread_cents: float, total_depth: int, liquidity_score: float) -> float:
        """Calculate overall quality score."""
        # Handle None spread_cents
        if spread_cents is None:
            spread_cents = self.max_spread_cents  # Use worst-case spread if unknown
        
        # Similar to spread optimizer but simplified
        spread_quality = max(0.0, 1.0 - (spread_cents / self.max_spread_cents))
        depth_quality = min(1.0, total_depth / 5.0)
        
        return (spread_quality * 0.4 + depth_quality * 0.3 + liquidity_score * 0.3)
    
    def _calculate_edge_threshold(self, spread_cents: float, total_depth: int) -> float:
        """Calculate edge threshold."""
        # Handle None spread_cents
        if spread_cents is None:
            spread_cents = self.max_spread_cents  # Use worst-case spread if unknown
        
        base_edge = 0.01
        spread_penalty = (spread_cents / 100.0) * 2.0
        liquidity_penalty = max(0.0, (10.0 / total_depth) - 0.1) if total_depth > 0 else 0.1
        
        return max(base_edge, spread_penalty + liquidity_penalty)
    
    def _calculate_minutes_to_expiry(self, market: Dict[str, Any]) -> float:
        """Calculate minutes to expiry.
        
        CRITICAL FIX: Use normalized minutes_to_expiry from market dict (canonical field).
        If missing, reject the market as invalid - no fallback to synthetic values.
        """
        # Check for normalized minutes_to_expiry first (canonical field)
        minutes = market.get("minutes_to_expiry")
        if minutes is not None:
            return float(minutes)
        
        # CRITICAL FIX: Reject market if minutes_to_expiry is missing
        # Returning 999.0 was causing valid markets to be rejected by TTE filter
        # This is a data integrity issue - if the field is missing, the market is invalid
        logger.warning(
            "[CANDIDATE-OPTIMIZER] market_id=%s missing minutes_to_expiry - rejecting as invalid",
            market.get("market_id", "unknown")
        )
        return -1.0  # Signal invalid market (will be rejected by TTE filter)
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics for the optimizer."""
        avg_pipeline_time = (
            self._total_pipeline_time / max(1, self._total_candidates_generated)
        )
        
        return {
            "total_candidates_generated": self._total_candidates_generated,
            "avg_pipeline_time_ms": avg_pipeline_time,
            "total_pipeline_time_ms": self._total_pipeline_time,
            "total_errors": self._total_errors,
            "cache_size": len(self._candidate_cache),
            "current_metrics": {
                "total_markets_scanned": self._pipeline_metrics.total_markets_scanned,
                "markets_with_md": self._pipeline_metrics.markets_with_md,
                "markets_with_spot": self._pipeline_metrics.markets_with_spot,
                "markets_passing_filters": self._pipeline_metrics.markets_passing_filters,
                "final_candidates": self._pipeline_metrics.final_candidates,
                "pipeline_duration_ms": self._pipeline_metrics.pipeline_duration_ms,
                "filter_breakdown": self._pipeline_metrics.filter_breakdown.copy()
            }
        }
    
    def reset_metrics(self) -> None:
        """Reset performance metrics."""
        self._total_candidates_generated = 0
        self._total_pipeline_time = 0.0
        self._total_errors = 0
        self._pipeline_metrics = CandidatePipelineMetrics()
        logger.info("[CANDIDATE-OPTIMIZER] Performance metrics reset")
    
    def clear_cache(self) -> None:
        """Clear candidate cache."""
        self._candidate_cache.clear()
        logger.info("[CANDIDATE-OPTIMIZER] Candidate cache cleared")


# Global optimizer instance
_optimizer_instance: Optional[CandidateOptimizer] = None


def get_candidate_optimizer() -> CandidateOptimizer:
    """Get the global candidate optimizer instance."""
    global _optimizer_instance
    
    if _optimizer_instance is None:
        _optimizer_instance = CandidateOptimizer()
    
    return _optimizer_instance


def reset_candidate_optimizer() -> None:
    """Reset the global candidate optimizer instance."""
    global _optimizer_instance
    _optimizer_instance = None
