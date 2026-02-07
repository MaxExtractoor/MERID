"""MERID Venue Adapter Interface.

Abstract base class for all trading venue adapters.
Provides unified interface for US-compliant venues.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum


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
    
    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Place order."""
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
