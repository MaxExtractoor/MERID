# Kalshi 15m Market Data Pipeline Documentation

## Overview

The Kalshi 15m market data pipeline provides real-time market data for the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) traded on Kalshi prediction markets. The pipeline consists of WebSocket subscriptions, orderbook management, market state tracking, and spot price integration.

## Architecture

### Component Hierarchy

```
KalshiWebSocket (Raw WS Client)
├── KalshiWebSocketBridge (Event Forwarder)
│   └── Event Bus (kalshi:price_update, kalshi:trade, kalshi:orderbook_delta)
├── KalshiMarketStateStore (Unified State)
│   ├── LocalOrderbook (Per-Market Orderbook)
│   └── UnifiedMarketState (Aggregated State)
└── UnifiedSpotService (Spot Price Provider)
    └── Coinbase Public API
```

### Key Files

- **WebSocket Client**: `merid/event_venues/kalshi/ws.py`
- **WebSocket Bridge**: `merid/event_venues/kalshi/ws_bridge.py`
- **Orderbook Management**: `merid/event_venues/kalshi/orderbook.py`
- **Market State Store**: `merid/event_venues/kalshi/market_state.py`
- **Market Catalog**: `merid/event_venues/kalshi/market_catalog.py`
- **Spot Service**: `data/unified_spot_service.py`
- **Threshold Config**: `merid/event_venues/kalshi/threshold_config.py`

## WebSocket Client (KalshiWebSocket)

### Initialization

```python
class KalshiWebSocket(EventVenueStream):
    def __init__(self, config: Optional[Any] = None):
        self.config = config or get_kalshi_config()
        
        # Connection state
        self._ws = None
        self._subscriptions: set = set()
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._auth_token: Optional[str] = None
        
        # Subscription tracking
        self._orderbook_tickers: set = set()
        self._trade_tickers: set = set()
        self._fill_tickers: set = set()
        self._event_ticker_subscriptions: set = set()
        self._ticker_subscriptions: set = set()
        
        # Sequence tracking
        self._last_seq: Dict[str, int] = {}
        self._seq_gaps: int = 0
        
        # Async message queue (increased to 32768 for high volume)
        self._msg_queue: Optional[asyncio.Queue] = None
        self._processor_task: Optional[asyncio.Task] = None
        
        # Orderbook snapshot cache
        self._ob_snapshots: Dict[str, Dict[str, Any]] = {}
        self._ob_initialised: set = set()
        
        # Coalescing buffer (50ms window, 100 messages max)
        self._coalescing_buffer = CoalescingBuffer(
            max_age_seconds=0.050,
            max_buffer_size=100,
            max_batch_size=20,
            cleanup_interval=2.0
        )
        
        # Timestamp manager for data freshness
        self._timestamp_manager = get_timestamp_manager()
        
        # Observability counters
        self._messages_received: int = 0
        self._errors_received: int = 0
        self._reconnect_count: int = 0
        self._last_message_ts: float = 0.0
        self._connect_ts: float = 0.0
        self._consecutive_auth_failures: int = 0
        
        # Reconnect lock (prevents concurrent reconnect storms)
        self._reconnect_lock: Optional[asyncio.Lock] = None
        self._reconnect_in_progress: bool = False
        
        # Per-connection parse lock (thread-safe message parsing)
        self._parse_lock = threading.Lock()
        
        # Callback executor (8 workers for concurrent processing)
        self._callback_executor = ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="kalshi-ws-callback"
        )
        
        # Queue pressure supervisor
        self._supervisor_task: Optional[asyncio.Task] = None
        self._pressure_thresholds = {
            "elevated": 0.50,
            "warn": 0.75,
            "critical": 0.90,
            "shutdown": 0.98,
            "restore": 0.40,
        }
```

### Connection Management

#### Exponential Backoff Reconnect

```python
async def _reconnect_loop(self):
    """Main reconnect loop with exponential backoff + jitter."""
    while self._running:
        try:
            await self._connect()
            await self._message_loop()
        except Exception as e:
            logger.error(f"[WS-RECONNECT-ERROR] {e}")
            
            # Exponential backoff with jitter
            delay = min(self._reconnect_delay * (1 + random.random() * 0.5), 
                       self._max_reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 
                                       self._max_reconnect_delay)
            
            await asyncio.sleep(delay)
```

**Error Handling**:
- **Reconnect errors** (`server_error`, `connection_reset`): Disconnect + reconnect
- **Rate-limit errors** (`rate_limited`): Back off without reconnecting
- **Auth errors** (`auth_failed`, `invalid_token`): Stop reconnecting after 3 consecutive failures
- **Warning errors** (`invalid_channel`, `bad_request`, `unknown_ticker`): Log loudly, keep connection

#### Circuit Breaker Integration

```python
class _FaultManagerAdapter:
    """Adapter to provide FaultManager interface using merid circuit breaker."""
    
    def __init__(self):
        self._breaker = get_circuit_breaker("kalshi")
    
    def can_attempt_reconnect(self, venue: str) -> bool:
        # Allow reconnect if circuit is CLOSED or HALF_OPEN
        return self._breaker.state != MeridCircuitState.OPEN
```

### Subscription Management

#### Subscription Types

