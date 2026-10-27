# Kalshi WebSocket Shutdown Cascade – Runbook

## Overview

This runbook documents the **Kalshi WebSocket shutdown cascade** issue class, the implemented mitigations, and operational guidance for production incidents.

## Problem Statement

MERID's server would experience **unexpected graceful shutdown** during Kalshi WebSocket instability, showing the following log sequence:

```
1. WebSocket connection resets (WinError 10054, WinError 995)
2. Reconnect storm with repeated connection attempts
3. Event-loop lag climbing: <50ms → 500ms → 2000ms+ (halt band)
4. ASGI fatal error classification triggering uvicorn shutdown
5. Graceful shutdown sequence with "drain complete" for all agents
```

### Root Cause Chain

```
Kalshi WebSocket disconnect
    ↓
Reconnect storm (thundering herd)
    ↓
Event-loop starvation (lag >2000ms)
    ↓
Windows I/O errors during close() classified as ASGI_FATAL
    ↓
Uvicorn graceful shutdown triggered
    ↓
All subsystems drained and stopped
```

### Why NOT the Liquidity Budget?

The `[BUDGET] liquidity_budget_exceeded` log message is often present during these incidents but **does not trigger shutdown**. It only aborts the liquidity sweep step. The error budget system (`merid/core/error_budget.py`) is observability-only and never halts trading.

## Implemented Fixes

### 1. Hardened WebSocket Close (merid/event_venues/kalshi/ws.py)

**What changed:**
- `close()` method now suppresses known benign Windows errors (WinError 995, 10054)
- Uses `_is_benign_ws_error()` helper to classify errors
- Logs unexpected errors as warnings, not exceptions

**Expected behavior:**
- WebSocket close operations complete cleanly even during forced shutdown
- Benign Windows I/O errors don't bubble up to ASGI fatal handler

**Configuration:**
- No configuration required
- Errors are detected by `winerror` code and `errno` inspection

### 2. Circuit Breaker in Reconnect Logic (merid/event_venues/kalshi/ws.py)

**What changed:**
- Added `_reconnect_circuit_threshold` (default: 5 failures)
- Circuit opens after N consecutive reconnect failures
- Once open, no more reconnect attempts until manual restart
- Success resets the failure count

**Expected behavior:**
- After 5 failed reconnects, circuit opens and logs CRITICAL message
- Prevents endless reconnection loops from starving the event loop
- Manual process restart required to reset the circuit

**Configuration:**
```bash
# Environment variable to adjust circuit threshold
export KALSHI_WS_RECONNECT_CIRCUIT_THRESHOLD=5
```

**Log signals:**
```
# Circuit about to open
WARNING Kalshi reconnection failed (attempt 4/5 circuit threshold): ...

# Circuit opens
CRITICAL [CIRCUIT-BREAKER] OPENED after 5 consecutive reconnect failures (threshold=5). ...

# Circuit open - blocking reconnects
CRITICAL [CIRCUIT-BREAKER] Reconnect circuit OPEN — too many consecutive failures. ...

# Success resets circuit
INFO [CIRCUIT-BREAKER] Resetting failure count after successful reconnect
```

### 3. Lag-Aware Reconnect Backoff (merid/event_venues/kalshi/ws.py)

**What changed:**
- Reconnect checks event-loop lag before attempting
- If lag >2000ms (halt band): enters "lag pause mode", skips all reconnects
- If lag >1000ms but <2000ms: skips individual reconnect, doubles backoff
- Exponential backoff with jitter (±25%)

**Expected behavior:**
- During high lag, reconnect attempts back off to let the event loop recover
- Prevents reconnect storm from amplifying lag

**Configuration:**
```bash
# Lag threshold for skipping individual reconnects (ms)
export KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS=1000

# Halt band is hardcoded at 2000ms
```

**Log signals:**
```
# Entering lag pause
CRITICAL [EVENT-LOOP-FIX] ENTERING LAG PAUSE MODE — lag 2500ms > 2000ms ...

# Exiting lag pause
WARNING [EVENT-LOOP-FIX] EXITING LAG PAUSE MODE — lag recovered to 800ms after 12.5s

# Individual skip
WARNING [EVENT-LOOP-FIX] Skipping WS reconnect — event loop lag 1500ms exceeds threshold 1000ms
```

### 4. Extended Liquidity Budget (merid/loop.py)

