"""
Feed Handler Services - Dedicated market data feed processors

Implements feed handlers for different market data sources:
- MulticastFeedHandler: UDP multicast (ITCH, SOUPBIN, OPRA)
- FixFeedHandler: FIX protocol with session management
- WsFeedHandler: WebSocket for crypto exchanges
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import threading

from execution.multicast_feed import get_multicast_feed_manager, MulticastFeedManager, MulticastFeedHandler, create_itch_config, create_soupbin_config
from execution.fix_feed import get_fix_feed_manager, FIXFeedManager, FIXMarketDataFeed, create_fix_config
from execution.market_data_ingestor import get_market_data_ingestor, create_binance_websocket_config, create_kraken_websocket_config
from data.market_data_schemas import DataType
from utils.logger import get_logger

logger = get_logger("feed_handlers")


class FeedHandlerType(Enum):
    """Types of feed handlers."""
    MULTICAST = "multicast"
    FIX = "fix"
    WEBSOCKET = "websocket"


@dataclass
class FeedHandlerConfig:
    """Configuration for a feed handler."""
    handler_type: FeedHandlerType
    name: str
    symbols: List[str]
    credentials: Dict[str, str] = None
    settings: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.credentials is None:
            self.credentials = {}
        if self.settings is None:
            self.settings = {}


class FeedHandler:
    """Base class for all feed handlers."""
    
    def __init__(self, config: FeedHandlerConfig):
        self.config = config
        self.handler_type = config.handler_type
        self.name = config.name
        self.symbols = config.symbols
        self._running = False
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._last_heartbeat = time.time()
        
        logger.info(f"Initialized {self.handler_type.value} feed handler: {self.name}")
    
    async def start(self) -> None:
        """Start the feed handler."""
        if self._running:
            return
        
        self._running = True
        logger.info(f"Starting {self.handler_type.value} feed handler: {self.name}")
    
    async def stop(self) -> None:
        """Stop the feed handler."""
        if not self._running:
            return
        
        self._running = False
        logger.info(f"Stopped {self.handler_type.value} feed handler: {self.name}")
    
    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe to market data updates."""
        self._callbacks.append(callback)
    
    def _publish_data(self, data: Dict[str, Any]) -> None:
        """Publish market data to subscribers."""
        for callback in self._callbacks:
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Error in feed handler callback: {e}")
    
    def _send_heartbeat(self) -> None:
        """Send heartbeat to anti-silent-failure system."""
        heartbeat_data = {
            "handler_type": self.handler_type.value,
            "handler_name": self.name,
            "timestamp": time.time(),
            "status": "running" if self._running else "stopped",
            "symbol_count": len(self.symbols)
        }
        
        self._publish_data(heartbeat_data)
        self._last_heartbeat = time.time()


