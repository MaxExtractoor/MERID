# Kalshi WebSocket Production Health Checklist

**Purpose:** Maintain WebSocket cleanliness and prevent regressions in the 15-minute scalping stack  
**Frequency:** Run before deployments, during incidents, and weekly during active trading  
**Audit Tool:** `scripts/audit_websocket_health.py`

---

## Pre-Deployment Checks

### Critical (Must Pass Before Deploy)

- [ ] **Run WebSocket audit script**
  ```bash
  py scripts/audit_websocket_health.py
  ```
  - Exit code must be 0 (no CRITICAL findings)
  - Review any HIGH findings with team

- [ ] **Verify environment configuration**
  - `KALSHI_API_KEY_ID` set and valid
  - `KALSHI_PRIVATE_KEY_PATH` points to existing key file
  - `KALSHI_ENV` matches target (demo/live)
  - Optional tuning vars reviewed if changed

- [ ] **Test connection in target environment**
  - Deploy to staging/dev
  - Verify WebSocket connects successfully
  - Check log for "Connected to Kalshi WebSocket with RSA-PSS authentication"
  - Verify subscription messages sent

- [ ] **Validate subscription scope**
  - Confirm ticker list matches expected markets
  - Verify 15m markets prioritized (BTC/ETH/SOL/XRP/DOGE)
  - Check subscription count ≤ 150 (hard cap)
  - Verify channel filtering (fills > orderbooks > quotes)

### High (Review Before Deploy)

- [ ] **Check for duplicate listener patterns**
  - Search for `addEventListener` or callback registrations
  - Verify no duplicate subscriptions in reconnect paths
  - Confirm event listeners removed on close

- [ ] **Review reconnect logic changes**
  - Any changes to `_reconnect()` method?
  - Verify `self.connect()` still called (handles cleanup)
  - Check circuit breaker threshold still reasonable (20 failures)
  - Confirm exponential backoff intact

- [ ] **Validate queue size changes**
  - If queue size changed, stress test with burst traffic
  - Verify backpressure thresholds adjusted accordingly
  - Check QueueFull exception handling still present

---

## Runtime Monitoring

### Critical (Alert Immediately)

- [ ] **Reconnection burst detection**
  - Alert if > 5 reconnects in 60 seconds
  - Alert if circuit breaker trips
  - Check logs for "CIRCUIT-BREAKER TRIPPED"
  - Verify fault manager state

- [ ] **Queue depth critical threshold**
  - Alert if queue pressure > 90%
  - Alert if queue pressure > 98% (shutdown threshold)
  - Check for message processing stalls
  - Verify consumer tasks not blocked

- [ ] **Heartbeat failure detection**
  - Alert if no messages for > 60 seconds
  - Check `_last_message_ts` timestamp
  - Verify ping_interval=20s, ping_timeout=60s
  - Test connection state with `is_open` check

### High (Alert Within 5 Minutes)

- [ ] **Message rate anomalies**
  - Alert if message rate drops > 50% from baseline
  - Alert if message rate spikes > 200% from baseline
  - Check per-channel rates (orderbook_delta, fills, trades)
  - Verify subscription scope unchanged

- [ ] **Sequence gap detection**
  - Monitor `_seq_gaps` counter
  - Alert if gap rate > 1% of messages
  - Check for stale orderbook snapshots
  - Verify snapshot refresh after gaps

- [ ] **Processing latency buildup**
  - Alert if event-loop lag > 3000ms
  - Alert if lag > 6000ms (halt band)
  - Check for lag pause mode activation
  - Profile slow message handlers

### Medium (Review Daily)

- [ ] **Connection duration tracking**
  - Review average connection duration
  - Check for unusually short connections (< 30s)
  - Verify reconnect delay not growing unbounded
  - Review circuit breaker cooldown periods

- [ ] **Error rate monitoring**
  - Track `_errors_received` counter
  - Alert if error rate > 1% of messages
  - Categorize errors by type (auth, rate limit, network)
  - Review error message patterns

---

## Failure Mode Detection

### Memory Leaks

**Symptoms:**
- Gradual memory growth over hours/days
- Increasing queue depth despite normal message rate
- Slow degradation in processing latency

**Detection:**
- [ ] Sample memory during active market windows
- [ ] Compare memory at startup vs after 4 hours
- [ ] Check for growing data structures in snapshots
- [ ] Verify event listeners removed on close

**Recovery:**
- [ ] Restart WebSocket bridge
- [ ] Clear orderbook snapshot cache
- [ ] Reset sequence tracking
- [ ] Monitor memory after restart

### Orphaned Connections

**Symptoms:**
- Multiple WebSocket connections to same endpoint
- Connection count exceeds expected
- Resource exhaustion (file descriptors, sockets)

**Detection:**
- [ ] Monitor active connection count
- [ ] Check for duplicate connection attempts
- [ ] Verify reconnect lock working
- [ ] Review connection lifecycle logs

**Recovery:**
- [ ] Force close all connections
- [ ] Restart bridge with clean state
- [ ] Verify single connection after restart
- [ ] Check for race conditions in reconnect

### Stale Data / Sequence Gaps

**Symptoms:**
- Orderbook not updating despite activity
- Price discrepancies between WS and REST
- Missed fills or trade updates

**Detection:**
- [ ] Monitor `_seq_gaps` counter
- [ ] Check `_last_seq` per market
- [ ] Verify snapshot refresh after gaps
- [ ] Compare WS vs REST prices

**Recovery:**
- [ ] Force REST snapshot refresh
- [ ] Clear orderbook cache
- [ ] Resubscribe to affected markets
- [ ] Verify sequence continuity

### Silent Latency Buildup

**Symptoms:**
- Gradual increase in message processing time
- Queue depth growing despite normal message rate
- Lag pause mode activating frequently