**What changed:**
- Hard budget increased from 1000ms to 2000ms
- Made configurable via environment variable
- Clarified log message that this aborts sweep only, NOT server

**Expected behavior:**
- Liquidity sweep continues during moderate lag (<2000ms)
- Only aborts when approaching halt band
- Clearer logs reduce confusion about shutdown attribution

**Configuration:**
```bash
# Configure liquidity sweep budget (ms)
export MERID_LIQUIDITY_HARD_BUDGET_MS=2000
```

**Log signals:**
```
# Budget exceeded (sweep aborts, server continues)
ERROR [BUDGET] liquidity_budget_exceeded: aborting sweep step after 2100ms (budget 2000ms). This aborts the sweep only, NOT the server.
```

### 5. ASGI Guard Tolerance (web/asgi_guard.py)

**What changed:**
- Added `is_benign_ws_error()` method to classify Windows errors
- WinError 995, 10054 now classified as `UNKNOWN` (not `ASGI_FATAL`)
- WinError 10038, 10060 remain `ASGI_FATAL`
- Debug logging when errors are downgraded

**Expected behavior:**
- Benign WebSocket close errors don't trigger server shutdown
- Genuine fatal errors (corrupted socket state) still trigger shutdown

**Log signals:**
```
# Debug: error downgraded
DEBUG FatalErrorClassifier: Downgrading OSError to benign (WebSocket close)
```

### 6. Structured Shutdown Logging (web/main.py)

**What changed:**
- Added `[SHUTDOWN-INITIATED]` structured log with JSON context
- Added `[SHUTDOWN-METRICS]` with lag statistics (p95, max, samples)
- Preserved existing shutdown logs for compatibility

**Expected behavior:**
- Every shutdown now has clear attribution and metrics
- Easy to grep for post-incident analysis

**Log signals:**
```
# New structured log
CRITICAL [SHUTDOWN-INITIATED] {"reason": "asgi_fatal", "sub_reason": "OSError", "fatal_error": "OSError", "timestamp": 1234567890.123}

# New metrics snapshot
CRITICAL [SHUTDOWN-METRICS] lag_ms=2500.0 lag_p95=1800.0 lag_max=3000.0 samples=60

# Legacy log (preserved)
CRITICAL 🛑 MERID shutdown initiated - cancelling background tasks... shutdown_reason=asgi_fatal sub_reason=OSError fatal_error_type=OSError
```

## Operational Playbook

### Scenario 1: Server Unexpectedly Shuts Down

**Investigation steps:**

1. **Check shutdown attribution:**
   ```bash
   grep "SHUTDOWN-INITIATED" logs/merid.log | tail -1
   ```
   Look for `reason`, `sub_reason`, `fatal_error` fields.

2. **Check lag metrics at shutdown:**
   ```bash
   grep "SHUTDOWN-METRICS" logs/merid.log | tail -1
   ```
   High `lag_ms` (>2000) indicates event-loop starvation.

3. **Check for circuit breaker:**
   ```bash
   grep "CIRCUIT-BREAKER.*OPENED" logs/merid.log
   ```
   If present, circuit opened due to reconnect failures.

4. **Check for lag pause mode:**
   ```bash
   grep "LAG PAUSE MODE" logs/merid.log | tail -5
   ```
   If present, lag-driven backoff was active.

5. **Check WebSocket lifetime stats:**
   ```bash
   grep "Kalshi WebSocket closed" logs/merid.log | tail -1
   ```
   High `reconnects` (>10) indicates instability.

### Scenario 2: Circuit Breaker Open

**Symptoms:**
- Log line: `[CIRCUIT-BREAKER] OPENED after N consecutive reconnect failures`
- No further WebSocket reconnect attempts
- Kalshi data may become stale

**Remediation:**
1. Check network connectivity to Kalshi:
   ```bash
   curl -I https://trading-api.kalshi.com
   ```

2. If connectivity OK, restart the MERID process:
   ```bash
   # Circuit breaker resets on process restart
   systemctl restart merid
   ```

3. If connectivity issues persist, investigate:
   - Firewall rules
   - DNS resolution
   - Kalshi API status page

### Scenario 3: High Event-Loop Lag

**Symptoms:**
- Log line: `ENTERING LAG PAUSE MODE`
- `SHUTDOWN-METRICS` shows `lag_ms > 2000`

