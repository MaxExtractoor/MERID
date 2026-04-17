# MERID Operator Runbook

**Version**: 1.0  
**Last Updated**: 2026-02-04  
**Audience**: System operators, on-call engineers

---

## Quick Reference

### Emergency Commands

```bash
# HALT ALL TRADING IMMEDIATELY
make emergency-stop

# Check system status
make show-risk
make show-mode

# Reset after investigation (use with caution)
make reset-kill-switch
```

### Key Dashboards

| Dashboard | URL | Purpose |
|-----------|-----|---------|
| Risk Status | `http://localhost:8000/api/risk/status` | Kill switch state, daily P&L |
| Circuit Breakers | `http://localhost:8000/api/health/circuits` | Venue connectivity |
| Positions | `http://localhost:8000/api/positions` | Open positions |

---

## 1. Daily Operations

### 1.1 Morning Checklist

Before market open:

1. **Verify system health**
   ```bash
   make show-risk
   make show-mode
   ```

2. **Check overnight logs** for errors
   ```bash
   grep -i "error\|warning\|kill" logs/merid.log | tail -50
   ```

3. **Confirm circuit breakers are closed**
   ```python
   from merid.resilience import get_all_breakers
   for name, cb in get_all_breakers().items():
       print(f"{name}: {cb.state}")
   ```

4. **Verify daily P&L reset** (should be $0 at start of day)

### 1.2 During Trading Hours

Monitor these metrics:

- **Daily P&L** — Alert if approaching 80% of daily loss limit
- **Circuit breaker state** — Should be CLOSED for all venues
- **Error rate** — Sustained errors may indicate venue issues
- **Position sizes** — Watch for concentration risk

### 1.3 End of Day

1. Review daily P&L and trade count
2. Check for any triggered kill switches
3. Export trade log for reconciliation
4. Note any incidents for next shift

---

## 2. Common Failure Scenarios

### 2.1 Kill Switch Triggered: Daily Loss

**Symptoms**:
- Orders rejected with "risk kill switch triggered"
- `make show-risk` shows `state: triggered`, `kill_reason: daily_loss`

**Investigation**:
1. Review recent trades for unexpected losses
2. Check for pricing anomalies or bad fills
3. Verify P&L calculation is correct

**Resolution**:
```bash
# After investigation, if safe to resume:
make reset-kill-switch

# Or programmatically:
python -c "from merid.risk import risk_controller; risk_controller.reset('operator_name')"
```

**Prevention**: Tighten position limits, reduce order sizes

### 2.2 Kill Switch Triggered: Error Threshold

**Symptoms**:
- `kill_reason: error_threshold` in risk status
- Multiple failed API calls in logs

**Investigation**:
1. Check venue API status (Kalshi, Polymarket status pages)
2. Review error logs for specific failures
3. Verify API credentials are valid

**Resolution**:
1. Wait for venue to recover
2. Reset kill switch after confirming venue is healthy

### 2.3 Circuit Breaker Open

**Symptoms**:
- Specific venue operations fail immediately
- `CircuitOpenError` in logs

**Investigation**:
```python
from merid.resilience import get_circuit_breaker
cb = get_circuit_breaker("kalshi")
print(cb.get_stats())
# Shows: failure_count, time_until_retry
```

**Resolution**:
- Circuit will auto-recover after `recovery_timeout` (default 30s)
- Manual reset if needed:
  ```python
  cb.reset()
  ```

### 2.4 WebSocket Disconnection

**Symptoms**:
- Stale market data
- "Reconnecting in Xs..." messages in logs

**Investigation**:
1. Check network connectivity
2. Verify WebSocket endpoint is reachable
3. Check for rate limiting

**Resolution**:
- Auto-reconnect should handle this
- If persistent, restart the affected feed handler

### 2.5 Position Limit Exceeded

**Symptoms**:
- Orders rejected
- `kill_reason: position_limit` in risk status

**Investigation**:
1. Review current positions: `GET /api/positions`
2. Check if positions are correctly reported

**Resolution**:
1. Close positions to reduce exposure
2. Reset kill switch after reducing position size

---

## 3. Operational Procedures

### 3.1 Starting the System

