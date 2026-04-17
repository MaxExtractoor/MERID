"""
Persistent Order Book with Journaling and Snapshots

Provides durable order book storage with recovery capabilities.
Implements LMAX-style architecture with in-memory book + disk journal + periodic snapshots.
"""

from __future__ import annotations

import asyncio
import json
import time
import os
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import threading
import ormsgpack
from pathlib import Path
import sqlite3
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("execution.persistent_book")


class BookEventType(Enum):
    """Order book event types."""
    ADD_ORDER = 'add_order'
    REMOVE_ORDER = 'remove_order'
    EXECUTE_ORDER = 'execute_order'
    CANCEL_ORDER = 'cancel_order'
    UPDATE_ORDER = 'update_order'


@dataclass
class BookEvent:
    """Order book event for journaling."""
    timestamp: float
    event_type: BookEventType
    symbol: str
    order_id: str
    side: str  # 'buy' or 'sell'
    price: float
    quantity: int
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class OrderBookLevel:
    """Order book price level."""
    price: float
    quantity: int
    order_count: int
    orders: Dict[str, int]  # order_id -> quantity


@dataclass
class OrderBookSnapshot:
    """Order book snapshot."""
    timestamp: float
    symbol: str
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    last_trade_price: Optional[float] = None
    last_trade_size: Optional[int] = None
    sequence_number: int = 0


