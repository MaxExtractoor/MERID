"""
Market Data Ingestor - Live and replay market data for the execution simulator

Handles multiple data sources:
- Live WebSocket feeds from crypto exchanges
- Replay of historical tick/quote data
- Normalized market data format
- Real-time publishing to simulator
"""

from __future__ import annotations

import asyncio
import json
import time
import websockets
from typing import Dict, List, Optional, Any, Callable, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
import aiohttp
import pandas as pd
from pathlib import Path

from execution.simulator import get_execution_simulator, MarketData
from utils.logger import get_logger

logger = get_logger("execution.market_data")


class DataSource(Enum):
    """Market data source types."""
    LIVE_WEBSOCKET = "live_websocket"
    LIVE_REST = "live_rest"
    REPLAY_FILE = "replay_file"
    REPLAY_DATABASE = "replay_database"


@dataclass
class MarketDataConfig:
    """Configuration for a market data source."""
    source_type: DataSource
    source_name: str
    symbols: List[str]
    credentials: Dict[str, str] = None
    settings: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.credentials is None:
            self.credentials = {}
        if self.settings is None:
            self.settings = {}


class MarketDataIngestor:
    """Market data ingestion service."""
    
    def __init__(self):
        self.sources: Dict[str, MarketDataConfig] = {}
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._callbacks: List[Callable[[MarketData], None]] = []
        self._symbol_subscriptions: Dict[str, set] = {}  # source -> symbols
        
        logger.info("MarketDataIngestor initialized")
    
    def add_source(self, source_id: str, config: MarketDataConfig) -> None:
        """Add a market data source."""
        self.sources[source_id] = config
        self._symbol_subscriptions[source_id] = set(config.symbols)
        logger.info(f"Added market data source: {source_id} ({config.source_type.value})")
    
    def remove_source(self, source_id: str) -> None:
        """Remove a market data source."""
        if source_id in self.sources:
            del self.sources[source_id]
            del self._symbol_subscriptions[source_id]
            if source_id in self._tasks:
                self._tasks[source_id].cancel()
                del self._tasks[source_id]
            logger.info(f"Removed market data source: {source_id}")
    
    def subscribe(self, callback: Callable[[MarketData], None]) -> None:
        """Subscribe to market data updates."""
        self._callbacks.append(callback)
    
    async def start(self) -> None:
        """Start all market data sources."""
        if self._running:
            return
        
        self._running = True
        
        # Start tasks for each source
        for source_id, config in self.sources.items():
            if config.source_type == DataSource.LIVE_WEBSOCKET:
                task = asyncio.create_task(self._run_websocket_source(source_id, config))
            elif config.source_type == DataSource.LIVE_REST:
                task = asyncio.create_task(self._run_rest_source(source_id, config))
            elif config.source_type == DataSource.REPLAY_FILE:
                task = asyncio.create_task(self._run_file_replay(source_id, config))
            else:
                logger.warning(f"Unsupported source type: {config.source_type}")
                continue
            
            self._tasks[source_id] = task
        
        logger.info(f"Started {len(self._tasks)} market data sources")
    
    async def stop(self) -> None:
        """Stop all market data sources."""
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks.values():
            task.cancel()
        
        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        
        self._tasks.clear()
        logger.info("Stopped all market data sources")
    
    async def _run_websocket_source(self, source_id: str, config: MarketDataConfig) -> None:
        """Run a WebSocket market data source."""
        exchange = config.source_name.lower()
        symbols = config.symbols
        
        # Exchange-specific WebSocket URLs and message formats
        ws_urls = {
            "binance": "wss://stream.binance.com:9443/ws",
            "kraken": "wss://ws.kraken.com/",
            "coinbase": "wss://ws-feed.exchange.coinbase.com"
        }
        
        ws_url = ws_urls.get(exchange)
        if not ws_url:
            logger.error(f"Unsupported exchange for WebSocket: {exchange}")
            return
        
        logger.info(f"Starting WebSocket source: {source_id} ({exchange})")
        
        while self._running:
            try:
                async with websockets.connect(ws_url) as websocket:
                    # Subscribe to streams
                    if exchange == "binance":
                        subscribe_msg = {
                            "method": "SUBSCRIBE",
                            "params": [f"{symbol.lower()}@ticker" for symbol in symbols],
                            "id": 1
                        }
                        await websocket.send(json.dumps(subscribe_msg))
                    
                    elif exchange == "kraken":
                        subscribe_msg = {
                            "event": "subscribe",
                            "pair": [symbol.upper() for symbol in symbols],
                            "subscription": {"name": "ticker"}
                        }
                        await websocket.send(json.dumps(subscribe_msg))
                    
                    elif exchange == "coinbase":
                        subscribe_msg = {
                            "type": "subscribe",
                            "product_ids": symbols,
                            "channels": ["ticker"]
                        }
                        await websocket.send(json.dumps(subscribe_msg))
                    
                    # Process messages
                    while self._running:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                            market_data = self._parse_websocket_message(exchange, message)
                            if market_data:
                                self._publish_market_data(market_data)
                        
                        except asyncio.TimeoutError:
                            # Send ping to keep connection alive
                            try:
                                await websocket.ping()
                            except (ConnectionError, RuntimeError):
                                break
                        except (ConnectionError, RuntimeError, ValueError) as e:
                            logger.error(f"Error processing WebSocket message: {e}")
                            break
            
            except (ConnectionError, RuntimeError) as e:
                logger.error(f"WebSocket connection error for {source_id}: {e}")
                if self._running:
                    await asyncio.sleep(5)  # Wait before reconnecting
    
    async def _run_rest_source(self, source_id: str, config: MarketDataConfig) -> None:
        """Run a REST polling market data source."""
        exchange = config.source_name.lower()
        symbols = config.symbols
        poll_interval = config.settings.get("poll_interval", 5.0)
        
        logger.info(f"Starting REST source: {source_id} ({exchange})")
        
        while self._running:
            try:
                for symbol in symbols:
                    market_data = await self._fetch_rest_ticker(exchange, symbol)
                    if market_data:
                        self._publish_market_data(market_data)
                
                await asyncio.sleep(poll_interval)
            
            except (ConnectionError, RuntimeError, ValueError) as e:
                logger.error(f"REST polling error for {source_id}: {e}")
                await asyncio.sleep(5)
    
    async def _run_file_replay(self, source_id: str, config: MarketDataConfig) -> None:
        """Replay market data from file."""
        file_path = config.settings.get("file_path")
        replay_speed = config.settings.get("replay_speed", 1.0)  # 1.0 = real-time
        
        if not file_path or not Path(file_path).exists():
            logger.error(f"Replay file not found: {file_path}")
            return
        
        logger.info(f"Starting file replay: {source_id} (speed: {replay_speed}x)")
        
        try:
            # Load data from file (assuming CSV format)
            df = pd.read_csv(file_path)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            start_time = time.time()
            first_timestamp = df['timestamp'].iloc[0].timestamp()
            
            for _, row in df.iterrows():
                if not self._running:
                    break
                
                # Calculate when to publish this tick
                data_timestamp = row['timestamp'].timestamp()
                elapsed_real_time = time.time() - start_time
                elapsed_data_time = (data_timestamp - first_timestamp) / replay_speed
                
                if elapsed_data_time > elapsed_real_time:
                    await asyncio.sleep(elapsed_data_time - elapsed_real_time)
                
                # Create market data
                market_data = MarketData(
                    symbol=row['symbol'],
                    timestamp=data_timestamp,
                    last_price=row.get('price'),
                    bid_price=row.get('bid'),
                    ask_price=row.get('ask'),
                    last_size=row.get('size'),
                    bid_size=row.get('bid_size'),
                    ask_size=row.get('ask_size')
                )
                
                self._publish_market_data(market_data)
        
        except (IOError, OSError, ValueError) as e:
            logger.error(f"File replay error for {source_id}: {e}")
    
    async def _fetch_rest_ticker(self, exchange: str, symbol: str) -> Optional[MarketData]:
        """Fetch ticker data via REST API."""
        try:
            if exchange == "binance":
                url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            return MarketData(
                                symbol=symbol,
                                timestamp=time.time(),
                                last_price=float(data['lastPrice']),
                                bid_price=float(data['bidPrice']),
                                ask_price=float(data['askPrice']),
                                last_size=float(data['volume'])
                            )
            
            elif exchange == "kraken":
                url = f"https://api.kraken.com/0/public/Ticker?pair={symbol.upper()}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data['error']:
                                return None
                            
                            result = list(data['result'].values())[0]
                            return MarketData(
                                symbol=symbol,
                                timestamp=time.time(),
                                last_price=float(result['c'][0]),
                                bid_price=float(result['b'][0]),
                                ask_price=float(result['a'][0]),
                                last_size=float(result['v'][1])
                            )
        
        except (ConnectionError, TimeoutError, ValueError) as e:
            logger.error(f"Error fetching REST ticker for {symbol}: {e}")
        
        return None
    
    def _parse_websocket_message(self, exchange: str, message: str) -> Optional[MarketData]:
        """Parse WebSocket message into MarketData."""
        try:
            data = json.loads(message)
            
            if exchange == "binance":
                if data.get('e') == '24hrTicker':
                    symbol = data['s']
                    return MarketData(
                        symbol=symbol,
                        timestamp=data['E'] / 1000.0,
                        last_price=float(data['c']),
                        bid_price=float(data['b']),
                        ask_price=float(data['a']),
                        last_size=float(data['v'])
                    )
            
            elif exchange == "kraken":
                if isinstance(data, dict) and data.get('channel') == 'ticker':
                    symbol = list(data['data'].keys())[0]
                    ticker_data = list(data['data'].values())[0]
                    return MarketData(
                        symbol=symbol,
                        timestamp=time.time(),
                        last_price=float(ticker_data['c'][0]),
                        bid_price=float(ticker_data['b'][0]),
                        ask_price=float(ticker_data['a'][0]),
                        last_size=float(ticker_data['v'][1])
                    )
            
            elif exchange == "coinbase":
                if data.get('type') == 'ticker':
                    return MarketData(
                        symbol=data['product_id'],
                        timestamp=time.time(),
                        last_price=float(data['price']),
                        bid_price=float(data.get('best_bid', 0)),
                        ask_price=float(data.get('best_ask', 0)),
                        last_size=float(data.get('volume_24h', 0))
                    )
        
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error(f"Error parsing WebSocket message: {e}")
        
        return None
    
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
    
    def add_symbol_subscription(self, source_id: str, symbol: str) -> None:
        """Add a symbol subscription to a source."""
        if source_id in self._symbol_subscriptions:
            self._symbol_subscriptions[source_id].add(symbol)
    
    def remove_symbol_subscription(self, source_id: str, symbol: str) -> None:
        """Remove a symbol subscription from a source."""
        if source_id in self._symbol_subscriptions:
            self._symbol_subscriptions[source_id].discard(symbol)


