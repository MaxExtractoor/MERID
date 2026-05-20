"""Canonical Portfolio Model for Kalshi Event-Driven Reconciliation.

This module defines the data structures for the event-sourced portfolio system:
- Account: Represents a Kalshi account/subaccount
- CashLedgerEntry: Individual cash events (deposits, withdrawals, fees, trades, settlements)
- Position: Per-market position with quantity, entry price, cost basis, realized PnL
- Order: Working orders with reserved cash
- Fill: Trade events that mutate positions and cash
- PortfolioEvent: Append-only event log entries

Design principles:
- All monetary values stored in cents (integers) to match Kalshi API
- Use Decimal for PnL calculations to avoid floating-point drift
- Event sequence ID ensures deterministic replay
- Unrealized PnL always derived from positions + current marks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any
from uuid import uuid4

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.portfolio_models")


# ═══════════════════════════════════════════════════════════════════════════
# Event Types
# ═══════════════════════════════════════════════════════════════════════════

class EventType(Enum):
    """Types of portfolio events."""
    FILL = "fill"  # Trade execution
    ORDER_CREATED = "order_created"  # New order placed
    ORDER_FILLED = "order_filled"  # Order partially/fully filled
    ORDER_CANCELLED = "order_cancelled"  # Order cancelled
    ORDER_EXPIRED = "order_expired"  # Order expired
    SETTLEMENT = "settlement"  # Market settlement
    CASH_DEPOSIT = "cash_deposit"  # Deposit to account
    CASH_WITHDRAWAL = "cash_withdrawal"  # Withdrawal from account
    FEE = "fee"  # Trading fee
    REFUND = "refund"  # Fee refund
    ADJUSTMENT = "adjustment"  # Manual adjustment


class CashEventType(Enum):
    """Types of cash ledger entries."""
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRADE = "trade"  # Cash impact from fill
    FEE = "fee"
    REFUND = "refund"
    SETTLEMENT = "settlement"  # PnL realization on settlement
    ADJUSTMENT = "adjustment"


# ═══════════════════════════════════════════════════════════════════════════
# Core Data Models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Account:
    """Represents a Kalshi account/subaccount."""
    account_id: str
    kalshi_subaccount_id: Optional[str] = None
    currency: str = "USD"
    risk_limits: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True


@dataclass(frozen=True)
class CashLedgerEntry:
    """Individual cash event in the ledger.
    
    All amounts in cents (integers) to match Kalshi API precision.
    """
    entry_id: str
    account_id: str
    event_type: CashEventType
    amount_cents: int  # Positive for deposits/income, negative for withdrawals/expenses
    related_order_id: Optional[str] = None
    related_fill_id: Optional[str] = None
    related_ticker: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Position:
    """Per-market position state.
    
    All monetary values in cents (integers).
    """
    position_id: str
    account_id: str
    ticker: str  # Kalshi market ticker
    side: str  # "yes" or "no"
    quantity: int  # Signed quantity (positive for long, negative for short)
    avg_entry_price_cents: int  # Weighted average entry price
    cost_basis_cents: int  # quantity * avg_entry_price_cents (sign-aware)
    realized_pnl_cents: int = 0  # Crystallized PnL from closes/settlements
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def is_open(self) -> bool:
        return self.quantity != 0
    
    @property
    def market_value_cents(self) -> int:
        """Current market value = quantity * current_mark (not stored, derived)."""
        # This would be computed from current market price
        return 0  # Placeholder - computed by portfolio engine


@dataclass(frozen=True)
class Order:
    """Working order with reserved cash.
    
    All monetary values in cents (integers).
    """
    order_id: str
    account_id: str
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    quantity: int  # Total order quantity
    price_cents: int  # Limit price
    status: str  # "resting", "filled", "cancelled", "expired"
    filled_quantity: int = 0
    remaining_quantity: int = 0
    reserved_cash_cents: int = 0  # Cash reserved for this order
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    client_order_id: Optional[str] = None
    agent_id: Optional[str] = None
    
    def __post_init__(self):
        # Derive remaining_quantity if not set
        if self.remaining_quantity == 0:
            object.__setattr__(self, 'remaining_quantity', self.quantity - self.filled_quantity)


@dataclass(frozen=True)
class Fill:
    """Trade event that mutates positions and cash.
    
    All monetary values in cents (integers).
    """
    fill_id: str
    order_id: str
    account_id: str
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    quantity: int  # Contracts filled in this event
    price_cents: int  # Fill price
    fee_cents: int  # Trading fee
    fill_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    venue_fill_id: Optional[str] = None
    agent_id: Optional[str] = None
    ingestion_source: str = "unknown"  # "http" or "websocket"
    
    @property
    def notional_cents(self) -> int:
        """Notional value = quantity * price_cents."""
        return self.quantity * self.price_cents
    
    @property
    def net_cash_impact_cents(self) -> int:
        """Net cash impact = notional + fee (sign-aware based on action)."""
        direction = 1 if self.action == "sell" else -1
        return direction * self.notional_cents - self.fee_cents


@dataclass(frozen=True)
class PortfolioEvent:
    """Append-only event log entry.
    
    This is the single source of truth for all portfolio state transitions.
    Events are replayed in sequence order to reconstruct portfolio state.
    """
    event_id: str
    sequence_id: int  # Monotonically increasing, ensures ordering
    event_type: EventType
    account_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/transmission."""
        return {
            "event_id": self.event_id,
            "sequence_id": self.sequence_id,
            "event_type": self.event_type.value,
            "account_id": self.account_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PortfolioEvent":
        """Create from dictionary (for storage retrieval)."""
        return cls(
            event_id=data["event_id"],
            sequence_id=data["sequence_id"],
            event_type=EventType(data["event_type"]),
            account_id=data["account_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            data=data["data"],
        )


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio Snapshot (Derived State)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EODSnapshot:
    """End-of-day snapshot for tracking prior close values needed for daily PnL calculation.
    
    Stored at market close to enable calculation of daily unrealized PnL change:
    daily_pnl = daily_realized + (current_unrealized - prior_close_unrealized)
    
    Attributes:
        account_id: Account identifier
        snapshot_date: Date of the snapshot (YYYY-MM-DD)
        cash_eod_cents: Cash balance at end of day
        portfolio_value_eod_cents: Portfolio value at end of day
        unrealized_pnl_eod_cents: Unrealized PnL at end of day
        timestamp_utc: When snapshot was recorded
    """
    account_id: str
    snapshot_date: str  # YYYY-MM-DD format
    cash_eod_cents: int
    portfolio_value_eod_cents: int
    unrealized_pnl_eod_cents: int
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Complete portfolio state at a point in time.
    
    This is derived by replaying events up to a given sequence_id.
    All monetary values in cents (integers) except PnL fields (Decimal).
    """
    account_id: str
    sequence_id: int  # Last event processed
    timestamp: datetime
    
    # Cash state
    cash_available_cents: int
    cash_reserved_cents: int
    cash_total_cents: int
    
    # Positions
    positions: Dict[str, Position]  # ticker -> Position
    
    # Orders
    open_orders: Dict[str, Order]  # order_id -> Order
    
    # PnL
    realized_pnl_cents: int  # Crystallized PnL
    unrealized_pnl_cents: int  # Derived from positions + current marks
    
    @property
    def total_equity_cents(self) -> int:
        """Total equity = cash_available + unrealized_pnl."""
        return self.cash_available_cents + self.unrealized_pnl_cents
    
    @property
    def total_equity_usd(self) -> float:
        """Total equity in USD."""
        return self.total_equity_cents / 100.0
    
    @property
    def total_pnl_cents(self) -> int:
        """Total PnL = realized + unrealized."""
        return self.realized_pnl_cents + self.unrealized_pnl_cents
    
    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return sum(1 for p in self.positions.values() if p.is_open)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "account_id": self.account_id,
            "sequence_id": self.sequence_id,
            "timestamp": self.timestamp.isoformat(),
            "cash_available_cents": self.cash_available_cents,
            "cash_available_usd": self.cash_available_cents / 100.0,
            "cash_reserved_cents": self.cash_reserved_cents,
            "cash_total_cents": self.cash_total_cents,
            "positions": {
                ticker: {
                    "ticker": pos.ticker,
                    "side": pos.side,
                    "quantity": pos.quantity,
                    "avg_entry_price_cents": pos.avg_entry_price_cents,
                    "cost_basis_cents": pos.cost_basis_cents,
                    "realized_pnl_cents": pos.realized_pnl_cents,
                    "is_open": pos.is_open,
                    "last_updated": pos.last_updated.isoformat(),
                }
                for ticker, pos in self.positions.items()
            },
            "open_orders": {
                order_id: {
                    "order_id": order.order_id,
                    "ticker": order.ticker,
                    "side": order.side,
                    "action": order.action,
                    "quantity": order.quantity,
                    "price_cents": order.price_cents,
                    "status": order.status,
                    "filled_quantity": order.filled_quantity,
                    "remaining_quantity": order.remaining_quantity,
                    "reserved_cash_cents": order.reserved_cash_cents,
                    "created_at": order.created_at.isoformat(),
                }
                for order_id, order in self.open_orders.items()
            },
            "realized_pnl_cents": self.realized_pnl_cents,
            "realized_pnl_usd": self.realized_pnl_cents / 100.0,
            "unrealized_pnl_cents": self.unrealized_pnl_cents,
            "unrealized_pnl_usd": self.unrealized_pnl_cents / 100.0,
            "total_pnl_cents": self.total_pnl_cents,
            "total_pnl_usd": self.total_pnl_cents / 100.0,
            "total_equity_cents": self.total_equity_cents,
            "total_equity_usd": self.total_equity_usd,
            "position_count": self.position_count,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation Result
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ReconciliationResult:
    """Result of comparing internal state to Kalshi API."""
    account_id: str
    timestamp: datetime
    is_match: bool
    
    # Cash differences
    cash_diff_cents: int = 0
    cash_tolerance_cents: int = 1  # Allow 1 cent rounding
    
    # Position differences
    position_diff_count: int = 0
    position_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # PnL differences
    pnl_diff_cents: int = 0
    pnl_tolerance_cents: int = 10  # Allow 10 cents for pricing differences
    
    # Metadata
    internal_sequence_id: int = 0
    kalshi_api_timestamp: Optional[datetime] = None
    discrepancies: list = field(default_factory=list)
    
    @property
    def has_cash_discrepancy(self) -> bool:
        return abs(self.cash_diff_cents) > self.cash_tolerance_cents
    
    @property
    def has_position_discrepancy(self) -> bool:
        return self.position_diff_count > 0
    
    @property
    def has_pnl_discrepancy(self) -> bool:
        return abs(self.pnl_diff_cents) > self.pnl_tolerance_cents
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "timestamp": self.timestamp.isoformat(),
            "is_match": self.is_match,
            "cash_diff_cents": self.cash_diff_cents,
            "cash_diff_usd": self.cash_diff_cents / 100.0,
            "cash_tolerance_cents": self.cash_tolerance_cents,
            "position_diff_count": self.position_diff_count,
            "position_details": self.position_details,
            "pnl_diff_cents": self.pnl_diff_cents,
            "pnl_diff_usd": self.pnl_diff_cents / 100.0,
            "pnl_tolerance_cents": self.pnl_tolerance_cents,
            "internal_sequence_id": self.internal_sequence_id,
            "kalshi_api_timestamp": self.kalshi_api_timestamp.isoformat() if self.kalshi_api_timestamp else None,
            "discrepancies": self.discrepancies,
            "has_cash_discrepancy": self.has_cash_discrepancy,
            "has_position_discrepancy": self.has_position_discrepancy,
            "has_pnl_discrepancy": self.has_pnl_discrepancy,
        }