**Detection:**
- [ ] Track event-loop lag samples
- [ ] Monitor `_process_time_max` (worst-case handler)
- [ ] Check for slow callback patterns
- [ ] Profile message handlers

**Recovery:**
- [ ] Identify slow message handlers
- [ ] Offload heavy processing to worker threads
- [ ] Increase queue size if needed
- [ ] Consider message sampling under pressure

---

## Recovery Procedures

### Circuit Breaker Tripped

**Symptoms:**
- Log: "CIRCUIT-BREAKER TRIPPED"
- Reconnections blocked
- Fault manager circuit state = OPEN

**Recovery:**
1. Check fault manager state: `fm.get_venue_circuit_state("kalshi")`
2. Review failure history in logs
3. Identify root cause (auth, network, rate limit)
4. Fix root cause
5. Reset circuit breaker manually if needed
6. Monitor for recurrence

### Lag Pause Mode Active

**Symptoms:**
- Log: "ENTERING LAG PAUSE MODE"
- All WS reconnects suspended
- Event-loop lag > 6000ms

**Recovery:**
1. Check event-loop lag with `_get_event_loop_lag_ms()`
2. Identify blocking operations
3. Offload blocking work to thread pool
4. Reduce message processing complexity
5. Wait for lag to recover (< 3000ms)
6. Verify automatic exit from lag pause

### Queue Pressure Critical

**Symptoms:**
- Queue pressure > 90%
- Messages being dropped
- Log: "WS message queue full"

**Recovery:**
1. Check message processing rate
2. Identify slow consumer
3. Temporarily reduce subscription scope
4. Increase queue size if needed
5. Consider message sampling
6. Monitor after changes

---

## Maintenance Tasks

### Weekly (During Active Trading)

- [ ] Run WebSocket audit script
- [ ] Review connection metrics dashboard
- [ ] Check for sequence gap trends
- [ ] Verify memory usage stable
- [ ] Review error rate patterns
- [ ] Test failover to backup connection

### Monthly

- [ ] Full review of WebSocket logs
- [ ] Update audit script if new patterns found
- [ ] Review and tune queue sizes
- [ ] Verify circuit breaker thresholds
- [ ] Test reconnection under load
- [ ] Review Kalshi API changes

### Quarterly

- [ ] Load test with peak message rates
- [ ] Memory profiling under stress
- [ ] Review and update security patterns
- [ ] Audit authentication key rotation
- [ ] Review subscription scope optimization
- [ ] Update documentation

---

## Incident Response

### WebSocket Outage

**Severity:** CRITICAL  
**Response Time:** < 5 minutes

1. Check fault manager circuit state
2. Review WebSocket logs for errors
3. Verify Kalshi API status
4. Check network connectivity
5. Attempt manual reconnect
6. If failed, restart bridge
7. Escalate if outage > 15 minutes

### Data Quality Issue

**Severity:** HIGH  
**Response Time:** < 15 minutes

1. Check sequence gap counter
2. Compare WS vs REST prices
3. Verify orderbook freshness
4. Force REST snapshot refresh
5. Resubscribe to affected markets
6. Monitor for recurrence

### Performance Degradation

**Severity:** MEDIUM  
**Response Time:** < 30 minutes

1. Check event-loop lag
2. Review queue depth
3. Profile message handlers
4. Identify bottlenecks
5. Optimize or offload work
6. Monitor after changes

---

## Integration Points

### CI/CD Pipeline

Add to deployment pipeline:

```yaml
# Example GitHub Actions step
- name: WebSocket Health Audit
  run: |
    py scripts/audit_websocket_health.py
  # Fails deployment if CRITICAL findings
```

### Monitoring Dashboard

Key metrics to display:

- Connection status (connected/disconnected)
- Active connection count
- Message rate (msg/sec)
- Queue depth / pressure %
- Reconnect count (last hour)
- Event-loop lag (ms)
- Sequence gap count
- Circuit breaker state

### Alert Routing

- **CRITICAL:** PagerDuty / on-call
- **HIGH:** Slack #trading-alerts
- **MEDIUM:** Email daily digest
- **LOW:** Weekly report

---

## Quick Reference

### Audit Commands

```bash
# Quick audit
py scripts/audit_websocket_health.py

# Verbose audit
py scripts/audit_websocket_health.py --verbose

# JSON output
py scripts/audit_websocket_health.py --json
```

### Health Check Endpoints

```
GET /api/v1/system/health
GET /api/v1/kalshi/ws-bridge/health
```

### Key Configuration

```python
# Queue sizes
self._msg_queue: asyncio.Queue(maxsize=32768)
_BRIDGE_QUEUE_SIZE = 16384

# Reconnect settings
ping_interval = 20s
ping_timeout = 60s
_max_reconnect_delay = 60s

# Circuit breaker
_CIRCUIT_BREAKER_THRESHOLD = 20
_CIRCUIT_BREAKER_WINDOW_S = 60
_CIRCUIT_BREAKER_COOLDOWN_S = 15

# Subscription limits
_MAX_WS_SUBSCRIPTIONS = 150
_WS_CRITICAL_THRESHOLD = 120
```

### Log Patterns to Watch

```
# Critical
[CIRCUIT-BREAKER TRIPPED]
[EVENT-LOOP-FIX] ENTERING LAG PAUSE MODE
WS message queue full

# High
[WS-BRIDGE-CONNECT] Failed after 3 attempts
Sequence gap detected
Queue pressure critical

# Informational
Connected to Kalshi WebSocket
Reconnected successfully
```

---

## Change Log

| Date | Change | Impact |
|------|--------|--------|
| 2026-05-22 | Initial checklist creation | Baseline for WebSocket health monitoring |