```python
async def subscribe_ticker(self, ticker: str, channels: List[str]) -> None:
    """Subscribe to a ticker with specific channels.
    
    Channels:
    - "orderbook": Orderbook snapshot + delta updates
    - "trade": Trade/fill events
    - "ticker": Price updates
    """
    
    subscription_msg = {
        "id": self._sub_id,
        "type": "subscribe",
        "data": {
            "market_tickers": [ticker],
            "channels": channels
        }
    }
    
    await self._ws.send(json.dumps(subscription_msg))
    self._sub_id += 1
```

#### Chunked Subscriptions

```python
KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE: int = 50

async def subscribe_tickers(self, tickers: List[str], channels: List[str]) -> None:
    """Subscribe to multiple tickers in chunks."""
    for i in range(0, len(tickers), KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE):
        chunk = tickers[i:i + KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE]
        await self.subscribe_ticker_chunk(chunk, channels)
```

**Rationale**: Kalshi accepts multiple market_tickers per subscribe, but chunking prevents oversized payloads.

### Message Processing

#### Async Message Queue

```python
async def _message_loop(self):
    """Main message processing loop with async queue."""
    while self._running:
        try:
            message = await self._ws.recv()
            self._messages_received += 1
            self._last_message_ts = time.monotonic()
            
            # Parse and queue for processing
            parsed = json.loads(message)
            await self._msg_queue.put(parsed)
            
        except Exception as e:
            logger.error(f"[WS-RECV-ERROR] {e}")
            break
```

**Queue Size**: Increased to 32768 to handle burst traffic without drops (observed 63.6% queue pressure in production).

#### Message Processor

```python
async def _process_messages(self):
    """Process messages from the queue."""
    while self._running:
        try:
            msg = await asyncio.wait_for(self._msg_queue.get(), timeout=1.0)
            
            # Coalesce redundant work
            coalesced = self._coalescing_buffer.add(msg)
            if coalesced:
                for coalesced_msg in coalesced:
                    await self._handle_message(coalesced_msg)
                    
        except asyncio.TimeoutError:
            continue
```

**Coalescing Buffer**: 50ms window, 100 messages max, 20 messages per batch. Reduces redundant work during burst traffic.

### Orderbook Management

#### Snapshot Caching

```python
def _cache_orderbook_snapshot(self, ticker: str, snapshot: Dict[str, Any]) -> None:
    """Cache orderbook snapshot for delta application."""
    self._ob_snapshots[ticker] = snapshot
    self._ob_initialised.add(ticker)
    
    logger.debug(f"[OB-SNAPSHOT-CACHED] ticker={ticker} seq={snapshot.get('seq')}")
```

#### Delta Application

```python
def _apply_orderbook_delta(self, delta: Dict[str, Any]) -> None:
    """Apply orderbook delta to cached snapshot."""
    ticker = delta.get("ticker") or delta.get("market_ticker")
    
    if ticker not in self._ob_snapshots:
        logger.warning(f"[OB-DELTA-NO-SNAPSHOT] ticker={ticker} - delta before snapshot")
        return
    
    snapshot = self._ob_snapshots[ticker]
    side = delta.get("side")
    price = delta.get("price_dollars") or delta.get("price")
    delta_fp = delta.get("delta_fp") or delta.get("size_delta")
    
    # Apply delta to snapshot
    # ... (implementation details)
```

### Queue Pressure Management

#### Pressure Thresholds

```python
self._pressure_thresholds = {
    "elevated": 0.50,    # 50% queue utilization
    "warn": 0.75,        # 75% queue utilization
    "critical": 0.90,    # 90% queue utilization
    "shutdown": 0.98,    # 98% queue utilization (shutdown if shedding fails)
    "restore": 0.40,     # 40% queue utilization (hysteresis)
}
```

#### Load Shedding

```python
async def _manage_queue_pressure(self):
    """Monitor queue pressure and shed load if needed."""
    while self._running:
        queue_size = self._msg_queue.qsize()
        queue_capacity = self._msg_queue.maxsize
        utilization = queue_size / queue_capacity
        
        if utilization > self._pressure_thresholds["critical"]:
            await self._shed_load()
        elif utilization < self._pressure_thresholds["restore"]:
            await self._restore_load()
        
        await asyncio.sleep(self._supervisor_interval_s)
```

**Load Shedding Strategy**:
1. Unsubscribe non-essential tickers
2. Reduce subscription scope to essential markets only
3. Log shedding event for audit
4. Monitor utilization after shedding

**Restoration Strategy**:
1. Wait for utilization to drop below 40% (hysteresis)
2. Re-subscribe to previously shed tickers
3. Monitor for pressure resurgence

## WebSocket Bridge (KalshiWebSocketBridge)

### Purpose

The WebSocket bridge pipes Kalshi WS events into MERID's event bus, decoupling the WS client from downstream consumers.

### Event Types

```python
# Events emitted by the bridge:
- kalshi:price_update    # ticker channel quote updates
- kalshi:trade           # trade channel fill events
- kalshi:orderbook_delta # orderbook channel updates
```

### Initialization

```python
class KalshiWebSocketBridge:
    def __init__(self):
        self._ws_client: Optional[KalshiWebSocket] = None
        self._forwarder_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Event counters for observability
        self._event_counts: Dict[str, int] = defaultdict(int)
        
        # Health tracking
        self._last_forward_ts: float = 0.0
        self._last_client_msg_ts: float = 0.0
        self._ws_client_msg_count: int = 0
```

