"""
MarketStream - CCXT-based market data stream per MASTER_SPEC v1.0

This module implements production-grade market data streaming using CCXT.
Emits normalized price and funding rate events as EventEnvelope objects.

Key features:
- Multi-exchange support (Binance, Coinbase, etc.)
- Normalized ticker and funding rate events
- Rate limiting and backoff
- No trading logic (data ingestion only)

Reference: MASTER_SPEC.md Section 3 (Layer 1: Data Ingestion)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from core.events import EventEnvelope, EventType, EventPriority, EventMetadata
from streams.base_stream import (
    BaseStream,
    StreamConfig,
    StreamState,
    ConnectionError,
    get_stream_registry,
)
from utils.deps import get_ccxt_async
from utils.logger import get_logger

logger = get_logger("streams.market")


@dataclass
class MarketStreamConfig(StreamConfig):
    """Configuration for market data stream."""
    
    exchanges: List[str] = field(default_factory=lambda: ["binance", "coinbase"])
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    
    ticker_interval_seconds: float = 1.0
    funding_interval_seconds: float = 60.0
    orderbook_depth: int = 10
    
    enable_tickers: bool = True
    enable_funding: bool = True
    enable_orderbook: bool = False
    
    rate_limit_per_exchange: int = 10
    rate_limit_window_seconds: float = 1.0


@dataclass
class ExchangeConnection:
    """Wrapper for exchange connection state."""
    
    exchange_id: str
    exchange: object
    connected: bool = False
    last_request: float = 0.0
    request_count: int = 0
    error_count: int = 0
    
    def can_request(self, rate_limit: int, window: float) -> bool:
        """Check if we can make another request within rate limits."""
        now = time.time()
        if now - self.last_request > window:
            self.request_count = 0
        return self.request_count < rate_limit
    
    def record_request(self) -> None:
        """Record a request for rate limiting."""
        self.last_request = time.time()
        self.request_count += 1


class MarketStream(BaseStream):
    """
    Production-grade market data stream using CCXT.
    
    Streams normalized price and funding rate data from multiple exchanges.
    All data is emitted as EventEnvelope objects.
    
    This stream:
    - Connects to configured exchanges via CCXT
    - Polls ticker data at configurable intervals
    - Polls funding rates for perpetual futures
    - Normalizes all data to canonical event format
    - Handles rate limiting and reconnection
    - Never performs trading operations
    """
    
    def __init__(
        self,
        stream_id: str = "market-stream-01",
        config: Optional[MarketStreamConfig] = None,
    ) -> None:
        """
        Initialize market stream.
        
        Args:
            stream_id: Unique identifier for this stream
            config: Optional configuration override
        """
        self._market_config = config or MarketStreamConfig()
        super().__init__(stream_id, self._market_config)
        
        self._connections: Dict[str, ExchangeConnection] = {}
        self._ticker_task: Optional[asyncio.Task[None]] = None
        self._funding_task: Optional[asyncio.Task[None]] = None
        self._seen_symbols: Set[str] = set()
    
    @property
    def stream_type(self) -> str:
        """Type identifier for this stream."""
        return "market"
    
    async def _connect(self) -> None:
        """
        Connect to all configured exchanges.
        
        Raises:
            ConnectionError: If no exchanges could be connected
        """
        ccxt_async = get_ccxt_async()
        if not ccxt_async:
            raise ConnectionError(
                self._stream_id,
                "CCXT library not installed. Run: pip install ccxt"
            )
        
        connected_count = 0
        
        for exchange_id in self._market_config.exchanges:
            try:
                exchange_class = getattr(ccxt_async, exchange_id, None)
                if exchange_class is None:
                    self._logger.warning("Unknown exchange: %s", exchange_id)
                    continue
                
                exchange = exchange_class({
                    "enableRateLimit": True,
                    "options": {"defaultType": "spot"},
                })
                
                await exchange.load_markets()
                
                self._connections[exchange_id] = ExchangeConnection(
                    exchange_id=exchange_id,
                    exchange=exchange,
                    connected=True,
                )
                
                connected_count += 1
                self._logger.info(
                    "Connected to %s (%d markets)",
                    exchange_id, len(exchange.markets)
                )
                
            except Exception as e:
                self._logger.error("Failed to connect to %s: %s", exchange_id, e)
        
        if connected_count == 0:
            raise ConnectionError(
                self._stream_id,
                f"Failed to connect to any exchange: {self._market_config.exchanges}"
            )
        
        self._logger.info(
            "Market stream connected to %d/%d exchanges",
            connected_count, len(self._market_config.exchanges)
        )
    
    async def _disconnect(self) -> None:
        """Disconnect from all exchanges."""
        for conn in self._connections.values():
            try:
                if conn.connected and hasattr(conn.exchange, "close"):
                    await conn.exchange.close()
                conn.connected = False
            except Exception as e:
                self._logger.error("Error closing %s: %s", conn.exchange_id, e)
        
        self._connections.clear()
        self._logger.info("Market stream disconnected")
    
    async def _fetch_data(self) -> Optional[object]:
        """
        Fetch market data from exchanges.
        
        This method is called in the main stream loop.
        Returns None as we use separate tasks for tickers/funding.
        """
        if self._ticker_task is None and self._market_config.enable_tickers:
            self._ticker_task = asyncio.create_task(self._ticker_loop())
        
        if self._funding_task is None and self._market_config.enable_funding:
            self._funding_task = asyncio.create_task(self._funding_loop())
        
        await asyncio.sleep(1.0)
        return None
    
    def _transform_to_events(self, data: object) -> List[EventEnvelope]:
        """Transform raw data to events (not used, events created in loops)."""
        return []
    
    async def _ticker_loop(self) -> None:
        """Continuous ticker polling loop."""
        self._logger.info("Starting ticker loop")
        
        while self._running and self._state == StreamState.STREAMING:
            try:
                for exchange_id, conn in self._connections.items():
                    if not conn.connected:
                        continue
                    
                    if not conn.can_request(
                        self._market_config.rate_limit_per_exchange,
                        self._market_config.rate_limit_window_seconds,
                    ):
                        continue
                    
                    for symbol in self._market_config.symbols:
                        try:
                            ticker = await conn.exchange.fetch_ticker(symbol)
                            conn.record_request()
                            
                            event = self._create_ticker_event(
                                exchange_id, symbol, ticker
                            )
                            await self.emit(event)
                            
                        except Exception as e:
                            conn.error_count += 1
                            self._logger.debug(
                                "Ticker fetch failed %s/%s: %s",
                                exchange_id, symbol, e
                            )
                
                await asyncio.sleep(self._market_config.ticker_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Ticker loop error: %s", e)
                await asyncio.sleep(5.0)
    
    async def _funding_loop(self) -> None:
        """Continuous funding rate polling loop."""
        self._logger.info("Starting funding loop")
        
        while self._running and self._state == StreamState.STREAMING:
            try:
                for exchange_id, conn in self._connections.items():
                    if not conn.connected:
                        continue
                    
                    if not hasattr(conn.exchange, "fetch_funding_rate"):
                        continue
                    
                    for symbol in self._market_config.symbols:
                        try:
                            perp_symbol = self._get_perp_symbol(symbol)
                            funding = await conn.exchange.fetch_funding_rate(perp_symbol)
                            conn.record_request()
                            
                            event = self._create_funding_event(
                                exchange_id, symbol, funding
                            )
                            await self.emit(event)
                            
                        except Exception as e:
                            self._logger.debug(
                                "Funding fetch failed %s/%s: %s",
                                exchange_id, symbol, e
                            )
                
                await asyncio.sleep(self._market_config.funding_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Funding loop error: %s", e)
                await asyncio.sleep(30.0)
    
    def _create_ticker_event(
        self,
        exchange_id: str,
        symbol: str,
        ticker: Dict[str, object],
    ) -> EventEnvelope:
        """
        Create normalized ticker event.
        
        Args:
            exchange_id: Source exchange
            symbol: Trading symbol
            ticker: Raw ticker data from CCXT
            
        Returns:
            EventEnvelope with normalized ticker data
        """
        price = ticker.get("last")
        if price is None:
            price = ticker.get("close", 0.0)
        
        return EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source=f"{exchange_id}:{symbol}",
            payload={
                "data_type": "ticker",
                "exchange": exchange_id,
                "symbol": symbol,
                "price": float(price) if price else 0.0,
                "bid": float(ticker.get("bid", 0.0) or 0.0),
                "ask": float(ticker.get("ask", 0.0) or 0.0),
                "volume": float(ticker.get("baseVolume", 0.0) or 0.0),
                "volume_quote": float(ticker.get("quoteVolume", 0.0) or 0.0),
                "high_24h": float(ticker.get("high", 0.0) or 0.0),
                "low_24h": float(ticker.get("low", 0.0) or 0.0),
                "change_24h": float(ticker.get("change", 0.0) or 0.0),
                "change_pct_24h": float(ticker.get("percentage", 0.0) or 0.0),
                "timestamp": ticker.get("timestamp", int(time.time() * 1000)),
            },
            priority=EventPriority.HIGH,
            metadata=EventMetadata(
                producer_id=self._stream_id,
                producer_type="market_stream",
                tags={"exchange": exchange_id, "symbol": symbol},
            ),
        )
    
    def _create_funding_event(
        self,
        exchange_id: str,
        symbol: str,
        funding: Dict[str, object],
    ) -> EventEnvelope:
        """
        Create normalized funding rate event.
        
        Args:
            exchange_id: Source exchange
            symbol: Trading symbol
            funding: Raw funding data from CCXT
            
        Returns:
            EventEnvelope with normalized funding data
        """
        return EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source=f"{exchange_id}:{symbol}:funding",
            payload={
                "data_type": "funding_rate",
                "exchange": exchange_id,
                "symbol": symbol,
                "funding_rate": float(funding.get("fundingRate", 0.0) or 0.0),
                "funding_timestamp": funding.get("fundingTimestamp"),
                "next_funding_time": funding.get("nextFundingTimestamp"),
                "mark_price": float(funding.get("markPrice", 0.0) or 0.0),
                "index_price": float(funding.get("indexPrice", 0.0) or 0.0),
                "interest_rate": float(funding.get("interestRate", 0.0) or 0.0),
                "timestamp": int(time.time() * 1000),
            },
            priority=EventPriority.NORMAL,
            metadata=EventMetadata(
                producer_id=self._stream_id,
                producer_type="market_stream",
                tags={"exchange": exchange_id, "symbol": symbol, "type": "funding"},
            ),
        )
    
    def _get_perp_symbol(self, symbol: str) -> str:
        """
        Convert spot symbol to perpetual symbol format.
        
        Args:
            symbol: Spot symbol (e.g., "BTC/USDT")
            
        Returns:
            Perpetual symbol (e.g., "BTC/USDT:USDT")
        """
        if ":" in symbol:
            return symbol
        base_quote = symbol.split("/")
        if len(base_quote) == 2:
            return f"{symbol}:{base_quote[1]}"
        return symbol
    
    async def stop(self) -> None:
        """Stop the stream and all sub-tasks."""
        if self._ticker_task:
            self._ticker_task.cancel()
            try:
                await self._ticker_task
            except asyncio.CancelledError:
                pass
            self._ticker_task = None
        
        if self._funding_task:
            self._funding_task.cancel()
            try:
                await self._funding_task
            except asyncio.CancelledError:
                pass
            self._funding_task = None
        
        await super().stop()
    
    def get_exchange_stats(self) -> Dict[str, Dict[str, object]]:
        """Get statistics for each exchange connection."""
        return {
            exchange_id: {
                "connected": conn.connected,
                "request_count": conn.request_count,
                "error_count": conn.error_count,
                "last_request": conn.last_request,
            }
            for exchange_id, conn in self._connections.items()
        }


_market_stream: Optional[MarketStream] = None


def get_market_stream() -> MarketStream:
    """Get or create global market stream singleton."""
    global _market_stream
    if _market_stream is None:
        _market_stream = MarketStream()
        get_stream_registry().register(_market_stream)
    return _market_stream


async def start_market_stream(config: Optional[MarketStreamConfig] = None) -> MarketStream:
    """
    Start the global market stream.
    
    Args:
        config: Optional configuration override
        
    Returns:
        Running MarketStream instance
    """
    global _market_stream
    if _market_stream is None:
        _market_stream = MarketStream(config=config)
        get_stream_registry().register(_market_stream)
    
    if not _market_stream.is_running:
        await _market_stream.start()
    
    return _market_stream


async def stop_market_stream() -> None:
    """Stop the global market stream."""
    global _market_stream
    if _market_stream is not None:
        await _market_stream.stop()
