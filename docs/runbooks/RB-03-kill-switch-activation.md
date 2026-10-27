# RB-3: Kill-Switch Activation

**Alert:** `merid_kill_switch_active == 1` or `merid_kill_switch_activations_total > 0`

**SEVERITY: CRITICAL - IMMEDIATE OPERATOR ATTENTION REQUIRED**

## Symptoms

- Critical alert fired (page/SMS)
- Log: `{"event_type": "KILL_SWITCH", "severity": "critical"}`
- All trading halted (orders rejected)
- `merid_kill_switch_active` metric == 1
- System returns errors on all order endpoints

## Impact

- **Complete trading halt**
- No new positions can be opened
- Existing positions remain (not liquidated)
- Manual intervention required to resume

## DO NOT

- ❌ Immediately restart the application
- ❌ Bypass or disable the kill switch without investigation
- ❌ Resume trading without root cause analysis
- ❌ Skip test suite verification

## Investigation

### Step 1: Identify Trigger Reason

```bash
# Get kill switch details
jq 'select(.event_type == "KILL_SWITCH") | {timestamp, reason, severity, source, details}' \
  /var/log/merid/app.log | tail -1

# Example output:
# {
#   "timestamp": "2026-04-23T14:30:00Z",
#   "reason": "Executor contract violation: order_router unavailable in non-SIM mode",
#   "severity": "critical",
#   "source": "kalshi_api.place_order",
#   "details": {"error": "ImportError: No module named 'order_router'"}
# }
```

### Step 2: Determine Cause Category

| Trigger Source | Likely Cause | Investigation Focus |
|---------------|--------------|---------------------|
| `kalshi_api.place_order` | Executor failure / import error | Check `order_router` imports |
| `startup` | Config violation | Check `enforce_at_startup()` logs |
| `manual` | Operator triggered | Check who triggered and why |
| `risk_manager` | Risk limit breach | Check exposure, bankroll |

### Step 3: Gather Context

```bash
# Logs 5 minutes before trigger
grep -B100 "KILL_SWITCH" /var/log/merid/app.log | head -150

# Recent errors
grep "ERROR\|CRITICAL" /var/log/merid/app.log | tail -20

# System state
jq 'select(.timestamp > "2026-04-23T14:00:00Z")' /var/log/merid/app.log | \
  jq -s 'group_by(.event_type) | map({type: .[0].event_type, count: length})'
```

## Remediation by Cause

### Cause A: Executor Import Failure

**If:** Kill switch triggered because `order_router` unavailable

1. **Fix import issue** (see RB-2 for details)
2. **Verify fix:**
   ```bash
   python -c "from merid.event_venues.kalshi.order_router import get_order_router; print('OK')"
   ```

3. **Run full validation:**
   ```bash
   pytest tests/scenario/test_pass9_scenarios.py -v
   # MUST pass: 17/17
   ```

4. **Reset with approval:**
   ```bash
   # Get on-call approval first!
   python -c "
   from merid.risk.kill_switches import get_kill_switch
   ks = get_kill_switch()
   ks.reset(
       reason='Import fixed, all tests pass. On-call approval: [NAME]',
       approved_by='[NAME]'
   )
   "
   ```

### Cause B: Config Violation

**If:** Startup enforcement failed

1. **Check specific violation:**
   ```bash
   grep "RiskConfigViolationError" /var/log/merid/startup.log
   ```

2. **Fix config:**
   - Reduce `max_risk_pct_global` to ≤0.02 (2%)
   - Remove `max_total_notional_usd` for live/paper mode

3. **Verify config:**
   ```bash
   python -c "
   from merid.config.unified_risk_enforcement import enforce_at_startup
   enforce_at_startup()
   print('Config valid')
   "
   ```

4. **Restart and validate:**
   ```bash
   # Restart
   python -m web.main
   
   # Check startup logs
   grep "STARTUP_ENFORCEMENT" /var/log/merid/startup.log
   # Expected: success
   ```

5. **Reset kill switch** (if not auto-cleared)

### Cause C: Manual Trigger

**If:** Operator intentionally triggered

1. **Verify trigger reason:**
   ```bash
   jq 'select(.event_type == "KILL_SWITCH") | .details.trigger_reason' \
     /var/log/merid/app.log | tail -1
   ```

2. **Confirm issue resolved:**
   - If external issue (market halt, etc.), confirm resolved
   - If internal issue, verify fix applied

3. **Get second approval:**
   - Original triggerer: [NAME]
   - Reset approver: Must be different person

4. **Reset:**
   ```bash
   python -c "
   from merid.risk.kill_switches import get_kill_switch
   ks = get_kill_switch()
   ks.reset(
       reason='External issue resolved. Original trigger: [NAME], Reset approval: [NAME2]',
       triggered_by='[NAME]',
       approved_by='[NAME2]'
   )
   "
   ```

### Cause D: Unknown

**If:** Reason unclear

1. **Preserve evidence:**
   ```bash
   cp /var/log/merid/app.log /var/log/merid/app.log.incident-$(date +%Y%m%d-%H%M%S)
   ```

2. **Full system review:**
   - Check all recent deployments
   - Review config changes
   - Check infrastructure status

3. **Escalate to platform team**

4. **Do NOT reset until root cause identified**

## Verification (Required Before Resume)

### Mandatory Checks

```bash
# 1. All scenario tests passing
pytest tests/scenario/test_pass9_scenarios.py -v
# Result: 17 passed

# 2. CI invariants passing
python scripts/ci/check_kalshi_invariants.py
# Result: All invariants verified

# 3. Health check
curl /api/v1/health | jq
# Result: {"status": "ok", "kill_switch": {"active": false}}

# 4. Metrics
curl http://localhost:9100/metrics | grep merid_kill_switch_active
# Result: 0

# 5. Test order
curl -X POST /api/v1/kalshi/orders -d '{...}'
# Result: 200 OK (or risk rejection, not kill-switch block)
```

### Sign-off Required

Before resuming trading:

- [ ] Root cause identified and fixed
- [ ] All 17 scenario tests passing
- [ ] All 8 CI invariants passing
- [ ] On-call engineer approval (for automated triggers)
- [ ] Second engineer approval (for manual triggers)
- [ ] Incident post-mortem scheduled (if warranted)

## Prevention

### Monitoring

```yaml
# Add to alerting rules
- alert: KillSwitchActive
  expr: merid_kill_switch_active == 1
  for: 0s  # Immediate
  labels:
    severity: critical
  annotations:
    summary: "Trading halted - kill switch active"

- alert: HighGuardTripRate
  expr: rate(merid_guard_trips_total[5m]) > 0.1
  labels:
    severity: warning
  annotations:
    summary: "Elevated guard trip rate - possible system issue"
```

### Process

- Run full test suite before any production deployment
- Require two-person approval for manual kill switch resets
- Post-incident review within 24 hours

## Escalation

**Immediate:**
- #on-call: All kill switch activations
- #risk-engineering: If unclear if safe to resume

**Within 1 hour:**
- #platform-engineering: If root cause unknown
- #executive: If trading halted > 1 hour during market hours

## Related

- Kill switch module: `merid/risk/kill_switches.py`
- Tests: `tests/scenario/test_pass9_scenarios.py::test_kill_switch_triggered`
- Metric: `merid_kill_switch_activations_total`