class PersistentOrderBook:
    """Order book with persistence and recovery capabilities."""
    
    def __init__(self, symbol: str, data_dir: str = "data/order_books"):
        self.symbol = symbol
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory order book
        self.bids: Dict[float, OrderBookLevel] = {}  # price -> level
        self.asks: Dict[float, OrderBookLevel] = {}  # price -> level
        self.orders: Dict[str, Dict[str, Any]] = {}  # order_id -> order info
        
        # Persistence
        self.journal_file = self.data_dir / f"{symbol}_journal.pkl"
        self.snapshot_file = self.data_dir / f"{symbol}_snapshot.pkl"
        self.db_file = self.data_dir / f"{symbol}.db"
        
        # Journaling
        self._journal: List[BookEvent] = []
        self._journal_lock = threading.Lock()
        self._sequence_number = 0
        
        # Snapshot settings
        self._snapshot_interval = 60.0  # seconds
        self._snapshot_event_count = 1000
        self._last_snapshot_time = time.time()
        self._last_snapshot_count = 0
        
        # Background tasks
        self._snapshot_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Initialize database
        self._init_database()
        
        # Load from disk
        self._load_from_disk()
        
        logger.info(f"Initialized persistent order book for {symbol}")
    
    def _init_database(self) -> None:
        """Initialize SQLite database for query support."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # Create tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                event_type TEXT,
                symbol TEXT,
                order_id TEXT,
                side TEXT,
                price REAL,
                quantity INTEGER,
                metadata TEXT,
                sequence_number INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                symbol TEXT,
                snapshot_data TEXT,
                sequence_number INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_events_symbol ON events(symbol)
        ''')
        
        conn.commit()
        conn.close()
    
    def _load_from_disk(self) -> None:
        """Load order book from latest snapshot and replay journal."""
        try:
            # Load latest snapshot
            if self.snapshot_file.exists():
                with open(self.snapshot_file, 'rb') as f:
                    snapshot = pickle.load(f)
                    self._restore_snapshot(snapshot)
                    self._sequence_number = snapshot.sequence_number
                    logger.info(f"Loaded snapshot for {self.symbol} at seq {self._sequence_number}")
            
            # Replay journal events
            if self.journal_file.exists():
                with open(self.journal_file, 'rb') as f:
                    journal = pickle.load(f)
                    
                # Replay events after snapshot
                for event in journal:
                    if event.sequence_number > self._sequence_number:
                        self._apply_event(event)
                        self._sequence_number = event.sequence_number
                
                logger.info(f"Replayed {len(journal)} journal events for {self.symbol}")
        
        except (IOError, OSError, pickle.PickleError, ValueError) as e:
            logger.error(f"Error loading order book from disk: {e}")
            # Start with empty book
            self._clear_book()
    
    def _restore_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """Restore order book from snapshot."""
        self._clear_book()
        
        # Restore bids
        for level in snapshot.bids:
            self.bids[level.price] = level
        
        # Restore asks
        for level in snapshot.asks:
            self.asks[level.price] = level
        
        # Restore orders
        for level in snapshot.bids + snapshot.asks:
            for order_id, quantity in level.orders.items():
                self.orders[order_id] = {
                    'price': level.price,
                    'quantity': quantity,
                    'side': 'buy' if level.price in self.bids else 'sell'
                }
    
    def _clear_book(self) -> None:
        """Clear the order book."""
        self.bids.clear()
        self.asks.clear()
        self.orders.clear()
    
    def start(self) -> None:
        """Start background snapshot task."""
        if self._running:
            return
        
        self._running = True
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        logger.info(f"Started persistent order book for {self.symbol}")
    
    def stop(self) -> None:
        """Stop background tasks and save final state."""
        if not self._running:
            return
        
        self._running = False
        
        if self._snapshot_task:
            self._snapshot_task.cancel()
        
        # Save final snapshot
        self._save_snapshot()
        logger.info(f"Stopped persistent order book for {self.symbol}")
    
    async def _snapshot_loop(self) -> None:
        """Background task to periodically save snapshots."""
        while self._running:
            try:
                await asyncio.sleep(self._snapshot_interval)
                
                current_time = time.time()
                event_count = len(self._journal)
                
                # Check if snapshot is needed
                time_diff = current_time - self._last_snapshot_time
                count_diff = event_count - self._last_snapshot_count
                
                if time_diff >= self._snapshot_interval or count_diff >= self._snapshot_event_count:
                    self._save_snapshot()
                    self._last_snapshot_time = current_time
                    self._last_snapshot_count = event_count
            
            except asyncio.CancelledError:
                break
            except (IOError, OSError, RuntimeError) as e:
                logger.error(f"Error in snapshot loop: {e}")
                await asyncio.sleep(1)
    
    def _save_snapshot(self) -> None:
        """Save current order book snapshot."""
        try:
            # Create snapshot
            bids = sorted(self.bids.values(), key=lambda x: x.price, reverse=True)
            asks = sorted(self.asks.values(), key=lambda x: x.price)
            
            snapshot = OrderBookSnapshot(
                timestamp=time.time(),
                symbol=self.symbol,
                bids=bids,
                asks=asks,
                sequence_number=self._sequence_number
            )
            
            # Save to file
            with open(self.snapshot_file, 'wb') as f:
                pickle.dump(snapshot, f)
            
            # Save to database
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO snapshots (timestamp, symbol, snapshot_data, sequence_number)
                VALUES (?, ?, ?, ?)
            ''', (snapshot.timestamp, snapshot.symbol, json.dumps(asdict(snapshot)), snapshot.sequence_number))
            conn.commit()
            conn.close()
            
            # Trim journal (keep only events after snapshot)
            with self._journal_lock:
                self._journal = [event for event in self._journal if event.sequence_number > self._sequence_number]
                
                # Save trimmed journal
                with open(self.journal_file, 'wb') as f:
                    f.write(ormsgpack.packb(self._journal))
            
            logger.info(f"Saved snapshot for {self.symbol} at seq {self._sequence_number}")
        
        except (IOError, OSError, sqlite3.Error) as e:
            logger.error(f"Error saving snapshot: {e}")
    
    def add_order(self, order_id: str, side: str, price: float, quantity: int, metadata: Dict[str, Any] = None) -> None:
        """Add an order to the book."""
        event = BookEvent(
            timestamp=time.time(),
            event_type=BookEventType.ADD_ORDER,
            symbol=self.symbol,
            order_id=order_id,
            side=side,
            price=price,
            quantity=quantity,
            metadata=metadata or {}
        )
        
        self._apply_event(event)
        self._journal_event(event)
    
    def remove_order(self, order_id: str) -> None:
        """Remove an order from the book."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        
        event = BookEvent(
            timestamp=time.time(),
            event_type=BookEventType.REMOVE_ORDER,
            symbol=self.symbol,
            order_id=order_id,
            side=order['side'],
            price=order['price'],
            quantity=order['quantity']
        )
        
        self._apply_event(event)
        self._journal_event(event)
    
    def execute_order(self, order_id: str, quantity: int, trade_price: Optional[float] = None) -> None:
        """Execute an order (partial or full fill)."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        price = trade_price or order['price']
        
        event = BookEvent(
            timestamp=time.time(),
            event_type=BookEventType.EXECUTE_ORDER,
            symbol=self.symbol,
            order_id=order_id,
            side=order['side'],
            price=price,
            quantity=quantity,
            metadata={'trade_price': trade_price}
        )
        
        self._apply_event(event)
        self._journal_event(event)
    
    def _apply_event(self, event: BookEvent) -> None:
        """Apply an event to the in-memory order book."""
        if event.event_type == BookEventType.ADD_ORDER:
            self._add_order_impl(event.order_id, event.side, event.price, event.quantity)
        elif event.event_type == BookEventType.REMOVE_ORDER:
            self._remove_order_impl(event.order_id)
        elif event.event_type == BookEventType.EXECUTE_ORDER:
            self._execute_order_impl(event.order_id, event.quantity, event.metadata.get('trade_price'))
        elif event.event_type == BookEventType.CANCEL_ORDER:
            self._remove_order_impl(event.order_id)
    
    def _add_order_impl(self, order_id: str, side: str, price: float, quantity: int) -> None:
        """Add order implementation."""
        book = self.bids if side == 'buy' else self.asks
        
        # Create or update price level
        if price not in book:
            book[price] = OrderBookLevel(price=price, quantity=0, order_count=0, orders={})
        
        level = book[price]
        level.quantity += quantity
        level.order_count += 1
        level.orders[order_id] = quantity
        
        # Store order info
        self.orders[order_id] = {
            'price': price,
            'quantity': quantity,
            'side': side
        }
    
    def _remove_order_impl(self, order_id: str) -> None:
        """Remove order implementation."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        price = order['price']
        side = order['side']
        quantity = order['quantity']
        
        book = self.bids if side == 'buy' else self.asks
        
        if price in book:
            level = book[price]
            level.quantity -= quantity
            level.order_count -= 1
            
            if order_id in level.orders:
                del level.orders[order_id]
            
            # Remove empty price level
            if level.quantity <= 0:
                del book[price]
        
        del self.orders[order_id]
    
    def _execute_order_impl(self, order_id: str, quantity: int, trade_price: Optional[float] = None) -> None:
        """Execute order implementation."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        price = order['price']
        side = order['side']
        
        book = self.bids if side == 'buy' else self.asks
        
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
                    self.orders[order_id]['quantity'] = remaining
            
            # Remove empty price level
            if level.quantity <= 0:
                del book[price]
    
    def _journal_event(self, event: BookEvent) -> None:
        """Journal an event."""
        with self._journal_lock:
            event.sequence_number = self._sequence_number + 1
            self._sequence_number = event.sequence_number
            self._journal.append(event)
            
            # Save journal to file
            with open(self.journal_file, 'wb') as f:
                pickle.dump(self._journal, f)
            
            # Save to database
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO events (timestamp, event_type, symbol, order_id, side, price, quantity, metadata, sequence_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (event.timestamp, event.event_type.value, event.symbol, event.order_id, event.side, 
                  event.price, event.quantity, json.dumps(event.metadata), event.sequence_number))
            conn.commit()
            conn.close()
    
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
    
    def get_snapshot(self) -> OrderBookSnapshot:
        """Get current order book snapshot."""
        bids = sorted(self.bids.values(), key=lambda x: x.price, reverse=True)
        asks = sorted(self.asks.values(), key=lambda x: x.price)
        
        return OrderBookSnapshot(
            timestamp=time.time(),
            symbol=self.symbol,
            bids=bids,
            asks=asks,
            sequence_number=self._sequence_number
        )
    
    def get_events_since(self, sequence_number: int) -> List[BookEvent]:
        """Get events since a specific sequence number."""
        with self._journal_lock:
            return [event for event in self._journal if event.sequence_number > sequence_number]
    
    def query_events(self, start_time: Optional[float] = None, end_time: Optional[float] = None) -> List[BookEvent]:
        """Query events from database."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        query = "SELECT * FROM events WHERE symbol = ?"
        params = [self.symbol]
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        
        query += " ORDER BY sequence_number"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        events = []
        for row in rows:
            event = BookEvent(
                timestamp=row[1],
                event_type=BookEventType(row[2]),
                symbol=row[3],
                order_id=row[4],
                side=row[5],
                price=row[6],
                quantity=row[7],
                metadata=json.loads(row[8]) if row[8] else {}
            )
            events.append(event)
        
        return events


