"""Kalshi Order Constraints - Enforces API and market-specific rules.

This module validates orders against Kalshi's API constraints and market rules
before they are submitted to the exchange. This ensures compliance with:

1. Market status gating (only submit when market is open/active)
2. Price bounds (0-100 cents for binary markets)
3. Quantity limits (per-order and per-market limits)
4. Trading windows (no orders after close_time, respect halts)

All constraints are enforced before HTTP requests to avoid API rejections.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple, List

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_constraints")


class OrderRejectionReason(str, Enum):
    """Reasons for rejecting an order based on Kalshi constraints."""
    MARKET_NOT_OPEN = "market_not_open"
    MARKET_CLOSED = "market_closed"
    MARKET_SETTLED = "market_settled"
    MARKET_PAUSED = "market_paused"
    PRICE_OUT_OF_BOUNDS = "price_out_of_bounds"
    QUANTITY_TOO_SMALL = "quantity_too_small"
    QUANTITY_TOO_LARGE = "quantity_too_large"
    MARKET_LIMIT_EXCEEDED = "market_limit_exceeded"
    TRADING_WINDOW_CLOSED = "trading_window_closed"
    MARKET_HALTED = "market_halted"


@dataclass
class OrderConstraintResult:
    """Result of order constraint validation."""
    allowed: bool
    reason: Optional[OrderRejectionReason] = None
    message: str = ""
    
    @classmethod
    def allowed_result(cls) -> "OrderConstraintResult":
        """Create a result indicating the order is allowed."""
        return cls(allowed=True)
    
    @classmethod
    def rejected_result(cls, reason: OrderRejectionReason, message: str) -> "OrderConstraintResult":
        """Create a result indicating the order is rejected."""
        return cls(allowed=False, reason=reason, message=message)


@dataclass
class KalshiOrderLimits:
    """Kalshi order limits from API documentation."""
    # Binary market price bounds (cents)
    MIN_PRICE_CENTS: int = 1
    MAX_PRICE_CENTS: int = 99
    
    # Per-order quantity limits
    MIN_ORDER_SIZE: int = 1
    MAX_ORDER_SIZE: int = 10000  # Default max per order
    
    # Per-market position limits (contracts)
    MAX_POSITION_SIZE: int = 10000  # Default max per market
    
    # Trading window buffer (seconds before close)
    CLOSE_WINDOW_BUFFER_SECONDS: int = 60  # Don't trade within 60s of close


class KalshiOrderConstraints:
    """Validates orders against Kalshi API and market constraints."""
    
    def __init__(self, limits: Optional[KalshiOrderLimits] = None):
        """Initialize constraints with optional custom limits."""
        self.limits = limits or KalshiOrderLimits()
        self.logger = logger
    
    def validate_order(
        self,
        market_id: str,
        market_status: str,
        market_close_time: Optional[datetime],
        side: str,
        price_cents: int,
        quantity: int,
        current_position: int = 0,
        market_halted: bool = False,
    ) -> OrderConstraintResult:
        """Validate an order against all Kalshi constraints.
        
        Args:
            market_id: Kalshi market ticker
            market_status: Current market status (active, paused, closed, settled)
            market_close_time: Market close timestamp (if available)
            side: Order side (yes/no)
            price_cents: Price in cents (1-99 for binary markets)
            quantity: Number of contracts
            current_position: Current position size in this market
            market_halted: Whether the market is halted
            
        Returns:
            OrderConstraintResult indicating if order is allowed
        """
        # Check market status first
        status_result = self._validate_market_status(market_id, market_status, market_halted)
        if not status_result.allowed:
            return status_result
        
        # Check trading window
        if market_close_time:
            window_result = self._validate_trading_window(market_id, market_close_time)
            if not window_result.allowed:
                return window_result
        
        # Check price bounds
        price_result = self._validate_price_bounds(market_id, price_cents)
        if not price_result.allowed:
            return price_result
        
        # Check quantity limits
        qty_result = self._validate_quantity_limits(
            market_id, quantity, current_position
        )
        if not qty_result.allowed:
            return qty_result
        
        return OrderConstraintResult.allowed_result()
    
    def _validate_market_status(
        self,
        market_id: str,
        market_status: str,
        market_halted: bool,
    ) -> OrderConstraintResult:
        """Validate that market is in a tradable status."""
        if market_halted:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Market halted: %s",
                market_id
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.MARKET_HALTED,
                f"Market {market_id} is halted"
            )
        
        # Normalize status to lowercase for comparison
        status_normalized = market_status.lower().strip()
        
        if status_normalized == "closed":
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Market closed: %s",
                market_id
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.MARKET_CLOSED,
                f"Market {market_id} is closed"
            )
        
        if status_normalized == "settled":
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Market settled: %s",
                market_id
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.MARKET_SETTLED,
                f"Market {market_id} is settled"
            )
        
        if status_normalized == "paused":
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Market paused: %s",
                market_id
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.MARKET_PAUSED,
                f"Market {market_id} is paused"
            )
        
        if status_normalized != "active":
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Unknown market status: %s for %s",
                market_status,
                market_id
            )
            # Be conservative: reject if status is unknown
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.MARKET_NOT_OPEN,
                f"Market {market_id} has unknown status: {market_status}"
            )
        
        return OrderConstraintResult.allowed_result()
    
    def _validate_trading_window(
        self,
        market_id: str,
        market_close_time: datetime,
    ) -> OrderConstraintResult:
        """Validate that we're not too close to market close."""
        now = datetime.now(timezone.utc)
        
        if market_close_time.tzinfo is None:
            market_close_time = market_close_time.replace(tzinfo=timezone.utc)
        
        time_until_close = (market_close_time - now).total_seconds()
        
        if time_until_close <= self.limits.CLOSE_WINDOW_BUFFER_SECONDS:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Trading window closed: %s (closes in %ds, buffer %ds)",
                market_id,
                int(time_until_close),
                self.limits.CLOSE_WINDOW_BUFFER_SECONDS
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.TRADING_WINDOW_CLOSED,
                f"Market {market_id} closes in {int(time_until_close)}s (buffer: {self.limits.CLOSE_WINDOW_BUFFER_SECONDS}s)"
            )
        
        if time_until_close < 0:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Market already closed: %s (closed %ds ago)",
                market_id,
                int(-time_until_close)
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.TRADING_WINDOW_CLOSED,
                f"Market {market_id} closed {int(-time_until_close)}s ago"
            )
        
        return OrderConstraintResult.allowed_result()
    
    def _validate_price_bounds(
        self,
        market_id: str,
        price_cents: int,
    ) -> OrderConstraintResult:
        """Validate that price is within Kalshi bounds."""
        if price_cents < self.limits.MIN_PRICE_CENTS:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Price too low: %s (price=%d cents, min=%d)",
                market_id,
                price_cents,
                self.limits.MIN_PRICE_CENTS
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.PRICE_OUT_OF_BOUNDS,
                f"Price {price_cents} cents below minimum {self.limits.MIN_PRICE_CENTS} cents"
            )
        
        if price_cents > self.limits.MAX_PRICE_CENTS:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Price too high: %s (price=%d cents, max=%d)",
                market_id,
                price_cents,
                self.limits.MAX_PRICE_CENTS
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.PRICE_OUT_OF_BOUNDS,
                f"Price {price_cents} cents above maximum {self.limits.MAX_PRICE_CENTS} cents"
            )
        
        return OrderConstraintResult.allowed_result()
    
    def _validate_quantity_limits(
        self,
        market_id: str,
        quantity: int,
        current_position: int,
    ) -> OrderConstraintResult:
        """Validate that quantity is within limits."""
        if quantity < self.limits.MIN_ORDER_SIZE:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Quantity too small: %s (qty=%d, min=%d)",
                market_id,
                quantity,
                self.limits.MIN_ORDER_SIZE
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.QUANTITY_TOO_SMALL,
                f"Quantity {quantity} below minimum {self.limits.MIN_ORDER_SIZE}"
            )
        
        if quantity > self.limits.MAX_ORDER_SIZE:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Quantity too large: %s (qty=%d, max=%d)",
                market_id,
                quantity,
                self.limits.MAX_ORDER_SIZE
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.QUANTITY_TOO_LARGE,
                f"Quantity {quantity} above maximum {self.limits.MAX_ORDER_SIZE}"
            )
        
        # Check per-market position limit
        new_position = current_position + quantity
        if abs(new_position) > self.limits.MAX_POSITION_SIZE:
            self.logger.warning(
                "[ORDER_CONSTRAINTS] Market limit exceeded: %s (new_pos=%d, max=%d)",
                market_id,
                new_position,
                self.limits.MAX_POSITION_SIZE
            )
            return OrderConstraintResult.rejected_result(
                OrderRejectionReason.MARKET_LIMIT_EXCEEDED,
                f"New position {new_position} would exceed market limit {self.limits.MAX_POSITION_SIZE}"
            )
        
        return OrderConstraintResult.allowed_result()


