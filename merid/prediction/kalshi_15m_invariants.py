"""
Kalshi 15-Minute Up/Down Market Invariants

This module codifies the semantic invariants for Kalshi 15-minute crypto markets
(BTC, ETH, SOL, XRP, DOGE), ensuring consistent mapping between strategy intent,
thesis_side, and Kalshi contract legs.

Market Semantics:
- Kalshi 15m Up/Down markets are binary contracts on whether the underlying asset
  price will be HIGHER (Up) or LOWER (Down) at the 15-minute resolution window.
- Each market exposes one binary contract with YES/NO legs corresponding to
  "Up" vs "Down" for the underlying over the 15-minute resolution.

Canonical Mapping (2026-07-23):
- BULLISH_EVENT (bet on event occurring) → thesis_side = YES → "Up" leg
- BEARISH_EVENT (bet against event occurring) → thesis_side = NO → "Down" leg

Key Invariants:
1. Intent → thesis_side mapping is deterministic and never inverted
2. thesis_side is immutable per position (set at entry, never changed)
3. Kalshi leg is derived from thesis_side, not hardcoded
4. Exit orders use thesis_side from position state, not mutable cache
5. YES/NO legs correspond to Up/Down outcomes per market definition

Usage::

    from merid.prediction.kalshi_15m_invariants import (
        get_up_down_leg_mapping,
        validate_kalshi_15m_leg_consistency,
        Kalshi15MMarketType
    )
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

try:
    from merid.prediction.signal_terminology import StrategyIntent
except ImportError:
    class StrategyIntent:
        BULLISH_EVENT = "bullish_event"
        BEARISH_EVENT = "bearish_event"
        NEUTRAL = "neutral"


class Kalshi15MMarketType(str, Enum):
    """Kalshi 15-minute market types for crypto assets."""
    
    # Up/Down markets: binary on whether price goes up or down
    UP_DOWN = "up_down"
    
    # Future market types (not yet implemented)
    # RANGE = "range"  # Binary on whether price stays in range
    # TOUCH = "touch"  # Binary on whether price touches level


@dataclass
class UpDownLegMapping:
    """Mapping between strategy intent and Kalshi Up/Down legs."""
    
    intent: StrategyIntent
    thesis_side: str  # "yes" or "no"
    kalshi_leg: str  # "Up" or "Down"
    description: str
    
    def to_dict(self) -> Dict:
        return {
            "intent": self.intent.value,
            "thesis_side": self.thesis_side,
            "kalshi_leg": self.kalshi_leg,
            "description": self.description,
        }


# Canonical mapping for 15m Up/Down markets
# CRITICAL: This is the SINGLE SOURCE OF TRUTH for intent → leg mapping
_KALSHI_15M_UP_DOWN_MAPPING = {
    StrategyIntent.BULLISH_EVENT: UpDownLegMapping(
        intent=StrategyIntent.BULLISH_EVENT,
        thesis_side="yes",
        kalshi_leg="Up",
        description="BULLISH_EVENT: Bet on event occurring (price goes Up in 15m)"
    ),
    StrategyIntent.BEARISH_EVENT: UpDownLegMapping(
        intent=StrategyIntent.BEARISH_EVENT,
        thesis_side="no",
        kalshi_leg="Down",
        description="BEARISH_EVENT: Bet against event occurring (price goes Down in 15m)"
    ),
}


def get_up_down_leg_mapping(intent: StrategyIntent) -> Optional[UpDownLegMapping]:
    """Get the canonical leg mapping for a strategy intent.
    
    Args:
        intent: Strategy intent (BULLISH_EVENT or BEARISH_EVENT)
        
    Returns:
        UpDownLegMapping or None if intent is NEUTRAL
        
    Raises:
        ValueError: If intent is not recognized
    """
    if intent == StrategyIntent.NEUTRAL:
        return None
    
    if intent not in _KALSHI_15M_UP_DOWN_MAPPING:
        raise ValueError(f"Unknown intent: {intent}")
    
    return _KALSHI_15M_UP_DOWN_MAPPING[intent]


def validate_kalshi_15m_leg_consistency(
    intent: StrategyIntent,
    thesis_side: str,
    kalshi_leg: str,
    market_type: Kalshi15MMarketType = Kalshi15MMarketType.UP_DOWN,
) -> Tuple[bool, Optional[str]]:
    """Validate that thesis_side and kalshi_leg match the canonical mapping.
    
    Args:
        intent: Strategy intent
        thesis_side: thesis_side from position ("yes" or "no")
        kalshi_leg: Kalshi leg ("Up" or "Down")
        market_type: Market type (default UP_DOWN)
        
    Returns:
        (is_valid, error_message)
    """
    if market_type != Kalshi15MMarketType.UP_DOWN:
        return False, f"Unsupported market type: {market_type}"
    
    if intent == StrategyIntent.NEUTRAL:
        # NEUTRAL intent has no directional leg mapping
        return True, None
    
    # Get canonical mapping
    canonical = get_up_down_leg_mapping(intent)
    if canonical is None:
        return False, f"No mapping for intent: {intent}"
    
    # Validate thesis_side
    if thesis_side.lower() != canonical.thesis_side.lower():
        return False, (
            f"Thesis side mismatch: intent={intent.value} expects thesis_side={canonical.thesis_side}, "
            f"got {thesis_side}"
        )
    
    # Validate kalshi_leg
    if kalshi_leg != canonical.kalshi_leg:
        return False, (
            f"Kalshi leg mismatch: intent={intent.value} expects leg={canonical.kalshi_leg}, "
            f"got {kalshi_leg}"
        )
    
    return True, None


def get_market_definition(
    asset: str,
    market_type: Kalshi15MMarketType = Kalshi15MMarketType.UP_DOWN,
) -> Dict[str, str]:
    """Get the market definition for an asset.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        market_type: Market type (default UP_DOWN)
        
    Returns:
        Dict with market definition including YES/NO leg semantics
    """
    if market_type == Kalshi15MMarketType.UP_DOWN:
        return {
            "asset": asset,
            "market_type": market_type.value,
            "yes_leg": "Up",
            "no_leg": "Down",
            "description": f"Binary contract on whether {asset} price goes Up or Down in 15 minutes",
            "resolution": "15-minute window",
            "underlying": f"{asset}/USD spot price",
        }
    else:
        raise ValueError(f"Unsupported market type: {market_type}")


def validate_asset_market_support(asset: str) -> Tuple[bool, Optional[str]]:
    """Validate that an asset is supported for 15m trading.
    
    Args:
        asset: Asset symbol
        
    Returns:
        (is_supported, error_message)
    """
    supported_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    if asset.upper() not in supported_assets:
        return False, (
            f"Asset {asset} not supported for 15m trading. "
            f"Supported assets: {', '.join(supported_assets)}"
        )
    
    return True, None


# Invariant documentation strings for logging
INVARIANT_DOCUMENTATION = """
Kalshi 15-Minute Up/Down Market Invariants (2026-07-23)

