# Graceful Degradation Paths

## Overview

This document describes all graceful degradation paths in the MERID system for Kalshi 15m crypto trading. Degradation paths ensure the system continues operating safely when components fail or become unavailable.

## Degradation Principles

1. **Fail-safe defaults**: When a component fails, use conservative defaults that prevent over-trading
2. **Circuit breakers**: Prevent cascade failures by isolating failing components
3. **Fallback data sources**: Use secondary data sources when primary is unavailable
4. **Health-based routing**: Route traffic based on component health status
5. **Graceful shutdown**: Clean shutdown when degradation is unrecoverable

## Existing Degradation Paths

### 1. Market Data Degradation

**Location**: `merid/event_venues/kalshi/market_state.py`

**Primary Source**: WebSocket feed (real-time orderbook)
**Fallback Source**: REST API (throttled to 5s per market)

**Health States**:
- `HEALTHY`: Primary feed timely; REST agrees within threshold
- `DEGRADED`: Using REST because primary missing/stale, but REST shows open & fresh
- `STALE`: Very old quote, use with caution
- `SUSPENDED`: Conflicting data, closed/paused state, or repeated failures

**Degradation Logic**:
- Primary stale > 5s → try REST fallback
- REST stale > 10s → mark as STALE
- Consecutive failures > 10 → circuit breaker opens (300s recovery)
- Cross-validation fails > 5c or 10% → mark as DEGRADED

**Safeguards**:
- Minimum 3/5 markets must be healthy for trading (60% quorum)
- Fallback quotes are not executable (`executable=False`)
- Max quote TTL: 15s

**Circuit Breaker**:
- Threshold: 10 consecutive failures
- Recovery: 300s with exponential backoff (max 60s)
- Per-ticker circuit breakers

### 2. WebSocket Connection Degradation

**Location**: `merid/event_venues/kalshi/ws_bridge.py`

**Primary**: WebSocket connection to Kalshi
**Fallback**: None (uses REST for market data)

**Circuit Breaker**:
- Threshold: 20 failures in 60s window
- Cooldown: 15s backoff when tripped
- Auto-reset after cooldown

**Degradation Behavior**:
- On trip: Block WS reconnects for cooldown period
- On cooldown expiry: Reset circuit breaker and attempt reconnect
- Logs: `[CIRCUIT-BREAKER] TRIPPED` with failure count and window

### 3. Order Submission Degradation

**Location**: `merid/event_venues/kalshi/order_router.py`

**Primary**: Kalshi API order submission
**Fallback**: None (orders fail-safe to not submit)

**Dry-Run Mode**:
- `MERID_EXECUTION_MODE=dry_run`: Log would-submit without placing order
- `MERID_EXECUTION_MODE=simulate`: Log + optionally simulate fills

**Circuit Breaker**:
- Location: `merid/event_venues/kalshi/client.py`
- Threshold: Configurable via `KALSHI_CIRCUIT_FAILURE_THRESHOLD`
- Recovery: Configurable via `KALSHI_CIRCUIT_RECOVERY_TIMEOUT`
- Per-environment breakers (demo vs live)

**Safeguards**:
- Auth failures not counted against circuit breaker
- Orders rejected if circuit breaker open
- Returns `CircuitOpenError` with retry-after time

### 4. Fills Persistence Degradation

**Location**: `merid/event_venues/kalshi/fills_ledger.py`

**Primary**: Database persistence
**Fallback**: Dead Letter Queue (DLQ)

**Circuit Breaker**:
- Threshold: Repeated persistence errors
- Behavior: Halts persistence, queues to DLQ
- Manual reset: `reset_circuit_breaker()` API endpoint

**Degradation Behavior**:
- On error: Check circuit breaker
- If open: Queue fill to DLQ, log warning
- If closed: Attempt persistence, update circuit breaker on failure
- DLQ fills: Require manual migration or circuit breaker reset

### 5. Backfill Degradation

**Location**: `merid/event_venues/kalshi/fills_poller.py`

**Primary**: Periodic full backfill
**Fallback**: Skip cycle if circuit breaker open

**Circuit Breaker**:
- Threshold: Repeated backfill failures
- Behavior: Opens after threshold, skips cycles until reset
- Monitoring: `get_circuit_breaker_status()` API endpoint

**Degradation Behavior**:
- On failure: Increment failure counter
- If threshold reached: Open circuit breaker, log `[BACKFILL-CIRCUIT-BREAKER]`
- On success: Reset failure counter, close circuit breaker
- When open: Skip backfill cycles, log "circuit breaker open - skipping cycle"

### 6. Settlement Poller Degradation

**Location**: `merid/event_venues/kalshi/settlement_poller.py`

**Primary**: Settlement API polling
**Fallback**: Continue with degraded status

