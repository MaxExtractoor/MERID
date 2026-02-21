"""MERID Venue Adapter Interface.

Abstract base class for all trading venue adapters.
Provides unified interface for US-compliant venues.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum
import logging

_va_logger = logging.getLogger(__name__)


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass
class Order:
    """Unified order representation."""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: Decimal
    price: Optional[Decimal]
    filled: Decimal
    remaining: Decimal
    status: str
    venue: str
    timestamp: datetime


@dataclass
class Position:
    """Unified position representation."""
    symbol: str
    side: str
    size: Decimal
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    venue: str
    timestamp: datetime


@dataclass
class MarketData:
    """Unified market data."""
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h: Decimal
    high_24h: Decimal
    low_24h: Decimal
    timestamp: datetime
    venue: str


class VenueAdapter(ABC):
    """Abstract base class for venue adapters."""

    # Subclasses that return hardcoded/mock data should set _is_stub = True.
    # This prevents accidental live execution through stub adapters.
    _is_stub: bool = False
    
    def __init__(self, venue_id: str, paper: bool = True):
        self.venue_id = venue_id
        self.paper = paper
        self.connected = False
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to venue."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """Disconnect from venue."""
        pass
    
    @abstractmethod
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data for symbol."""
        pass
    
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Place order. Raises NotImplementedError if this is a stub adapter in live mode."""
        if self._is_stub and not self.paper:
            raise NotImplementedError(
                f"Live trading not implemented for stub adapter '{self.venue_id}'. "
                f"Wire a real venue API or use paper mode."
            )
        return await self._place_order_impl(symbol, side, order_type, amount, price)

    @abstractmethod
    async def _place_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Implement order placement. Called by place_order after stub guard."""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel order."""
        pass
    
    @abstractmethod
    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status."""
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders."""
        pass
    
    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Get positions."""
        pass
    
    @abstractmethod
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance."""
        pass
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.connected

    async def get_market_data_validated(
        self, symbol: str
    ) -> Tuple[Optional["MarketData"], Optional[Dict[str, Any]]]:
        """Get market data with DataContractRegistry validation.

        Returns:
            (market_data, validation_result_dict) — validation_result_dict is
            None if no contract is registered for this venue.
        """
        md = await self.get_market_data(symbol)
        if md is None:
            return None, None

        try:
            from core.data_contracts import get_data_contract_registry
            registry = get_data_contract_registry()
            data_dict = {
                "price": float(md.last),
                "volume": float(md.volume_24h),
                "timestamp": md.timestamp.timestamp() if hasattr(md.timestamp, 'timestamp') else float(md.timestamp),
                "symbol": md.symbol,
            }
            result = registry.validate(self.venue_id, data_dict)
            if not result.valid:
                _va_logger.warning(
                    "Data contract violation for %s/%s: %s",
                    self.venue_id, symbol, result.errors,
                )
            return md, result.to_dict()
        except ImportError:
            return md, None
        except Exception as exc:
            _va_logger.debug("Data contract validation error: %s", exc)
            return md, None
