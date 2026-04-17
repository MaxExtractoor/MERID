"""
UDP Multicast Market Data Feed Handler

Consumes exchange multicast feeds (ITCH/SoupBIN, etc.) for ultra-low latency market data.
Provides normalized market data to the execution simulator.
"""

from __future__ import annotations

import socket
import struct
import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import threading
from collections import deque
import select

from execution.simulator import get_execution_simulator, MarketData
from utils.logger import get_logger

logger = get_logger("execution.multicast_feed")


class MulticastFeedType(Enum):
    """Types of multicast market data feeds."""
    ITCH = "itch"
    SOUPBIN = "soupbin"
    OPRA = "opra"
    CUSTOM = "custom"


@dataclass
class MulticastConfig:
    """Configuration for a multicast feed."""
    feed_type: MulticastFeedType
    multicast_group: str
    port: int
    interface: str
    buffer_size: int = 65536
    timeout: float = 1.0
    symbols: List[str] = None
    
    def __post_init__(self):
        if self.symbols is None:
            self.symbols = []


@dataclass
class ITCHMessage:
    """ITCH message header."""
    message_type: int
    stock_locate: int
    tracking_number: int
    timestamp: int
    payload: bytes


@dataclass
class ITCHAddOrder:
    """ITCH Add Order message."""
    order_reference_number: int
    buy_sell_indicator: str
    shares: int
    stock_symbol: str
    price: int
    order_reference_number: int


@dataclass
class ITCHOrderExecuted:
    """ITCH Order Executed message."""
    order_reference_number: int
    shares: int
    stock_symbol: str
    price: int
    match_id: int


