# Runbook: Emergency Lockdown / Kill Switch

**ID**: RB-RISK-002  
**Severity**: SEV-1 (High) / SEV-0 (Critical)  
**Last Updated**: 2026-02-01

---

## When to Use

**Immediate lockdown required when**:
- Suspected account compromise or unauthorized access
- Runaway trading algorithm generating excessive orders
- Flash crash or market panic conditions
- Regulatory intervention or compliance hold
- Critical bug causing incorrect trading decisions
- Any situation where "stop everything now" is the safest choice

---

## Immediate Actions (< 2 minutes)

### 1. Activate Kill Switch

**Option A: Dashboard (Fastest)**
1. Navigate to main dashboard
2. Locate "Risk Protections" card
3. Click **"EMERGENCY LOCKDOWN"** button
4. Confirm in dialog: "EMERGENCY LOCKDOWN: This will BLOCK all trading immediately. Confirm?"
5. Click **"Yes, Lock Down Trading"**

**Option B: API**
```bash
curl -X POST http://localhost:8000/api/risk/kill-switch/enable
```

**Option C: Code (Emergency)**
```python
from trading.guards.trading_guard import TradingGuard

guard = TradingGuard()
guard.config.enable_trading_suite = False
print("🚨 KILL SWITCH ACTIVATED 🚨")
```

### 2. Verify Lockdown

```bash
curl -s http://localhost:8000/api/risk/protections | jq '.lockdown'
```

Expected:
```json
{
  "trading_suite_enabled": false,
  "global_mode": "simulation",
  "spectator_mode": true,
  "lockdown_reason": "Trading suite disabled via kill switch"
}
```

**Dashboard verification**:
- Risk Protections card shows 🔴 "TRADING DISABLED"
- Status banner shows "Lockdown Active"

### 3. Test Block is Working

Attempt a test trade (should be blocked):
```bash
curl -X POST http://localhost:8000/api/trading/submit \
  -H "Content-Type: application/json" \
  -d '{"venue": "kalshi", "symbol": "TEST", "side": "buy", "quantity": 1}'
```

Expected response:
```json
{
  "status": "BLOCK",
  "reason": "Trading suite disabled via kill switch"
}
```

---

## Investigation (2-30 minutes)

### Step 1: Preserve State

```bash
# Capture current state
curl -s http://localhost:8000/api/risk/protections > /tmp/lockdown-state-$(date +%s).json

# Copy recent logs
cp logs/trading.log /tmp/trading-$(date +%s).log
cp logs/venues.log /tmp/venues-$(date +%s).log
```

### Step 2: Identify Trigger

Review what happened immediately before lockdown:

```bash
# Last trades before lockdown
grep "submit_trade" logs/trading.log | tail -20

# Position changes
grep "position_update" logs/portfolio.log | tail -10

# Any errors or anomalies
grep -i "error\|warning\|critical" logs/*.log | tail -50
```

### Step 3: Assess Impact

```bash
# Current positions
curl -s http://localhost:8000/api/portfolio/positions

# P&L impact
curl -s http://localhost:8000/api/risk/pnl-summary

# Open orders (should be few/none if lockdown worked)
curl -s http://localhost:8000/api/orders/open
```

---

## Common Scenarios

### Scenario A: Runaway Algorithm

**Signs**:
- High order submission rate
- Same symbol repeatedly
- Unusual position sizes

**Actions**:
1. ✅ Lockdown already active
2. Cancel any pending orders: `POST /api/orders/cancel-all`
3. Review algorithm logs for loops/recursion
4. Check for market data feed issues causing bad signals

### Scenario B: Suspicious Activity

**Signs**:
- Orders from unknown strategies
- Unusual venues or symbols
- Off-hours trading

**Actions**:
1. ✅ Lockdown already active
2. Check authentication logs: `grep "login\|auth" logs/security.log`
3. Rotate API keys if compromise suspected
4. Review access logs for unauthorized access

### Scenario C: Market Flash Crash

**Signs**:
- Sudden P&L drop
- Market-wide price movements
- Increased volatility

**Actions**:
1. ✅ Lockdown already active (good)
2. Check market data: `curl /api/market/status`
3. Review if any positions were liquidated
4. Assess when to resume (may wait for market stabilization)

---

## Recovery

### When to Resume

**Checklist before disabling kill switch**:
- [ ] Root cause identified and addressed
- [ ] No unauthorized access detected (if security-related)
- [ ] Algorithm bug fixed and tested (if code-related)
- [ ] Market conditions stabilized (if market-related)
- [ ] Team consensus on resuming

### Disable Kill Switch

**Option A: Dashboard**
1. Navigate to Risk & Protections panel
2. Click **"Disable Kill Switch"** button
3. Confirm in dialog
4. Verify status changes to 🟢 "Trading Enabled"

**Option B: API**
```bash
curl -X POST http://localhost:8000/api/risk/kill-switch/disable
```

**Verification**:
```bash
curl -s http://localhost:8000/api/risk/protections | jq '.lockdown.trading_suite_enabled'
# Should return: true
```

### Gradual Recovery

1. **Start in simulation mode**:
   ```bash
   curl -X POST /api/config/mode -d '{"mode": "simulation"}'
   ```

2. **Test with small trade**:
   ```bash
   curl -X POST /api/trading/submit -d '{...small test order...}'
   ```

3. **Monitor for 10 minutes**:
   - Watch error rates
   - Verify P&L tracking correctly
   - Confirm circuit breaker healthy

4. **Enable live trading** (if appropriate):
   ```bash
   curl -X POST /api/config/mode -d '{"mode": "live"}'
   ```

---

## Post-Lockdown Review

### Immediate (within 1 hour)

Document the incident:
```markdown
## Lockdown Incident Report

**Date**: YYYY-MM-DD HH:MM  
**Duration**: X minutes  
**Triggered by**: [Name/Alert/System]  

**Reason for Lockdown**: 
[Description]

**Impact**:
- Positions affected: [List]
- P&L impact: $X
- Orders blocked: N

**Resolution**:
[What was fixed]

**Lessons Learned**:
- 
-
```

### Within 24 Hours

- [ ] Root cause analysis completed
- [ ] Fix implemented and tested
- [ ] Monitoring/alerting improved if needed
- [ ] Team debrief conducted
- [ ] Documentation updated

---

## Prevention

### Add Pre-Lockdown Alerts

Alert before needing emergency lockdown:
```python
# High order rate alert
if orders_per_minute > threshold:
    alert("Unusually high order rate - potential runaway algorithm")

# Position concentration alert
if position_pct_of_equity > 0.5:
    alert("Position exceeds 50% of equity - review immediately")
```

### Circuit Breaker as First Line

Circuit breaker may prevent need for manual lockdown:
- Configure appropriate thresholds
- Monitor for frequent trips (indicates underlying issue)
- Consider auto-lockdown after N circuit trips in M minutes

### Access Controls

- Limit who can disable kill switch
- Require MFA for kill switch disable
- Log all kill switch actions with audit trail

---

## Escalation

| Scenario | Action | Contact |
|----------|--------|---------|
| Security breach | Page security team + CTO | security@merid.io |
| Regulatory issue | Page compliance + legal | compliance@merid.io |
| Major bug | Page engineering leads | eng-leads@merid.io |
| Market event | Page risk committee | risk-committee@merid.io |

---

## Related

- [Policy: Kill Switch / Lockdown](../RISK_POLICY.md#4-kill-switch--lockdown)
- [Runbook: Circuit Breaker Tripped](./RB-RISK-001-circuit-breaker-tripped.md)
- [Security Incident Response](./RB-SEC-001-security-incident.md)
