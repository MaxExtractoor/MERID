"""Edge Threshold Matrix — Unified edge threshold resolution.

This module provides centralized edge threshold resolution that eliminates
the divergence between CT and Grid edge threshold logic.

Usage::
    from merid.risk.edge_thresholds import EdgeThresholdMatrix, ExpiryPhase
    
    # Create threshold matrix with default or custom parameters
    matrix = EdgeThresholdMatrix.default()
    
    # Resolve threshold for current conditions
    threshold_bps = matrix.resolve(
        phase=ExpiryPhase.MID,
        realized_vol_annual=0.25,
        depth_dollars=5000,
        sentiment_score=50,
        paper_mode=False
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional
from enum import Enum


class ExpiryPhase(Enum):
    """Expiry phases for edge threshold adjustment."""
    EARLY = "early"       # > 24h to expiry
    MID = "mid"           # 4-24h
    LATE = "late"         # 1-4h
    TERMINAL = "terminal" # < 1h


@dataclass(frozen=True)
class EdgeThresholdMatrix:
    """Edge thresholds by regime and market condition.
    
    This matrix provides phase-aware, condition-sensitive edge thresholds
    that account for volatility, liquidity, and sentiment.
    
    All thresholds are in basis points (1 bps = 0.01%).
    """
    
    # ═══════════════════════════════════════════════════════════════════════
    # Base thresholds by expiry phase (CONSERVATIVE "SURE BET" — 2026-05-10)
    # ═══════════════════════════════════════════════════════════════════════
    base_bps: Dict[ExpiryPhase, int] = field(default_factory=lambda: {
        ExpiryPhase.EARLY: 800,     # 8.0% — market just opened, high uncertainty
        ExpiryPhase.MID: 600,       # 6.0% — most liquid phase
        ExpiryPhase.LATE: 500,      # 5.0% — approaching close
        ExpiryPhase.TERMINAL: 1000, # 10.0% — very close to expiry, high risk
    })
    """Base edge thresholds by expiry phase (bps). Conservative for Kalshi PM."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Volatility adjustments
    # ═══════════════════════════════════════════════════════════════════════
    high_vol_threshold: float = 0.50
    """Threshold for high volatility regime (50% annualized)."""
    
    extreme_vol_threshold: float = 0.80
    """Threshold for extreme volatility regime (80% annualized)."""
    
    high_vol_premium_bps: int = 50
    """Additional edge required in high volatility (bps)."""
    
    extreme_vol_premium_bps: int = 100
    """Additional edge required in extreme volatility (bps)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Liquidity adjustments
    # ═══════════════════════════════════════════════════════════════════════
    low_liquidity_threshold_usd: float = 1000.0
    """Depth threshold for low liquidity ($1000)."""
    
    critical_liquidity_threshold_usd: float = 500.0
    """Depth threshold for critical liquidity ($500)."""
    
    low_liquidity_premium_bps: int = 30
    """Additional edge required in low liquidity (bps)."""
    
    critical_liquidity_premium_bps: int = 60
    """Additional edge required in critical liquidity (bps)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Sentiment adjustments
    # ═══════════════════════════════════════════════════════════════════════
    sentiment_fear_threshold: float = 20.0
    """Fear index threshold (0-100)."""
    
    sentiment_extreme_fear_threshold: float = 10.0
    """Extreme fear threshold."""
    
    sentiment_greed_threshold: float = 80.0
    """Greed index threshold (0-100)."""
    
    sentiment_extreme_greed_threshold: float = 90.0
    """Extreme greed threshold."""
    
    sentiment_fear_discount_bps: int = 20
    """Edge discount during fear (opportunity, lower threshold)."""
    
    sentiment_extreme_fear_discount_bps: int = 30
    """Edge discount during extreme fear."""
    
    sentiment_greed_premium_bps: int = 20
    """Edge premium required during greed (caution, higher threshold)."""
    
    sentiment_extreme_greed_premium_bps: int = 40
    """Edge premium required during extreme greed."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Safety limits
    # ═══════════════════════════════════════════════════════════════════════
    absolute_minimum_bps: int = 250
    """Absolute minimum edge threshold (safety floor: 2.5%)."""
    
    absolute_maximum_bps: int = 1500
    """Absolute maximum edge threshold (sanity ceiling: 15%)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Mode adjustments
    # ═══════════════════════════════════════════════════════════════════════
    paper_mode_discount_pct: float = 0.30
    """Threshold reduction in paper mode (30% lower)."""
    
    shadow_mode_discount_pct: float = 0.20
    """Threshold reduction in shadow mode (20% lower)."""
    
    def resolve(
        self,
        phase: ExpiryPhase,
        realized_vol_annual: float = 0.0,
        depth_dollars: float = 10000.0,
        sentiment_score: float = 50.0,
        paper_mode: bool = False,
        shadow_mode: bool = False
    ) -> int:
        """Resolve effective edge threshold for current conditions.
        
        This method combines base thresholds with all adjustments to produce
        the final edge requirement for a trade.
        
        Args:
            phase: Expiry phase (early/mid/late/terminal)
            realized_vol_annual: Realized volatility (annualized, decimal)
            depth_dollars: Market depth in USD
            sentiment_score: Sentiment index (0-100, 50 = neutral)
            paper_mode: Whether in paper trading mode
            shadow_mode: Whether in shadow mode
            
        Returns:
            Effective edge threshold in basis points
        """
        # Start with base threshold for phase
        threshold = self.base_bps.get(phase, 75)
        
        # ═══════════════════════════════════════════════════════════════════
        # Volatility adjustments
        # ═══════════════════════════════════════════════════════════════════
        if realized_vol_annual > self.extreme_vol_threshold:
            threshold += self.extreme_vol_premium_bps
        elif realized_vol_annual > self.high_vol_threshold:
            threshold += self.high_vol_premium_bps
        
        # ═══════════════════════════════════════════════════════════════════
        # Liquidity adjustments
        # ═══════════════════════════════════════════════════════════════════
        if depth_dollars < self.critical_liquidity_threshold_usd:
            threshold += self.critical_liquidity_premium_bps
        elif depth_dollars < self.low_liquidity_threshold_usd:
            threshold += self.low_liquidity_premium_bps
        
        # ═══════════════════════════════════════════════════════════════════
        # Sentiment adjustments
        # ═══════════════════════════════════════════════════════════════════
        if sentiment_score < self.sentiment_extreme_fear_threshold:
            # Extreme fear = opportunity, lower threshold
            threshold -= self.sentiment_extreme_fear_discount_bps
        elif sentiment_score < self.sentiment_fear_threshold:
            # Fear = slight opportunity
            threshold -= self.sentiment_fear_discount_bps
        elif sentiment_score > self.sentiment_extreme_greed_threshold:
            # Extreme greed = caution, higher threshold
            threshold += self.sentiment_extreme_greed_premium_bps
        elif sentiment_score > self.sentiment_greed_threshold:
            # Greed = caution
            threshold += self.sentiment_greed_premium_bps
        
        # ═══════════════════════════════════════════════════════════════════
        # Mode adjustments
        # ═══════════════════════════════════════════════════════════════════
        if paper_mode:
            threshold = int(threshold * (1.0 - self.paper_mode_discount_pct))
        elif shadow_mode:
            threshold = int(threshold * (1.0 - self.shadow_mode_discount_pct))
        
        # ═══════════════════════════════════════════════════════════════════
        # Safety clamps
        # ═══════════════════════════════════════════════════════════════════
        threshold = max(threshold, self.absolute_minimum_bps)
        threshold = min(threshold, self.absolute_maximum_bps)
        
        return threshold
    
    def resolve_from_strings(
        self,
        phase_str: str,
        **kwargs
    ) -> int:
        """Resolve threshold from string phase name.
        
        Args:
            phase_str: Phase name ("early", "mid", "late", "terminal")
            **kwargs: Additional arguments for resolve()
            
        Returns:
            Effective edge threshold in basis points
        """
        phase_map = {
            "early": ExpiryPhase.EARLY,
            "mid": ExpiryPhase.MID,
            "late": ExpiryPhase.LATE,
            "terminal": ExpiryPhase.TERMINAL,
        }
        phase = phase_map.get(phase_str.lower(), ExpiryPhase.MID)
        return self.resolve(phase, **kwargs)
    
    @classmethod
    def default(cls) -> "EdgeThresholdMatrix":
        """Default edge threshold matrix (moderate settings)."""
        return cls()
    
    @classmethod
    def conservative(cls) -> "EdgeThresholdMatrix":
        """Conservative edge threshold matrix (highest thresholds — sure bets only)."""
        return cls(
            base_bps={
                ExpiryPhase.EARLY: 1000,  # 10%
                ExpiryPhase.MID: 800,     # 8%
                ExpiryPhase.LATE: 600,    # 6%
                ExpiryPhase.TERMINAL: 1200, # 12%
            },
            high_vol_premium_bps=100,
            extreme_vol_premium_bps=200,
            low_liquidity_premium_bps=75,
            critical_liquidity_premium_bps=150,
            absolute_minimum_bps=300,
        )
    
    @classmethod
    def aggressive(cls) -> "EdgeThresholdMatrix":
        """Aggressive edge threshold matrix (lower thresholds — paper/research only)."""
        return cls(
            base_bps={
                ExpiryPhase.EARLY: 300,   # 3%
                ExpiryPhase.MID: 250,     # 2.5%
                ExpiryPhase.LATE: 200,    # 2%
                ExpiryPhase.TERMINAL: 350, # 3.5%
            },
            high_vol_premium_bps=50,
            extreme_vol_premium_bps=100,
            low_liquidity_premium_bps=30,
            critical_liquidity_premium_bps=60,
            absolute_minimum_bps=150,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience functions for backwards compatibility
# ═══════════════════════════════════════════════════════════════════════════════

def get_default_threshold(
    phase: str,
    realized_vol: float = 0.0,
    depth_usd: float = 10000.0,
    sentiment: float = 50.0,
    paper_mode: bool = False
) -> int:
    """Get default edge threshold (convenience function).
    
    Args:
        phase: Expiry phase ("early", "mid", "late", "terminal")
        realized_vol: Realized volatility (annualized, decimal)
        depth_usd: Market depth in USD
        sentiment: Sentiment score (0-100)
        paper_mode: Whether in paper mode
        
    Returns:
        Edge threshold in basis points
    """
    matrix = EdgeThresholdMatrix.default()
    return matrix.resolve_from_strings(
        phase,
        realized_vol_annual=realized_vol,
        depth_dollars=depth_usd,
        sentiment_score=sentiment,
        paper_mode=paper_mode
    )
