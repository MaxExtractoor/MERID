# Runbook: Post-Incident Recovery

**ID**: RB-RISK-003  
**Severity**: SEV-2 (Medium)  
**Last Updated**: 2026-02-01

---

## Purpose

Standard procedure for safely resuming trading after any incident that caused:
- Circuit breaker trip
- Kill switch activation
- Venue disconnection
- Extended downtime

---

## Prerequisites

Before starting recovery:
- [ ] Root cause identified and documented
- [ ] Fix implemented and tested in non-production
- [ ] No active security incidents
- [ ] Team lead approval for recovery
- [ ] Monitoring and alerting verified working

---

## Recovery Steps

### Phase 1: System Health Verification (5 min)

#### 1.1 Check Overall Health

```bash
# System health
curl -s http://localhost:8000/api/system/health | jq '.'

# Expected: {"status": "healthy", "services": {...}}
```

#### 1.2 Verify Risk Protections

```bash
curl -s http://localhost:8000/api/risk/protections | jq '.'
```

Verify:
- `circuit_breaker.state`: "CLOSED"
- `lockdown.trading_suite_enabled`: true
- No recent error spikes

#### 1.3 Check Venue Connectivity

```bash
# Test all venues
for venue in kalshi coinbase; do
  echo "Testing $venue..."
  curl -s http://localhost:8000/api/venues/$venue/health | jq -r '.status'
done
```

---

### Phase 2: Simulation Mode Testing (10 min)

#### 2.1 Enable Simulation Mode

```bash
curl -X POST http://localhost:8000/api/config/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "simulation", "spectator_mode": true}'
```

#### 2.2 Submit Test Trades

```bash
# Small test trade per venue
for venue in kalshi coinbase; do
  echo "Testing $venue..."
  curl -X POST http://localhost:8000/api/trading/submit \
    -H "Content-Type: application/json" \
    -d "{\"venue\": \"$venue\", \"symbol\": \"TEST\", \"side\": \"buy\", \"quantity\": 0.01, \"price\": 0.50}"
  echo
done
```

Expected: All trades return `status: "SIMULATE"`

#### 2.3 Verify Risk Tracking

```bash
# Check risk metrics updated
curl -s http://localhost:8000/api/risk/pnl-summary
curl -s http://localhost:8000/api/risk/protections | jq '.risk_limits'
```

Verify:
- P&L tracking correctly
- Risk limits being enforced
- No unexpected warnings

#### 2.4 Monitor for 5 Minutes

Watch logs for errors:
```bash
tail -f logs/trading.log | grep -i "error\|warning"
```

Should see: No errors or warnings

---

### Phase 3: Limited Live Trading (15 min)

#### 3.1 Enable Live Mode (Small Limits)

```bash
# Set conservative limits
curl -X POST http://localhost:8000/api/config/guard-limits \
  -H "Content-Type: application/json" \
  -d '{
    "max_notional_usd": 1000,
    "max_position_pct": 5,
    "circuit_breaker_threshold": 3
  }'
```

#### 3.2 Enable Live Mode

```bash
curl -X POST http://localhost:8000/api/config/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "live", "spectator_mode": false, "allow_live_trades": true}'
```

#### 3.3 Execute Small Live Trade

```bash
# Single small trade
curl -X POST http://localhost:8000/api/trading/submit \
  -H "Content-Type: application/json" \
  -d '{
    "venue": "kalshi",
    "symbol": "PRES-2024-DEM",
    "side": "buy",
    "quantity": 1,
    "price": 0.60,
    "notional_usd": 0.60
  }'
```

Expected: `status: "ALLOW"`, executes successfully

#### 3.4 Verify Execution

```bash
# Check order status
curl -s http://localhost:8000/api/orders/recent | jq '.[0]'

# Verify position updated
curl -s http://localhost:8000/api/portfolio/positions | jq '.[] | select(.symbol == "PRES-2024-DEM")'
```

#### 3.5 Monitor Metrics

Watch for 10 minutes:
- Circuit breaker error count: Should remain 0
- P&L: Should track correctly
- No venue errors

