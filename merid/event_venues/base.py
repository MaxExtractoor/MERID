"""
MERID Event Venue Client Interface

Shared protocol for prediction market venues (Polymarket, Kalshi, etc.)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol, Union


# ============================================================================
# Shared Data Models (Venue-agnostic)
# ============================================================================

@dataclass
class EventOutcome:
    """Represents an outcome for an event market."""
    outcome_id: str
    outcome_name: str
    price: Decimal
    probability: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None
    best_bid: Optional[Decimal] = None


@dataclass
class EventMarket:
    """Represents an event/prediction market (venue-agnostic)."""
    market_id: str
    venue: str  # "polymarket", "kalshi", etc.
    question: str
    description: str
    outcomes: List[EventOutcome]
    category: Optional[str] = None
    tags: List[str] = None
    end_date: Optional[datetime] = None
    active: bool = True
    volume: Optional[Decimal] = None
    open_interest: Optional[Decimal] = None
    liquidity: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    resolved: bool = False
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    raw_data: Optional[Dict[str, Any]] = None  # Venue-specific raw data
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class VenueOrder:
    """Normalized order for any event venue."""
    market_id: str
    side: str  # "buy" or "sell"
    size: Decimal
    price: Optional[Decimal] = None  # None for market orders
    order_type: str = "limit"  # "limit" or "market"
    outcome_id: Optional[str] = None  # For multi-outcome markets
    client_order_id: Optional[str] = None
    time_in_force: str = "GTC"  # GTC, IOC, FOK


@dataclass
class PlacedOrder:
    """Order that has been placed on a venue."""
    order_id: str
    market_id: str
    side: str
    size: Decimal
    price: Optional[Decimal]
    filled_size: Decimal = Decimal("0")
    remaining_size: Optional[Decimal] = None
    status: str = "pending"  # pending, filled, partially_filled, cancelled, rejected
    venue: str = ""
    created_at: Optional[datetime] = None
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class VenuePosition:
    """Position in an event market."""
    market_id: str
    outcome_id: Optional[str]
    size: Decimal
    average_entry_price: Decimal
    unrealized_pnl: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    venue: str = ""
    created_at: Optional[datetime] = None


@dataclass
class VenueTrade:
    """Trade execution on an event venue."""
    trade_id: str
    market_id: str
    order_id: str
    side: str
    size: Decimal
    price: Decimal
    fee: Decimal
    timestamp: datetime
    venue: str = ""


@dataclass
class VenueOrderBook:
    """Order book for an event market."""
    market_id: str
    outcome_id: Optional[str]
    bids: List[tuple[Decimal, Decimal]]  # (price, size)
    asks: List[tuple[Decimal, Decimal]]  # (price, size)
    timestamp: datetime
    venue: str = ""


@dataclass
class MarketFilter:
    """Filter for listing markets."""
    active_only: bool = True
    category: Optional[str] = None
    search: Optional[str] = None
    limit: int = 100
    offset: int = 0
    min_volume: Optional[Decimal] = None
    tags: Optional[List[str]] = None


@dataclass
class QuoteEvent:
    """Real-time quote update from venue WebSocket."""
    market_id: str
    outcome_id: Optional[str]
    bid_price: Optional[Decimal]
    ask_price: Optional[Decimal]
    last_price: Optional[Decimal]
    volume: Optional[Decimal]
    timestamp: datetime
    venue: str = ""
    raw_data: Optional[Dict[str, Any]] = None


# ============================================================================
# EventVenueClient Interface (Protocol)
# ============================================================================

class EventVenueClient(ABC):
    """
    Abstract base class for event market venue clients.
    
    Implementations: PolymarketClient, KalshiClient
    """
    
    @property
    @abstractmethod
    def venue_name(self) -> str:
        """Return the venue identifier (e.g., 'polymarket', 'kalshi')."""
        pass
    
    @abstractmethod
    async def connect(self) -> None:
        """Initialize connections, authenticate if needed."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close all connections and cleanup."""
        pass
    
    # ------------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------------
    
    @abstractmethod
    async def list_markets(self, filter_params: Optional[MarketFilter] = None) -> List[EventMarket]:
        """List available markets matching the filter."""
        pass
    
    @abstractmethod
    async def get_market(self, market_id: str) -> Optional[EventMarket]:
        """Get detailed information about a specific market."""
        pass
    
    @abstractmethod
    async def get_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> Optional[VenueOrderBook]:
        """Get order book for a market."""
        pass
    
    # ------------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------------
    
    @abstractmethod
    async def place_order(self, order: VenueOrder) -> Optional[PlacedOrder]:
        """Place an order on the venue."""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> bool:
        """Cancel an order."""
        pass
    
    @abstractmethod
    async def get_order(self, order_id: str, market_id: Optional[str] = None) -> Optional[PlacedOrder]:
        """Get order status."""
        pass
    
    @abstractmethod
    async def get_open_orders(self, market_id: Optional[str] = None) -> List[PlacedOrder]:
        """Get all open orders."""
        pass
    
    # ------------------------------------------------------------------------
    # Account Data
    # ------------------------------------------------------------------------
    
    @abstractmethod
    async def get_positions(self) -> List[VenuePosition]:
        """Get all positions."""
        pass
    
    @abstractmethod
    async def get_trades(self, limit: int = 100) -> List[VenueTrade]:
        """Get recent trades."""
        pass
    
    @abstractmethod
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance by currency/token."""
        pass


# ============================================================================
# Streaming Interface
# ============================================================================

class EventVenueStream(ABC):
    """
    Abstract base class for venue WebSocket streaming.
    """
    
    @property
    @abstractmethod
    def venue_name(self) -> str:
        """Return the venue identifier."""
        pass
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to WebSocket stream."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close WebSocket connection."""
        pass
    
    @abstractmethod
    async def subscribe_quotes(self, market_ids: List[str]) -> None:
        """Subscribe to real-time quote updates for markets."""
        pass
    
    @abstractmethod
    async def subscribe_trades(self, market_ids: Optional[List[str]] = None) -> None:
        """Subscribe to trade updates (all or specific markets)."""
        pass
    
    @abstractmethod
    async def subscribe_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> None:
        """Subscribe to order book updates."""
        pass
    
    @abstractmethod
    async def listen(self, callback: callable) -> None:
        """
        Listen for events and call callback with QuoteEvent, VenueTrade, etc.
        
        Args:
            callback: async function receiving events
        """
        pass


# ============================================================================
# Factory and Utilities
# ============================================================================

class VenueClientFactory:
    """Factory for creating venue clients."""
    
    _registry: Dict[str, type] = {}
    
    @classmethod
    def register(cls, venue: str, client_class: type):
        """Register a venue client implementation."""
        cls._registry[venue] = client_class
    
    @classmethod
    def create(cls, venue: str, **kwargs) -> EventVenueClient:
        """Create a venue client instance."""
        if venue not in cls._registry:
            raise ValueError(f"Unknown venue: {venue}. Available: {list(cls._registry.keys())}")
        return cls._registry[venue](**kwargs)
    
    @classmethod
    def available_venues(cls) -> List[str]:
        """List available venue names."""
        return list(cls._registry.keys())


# Convenience type
AnyEventVenue = Union[EventVenueClient, EventVenueStream]