class MulticastFeedHandler(FeedHandler):
    """UDP multicast feed handler."""
    
    def __init__(self, config: FeedHandlerConfig):
        super().__init__(config)
        self.multicast_manager: Optional[MulticastFeedManager] = None
        self.feed_handlers: Dict[str, MulticastFeedHandler] = {}
    
    async def start(self) -> None:
        """Start multicast feed handlers."""
        await super().start()
        
        try:
            self.multicast_manager = get_multicast_feed_manager()
            
            # Create multicast feed configurations
            for symbol in self.symbols:
                # Create ITCH configuration (NASDAQ)
                itch_config = create_itch_config(
                    multicast_group="239.1.1.1",
                    port=50000,
                    interface="eth0",
                    symbols=[symbol]
                )
                
                feed_id = f"{self.name}_itch_{symbol}"
                self.multicast_manager.add_feed(feed_id, itch_config)
                self.feed_handlers[feed_id] = self.multicast_manager.feeds[feed_id]
            
            # Start all feeds
            await self.multicast_manager.start_all()
            
            # Subscribe to market data
            for feed_id, feed in self.feed_handlers.items():
                feed.subscribe(self._on_market_data)
            
            logger.info(f"Started {len(self.feed_handlers)} multicast feeds")
        
        except Exception as e:
            logger.error(f"Failed to start multicast feed handler: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop multicast feed handlers."""
        await super().stop()
        
        if self.multicast_manager:
            await self.multicast_manager.stop_all()
        
        self.feed_handlers.clear()
    
    def _on_market_data(self, market_data) -> None:
        """Handle market data from multicast feeds."""
        # Convert to normalized format
        normalized_data = {
            "symbol": market_data.symbol,
            "timestamp": market_data.timestamp,
            "data_type": DataType.MULTICAST_ITCH,
            "bid_price": market_data.bid_price,
            "ask_price": market_data.ask_price,
            "bid_size": market_data.bid_size,
            "ask_size": market_data.ask_size,
            "last_price": market_data.last_price,
            "last_size": market_data.last_size,
            "venue": "multicast",
            "feed_handler": self.name
        }
        
        self._publish_data(normalized_data)


class FixFeedHandler(FeedHandler):
    """FIX protocol feed handler."""
    
    def __init__(self, config: FeedHandlerConfig):
        super().__init__(config)
        self.fix_manager: Optional[FIXFeedManager] = None
        self.feed_handlers: Dict[str, FIXMarketDataFeed] = {}
    
    async def start(self) -> None:
        """Start FIX feed handlers."""
        await super().start()
        
        try:
            self.fix_manager = get_fix_feed_manager()
            
            # Create FIX configuration
            fix_config = create_fix_config(
                host=self.config.credentials.get("host", "localhost"),
                port=int(self.config.credentials.get("port", "5001")),
                sender_comp_id=self.config.credentials.get("sender_comp_id", "MERID"),
                target_comp_id=self.config.credentials.get("target_comp_id", "EXCHANGE"),
                username=self.config.credentials.get("username"),
                password=self.config.credentials.get("password"),
                symbols=self.symbols
            )
            
            feed_id = f"{self.name}_fix"
            self.fix_manager.add_feed(feed_id, fix_config)
            self.feed_handlers[feed_id] = self.fix_manager.feeds[feed_id]
            
            # Start FIX feed
            await self.fix_manager.start_all()
            
            # Subscribe to market data
            for feed_id, feed in self.feed_handlers.items():
                feed.add_callback(self._on_market_data)
            
            # Subscribe to symbols
            await self.fix_manager.subscribe(feed_id, self.symbols)
            
            logger.info(f"Started FIX feed handler: {self.name}")
        
        except Exception as e:
            logger.error(f"Failed to start FIX feed handler: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop FIX feed handlers."""
        await super().stop()
        
        if self.fix_manager:
            await self.fix_manager.stop_all()
        
        self.feed_handlers.clear()
    
    def _on_market_data(self, market_data) -> None:
        """Handle market data from FIX feeds."""
        # Convert to normalized format
        normalized_data = {
            "symbol": market_data.symbol,
            "timestamp": market_data.timestamp,
            "data_type": DataType.FIX_SNAPSHOT if "snapshot" in str(market_data).lower() else DataType.FIX_INCREMENTAL,
            "bid_price": market_data.get("bid_price"),
            "ask_price": market_data.get("ask_price"),
            "bid_size": market_data.get("bid_size"),
            "ask_size": market_data.get("ask_size"),
            "last_price": market_data.get("last_price"),
            "last_size": market_data.get("last_size"),
            "venue": "fix",
            "feed_handler": self.name
        }
        
        self._publish_data(normalized_data)


class WsFeedHandler(FeedHandler):
    """WebSocket feed handler for crypto exchanges."""
    
    def __init__(self, config: FeedHandlerConfig):
        super().__init__(config)
        self.market_data_ingestor = get_market_data_ingestor()
        self.feed_configs: Dict[str, Any] = {}
    
    async def start(self) -> None:
        """Start WebSocket feed handlers."""
        await super().start()
        
        try:
            # Add WebSocket feed configurations
            if "binance" in self.settings.get("exchanges", []):
                binance_config = create_binance_websocket_config(self.symbols)
                feed_id = f"{self.name}_binance"
                self.market_data_ingestor.add_source(feed_id, binance_config)
                self.feed_configs[feed_id] = binance_config
            
            if "kraken" in self.settings.get("exchanges", []):
                kraken_config = create_kraken_websocket_config(self.symbols)
                feed_id = f"{self.name}_kraken"
                self.market_data_ingestor.add_source(feed_id, kraken_config)
                self.feed_configs[feed_id] = kraken_config
            
            # Start market data ingestor
            await self.market_data_ingestor.start()
            
            # Subscribe to market data
            self.market_data_ingestor.subscribe(self._on_market_data)
            
            logger.info(f"Started WebSocket feed handler: {self.name}")
        
        except Exception as e:
            logger.error(f"Failed to start WebSocket feed handler: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop WebSocket feed handlers."""
        await super().stop()
        
        if self.market_data_ingestor:
            await self.market_data_ingestor.stop()
    
    def _on_market_data(self, market_data) -> None:
        """Handle market data from WebSocket feeds."""
        # Convert to normalized format
        normalized_data = {
            "symbol": market_data.symbol,
            "timestamp": market_data.timestamp,
            "data_type": DataType.TICK,
            "bid_price": market_data.bid_price,
            "ask_price": market_data.ask_price,
            "bid_size": market_data.bid_size,
            "ask_size": market_data.ask_size,
            "last_price": market_data.last_price,
            "last_size": market_data.last_size,
            "venue": "websocket",
            "feed_handler": self.name
        }
        
        self._publish_data(normalized_data)


class FeedHandlerManager:
    """Manages multiple feed handlers."""
    
    def __init__(self):
        self.handlers: Dict[str, FeedHandler] = {}
        self._running = False
        self._global_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        
        logger.info("FeedHandlerManager initialized")
    
    def add_handler(self, handler_id: str, handler: FeedHandler) -> None:
        """Add a feed handler."""
        self.handlers[handler_id] = handler
        logger.info(f"Added feed handler: {handler_id} ({handler.handler_type.value})")
    
    def remove_handler(self, handler_id: str) -> None:
        """Remove a feed handler."""
        if handler_id in self.handlers:
            del self.handlers[handler_id]
            logger.info(f"Removed feed handler: {handler_id}")
    
    async def start_all(self) -> None:
        """Start all feed handlers."""
        if self._running:
            return
        
        self._running = True
        
        tasks = []
        for handler_id, handler in self.handlers.items():
            task = asyncio.create_task(handler.start())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Started {len(self.handlers)} feed handlers")
    
    async def stop_all(self) -> None:
        """Stop all feed handlers."""
        if not self._running:
            return
        
        self._running = False
        
        tasks = []
        for handler in self.handlers.values():
            task = asyncio.create_task(handler.stop())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Stopped all feed handlers")
    
    def subscribe_all(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe to all feed handlers."""
        for handler in self.handlers.values():
            handler.subscribe(callback)
    
    def subscribe_handler(self, handler_id: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe to a specific feed handler."""
        if handler_id in self.handlers:
            self.handlers[handler_id].subscribe(callback)
    
    def get_handler(self, handler_id: str) -> Optional[FeedHandler]:
        """Get a specific feed handler."""
        return self.handlers.get(handler_id)
    
    def list_handlers(self) -> List[Dict[str, Any]]:
        """List all feed handlers."""
        return [
            {
                "handler_id": handler_id,
                "handler_type": handler.handler_type.value,
                "name": handler.name,
                "symbols": handler.symbols,
                "running": handler._running,
                "last_heartbeat": handler._last_heartbeat
            }
            for handler_id, handler in self.handlers.items()
        ]


# Global feed handler manager instance
_feed_manager: Optional[FeedHandlerManager] = None


def get_feed_handler_manager() -> FeedHandlerManager:
    """Get the global feed handler manager instance."""
    global _feed_manager
    if _feed_manager is None:
        _feed_manager = FeedHandlerManager()
    return _feed_manager


# Utility functions for creating common feed handler configurations
def create_multicast_handler_config(name: str, symbols: List[str], 
                                   multicast_group: str = "239.1.1.1", port: int = 50000,
                                   interface: str = "eth0") -> FeedHandlerConfig:
    """Create multicast feed handler configuration."""
    return FeedHandlerConfig(
        handler_type=FeedHandlerType.MULTICAST,
        name=name,
        symbols=symbols,
        settings={
            "multicast_group": multicast_group,
            "port": port,
            "interface": interface
        }
    )


def create_fix_handler_config(name: str, symbols: List[str],
                               host: str = "localhost", port: int = 5001,
                               sender_comp_id: str = "MERID", target_comp_id: str = "EXCHANGE",
                               username: Optional[str] = None, password: Optional[str] = None) -> FeedHandlerConfig:
    """Create FIX feed handler configuration."""
    credentials = {
        "host": host,
        "port": str(port),
        "sender_comp_id": sender_comp_id,
        "target_comp_id": target_comp_id
    }
    
    if username:
        credentials["username"] = username
    if password:
        credentials["password"] = password
    
    return FeedHandlerConfig(
        handler_type=FeedHandlerType.FIX,
        name=name,
        symbols=symbols,
        credentials=credentials
    )


def create_websocket_handler_config(name: str, symbols: List[str],
                                    exchanges: List[str] = None) -> FeedHandlerConfig:
    """Create WebSocket feed handler configuration."""
    return FeedHandlerConfig(
        handler_type=FeedHandlerType.WEBSOCKET,
        name=name,
        symbols=symbols,
        settings={
            "exchanges": exchanges or ["binance", "kraken"]
        }
    )
