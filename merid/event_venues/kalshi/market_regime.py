"""Market Regime Classifier for Fee-Aware Trading.

Implements the recommended regime classification system for Kalshi binary
contracts, distinguishing balanced, transition, skewed, and disabled-tail
markets with appropriate risk controls per regime.

Reference: OddsShopper Kalshi trading research and Kalshi Research calibration papers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Literal, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_regime")


@dataclass(frozen=True)
class SkewRegime:
    """Market regime configuration with risk controls.
    
    Each regime has specific thresholds for net edge, confidence, depth,
    spread, and sizing to account for different risk profiles across the
    probability spectrum.
    """
    name: Literal["balanced", "transition_low", "transition_high", "skewed_low", "skewed_high", "disabled_tail"]
    min_price_cents: int
    max_price_cents: int
    min_net_edge_cents: Decimal
    min_confidence: Decimal
    max_spread_cents: int
    min_depth_multiple: Decimal
    size_multiplier: Decimal
    enabled: bool
    min_time_to_expiry_seconds: int = 120
    max_time_to_expiry_seconds: int = 1800
    min_book_freshness_ms: int = 2000


# Recommended regime configurations for 15-minute crypto contracts
REGIME_CONFIGS: Dict[str, SkewRegime] = {
    "balanced": SkewRegime(
        name="balanced",
        min_price_cents=25,
        max_price_cents=75,
        min_net_edge_cents=Decimal("2.5"),
        min_confidence=Decimal("0.62"),
        max_spread_cents=2,
        min_depth_multiple=Decimal("2.0"),
        size_multiplier=Decimal("1.00"),
        enabled=True,
        min_book_freshness_ms=2000,
        min_time_to_expiry_seconds=120,
        max_time_to_expiry_seconds=1800,
    ),
    "transition_low": SkewRegime(
        name="transition_low",
        min_price_cents=15,
        max_price_cents=24,
        min_net_edge_cents=Decimal("2.25"),
        min_confidence=Decimal("0.68"),
        max_spread_cents=1,
        min_depth_multiple=Decimal("3.0"),
        size_multiplier=Decimal("0.75"),
        enabled=True,
        min_book_freshness_ms=1500,
        min_time_to_expiry_seconds=180,
        max_time_to_expiry_seconds=1500,
    ),
    "transition_high": SkewRegime(
        name="transition_high",
        min_price_cents=76,
        max_price_cents=85,
        min_net_edge_cents=Decimal("2.25"),
        min_confidence=Decimal("0.68"),
        max_spread_cents=1,
        min_depth_multiple=Decimal("3.0"),
        size_multiplier=Decimal("0.75"),
        enabled=True,
        min_book_freshness_ms=1500,
        min_time_to_expiry_seconds=180,
        max_time_to_expiry_seconds=1500,
    ),
    "skewed_low": SkewRegime(
        name="skewed_low",
        min_price_cents=10,
        max_price_cents=14,
        min_net_edge_cents=Decimal("2.0"),
        min_confidence=Decimal("0.75"),
        max_spread_cents=1,
        min_depth_multiple=Decimal("4.0"),
        size_multiplier=Decimal("0.50"),
        enabled=True,
        min_book_freshness_ms=1000,
        min_time_to_expiry_seconds=240,
        max_time_to_expiry_seconds=1200,
    ),
    "skewed_high": SkewRegime(
        name="skewed_high",
        min_price_cents=86,
        max_price_cents=90,
        min_net_edge_cents=Decimal("2.0"),
        min_confidence=Decimal("0.75"),
        max_spread_cents=1,
        min_depth_multiple=Decimal("4.0"),
        size_multiplier=Decimal("0.50"),
        enabled=True,
        min_book_freshness_ms=1000,
        min_time_to_expiry_seconds=240,
        max_time_to_expiry_seconds=1200,
    ),
    "disabled_tail": SkewRegime(
        name="disabled_tail",
        min_price_cents=1,
        max_price_cents=99,
        min_net_edge_cents=Decimal("0"),
        min_confidence=Decimal("0"),
        max_spread_cents=0,
        min_depth_multiple=Decimal("0"),
        size_multiplier=Decimal("0"),
        enabled=False,
    ),
}


def classify_market_regime(
    price_cents: int,
    time_to_expiry_seconds: Optional[int] = None,
) -> Optional[SkewRegime]:
    """Classify a market into its regime based on executable price.
    
    Classification uses the executable side price (ask for YES, bid for NO)
    rather than model probability or midpoint, because regime affects execution
    quality and risk regardless of model beliefs.
    
    Args:
        price_cents: Executable price in cents (1-99)
        time_to_expiry_seconds: Optional time to expiry for additional validation
        
    Returns:
        SkewRegime if enabled and within time window, None if disabled
        
    Examples:
        >>> classify_market_regime(50)
        SkewRegime(name='balanced', ...)
        
        >>> classify_market_regime(88)
        SkewRegime(name='skewed_high', ...)
        
        >>> classify_market_regime(3)
        None  # Disabled tail
    """
    if not 1 <= price_cents <= 99:
        logger.warning(f"Invalid price_cents for regime classification: {price_cents}")
        return None
    
    for regime_name, regime in REGIME_CONFIGS.items():
        if regime.enabled and regime.min_price_cents <= price_cents <= regime.max_price_cents:
            # Validate time window if provided
            if time_to_expiry_seconds is not None:
                if time_to_expiry_seconds < regime.min_time_to_expiry_seconds:
                    logger.debug(
                        f"Regime {regime_name}: price={price_cents}c below min time window "
                        f"({time_to_expiry_seconds}s < {regime.min_time_to_expiry_seconds}s)"
                    )
                    continue
                if time_to_expiry_seconds > regime.max_time_to_expiry_seconds:
                    logger.debug(
                        f"Regime {regime_name}: price={price_cents}c above max time window "
                        f"({time_to_expiry_seconds}s > {regime.max_time_to_expiry_seconds}s)"
                    )
                    continue
            
            return regime
    
    return None


@dataclass(frozen=True)
class ExecutionScore:
    """Structured execution scoring for fee-aware decision making.
    
    Captures all components of the net executable edge calculation for
    transparent logging and debugging.
    """
    gross_edge_cents: Decimal
    fee_cents: Decimal
    slippage_cents: Decimal
    uncertainty_cents: Decimal
    net_edge_cents: Decimal
    regime: str
    execution_role: str
    rejection_reason: Optional[str] = None
    confidence: Optional[Decimal] = None
    depth_multiple: Optional[Decimal] = None
    spread_cents: Optional[int] = None
    size_multiplier: Optional[Decimal] = None


def compute_net_executable_edge(
    fair_prob: Decimal,
    executable_price_cents: int,
    fee_per_contract_cents: Decimal,
    slippage_buffer_cents: Decimal = Decimal("0.5"),
    uncertainty_buffer_cents: Decimal = Decimal("0.5"),
    side: str = "yes",
) -> Decimal:
    """Compute net executable edge after all costs and buffers.
    
    Net Edge = (fair_prob - executable_price_prob) - fee - slippage - uncertainty
    
    For NO positions, convert to YES-equivalent first:
        p_yes_equiv = 1 - p_no
        fair_prob_yes_equiv = 1 - fair_prob_no
    
    Args:
        fair_prob: Model fair probability (0-1)
        executable_price_cents: Executable price in cents
        fee_per_contract_cents: Fee per contract in cents
        slippage_buffer_cents: Expected slippage buffer
        uncertainty_buffer_cents: Calibration uncertainty buffer
        side: "yes" or "no"
        
    Returns:
        Net edge in cents (can be negative)
        
    Examples:
        >>> compute_net_executable_edge(
        ...     fair_prob=Decimal("0.54"),
        ...     executable_price_cents=50,
        ...     fee_per_contract_cents=Decimal("1.75"),
        ... )
        Decimal("1.25")  # 4c gross - 1.75c fee - 0.5c slippage - 0.5c uncertainty
    """
    if side.lower() == "no":
        # Convert NO to YES-equivalent
        executable_price_prob = Decimal(1) - (Decimal(executable_price_cents) / Decimal("100"))
        fair_prob = Decimal(1) - fair_prob
    else:
        executable_price_prob = Decimal(executable_price_cents) / Decimal("100")
    
    gross_edge = fair_prob - executable_price_prob
    gross_edge_cents = gross_edge * Decimal("100")
    
    net_edge_cents = (
        gross_edge_cents
        - fee_per_contract_cents
        - slippage_buffer_cents
        - uncertainty_buffer_cents
    )
    
    return net_edge_cents