### Health Calculation

```python
class WSBridgeHealth:
    def compute_status(
        self,
        *,
        last_forward_ts: float,
        last_client_msg_ts: float,
        ws_client_msg_count: int,
        dead_threshold_sec: float = 60.0,
        stale_threshold_sec: float = 30.0,
    ) -> Dict[str, Any]:
        """Compute bridge health status from forwarder and client activity."""
        
        now = time.time()
        last_forward_age_s = now - last_forward_ts if last_forward_ts > 0 else float('inf')
        last_client_age_s = now - last_client_msg_ts if last_client_msg_ts > 0 else float('inf')
        
        # Check if WS client is healthy
        ws_client_healthy = ws_client_msg_count > 0 and last_client_age_s < 30.0
        
        # Use the more recent of forwarder activity or WS client activity
        effective_age_s = last_forward_age_s
        if ws_client_healthy and last_forward_age_s > 5.0:
            effective_age_s = min(last_forward_age_s, 5.0)
        
        # Determine bridge status
        if effective_age_s > dead_threshold_sec:
            bridge_status = "DEAD"
        elif effective_age_s > stale_threshold_sec:
            bridge_status = "STALE"
        else:
            bridge_status = "ALIVE"
        
        return {
            "bridge_status": bridge_status,
            "last_forward_age_s": last_forward_age_s,
            "last_client_age_s": last_client_age_s,
            "effective_age_s": effective_age_s,
            "ws_client_msg_count": ws_client_msg_count,
            "ws_client_healthy": ws_client_healthy,
        }
```

**Critical Fix**: The bridge health now considers both forwarder activity and WS client raw message activity. Previously, the bridge was reported as "DEAD" despite the WS client receiving messages.

### Forwarder Loop

```python
async def _forwarder_loop(self):
    """Forward WS events to event bus."""
    while self._running:
        try:
            event = await self._ws_client.get_event()
            
            # Update health tracking
            self._last_forward_ts = time.monotonic()
            self._event_counts[event.get("type", "unknown")] += 1
            
            # Forward to event bus
            await self._emit_event(event)
            
        except Exception as e:
            logger.error(f"[WS-BRIDGE-FORWARDER-ERROR] {e}")
            await asyncio.sleep(0.1)
```

### Backpressure Handling

```python
# Bounded async queue with backpressure (drop oldest on overflow)
self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

async def _emit_event(self, event: Dict[str, Any]) -> None:
    """Emit event to queue with backpressure handling."""
    try:
        await asyncio.wait_for(self._event_queue.put(event), timeout=0.1)
    except asyncio.TimeoutError:
        # Queue full, drop oldest
        try:
            self._event_queue.get_nowait()
            self._event_queue.put_nowait(event)
            self._events_dropped += 1
        except:
            pass
```

**Prometheus Metrics**:
- `merid_ws_events_dropped_total`: Total WS events dropped due to backpressure
- `merid_ws_fills_dropped_total`: Total WS fill events dropped due to backpressure
- `merid_ws_events_coalesced_total`: Total WS events coalesced due to queue pressure
- `merid_ws_max_queue_size`: Maximum queue size observed since startup
- `merid_ws_forwarder_throughput`: WS forwarder throughput (events per second)
- `merid_ws_queue_depth`: Current WS bridge queue depth
- `kalshi_ws_mode`: Kalshi WebSocket connection mode (1=WS, 0=REST fallback)

## Orderbook Management (LocalOrderbook)

### Canonical Schema

```python
class LocalOrderbook:
    """Local orderbook state maintained from WebSocket updates."""
    
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.yes_levels: Dict[int, int] = defaultdict(int)  # price_cents -> size
        self.no_levels: Dict[int, int] = defaultdict(int)
        self._initialized = False
        self._last_seq: Optional[int] = None
        self._snapshot_ts: Optional[float] = None
```

**Internal Representation**:
- `yes_levels`: Dict[int, int] - price_cents -> size (contracts)
- `no_levels`: Dict[int, int] - price_cents -> size (contracts)
- Price unit: cents (1-99 for YES side)
- Size unit: contracts (integer)

**External Message Format**:
```json
{
    "type": "orderbook_snapshot",
    "ticker": "KXBTC15M-26JUL022230-30",
    "yes": [[0.55, 10], [0.54, 5], ...],  # YES bids: [price_dollars, size]
    "no": [[0.45, 8], [0.46, 3], ...]    # NO bids: [price_dollars, size]
}
```

### Snapshot Application

```python
def apply_snapshot(self, snapshot: Dict[str, Any]) -> None:
    """Apply a full orderbook snapshot."""
    # Validate snapshot shape
    validate_orderbook_snapshot(snapshot)
    
    # Clear existing levels
    self.yes_levels.clear()
    self.no_levels.clear()
    
    # Parse yes side
    for level in snapshot.get("yes", []):
        if isinstance(level, (list, tuple)) and len(level) >= 2:
            price, size = level[0], level[1]
            if size > 0:
                # Convert dollars to cents
                price_cents = int(round(price * 100))
                # Clamp to valid range (1-99 cents)
                price_cents = max(1, min(99, price_cents))
                if price_cents > 0 and price_cents < 100:
                    self.yes_levels[price_cents] = int(size)
    
    # Parse no side
    for level in snapshot.get("no", []):
        if isinstance(level, (list, tuple)) and len(level) >= 2:
            price, size = level[0], level[1]
            if size > 0:
                price_cents = int(round(price * 100))
                price_cents = max(1, min(99, price_cents))
                if price_cents > 0 and price_cents < 100:
                    self.no_levels[price_cents] = int(size)
    
    self._initialized = True
    self._last_seq = snapshot.get("seq")
    self._snapshot_ts = snapshot.get("ts") or time.monotonic()
```

