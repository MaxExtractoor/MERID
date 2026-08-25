"""
Strategy Position Domain Layer

This module defines the domain model for strategy positions, implementing
thesis_side as a first-class invariant. It provides clean separation between
strategy intent (thesis_side) and exchange representation (action/side).

Based on Kalshi's order-direction semantics:
- outcome_side (yes/no) expresses which outcome the user is long
- book_side (bid/ask) carries the same bit in order-book vocabulary
- Legacy action/side are deprecated and should not drive logic

Reference: https://docs.kalshi.com/getting_started/order_direction
"""

import logging
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class PositionThesisMismatch(ValueError):
    """Raised when an exit is built from a prediction thesis that does not
    match the confirmed live exposure.  Exits must use confirmed exposure."""


class ThesisSide(str, Enum):
    """Strategy thesis side - immutable per position.
    
    Represents the outcome the strategy is long on, independent of
    how the exchange chooses to represent the trade leg.
    
    On Kalshi:
    - Long YES can be achieved via buy YES or sell NO
    - Long NO can be achieved via buy NO or sell YES
    
    This enum captures the semantic intent, not the exchange mechanics.
    """
    YES = "yes"
    NO = "no"
    
    @classmethod
    def from_outcome_side(cls, outcome_side: str) -> "ThesisSide":
        """Create ThesisSide from Kalshi outcome_side field."""
        outcome_lower = outcome_side.lower()
        if outcome_lower == "yes":
            return cls.YES
        elif outcome_lower == "no":
            return cls.NO
        else:
            raise ValueError(f"Invalid outcome_side: {outcome_side}")
    
    @classmethod
    def from_kalshi_format(cls, kalshi_side: str) -> "ThesisSide":
        """Create ThesisSide from Kalshi's legacy action/side format.
        
        Maps:
        - BUY_YES, SELL_NO -> YES (long YES exposure)
        - BUY_NO, SELL_YES -> NO (long NO exposure)
        """
        kalshi_upper = kalshi_side.upper()
        if kalshi_upper == "BUY_YES" or kalshi_upper == "SELL_NO":
            return cls.YES
        elif kalshi_upper == "BUY_NO" or kalshi_upper == "SELL_YES":
            return cls.NO
        else:
            raise ValueError(f"Invalid Kalshi format: {kalshi_side}")


@dataclass
class FillRecord:
    """Record of a fill for position tracking."""
    timestamp: datetime
    fill_id: str
    side: str  # Exchange-reported side (may be from REST, not authoritative)
    action: str  # Exchange-reported action (buy/sell)
    outcome_side: str  # Canonical outcome_side from fill payload
    count_fp: Decimal  # Number of contracts (fixed-point, fractional OK)
    price_cents: int
    fee_cents: int
    intent_side: str  # Original intent side from order trace

    def __post_init__(self):
        if not isinstance(self.count_fp, Decimal):
            try:
                self.count_fp = Decimal(str(self.count_fp))
            except Exception:
                self.count_fp = Decimal("0")


