"""Tiered Fallback Logic for Liquidity Crisis Detection.

Based on Markaicode research (2024) on flash crash prevention:
- Multi-tier execution strategies (NORMAL → CAUTIOUS → DEFENSIVE → EMERGENCY → HALT)
- Real-time liquidity scoring to predict execution failure
- Automatic adjustment of order sizing and spread tolerance
- Emergency shutdown at crisis levels

Key insight: The issue isn't the strategy, it's the lack of fallback logic
when liquidity disappears and spreads explode.

Implementation:
- Calculate real-time liquidity score (0-100)
- Map score to execution tier
- Each tier has pre-configured limits and strategies
- Automatic tier transitions based on liquidity conditions
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from utils.logger import get_logger

from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
from merid.event_venues.kalshi.microstructure import compute_side_microstructure

logger = get_logger("merid.risk.liquidity_fallback")


class ExecutionTier(Enum):
    """Execution strategy tiers based on liquidity."""
    NORMAL = "normal"           # Score 70-100: Full execution
    CAUTIOUS = "cautious"       # Score 40-70: Reduced size, wider tolerance
    DEFENSIVE = "defensive"     # Score 20-40: Conservative execution
    EMERGENCY = "emergency"     # Score <20: Emergency mode
    HALT = "halt"              # Manual override or critical failure


@dataclass
class FallbackConfig:
    """Configuration for each execution tier."""
    tier: ExecutionTier
    max_order_size_usd: float
    max_spread_pct: float
    order_type: str  # 'market', 'limit', 'halt'
    limit_offset_bps: int  # Basis points from mid
    max_clip_size_pct: float  # % of book depth
    timeout_seconds: int
    min_confidence: float  # Minimum model confidence to execute


@dataclass
class LiquidityScore:
    """Real-time liquidity score and metrics."""
    score: float  # 0-100
    tier: ExecutionTier
    spread_pct: float
    depth_total: int
    depth_ratio: float  # depth / max_depth
    spread_ratio: float  # spread / max_spread
    details: Dict[str, float]


class LiquidityFallbackExecutor:
    """Multi-tier fallback executor for liquidity crisis management.
    
    Based on Markaicode research (2024):
    - Detect liquidity crises in real-time before execution
    - Build multi-tier fallback strategies that activate automatically
    - Implement circuit breakers that work under stress
    
    Args:
        configs: Dictionary of ExecutionTier to FallbackConfig
        score_window: Number of snapshots to average for score
    """
    
    def __init__(
        self,
        configs: Optional[Dict[ExecutionTier, FallbackConfig]] = None,
        score_window: int = 5,
    ):
        self.score_window = score_window
        
        # Default configurations based on research
        if configs is None:
            self.configs = {
                ExecutionTier.NORMAL: FallbackConfig(
                    tier=ExecutionTier.NORMAL,
                    max_order_size_usd=50000,
                    max_spread_pct=0.5,
                    order_type='limit',
                    limit_offset_bps=10,  # 0.1% from mid
                    max_clip_size_pct=0.25,
                    timeout_seconds=30,
                    min_confidence=0.55,
                ),
                ExecutionTier.CAUTIOUS: FallbackConfig(
                    tier=ExecutionTier.CAUTIOUS,
                    max_order_size_usd=10000,
                    max_spread_pct=1.0,
                    order_type='limit',
                    limit_offset_bps=25,
                    max_clip_size_pct=0.15,
                    timeout_seconds=20,
                    min_confidence=0.60,
                ),
                ExecutionTier.DEFENSIVE: FallbackConfig(
                    tier=ExecutionTier.DEFENSIVE,
                    max_order_size_usd=2000,
                    max_spread_pct=2.0,
                    order_type='limit',
                    limit_offset_bps=50,
                    max_clip_size_pct=0.10,
                    timeout_seconds=15,
                    min_confidence=0.65,
                ),
                ExecutionTier.EMERGENCY: FallbackConfig(
                    tier=ExecutionTier.EMERGENCY,
                    max_order_size_usd=500,
                    max_spread_pct=5.0,
                    order_type='limit',
                    limit_offset_bps=100,
                    max_clip_size_pct=0.05,
                    timeout_seconds=10,
                    min_confidence=0.70,
                ),
                ExecutionTier.HALT: FallbackConfig(
                    tier=ExecutionTier.HALT,
                    max_order_size_usd=0,
                    max_spread_pct=0.0,
                    order_type='halt',
                    limit_offset_bps=0,
                    max_clip_size_pct=0.0,
                    timeout_seconds=0,
                    min_confidence=1.0,
                ),
            }
        else:
            self.configs = configs
        
        # Scoring history for smoothing
        self._score_history: Dict[str, list] = {}
        
        # Reference values for normalization
        self._max_depth_ref: Dict[str, int] = {}
        self._max_spread_ref: Dict[str, float] = {}
    
    def compute_liquidity_score(
        self,
        ob: OrderbookSnapshot,
        side: str = "yes",
    ) -> LiquidityScore:
        """Compute real-time liquidity score (0-100).
        
        Score components:
        1. Spread quality (40%): Lower spread = higher score
        2. Depth quality (40%): Higher depth = higher score
        3. Spread stability (20%): Stable spread = higher score
        
        Args:
            ob: Canonical OrderbookSnapshot
            side: "yes" or "no"
            
        Returns:
            LiquidityScore with score, tier, and metrics
        """
        micro = compute_side_microstructure(ob, side, size=1)
        
        # Extract metrics
        spread_pct = micro.spread_pct if micro.spread_pct else 0.0
        depth_total = micro.depth_yes_at_best + micro.depth_no_at_best
        
        # Update reference values for normalization
        ticker = ob.ticker
        if ticker not in self._max_depth_ref:
            self._max_depth_ref[ticker] = max(depth_total, 100)
        else:
            self._max_depth_ref[ticker] = max(self._max_depth_ref[ticker], depth_total)
        
        if ticker not in self._max_spread_ref:
            self._max_spread_ref[ticker] = max(spread_pct, 0.01)
        else:
            self._max_spread_ref[ticker] = max(self._max_spread_ref[ticker], spread_pct)
        
        # Normalize metrics (0-1 scale)
        depth_ratio = depth_total / self._max_depth_ref[ticker] if self._max_depth_ref[ticker] > 0 else 0.0
        spread_ratio = 1.0 - (spread_pct / self._max_spread_ref[ticker]) if self._max_spread_ref[ticker] > 0 else 0.0
        
        # Compute score (weighted components)
        # CRITICAL FIX: Increase depth weight to make score more sensitive to depth changes
        # CRITICAL FIX: If depth is zero, all scores should be zero to trigger HALT
        if depth_total == 0:
            spread_score = 0.0
            depth_score = 0.0
            stability_score = 0.0
        else:
            spread_score = spread_ratio * 30.0  # Reduced from 40.0
            depth_score = depth_ratio * 50.0  # Increased from 40.0
            stability_score = 20.0  # Default to neutral
        
        raw_score = spread_score + depth_score + stability_score
        score = max(0.0, min(100.0, raw_score))
        
        # Smooth score with history
        if ticker not in self._score_history:
            self._score_history[ticker] = []
        self._score_history[ticker].append(score)
        if len(self._score_history[ticker]) > self.score_window:
            self._score_history[ticker].pop(0)
        
        smoothed_score = sum(self._score_history[ticker]) / len(self._score_history[ticker])
        
        # Map score to tier
        if smoothed_score >= 70:
            tier = ExecutionTier.NORMAL
        elif smoothed_score >= 40:
            tier = ExecutionTier.CAUTIOUS
        elif smoothed_score >= 20:
            tier = ExecutionTier.DEFENSIVE
        elif smoothed_score > 0:
            tier = ExecutionTier.EMERGENCY
        else:
            tier = ExecutionTier.HALT
        
        return LiquidityScore(
            score=smoothed_score,
            tier=tier,
            spread_pct=spread_pct,
            depth_total=depth_total,
            depth_ratio=depth_ratio,
            spread_ratio=spread_ratio,
            details={
                "spread_score": spread_score,
                "depth_score": depth_score,
                "stability_score": stability_score,
            },
        )
    
    def get_execution_config(self, score: LiquidityScore) -> FallbackConfig:
        """Get execution configuration for the current liquidity tier."""
        return self.configs[score.tier]
    
    def should_execute(
        self,
        score: LiquidityScore,
        model_confidence: float,
        order_size_usd: float,
    ) -> tuple[bool, str]:
        """Determine if execution should proceed based on liquidity tier.
        
        Args:
            score: Current liquidity score
            model_confidence: Model confidence (0-1)
            order_size_usd: Proposed order size in USD
            
        Returns:
            Tuple of (should_execute, reason)
        """
        config = self.get_execution_config(score)
        
        # Check if tier is HALT
        if score.tier == ExecutionTier.HALT:
            return False, f"Liquidity score {score.score:.1f} in HALT tier"
        
        # Check minimum confidence
        if model_confidence < config.min_confidence:
            return False, f"Model confidence {model_confidence:.2f} below tier minimum {config.min_confidence}"
        
        # Check order size limit
        if order_size_usd > config.max_order_size_usd:
            return False, f"Order size ${order_size_usd:.0f} exceeds tier limit ${config.max_order_size_usd:.0f}"
        
        # Check spread limit
        if score.spread_pct > config.max_spread_pct:
            return False, f"Spread {score.spread_pct:.2%} exceeds tier limit {config.max_spread_pct:.2%}"
        
        return True, f"Execution approved in {score.tier.value} tier"
    
    def adjust_order_size(
        self,
        score: LiquidityScore,
        proposed_size_usd: float,
    ) -> float:
        """Adjust order size based on liquidity tier."""
        config = self.get_execution_config(score)
        
        # Cap at tier maximum
        adjusted_size = min(proposed_size_usd, config.max_order_size_usd)
        
        # Further reduce based on depth clip percentage
        # This is a placeholder - would need actual book depth
        # adjusted_size = adjusted_size * config.max_clip_size_pct
        
        return adjusted_size
    
    def get_limit_offset(self, score: LiquidityScore) -> int:
        """Get limit order offset in basis points based on tier."""
        config = self.get_execution_config(score)
        return config.limit_offset_bps
    
    def get_timeout(self, score: LiquidityScore) -> int:
        """Get order timeout in seconds based on tier."""
        config = self.get_execution_config(score)
        return config.timeout_seconds


# Singleton instance for use across the system
_fallback_executor_instance: Optional[LiquidityFallbackExecutor] = None
_fallback_executor_lock = threading.Lock()


def get_liquidity_fallback_executor() -> Optional[LiquidityFallbackExecutor]:
    """Get the singleton liquidity fallback executor instance.
    
    This is the canonical way to access the liquidity fallback system
    across the codebase (order_router, agent_grid, etc.).
    
    Returns:
        LiquidityFallbackExecutor instance or None if not initialized
    """
    global _fallback_executor_instance
    return _fallback_executor_instance


def init_liquidity_fallback_executor(
    configs: Optional[Dict[ExecutionTier, FallbackConfig]] = None,
    score_window: int = 5,
    force_reinit: bool = False,
) -> LiquidityFallbackExecutor:
    """Initialize the singleton liquidity fallback executor.
    
    This should be called during system initialization (e.g., in main.py
    or during agent grid initialization).
    
    Args:
        configs: Optional custom configurations
        score_window: Score averaging window
        force_reinit: If True, re-initialize even if instance exists (for testing)
        
    Returns:
        The initialized LiquidityFallbackExecutor instance
    """
    global _fallback_executor_instance
    with _fallback_executor_lock:
        if _fallback_executor_instance is None or force_reinit:
            _fallback_executor_instance = LiquidityFallbackExecutor(
                configs=configs,
                score_window=score_window,
            )
            logger.info("[LIQUIDITY-FALLBACK] Singleton executor initialized")
        return _fallback_executor_instance
