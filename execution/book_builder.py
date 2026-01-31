"""
Book Builder Component - Maintains per-symbol order books from normalized market data

Subscribes to normalized events from FeedHandlers and maintains order books
for both simulation feed and execution feed consumption.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict

from data.market_data_schemas import DataType, Side
from execution.persistent_book import get_persistent_book_manager, PersistentOrderBook
from execution.simulator import get_execution_simulator, MarketData
from utils.logger import get_logger

logger = get_logger("execution.book_builder")


class BookEventType(Enum):
    """Book event types."""
    ADD_ORDER = "add_order"
    REMOVE_ORDER = "remove_order"
    EXECUTE_ORDER = "execute_order"
    UPDATE_ORDER = "update_order"
    SNAPSHOT = "snapshot"


@dataclass
class BookEvent:
    """Order book event."""
    timestamp: float
    symbol: str
    event_type: BookEventType
    side: str
    price: float
    quantity: int
    order_id: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class BookLevel:
    """Order book price level."""
    price: float
    quantity: int
    order_count: int
    orders: Dict[str, int]  # order_id -> quantity


class OrderBook:
    """In-memory order book for a single symbol."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: Dict[float, BookLevel] = {}  # price -> level
        self.asks: Dict[float, BookLevel] = {}  # price -> level
        self.orders: Dict[str, Dict[str, Any]] = {}  # order_id -> order info
        self.last_update = time.time()
        self.sequence_number = 0
    
    def get_best_bid(self) -> Optional[float]:
        """Get best bid price."""
        if not self.bids:
            return None
        return max(self.bids.keys())
    
    def get_best_ask(self) -> Optional[float]:
        """Get best ask price."""
        if not self.asks:
            return None
        return min(self.asks.keys())
    
    def get_spread(self) -> Optional[float]:
        """Get bid-ask spread."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask:
            return best_ask - best_bid
        return None
    
    def add_order(self, order_id: str, side: str, price: float, quantity: int) -> None:
        """Add an order to the book."""
        book = self.bids if side == "buy" else self.asks
        
        if price not in book:
            book[price] = BookLevel(price=price, quantity=0, order_count=0, orders={})
        
        level = book[price]
        level.quantity += quantity
        level.order_count += 1
        level.orders[order_id] = quantity
        
        self.orders[order_id] = {
            "price": price,
            "quantity": quantity,
            "side": side
        }
        
        self.last_update = time.time()
        self.sequence_number += 1
    
    def remove_order(self, order_id: str) -> None:
        """Remove an order from the book."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        price = order["price"]
        side = order["side"]
        quantity = order["quantity"]
        
        book = self.bids if side == "buy" else self.asks
        
        if price in book:
            level = book[price]
            level.quantity -= quantity
            level.order_count -= 1
            
            if order_id in level.orders:
                del level.orders[order_id]
            
            if level.quantity <= 0:
                del book[price]
        
        del self.orders[order_id]
        self.last_update = time.time()
        self.sequence_number += 1
    
    def execute_order(self, order_id: str, quantity: int) -> None:
        """Execute an order (partial or full fill)."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        price = order["price"]
        side = order["side"]
        
        book = self.bids if side == "buy" else self.asks
        
        if price in book:
            level = book[price]
            executed_quantity = min(quantity, level.quantity)
            
            level.quantity -= executed_quantity
            
            if order_id in level.orders:
                remaining = level.orders[order_id] - executed_quantity
                if remaining <= 0:
                    del level.orders[order_id]
                    level.order_count -= 1
                    del self.orders[order_id]
                else:
                    level.orders[order_id] = remaining
                    self.orders[order_id]["quantity"] = remaining
            
            if level.quantity <= 0:
                del book[price]
        
        self.last_update = time.time()
        self.sequence_number += 1
    
    def apply_snapshot(self, bids: List[Dict[str, Any]], asks: List[Dict[str, Any]]) -> None:
        """Apply a full book snapshot."""
        self.bids.clear()
        self.asks.clear()
        self.orders.clear()
        
        # Apply bids
        for bid in bids:
            price = bid["price"]
            quantity = bid["quantity"]
            self.bids[price] = BookLevel(
                price=price,
                quantity=quantity,
                order_count=1,
                orders={"snapshot": quantity}
            )
        
        # Apply asks
        for ask in asks:
            price = ask["price"]
            quantity = ask["quantity"]
            self.asks[price] = BookLevel(
                price=price,
                quantity=quantity,
                order_count=1,
                orders={"snapshot": quantity}
            )
        
        self.last_update = time.time()
        self.sequence_number += 1
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current book snapshot."""
        bids = sorted(self.bids.values(), key=lambda x: x.price, reverse=True)
        asks = sorted(self.asks.values(), key=lambda x: x.price)
        
        return {
            "symbol": self.symbol,
            "timestamp": self.last_update,
            "bids": [{"price": level.price, "quantity": level.quantity} for level in bids],
            "asks": [{"price": level.price, "quantity": level.quantity} for level in asks],
            "best_bid": self.get_best_bid(),
            "best_ask": self.get_best_ask(),
            "spread": self.get_spread(),
            "sequence_number": self.sequence_number
        }


