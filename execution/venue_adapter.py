"""
Venue Adapter Interface - Swappable broker/exchange connections

Provides a unified interface for MERID to connect to different execution venues:
- Self-hosted simulator for paper trading
- External brokers (Alpaca, Interactive Brokers)
- Crypto exchanges (Binance, Kraken)
- Direct exchange connectivity (FIX, WebSocket)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import threading
import asyncio
import time

from utils.logger import get_logger

logger = get_logger("execution.venue_adapter")


class VenueType(Enum):
    """Types of execution venues."""
    SIMULATOR = "simulator"
    BROKER = "broker"  # Alpaca, IB, etc.
    CRYPTO_EXCHANGE = "crypto_exchange"  # Binance, Kraken, etc.
    FIX = "fix"  # Direct FIX connectivity
    WEBSOCKET = "websocket"  # Direct WebSocket API


class OrderStatus(Enum):
    """Standard order status across all venues."""
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class VenueOrder:
    """Unified order representation across venues."""
    venue_order_id: str
    client_order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    order_type: str  # "market", "limit", "stop", "stop_limit"
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "GTC"
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
    venue_metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.updated_at == 0.0:
            self.updated_at = time.time()
        if self.venue_metadata is None:
            self.venue_metadata = {}


@dataclass
class VenuePosition:
    """Unified position representation."""
    symbol: str
    quantity: float
    avg_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    last_updated: float = 0.0

    def __post_init__(self):
        if self.last_updated == 0.0:
            self.last_updated = time.time()


@dataclass
class VenueAccount:
    """Unified account information."""
    account_id: str
    cash: float
    buying_power: float
    margin_used: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    positions: Dict[str, VenuePosition] = None
    last_updated: float = 0.0

    def __post_init__(self):
        if self.positions is None:
            self.positions = {}
        if self.last_updated == 0.0:
            self.last_updated = time.time()


@dataclass
class VenueConfig:
    """Configuration for a venue adapter."""
    venue_type: VenueType
    venue_name: str
    credentials: Dict[str, str] = None
    settings: Dict[str, Any] = None
    enabled: bool = True

    def __post_init__(self):
        if self.credentials is None:
            self.credentials = {}
        if self.settings is None:
            self.settings = {}


class VenueAdapter(ABC):
    """Abstract base class for all venue adapters."""
    
    def __init__(self, config: VenueConfig):
        self.config = config
        self.venue_type = config.venue_type
        self.venue_name = config.venue_name
        self._connected = False
        self._order_callbacks: List[Callable[[VenueOrder], None]] = []
        self._position_callbacks: List[Callable[[Dict[str, VenuePosition]], None]] = []
        self._account_callbacks: List[Callable[[VenueAccount], None]] = []
        
        logger.info(f"Initialized {self.venue_name} adapter ({self.venue_type.value})")
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to the venue."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the venue."""
        pass
    
    @abstractmethod
    async def submit_order(self, order: VenueOrder) -> VenueOrder:
        """Submit an order to the venue."""
        pass
    
    @abstractmethod
    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an order."""
        pass
    
    @abstractmethod
    async def get_orders(self, status: Optional[str] = None) -> List[VenueOrder]:
        """Get orders from the venue."""
        pass
    
    @abstractmethod
    async def get_positions(self) -> Dict[str, VenuePosition]:
        """Get current positions."""
        pass
    
    @abstractmethod
    async def get_account(self) -> VenueAccount:
        """Get account information."""
        pass
    
    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get symbol information (trading hours, min tick size, etc.)."""
        pass
    
    def is_connected(self) -> bool:
        """Check if connected to the venue."""
        return self._connected
    
    def subscribe_orders(self, callback: Callable[[VenueOrder], None]) -> None:
        """Subscribe to order updates."""
        self._order_callbacks.append(callback)
    
    def subscribe_positions(self, callback: Callable[[Dict[str, VenuePosition]], None]) -> None:
        """Subscribe to position updates."""
        self._position_callbacks.append(callback)
    
    def subscribe_account(self, callback: Callable[[VenueAccount], None]) -> None:
        """Subscribe to account updates."""
        self._account_callbacks.append(callback)
    
    def _notify_order_update(self, order: VenueOrder) -> None:
        """Notify subscribers of order update."""
        for callback in self._order_callbacks:
            try:
                callback(order)
            except (TypeError, ValueError, RuntimeError) as e:
                logger.error(f"Error in order callback: {e}")
    
    def _notify_position_update(self, positions: Dict[str, VenuePosition]) -> None:
        """Notify subscribers of position update."""
        for callback in self._position_callbacks:
            try:
                callback(positions)
            except (TypeError, ValueError, RuntimeError) as e:
                logger.error(f"Error in position callback: {e}")
    
    def _notify_account_update(self, account: VenueAccount) -> None:
        """Notify subscribers of account update."""
        for callback in self._account_callbacks:
            try:
                callback(account)
            except (TypeError, ValueError, RuntimeError) as e:
                logger.error(f"Error in account callback: {e}")


