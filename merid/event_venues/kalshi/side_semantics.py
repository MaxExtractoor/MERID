"""Unified Side and Outcome enums for Kalshi markets.

This module provides canonical type-safe enums for sides and outcomes
to eliminate stringly-typed "yes/no" inconsistencies across the codebase.

CRITICAL: This module is now integrated with signal_terminology.py for
unified signal terminology across the entire codebase. The Side and Action
enums here are the canonical Kalshi-specific definitions, while signal_terminology.py
provides broader trading signal concepts (Direction, Momentum, Velocity, StrategyMode).

Usage::

    from merid.event_venues.kalshi.side_semantics import Side, Outcome, Action

    # Side selection
    side = Side.YES
    assert side == "yes"  # String comparison works
    assert side.value == "yes"  # Explicit value access

    # Outcome determination
    outcome = Outcome.from_kalshi_result(True)  # YES won
    outcome = Outcome.from_position_and_pnl(side="yes", pnl_cents=50)

    # Action enum
    action = Action.BUY
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

# Import unified signal terminology for integration
try:
    from merid.prediction.signal_terminology import Side as UnifiedSide, Action as UnifiedAction
    UNIFIED_TERMINOLOGY_AVAILABLE = True
except ImportError:
    UNIFIED_TERMINOLOGY_AVAILABLE = False


class Side(str, Enum):
    """Kalshi market side - YES or NO.
    
    This enum is a string enum, so it can be compared to strings directly
    for backward compatibility while providing type safety.
    """
    YES = "yes"
    NO = "no"

    @classmethod
    def from_string(cls, value: str) -> "Side":
        """Parse string to Side enum, case-insensitive.
        
        Args:
            value: String representation ("yes", "no", "YES", "NO", etc.)
            
        Returns:
            Side enum
            
        Raises:
            ValueError: If value is not a valid side
        """
        normalized = value.lower().strip()
        if normalized == "yes":
            return cls.YES
        elif normalized == "no":
            return cls.NO
        else:
            raise ValueError(f"Invalid side: {value!r}. Must be 'yes' or 'no'")

    def opposite(self) -> "Side":
        """Return the opposite side."""
        return Side.NO if self == Side.YES else Side.YES

    def to_buy_action_for_long(self) -> "Action":
        """For a long position (betting on this side), return the buy action."""
        return Action.BUY

    def to_sell_action_for_exit(self) -> "Action":
        """For exiting a position on this side, return the sell action."""
        return Action.SELL


class Action(str, Enum):
    """Order action - BUY or SELL."""
    BUY = "buy"
    SELL = "sell"

    @classmethod
    def from_string(cls, value: str) -> "Action":
        """Parse string to Action enum, case-insensitive."""
        normalized = value.lower().strip()
        if normalized == "buy":
            return cls.BUY
        elif normalized == "sell":
            return cls.SELL
        else:
            raise ValueError(f"Invalid action: {value!r}. Must be 'buy' or 'sell'")


class Outcome(str, Enum):
    """Settlement outcome - YES_WON, NO_WON, or UNKNOWN.
    
    This enum represents the actual settlement result of a market,
    independent of which side was traded.
    """
    YES_WON = "yes_won"
    NO_WON = "no_won"
    UNKNOWN = "unknown"

    @classmethod
    def from_kalshi_result(cls, settled_yes: bool) -> "Outcome":
        """Create Outcome from Kalshi API settlement result.
        
        Args:
            settled_yes: True if YES won, False if NO won
            
        Returns:
            Outcome enum
        """
        return cls.YES_WON if settled_yes else cls.NO_WON

    @classmethod
    def from_position_and_pnl(
        cls,
        side: str,
        pnl_cents: int,
        position_closed: bool = True
    ) -> "Outcome":
        """Infer outcome from position side and realized PnL.
        
        This is a fallback inference method when Kalshi API is unavailable.
        It assumes the position was held to settlement.
        
        Args:
            side: Position side ("yes" or "no")
            pnl_cents: Realized PnL in cents (positive for win, negative for loss)
            position_closed: Whether position is closed (default True)
            
        Returns:
            Inferred Outcome enum
        """
        if not position_closed:
            return cls.UNKNOWN

        side_enum = Side.from_string(side)
        
        # If PnL is positive, the side we held won
        # If PnL is negative, the opposite side won
        if pnl_cents > 0:
            return cls.YES_WON if side_enum == Side.YES else cls.NO_WON
        elif pnl_cents < 0:
            return cls.NO_WON if side_enum == Side.YES else cls.YES_WON
        else:
            # PnL = 0 could mean scratch or unclear - conservatively unknown
            return cls.UNKNOWN

    @classmethod
    def from_side_hint(cls, side_hint: str) -> "Outcome":
        """Infer outcome from position side hint (conservative fallback).
        
        This assumes the position was held to settlement and the side
        held is the outcome. This is ONLY safe when:
        - Kalshi API is unavailable
        - Market is clearly expired
        - No open position exists
        
        Args:
            side_hint: Position side at close ("yes" or "no")
            
        Returns:
            Inferred Outcome (WARNING: this is a fallback, not authoritative)
        """
        side_enum = Side.from_string(side_hint)
        return cls.YES_WON if side_enum == Side.YES else cls.NO_WON

    def did_side_win(self, side: str) -> bool:
        """Check if a given side won based on this outcome.
        
        Args:
            side: Side to check ("yes" or "no")
            
        Returns:
            True if the side won, False otherwise
        """
        side_enum = Side.from_string(side)
        if self == Outcome.YES_WON:
            return side_enum == Side.YES
        elif self == Outcome.NO_WON:
            return side_enum == Side.NO
        else:
            return False  # UNKNOWN means we can't determine

    def to_settled_yes(self) -> Optional[bool]:
        """Convert to Kalshi API format (True/False/None).
        
        Returns:
            True if YES won, False if NO won, None if UNKNOWN
        """
        if self == Outcome.YES_WON:
            return True
        elif self == Outcome.NO_WON:
            return False
        else:
            return None


# Type aliases for common patterns
SideLiteral = Literal["yes", "no"]
ActionLiteral = Literal["buy", "sell"]
OutcomeLiteral = Literal["yes_won", "no_won", "unknown"]


def normalize_side(value: str) -> str:
    """Normalize any side representation to canonical lowercase string.
    
    Args:
        value: Any side representation ("yes", "YES", "Yes", "no", etc.)
        
    Returns:
        Canonical lowercase string ("yes" or "no")
        
    Raises:
        ValueError: If value is not a valid side
    """
    return Side.from_string(value).value


def normalize_action(value: str) -> str:
    """Normalize any action representation to canonical lowercase string.
    
    Args:
        value: Any action representation ("buy", "BUY", "Buy", etc.)
        
    Returns:
        Canonical lowercase string ("buy" or "sell")
        
    Raises:
        ValueError: If value is not a valid action
    """
    return Action.from_string(value).value
