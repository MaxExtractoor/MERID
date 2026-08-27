"""Kalshi execution port — normalized boundary between strategy code and the venue.

The port is a narrow, exchange-agnostic async interface used by:

- `OrderRouter` to create/cancel orders and look up market state
- `FillsPoller` to poll fills and positions
- `kalshi_risk.reconcile_unified_risk_with_venue` to reconcile live exposure
- unit tests via `DeterministicKalshiClient` in the test tree

Why this exists:
- Production uses `KalshiVenueClient`, which is Kalshi-HTTP-specific.
- Tests need a deterministic, in-memory implementation that exercises the same
  production state transitions without respx or real network calls.
- By depending on the port, the production paths can run against either
  implementation without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class CreateOrderRequest:
    """Normalized order-creation request."""

    ticker: str
    side: str                      # "buy" or "sell"
    outcome: str                   # "yes" or "no"
    size: Decimal
    price_cents: Optional[int] = None  # None => market order
    order_type: str = "limit"      # "limit" or "market"
    time_in_force: str = "GTC"     # GTC, IOC, FOK, GTT
    expiration_ts: Optional[int] = None  # for GTT
    client_order_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    post_only: bool = False
    reduce_only: bool = False
    order_group_id: Optional[str] = None
    self_trade_prevention_type: Optional[str] = "taker_at_cross"
    source: Optional[str] = "agent_grid"
    take_profit_price_cents: Optional[int] = None
    stop_loss_price_cents: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    exchange_index: Optional[int] = None  # Kalshi exchange shard index


@dataclass
class CreateOrderResponse:
    """Result of a create-order call."""

    success: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    status: str = "pending"        # pending, resting, filled, partially_filled, canceled, rejected, unfilled
    filled_size: Decimal = Decimal("0")
    remaining_size: Optional[Decimal] = None
    price_cents: Optional[int] = None  # Limit price in cents (None for market orders)
    average_price_cents: Optional[int] = None
    error: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    """Normalized order snapshot returned by get_order / get_open_orders."""

    order_id: str
    client_order_id: Optional[str]
    ticker: str
    side: str
    outcome: str
    size: Decimal
    filled_size: Decimal
    remaining_size: Decimal
    price_cents: Optional[int]
    status: str                    # open/resting, filled, partially_filled, canceled, rejected, expired, unfilled
    time_in_force: str
    created_at: Optional[datetime] = None
    order_group_id: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CancelResult:
    success: bool
    order_id: str
    new_status: str = "canceled"
    error: Optional[str] = None


@dataclass
class Position:
    """Normalized position."""

    ticker: str
    outcome: str
    size: Decimal
    average_entry_price_cents: int
    realized_pnl_usd: Optional[Decimal] = None
    unrealized_pnl_usd: Optional[Decimal] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    exchange_index: Optional[int] = None  # Kalshi exchange shard index


@dataclass
class Fill:
    """Normalized fill."""

    fill_id: str
    order_id: str
    ticker: str
    side: str
    outcome: str
    size: Decimal
    price_cents: int
    client_order_id: Optional[str] = None
    trade_id: Optional[str] = None
    fee_usd: Optional[Decimal] = None
    timestamp: Optional[datetime] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    exchange_index: Optional[int] = None  # Kalshi exchange shard index


@dataclass
class PositionsResponse:
    positions: List[Position] = field(default_factory=list)
    cursor: Optional[str] = None


@dataclass
class FillsResponse:
    fills: List[Fill] = field(default_factory=list)
    cursor: Optional[str] = None


@dataclass
class HistoricalPositionsResponse:
    """Settled/closed positions not returned by live endpoints."""

    positions: List[Position] = field(default_factory=list)
    cursor: Optional[str] = None


@dataclass
class HistoricalFillsResponse:
    """Settled/closed fills not returned by live fill streams."""

    fills: List[Fill] = field(default_factory=list)
    cursor: Optional[str] = None


@dataclass
class MarketResult:
    """Result of a market query."""

    success: bool
    market: Optional[Any] = None   # domain EventMarket / dict
    error: Optional[str] = None


@dataclass
class BalanceResult:
    """Result of a balance query."""

    success: bool
    available_usd: Optional[Decimal] = None
    locked_usd: Optional[Decimal] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class OrderGroup:
    """Normalized order group."""

    group_id: str
    orders: List[Order]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderGroupsResult:
    """Result of an order-group query."""

    success: bool
    groups: List[OrderGroup] = field(default_factory=list)
    cursor: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class OrderbookLevel:
    """One side/level of an orderbook."""

    price_cents: int
    size: Decimal
    side: Optional[str] = None  # "yes" or "no"


@dataclass
class OrderbookResult:
    """Result of an orderbook snapshot query."""

    success: bool
    yes_levels: List[OrderbookLevel] = field(default_factory=list)
    no_levels: List[OrderbookLevel] = field(default_factory=list)
    timestamp: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class KalshiExecutionPort(Protocol):
    """Async port used by all Kalshi trading paths."""

    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResponse: ...
    async def get_order(self, order_id: Optional[str] = None, client_order_id: Optional[str] = None, market_id: Optional[str] = None) -> Optional[Order]: ...
    async def cancel_order(self, order_id: str) -> CancelResult: ...

    async def get_open_orders(self, ticker: Optional[str] = None) -> List[Order]: ...

    async def get_positions(self) -> PositionsResponse: ...
    async def get_historical_positions(self, cursor: Optional[str] = None) -> HistoricalPositionsResponse: ...

    async def get_fills(self, cursor: Optional[str] = None, since_ts: Optional[int] = None, limit: int = 200, market_id: Optional[str] = None, order_id: Optional[str] = None) -> FillsResponse: ...
    async def get_historical_fills(self, cursor: Optional[str] = None, since_ts: Optional[int] = None, limit: int = 200) -> HistoricalFillsResponse: ...

    async def get_market(self, ticker: str) -> MarketResult: ...
    async def get_orderbook(self, ticker: str) -> OrderbookResult: ...

    async def get_balance(self) -> BalanceResult: ...
    async def get_order_groups(self, limit: int = 200) -> OrderGroupsResult: ...

    @property
    def is_circuit_open(self) -> bool: ...


# ── Singleton ──

_port: Optional[KalshiExecutionPort] = None
_port_lock = __import__("threading").Lock()


def set_kalshi_execution_port(port: KalshiExecutionPort) -> None:
    """Override the port for tests or for dependency injection."""
    global _port
    with _port_lock:
        _port = port


def get_kalshi_execution_port() -> KalshiExecutionPort:
    """Return the process-wide port, lazily wrapping the KalshiVenueClient.

    Tests can call `set_kalshi_execution_port(...)` with a simulator before
    this is first invoked.
    """
    global _port
    with _port_lock:
        if _port is None:
            from merid.event_venues.kalshi.venue_client_port import KalshiVenueClientExecutionPort
            _port = KalshiVenueClientExecutionPort()
        return _port


def reset_kalshi_execution_port_for_testing() -> None:
    """Clear the global port.  Used by test fixtures."""
    global _port
    with _port_lock:
        _port = None
