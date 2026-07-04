"""Unified Risk Profile — Single source of truth for system-wide risk stance.

This module provides a centralized RiskProfile abstraction that eliminates
the divergence between ContinuousTrader and AgentGrid risk configurations.

Usage::
    from merid.risk.risk_profile import RiskProfile, get_risk_profile
    
    # Get current profile (from env or default)
    profile = get_risk_profile()
    
    # Access unified thresholds
    kelly = profile.base_kelly_fraction
    max_risk = profile.max_risk_per_trade_pct
    
    # Get phase-aware edge threshold
    threshold = profile.get_edge_threshold("mid", realized_vol=0.25)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional
from enum import Enum


class RiskProfileLevel(Enum):
    """Risk profile levels from conservative to aggressive."""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class RiskProfile:
    """Single source of truth for system-wide risk stance.
    
    This dataclass is immutable (frozen=True) to ensure risk parameters
    cannot be accidentally modified at runtime.
    
    All percentage fields are expressed as decimals (0.20 = 20%).
    Basis point (bps) fields are integers (100 = 1%).
    """
    
    # ═══════════════════════════════════════════════════════════════════════
    # Kelly sizing parameters
    # CRITICAL FIX: Aligned with kalshi_crypto_15m_v2.yaml profile (2026-07-04)
    # Profile specifies: kelly_fraction: 0.02 (2%)
    # ═══════════════════════════════════════════════════════════════════════
    base_kelly_fraction: float = 0.02
    """Base Kelly fraction (0.02 = 2% of full Kelly - aligned with profile)."""
    
    min_kelly_fraction: float = 0.01
    """Floor under stress/drawdown."""
    
    max_kelly_fraction: float = 0.03
    """Cap in favorable regimes."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Exposure limits
    # ═══════════════════════════════════════════════════════════════════════
    max_risk_per_trade_pct: float = 0.02
    """Maximum risk per individual trade (2% - aligned with profile)."""
    
    max_risk_per_event_pct: float = 0.04
    """Maximum risk per event/market (4.0%)."""
    
    max_risk_per_venue_pct: float = 0.125
    """Maximum risk per venue (12.5%)."""
    
    max_total_exposure_pct: float = 0.25
    """Maximum total portfolio exposure (25%)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Drawdown clamps
    # ═══════════════════════════════════════════════════════════════════════
    drawdown_reduce_pct: float = 0.10
    """Drawdown level to reduce sizing (10%)."""
    
    drawdown_halt_pct: float = 0.20
    """Drawdown level to halt trading (20%)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Edge thresholds (basis points)
    # PROFILE-GATED: For kalshi_crypto_15m_v2, use profile edge bands (4-7%)
    # ═══════════════════════════════════════════════════════════════════════
    min_edge_bps: int = 75
    """Base minimum edge threshold (75 bps = 0.75%). PROFILE-GATED for kalshi_crypto_15m_v2."""
    
    min_edge_by_phase: Dict[str, int] = field(default_factory=lambda: {
        "early": 120,      # > 24h to expiry
        "mid": 75,         # 4-24h
        "late": 60,        # 1-4h
        "terminal": 100,   # < 1h
    })
    """Phase-aware edge thresholds. PROFILE-GATED for kalshi_crypto_15m_v2."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Volatility scaling
    # ═══════════════════════════════════════════════════════════════════════
    target_annual_vol_pct: float = 0.20
    """Target annual volatility for sizing (20%)."""
    
    vol_lookback_days: int = 30
    """Volatility calculation lookback period."""
    
    high_vol_threshold: float = 0.50
    """Threshold for high volatility regime (50%)."""
    
    high_vol_premium_bps: int = 50
    """Additional edge required in high vol (50 bps)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Liquidity adjustments
    # ═══════════════════════════════════════════════════════════════════════
    low_liquidity_threshold_usd: float = 1000.0
    """Depth threshold for low liquidity ($1000)."""
    
    low_liquidity_premium_bps: int = 30
    """Additional edge required in low liquidity (30 bps)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Sentiment adjustments
    # ═══════════════════════════════════════════════════════════════════════
    sentiment_fear_threshold: float = 20.0
    """Fear index threshold (0-100)."""
    
    sentiment_fear_discount_bps: int = 20
    """Edge discount during extreme fear."""
    
    sentiment_greed_threshold: float = 80.0
    """Greed index threshold (0-100)."""
    
    sentiment_greed_premium_bps: int = 20
    """Edge premium required during extreme greed."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Contract constraints
    # ═══════════════════════════════════════════════════════════════════════
    max_contract_price_cents: int = 65
    """Maximum contract price to trade (65 cents)."""
    
    min_contract_price_cents: int = 1
    """Minimum contract price to trade (1 cent)."""
    
    max_position_per_market: int = 3
    """Maximum position count per market."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Fee and churn controls
    # ═══════════════════════════════════════════════════════════════════════
    fee_drag_threshold_pct: float = 0.25
    """Fee drag level for auto-tightening (25%)."""
    
    churn_cooldown_cycles: int = 3
    """Anti-churn hysteresis cooldown (3 cycles)."""
    
    min_edge_improvement_bps: int = 20
    """Minimum edge improvement to exit cooldown (20 bps)."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Paper mode adjustments
    # ═══════════════════════════════════════════════════════════════════════
    paper_edge_boost_pct: float = 0.30
    """Edge boost in paper mode (30% lower threshold)."""
    
    def get_edge_threshold(
        self,
        phase: str,
        realized_vol: float = 0.0,
        depth_usd: float = 0.0,
        sentiment_score: float = 50.0,
        paper_mode: bool = False
    ) -> int:
        """Resolve effective edge threshold for current conditions.
        
        Args:
            phase: Expiry phase ("early", "mid", "late", "terminal")
            realized_vol: Realized volatility (annualized, decimal)
            depth_usd: Market depth in USD
            sentiment_score: Sentiment index (0-100, 50 = neutral)
            paper_mode: Whether in paper trading mode
            
        Returns:
            Effective edge threshold in basis points
        """
        # Base threshold from phase
        base = self.min_edge_by_phase.get(phase, self.min_edge_bps)
        
        # Volatility adjustment
        if realized_vol > self.high_vol_threshold:
            base += self.high_vol_premium_bps
        
        # Liquidity adjustment
        if depth_usd < self.low_liquidity_threshold_usd:
            base += self.low_liquidity_premium_bps
        
        # Sentiment adjustment
        if sentiment_score < self.sentiment_fear_threshold:
            base -= self.sentiment_fear_discount_bps
        elif sentiment_score > self.sentiment_greed_threshold:
            base += self.sentiment_greed_premium_bps
        
        # Paper mode adjustment (lower threshold)
        if paper_mode:
            base = int(base * (1.0 - self.paper_edge_boost_pct))
        
        # Absolute floor
        return max(base, 25)  # Never go below 25 bps
    
    def get_kelly_fraction(
        self,
        current_drawdown: float = 0.0,
        profit_factor: float = 1.5
    ) -> float:
        """Get adaptive Kelly fraction based on conditions.
        
        Args:
            current_drawdown: Current drawdown from peak (decimal)
            profit_factor: Measured profit factor
            
        Returns:
            Effective Kelly fraction
        """
        # Start with base
        f = self.base_kelly_fraction
        
        # Drawdown reduction
        if current_drawdown > self.drawdown_reduce_pct:
            f *= 0.5  # Halve sizing under drawdown
        
        # Profit factor adjustment
        if profit_factor < 1.2:
            f = min(f, self.min_kelly_fraction)
        elif profit_factor > 2.0:
            f = min(f * 1.1, self.max_kelly_fraction)
        
        return max(f, self.min_kelly_fraction)
    
    @classmethod
    def conservative(cls) -> "RiskProfile":
        """Conservative risk profile for capital preservation."""
        return cls(
            base_kelly_fraction=0.15,
            min_kelly_fraction=0.05,
            max_kelly_fraction=0.20,
            max_risk_per_trade_pct=0.010,
            max_risk_per_event_pct=0.030,
            max_risk_per_venue_pct=0.10,
            max_total_exposure_pct=0.20,
            drawdown_reduce_pct=0.08,
            drawdown_halt_pct=0.15,
            min_edge_bps=100,
            min_edge_by_phase={
                "early": 150,
                "mid": 100,
                "late": 80,
                "terminal": 120,
            },
            target_annual_vol_pct=0.15,
            high_vol_threshold=0.40,
            high_vol_premium_bps=75,
            paper_edge_boost_pct=0.20,
        )
    
    @classmethod
    def moderate(cls) -> "RiskProfile":
        """Moderate risk profile for balanced growth."""
        return cls()  # Uses defaults
    
    @classmethod
    def aggressive(cls) -> "RiskProfile":
        """Aggressive risk profile for maximum growth."""
        return cls(
            base_kelly_fraction=0.25,
            min_kelly_fraction=0.15,
            max_kelly_fraction=0.35,
            max_risk_per_trade_pct=0.020,
            max_risk_per_event_pct=0.050,
            max_risk_per_venue_pct=0.15,
            max_total_exposure_pct=0.30,
            drawdown_reduce_pct=0.10,
            drawdown_halt_pct=0.20,
            min_edge_bps=50,
            min_edge_by_phase={
                "early": 100,
                "mid": 50,
                "late": 40,
                "terminal": 80,
            },
            target_annual_vol_pct=0.25,
            high_vol_threshold=0.60,
            high_vol_premium_bps=30,
            paper_edge_boost_pct=0.40,
        )
    
    @classmethod
    def from_env(cls) -> "RiskProfile":
        """Load risk profile from environment variable."""
        level = os.getenv("MERID_RISK_PROFILE", "moderate").lower()
        
        if level == "conservative":
            return cls.conservative()
        elif level == "aggressive":
            return cls.aggressive()
        else:
            return cls.moderate()


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton instance
# ═══════════════════════════════════════════════════════════════════════════════

_risk_profile_instance: Optional[RiskProfile] = None


def get_risk_profile() -> RiskProfile:
    """Get the global RiskProfile instance.
    
    This is a singleton that loads from environment on first call:
    - MERID_RISK_PROFILE=conservative|moderate|aggressive
    
    Returns:
        RiskProfile instance
    """
    global _risk_profile_instance
    
    if _risk_profile_instance is None:
        _risk_profile_instance = RiskProfile.from_env()
    
    return _risk_profile_instance


def set_risk_profile(profile: RiskProfile) -> None:
    """Set the global RiskProfile instance (for testing)."""
    global _risk_profile_instance
    _risk_profile_instance = profile


def reset_risk_profile() -> None:
    """Reset the global RiskProfile instance (for testing)."""
    global _risk_profile_instance
    _risk_profile_instance = None