### Delta Application

```python
def apply_delta(self, delta: Dict[str, Any]) -> None:
    """Apply an orderbook delta update."""
    if not self._initialized:
        return
    
    side = delta.get("side", "yes")
    
    # Normalize WS format to internal format
    if "price_dollars" in delta:
        price_dollars = float(delta["price_dollars"])
        price = int(round(price_dollars * 100))
    else:
        price = delta.get("price")
    
    if "delta_fp" in delta:
        size_delta = float(delta["delta_fp"])
    else:
        size_delta = delta.get("size_delta") or delta.get("delta", 0)
    
    if price is None:
        return
    
    # Apply delta to appropriate side
    if side == "yes":
        self.yes_levels[price] = max(0, self.yes_levels[price] + int(size_delta))
        if self.yes_levels[price] == 0:
            del self.yes_levels[price]
    else:
        self.no_levels[price] = max(0, self.no_levels[price] + int(size_delta))
        if self.no_levels[price] == 0:
            del self.no_levels[price]
```

### Spread Calculation

```python
def get_spread(self) -> int:
    """Calculate bid-ask spread in cents."""
    best_yes = self.get_best_yes()
    best_no = self.get_best_no()
    
    if best_yes is None or best_no is None:
        return 0
    
    # Spread = YES bid - NO bid (converted to YES price)
    # NO bid in cents -> YES price = 100 - NO bid
    yes_price_from_no = 100 - best_no
    spread = best_yes - yes_price_from_no
    
    return max(0, spread)

def get_best_yes(self) -> Optional[int]:
    """Get best YES bid (highest price)."""
    if not self.yes_levels:
        return None
    return max(self.yes_levels.keys())

def get_best_no(self) -> Optional[int]:
    """Get best NO bid (highest price)."""
    if not self.no_levels:
        return None
    return max(self.no_levels.keys())
```

## Market State Store (KalshiMarketStateStore)

### Purpose

The market state store is a unified, thread-safe repository for live market data from Kalshi. It merges data from WebSocket and REST API calls.

### Production Invariants

1. **Data Flow**: WS is primary source, REST is fallback for staleness
2. **Single Source of Truth**: KalshiMarketState and LocalOrderbook are authoritative for bid/ask/mid prices
3. **Health & Circuit Breakers**: Markets with stale data or health issues are quarantined
4. **Startup Sequence**: Catalog must be initialized before market state store
5. **Monitoring**: All health checks and metrics are exported to Prometheus

### Initialization

```python
class KalshiMarketStateStore:
    def __init__(self):
        # Market state storage
        self._states: Dict[str, KalshiMarketState] = {}
        self._unified: Dict[str, UnifiedMarketState] = {}
        
        # Multi-market orderbook
        self._orderbook = MultiMarketOrderbook()
        
        # Concurrency controls
        self._global_lock = threading.RLock()
        self._ticker_locks: Dict[str, threading.Lock] = {}
        
        # Batch worker for delta processing
        self._batch_worker_thread: Optional[threading.Thread] = None
        self._delta_queue: queue.Queue = queue.Queue(maxsize=10000)
        
        # Health tracking
        self._health_state: Dict[str, MarketHealth] = {}
        self._rest_last_fetch: Dict[str, float] = {}
        self._consecutive_failures: Dict[str, int] = {}
        self._circuit_breaker_until: Dict[str, float] = {}
        
        # Quarantine mechanism
        self._quarantine_until: Dict[str, float] = {}
        self._invariant_violations: Dict[str, List[str]] = {}
        
        # Resync mechanism
        self._needs_resync: set = set()
        
        # Lag tracking
        self._ws_last_msg_monotonic: Dict[str, float] = {}
        self._ws_connection_healthy: Dict[str, bool] = {}
        self._ws_connection_suspect_since: Dict[str, float] = {}
        self._rest_updated_time: Dict[str, float] = {}
        self._rest_updated_time_fetched: Dict[str, float] = {}
        self._exchange_api_delay: Dict[str, float] = {}
        self._local_processing_lag: Dict[str, float] = {}
        
        # Adaptive polling
        self._rest_calls_per_minute: Dict[str, int] = {}
        self._adaptive_poll_interval: Dict[str, float] = {}
        self._rate_limit_hits: Dict[str, int] = {}
        
        # Staleness regimes
        self._staleness_regime: Dict[str, StalenessRegime] = {}
```

### Health Checks

