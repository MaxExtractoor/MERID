# Kalshi Robustness Layer - Usage Guide

## Overview

The Kalshi Robustness Layer provides enterprise-grade reliability features for Kalshi trading operations, including:

- **Automatic Reconnection**: Exponential backoff reconnection with configurable retries
- **Health Monitoring**: Real-time health checks and status reporting
- **Request Deduplication**: Prevents duplicate API calls within a time window
- **Circuit Breaker Integration**: Prevents cascade failures
- **Order Lifecycle Tracking**: Persistent order state management
- **Graceful Degradation**: Fallback values and error recovery

## Quick Start

### Basic Usage

```python
from merid.event_venues.kalshi.robustness_integration import get_robust_kalshi_client
from merid.event_venues.kalshi.models import KalshiConfig

# Create and start robust client
client = get_robust_kalshi_client(
    config=KalshiConfig(
        api_key="your-api-key",
        private_key_path="/path/to/key.pem"
    ),
    max_reconnect_attempts=10,
    health_check_interval=30.0
)

await client.start()

# Use client for trading operations
result = await client.place_order(order)
balance = await client.get_balance()
positions = await client.get_positions()

# Clean shutdown
await client.stop()
```

### Advanced Configuration

```python
from merid.event_venues.kalshi.kalshi_robustness import RobustKalshiClient

client = RobustKalshiClient(
    client_factory=lambda: KalshiVenueClient(config),
    max_reconnect_attempts=10,        # Max reconnection attempts
    reconnect_base_delay=1.0,         # Initial reconnection delay (seconds)
    reconnect_max_delay=60.0,          # Maximum reconnection delay
    health_check_interval=30.0,        # Health check interval (seconds)
)
```

## Architecture

### Components

1. **RobustKalshiClient**: Main wrapper around KalshiVenueClient
   - Manages connection lifecycle
   - Handles automatic reconnection
   - Provides request deduplication
   - Tracks health metrics

2. **OrderLifecycleTracker**: Tracks order state and PnL
   - Records order submissions
   - Processes fill events
   - Calculates realized PnL
   - Maintains order history

3. **KalshiResilienceManager**: Central coordination
   - Manages all robustness components
   - Provides health summaries
   - Coordinates failover logic

## Features

### 1. Automatic Reconnection

When connection failures are detected, the client automatically attempts reconnection with exponential backoff:

```python
# Reconnection delays: 1s, 2s, 4s, 8s, ... up to max_delay
client = get_robust_kalshi_client(
    max_reconnect_attempts=10,
    reconnect_base_delay=1.0,
    reconnect_max_delay=60.0
)
```

### 2. Health Monitoring

Continuous health checks monitor:
- Connection state
- API latency
- Error rates
- Reconnection frequency

```python
# Access health status
health = client.health
print(f"Client healthy: {health.client_healthy}")
print(f"Avg latency: {health.latency_ms_avg}ms")
print(f"Errors (1h): {health.error_count_1h}")
```

### 3. Request Deduplication

Prevents duplicate API calls within a 5-second window for idempotent operations:

```python
# These two calls will only execute once
task1 = client.place_order(order)
task2 = client.place_order(order)  # Same order
results = await asyncio.gather(task1, task2)
# Both results will reference the same API call
```

### 4. Error Recovery

Operations execute with automatic fallback handling:

```python
result = await client.execute_with_robustness(
    operation=some_async_function,
    operation_name="my_operation",
    fallback_value=default_result  # Returned on failure
)
```

### 5. Order Lifecycle Tracking

Track orders from submission through fill:

```python
from merid.event_venues.kalshi.kalshi_robustness import OrderLifecycleTracker

tracker = OrderLifecycleTracker()

# Record order submission
tracker.on_order_submitted("order-123", {
    "ticker": "BTC-USD",
    "side": "buy",
    "size": 10
})

# Process fill events
tracker.on_order_filled("order-123", {
    "price": 55,
    "size": 10,
    "side": "buy"
})

# Check status
status = tracker.get_order_status("order-123")
unfilled = tracker.get_unfilled_orders()
pnl = tracker.get_total_pnl()
```

## Migration Guide

### From KalshiVenueClient

**Before:**
```python
from merid.event_venues.kalshi.client import KalshiVenueClient, KalshiConfig

client = KalshiVenueClient(KalshiConfig())
await client.connect()

# No automatic reconnection, no health monitoring
result = await client.place_order(order)
```

**After:**
```python
from merid.event_venues.kalshi.robustness_integration import get_robust_kalshi_client

client = get_robust_kalshi_client()
await client.start()  # Includes health monitoring

# Automatic reconnection, health monitoring, error recovery
result = await client.place_order(order)
```

### Gradual Migration

Use `upgrade_existing_client` for gradual migration:

```python
from merid.event_venues.kalshi.robustness_integration import upgrade_existing_client

# Wrap existing client
existing_client = KalshiVenueClient(config)
robust_client = upgrade_existing_client(existing_client)

await robust_client.start()
```

## Configuration

### Environment Variables

```bash
# Reconnection settings
KALSHI_MAX_RECONNECT_ATTEMPTS=10
KALSHI_RECONNECT_BASE_DELAY=1.0
KALSHI_RECONNECT_MAX_DELAY=60.0
KALSHI_HEALTH_CHECK_INTERVAL=30.0
```

