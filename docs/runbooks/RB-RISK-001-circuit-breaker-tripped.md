# Runbook: Circuit Breaker Tripped

**ID**: RB-RISK-001  
**Severity**: SEV-1 (High)  
**Last Updated**: 2026-02-01

---

## Symptoms

- Dashboard shows 🔴 **"Circuit Open - Orders Blocked"**
- Trades being rejected with `"reason": "Circuit breaker open"`
- API response shows `circuit_breaker.state: "OPEN"`
- Error count at or above threshold (default: 5)

---

## Immediate Actions (< 5 minutes)

### 1. Verify Current State

```bash
curl -s http://localhost:8000/api/risk/protections | jq '.circuit_breaker'
```

Expected output if tripped:
```json
{
  "state": "OPEN",
  "state_color": "red",
  "error_count": 5,
  "threshold": 5,
  "opened_at": "2026-02-01T12:34:56Z"
}
```

### 2. Check System Health

```bash
# Overall health
curl -s http://localhost:8000/api/system/health | jq '.status'

# Recent events
curl -s http://localhost:8000/api/risk/protections | jq '.recent_events[-5:]'
```

### 3. Check Venue Status

```bash
# Kalshi health
curl -s http://localhost:8000/api/venues/kalshi/health

# Coinbase health
curl -s http://localhost:8000/api/venues/coinbase/health
```

---

## Investigation (5-15 minutes)

### Step 1: Identify Error Source

Check logs for recent errors:

```bash
# Recent errors in trading guard
grep -i "circuit\|breaker\|error" logs/trading.log | tail -20

# Venue-specific errors
grep -i "timeout\|connection\|5xx" logs/venues.log | tail -20
```

Common causes:
| Pattern | Likely Cause | Action |
|---------|--------------|--------|
| `TimeoutError` | Venue API slow/down | Check venue status page |
| `ConnectionError` | Network issue | Check connectivity |
| `HTTP 5xx` | Venue internal error | Check venue status page |
| `RateLimitError` | Too many requests | Reduce request rate |

### Step 2: Determine Scope

```bash
# Are all venues affected or just one?
curl -s http://localhost:8000/api/venues/status | jq '.venues | map({name: .name, status: .status})'
```

### Step 3: Check Recent Deployments

```bash
# Any recent code changes?
git log --oneline -10

# Any configuration changes?
git diff HEAD~5 -- *.yaml *.yml *.json
```

---

## Resolution Options

### Option A: Wait for Auto-Recovery (Recommended if cause resolved)

**When to use**: Issue was transient (network blip, venue recovered)

**Procedure**:
1. Confirm venue/network is healthy
2. Wait `cooldown_seconds` (default: 300s / 5 min)
3. System automatically enters HALF_OPEN
4. Monitor for successful test requests
5. Circuit closes automatically after `half_open_max` successes

**Monitor**:
```bash
watch -n 5 'curl -s http://localhost:8000/api/risk/protections | jq ".circuit_breaker.state"'
```

### Option B: Manual Reset (If confident issue is resolved)

**When to use**: Root cause identified and fixed, don't want to wait

**⚠️ WARNING**: Only reset if you're certain the underlying issue is resolved

**Procedure**:

1. **Via Dashboard**:
   - Navigate to Risk & Protections panel
   - Click "Reset Circuit Breaker" button
   - Confirm in dialog

2. **Via API**:
   ```bash
   curl -X POST http://localhost:8000/api/risk/circuit-breaker/reset
   ```

3. **Verify reset**:
   ```bash
   curl -s http://localhost:8000/api/risk/protections | jq '.circuit_breaker.state'
   # Should return: "CLOSED"
   ```

### Option C: Emergency Lockdown (If uncertain)

**When to use**: Can't determine cause, want to stop all trading

**Procedure**:
1. Enable kill switch: `POST /api/risk/kill-switch/enable`
2. Investigate thoroughly
3. Fix underlying issue
4. Disable kill switch when confident

---

## Verification

After resolution:

1. **Test a small trade** (if in simulation mode)
2. **Monitor error count** stays at 0
3. **Check circuit state** remains CLOSED
4. **Review logs** for 10 minutes post-recovery

```bash
# Verify circuit closed
curl -s http://localhost:8000/api/risk/protections | jq '.circuit_breaker.state' | grep -q "CLOSED" && echo "✅ Circuit closed" || echo "❌ Still open"

# Verify no new errors
curl -s http://localhost:8000/api/risk/protections | jq '.circuit_breaker.error_count' | grep -q "0" && echo "✅ No errors" || echo "❌ Errors present"
```

---

## Post-Incident

### Within 1 Hour

- [ ] Document incident in logbook
- [ ] Update status page if customer-facing
- [ ] Notify stakeholders if prolonged (>15 min)

### Within 24 Hours

- [ ] Root cause analysis
- [ ] Adjust thresholds if needed (see Policy §11)
- [ ] Update monitoring/alerting if gaps found

### Questions to Answer

1. What caused the errors? (venue, network, code, config)
2. Could we have caught this earlier?
3. Should we adjust the threshold or window?
4. Do we need better venue health checks?

---

## Prevention

### Tune Circuit Breaker

If tripping too frequently:

```python
# Increase threshold or window
TradingGuardConfig(
    circuit_breaker_threshold=10,        # Was 5
    circuit_breaker_window_seconds=120,  # Was 60
)
```

### Improve Venue Health Checks

- Reduce detection time for venue issues
- Add more granular health metrics
- Implement venue-specific circuit breakers

### Add Predictive Alerts

Alert when approaching threshold:
```python
if error_count >= threshold * 0.8:
    send_alert("Circuit breaker approaching threshold")
```

---

## Escalation

| Time | Action | Contact |
|------|--------|---------|
| 0 min | Start runbook | On-call engineer |
| 15 min | Escalate if unresolved | Senior engineer |
| 30 min | Escalate to team lead | Risk team lead |
| 1 hour | Executive notification | CTO/CEO |

---

## Related

- [Policy: Circuit Breaker](../RISK_POLICY.md#3-circuit-breaker)
- [Runbook: Emergency Lockdown](./RB-RISK-002-emergency-lockdown.md)
- [Runbook: Venue Failure](./RB-RISK-003-venue-failure.md)
