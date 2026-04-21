"""
Market Data Stream Implementation

Concrete implementation of BaseStream for real-time market data ingestion.
Supports WebSocket and HTTP polling sources with health monitoring and metrics.
"""

import asyncio
import time
import json
from typing import AsyncGenerator, Dict, List, Optional, Any, AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from collections import deque

from streams.base_stream import BaseStream, StreamState
from core.events import EventEnvelope, EventType, EventPriority
from utils.logger import get_logger

logger = get_logger("market_data_stream")

@dataclass
class MarketTick:
    """Normalized market tick data structure"""
    symbol: str
    price: float
    volume: float
    timestamp: datetime
    exchange: str
    venue: str
    side: str  # 'buy' or 'sell'
    size: float
    tick_id: Optional[str] = None

@dataclass
class StreamMetrics:
    """Stream performance metrics"""
    events_per_second: float = 0.0
    error_count: int = 0
    lag_ms: float = 0.0
    last_event_time: Optional[datetime] = None
    total_events: int = 0
    connection_status: str = "disconnected"

class MarketDataStream(BaseStream):
    """
    Concrete market data stream implementation.
    
    Supports multiple sources:
    - WebSocket connections for real-time data
    - HTTP polling for periodic snapshots
    - Mock data for testing
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self.source_type = config.get("source_type", "mock")  # "websocket", "http", "mock"
        self.source_url = config.get("source_url", "")
        self.api_key = config.get("api_key", "")
        self.polling_interval = config.get("polling_interval", 5.0)
        try:
            from data.asset_universe import get_watchlist_symbols
            _default_syms = get_watchlist_symbols()
        except Exception:
            _default_syms = ["BTC/USD", "ETH/USD"]
        self.symbols = config.get("symbols", _default_syms)
        
        # Stream state
        self._client: Optional["aiohttp.ClientSession"] = None
        self._websocket: Optional["websockets.WebSocketServerProtocol"] = None
        self._running = False
        self._last_error: Optional[str] = None
        self._stream_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        
        # Metrics
        self._metrics = StreamMetrics()
        self._event_times = deque(maxlen=1000)
        self._error_times = deque(maxlen=100)
        
        # Event queue
        self._event_queue = asyncio.Queue(maxsize=1000)
        self._subscribers: List[asyncio.Queue] = []
        
        logger.info(f"MarketDataStream initialized: {self.source_type} for {len(self.symbols)} symbols")
    
    def stream_type(self) -> str:
        """Return stream type identifier"""
        return "market_data"
    
    async def _connect(self) -> bool:
        """Connect to data source with health checks and backoff"""
        try:
            if self.source_type == "websocket":
                return await self._connect_websocket()
            elif self.source_type == "http":
                return await self._connect_http()
            elif self.source_type == "mock":
                return await self._connect_mock()
            else:
                raise ValueError(f"Unsupported source type: {self.source_type}")
                
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._last_error = str(e)
            self._metrics.error_count += 1
            self._metrics.connection_status = "error"
            return False
    
    async def _connect_websocket(self) -> bool:
        """Connect to WebSocket data source"""
        try:
            logger.info(f"Connecting to WebSocket: {self.source_url}")
            
            # Create WebSocket connection
            self._websocket = await websockets.connect(
                self.source_url,
                extra_headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
            )
            
            # Subscribe to market data
            subscribe_msg = {
                "action": "subscribe",
                "symbols": self.symbols,
                "type": "market_data"
            }
            await self._websocket.send(json.dumps(subscribe_msg))
            
            # Wait for subscription confirmation
            response = await self._websocket.recv()
            logger.info(f"WebSocket subscription response: {response}")
            
            self._metrics.connection_status = "connected"
            logger.info("WebSocket connection established")
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise
    
    async def _connect_http(self) -> bool:
        """Connect to HTTP polling source"""
        try:
            logger.info(f"Creating HTTP client for: {self.source_url}")
            self._client = aiohttp.ClientSession()
            
            # Test connection with health check
            test_url = f"{self.source_url}/health"
            async with self._client.get(test_url) as response:
                if response.status == 200:
                    self._metrics.connection_status = "connected"
                    logger.info("HTTP connection established")
                    return True
                else:
                    raise ConnectionError(f"Health check failed: {response.status}")
                    
        except Exception as e:
            logger.error(f"HTTP connection failed: {e}")
            raise
    
    async def _connect_mock(self) -> bool:
        """Connect to mock data source"""
        logger.info("Using mock data source")
        self._metrics.connection_status = "connected"
        return True
    
    async def _disconnect(self) -> None:
        """Clean disconnect with resource cleanup"""
        try:
            if self._websocket:
                await self._websocket.close()
                self._websocket = None
                logger.info("WebSocket connection closed")
            
            if self._client:
                await self._client.close()
                self._client = None
                logger.info("HTTP client closed")
            
            self._running = False
            self._metrics.connection_status = "disconnected"
            logger.info("MarketDataStream disconnected")
            
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
    
    async def _fetch_data(self) -> Optional[Any]:
        """Fetch data from source with error handling"""
        try:
            if self.source_type == "websocket":
                return await self._fetch_websocket_data()
            elif self.source_type == "http":
                return await self._fetch_http_data()
            elif self.source_type == "mock":
                return await self._fetch_mock_data()
            else:
                return None
                
        except Exception as e:
            logger.error(f"Data fetch failed: {e}")
            self._last_error = str(e)
            self._metrics.error_count += 1
            self._error_times.append(time.time())
            return None
    
    async def _fetch_websocket_data(self) -> Optional[Any]:
        """Fetch data from WebSocket"""
        try:
            # Wait for message with timeout
            message = await asyncio.wait_for(
                self._websocket.recv(), 
                timeout=30.0
            )
            
            # Parse JSON message
            data = json.loads(message)
            return data
            
        except asyncio.TimeoutError:
            logger.warning("WebSocket receive timeout")
            return None
        except Exception as e:
            logger.error(f"WebSocket data fetch error: {e}")
            return None
    
    async def _fetch_http_data(self) -> Optional[Any]:
        """Fetch data from HTTP API"""
        try:
            # Build query parameters
            params = {"symbols": ",".join(self.symbols)} if self.symbols else {}
            
            async with self._client.get(
                f"{self.source_url}/market_data",
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"HTTP request failed: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"HTTP data fetch error: {e}")
            return None
    
    async def _fetch_mock_data(self) -> Optional[Any]:
        """Generate mock market data"""
        try:
            # Generate realistic mock data
            mock_data = []
            current_time = datetime.now()
            
            for symbol in self.symbols:
                # Generate random price around current market price
                base_price = 45000.0 if "BTC" in symbol else 3000.0
                price_variation = (hash(symbol) % 1000 - 500) / 100.0
                current_price = base_price + price_variation
                
                mock_data.append({
                    "symbol": symbol,
                    "price": current_price,
                    "volume": 1000000.0 + (hash(symbol) % 500000),
                    "timestamp": current_time.isoformat(),
                    "exchange": "mock",
                    "venue": "mock",
                    "side": "buy" if hash(symbol) % 2 == 0 else "sell",
                    "size": 0.1 + (hash(symbol) % 100) / 100.0,
                    "tick_id": f"mock_{int(time.time())}_{hash(symbol) % 10000}"
                })
            
            return mock_data
            
        except Exception as e:
            logger.error(f"Mock data generation error: {e}")
            return None
    
    async def _transform_to_events(self, data: Any) -> List[EventEnvelope]:
        """Transform raw data into normalized EventEnvelope objects"""
        try:
            events = []
            current_time = datetime.now()
            
            if isinstance(data, list):
                # Handle list of market data
                for item in data:
                    event = self._create_market_event(item, current_time)
                    if event:
                        events.append(event)
            elif isinstance(data, dict):
                # Handle single market data item
                event = self._create_market_event(data, current_time)
                if event:
                    events.append(event)
            
            # Update metrics
            self._update_metrics(events)
            
            return events
            
        except Exception as e:
            logger.error(f"Data transformation error: {e}")
            return []
    
    def _create_market_event(self, data: Dict[str, Any], wall_time: datetime) -> Optional[EventEnvelope]:
        """Create EventEnvelope from market data.

        Uses the provider's own timestamp from the payload so that downstream
        staleness checks (cross-timeframe aggregator, DataFreshnessPanel,
        lag_ms metric) reflect actual feed latency rather than local ingestion
        time.  Falls back to wall_time only when the field is absent or
        unparseable, and logs the fallback.
        """
        try:
            # Validate required fields
            if not all(key in data for key in ["symbol", "price", "timestamp"]):
                logger.warning(f"Missing required fields in market data: {data}")
                return None

            # --- H1 fix: prefer provider timestamp over batch wall-clock ---
            raw_ts = data["timestamp"]
            provider_ts: Optional[datetime] = None
            if isinstance(raw_ts, datetime):
                provider_ts = raw_ts
            elif isinstance(raw_ts, (int, float)):
                try:
                    provider_ts = datetime.fromtimestamp(float(raw_ts))
                except (OSError, OverflowError, ValueError):
                    pass
            elif isinstance(raw_ts, str):
                try:
                    provider_ts = datetime.fromisoformat(raw_ts)
                except ValueError:
                    pass
            if provider_ts is None:
                logger.warning(
                    "Could not parse provider timestamp '%s' for %s — using wall-clock fallback",
                    raw_ts, data.get("symbol", "?"),
                )
                provider_ts = wall_time

            # Create MarketTick using the provider timestamp
            tick = MarketTick(
                symbol=data["symbol"],
                price=float(data["price"]),
                volume=float(data.get("volume", 0)),
                timestamp=provider_ts,
                exchange=data.get("exchange", "unknown"),
                venue=data.get("venue", "unknown"),
                side=data.get("side", "unknown"),
                size=float(data.get("size", 0.0)),
                tick_id=data.get("tick_id")
            )

            # Create EventEnvelope; embed true lag in metadata
            lag_ms = (wall_time - provider_ts).total_seconds() * 1000
            event = EventEnvelope(
                event_id=f"market_{tick.symbol}_{int(provider_ts.timestamp())}_{hash(str(tick)) % 10000}",
                event_type="market_tick",
                timestamp=provider_ts,
                source=self.stream_type(),
                data=tick,
                metadata={
                    "exchange": tick.exchange,
                    "venue": tick.venue,
                    "side": tick.side,
                    "lag_ms": round(lag_ms, 1),
                    "wall_time": wall_time.isoformat(),
                }
            )

            return event

        except Exception as e:
            logger.error(f"Event creation error: {e}")
            return None
    
    def _update_metrics(self, events: List[EventEnvelope]) -> None:
        """Update stream metrics"""
        try:
            current_time = time.time()
            
            # Update event count
            self._metrics.total_events += len(events)
            
            # Calculate events per second
            if self._event_times:
                # Remove old events (older than 1 minute)
                cutoff_time = current_time - 60
                while self._event_times and self._event_times[0] < cutoff_time:
                    self._event_times.popleft()
                
                # Add current events
                for event in events:
                    self._event_times.append(current_time)
                    if len(self._event_times) > 1000: self._event_times[:] = self._event_times[-1000:]
                
                # Calculate rate
                if len(self._event_times) > 1:
                    time_span = self._event_times[-1] - self._event_times[0]
                    if time_span > 0:
                        self._metrics.events_per_second = len(self._event_times) / time_span
            
            # Update last event time
            if events:
                self._metrics.last_event_time = events[-1].timestamp
                self._metrics.lag_ms = (current_time - events[-1].timestamp.timestamp()) * 1000
            
            # Log metrics periodically
            if self._metrics.total_events % 100 == 0:
                logger.info(f"Stream metrics: {self._metrics.total_events} events, "
                           f"{self._metrics.events_per_second:.2f}/sec, "
                           f"lag: {self._metrics.lag_ms:.1f}ms, "
                           f"errors: {self._metrics.error_count}")
            
        except Exception as e:
            logger.error(f"Metrics update error: {e}")
    
    async def start(self) -> None:
        """Start the stream with health monitoring"""
        try:
            logger.info(f"Starting MarketDataStream: {self.source_type}")
            
            if not await self._connect():
                raise ConnectionError("Failed to connect to data source")
            
            self._running = True
            
            # Start background tasks (store refs so stop() can cancel)
            self._stream_task = asyncio.create_task(self._stream_loop())
            self._health_task = asyncio.create_task(self._health_check_loop())
            
            logger.info("MarketDataStream started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start stream: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the stream gracefully"""
        try:
            logger.info("Stopping MarketDataStream")
            self._running = False
            for t in (self._stream_task, self._health_task):
                if t and not t.done():
                    t.cancel()
            self._stream_task = self._health_task = None
            await self._disconnect()
            logger.info("MarketDataStream stopped")
            
        except Exception as e:
            logger.error(f"Error stopping stream: {e}")
    
    async def subscribe(self) -> AsyncGenerator[EventEnvelope, None]:
        """Subscribe to stream events"""
        try:
            while self._running:
                try:
                    # Get event from queue with timeout
                    event = await asyncio.wait_for(
                        self._event_queue.get(),
                        timeout=1.0
                    )
                    yield event
                    
                except asyncio.TimeoutError:
                    # No event available, continue
                    continue
                except Exception as e:
                    logger.error(f"Error in subscription: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            raise
    
    async def _stream_loop(self) -> None:
        """Main streaming loop"""
        try:
            while self._running:
                # Fetch data
                data = await self._fetch_data()
                
                if data:
                    # Transform to events
                    events = await self._transform_to_events(data)
                    
                    # Add to queue
                    for event in events:
                        try:
                            await self._event_queue.put(event)
                        except asyncio.QueueFull:
                            logger.warning("Event queue full, dropping event")
                            self._metrics.error_count += 1
                
                # Sleep based on source type
                if self.source_type == "mock":
                    await asyncio.sleep(1.0)  # Mock data every second
                elif self.source_type == "http":
                    await asyncio.sleep(self.polling_interval)
                else:
                    await asyncio.sleep(0.1)  # WebSocket is event-driven
                    
        except Exception as e:
            logger.error(f"Stream loop error: {e}")
            self._running = False
    
    async def _health_check_loop(self) -> None:
        """Periodic health monitoring"""
        try:
            while self._running:
                await asyncio.sleep(30.0)  # Check every 30 seconds
                
                # Check connection health
                if self.source_type == "websocket" and self._websocket:
                    try:
                        # Send ping
                        await self._websocket.ping()
                    except Exception as e:
                        logger.warning(f"WebSocket health check failed: {e}")
                        self._metrics.connection_status = "error"
                        self._metrics.error_count += 1
                
                # Log health status
                logger.info(f"Health check: {self._metrics.connection_status}, "
                           f"events: {self._metrics.total_events}, "
                           f"rate: {self._metrics.events_per_second:.2f}/sec")
                
        except Exception as e:
            logger.error(f"Health check loop error: {e}")
    
    def get_metrics(self) -> StreamMetrics:
        """Get current stream metrics"""
        return self._metrics
    
    def get_status(self) -> Dict[str, Any]:
        """Get stream status"""
        return {
            "stream_type": self.stream_type(),
            "source_type": self.source_type,
            "running": self._running,
            "connection_status": self._metrics.connection_status,
            "symbols": self.symbols,
            "metrics": {
                "total_events": self._metrics.total_events,
                "events_per_second": self._metrics.events_per_second,
                "error_count": self._metrics.error_count,
                "lag_ms": self._metrics.lag_ms,
                "last_event_time": self._metrics.last_event_time.isoformat() if self._metrics.last_event_time else None
            }
        }
