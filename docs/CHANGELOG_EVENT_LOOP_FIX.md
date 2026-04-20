# Event Loop Lag, Queue Pressure, and Shutdown Hardening

**Status**: Production Ready  
**Date**: 2026-01-11  
**Impact**: Eliminates silent shutdowns and event-loop lag entering halt band

## Executive Summary

This release implements comprehensive hardening for event-loop lag, queue pressure, and shutdown attribution in the MERID trading system. The system now:

1. **Never allows SHUTDOWN-INITIATED with reason unknown** - all shutdowns have explicit, auditable reasons
2. **Implements progressive load shedding** - sheds non-critical work before considering shutdown
3. **Enforces hard queue pressure policies** - automatically reduces scope at critical thresholds
4. **Provides self-diagnosing instrumentation** - all metrics visible in execution gate diagnostics

## Changes by Component

### 1. Shutdown API (`web/asgi_guard.py`)

**New Shutdown Reasons:**
- `LOOP_LAG_HALT` - Event loop lag exceeded halt threshold for consecutive samples
- `QUEUE_PRESSURE_HALT` - Queue pressure critical after load shedding failed
- `FATAL_EXCEPTION` - Unhandled fatal exception
- `LIFESPAN_END` - Normal lifespan end (not an error)
- `MANUAL_OPERATOR` - Explicit operator shutdown command
- `DEPLOY_RESTART` - Deployment/restart requested

**New Function: `initiate_shutdown()`**
```python
def initiate_shutdown(
    reason: ShutdownReason,
    sub_reason: Optional[str] = None,
    fatal_error: Optional[Exception] = None,
    initiator_module: str = "asgi_guard",
    metrics: Optional[dict] = None,
) -> ShutdownEvent
```

**Key Behavior:**
- Raises `ValueError` if `reason=UNKNOWN` is passed in production
- Logs structured shutdown context with metrics
- Captures stack summary for forensics
- Records to metrics for dashboards

### 2. Loop Lag Monitor (`merid/diagnostics/loop_lag.py`)

**Progressive Load Shedding:**

| Threshold | Action | Log Level |
|-----------|--------|-----------|
| healthy (<50ms) | Normal operation | - |
| elevated (50-500ms) | Log warning, trigger callbacks | WARNING |
| degraded (500-2000ms) | Reduce scope, shed non-critical work | WARNING |
| halt (>=2000ms) | Consider shutdown after 3 consecutive samples | CRITICAL |

**New Callbacks:**
- `on_elevated(callback)` - Register callback for elevated lag
- `on_degraded(callback)` - Register callback for degraded lag (scope reduction)
- `on_halt(callback)` - Register callback for halt band (can suppress shutdown)

**New Health Metrics:**
```python
{
    "scope_reduced": bool,           # True when in degraded mode
    "scope_reduced_at": float,       # Timestamp of scope reduction
    "halt_consecutive_count": int,   # Consecutive halt-band samples
    "halt_max_consecutive": int,     # Configurable threshold (default: 3)
}
```

**Environment Variables:**
- `KALSHI_LOOP_LAG_HEALTHY_MS` - Healthy threshold (default: 50)
- `KALSHI_LOOP_LAG_DEGRADE_MS` - Degraded threshold (default: 500)
- `KALSHI_LOOP_LAG_HALT_MS` - Halt threshold (default: 2000)
- `KALSHI_LOOP_LAG_HALT_CONSECUTIVE` - Consecutive samples before shutdown (default: 3)

### 3. Queue Pressure Supervisor (`merid/event_venues/kalshi/ws.py`)

**Enhanced Thresholds:**

| Threshold | Utilization | Action |
|-----------|-------------|--------|
| elevated | 50% | Log warning |
| warn | 75% | Proactive reduction warning |
| critical | 90% | Immediate load shedding |
| shutdown | 98% | Shutdown if persists after shedding |

**New Tracking:**
- `_pressure_shutdown_consecutive` - Consecutive critical samples
- `_pressure_shutdown_max` - Configurable threshold (default: 3)
- `_pressure_post_shed_utilization` - Utilization after last shed
- `_shedding_failed_count` - Times shedding didn't relieve pressure

**Shutdown Logic:**
1. At 90% utilization: Shed load to essential tickers only
2. After shedding: Track consecutive samples at critical level
3. If still critical after 3 samples: Initiate `QUEUE_PRESSURE_HALT` shutdown

**Environment Variables:**
- `KALSHI_WS_PRESSURE_SHUTDOWN_MAX` - Consecutive critical samples before shutdown (default: 3)

### 4. Lifespan Shutdown (`web/main.py`)

**Explicit Shutdown Attribution:**
- Derives shutdown reason from context if ASGI guard doesn't provide one
- Checks loop lag monitor for critical state
- Never produces "reason unknown" - falls back to `LIFESPAN_END` as safest option