```bash
# Check every 30 seconds
while true; do
  curl -s http://localhost:8000/api/risk/protections | jq -r '[.timestamp, .circuit_breaker.state, .circuit_breaker.error_count] | @tsv'
  sleep 30
done
```

---

### Phase 4: Normal Operations (5 min)

#### 4.1 Restore Normal Limits

```bash
# Restore standard configuration
curl -X POST http://localhost:8000/api/config/guard-limits \
  -H "Content-Type: application/json" \
  -d '{
    "max_notional_usd": 25000,
    "max_position_pct": 20,
    "circuit_breaker_threshold": 5
  }'
```

#### 4.2 Enable All Strategies

```bash
# Resume normal trading
curl -X POST http://localhost:8000/api/trading/resume
```

#### 4.3 Final Verification

```bash
# Complete system check
echo "=== System Health ==="
curl -s http://localhost:8000/api/system/health | jq -r '.status'

echo "=== Circuit Breaker ==="
curl -s http://localhost:8000/api/risk/protections | jq -r '.circuit_breaker.state'

echo "=== Trading Mode ==="
curl -s http://localhost:8000/api/risk/protections | jq -r '.lockdown.global_mode'

echo "=== Active Strategies ==="
curl -s http://localhost:8000/api/agents/summary | jq -r '.summary.healthy'
```

---

## Validation Checklist

Before declaring recovery complete:

- [ ] All health checks pass
- [ ] Circuit breaker state is CLOSED
- [ ] Kill switch is disabled
- [ ] At least one test trade executed successfully
- [ ] Positions tracking correctly
- [ ] P&L updating correctly
- [ ] No errors in logs for 10 minutes
- [ ] All venues responding normally
- [ ] Risk limits enforced correctly

---

## Rollback Procedure

If issues detected during recovery:

### Immediate Rollback (< 1 min)

```bash
# 1. Re-enable kill switch
curl -X POST http://localhost:8000/api/risk/kill-switch/enable

# 2. Verify
curl -s http://localhost:8000/api/risk/protections | jq '.lockdown.trading_suite_enabled'
# Should return: false
```

### Investigation

1. Capture state: `curl /api/risk/protections > /tmp/rollback-state.json`
2. Review logs for new errors
3. Determine if issue is related to original incident or new problem

### Re-Recovery

1. Fix new issues
2. Return to Phase 1
3. Be more conservative in limits

---

## Communication

### Internal

| Phase | Action | Audience |
|-------|--------|----------|
| Start recovery | Slack #trading-ops | Trading team |
| Phase 2 complete | Slack #trading-ops | Trading team |
| Phase 3 complete | Slack #general | All engineering |
| Recovery complete | Email to stakeholders | Business + mgmt |

### External (if customer-facing)

- Update status page: "Trading systems recovering"
- Post to status.merid.io
- Tweet if major incident

---

## Timeline Expectations

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Health check | 5 min | 5 min |
| Simulation testing | 10 min | 15 min |
| Limited live | 15 min | 30 min |
| Normal ops | 5 min | 35 min |

**Total expected time**: 30-40 minutes from start to full recovery

---

## Automation

Consider automating Phase 1 and 2:

```python
# recovery_script.py
import requests
import time

def run_recovery():
    # Phase 1
    if not check_health():
        raise Exception("Health check failed")
    
    # Phase 2
    enable_simulation_mode()
    submit_test_trades()
    time.sleep(300)  # 5 min monitoring
    
    if check_for_errors():
        raise Exception("Errors detected in simulation")
    
    # Phase 3
    enable_live_mode_limited()
    submit_small_live_trade()
    time.sleep(600)  # 10 min monitoring
    
    # Phase 4
    restore_normal_limits()
    print("Recovery complete!")
```

---

## Related

- [Runbook: Circuit Breaker Tripped](./RB-RISK-001-circuit-breaker-tripped.md)
- [Runbook: Emergency Lockdown](./RB-RISK-002-emergency-lockdown.md)
- [Policy: Risk Limits](../RISK_POLICY.md#2-risk-guardrails)