# Singleton instance
_order_constraints: Optional[KalshiOrderConstraints] = None


def get_order_constraints() -> KalshiOrderConstraints:
    """Get the singleton Kalshi order constraints instance."""
    global _order_constraints
    if _order_constraints is None:
        _order_constraints = KalshiOrderConstraints()
    return _order_constraints


def validate_kalshi_order(
    market_id: str,
    market_status: str,
    market_close_time: Optional[datetime],
    side: str,
    price_cents: int,
    quantity: int,
    current_position: int = 0,
    market_halted: bool = False,
) -> Tuple[bool, str]:
    """Validate a Kalshi order against constraints.
    
    Convenience function that returns a simple (allowed, reason) tuple.
    
    Args:
        market_id: Kalshi market ticker
        market_status: Current market status (active, paused, closed, settled)
        market_close_time: Market close timestamp (if available)
        side: Order side (yes/no)
        price_cents: Price in cents (1-99 for binary markets)
        quantity: Number of contracts
        current_position: Current position size in this market
        market_halted: Whether the market is halted
        
    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    constraints = get_order_constraints()
    result = constraints.validate_order(
        market_id=market_id,
        market_status=market_status,
        market_close_time=market_close_time,
        side=side,
        price_cents=price_cents,
        quantity=quantity,
        current_position=current_position,
        market_halted=market_halted,
    )
    
    if result.allowed:
        return True, ""
    else:
        return False, result.message