class BookBuilder:
    """
    Book Builder component that maintains order books from normalized market data.
    
    Subscribes to FeedHandlers and builds books for both simulation and execution.
    """
    
    def __init__(self):
        self.books: Dict[str, OrderBook] = {}
        self.book_manager = get_persistent_book_manager()
        self.simulator = get_execution_simulator()
        
        # Subscriptions
        self._market_data_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._book_update_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []
        
        # Event processing
        self._event_queue = asyncio.Queue()
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("BookBuilder initialized")
    
    async def start(self) -> None:
        """Start the book builder."""
        if self._running:
            return
        
        self._running = True
        self._processing_task = asyncio.create_task(self._process_events())
        logger.info("BookBuilder started")
    
    async def stop(self) -> None:
        """Stop the book builder."""
        if not self._running:
            return
        
        self._running = False
        
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        
        logger.info("BookBuilder stopped")
    
    def subscribe_market_data(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe to market data updates."""
        self._market_data_callbacks.append(callback)
    
    def subscribe_book_updates(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Subscribe to book update notifications."""
        self._book_update_callbacks.append(callback)
    
    async def process_market_data(self, market_data: Dict[str, Any]) -> None:
        """Process incoming market data."""
        try:
            symbol = market_data.get("symbol")
            if not symbol:
                return
            
            data_type = market_data.get("data_type")
            
            # Get or create book
            if symbol not in self.books:
                self.books[symbol] = OrderBook(symbol)
            
            book = self.books[symbol]
            
            # Process based on data type
            if data_type in [DataType.MULTICAST_ITCH, DataType.FIX_SNAPSHOT, DataType.FIX_INCREMENTAL]:
                await self._process_order_book_update(book, market_data)
            elif data_type in [DataType.LOCAL_SIM_TICK, DataType.LOCAL_SIM_TRADE]:
                await self._process_trade_update(book, market_data)
            else:
                # Handle generic tick/trade data
                await self._process_generic_update(book, market_data)
            
            # Update persistent book
            persistent_book = self.book_manager.get_book(symbol)
            if data_type == DataType.MULTICAST_ITCH:
                await self._update_persistent_book(persistent_book, market_data)
            
            # Notify subscribers
            for callback in self._book_update_callbacks:
                try:
                    callback(symbol, book.get_snapshot())
                except Exception as e:
                    logger.error(f"Error in book update callback: {e}")
        
        except Exception as e:
            logger.error(f"Error processing market data: {e}")
    
    async def _process_order_book_update(self, book: OrderBook, market_data: Dict[str, Any]) -> None:
        """Process order book update from FIX/ITCH feeds."""
        data_type = market_data.get("data_type")
        
        if data_type == DataType.FIX_SNAPSHOT:
            # Apply full snapshot
            bids = market_data.get("bids", [])
            asks = market_data.get("asks", [])
            book.apply_snapshot(bids, asks)
        
        elif data_type == DataType.FIX_INCREMENTAL or data_type == DataType.MULTICAST_ITCH:
            # Apply incremental updates
            if "add_order" in market_data:
                self._add_order_from_data(book, market_data["add_order"])
            if "remove_order" in market_data:
                self._remove_order_from_data(book, market_data["remove_order"])
            if "execute_order" in market_data:
                self._execute_order_from_data(book, market_data["execute_order"])
    
    async def _process_trade_update(self, book: OrderBook, market_data: Dict[str, Any]) -> None:
        """Process trade update."""
        last_price = market_data.get("last_price")
        last_size = market_data.get("last_size")
        
        if last_price and last_size:
            # This would update trade history
            # For now, just log the trade
            logger.debug(f"Trade for {book.symbol}: {last_size} @ {last_price}")
    
    async def _process_generic_update(self, book: OrderBook, market_data: Dict[str, Any]) -> None:
        """Process generic market data update."""
        # Update best bid/ask if available
        bid_price = market_data.get("bid_price")
        ask_price = market_data.get("ask_price")
        
        if bid_price and ask_price:
            # This is a simple quote update
            # In a full implementation, you'd maintain the book properly
            logger.debug(f"Quote update for {book.symbol}: {bid_price}/{ask_price}")
    
    async def _update_persistent_book(self, persistent_book: PersistentOrderBook, market_data: Dict[str, Any]) -> None:
        """Update persistent order book."""
        data_type = market_data.get("data_type")
        
        if data_type == DataType.MULTICAST_ITCH:
            # Add order to persistent book
            order_id = f"order_{int(time.time() * 1000000)}"
            side = market_data.get("side", "buy")
            price = market_data.get("bid_price") or market_data.get("ask_price") or market_data.get("last_price", 0.0)
            quantity = int(market_data.get("bid_size") or market_data.get("ask_size") or market_data.get("last_size", 0))
            
            if price > 0 and quantity > 0:
                persistent_book.add_order(order_id, side, price, quantity)
    
    def _add_order_from_data(self, book: OrderBook, order_data: Dict[str, Any]) -> None:
        """Add order from market data."""
        order_id = order_data.get("order_id", f"order_{int(time.time() * 1000000)}")
        side = order_data.get("side", "buy")
        price = order_data.get("price", 0.0)
        quantity = order_data.get("quantity", 0)
        
        if price > 0 and quantity > 0:
            book.add_order(order_id, side, price, quantity)
    
    def _remove_order_from_data(self, book: OrderBook, order_data: Dict[str, Any]) -> None:
        """Remove order from market data."""
        order_id = order_data.get("order_id")
        if order_id:
            book.remove_order(order_id)
    
    def _execute_order_from_data(self, book: OrderBook, order_data: Dict[str, Any]) -> None:
        """Execute order from market data."""
        order_id = order_data.get("order_id")
        quantity = order_data.get("quantity", 0)
        
        if order_id and quantity > 0:
            book.execute_order(order_id, quantity)
    
    async def _process_events(self) -> None:
        """Process events from the queue."""
        while self._running:
            try:
                # Get market data from callbacks
                for callback in self._market_data_callbacks:
                    # This would be fed by FeedHandlers
                    pass
                
                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in event processing loop: {e}")
                await asyncio.sleep(0.1)
    
    def get_book(self, symbol: str) -> Optional[OrderBook]:
        """Get order book for symbol."""
        return self.books.get(symbol)
    
    def get_all_books(self) -> Dict[str, OrderBook]:
        """Get all order books."""
        return self.books.copy()
    
    def get_book_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get book snapshot for symbol."""
        book = self.books.get(symbol)
        return book.get_snapshot() if book else None
    
    def get_simulation_feed(self, symbol: str) -> Dict[str, Any]:
        """Get simulation feed for backtesting."""
        book = self.books.get(symbol)
        if not book:
            return {}
        
        snapshot = book.get_snapshot()
        
        # Convert to simulation format
        return {
            "symbol": symbol,
            "timestamp": snapshot["timestamp"],
            "data_type": DataType.LOCAL_SIM_TICK,
            "bid_price": snapshot["best_bid"],
            "ask_price": snapshot["best_ask"],
            "spread": snapshot["spread"],
            "sequence_number": snapshot["sequence_number"]
        }
    
    def get_execution_feed(self, symbol: str) -> Dict[str, Any]:
        """Get execution feed for matching engine."""
        book = self.books.get(symbol)
        if not book:
            return {}
        
        snapshot = book.get_snapshot()
        
        # Convert to execution format
        return {
            "symbol": symbol,
            "timestamp": snapshot["timestamp"],
            "data_type": DataType.LOCAL_SIM_ORDER_BOOK,
            "bids": snapshot["bids"],
            "asks": snapshot["asks"],
            "best_bid": snapshot["best_bid"],
            "best_ask": snapshot["best_ask"],
            "sequence_number": snapshot["sequence_number"]
        }


# Global book builder instance
_book_builder: Optional[BookBuilder] = None


def get_book_builder() -> BookBuilder:
    """Get the global book builder instance."""
    global _book_builder
    if _book_builder is None:
        _book_builder = BookBuilder()
    return _book_builder
