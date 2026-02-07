# Low-Latency Market Data Architecture

## Overview

MERID now supports ultra-low latency market data consumption from multiple sources:
- **UDP Multicast Feeds**: Direct exchange multicast (ITCH, SOUPBIN, OPRA)
- **FIX Market Data**: Institutional FIX protocol with sequence numbers and recovery
- **Persistent Order Books**: LMAX-style architecture with journaling and snapshots
- **WebSocket/REST Fallback**: Standard exchange APIs for development and testing

## Architecture Components

### 1. UDP Multicast Feed Handler (`execution/multicast_feed.py`)

**Purpose**: Consume exchange multicast feeds with minimal latency

**Features**:
- Direct UDP multicast group joining
- ITCH protocol parsing (NASDAQ, NYSE, etc.)
- SOUPBIN protocol support
- Sequence number tracking and gap detection
- Real-time order book building
- Zero-copy message processing

**Configuration**:
```python
from execution.multicast_feed import create_itch_config, get_multicast_feed_manager

# ITCH multicast configuration
itch_config = create_itch_config(
    multicast_group="239.1.1.1",
    port=50000,
    interface="eth0",
    symbols=["AAPL", "MSFT", "GOOG"]
)

# Add to manager
manager = get_multicast_feed_manager()
manager.add_feed("nasdaq_itch", itch_config)
await manager.start_all()
```

**Network Requirements**:
- Multicast-enabled network interface
- Proper routing for 224.0.0.0/4 multicast range
- Tuned UDP receive buffers (`net.core.rmem_max`)
- CPU affinity for feed handler threads

### 2. FIX Market Data Feed (`execution/fix_feed.py`)

**Purpose**: Institutional-grade market data with reliability features

**Features**:
- FIX 4.2 protocol support
- MarketDataSnapshotFullRefresh (35=W)
- MarketDataIncrementalRefresh (35=X)
- Sequence number validation
- Automatic reconnection and recovery
- Heartbeat monitoring
- Session management

**Configuration**:
```python
from execution.fix_feed import create_fix_config, get_fix_feed_manager

# FIX configuration
fix_config = create_fix_config(
    host="fix.exchange.com",
    port=5001,
    sender_comp_id="MERID",
    target_comp_id="EXCHANGE",
    username="merid_user",
    password="secret",
    symbols=["AAPL", "MSFT"]
)

# Add to manager
manager = get_fix_feed_manager()
manager.add_feed("exchange_fix", fix_config)
await manager.start_all()
```

**Message Types**:
- `35=A`: Logon
- `35=0`: Heartbeat
- `35=V`: MarketDataRequest
- `35=W`: MarketDataSnapshotFullRefresh
- `35=X`: MarketDataIncrementalRefresh
- `35=Y`: MarketDataReject

### 3. Persistent Order Books (`execution/persistent_book.py`)

**Purpose**: LMAX-style durable order book storage with fast recovery

**Features**:
- In-memory order book with price-time priority
- Disk journaling of all events
- Periodic snapshots for fast recovery
- SQLite database for historical queries
- Event replay capabilities
- Sequence number tracking

**Architecture**:
```
In-Memory Book + Disk Journal + Periodic Snapshots
```

**Usage**:
```python
from execution.persistent_book import get_persistent_book_manager

# Get order book for symbol
manager = get_persistent_book_manager()
book = manager.get_book("AAPL")

# Start background tasks
book.start()

# Add order
book.add_order("order_123", "buy", 150.25, 100)

# Get best bid/ask
best_bid = book.get_best_bid()
best_ask = book.get_best_ask()
spread = book.get_spread()

# Get snapshot
snapshot = book.get_snapshot()
```

**Recovery Process**:
1. Load latest snapshot from disk
2. Replay journal events since snapshot
3. Apply sequence number validation
4. Resume real-time processing

### 4. Market Data Normalization

All feeds normalize to the same `MarketData` format:

```python
@dataclass
class MarketData:
    symbol: str
    timestamp: float
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    last_price: Optional[float] = None
    last_size: Optional[float] = None
```

## Performance Optimizations

### Network Tuning

**Linux Kernel Parameters**:
```bash
# Increase UDP receive buffers
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.rmem_default=4194304

# Enable multicast routing
route add -net 224.0.0.0 netmask 240.0.0.0 dev eth0

# Disable CPU frequency scaling
cpupower frequency-set -g performance
```

