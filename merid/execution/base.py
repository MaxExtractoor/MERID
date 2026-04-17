"""Core execution abstractions for MERID's unified trading layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

TradeSideLiteral = Literal["buy", "sell"]


@dataclass(slots=True)
class Quote:
    """Lightweight venue-agnostic quote representation."""

    symbol: str
    side: TradeSideLiteral
    price: float
    venue: str
    size: float
    latency_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Position:
    """Normalized position view returned by venue adapters."""

    symbol: str
    size: float
    entry_price: float
    pnl: float
    venue: str
    leverage: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradeResult:
    """Standardized result returned by execution adapters."""

    success: bool
    venue: str
    symbol: str
    side: TradeSideLiteral
    size: float
    price: float
    tx_id: Optional[str] = None
    error: Optional[str] = None
    explanation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class TradeExecutor(ABC):
    """Abstract adapter interface for every MERID venue."""

    venue: str

    @abstractmethod
    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:  # pragma: no cover - interface
        """Return a price quote for the requested side/amount."""

    @abstractmethod
    async def execute_trade(
        self,
        symbol: str,
        side: TradeSideLiteral,
        amount: float,
        *,
        order_type: str = "market",
        price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeResult:  # pragma: no cover - interface
        """Submit an order and return a normalized result."""

    @abstractmethod
    async def get_positions(self) -> List[Position]:  # pragma: no cover - interface
        """Fetch open positions at the venue."""