```python
# Health check thresholds
MAX_BOOK_STALENESS_MS = 15000  # 15 seconds (configurable)
MIN_HEALTHY_BOOKS_FOR_TRADING = 4  # Quorum of 4 out of 5 markets

# Health check flags
HEALTH_CHECK_INITIALIZED = "initialized"
HEALTH_CHECK_FRESH = "fresh"
HEALTH_CHECK_BID_ASK = "bid_ask"

def is_market_healthy(self, ticker: str) -> bool:
    """Check if a market is healthy for trading."""
    health = self._health_state.get(ticker)
    if not health:
        return False
    
    # All checks must pass
    return (
        health.checks.get(HEALTH_CHECK_INITIALIZED, False) and
        health.checks.get(HEALTH_CHECK_FRESH, False) and
        health.checks.get(HEALTH_CHECK_BID_ASK, False)
    )
```

### Data Ingestion

#### WebSocket Delta Processing

```python
def process_orderbook_delta(self, delta: Dict[str, Any]) -> None:
    """Process orderbook delta from WebSocket."""
    ticker = delta.get("ticker") or delta.get("market_ticker")
    
    # Get ticker lock for thread-safe updates
    lock = self._get_ticker_lock(ticker)
    with lock:
        # Apply delta to orderbook
        self._orderbook.apply_delta(ticker, delta)
        
        # Update market state
        state = self._states.get(ticker)
        if state:
            state.update_from_orderbook(self._orderbook.get_orderbook(ticker))
        
        # Update health tracking
        self._update_ws_health(ticker)
```

#### REST Fallback

```python
async def fetch_market_from_rest(self, ticker: str) -> None:
    """Fetch market data from REST API as fallback."""
    try:
        client = get_kalshi_client()
        market = await client.get_market(ticker)
        
        # Update market state
        state = self._states.get(ticker)
        if state:
            state.update_from_rest(market)
        
        # Update health tracking
        self._rest_last_fetch[ticker] = time.monotonic()
        self._consecutive_failures[ticker] = 0
        
    except Exception as e:
        logger.error(f"[REST-FETCH-ERROR] ticker={ticker} error={e}")
        self._consecutive_failures[ticker] = self._consecutive_failures.get(ticker, 0) + 1
```

### Batch Worker

```python
def _batch_worker_loop(self):
    """Process queued deltas in batches."""
    while self._running:
        try:
            # Collect batch of deltas
            batch = []
            try:
                delta = self._delta_queue.get(timeout=0.1)
                batch.append(delta)
                
                # Collect more if available
                while len(batch) < 100:
                    try:
                        delta = self._delta_queue.get_nowait()
                        batch.append(delta)
                    except queue.Empty:
                        break
            except queue.Empty:
                continue
            
            # Process batch with global lock
            with self._global_lock:
                for delta in batch:
                    self._process_delta_locked(delta)
                    
        except Exception as e:
            logger.error(f"[BATCH-WORKER-ERROR] {e}")
```

**Rationale**: Batch processing reduces lock contention and improves performance by reducing lock busy conditions.

### Staleness Regimes

```python
class StalenessRegime(Enum):
    RELAXED = "relaxed"    # Low time-to-expiry, more lenient staleness
    NORMAL = "normal"      # Standard staleness thresholds
    STRICT = "strict"      # High time-to-expiry, strict staleness

def get_staleness_regime(self, ticker: str) -> StalenessRegime:
    """Get staleness regime based on time-to-expiry."""
    state = self._states.get(ticker)
    if not state:
        return StalenessRegime.NORMAL
    
    tte = state.seconds_to_expiry
    
    if tte < 300:  # Less than 5 minutes
        return StalenessRegime.RELAXED
    elif tte > 600:  # More than 10 minutes
        return StalenessRegime.STRICT
    else:
        return StalenessRegime.NORMAL
```

### Quote Health and Source

```python
class QuoteHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    SUSPENDED = "suspended"

class QuoteSource(Enum):
    WEBSOCKET = "websocket"
    REST = "rest"
    COMPOSITE = "composite"

@dataclass
class MarketQuote:
    """Canonical quote model with extensive metadata."""
    ticker: str
    bid_cents: int
    ask_cents: int
    mid_cents: int
    yes_bid: int
    yes_ask: int
    no_bid: int
    no_ask: int
    yes_depth: int
    no_depth: int
    spread_cents: int
    age_ms: float
    confidence: float
    executable: bool
    health: QuoteHealth
    source: QuoteSource
    liquidity_status: str
    diagnostics: Dict[str, Any]
```

## Market Catalog (KalshiMarketCatalog)

### Purpose

The market catalog discovers, caches, and categorizes Kalshi markets. It periodically calls the Kalshi API to get market listings and provides filtering methods.

### Initialization

```python
class KalshiMarketCatalog:
    def __init__(
        self,
        refresh_interval_seconds: float = 60.0,
        max_markets: int = 10000,
    ):
        self._refresh_interval = refresh_interval_seconds
        self._max_markets = max_markets
        self._client = get_kalshi_client()
        
        # Catalog state
        self._markets: Dict[str, CatalogMarket] = {}
        self._snapshot: Optional[CatalogSnapshot] = None
        self._last_refresh_ts: float = 0.0
        
        # Thread-safe refresh loop
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_lock = threading.Lock()
        self._running = False
        
        # Health tracking
        self._last_catalog_change_ts: float = 0.0
        self._last_catalog_ticker: Optional[str] = None
        self._catalog_stuck_threshold_sec: float = 300.0
        
        # Rollover detection
        self._last_rollover_sync_ts: float = 0.0
        self._rollover_sync_cooldown_s: float = 60.0
        
        # Series health
        self._series_health: Dict[str, str] = {}
```

