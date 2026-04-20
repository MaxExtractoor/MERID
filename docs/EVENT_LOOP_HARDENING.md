# Event Loop Hardening Summary

This document summarizes the event loop hardening changes made to address event loop blocking, backpressure, and eager shutdown issues.

## Changes Overview

### 1. WebSocket Bridge (`merid/event_venues/kalshi/ws_bridge.py`)

#### Queue Backpressure & Depth Monitoring
- Added queue pressure calculation (current_qsize / max_size)
- Added aggressive non-fill event dropping when queue >95% full to preserve capacity for fills
- Added `[BACKPRESSURE]` log warnings when queue exceeds 80% capacity
- Enhanced `get_health_status()` to include queue metrics:
  - `queue_depth`: Current items in queue
  - `queue_capacity`: Maximum queue size
  - `queue_pressure`: Ratio 0.0-1.0
  - `events_forwarded`, `events_dropped`, `fills_received`, `fills_dropped`
  - Health status upgrades to YELLOW/RED based on queue pressure

#### Forward Loop Batch Processing
- Rewrote `_forward_loop()` to process events in batches (max 50 events per batch)
- Added 100ms timeout budget per batch to yield control back to event loop
- Proper cancellation handling with `asyncio.CancelledError`
- Removed duplicate event counting from `_publish_event()` (now counted in forward loop)

### 2. MeridLoop (`merid/loop.py`)

#### Global Tick Timeout
- Added `MERID_TICK_GLOBAL_TIMEOUT_S` environment variable (default: 60s)
- Wrapped `_tick_body()` in `asyncio.wait_for()` with hard timeout
- On timeout: logs CRITICAL, increments `global_tick_timeouts` metric, returns error summary
- Prevents any single tick from starving the event loop indefinitely

#### Cooperative Shutdown
- Added cancellation checks at start of each tick iteration
- `CancelledError` caught and handled cleanly in main loop
- Background task draining with 6s timeout before force cancellation
- Shutdown timeout (default 10s) for graceful background task cleanup

#### Enhanced Metrics (LoopMetrics)
New fields added for observability:
- `timeout_count`: Total step timeouts
- `lag_skip_count`: Steps skipped due to high lag
- `slow_action_skips`: Steps skipped due to recent slowness
- `global_tick_timeouts`: Full tick global timeouts
- `last_lag_ms`: Last recorded event loop lag

#### Slow Action Skip Tracking
- All slow action skips now increment `slow_action_skips` metric:
  - `features` step
  - `arb_scan` step
  - `liquidity` step

### 3. Watchdog Agents (`agents/watchdog_agents.py`)

#### Lag-Aware Gating
- `_run_checks()` skips all checks if event loop lag >2000ms
- Logs `[WATCHDOG-LAG-SKIP]` when skipping due to high lag

#### Timeout Budget
- Hard 5-second budget for all watchdog checks combined
- Individual check timeouts with remaining budget calculation
- `[WATCHDOG-TIMEOUT]` and `[WATCHDOG-BUDGET]` logging

#### Cooperative Shutdown
- Cancellation checks before and during alert publishing
- `CancelledError` handling in main loop with clean exit
- Sleep wrapped with try/except for cancellation

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MERID_TICK_GLOBAL_TIMEOUT_S` | 60.0 | Hard timeout for entire tick execution |
| `MERID_LOOP_STEP_TIMEOUT_S` | 5.0 | Per-step timeout (already existed) |
| `MERID_LOOP_STEP_TIMEOUT_OVERRIDES` | JSON | Step-specific timeout overrides (already existed) |
| `KALSHI_LOOP_LAG_HEALTHY_MS` | 50 | Healthy lag threshold |
| `KALSHI_LOOP_LAG_DEGRADE_MS` | 500 | Degraded performance threshold |
| `KALSHI_LOOP_LAG_HALT_MS` | 2000 | Critical lag threshold |

## Log Messages to Monitor

### Critical (Investigate Immediately)
- `[TICK-TIMEOUT] Global tick timeout after Xs` - Event loop severely stalled
- `[BACKPRESSURE] Dropping non-fill event` - Queue at >95% capacity

### Warning (Investigate if Frequent)
- `[BACKPRESSURE] WS bridge queue at X% capacity` - Queue pressure building
- `[WATCHDOG-BUDGET] Check budget exceeded` - Watchdog checks taking too long
- `[LAG-SKIP] action=X reason=elevated_lag` - Operations skipped due to lag
- `Slow action 'X': Yms (budget Zms)` - Individual step exceeding budget

### Info (Normal Operation)
- `[WATCHDOG-LAG-SKIP] Skipping checks due to high loop lag` - Watchdog correctly backing off
- `[LOOP] Cancelled — exiting main loop cleanly` - Cooperative shutdown working
- `[SHUTDOWN] Background tasks cancelled successfully` - Clean shutdown

## Metrics to Monitor

### Loop Metrics (`merid_loop.status()`)
```python
{
    "timeout_count": int,          # Should be 0 under normal operation
    "lag_skip_count": int,         # Expected during high load
    "slow_action_skips": int,      # Expected if steps are slow
    "global_tick_timeouts": int,   # Should ALWAYS be 0
    "last_lag_ms": float,          # Current event loop lag
}
```

### WS Bridge Metrics (`ws_bridge.get_health_status()`)
```python
{
    "queue_depth": int,            # Alert if >80% of capacity
    "queue_pressure": float,       # Alert if >0.8
    "events_dropped": int,         # Alert if increasing rapidly
    "fills_dropped": int,          # CRITICAL if >0
    "status": "GREEN|YELLOW|RED",  # Based on pressure + failures
}
```

## Rollback Plan

All changes are additive with clear log prefixes. To disable specific features:

1. **Global tick timeout**: Set `MERID_TICK_GLOBAL_TIMEOUT_S=0` (or very high value)
2. **Watchdog lag gating**: Not configurable (safe to leave - only skips when lag >2s)
3. **Queue backpressure**: Not configurable (safe - protects critical fill events)

## Testing Recommendations

1. **Load test**: Verify queue pressure stays under 80% during normal operation
2. **Lag test**: Inject artificial lag, verify watchdog skips, tick continues
3. **Shutdown test**: Send SIGTERM during high load, verify clean exit within 10s
4. **Timeout test**: Simulate slow external API, verify step times out after 5s