# Global market data ingestor instance
_market_data_ingestor: Optional[MarketDataIngestor] = None


def get_market_data_ingestor() -> MarketDataIngestor:
    """Get the global market data ingestor instance."""
    global _market_data_ingestor
    if _market_data_ingestor is None:
        _market_data_ingestor = MarketDataIngestor()
    return _market_data_ingestor


# Utility functions for creating common configurations
def create_binance_websocket_config(symbols: List[str]) -> MarketDataConfig:
    """Create Binance WebSocket configuration."""
    return MarketDataConfig(
        source_type=DataSource.LIVE_WEBSOCKET,
        source_name="binance",
        symbols=symbols
    )


def create_kraken_websocket_config(symbols: List[str]) -> MarketDataConfig:
    """Create Kraken WebSocket configuration."""
    return MarketDataConfig(
        source_type=DataSource.LIVE_WEBSOCKET,
        source_name="kraken",
        symbols=symbols
    )


def create_file_replay_config(file_path: str, symbols: List[str], replay_speed: float = 1.0) -> MarketDataConfig:
    """Create file replay configuration."""
    return MarketDataConfig(
        source_type=DataSource.REPLAY_FILE,
        source_name="file_replay",
        symbols=symbols,
        settings={"file_path": file_path, "replay_speed": replay_speed}
    )