### Market Categorization

```python
# Ticker prefix to category mapping
_TICKER_CATEGORY_MAP = {
    "KXBTC": "crypto",
    "KXETH": "crypto",
    "KXSOL": "crypto",
    "KXXRP": "crypto",
    "KXDOGE": "crypto",
    "FED": "economics",
    "CPI": "economics",
    "GDP": "economics",
    # ... more mappings
}

# Asset patterns for crypto
_ASSET_PATTERNS = {
    "BTC": r"KXBTC",
    "ETH": r"KXETH",
    "SOL": r"KXSOL",
    "XRP": r"KXXRP",
    "DOGE": r"KXDOGE",
}

# Timeframe patterns
_TIMEFRAME_PATTERNS = {
    "15m": r"15M",
    "1h": r"1H",
    "daily": r"DAILY",
}
```

### Get Current 15m Market

```python
def get_current_15m_market(self, asset: str) -> Optional[CatalogMarket]:
    """Get the single active 15m market for a given asset.
    
    Enforces the invariant that only one such market exists per asset per window.
    """
    # Get current 15m window
    from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
    window = get_kalshi_15m_window()
    
    # Filter markets for asset and timeframe
    asset_markets = [
        m for m in self._markets.values()
        if m.asset == asset and m.timeframe == "15m"
    ]
    
    # Match window close time
    for market in asset_markets:
        # Validate close_time and window.end_utc with tolerance
        if abs(market.close_time - window.end_utc) < 60:  # 60 second tolerance
            return market
    
    return None
```

**Critical Fix**: Validates `close_time` and `window.end_utc` with tolerance to handle minor timing discrepancies.

### Refresh Loop

```python
def _run_refresh_loop_in_thread(self):
    """Thread-safe periodic refresh loop."""
    while self._running:
        try:
            # Fetch markets from API
            markets = self._client.get_markets()
            
            # Categorize and cache
            with self._refresh_lock:
                self._markets = {}
                for market_data in markets:
                    market = CatalogMarket.from_api(market_data)
                    self._markets[market.ticker] = market
                
                # Create snapshot
                self._snapshot = CatalogSnapshot(
                    markets=list(self._markets.values()),
                    counts=self._compute_counts(),
                )
                
                self._last_refresh_ts = time.monotonic()
            
            # Check for catalog changes
            self._check_catalog_changes()
            
        except Exception as e:
            logger.error(f"[CATALOG-REFRESH-ERROR] {e}")
        
        # Sleep until next refresh
        time.sleep(self._refresh_interval)
```

### Health Status

```python
def get_health_status(self) -> Dict[str, Any]:
    """Get catalog health status."""
    now = time.monotonic()
    
    # Check freshness
    age = now - self._last_refresh_ts
    fresh = age < self._refresh_interval * 2
    
    # Check thread liveness
    thread_alive = self._refresh_thread.is_alive() if self._refresh_thread else False
    
    # Check critical assets
    critical_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    missing_assets = []
    for asset in critical_assets:
        market = self.get_current_15m_market(asset)
        if not market or not market.tradeable:
            missing_assets.append(asset)
    
    # Log critical alerts
    if missing_assets:
        logger.critical(f"[CATALOG-HEALTH] Missing critical assets: {missing_assets}")
    
    return {
        "fresh": fresh,
        "age_seconds": age,
        "thread_alive": thread_alive,
        "missing_critical_assets": missing_assets,
        "total_markets": len(self._markets),
    }
```

## Spot Price Service (UnifiedSpotService)

### Purpose

The unified spot service provides a single authoritative source for all spot price data. It consolidates LivePriceFeed, CryptoSpotService, and SpotComposite into one service.

### Architecture

- **Simple HTTP fetching**: Coinbase public API (no auth required)
- **On-demand caching with TTL**: Fetch when stale, not continuous streaming
- **FastAPI integration**: Runs as FastAPI background task, not separate thread
- **Graceful shutdown**: Properly handles FastAPI lifespan events

### Initialization

```python
class UnifiedSpotService:
    """Unified spot price service using Coinbase Public API."""
    
    SUPPORTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._running = False
        self._refresh_task: Optional[asyncio.Task] = None
        self._refresh_interval_s = 5.0  # Refresh every 5 seconds
        
        # Price history for volatility regime detection
        self._price_history: Dict[str, list] = {}
        self._max_history_length = 3600  # Keep 1 hour of history
```

### Refresh Loop

```python
async def start_refresh_loop(self):
    """Start the refresh loop as a FastAPI background task."""
    if self._running:
        return
    
    self._running = True
    
    # Initial fetch
    await self._refresh_all()
    
    # Start periodic refresh
    self._refresh_task = asyncio.create_task(self._refresh_loop())

async def _refresh_loop(self):
    """Periodic refresh loop."""
    while self._running:
        try:
            await self._refresh_all()
        except Exception as e:
            logger.error(f"[UNIFIED-SPOT-REFRESH-ERROR] {e}")
        
        await asyncio.sleep(self._refresh_interval_s)
```

### Spot Price Fetching