@dataclass
class StrategyPosition:
    """Strategy position with thesis_side as immutable invariant.
    
    This domain model separates strategy intent from exchange representation:
    - thesis_side: Immutable strategy thesis (what outcome am I long?)
    - size_fp: Net contracts (positive = long thesis, negative = short thesis)
    - entry_fills: Record of fills that opened/added to position
    - exit_fills: Record of fills that closed/thinned position
    
    Entry creation:
    - When a new position is opened, set thesis_side from fill's outcome_side
    - Subsequent fills must have same outcome_side as thesis_side
    - Otherwise treat as hedges or separate positions
    
    Exit logic:
    - To flatten: "sell thesis" = reduce size_fp toward zero
    - Direction is thesis_side, quantity is negative delta
    - Generate all exit orders from thesis_side, never from position.side
    """
    ticker: str
    thesis_side: ThesisSide  # Immutable per position
    size_fp: Decimal  # Net contracts (fixed-point, fractional OK)
    avg_entry_price_cents: int
    agent_id: str = ""  # Agent identifier for composite key (ticker, agent_id); default for temp/wrapper positions
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    entry_fills: List[FillRecord] = field(default_factory=list)
    exit_fills: List[FillRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not isinstance(self.size_fp, Decimal):
            try:
                self.size_fp = Decimal(str(self.size_fp))
            except Exception:
                self.size_fp = Decimal("0")

    def add_entry_fill(self, fill: FillRecord) -> None:
        """Add an entry fill to the position.
        
        Validates that the fill's outcome_side matches thesis_side.
        If not, raises an error (this fill should be treated as hedge/separate position).
        
        Zero-quantity fills are treated as telemetry only and do not change position state.
        """
        # V15: Guard against 0-quantity fills - telemetry only, no state change
        if fill.count_fp == 0:
            logger.info(
                "[STRATEGY-POSITION] Zero-quantity entry fill ignored: fill_id=%s ticker=%s "
                "outcome_side=%s price_cents=%d - no position change",
                fill.fill_id, self.ticker, fill.outcome_side, fill.price_cents
            )
            return
        
        fill_outcome = ThesisSide.from_outcome_side(fill.outcome_side)
        if fill_outcome != self.thesis_side:
            raise ValueError(
                f"Fill outcome_side={fill.outcome_side} does not match "
                f"position thesis_side={self.thesis_side.value}. "
                f"This fill should be treated as hedge or separate position."
            )
        
        self.entry_fills.append(fill)
        self._update_size_and_avg_price(fill.count_fp, fill.price_cents, is_entry=True)
        self.last_updated = datetime.utcnow()
    
    def add_exit_fill(self, fill: FillRecord) -> None:
        """Add an exit fill to the position.
        
        Validates that the fill reduces exposure toward zero.
        
        Zero-quantity fills are treated as telemetry only and do not change position state.
        """
        # V15: Guard against 0-quantity fills - telemetry only, no state change
        if fill.count_fp == 0:
            logger.info(
                "[STRATEGY-POSITION] Zero-quantity exit fill ignored: fill_id=%s ticker=%s "
                "outcome_side=%s price_cents=%d - no position change",
                fill.fill_id, self.ticker, fill.outcome_side, fill.price_cents
            )
            return
        
        if fill.count_fp <= 0:
            raise ValueError(f"Exit fill must have positive count_fp, got {fill.count_fp}")
        
        if fill.count_fp > self.size_fp:
            raise ValueError(
                f"Exit fill count_fp={fill.count_fp} exceeds position size_fp={self.size_fp}. "
                f"This would over-close the position."
            )
        
        self.exit_fills.append(fill)
        self._update_size_and_avg_price(fill.count_fp, fill.price_cents, is_entry=False)
        self.last_updated = datetime.utcnow()
    
    def _update_size_and_avg_price(self, count_fp: Decimal, price_cents: int, is_entry: bool) -> None:
        """Update size and average price based on fill."""
        if not isinstance(count_fp, Decimal):
            count_fp = Decimal(str(count_fp))
        if is_entry:
            # Adding to position
            total_cost_old = self.size_fp * Decimal(self.avg_entry_price_cents)
            total_cost_new = count_fp * Decimal(price_cents)
            self.size_fp += count_fp
            if self.size_fp > 0:
                avg = (total_cost_old + total_cost_new) / self.size_fp
                self.avg_entry_price_cents = int(avg.to_integral_value(rounding=__import__("decimal").ROUND_HALF_UP))
            else:
                self.avg_entry_price_cents = price_cents
        else:
            # Removing from position
            self.size_fp -= count_fp
            # Average price doesn't change on exit (FIFO or specific lot tracking would require more complex logic)
    
    @property
    def is_open(self) -> bool:
        """Check if position is open (has non-zero size)."""
        return self.size_fp > 0
    
    @property
    def notional_usd(self) -> float:
        """Compute notional value in USD."""
        return float(self.size_fp * Decimal(self.avg_entry_price_cents) / Decimal("100"))


def thesis_to_outcome_side(thesis_side: ThesisSide) -> str:
    """Convert thesis_side to Kalshi outcome_side.
    
    This is a pure function that encapsulates the canonical mapping
    from strategy thesis to Kalshi's outcome_side field.
    
    Args:
        thesis_side: Strategy thesis side (YES or NO)
        
    Returns:
        Kalshi outcome_side string ("yes" or "no")
    """
    return thesis_side.value


def build_exit_order(
    position: StrategyPosition,
    qty_fp: Decimal,
    price_cents: int,
) -> dict:
    """Build exit order dict from strategy position.
    
    This is a pure function that encapsulates the canonical mapping
    from strategy thesis to Kalshi's order fields.
    
    For exits, we are "selling" the thesis (thinning long exposure).
    This generates an order that reduces long outcome_side exposure.
    
    Args:
        position: Strategy position with thesis_side
        qty_fp: Quantity to close (must be > 0 and <= position.size_fp)
        price_cents: Limit price in cents
        
    Returns:
        Dict with Kalshi order fields
        
    Raises:
        ValueError: If qty_fp is invalid or position is not open
    """
    if not isinstance(qty_fp, Decimal):
        qty_fp = Decimal(str(qty_fp))

    # CRITICAL FIX (2026-07-21): Exit invariants
    # Assert position size is positive (check before is_open)
    if position.size_fp <= 0:
        raise ValueError(
            f"Position size_fp must be positive for exit: ticker={position.ticker} size_fp={position.size_fp}"
        )

    # Assert position is open (has non-zero size)
    if not position.is_open:
        raise ValueError(
            f"Cannot exit closed position: ticker={position.ticker} size_fp={position.size_fp}"
        )

    if qty_fp <= 0:
        raise ValueError(f"Exit quantity must be positive, got {qty_fp}")
    if qty_fp > position.size_fp:
        raise ValueError(
            f"Exit quantity {qty_fp} exceeds position size {position.size_fp}"
        )
    
    outcome_side = thesis_to_outcome_side(position.thesis_side)
    
    # For Kalshi, we use the legacy action/side format for compatibility
    # But derive it deterministically from thesis_side
    if position.thesis_side == ThesisSide.YES:
        kalshi_side = "SELL_YES"  # Sell YES to close long YES
    else:
        kalshi_side = "SELL_NO"  # Sell NO to close long NO
    
    return {
        "market_ticker": position.ticker,
        "outcome_side": outcome_side,
        "action": "sell",
        "side": outcome_side,
        "kalshi_side": kalshi_side,
        "size_fp": qty_fp,
        "price_cents": price_cents,
        "thesis_side": position.thesis_side.value,  # For debugging
    }


def build_exit(
    confirmed_position: StrategyPosition,
    qty_fp: Decimal,
    price_cents: int,
    thesis_side: Optional[ThesisSide] = None,
) -> dict:
    """Build an exit order from the confirmed live exposure.

    Args:
        confirmed_position: StrategyPosition built from confirmed fills/positions.
        qty_fp: Quantity to close.
        price_cents: Limit price in cents (the risk price, not a sweet-spot rewrite).
        thesis_side: Optional explicit thesis to verify against the confirmed side.

    Raises:
        PositionThesisMismatch: If the provided thesis_side disagrees with the
            confirmed position's outcome side.
        ValueError: For size/qty invariants.
    """
    if not isinstance(qty_fp, Decimal):
        qty_fp = Decimal(str(qty_fp))

    if thesis_side is not None and thesis_side != confirmed_position.thesis_side:
        raise PositionThesisMismatch(
            f"thesis_side={thesis_side.value} does not match "
            f"confirmed_position.thesis_side={confirmed_position.thesis_side.value}"
        )

    if qty_fp <= 0:
        raise ValueError(f"Exit quantity must be positive, got {qty_fp}")
    if qty_fp > confirmed_position.size_fp:
        raise ValueError(
            f"Exit quantity {qty_fp} exceeds position size {confirmed_position.size_fp}"
        )

    return build_exit_order(confirmed_position, qty_fp, price_cents)