**Investigation:**
1. Check what's blocking the event loop:
   ```bash
   grep "Slow action" logs/merid.log | tail -10
   grep "Slow WS" logs/merid.log | tail -10
   ```

2. Check for other blocking operations:
   ```bash
   grep "step timeout" logs/merid.log | tail -5
   ```

**Remediation:**
- Lag pause mode is self-healing (reconnects resume when lag drops)
- If lag persists, investigate specific slow operations from logs
- Consider increasing `MERID_LIQUIDITY_HARD_BUDGET_MS` if liquidity sweep is the blocker

### Scenario 4: Liquidity Budget Exceeded

**Symptoms:**
- Log line: `[BUDGET] liquidity_budget_exceeded`
- Server **does NOT** shut down (this is normal)

**Investigation:**
1. Check if budget is too restrictive:
   ```bash
   grep "liquidity_budget_exceeded" logs/merid.log | wc -l
   ```
   Frequent occurrences suggest budget may be too low.

2. Check lag at time of budget breach:
   ```bash
   grep -A1 "liquidity_budget_exceeded" logs/merid.log | grep "lag"
   ```

**Remediation:**
```bash
# Increase budget if legitimate lag causing frequent aborts
export MERID_LIQUIDITY_HARD_BUDGET_MS=3000
```

## Monitoring & Alerting

### Recommended Alerts

1. **Circuit breaker opened:**
   ```bash
   # Alert when circuit opens
   grep "CIRCUIT-BREAKER.*OPENED" logs/merid.log
   ```

2. **Lag pause mode entered:**
   ```bash
   # Alert on lag-driven backoff
   grep "ENTERING LAG PAUSE MODE" logs/merid.log
   ```

3. **Unexpected shutdown:**
   ```bash
   # Alert on non-SIGTERM shutdown
   grep "SHUTDOWN-INITIATED" logs/merid.log | grep -v "user_request"
   ```

4. **High reconnect count:**
   ```bash
   # Alert if >10 reconnects in 5 minutes
   grep "Reconnecting to Kalshi" logs/merid.log | wc -l
   ```

### Dashboard Metrics

Track these metrics for operational visibility:

| Metric | Source | Description |
|--------|--------|-------------|
| `kalshi_ws_reconnect_count` | WebSocket client | Total reconnect attempts |
| `kalshi_ws_circuit_state` | WebSocket client | 0=closed, 1=open |
| `event_loop_lag_ms` | loop_lag monitor | Current lag |
| `lag_pause_mode_active` | WebSocket client | 0=inactive, 1=active |
| `liquidity_budget_exceeded_count` | Loop | Budget breach frequency |

## Testing

### Unit Tests

Run the new test suite:

```bash
pytest tests/merid/event_venues/kalshi/test_ws_hardening.py -v
```

### Integration Test

Simulate a benign shutdown scenario:

```python
# test_benign_shutdown.py
import asyncio
import os
os.environ["MERID_VALIDATION_MODE"] = "1"

from merid.event_venues.kalshi.ws import KalshiWebSocket

async def test_benign_close():
    ws = KalshiWebSocket()
    ws._running = True
    ws._ws = None  # Simulate closed state
    
    # Should complete without error
    await ws.close()
    print("✅ Benign close test passed")

if __name__ == "__main__":
    asyncio.run(test_benign_close())
```

## Configuration Summary

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_WS_RECONNECT_CIRCUIT_THRESHOLD` | 5 | Failures before circuit opens |
| `KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS` | 1000 | Lag threshold for skip/backoff |
| `MERID_LIQUIDITY_HARD_BUDGET_MS` | 2000 | Liquidity sweep budget (ms) |

## Future Improvements

Potential follow-ups:

1. **Prometheus metrics** for reconnect count, circuit state, lag distribution
2. **Health check endpoint** exposing circuit breaker state
3. **Automatic circuit reset** after cooldown period (currently requires restart)
4. **WebSocket connection pooling** for faster failover
5. **Kalshi-specific health dashboard** showing connection stability over time

## References

- Issue: Server self-shutdown due to WebSocket reconnect storms
- Files changed:
  - `merid/event_venues/kalshi/ws.py`
  - `merid/loop.py`
  - `web/asgi_guard.py`
  - `web/main.py`
- Tests: `tests/merid/event_venues/kalshi/test_ws_hardening.py`