class MulticastFeedHandler:
    """Handles UDP multicast market data feeds."""
    
    def __init__(self, config: MulticastConfig):
        self.config = config
        self.socket = None
        self._running = False
        self._callbacks: List[Callable[[MarketData], None]] = []
        self._message_queue = deque(maxlen=10000)
        self._sequence_numbers: Dict[str, int] = {}
        
        # ITCH-specific state
        self._order_books: Dict[str, Dict[str, Any]] = {}  # symbol -> {price: quantity}
        
        logger.info(f"Initialized {config.feed_type.value} multicast feed handler")
    
    async def start(self) -> None:
        """Start the multicast feed handler."""
        if self._running:
            return
        
        try:
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Bind to the multicast address and port
            self.socket.bind((self.config.multicast_group, self.config.port))
            
            # Join multicast group
            group = socket.inet_aton(self.config.multicast_group)
            mreq = struct.pack('4sl', group, socket.inet_aton(self.config.interface))
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            # Set socket options for low latency
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.config.buffer_size)
            
            self._running = True
            logger.info(f"Joined multicast group {self.config.multicast_group}:{self.config.port} on {self.config.interface}")
            
            # Start processing loop
            await self._process_messages()
            
        except (socket.error, IOError, OSError) as e:
            logger.error(f"Failed to start multicast feed: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the multicast feed handler."""
        if not self._running:
            return
        
        self._running = False
        
        if self.socket:
            try:
                # Leave multicast group
                group = socket.inet_aton(self.config.multicast_group)
                mreq = struct.pack('4sl', group, socket.inet_aton(self.config.interface))
                self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                self.socket.close()
            except (socket.error, OSError):
                pass
        
        logger.info(f"Stopped multicast feed: {self.config.feed_type.value}")
    
    def subscribe(self, callback: Callable[[MarketData], None]) -> None:
        """Subscribe to market data updates."""
        self._callbacks.append(callback)
    
    async def _process_messages(self) -> None:
        """Process incoming multicast messages."""
        while self._running:
            try:
                # Use select for timeout handling
                ready = select.select([self.socket], [], [], self.config.timeout)
                if not ready[0]:
                    continue
                
                # Receive message
                data, addr = self.socket.recvfrom(self.config.buffer_size)
                
                # Parse based on feed type
                if self.config.feed_type == MulticastFeedType.ITCH:
                    await self._parse_itch_message(data)
                elif self.config.feed_type == MulticastFeedType.SOUPBIN:
                    await self._parse_soupbin_message(data)
                else:
                    logger.warning(f"Unsupported feed type: {self.config.feed_type}")
                
            except socket.timeout:
                continue
            except (socket.error, RuntimeError, ValueError) as e:
                logger.error(f"Error processing multicast message: {e}")
                if self._running:
                    await asyncio.sleep(0.1)
    
    async def _parse_itch_message(self, data: bytes) -> None:
        """Parse ITCH protocol messages."""
        if len(data) < 4:
            return
        
        # Parse ITCH header
        message_type, stock_locate, tracking_number, timestamp = struct.unpack('>HHII', data[:8])
        payload = data[8:]
        
        # Track sequence numbers
        key = f"{stock_locate}"
        if key not in self._sequence_numbers:
            self._sequence_numbers[key] = 0
        expected_seq = self._sequence_numbers[key] + 1
        self._sequence_numbers[key] = tracking_number
        
        if tracking_number != expected_seq:
            logger.warning(f"Sequence number gap for {key}: expected {expected_seq}, got {tracking_number}")
        
        # Process message types
        if message_type == 0x21:  # Add Order
            await self._process_itch_add_order(payload)
        elif message_type == 0x22:  # Order Executed
            await self._process_itch_order_executed(payload)
        elif message_type == 0x24:  # Order Cancel
            await self._process_itch_order_cancel(payload)
        elif message_type == 0x27:  # Trade
            await self._process_itch_trade(payload)
        # Add more message types as needed
    
    async def _process_itch_add_order(self, payload: bytes) -> None:
        """Process ITCH Add Order message."""
        if len(payload) < 12:
            return
        
        # Parse Add Order message
        order_ref, side, shares, symbol, price = struct.unpack('>QcI6sI', payload[:20])
        
        # Convert to standard format
        symbol_str = symbol.strip().decode('ascii')
        price_float = price / 10000.0  # ITCH prices are in 4-decimal precision
        side_str = 'B' if side == 'B' else 'S'
        
        # Update order book
        if symbol_str not in self._order_books:
            self._order_books[symbol_str] = {}
        
        self._order_books[symbol_str][price_float] = shares
        
        # Publish market data
        market_data = MarketData(
            symbol=symbol_str,
            timestamp=time.time(),
            bid_price=price_float if side_str == 'B' else None,
            ask_price=price_float if side_str == 'S' else None,
            bid_size=shares if side_str == 'B' else None,
            ask_size=shares if side_str == 'S' else None
        )
        
        self._publish_market_data(market_data)
    
    async def _process_itch_order_executed(self, payload: bytes) -> None:
        """Process ITCH Order Executed message."""
        if len(payload) < 20:
            return
        
        # Parse Order Executed message
        order_ref, shares, symbol, price, match_id = struct.unpack('>QI6sIQ', payload[:20])
        
        symbol_str = symbol.strip().decode('ascii')
        price_float = price / 10000.0
        
        # Update order book (reduce quantity at price level)
        if symbol_str in self._order_books:
            book = self._order_books[symbol_str]
            if price_float in book:
                book[price_float] = max(0, book[price_float] - shares)
                if book[price_float] == 0:
                    del book[price_float]
        
        # Publish trade data
        market_data = MarketData(
            symbol=symbol_str,
            timestamp=time.time(),
            last_price=price_float,
            last_size=shares
        )
        
        self._publish_market_data(market_data)
    
    async def _process_itch_order_cancel(self, payload: bytes) -> None:
        """Process ITCH Order Cancel message."""
        if len(payload) < 8:
            return
        
        # Parse Order Cancel message
        order_ref, shares, symbol = struct.unpack('>QI6s', payload[:12])
        
        symbol_str = symbol.strip().decode('ascii')
        
        # Remove from order book
        if symbol_str in self._order_books:
            # For simplicity, we'll clear the book and rebuild
            # In production, you'd remove specific orders
            pass
    
    async def _process_itch_trade(self, payload: bytes) -> None:
        """Process ITCH Trade message."""
        if len(payload) < 20:
            return
        
        # Parse Trade message
        order_ref, shares, symbol, price, match_id = struct.unpack('>QI6sIQ', payload[:20])
        
        symbol_str = symbol.strip().decode('ascii')
        price_float = price / 10000.0
        
        # Publish trade data
        market_data = MarketData(
            symbol=symbol_str,
            timestamp=time.time(),
            last_price=price_float,
            last_size=shares
        )
        
        self._publish_market_data(market_data)
    
    async def _parse_soupbin_message(self, data: bytes) -> None:
        """Parse SOUPBIN protocol messages."""
        # SOUPBIN implementation would go here
        # For now, just log that we received data
        logger.debug(f"Received SOUPBIN message: {len(data)} bytes")
    
    def _publish_market_data(self, market_data: MarketData) -> None:
        """Publish market data to subscribers and simulator."""
        # Send to simulator
        simulator = get_execution_simulator()
        simulator.update_market_data(market_data)
        
        # Send to subscribers
        for callback in self._callbacks:
            try:
                callback(market_data)
            except (TypeError, ValueError, RuntimeError) as e:
                logger.error(f"Error in market data callback: {e}")
    
    def get_order_book(self, symbol: str) -> Dict[str, float]:
        """Get current order book for a symbol."""
        return self._order_books.get(symbol, {})


class MulticastFeedManager:
    """Manages multiple multicast feeds."""
    
    def __init__(self):
        self.feeds: Dict[str, MulticastFeedHandler] = {}
        self._running = False
        
        logger.info("MulticastFeedManager initialized")
    
    def add_feed(self, feed_id: str, config: MulticastConfig) -> None:
        """Add a multicast feed."""
        feed = MulticastFeedHandler(config)
        self.feeds[feed_id] = feed
        logger.info(f"Added multicast feed: {feed_id} ({config.feed_type.value})")
    
    def remove_feed(self, feed_id: str) -> None:
        """Remove a multicast feed."""
        if feed_id in self.feeds:
            del self.feeds[feed_id]
            logger.info(f"Removed multicast feed: {feed_id}")
    
    async def start_all(self) -> None:
        """Start all multicast feeds."""
        if self._running:
            return
        
        self._running = True
        
        tasks = []
        for feed_id, feed in self.feeds.items():
            task = asyncio.create_task(feed.start())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Started {len(self.feeds)} multicast feeds")
    
    async def stop_all(self) -> None:
        """Stop all multicast feeds."""
        if not self._running:
            return
        
        self._running = False
        
        tasks = []
        for feed in self.feeds.values():
            task = asyncio.create_task(feed.stop())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Stopped all multicast feeds")
    
    def subscribe(self, feed_id: str, callback: Callable[[MarketData], None]) -> None:
        """Subscribe to a specific feed."""
        if feed_id in self.feeds:
            self.feeds[feed_id].subscribe(callback)
    
    def get_order_book(self, feed_id: str, symbol: str) -> Dict[str, float]:
        """Get order book from a specific feed."""
        if feed_id in self.feeds:
            return self.feeds[feed_id].get_order_book(symbol)
        return {}


# Global multicast feed manager instance
_multicast_manager: Optional[MulticastFeedManager] = None
_multicast_manager_lock = threading.Lock()


def get_multicast_feed_manager() -> MulticastFeedManager:
    """Get the global multicast feed manager instance."""
    global _multicast_manager
    if _multicast_manager is None:
        with _multicast_manager_lock:
            if _multicast_manager is None:
                _multicast_manager = MulticastFeedManager()
    return _multicast_manager


# Utility functions for creating common feed configurations
def create_itch_config(multicast_group: str, port: int, interface: str = "eth0", symbols: List[str] = None) -> MulticastConfig:
    """Create ITCH multicast feed configuration."""
    return MulticastConfig(
        feed_type=MulticastFeedType.ITCH,
        multicast_group=multicast_group,
        port=port,
        interface=interface,
        symbols=symbols or []
    )


def create_soupbin_config(multicast_group: str, port: int, interface: str = "eth0", symbols: List[str] = None) -> MulticastConfig:
    """Create SOUPBIN multicast feed configuration."""
    return MulticastConfig(
        feed_type=MulticastFeedType.SOUPBIN,
        multicast_group=multicast_group,
        port=port,
        interface=interface,
        symbols=symbols or []
    )


def create_custom_config(multicast_group: str, port: int, interface: str = "eth0", symbols: List[str] = None) -> MulticastConfig:
    """Create custom multicast feed configuration."""
    return MulticastConfig(
        feed_type=MulticastFeedType.CUSTOM,
        multicast_group=multicast_group,
        port=port,
        interface=interface,
        symbols=symbols or []
    )