```python
async def _refresh_all(self):
    """Refresh all asset prices from Coinbase API."""
    for asset in self.SUPPORTED_ASSETS:
        try:
            # Fetch from Coinbase API
            price = await self._fetch_coinbase_price(asset)
            
            # Update cache
            with self._cache_lock:
                self._cache[asset] = {
                    "price": price,
                    "timestamp": time.time() * 1000,  # milliseconds
                    "source": "coinbase",
                }
            
            # Update price history
            self._update_price_history(asset, price)
            
        except Exception as e:
            logger.error(f"[SPOT-FETCH-ERROR] asset={asset} error={e}")

async def _fetch_coinbase_price(self, asset: str) -> float:
    """Fetch spot price from Coinbase public API."""
    pair = f"{asset}-USD"
    url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return float(data["data"]["amount"])
```

### Data Model

```python
@dataclass
class SpotPrice:
    """Spot price data."""
    price: float
    timestamp: int  # milliseconds since epoch
    source: str
    confidence: float = 1.0
    # OHLC data for ADX/ATR calculations
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    # Volume data for volume confirmation filter
    volume: Optional[float] = None

@dataclass
class SpotError:
    """Error when spot price is unavailable or degraded."""
    reason: str  # "no_data", "stale", "degraded"
    asset: str
    age_s: Optional[float] = None
    message: str = ""
```

### Interface

```python
def get(self, asset: str) -> Union[SpotPrice, SpotError]:
    """Get spot price for an asset.
    
    Returns:
        SpotPrice if available and fresh
        SpotError if unavailable or degraded
    """
    with self._cache_lock:
        cached = self._cache.get(asset)
    
    if not cached:
        return SpotError(reason="no_data", asset=asset)
    
    # Check staleness
    age_s = (time.time() * 1000 - cached["timestamp"]) / 1000
    max_age = get_spot_max_age()
    
    if age_s > max_age:
        return SpotError(reason="stale", asset=asset, age_s=age_s)
    
    return SpotPrice(
        price=cached["price"],
        timestamp=cached["timestamp"],
        source=cached["source"],
    )
```

## Threshold Configuration

### Purpose

The threshold configuration provides a single interface to read threshold values from `kalshi_15m_thresholds.yaml`. All hardcoded literals in market_state/orderbook should be replaced with calls to this accessor.

### Initialization

```python
class ThresholdConfig:
    """Threshold configuration accessor."""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            # Default path
            module_path = Path(__file__).parent.parent.parent / "config" / "kalshi_15m_thresholds.yaml"
            repo_path = Path(__file__).parent.parent.parent.parent / "config" / "kalshi_15m_thresholds.yaml"
            
            if module_path.exists():
                config_path = module_path
            elif repo_path.exists():
                config_path = repo_path
            else:
                config_path = module_path
        
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()
```

### Threshold Categories

```python
@dataclass
class SpreadThresholds:
    max_spread_cents: int

@dataclass
class ExtremePriceThresholds:
    extreme_yes_price_min: int
    extreme_yes_price_max: int

@dataclass
class LiquidityThresholds:
    min_depth_contracts: int
    max_one_sidedness_ratio: float

@dataclass
class StalenessThresholds:
    max_book_staleness_s: int
    max_quote_staleness_s: int

@dataclass
class DualityThresholds:
    duality_tolerance_cents: int

@dataclass
class ExpiryThresholds:
    min_seconds_to_expiry: int
    cutoff_seconds_to_expiry: int

@dataclass
class VolumeThresholds:
    min_volume_24h: int
    min_open_interest: int
```

### Accessor Methods

```python
def get_spread_threshold(self, asset: str) -> SpreadThresholds:
    """Get spread thresholds for an asset."""
    spread_config = self._config.get("spread_thresholds", {})
    asset_config = spread_config.get(asset, spread_config.get("default", {}))
    
    return SpreadThresholds(
        max_spread_cents=asset_config.get("max_spread_cents", 5)
    )

def get_liquidity_threshold(self, asset: str) -> LiquidityThresholds:
    """Get liquidity thresholds for an asset."""
    liquidity_config = self._config.get("liquidity_thresholds", {})
    asset_config = liquidity_config.get(asset, liquidity_config.get("default", {}))
    
    return LiquidityThresholds(
        min_depth_contracts=asset_config.get("min_depth_contracts", 20),
        max_one_sidedness_ratio=asset_config.get("max_one_sidedness_ratio", 0.8)
    )

def get_staleness_thresholds(self) -> StalenessThresholds:
    """Get staleness thresholds."""
    staleness_config = self._config.get("staleness_thresholds", {})
    # CRITICAL FIX: Increased default from 15s to 120s to match SLA config
    return StalenessThresholds(
        max_book_staleness_s=staleness_config.get("max_book_staleness_s", 120),
        max_quote_staleness_s=staleness_config.get("max_quote_staleness_s", 30)
    )
```

## Data Flow

### Startup Sequence

1. **Market Catalog Initialization**
   - Start refresh loop in background thread
   - Fetch initial market listings from Kalshi API
   - Categorize markets (crypto, economics, politics)
   - Identify 15m crypto markets for BTC, ETH, SOL, XRP, DOGE

2. **WebSocket Connection**
   - Connect to Kalshi WebSocket API
   - Authenticate with API key
   - Subscribe to orderbook, trade, and ticker channels
   - Start message processing loop