**Application Optimizations**:
- Pre-allocated buffers for message processing
- Lock-free queues for inter-thread communication
- CPU affinity for feed handler threads
- Memory-mapped files for journal I/O
- Zero-copy message parsing

### Latency Measurements

**Target Latencies**:
- UDP Multicast: < 50 microseconds
- FIX Processing: < 100 microseconds
- Order Book Update: < 25 microseconds
- Journal Write: < 10 microseconds

**Monitoring**:
- Message processing latency histograms
- Sequence number gap tracking
- Network packet loss monitoring
- Memory usage tracking

## Integration with MERID

### Unified Feed Interface

All market data sources implement the same interface:

```python
# Subscribe to market data updates
feed.subscribe(market_data_callback)

# Callback receives normalized MarketData
def market_data_callback(data: MarketData):
    # Send to execution simulator
    simulator.update_market_data(data)
```

### Execution Service Integration

The execution service automatically consumes from all active feeds:

```python
# Start execution service with multiple feeds
service = get_execution_service()

# Add multicast feeds
multicast_manager = get_multicast_feed_manager()
multicast_manager.add_feed("nasdaq", itch_config)

# Add FIX feeds
fix_manager = get_fix_feed_manager()
fix_manager.add_feed("nyse", fix_config)

# Start all feeds
await multicast_manager.start_all()
await fix_manager.start_all()

# Start execution service
service.run()
```

## Deployment Scenarios

### 1. Development Environment
- WebSocket/REST feeds from crypto exchanges
- Simple order book without persistence
- No network tuning required

### 2. Staging Environment
- FIX feeds from exchange test systems
- Persistent order books with journaling
- Basic network optimizations

### 3. Production Environment
- UDP multicast feeds for lowest latency
- Full network and kernel tuning
- Persistent order books with snapshots
- Multiple redundant feeds

## Monitoring and Alerting

### Key Metrics

**Feed Health**:
- Message rate per second
- Sequence number gaps
- Connection status
- Latency percentiles

**Order Book Health**:
- Book depth
- Spread statistics
- Update frequency
- Recovery time

**System Health**:
- CPU usage per core
- Memory usage
- Network I/O
- Disk I/O

### Alert Thresholds

**Critical Alerts**:
- Feed connection lost > 30 seconds
- Sequence number gap > 100
- Order book recovery failure
- Latency > 1 second

**Warning Alerts**:
- Message rate drops > 50%
- Latency > 100 milliseconds
- Memory usage > 80%
- Disk space < 10%

## Troubleshooting

### Common Issues

**Multicast Feed Issues**:
- Check network interface configuration
- Verify multicast routing
- Validate UDP buffer settings
- Monitor packet loss

**FIX Feed Issues**:
- Check sequence numbers
- Verify session state
- Monitor heartbeat intervals
- Validate message parsing

**Persistence Issues**:
- Check disk space
- Verify journal integrity
- Monitor snapshot frequency
- Validate database connectivity

### Debug Tools

**Network Debugging**:
```bash
# Monitor multicast traffic
tcpdump -i eth0 -nn -vv udp multicast

# Check socket buffers
ss -u -l -n | grep :50000

# Monitor network statistics
netstat -s | grep -i udp
```

**Application Debugging**:
```python
# Enable debug logging
import logging
logging.getLogger("execution.multicast_feed").setLevel(logging.DEBUG)

# Monitor sequence numbers
for feed_id, feed in manager.feeds.items():
    print(f"{feed_id}: {feed._sequence_numbers}")
```

## Best Practices

### Feed Handler Design
- Single thread per feed for deterministic latency
- Pre-allocate all buffers at startup
- Use lock-free data structures for sharing
- Implement graceful degradation on errors

### Order Book Design
- Keep hot path operations in memory only
- Batch writes to reduce I/O overhead
- Use compression for journal storage
- Implement efficient snapshot format

### Error Handling
- Log all sequence number gaps
- Implement automatic reconnection
- Use circuit breakers for failing feeds
- Provide manual recovery mechanisms

This low-latency market data architecture provides MERID with institutional-grade market data consumption capabilities while maintaining flexibility for different deployment scenarios.
