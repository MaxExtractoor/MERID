# Kalshi Integration Crash Resilience Runbook

## Overview

This runbook covers the detection, diagnosis, and response procedures for crash-class issues in the Merid-Kalshi integration. All CRASH-XXX fixes from the resilience audit are instrumented with health checks and metrics.

---

## Health Status Model

The integration now reports three health states:

### GREEN
- No recent critical errors (last 5 minutes)
- WebSocket connected and receiving messages
- Orders flowing normally (< 5% rejection rate)
- Callback failure rate < 10 per minute

### YELLOW
- Repeated transient errors detected
- Automatic retries in progress
- WS reconnect within last 60 seconds
- Callback failure rate 10-50 per minute
- Position cache fallback in use (CRASH-004)

### RED
- Critical exception in WS or router (CRASH-001, CRASH-002)
- Reconnect loop exceeded threshold (> 5 attempts in 5 min)
- Circuit breaker tripped
- Task failure rate > 50 per minute
- Position cache unavailable with orders being rejected

---

## Metrics Reference

### Critical Metrics to Monitor

| Metric | Type | Threshold | Description |
|--------|------|-----------|-------------|
| `kalshi_ws_bridge_task_crash` | Counter | > 0 | CRASH-001: Background task crash |
| `kalshi_ws_callback_failure` | Counter | > 10/min | CRASH-002: Callback handler failed |
| `kalshi_position_cache_failure` | Counter | > 5/min | CRASH-004: Position lookup failed, orders rejected |
| `kalshi_ws_reconnect_total` | Counter | > 5/5min | Reconnect storm indicator |
| `kalshi_order_rejected_invalid_params` | Counter | Spike | CRASH-007: Invalid order parameters |

### Health Endpoint Usage

```python
# WS Bridge health
from merid.event_venues.kalshi.ws_bridge import get_kalshi_ws_bridge
health = get_kalshi_ws_bridge().get_health_status()
# Returns: {"status": "GREEN|YELLOW|RED", "recent_task_failures": N, "running": True}

# WS Callback health
from merid.event_venues.kalshi.ws import get_kalshi_ws
health = get_kalshi_ws().get_callback_health()
# Returns: {"failure_count_60s": N, "healthy": True|False, ...}
```

---

## Incident Response Playbook

### Scenario 1: RED Status - WS Bridge Task Crash (CRASH-001)

**Symptoms:**
- `kalshi_ws_bridge_task_crash` metric firing
- Health status RED
- No market data updates for > 30 seconds

**Response:**
1. **Immediate**: Check logs for `CRITICAL: WS bridge task X crashed`
2. **Diagnose**: Review exception details in log context
3. **Auto-recovery**: System should auto-reconnect within 5 seconds
4. **Verify**: Confirm health returns to GREEN
5. **Escalate**: If still RED after 60 seconds, restart the service

**Log Query:**
```bash
grep "CRASH-001\|WS bridge task.*crashed" /var/log/merid/kalshi.log | tail -50
```

---

### Scenario 2: RED Status - Callback Failure Storm (CRASH-002)

**Symptoms:**
- `kalshi_ws_callback_failure` spiking (> 50/min)
- Health status RED
- Market data stale but WS appears connected

**Response:**
1. **Immediate**: Check callback health: `get_kalshi_ws().get_callback_health()`
2. **Diagnose**: Look for specific error types in logs
3. **Action**: System will auto-reconnect if failures > 10
4. **Verify**: Monitor `kalshi_ws_callback_failure` rate decreases

**Log Query:**
```bash
grep "CRASH-002\|WS callback task failed" /var/log/merid/kalshi.log | tail -100
```

---

### Scenario 3: YELLOW Status - Position Cache Unavailable (CRASH-004)

**Symptoms:**
- `kalshi_position_cache_failure` metric firing
- Health status YELLOW
- Orders being rejected with `position_cache_unavailable` reason

**Response:**
1. **Immediate**: Check position cache connectivity
2. **Diagnose**: Review position cache logs for errors
3. **Action**: Orders are fail-closed (rejected safely) - this is expected behavior
4. **Recovery**: Once cache recovers, orders will resume automatically

**Log Query:**
```bash
grep "CRASH-004\|position_cache_unavailable" /var/log/merid/kalshi.log | tail -50
```

