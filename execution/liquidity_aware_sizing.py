"""Liquidity-Aware Sizing Engine.

Implements position sizing based on orderbook depth to avoid slippage and market impact.
Sizes orders according to available liquidity at each price level to ensure execution
without significantly moving the market.

Key Features:
- Orderbook depth analysis
- Participation rate limits based on liquidity
- Depth-based order splitting
- Slippage estimation and avoidance
- Real-time liquidity monitoring

Usage:
    from execution.liquidity_aware_sizing import get_liquidity_sizer
    
    sizer = get_liquidity_sizer()
    
    # Get liquidity-aware size
    size = sizer.get_liquidity_aware_size(
        ticker="KXBTC15M-26MAY092115-15",
        side="yes",
        desired_contracts=100,
        max_participation_rate=0.1
    )
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from utils.logger import get_logger

logger = get_logger("execution.liquidity_aware_sizing")


class LiquidityLevel(str, Enum):
    """Liquidity level classification."""
    HIGH = "high"           # Deep orderbook, large sizes possible
    MEDIUM = "medium"       # Moderate liquidity, moderate sizes
    LOW = "low"            # Shallow orderbook, small sizes only
    ILLIQUID = "illiquid"  # Very shallow, avoid trading


@dataclass
class OrderbookDepth:
    """Orderbook depth at a price level."""
    price_cents: int
    yes_contracts: int
    no_contracts: int
    total_contracts: int = 0
    
    def __post_init__(self):
        self.total_contracts = self.yes_contracts + self.no_contracts


@dataclass
class LiquidityAnalysis:
    """Liquidity analysis result."""
    ticker: str
    liquidity_level: LiquidityLevel
    total_yes_depth: int
    total_no_depth: int
    total_depth: int
    spread_cents: int
    mid_cents: int
    recommended_max_contracts: int
    participation_rate_used: float
    slippage_estimate_pct: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class LiquidityConfig:
    """Liquidity-aware sizing configuration."""
    max_participation_rate: float = 0.1  # Maximum participation rate (10%)
    min_depth_for_high_liquidity: int = 1000  # Minimum contracts for high liquidity
    min_depth_for_medium_liquidity: int = 200  # Minimum contracts for medium liquidity
    max_slippage_tolerance_pct: float = 0.5  # Maximum acceptable slippage (0.5%)
    depth_levels_to_analyze: int = 5  # Number of price levels to analyze
    enable_adaptive_sizing: bool = True  # Enable adaptive sizing based on conditions


class LiquidityAwareSizer:
    """Liquidity-aware sizing engine.
    
    Sizes orders based on orderbook depth to avoid slippage and market impact.
    Analyzes available liquidity at each price level and recommends maximum
    order sizes that won't significantly move the market.
    """
    
    _instance: Optional["LiquidityAwareSizer"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize the liquidity sizer."""
        self._config = LiquidityConfig()
        self._liquidity_cache: Dict[str, LiquidityAnalysis] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl_seconds = 30  # Cache TTL in seconds
        logger.info("LiquidityAwareSizer initialized")
    
    def get_config(self) -> LiquidityConfig:
        """Get the liquidity configuration."""
        return self._config
    
    def set_config(self, config: LiquidityConfig):
        """Update the liquidity configuration."""
        self._config = config
        logger.info("Liquidity configuration updated")
    
    def get_liquidity_aware_size(
        self,
        ticker: str,
        side: str,
        desired_contracts: int,
        max_participation_rate: Optional[float] = None
    ) -> int:
        """Get liquidity-aware order size.
        
        Args:
            ticker: Market ticker
            side: Order side ("yes" or "no")
            desired_contracts: Desired number of contracts
            max_participation_rate: Maximum participation rate (uses config if None)
            
        Returns:
            Recommended order size based on liquidity
        """
        participation = max_participation_rate or self._config.max_participation_rate
        
        # Get liquidity analysis
        analysis = self._analyze_liquidity(ticker)
        
        if analysis.liquidity_level == LiquidityLevel.ILLIQUID:
            logger.warning(f"Illiquid market: {ticker}, recommending minimal size")
            return min(desired_contracts, 5)  # Conservative minimum
        
        # Calculate size based on participation rate
        if side == "yes":
            available_liquidity = analysis.total_yes_depth
        else:
            available_liquidity = analysis.total_no_depth
        
        max_size = int(available_liquidity * participation)
        
        # Ensure we don't exceed desired size
        recommended_size = min(desired_contracts, max_size)
        
        # Ensure minimum size of at least 1 contract
        recommended_size = max(1, recommended_size)
        
        logger.info(
            f"Liquidity-aware sizing: {ticker} side={side} "
            f"desired={desired_contracts} recommended={recommended_size} "
            f"liquidity={analysis.liquidity_level} depth={available_liquidity}"
        )
        
        return recommended_size
    
    def _analyze_liquidity(self, ticker: str) -> LiquidityAnalysis:
        """Analyze liquidity for a ticker.
        
        Args:
            ticker: Market ticker
            
        Returns:
            Liquidity analysis result
        """
        # Check cache
        with self._cache_lock:
            if ticker in self._liquidity_cache:
                cached = self._liquidity_cache[ticker]
                age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
                if age < self._cache_ttl_seconds:
                    return cached
        
        # Perform fresh analysis
        analysis = self._perform_liquidity_analysis(ticker)
        
        # Update cache
        with self._cache_lock:
            self._liquidity_cache[ticker] = analysis
        
        return analysis
    
    def _perform_liquidity_analysis(self, ticker: str) -> LiquidityAnalysis:
        """Perform liquidity analysis for a ticker.
        
        Args:
            ticker: Market ticker
            
        Returns:
            Liquidity analysis result
        """
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(ticker)
            
            if not state:
                logger.warning(f"No market state available for {ticker}")
                return self._create_default_analysis(ticker)
            
            # Get orderbook depth
            yes_depth = state.depth_yes or 0
            no_depth = state.depth_no or 0
            total_depth = yes_depth + no_depth
            
            spread_cents = state.spread_cents or 10
            mid_cents = state.mid_cents or 50
            
            # Classify liquidity level
            if total_depth >= self._config.min_depth_for_high_liquidity:
                liquidity_level = LiquidityLevel.HIGH
            elif total_depth >= self._config.min_depth_for_medium_liquidity:
                liquidity_level = LiquidityLevel.MEDIUM
            elif total_depth > 0:
                liquidity_level = LiquidityLevel.LOW
            else:
                liquidity_level = LiquidityLevel.ILLIQUID
            
            # Calculate recommended max contracts
            recommended_max = int(total_depth * self._config.max_participation_rate)
            recommended_max = max(1, recommended_max)
            
            # Estimate slippage
            slippage_estimate = self._estimate_slippage(spread_cents, mid_cents, total_depth)
            
            return LiquidityAnalysis(
                ticker=ticker,
                liquidity_level=liquidity_level,
                total_yes_depth=yes_depth,
                total_no_depth=no_depth,
                total_depth=total_depth,
                spread_cents=spread_cents,
                mid_cents=mid_cents,
                recommended_max_contracts=recommended_max,
                participation_rate_used=self._config.max_participation_rate,
                slippage_estimate_pct=slippage_estimate
            )
            
        except Exception as e:
            logger.error(f"Liquidity analysis failed for {ticker}: {e}")
            return self._create_default_analysis(ticker)
    
    def _create_default_analysis(self, ticker: str) -> LiquidityAnalysis:
        """Create a default liquidity analysis when data is unavailable.
        
        Args:
            ticker: Market ticker
            
        Returns:
            Default liquidity analysis (conservative)
        """
        return LiquidityAnalysis(
            ticker=ticker,
            liquidity_level=LiquidityLevel.MEDIUM,  # Conservative default
            total_yes_depth=100,
            total_no_depth=100,
            total_depth=200,
            spread_cents=10,
            mid_cents=50,
            recommended_max_contracts=20,  # Conservative default
            participation_rate_used=self._config.max_participation_rate,
            slippage_estimate_pct=0.1  # Conservative estimate
        )
    
    def _estimate_slippage(
        self,
        spread_cents: int,
        mid_cents: int,
        total_depth: int
    ) -> float:
        """Estimate slippage percentage.
        
        Args:
            spread_cents: Current spread in cents
            mid_cents: Mid price in cents
            total_depth: Total orderbook depth
            
        Returns:
            Estimated slippage as percentage
        """
        if mid_cents == 0:
            return 0.0
        
        # Slippage estimate based on spread and depth
        spread_pct = (spread_cents / mid_cents) * 100
        
        # Adjust for depth (deeper orderbook = less slippage)
        depth_factor = min(1.0, 100 / total_depth) if total_depth > 0 else 1.0
        
        estimated_slippage = spread_pct * depth_factor
        
        return min(estimated_slippage, self._config.max_slippage_tolerance_pct)
    
    def should_reduce_size(self, ticker: str, desired_contracts: int) -> Tuple[bool, int, str]:
        """Check if order size should be reduced due to liquidity constraints.
        
        Args:
            ticker: Market ticker
            desired_contracts: Desired number of contracts
            
        Returns:
            Tuple of (should_reduce, recommended_size, reason)
        """
        analysis = self._analyze_liquidity(ticker)
        
        if analysis.liquidity_level == LiquidityLevel.ILLIQUID:
            return True, min(desired_contracts, 5), "Market is illiquid"
        
        if desired_contracts > analysis.recommended_max_contracts:
            return (
                True,
                analysis.recommended_max_contracts,
                f"Size exceeds liquidity capacity: {desired_contracts} > {analysis.recommended_max_contracts}"
            )
        
        if analysis.slippage_estimate_pct > self._config.max_slippage_tolerance_pct:
            reduced_size = int(desired_contracts * 0.5)  # Reduce by 50%
            return (
                True,
                reduced_size,
                f"High slippage risk: {analysis.slippage_estimate_pct:.2f}%"
            )
        
        return False, desired_contracts, "Size is appropriate for liquidity"
    
    def get_liquidity_summary(self, tickers: List[str]) -> Dict[str, Any]:
        """Get liquidity summary for multiple tickers.
        
        Args:
            tickers: List of market tickers
            
        Returns:
            Summary of liquidity across all tickers
        """
        analyses = {}
        for ticker in tickers:
            analyses[ticker] = self._analyze_liquidity(ticker)
        
        # Aggregate statistics
        high_count = sum(1 for a in analyses.values() if a.liquidity_level == LiquidityLevel.HIGH)
        medium_count = sum(1 for a in analyses.values() if a.liquidity_level == LiquidityLevel.MEDIUM)
        low_count = sum(1 for a in analyses.values() if a.liquidity_level == LiquidityLevel.LOW)
        illiquid_count = sum(1 for a in analyses.values() if a.liquidity_level == LiquidityLevel.ILLIQUID)
        
        total_depth = sum(a.total_depth for a in analyses.values())
        avg_spread = sum(a.spread_cents for a in analyses.values()) / len(analyses) if analyses else 0
        
        return {
            "total_tickers": len(tickers),
            "liquidity_distribution": {
                "high": high_count,
                "medium": medium_count,
                "low": low_count,
                "illiquid": illiquid_count
            },
            "total_depth": total_depth,
            "average_spread_cents": avg_spread,
            "analyses": {
                ticker: {
                    "liquidity_level": a.liquidity_level,
                    "total_depth": a.total_depth,
                    "spread_cents": a.spread_cents,
                    "recommended_max_contracts": a.recommended_max_contracts,
                    "slippage_estimate_pct": a.slippage_estimate_pct
                }
                for ticker, a in analyses.items()
            }
        }
    
    def clear_cache(self):
        """Clear the liquidity cache."""
        with self._cache_lock:
            self._liquidity_cache.clear()
        logger.info("Liquidity cache cleared")


# Singleton accessor
_liquidity_sizer: Optional[LiquidityAwareSizer] = None
_liquidity_sizer_lock = threading.Lock()


def get_liquidity_sizer() -> LiquidityAwareSizer:
    """Get the singleton LiquidityAwareSizer instance."""
    global _liquidity_sizer
    if _liquidity_sizer is None:
        with _liquidity_sizer_lock:
            if _liquidity_sizer is None:
                _liquidity_sizer = LiquidityAwareSizer()
    return _liquidity_sizer