**New Documentation:**
Added comprehensive docstring to `_app_lifespan()` documenting:
- Event-loop architecture
- Lag thresholds and actions
- Queue pressure thresholds
- Shutdown policy
- Service startup/shutdown sequence

### 5. Execution Gate Diagnostics (`core/execution_gate.py`)

**New Diagnostics Field:**
```python
ExecutionGateStatus.diagnostics = {
    "event_loop_lag": {
        "current_ms": float,
        "p95_ms": float,
        "max_ms": float,
        "healthy": bool,
        "elevated": bool,
        "degraded": bool,
        "critical": bool,
        "scope_reduced": bool,
        "halt_consecutive_count": int,
    },
    "queue_pressure": {
        "utilization_pct": float,
        "messages_dropped": int,
        "action": str,
        "is_reduced_scope": bool,
        "shed_count": int,
    }
}
```

**API Endpoint:** `GET /api/v1/system/execution-gate`

Response now includes `diagnostics` field with real-time lag and queue metrics.

### 6. MeridLoop Documentation (`merid/loop.py`)

**Enhanced Class Docstring:**
- Event-loop architecture documentation
- Scheduled tasks enumeration
- Lag detection integration
- Shutdown policy

## Testing

**New Test File:** `tests/test_event_loop_fixes.py`

Test coverage includes:
1. `TestShutdownReasonExplicit` - Validates shutdown reason enforcement
2. `TestLoopLagActions` - Tests progressive load shedding
3. `TestQueuePressureShutdown` - Tests queue pressure backpressure
4. `TestExecutionGateDiagnostics` - Tests diagnostic metrics
5. `TestIntegration` - End-to-end integration tests

**Run Tests:**
```bash
python -m pytest tests/test_event_loop_fixes.py -v
```

## Configuration Reference

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `KALSHI_LOOP_LAG_HEALTHY_MS` | 50 | Healthy lag threshold |
| `KALSHI_LOOP_LAG_DEGRADE_MS` | 500 | Degraded lag threshold |
| `KALSHI_LOOP_LAG_HALT_MS` | 2000 | Halt band threshold |
| `KALSHI_LOOP_LAG_HALT_CONSECUTIVE` | 3 | Consecutive halt samples before shutdown |
| `KALSHI_WS_PRESSURE_SHUTDOWN_MAX` | 3 | Consecutive critical samples before shutdown |
| `MERID_ENV` | "" | Environment (production triggers strict UNKNOWN rejection) |

## Migration Guide

### For Operators

**No action required.** The system automatically:
1. Reduces scope when lag exceeds 500ms
2. Sheds queue load at 90% utilization
3. Logs all actions with structured context

**New Log Patterns:**
- `[LOOP-LAG] ENTERING DEGRADED MODE` - Scope reduction triggered
- `[LOOP-LAG] HALT BAND (Xms, count=Y)` - Approaching shutdown
- `[QUEUE-PRESSURE] SHUTDOWN TRIGGERED` - Queue pressure shutdown
- `[SHUTDOWN-INITIATED] reason=X` - Explicit shutdown with reason

### For Developers

**API Changes:**
- Use `initiate_shutdown()` with explicit `ShutdownReason`
- Register lag callbacks via `LoopLagMonitor.on_*()` methods
- Access diagnostics via `ExecutionGateStatus.diagnostics`

**Never use:**
```python
# WRONG - will raise ValueError in production
initiate_shutdown(reason=ShutdownReason.UNKNOWN)

# WRONG - bypasses structured logging
logger.critical("SHUTDOWN-INITIATED reason unknown")
```

**Always use:**
```python
# CORRECT - explicit reason and metrics
from web.asgi_guard import initiate_shutdown, ShutdownReason

initiate_shutdown(
    reason=ShutdownReason.LOOP_LAG_HALT,
    sub_reason="p95_lag_3500ms_for_60s",
    initiator_module="my_module",
    metrics={"lag_p95_ms": 3500, "samples": 60}
)
```

## Verification

**Check Event-Loop Health:**
```bash
curl http://localhost:8000/api/v1/system/execution-gate | jq '.diagnostics.event_loop_lag'
```

**Check Queue Pressure:**
```bash
curl http://localhost:8000/api/v1/system/execution-gate | jq '.diagnostics.queue_pressure'
```

**Check Shutdown Reason (if shutting down):**
```bash
# In logs, look for:
[SHUTDOWN-INITIATED] reason=X sub_reason=Y initiator=Z
```

## Backwards Compatibility

- **Fully backwards compatible** - no breaking API changes
- Existing code continues to work
- New diagnostics field is optional in responses
- Environment variables have sensible defaults
- UNKNOWN reason rejection only in production

## Related Documentation

- `docs/DIAGNOSTIC_RUNBOOK.md` - Event-loop lag investigation
- `web/main.py:_app_lifespan()` - Event-loop architecture
- `merid/diagnostics/loop_lag.py` - Lag monitor implementation
- `merid/event_venues/kalshi/ws.py` - Queue pressure supervisor