```bash
# 1. Validate configuration
make validate-config

# 2. Run go-live dry run (paper mode)
make go-live-dry-run

# 3. Start in paper mode first
MERID_TRADING_MODE=paper python -m merid.main

# 4. After validation, switch to live (requires unlock)
MERID_TRADING_MODE=live MERID_LIVE_TRADING_UNLOCKED=true python -m merid.main
```

### 3.2 Graceful Shutdown

```bash
# 1. Stop accepting new orders
make emergency-stop

# 2. Wait for pending orders to complete (check logs)

# 3. Close open positions if needed

# 4. Stop the process
```

### 3.3 Switching Trading Modes

**Paper → Live**:
1. Stop system
2. Set `MERID_TRADING_MODE=live`
3. Set `MERID_LIVE_TRADING_UNLOCKED=true`
4. Restart with reduced limits initially

**Live → Paper** (emergency):
1. `make emergency-stop`
2. Stop system
3. Set `MERID_TRADING_MODE=paper`
4. Restart

### 3.4 Adjusting Risk Limits

Risk limits are configured via environment variables:

```bash
# Maximum single order size
export MERID_MAX_ORDER_SIZE_USD=100

# Maximum daily loss before kill switch
export MERID_MAX_DAILY_LOSS_USD=500

# Maximum position size per market
export MERID_MAX_POSITION_SIZE_USD=1000
```

After changing, restart the system.

---

## 4. Monitoring & Alerts

### 4.1 Key Metrics to Monitor

| Metric | Warning | Critical |
|--------|---------|----------|
| Daily P&L % | < -50% of limit | < -80% of limit |
| Circuit breaker trips | > 2 in 5 min | > 5 in 5 min |
| API error rate | > 5% | > 20% |
| Order latency | > 500ms | > 2000ms |

### 4.2 Log Patterns to Watch

```bash
# Kill switch events
grep "KILL SWITCH" logs/merid.log

# Circuit breaker state changes
grep "Circuit.*OPEN\|Circuit.*CLOSED" logs/merid.log

# Failed orders
grep "Order rejected\|order failed" logs/merid.log
```

### 4.3 Health Check Endpoint

```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "trading_mode": "paper",
  "risk_state": "active",
  "circuits": {
    "kalshi": "closed",
    "polymarket": "closed"
  }
}
```

---

## 5. Incident Response

### 5.1 Severity Levels

| Level | Description | Response Time |
|-------|-------------|---------------|
| P1 | Trading halted, potential loss | Immediate |
| P2 | Degraded performance | < 15 min |
| P3 | Non-critical issue | < 1 hour |
| P4 | Minor/cosmetic | Next business day |

### 5.2 Incident Template

```
INCIDENT: [Brief description]
SEVERITY: P1/P2/P3/P4
TIME DETECTED: [timestamp]
SYMPTOMS: [what was observed]
IMPACT: [trading halted/degraded/none]
ROOT CAUSE: [if known]
RESOLUTION: [steps taken]
FOLLOW-UP: [preventive measures]
```

### 5.3 Escalation Path

1. **On-call operator** — First response, can reset kill switches
2. **Engineering lead** — Code changes, config updates
3. **Trading lead** — Position decisions, loss approval

---

## 6. Reference

### 6.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MERID_TRADING_MODE` | `paper` | `paper` or `live` |
| `MERID_LIVE_TRADING_UNLOCKED` | `false` | Must be `true` for live |
| `MERID_MAX_ORDER_SIZE_USD` | `100` | Max single order |
| `MERID_MAX_DAILY_LOSS_USD` | `500` | Daily loss limit |
| `MERID_MAX_POSITION_SIZE_USD` | `1000` | Max position per market |

### 6.2 Useful Commands

```bash
# Show all risk/trading status
make show-risk && make show-mode

# Run smoke tests
make smoke-test

# Check coverage
make coverage

# Validate before deploy
make validate-config
```

### 6.3 Related Documentation

- `docs/GO_LIVE_CHECKLIST.md` — Pre-launch checklist
- `docs/RESILIENCE_MAP.md` — Failure modes and mitigations
- `docs/RESILIENT_VENUE_CLIENT_RECIPE.md` — Technical architecture
- `README.md` — Project overview

---

## Changelog

| Date | Author | Changes |
|------|--------|---------|
| 2026-02-04 | System | Initial version |