**Health States**:
- `healthy`: Normal operation
- `warning`: Minor issues
- `degraded`: Using fallback or degraded data
- `critical`: Major issues
- `not_initialized`: Not yet initialized

**Degradation Behavior**:
- On API errors: Continue with degraded status
- Extended guard period for degraded settlement data
- Logs status changes

## Missing Degradation Paths

### 1. Agent Grid Degradation

**Status**: Not implemented

**Needed**: Circuit breaker for agent grid failures
- Threshold: N consecutive agent failures
- Behavior: Stop agent grid, log error, alert operator
- Recovery: Manual restart or auto-restart after cooldown

### 2. Risk Engine Degradation

**Status**: Partial (some fallbacks exist)

**Needed**: Circuit breaker for risk engine failures
- Threshold: N consecutive risk check failures
- Behavior: Halt trading, log error, alert operator
- Fallback: Use conservative risk limits (0 exposure)

### 3. Position Cache Degradation

**Status**: Partial (has REST fallback)

**Needed**: Circuit breaker for position cache failures
- Threshold: N consecutive cache sync failures
- Behavior: Use last known good state, log warning
- Fallback: REST API positions (throttled)

### 4. Reconciliation Degradation

**Status**: Not implemented

**Needed**: Circuit breaker for reconciliation failures
- Threshold: N consecutive reconciliation errors
- Behavior: Skip reconciliation cycle, log warning
- Fallback: Use last known reconciliation state

### 5. Hedge Engine Degradation

**Status**: Not implemented

**Needed**: Circuit breaker for hedge engine failures
- Threshold: N consecutive hedge order failures
- Behavior: Skip hedge pass, log warning
- Fallback: Continue without hedging (increased risk)

## Monitoring and Alerting

### Existing Metrics

- Circuit breaker state changes (logged)
- Market health state (logged)
- Fallback usage (tracked in market_state metrics)
- Circuit breaker status (API endpoints)

### Recommended Metrics

- `merid_degradation_events_total` - Counter for degradation events
- `merid_circuit_breaker_state` - Gauge for circuit breaker states
- `merid_fallback_usage_total` - Counter for fallback usage
- `merid_degraded_components` - Gauge for number of degraded components

### Recommended Alerts

- Circuit breaker opens (critical)
- Market health degraded (warning)
- Fallback usage > threshold (warning)
- Multiple components degraded (critical)

## Testing

### Existing Tests

- Circuit breaker tests in `hardening/circuit_breaker.py`
- Market state health tests

### Recommended Tests

- Degradation path integration tests
- Circuit breaker recovery tests
- Fallback data source tests
- Multi-component degradation tests

## Configuration

### Environment Variables

```bash
# Market data degradation
KALSHI_PRIMARY_STALE_SECONDS=5.0
KALSHI_REST_THROTTLE_SECONDS=5.0
KALSHI_MAX_REST_AGE_SECONDS=10
KALSHI_CROSS_VALIDATION_THRESHOLD_CENTS=5.0
KALSHI_CROSS_VALIDATION_THRESHOLD_PCT=0.10
KALSHI_MAX_QUOTE_TTL_SECONDS=15.0

# Circuit breakers
KALSHI_CIRCUIT_BREAKER_FAILURE_THRESHOLD=10
KALSHI_CIRCUIT_BREAKER_RECOVERY_SECONDS=300.0
KALSHI_CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS=60.0

# Health quorum
MIN_HEALTHY_BOOKS_FOR_TRADING=3
```

## Runbook

### Circuit Breaker Open

1. Check logs for circuit breaker trip reason
2. Check component health status
3. If transient: Wait for auto-recovery (check retry-after)
4. If persistent: Manual intervention required
5. Fix underlying issue
6. Reset circuit breaker if needed

### Market Data Degraded

1. Check WebSocket connection status
2. Check REST API availability
3. Check network connectivity
4. If both unavailable: System may halt trading
5. If REST available: System continues in degraded mode
6. Monitor for recovery to healthy state

### Multiple Components Degraded

1. Check system-wide health status
2. Identify common root cause (network, API, etc.)
3. If critical: Consider graceful shutdown
4. If non-critical: Continue with reduced capacity
5. Alert operators for manual intervention

## Future Improvements

1. **Consolidate circuit breakers**: Single circuit breaker implementation
2. **Add agent grid degradation**: Circuit breaker for agent failures
3. **Add risk engine degradation**: Circuit breaker for risk check failures
4. **Add reconciliation degradation**: Circuit breaker for reconciliation errors
5. **Add hedge engine degradation**: Circuit breaker for hedge order failures
6. **Add degradation metrics**: Prometheus metrics for all degradation events
7. **Add degradation alerts**: Alerting for critical degradation events
8. **Add degradation tests**: Integration tests for all degradation paths
