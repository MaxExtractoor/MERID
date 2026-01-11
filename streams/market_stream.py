"""
Continuous Market Data Streaming Worker.

Runs as background async task, streams real-time market data to event bus.
No mocking - all data from CCXT exchanges.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass

import ccxt.async_support as ccxt
from core.streaming_bus import streaming_bus, EventChannel, StreamEvent
from utils.logger import get_logger

logger = get_logger("streams.market")


@dataclass
class MarketConfig:
    """Market data stream configuration."""
    exchanges: List[str] = None
    symbols: List[str] = None
    ticker_interval: float = 1.0  # seconds
    funding_interval: float = 60.0  # seconds
    
    def __post_init__(self):
        if self.exchanges is None:
            self.exchanges = ["binance", "coinbase"]
        if self.symbols is None:
            self.symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


class MarketDataStream:
    """
    Continuous market data streaming worker.
    
    Streams:
    - Ticker data (price, volume) every 1s
    - Funding rates every 60s
    - Trades (real-time via WebSocket when available)
    """
    
    def __init__(self, config: Optional[MarketConfig] = None):
        self.config = config or MarketConfig()
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.running = False
        self._tasks: List[asyncio.Task] = []
        
    async def initialize(self):
        """Initialize exchange connections."""
        for exchange_id in self.config.exchanges:
            try:
                exchange_class = getattr(ccxt, exchange_id)
                exchange = exchange_class({
                    'enableRateLimit': True,
                    'options': {'defaultType': 'future'}
                })
                await exchange.load_markets()
                self.exchanges[exchange_id] = exchange
                logger.info(f"Initialized {exchange_id} connection")
            except Exception as exc:
                logger.error(f"Failed to initialize {exchange_id}: {exc}")
    
    async def start(self):
        """Start all streaming workers."""
        if self.running:
            logger.warning("Market stream already running")
            return
        
        await self.initialize()
        self.running = True
        
        # Start ticker streams for each exchange
        for exchange_id, exchange in self.exchanges.items():
            task = asyncio.create_task(
                self._stream_tickers(exchange_id, exchange)
            )
            self._tasks.append(task)
            
            # Start funding rate stream
            task = asyncio.create_task(
                self._stream_funding(exchange_id, exchange)
            )
            self._tasks.append(task)
        
        logger.info(f"Market data stream started with {len(self._tasks)} workers")
    
    async def stop(self):
        """Stop all streaming workers."""
        self.running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for cancellation
        await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Close exchange connections
        for exchange in self.exchanges.values():
            await exchange.close()
        
        self._tasks.clear()
        self.exchanges.clear()
        logger.info("Market data stream stopped")
    
    async def _stream_tickers(self, exchange_id: str, exchange: ccxt.Exchange):
        """Stream ticker data continuously."""
        logger.info(f"Starting ticker stream for {exchange_id}")
        
        while self.running:
            try:
                for symbol in self.config.symbols:
                    try:
                        # Fetch ticker
                        ticker = await exchange.fetch_ticker(symbol)
                        
                        # Publish to event bus
                        event = StreamEvent(
                            channel=EventChannel.MARKET_DATA,
                            event_type="ticker",
                            data={
                                "symbol": symbol,
                                "exchange": exchange_id,
                                "price": ticker.get('last'),
                                "bid": ticker.get('bid'),
                                "ask": ticker.get('ask'),
                                "volume": ticker.get('baseVolume'),
                                "volume_quote": ticker.get('quoteVolume'),
                                "high": ticker.get('high'),
                                "low": ticker.get('low'),
                                "change": ticker.get('change'),
                                "percentage": ticker.get('percentage')
                            },
                            source=f"{exchange_id}_ticker"
                        )
                        
                        await streaming_bus.publish(event)
                        
                    except Exception as exc:
                        logger.warning(f"Failed to fetch {symbol} from {exchange_id}: {exc}")
                
                # Wait before next poll
                await asyncio.sleep(self.config.ticker_interval)
                
            except asyncio.CancelledError:
                logger.info(f"Ticker stream cancelled for {exchange_id}")
                break
            except Exception as exc:
                logger.error(f"Ticker stream error for {exchange_id}: {exc}")
                await asyncio.sleep(5)  # Back off on error
    
    async def _stream_funding(self, exchange_id: str, exchange: ccxt.Exchange):
        """Stream funding rates continuously."""
        logger.info(f"Starting funding stream for {exchange_id}")
        
        while self.running:
            try:
                for symbol in self.config.symbols:
                    try:
                        # Fetch funding rate (only for perpetual futures)
                        if hasattr(exchange, 'fetch_funding_rate'):
                            funding = await exchange.fetch_funding_rate(symbol)
                            
                            # Publish to event bus
                            event = StreamEvent(
                                channel=EventChannel.MARKET_DATA,
                                event_type="funding",
                                data={
                                    "symbol": symbol,
                                    "exchange": exchange_id,
                                    "funding_rate": funding.get('fundingRate'),
                                    "next_funding_time": funding.get('fundingTimestamp'),
                                    "mark_price": funding.get('markPrice'),
                                    "index_price": funding.get('indexPrice')
                                },
                                source=f"{exchange_id}_funding"
                            )
                            
                            await streaming_bus.publish(event)
                            
                    except Exception as exc:
                        logger.debug(f"Funding rate not available for {symbol} on {exchange_id}")
                
                # Wait before next poll
                await asyncio.sleep(self.config.funding_interval)
                
            except asyncio.CancelledError:
                logger.info(f"Funding stream cancelled for {exchange_id}")
                break
            except Exception as exc:
                logger.error(f"Funding stream error for {exchange_id}: {exc}")
                await asyncio.sleep(30)  # Back off on error


# Global market stream instance
market_stream = MarketDataStream()


async def start_market_stream():
    """Start the global market data stream."""
    await market_stream.start()


async def stop_market_stream():
    """Stop the global market data stream."""
    await market_stream.stop()