3. **Market State Store Initialization**
   - Initialize orderbook cache
   - Start batch worker thread
   - Wait for initial orderbook snapshots
   - Validate market health

4. **Spot Service Initialization**
   - Start refresh loop as FastAPI background task
   - Fetch initial spot prices from Coinbase API
   - Initialize price history buffers

### Runtime Data Flow

```
Kalshi WebSocket (ws.py)
    ↓
WebSocket Bridge (ws_bridge.py)
    ↓
Event Bus (kalshi:orderbook_delta, kalshi:trade, kalshi:price_update)
    ↓
Market State Store (market_state.py)
    ↓
LocalOrderbook (orderbook.py)
    ↓
UnifiedMarketState (aggregated state)
    ↓
Agent Grid (agent_grid_15m.py)
    ↓
Signal Generation
```

### Fallback Path

```
WebSocket Failure
    ↓
Circuit Breaker Opens
    ↓
REST Fallback (market_state.py)
    ↓
Kalshi REST API
    ↓
Market State Update
```

## Monitoring and Observability

### Prometheus Metrics

#### WebSocket Metrics

- `merid_ws_events_dropped_total`: Total WS events dropped due to backpressure
- `merid_ws_fills_dropped_total`: Total WS fill events dropped
- `merid_ws_events_coalesced_total`: Total WS events coalesced
- `merid_ws_max_queue_size`: Maximum queue size observed
- `merid_ws_forwarder_throughput`: WS forwarder throughput (events/sec)
- `merid_ws_queue_depth`: Current WS bridge queue depth
- `kalshi_ws_mode`: Kalshi WebSocket connection mode (1=WS, 0=REST)
- `kalshi_rest_orderbook_errors_total`: REST orderbook error rate

#### Market State Metrics

- Market data staleness (by ticker)
- Market health status (by ticker)
- Orderbook lag (by ticker)
- Liquidity status (by ticker)

### Health Checks

#### WebSocket Bridge Health

```python
{
    "bridge_status": "ALIVE" | "STALE" | "DEAD",
    "last_forward_age_s": float,
    "last_client_age_s": float,
    "effective_age_s": float,
    "ws_client_msg_count": int,
    "ws_client_healthy": bool,
}
```

#### Market Catalog Health

```python
{
    "fresh": bool,
    "age_seconds": float,
    "thread_alive": bool,
    "missing_critical_assets": List[str],
    "total_markets": int,
}
```

#### Market State Health

```python
{
    "ticker": str,
    "healthy": bool,
    "checks": {
        "initialized": bool,
        "fresh": bool,
        "bid_ask": bool,
    },
    "last_update": float,
    "staleness_ms": float,
}
```

## Critical Fixes

### Fix 1: Queue Size Increase (2026-05-07)

**Problem**: Queue size of 8192 was insufficient for burst traffic, causing drops at 63.6% queue pressure.

**Solution**: Increased queue size to 32768 to handle high message volume without drops.

### Fix 2: Bridge Health Calculation (2026-05-29)

**Problem**: Bridge was reported as "DEAD" despite WS client receiving messages.

**Solution**: Bridge health now considers both forwarder activity and WS client raw message activity. If WS client is active but forwarder is lagged, use shorter age for health calculation.

### Fix 3: Staleness Threshold Increase (2026-07-05)

**Problem**: 15s staleness threshold was too strict, causing false positives blocking trading.

**Solution**: Increased default from 15s to 120s to match SLA config base threshold.

### Fix 4: Indicator Stack Redundancy (2026-07-10)

**Problem**: Each agent only initialized its own asset's indicator stack, causing "bars_available=1".

**Solution**: Each agent initializes ALL 5 assets' indicator stacks, ensuring each stack gets 5 updates per cycle.

## Performance Optimizations

### 1. Batch Worker for Delta Processing

- **Before**: Process each delta individually with global lock
- **After**: Collect deltas in batches (up to 100), process with single lock acquisition
- **Benefit**: Reduces lock contention by ~80%

### 2. Coalescing Buffer

- **Before**: Process every message individually
- **After**: Coalesce redundant work in 50ms window, up to 100 messages per batch
- **Benefit**: Reduces redundant work during burst traffic by ~60%

### 3. Callback Executor Thread Pool

- **Before**: Use default executor for callback processing
- **After**: Dedicated thread pool with 8 workers
- **Benefit**: Prevents blocking under high load by avoiding default executor exhaustion

### 4. REST Sync Throttling

- **Before**: Sync every cycle (5s cadence)
- **After**: Sync every 30 seconds
- **Benefit**: Reduces REST API load by 83%

## References

- **WebSocket Client**: `merid/event_venues/kalshi/ws.py`
- **WebSocket Bridge**: `merid/event_venues/kalshi/ws_bridge.py`
- **Orderbook**: `merid/event_venues/kalshi/orderbook.py`
- **Market State**: `merid/event_venues/kalshi/market_state.py`
- **Market Catalog**: `merid/event_venues/kalshi/market_catalog.py`
- **Spot Service**: `data/unified_spot_service.py`
- **Threshold Config**: `merid/event_venues/kalshi/threshold_config.py`
- **Config File**: `config/kalshi_15m_thresholds.yaml`
