"""
FIX Market Data Feed Handler

Consumes FIX market data feeds (MarketDataSnapshotFullRefresh, MarketDataIncrementalRefresh)
for institutional-grade market data with sequence numbers and recovery mechanisms.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import threading
from collections import deque

from execution.simulator import get_execution_simulator, MarketData
from utils.logger import get_logger

logger = get_logger("execution.fix_feed")


class FIXMessageType(Enum):
    """FIX message types for market data."""
    HEARTBEAT = '0'
    TEST_REQUEST = '1'
    RESEND_REQUEST = '2'
    REJECT = '3'
    SEQUENCE_RESET = '4'
    LOGOUT = '5'
    LOGON = 'A'
    MARKET_DATA_REQUEST = 'V'
    MARKET_DATA_SNAPSHOT_FULL_REFRESH = 'W'
    MARKET_DATA_INCREMENTAL_REFRESH = 'X'
    MARKET_DATA_REJECT = 'Y'


class MDEntryType(Enum):
    """Market Data Entry types."""
    BID = '0'
    OFFER = '1'
    TRADE = '2'
    INDEX_VALUE = '3'
    OPENING_PRICE = '4'
    CLOSING_PRICE = '5'
    SETTLEMENT_PRICE = '6'
    TRADING_SESSION_HIGH_PRICE = '7'
    TRADING_SESSION_LOW_PRICE = '8'
    TRADING_SESSION_VWAP = '9'
    IMBALANCE_BUY = 'A'
    IMBALANCE_SELL = 'B'
    TRADE_VOLUME = 'B'
    OPEN_INTEREST = 'C'


@dataclass
class FIXConfig:
    """Configuration for FIX market data feed."""
    host: str
    port: int
    sender_comp_id: str
    target_comp_id: str
    username: Optional[str] = None
    password: Optional[str] = None
    heartbeat_interval: int = 30
    symbols: List[str] = None
    
    def __post_init__(self):
        if self.symbols is None:
            self.symbols = []


@dataclass
class FIXMessage:
    """FIX message representation."""
    msg_type: str
    fields: Dict[int, str]
    raw_message: str
    timestamp: float


class FIXParser:
    """FIX protocol parser."""
    
    @staticmethod
    def parse_message(raw_message: str) -> FIXMessage:
        """Parse a raw FIX message."""
        fields = {}
        msg_type = None
        
        # Split by SOH (ASCII 1)
        tags = raw_message.split('\x01')
        
        for tag_value in tags:
            if not tag_value:
                continue
            
            if '=' not in tag_value:
                continue
            
            tag, value = tag_value.split('=', 1)
            try:
                tag_int = int(tag)
                fields[tag_int] = value
                
                if tag_int == 35:  # MsgType
                    msg_type = value
            except ValueError:
                continue
        
        return FIXMessage(
            msg_type=msg_type or '',
            fields=fields,
            raw_message=raw_message,
            timestamp=time.time()
        )
    
    @staticmethod
    def build_message(msg_type: str, fields: Dict[int, str]) -> str:
        """Build a FIX message from fields."""
        # Add standard header fields
        all_fields = {
            8: 'FIX.4.2',  # BeginString
            35: msg_type,   # MsgType
            **fields
        }
        
        # Build message
        message_parts = []
        for tag in sorted(all_fields.keys()):
            message_parts.append(f"{tag}={all_fields[tag]}")
        
        message = '\x01'.join(message_parts) + '\x01'
        
        # Calculate and add checksum
        checksum = sum(ord(c) for c in message) % 256
        message += f"10={checksum:03d}\x01"
        
        return message


class FIXMarketDataFeed:
    """FIX market data feed handler."""
    
    def __init__(self, config: FIXConfig):
        self.config = config
        self.socket = None
        self._running = False
        self._callbacks: List[Callable[[MarketData], None]] = []
        self._sequence_numbers: Dict[str, int] = {}
        self._order_books: Dict[str, Dict[str, Any]] = {}
        self._last_heartbeat = time.time()
        
        # Session state
        self._session_id = None
        self._logged_in = False
        
        logger.info(f"Initialized FIX market data feed for {config.target_comp_id}")
    
    async def connect(self) -> None:
        """Connect to FIX server."""
        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            
            # Connect to server
            self.socket.connect((self.config.host, self.config.port))
            
            # Send Logon message
            await self._send_logon()
            
            # Start message processing
            self._running = True
            await self._process_messages()
            
        except (ConnectionError, TimeoutError, socket.error) as e:
            logger.error(f"Failed to connect to FIX server: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from FIX server."""
        if self._logged_in:
            await self._send_logout()
        
        self._running = False
        
        if self.socket:
            self.socket.close()
        
        logger.info("Disconnected from FIX server")
    
    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to market data for symbols."""
        if not self._logged_in:
            raise RuntimeError("Not logged in")
        
        for symbol in symbols:
            await self._send_market_data_request(symbol)
        
        logger.info(f"Subscribed to market data for {len(symbols)} symbols")
    
    def add_callback(self, callback: Callable[[MarketData], None]) -> None:
        """Add callback for market data updates."""
        self._callbacks.append(callback)
    
    async def _process_messages(self) -> None:
        """Process incoming FIX messages."""
        buffer = ""
        
        while self._running:
            try:
                # Receive data
                data = self.socket.recv(4096).decode('ascii')
                if not data:
                    break
                
                buffer += data
                
                # Process complete messages
                while '\x01' in buffer:
                    # Find message end (checksum field)
                    msg_end = buffer.find('10=')
                    if msg_end == -1:
                        break
                    
                    # Find end of message
                    checksum_end = buffer.find('\x01', msg_end)
                    if checksum_end == -1:
                        break
                    
                    # Extract complete message
                    message = buffer[:checksum_end + 1]
                    buffer = buffer[checksum_end + 1:]
                    
                    # Parse and process message
                    await self._handle_message(message)
                
                # Check heartbeat timeout
                if time.time() - self._last_heartbeat > self.config.heartbeat_interval * 2:
                    logger.warning("Heartbeat timeout, sending test request")
                    await self._send_test_request()
                
            except socket.timeout:
                # Check heartbeat timeout
                if time.time() - self._last_heartbeat > self.config.heartbeat_interval * 2:
                    logger.warning("Heartbeat timeout, sending test request")
                    await self._send_test_request()
            except (ConnectionError, RuntimeError, ValueError) as e:
                logger.error(f"Error processing FIX message: {e}")
                if self._running:
                    await asyncio.sleep(0.1)
    
    async def _handle_message(self, raw_message: str) -> None:
        """Handle incoming FIX message."""
        try:
            message = FIXParser.parse_message(raw_message)
            
            # Update sequence numbers
            seq_num = int(message.fields.get(34, '0'))
            self._sequence_numbers[message.msg_type] = seq_num
            
            # Handle different message types
            if message.msg_type == FIXMessageType.HEARTBEAT.value:
                self._last_heartbeat = time.time()
            elif message.msg_type == FIXMessageType.LOGON.value:
                await self._handle_logon(message)
            elif message.msg_type == FIXMessageType.LOGOUT.value:
                await self._handle_logout(message)
            elif message.msg_type == FIXMessageType.TEST_REQUEST.value:
                await self._handle_test_request(message)
            elif message.msg_type == FIXMessageType.MARKET_DATA_SNAPSHOT_FULL_REFRESH.value:
                await self._handle_snapshot_refresh(message)
            elif message.msg_type == FIXMessageType.MARKET_DATA_INCREMENTAL_REFRESH.value:
                await self._handle_incremental_refresh(message)
            elif message.msg_type == FIXMessageType.REJECT.value:
                logger.warning(f"Received reject: {message.fields}")
            else:
                logger.debug(f"Received unhandled message type: {message.msg_type}")
        
        except (ValueError, KeyError, RuntimeError) as e:
            logger.error(f"Error handling FIX message: {e}")
    
    async def _handle_logon(self, message: FIXMessage) -> None:
        """Handle Logon response."""
        self._logged_in = True
        self._session_id = message.fields.get(49)
        logger.info("Logged in to FIX server")
    
    async def _handle_logout(self, message: FIXMessage) -> None:
        """Handle Logout message."""
        self._logged_in = False
        logger.info("Logged out from FIX server")
    
    async def _handle_test_request(self, message: FIXMessage) -> None:
        """Handle Test Request message."""
        await self._send_heartbeat(message.fields.get(112, ''))
    
    async def _handle_snapshot_refresh(self, message: FIXMessage) -> None:
        """Handle Market Data Snapshot Full Refresh."""
        try:
            symbol = message.fields.get(55, '')
            no_md_entries = int(message.fields.get(268, '0'))
            
            # Clear existing order book
            self._order_books[symbol] = {}
            
            # Parse MD entries
            md_entries = []
            for i in range(no_md_entries):
                md_entry = {}
                for tag, value in message.fields.items():
                    if tag >= 269 and tag <= 280:  # MD Entry fields
                        md_entry[tag] = value
                md_entries.append(md_entry)
            
            # Process entries
            for entry in md_entries:
                await self._process_md_entry(symbol, entry)
        
        except (ValueError, KeyError, RuntimeError) as e:
            logger.error(f"Error handling snapshot refresh: {e}")
    
    async def _handle_incremental_refresh(self, message: FIXMessage) -> None:
        """Handle Market Data Incremental Refresh."""
        try:
            no_md_entries = int(message.fields.get(268, '0'))
            
            # Parse MD entries
            md_entries = []
            for i in range(no_md_entries):
                md_entry = {}
                for tag, value in message.fields.items():
                    if tag >= 269 and tag <= 280:  # MD Entry fields
                        md_entry[tag] = value
                md_entries.append(md_entry)
            
            # Process entries
            for entry in md_entries:
                symbol = entry.get(55, '')
                await self._process_md_entry(symbol, entry)
        
        except (ValueError, KeyError, RuntimeError) as e:
            logger.error(f"Error handling incremental refresh: {e}")
    
    async def _process_md_entry(self, symbol: str, entry: Dict[str, str]) -> None:
        """Process a market data entry."""
        try:
            entry_type = entry.get(269, '')  # MDEntryType
            price = float(entry.get(270, '0'))  # MDEntryPx
            size = float(entry.get(271, '0'))  # MDEntrySize
            
            # Update order book
            if symbol not in self._order_books:
                self._order_books[symbol] = {}
            
            if entry_type == MDEntryType.BID.value:
                self._order_books[symbol][f"bid_{price}"] = size
            elif entry_type == MDEntryType.OFFER.value:
                self._order_books[symbol][f"ask_{price}"] = size
            elif entry_type == MDEntryType.TRADE.value:
                # Publish trade data
                market_data = MarketData(
                    symbol=symbol,
                    timestamp=time.time(),
                    last_price=price,
                    last_size=size
                )
                self._publish_market_data(market_data)
            
            # Publish order book data
            await self._publish_order_book(symbol)
        
        except (ValueError, KeyError, RuntimeError) as e:
            logger.error(f"Error processing MD entry: {e}")
    
    async def _publish_order_book(self, symbol: str) -> None:
        """Publish current order book for symbol."""
        if symbol not in self._order_books:
            return
        
        book = self._order_books[symbol]
        
        # Find best bid and ask
        best_bid = None
        best_ask = None
        bid_size = 0
        ask_size = 0
        
        for key, size in book.items():
            if key.startswith('bid_'):
                price = float(key.split('_')[1])
                if best_bid is None or price > best_bid:
                    best_bid = price
                    bid_size = size
            elif key.startswith('ask_'):
                price = float(key.split('_')[1])
                if best_ask is None or price < best_ask:
                    best_ask = price
                    ask_size = size
        
        if best_bid and best_ask:
            market_data = MarketData(
                symbol=symbol,
                timestamp=time.time(),
                bid_price=best_bid,
                ask_price=best_ask,
                bid_size=bid_size,
                ask_size=ask_size
            )
            self._publish_market_data(market_data)
    
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
    
    async def _send_logon(self) -> None:
        """Send Logon message."""
        fields = {
            49: self.config.sender_comp_id,  # SenderCompID
            56: self.config.target_comp_id,  # TargetCompID
            52: time.strftime('%Y%m%d-%H:%M:%S'),  # SendingTime
            98: '0',  # EncryptMethod
            108: str(self.config.heartbeat_interval),  # HeartBtInt
        }
        
        if self.config.username:
            fields[553] = self.config.username  # Username
        if self.config.password:
            fields[554] = self.config.password  # Password
        
        message = FIXParser.build_message(FIXMessageType.LOGON.value, fields)
        self.socket.send(message.encode('ascii'))
        
        logger.info("Sent Logon message")
    
    async def _send_logout(self) -> None:
        """Send Logout message."""
        fields = {
            49: self.config.sender_comp_id,
            56: self.config.target_comp_id,
            52: time.strftime('%Y%m%d-%H:%M:%S'),
        }
        
        message = FIXParser.build_message(FIXMessageType.LOGOUT.value, fields)
        self.socket.send(message.encode('ascii'))
        
        logger.info("Sent Logout message")
    
    async def _send_heartbeat(self, test_req_id: str = '') -> None:
        """Send Heartbeat message."""
        fields = {
            49: self.config.sender_comp_id,
            56: self.config.target_comp_id,
            52: time.strftime('%Y%m%d-%H:%M:%S'),
        }
        
        if test_req_id:
            fields[112] = test_req_id  # TestReqID
        
        message = FIXParser.build_message(FIXMessageType.HEARTBEAT.value, fields)
        self.socket.send(message.encode('ascii'))
    
    async def _send_test_request(self) -> None:
        """Send Test Request message."""
        fields = {
            49: self.config.sender_comp_id,
            56: self.config.target_comp_id,
            52: time.strftime('%Y%m%d-%H:%M:%S'),
            112: str(int(time.time()))  # TestReqID
        }
        
        message = FIXParser.build_message(FIXMessageType.TEST_REQUEST.value, fields)
        self.socket.send(message.encode('ascii'))
        
        logger.info("Sent Test Request message")
    
    async def _send_market_data_request(self, symbol: str) -> None:
        """Send Market Data Request message."""
        fields = {
            49: self.config.sender_comp_id,
            56: self.config.target_comp_id,
            52: time.strftime('%Y%m%d-%H:%M:%S'),
            55: symbol,  # Symbol
            262: '1',  # SubscriptionRequestType (Snapshot + Updates)
            263: '0',  # MarketDepth (Full book)
            264: '1',  # UpdateIncrementalRefresh
            265: '0',  # NoMDEntryTypes (all)
        }
        
        message = FIXParser.build_message(FIXMessageType.MARKET_DATA_REQUEST.value, fields)
        self.socket.send(message.encode('ascii'))
        
        logger.info(f"Sent Market Data Request for {symbol}")


class FIXFeedManager:
    """Manages multiple FIX market data feeds."""
    
    def __init__(self):
        self.feeds: Dict[str, FIXMarketDataFeed] = {}
        self._running = False
        
        logger.info("FIXFeedManager initialized")
    
    def add_feed(self, feed_id: str, config: FIXConfig) -> None:
        """Add a FIX feed."""
        feed = FIXMarketDataFeed(config)
        self.feeds[feed_id] = feed
        logger.info(f"Added FIX feed: {feed_id} ({config.target_comp_id})")
    
    def remove_feed(self, feed_id: str) -> None:
        """Remove a FIX feed."""
        if feed_id in self.feeds:
            del self.feeds[feed_id]
            logger.info(f"Removed FIX feed: {feed_id}")
    
    async def start_all(self) -> None:
        """Start all FIX feeds."""
        if self._running:
            return
        
        self._running = True
        
        tasks = []
        for feed_id, feed in self.feeds.items():
            task = asyncio.create_task(feed.connect())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Started {len(self.feeds)} FIX feeds")
    
    async def stop_all(self) -> None:
        """Stop all FIX feeds."""
        if not self._running:
            return
        
        self._running = False
        
        tasks = []
        for feed in self.feeds.values():
            task = asyncio.create_task(feed.disconnect())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Stopped all FIX feeds")
    
    def subscribe(self, feed_id: str, symbols: List[str]) -> None:
        """Subscribe to symbols on a specific feed."""
        if feed_id in self.feeds:
            asyncio.create_task(self.feeds[feed_id].subscribe(symbols))


# Global FIX feed manager instance
_fix_manager: Optional[FIXFeedManager] = None


def get_fix_feed_manager() -> FIXFeedManager:
    """Get the global FIX feed manager instance."""
    global _fix_manager
    if _fix_manager is None:
        _fix_manager = FIXFeedManager()
    return _fix_manager


# Utility functions for creating common FIX configurations
def create_fix_config(host: str, port: int, sender_comp_id: str, target_comp_id: str,
                     username: Optional[str] = None, password: Optional[str] = None,
                     symbols: List[str] = None) -> FIXConfig:
    """Create FIX market data feed configuration."""
    return FIXConfig(
        host=host,
        port=port,
        sender_comp_id=sender_comp_id,
        target_comp_id=target_comp_id,
        username=username,
        password=password,
        symbols=symbols or []
    )