class VenueManager:
    """Manages multiple venue adapters and provides unified interface."""
    
    def __init__(self):
        self.adapters: Dict[str, VenueAdapter] = {}
        self.primary_venue: Optional[str] = None
        self._connected = False
        
        logger.info("VenueManager initialized")
    
    def add_adapter(self, venue_id: str, adapter: VenueAdapter, is_primary: bool = False) -> None:
        """Add a venue adapter."""
        self.adapters[venue_id] = adapter
        if is_primary or self.primary_venue is None:
            self.primary_venue = venue_id
        logger.info(f"Added venue adapter: {venue_id} ({adapter.venue_name})")
    
    def remove_adapter(self, venue_id: str) -> None:
        """Remove a venue adapter."""
        if venue_id in self.adapters:
            del self.adapters[venue_id]
            if self.primary_venue == venue_id:
                self.primary_venue = next(iter(self.adapters), None)
            logger.info(f"Removed venue adapter: {venue_id}")
    
    async def connect_all(self) -> None:
        """Connect all venue adapters."""
        tasks = []
        for venue_id, adapter in self.adapters.items():
            tasks.append(self._connect_adapter(venue_id, adapter))
        
        await asyncio.gather(*tasks, return_exceptions=True)
        self._connected = any(adapter.is_connected() for adapter in self.adapters.values())
        
        logger.info(f"Connected to {sum(1 for a in self.adapters.values() if a.is_connected())}/{len(self.adapters)} venues")
    
    async def disconnect_all(self) -> None:
        """Disconnect all venue adapters."""
        tasks = []
        for adapter in self.adapters.values():
            tasks.append(adapter.disconnect())
        
        await asyncio.gather(*tasks, return_exceptions=True)
        self._connected = False
        logger.info("Disconnected from all venues")
    
    async def _connect_adapter(self, venue_id: str, adapter: VenueAdapter) -> None:
        """Connect a single adapter with error handling."""
        try:
            await adapter.connect()
            logger.info(f"Connected to venue: {venue_id}")
        except (ConnectionError, RuntimeError) as e:
            logger.error(f"Failed to connect to venue {venue_id}: {e}")
    
    def get_adapter(self, venue_id: Optional[str] = None) -> Optional[VenueAdapter]:
        """Get a venue adapter by ID or primary if not specified."""
        if venue_id is None:
            venue_id = self.primary_venue
        
        return self.adapters.get(venue_id) if venue_id else None
    
    def list_venues(self) -> List[Dict[str, Any]]:
        """List all configured venues."""
        venues = []
        for venue_id, adapter in self.adapters.items():
            venues.append({
                "venue_id": venue_id,
                "venue_name": adapter.venue_name,
                "venue_type": adapter.venue_type.value,
                "connected": adapter.is_connected(),
                "is_primary": venue_id == self.primary_venue
            })
        return venues
    
    async def submit_order(self, order: VenueOrder, venue_id: Optional[str] = None) -> VenueOrder:
        """Submit order to specified venue or primary."""
        adapter = self.get_adapter(venue_id)
        if not adapter:
            raise ValueError(f"Venue not found: {venue_id}")
        
        if not adapter.is_connected():
            raise RuntimeError(f"Venue {venue_id or self.primary_venue} not connected")
        
        return await adapter.submit_order(order)
    
    async def cancel_order(self, venue_order_id: str, venue_id: Optional[str] = None) -> bool:
        """Cancel order on specified venue."""
        adapter = self.get_adapter(venue_id)
        if not adapter:
            raise ValueError(f"Venue not found: {venue_id}")
        
        return await adapter.cancel_order(venue_order_id)
    
    async def get_positions(self, venue_id: Optional[str] = None) -> Dict[str, VenuePosition]:
        """Get positions from specified venue."""
        adapter = self.get_adapter(venue_id)
        if not adapter:
            raise ValueError(f"Venue not found: {venue_id}")
        
        return await adapter.get_positions()
    
    async def get_account(self, venue_id: Optional[str] = None) -> VenueAccount:
        """Get account from specified venue."""
        adapter = self.get_adapter(venue_id)
        if not adapter:
            raise ValueError(f"Venue not found: {venue_id}")
        
        return await adapter.get_account()
    
    def is_connected(self) -> bool:
        """Check if any venue is connected."""
        return self._connected and any(adapter.is_connected() for adapter in self.adapters.values())


# Global venue manager instance
_venue_manager: Optional[VenueManager] = None
_venue_manager_lock = threading.Lock()


def get_venue_manager() -> VenueManager:
    """Get the global venue manager instance."""
    global _venue_manager
    if _venue_manager is None:
        with _venue_manager_lock:
            if _venue_manager is None:
                _venue_manager = VenueManager()
    return _venue_manager