class PersistentOrderBookManager:
    """Manages multiple persistent order books."""
    
    def __init__(self, data_dir: str = "data/order_books"):
        self.data_dir = data_dir
        self.books: Dict[str, PersistentOrderBook] = {}
        self._running = False
        
        logger.info("PersistentOrderBookManager initialized")
    
    def get_book(self, symbol: str) -> PersistentOrderBook:
        """Get or create order book for symbol."""
        if symbol not in self.books:
            self.books[symbol] = PersistentOrderBook(symbol, self.data_dir)
        return self.books[symbol]
    
    def start_all(self) -> None:
        """Start all order books."""
        if self._running:
            return
        
        self._running = True
        for book in self.books.values():
            book.start()
        
        logger.info(f"Started {len(self.books)} persistent order books")
    
    def stop_all(self) -> None:
        """Stop all order books."""
        if not self._running:
            return
        
        self._running = False
        for book in self.books.values():
            book.stop()
        
        logger.info("Stopped all persistent order books")
    
    def get_symbols(self) -> List[str]:
        """Get all symbols with order books."""
        return list(self.books.keys())


# Global persistent order book manager instance
_book_manager: Optional[PersistentOrderBookManager] = None


def get_persistent_book_manager() -> PersistentOrderBookManager:
    """Get the global persistent order book manager instance."""
    global _book_manager
    if _book_manager is None:
        _book_manager = PersistentOrderBookManager()
    return _book_manager