1. Intent → thesis_side Mapping (Canonical):
   - BULLISH_EVENT → thesis_side = YES (bet on "Up" outcome)
   - BEARISH_EVENT → thesis_side = NO (bet on "Down" outcome)
   - This mapping is NEVER inverted

2. thesis_side Immutability:
   - Set from entry intent during position creation
   - Never overwritten by REST sync or WebSocket updates
   - REST/WebSocket data used for quantity/price only, never for side

3. Kalshi Leg Semantics:
   - YES leg = "Up" (price higher at 15m resolution)
   - NO leg = "Down" (price lower at 15m resolution)
   - Legs are derived from thesis_side, not hardcoded

4. Exit Order Consistency:
   - Exit orders use thesis_side from position state
   - Deterministic mapping: thesis_side → Kalshi format
   - Backward compatibility: fallback to position.side for legacy positions

5. Asset Coverage:
   - All 5 assets must be included: BTC, ETH, SOL, XRP, DOGE
   - No asset skipping or disabling allowed
   - Per-asset tuning allowed (volatility, thresholds) but not exclusion

6. Price Range:
   - Canonical range: 10c-75c for order execution
   - Crisis regime: 5c-95c (expanded during extreme volatility)
   - Price clamping enforced at multiple layers

7. Risk Exposure:
   - $1 global exposure cap (fixed dollar model)
   - No percentage-based allocation caps
   - Exit orders bypass allocation (reduce exposure)
"""


def log_invariant_violation(
    invariant_name: str,
    details: str,
    asset: str,
    severity: str = "CRITICAL",
) -> str:
    """Generate a formatted invariant violation log message.
    
    Args:
        invariant_name: Name of the violated invariant
        details: Details of the violation
        asset: Asset involved
        severity: Severity level (CRITICAL, WARNING, INFO)
        
    Returns:
        Formatted log message
    """
    return (
        f"[{severity}] INVARIANT VIOLATION: {invariant_name} | "
        f"asset={asset} | {details}"
    )