**Note:** This is defensive behavior - orders are rejected rather than traded with unknown position risk.

---

### Scenario 4: RED Status - Reconnect Storm (CRASH-006)

**Symptoms:**
- `kalshi_ws_reconnect_total` spiking (> 5 in 5 minutes)
- Health status RED
- Intermittent connection with rapid disconnects

**Response:**
1. **Immediate**: Check Kalshi API status page
2. **Diagnose**: Review logs for disconnect reasons
3. **Action**: System has reconnect lock - only 1 reconnect runs at a time
4. **Wait**: Exponential backoff will increase delay between attempts
5. **Escalate**: If persists > 10 minutes, check network/firewall

**Log Query:**
```bash
grep "Reconnecting to Kalshi\|CRASH-006" /var/log/merid/kalshi.log | tail -30
```

---

### Scenario 5: YELLOW Status - Batch Order None Results (CRASH-005)

**Symptoms:**
- `kalshi_order_rejected_routing_returned_none` metric
- Batch orders partially failing

**Response:**
1. **Immediate**: Check order router logs
2. **Diagnose**: Look for `CRASH-005` in logs
3. **Action**: Individual orders rejected - retry failed orders individually
4. **Verify**: Confirm subsequent batches process normally

**Log Query:**
```bash
grep "CRASH-005\|routing_returned_none" /var/log/merid/kalshi.log | tail -20
```

---

## Rollback Procedures

### Canary Rollback Criteria

Roll back immediately if any of the following occur:

1. **New crash types appearing** in logs (previously unseen exceptions)
2. **Order rejection rate > 20%** for > 5 minutes
3. **All orders rejected** with `position_cache_unavailable` for > 3 minutes
4. **WebSocket disconnected** > 60% of time over 10-minute window
5. **Latency spike** > 5 seconds for order routing (P99)

### Rollback Commands

```bash
# Rollback to previous version
kubectl rollout undo deployment/merid-kalshi-integration

# Verify rollback
kubectl get pods -l app=merid-kalshi

# Check health after rollback
curl http://merid-health:8080/health | jq '.kalshi.status'
```

---

## Testing Procedures

### Pre-Deployment Validation

Run these tests before any production deployment:

```bash
# Run crash resilience test suite
pytest tests/merid/event_venues/kalshi/test_crash_resilience.py -v

# Run integration tests with Kalshi sandbox
pytest tests/integration/kalshi/ -v --sandbox
```

### Failure Injection Test

```python
# Test CRASH-001: Simulate task crash
from tests.merid.event_venues.kalshi.test_crash_resilience import TestCrash001WSBridgeTaskExceptions
test = TestCrash001WSBridgeTaskExceptions()
await test.test_ws_bridge_task_crash_triggers_health_degradation()

# Test CRASH-004: Simulate position cache failure
test = TestCrash004PositionCacheFailClosed()
await test.test_position_cache_failure_rejects_order()

# Verify health endpoints respond correctly
health = get_kalshi_ws_bridge().get_health_status()
assert health["status"] in ["GREEN", "YELLOW", "RED"]
```

---

## Contact and Escalation

| Issue Type | Primary | Escalation |
|------------|---------|------------|
| WS/Connectivity | #infra-kalshi | @sre-oncall |
| Order Routing | #trading-systems | @trading-leads |
| Risk/Gate Issues | #risk-systems | @risk-oncall |
| Metrics/Health | #observability | @sre-oncall |

---

## Appendix: Log Patterns Reference

### Critical Log Patterns (RED alert)

```
CRITICAL: WS bridge task.*crashed
CRITICAL: Too many callback failures.*forcing reconnect
FATAL: Kalshi.*authentication.*failed
ERROR: Position cache lookup failed.*rejecting order
```

### Warning Log Patterns (YELLOW alert)

```
WARNING: WS callback task failed
WARNING: Reconnecting to Kalshi
WARNING: Kalshi reconnection failed
WARNING: Event-loop lag:.*ms
```

### Info Log Patterns (Normal operation)

```
INFO: Reconnected successfully
INFO: [order-router].*accepted
INFO: [order-router].*filled
INFO: [KALSHI_CT_CONFIG]
```