### Programmatic Configuration

```python
client = get_robust_kalshi_client(
    max_reconnect_attempts=10,
    reconnect_base_delay=1.0,
    reconnect_max_delay=60.0,
    health_check_interval=30.0
)
```

## Monitoring & Alerting

### Health Check Endpoint

```python
# Get health summary
manager = get_kalshi_resilience_manager()
summary = manager.get_health_summary()

print(f"Client healthy: {summary['client_healthy']}")
print(f"Unfilled orders: {summary['unfilled_orders']}")
print(f"Total PnL: {summary['total_pnl']}")
```

### Integration with HealthChecker

```python
from merid.pipeline.robustness import get_health_checker

health_checker = get_health_checker()

# Register custom health check
async def custom_check():
    return {"healthy": True, "custom_metric": 42}

health_checker.register_check("my_kalshi_check", custom_check)

# Run all checks
results = await health_checker.run_all_checks()
```

## Best Practices

### 1. Always Use Context Managers

```python
# Good - automatic cleanup
client = get_robust_kalshi_client()
try:
    await client.start()
    # ... operations
finally:
    await client.stop()
```

### 2. Handle Fallback Values

```python
# Always provide sensible fallback values
balance = await client.execute_with_robustness(
    client._client.get_balance,
    operation_name="get_balance",
    fallback_value={"balance": 0, "currency": "USD"}
)
```

### 3. Monitor Health Metrics

```python
# Log health status periodically
if not client.health.client_healthy:
    logger.warning("Kalshi client unhealthy - check connection")

if client.health.error_count_1h > 10:
    logger.error("High error rate detected - investigation needed")
```

### 4. Use Request Deduplication Wisely

```python
# Deduplication is automatic for identical operations
# Only identical operations (same name + args) within 5s are deduplicated

# These will be deduplicated:
result1 = await client.place_order(order)  # Executes
result2 = await client.place_order(order)  # Returns cached result

# These will NOT be deduplicated (different args):
result3 = await client.place_order(different_order)
```

## Troubleshooting

### Connection Issues

**Problem**: Client keeps reconnecting
- Check network connectivity to Kalshi API
- Verify API credentials are valid
- Check Kalshi API status page

**Solution**:
```python
# Increase reconnection delays
client = get_robust_kalshi_client(
    reconnect_base_delay=5.0,  # Start with 5s delay
    reconnect_max_delay=300.0  # Max 5 minutes
)
```

### High Error Rate

**Problem**: Many operations failing
- Check rate limits (may need higher tier)
- Verify order parameters are valid
- Check market status (some markets may be closed)

**Solution**:
```python
# Check health status
health = client.health
print(f"Errors: {health.error_count_1h}")
print(f"Latency: {health.latency_ms_avg}ms")
print(f"Reconnects: {health.reconnect_count_1h}")
```

### Order Tracking Issues

**Problem**: Orders not appearing in tracker
- Ensure `on_order_submitted` is called
- Verify order IDs are consistent
- Check for callback errors

**Solution**:
```python
# Add callback to debug
tracker.register_callback(lambda event, oid, data: 
    print(f"Event: {event}, Order: {oid}"))
```

## API Reference

### RobustKalshiClient

#### Constructor
```python
RobustKalshiClient(
    client_factory: Callable,           # Factory for creating KalshiVenueClient
    max_reconnect_attempts: int = 10,   # Max reconnection attempts
    reconnect_base_delay: float = 1.0,  # Initial reconnection delay
    reconnect_max_delay: float = 60.0,   # Maximum reconnection delay
    health_check_interval: float = 30.0 # Health check interval (seconds)
)
```

#### Methods
- `async start()`: Start client with health monitoring
- `async stop()`: Stop client gracefully
- `async place_order(order)`: Place order with robustness
- `async cancel_order(order_id)`: Cancel order with robustness
- `async get_positions()`: Get positions with robustness
- `async get_balance()`: Get balance with robustness
- `execute_with_robustness(operation, fallback_value)`: Execute with error recovery

#### Properties
- `health`: KalshiHealthStatus instance

### OrderLifecycleTracker

#### Methods
- `on_order_submitted(order_id, order_data)`: Record submission
- `on_order_filled(order_id, fill_data)`: Process fill
- `on_order_cancelled(order_id)`: Record cancellation
- `get_order_status(order_id)`: Get order status
- `get_unfilled_orders()`: Get list of unfilled order IDs
- `get_total_pnl()`: Get total realized PnL
- `register_callback(callback)`: Register event callback

### KalshiResilienceManager

#### Methods
- `initialize_client(client_factory)`: Initialize robust client
- `async start()`: Start all resilience components
- `async stop()`: Stop all resilience components
- `get_health_summary()`: Get comprehensive health summary

## Testing

Run the test suite:

```bash
# Run all tests
pytest tests/event_venues/kalshi/test_robustness.py -v

# Run specific test class
pytest tests/event_venues/kalshi/test_robustness.py::TestRobustKalshiClient -v

# Run with coverage
pytest tests/event_venues/kalshi/test_robustness.py --cov=merid.event_venues.kalshi.kalshi_robustness
```

## License

Part of the MERID trading system. See main LICENSE file.
