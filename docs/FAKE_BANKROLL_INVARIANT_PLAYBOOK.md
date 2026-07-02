# Fake Bankroll Invariant - Operations Playbook

## Overview

The `FAKE_BANKROLL_SOURCE_USED` invariant is a **CRITICAL** safeguard that prevents fake bankroll sources from being used in live trading profiles. This invariant ensures that only API-derived bankroll values from Kalshi are used for risk calculations and trading decisions.

## Invariant Behavior

### What Triggers the Invariant

The invariant fires **CRITICAL** when either condition is met in a **live profile**:

1. **Fake bankroll source detected**: `bankroll_source` in `{"fallback", "config", "manual", "test", "bootstrap", "default"}`
2. **Fake bankroll value detected**: `bankroll_value` in `{1000.0, 100000.0}` ($1000 or $1000 in cents)

### Profile Classification

- **Live profiles**: `kalshi_crypto_15m_v2`, `live_*`, `prod_*`, `production_*`
- **Test profiles**: `kalshi_crypto_test`, `test_*`, `sim_*`, `demo_*`, `paper_*`
- **Unknown profiles**: Default to **LIVE** (safe default)

### Environment Override

- `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=1` allows fake bankroll in **test profiles only**
- **NEVER** set this flag in production environments

## Log Patterns to Monitor

### Normal Operation (Expected)
```
[15M-EXECUTION-READY] execution_ready=True
  bankroll={
    'live_bankroll': 3681.25,
    'source': 'kalshi',
    'source_valid': True,
    'fake_used': False
  }

[E2E-AUDIT-SNAPSHOT] profile=kalshi_crypto_15m_v2 execution_ready=True reasons={none}
  bankroll_source=kalshi bankroll_source_valid=True fake_bankroll_used=False
```

### Fake Bankroll Detected (ALERT)
```
[FAKE-BANKROLL-INVARIANT] Fake bankroll source detected in live profile: source=fallback value=1000.00

[15M-EXECUTION-DEGRADED] execution_ready=False
  bankroll={
    'live_bankroll': 1000.0,
    'source': 'fallback',
    'source_valid': True,
    'fake_used': True
  }

[E2E-GUARDRAIL-TRIP] severity=CRITICAL violations={FAKE_BANKROLL_SOURCE_USED}
  bankroll_source=fallback bankroll_source_valid=False fake_bankroll_used=True
```

## Monitoring Commands

### Critical Alerts (Page Immediately)
```bash
# Any fake bankroll invariant in production
grep 'FAKE_BANKROLL_SOURCE_USED' logs/*.log

# Any execution without valid bankroll source
grep 'execution_ready=True.*bankroll_source_valid=False' logs/*.log
```

### Health Monitoring
```bash
# Bankroll source validation status
grep 'bankroll_source=\|bankroll_source_valid=\|fake_bankroll_used=' logs/*.log

# Guardrail trips involving bankroll
grep 'E2E-GUARDRAIL-TRIP.*bankroll' logs/*.log
```

### Trend Analysis
```bash
# Bankroll source distribution
grep 'bankroll_source=' logs/*.log | sort | uniq -c

# Profile classification verification
grep 'is_live_profile:' logs/*.log | tail -10
```

## Response Procedures

### 🚨 CRITICAL: FAKE_BANKROLL_SOURCE_USED Detected

**IMMEDIATE ACTIONS:**
1. **STOP TRADING** - Do not override or continue
2. **Investigate root cause** - Check why fake source appeared
3. **Fix bankroll source** - Ensure proper Kalshi API connectivity
4. **Verify fix** - Confirm logs show `bankroll_source=kalshi` or `bankroll_service_v2`

**DO NOT:**
- ❌ Override the invariant
- ❌ Set `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=1` in production
- ❌ Continue trading with fake bankroll
- ❌ Ignore the alert

### 🟡 WARNING: Bankroll Source Invalid but No Invariant

This can happen in test profiles or during configuration changes:

1. **Verify profile** - Confirm this is a test profile
2. **Check configuration** - Ensure proper Kalshi credentials
3. **Monitor** - Watch for resolution

### 📊 Ongoing Monitoring

**Daily Checks:**
- Verify no `FAKE_BANKROLL_SOURCE_USED` in production logs
- Confirm `bankroll_source` is always `kalshi` or `bankroll_service_v2`
- Check `bankroll_source_valid=True` in all execution-ready cycles

**Weekly Reviews:**
- Analyze bankroll source patterns
- Verify profile classification consistency
- Review any guardrail trips

## Testing Procedures

### Test Profile Development
```bash
# Allow fake bankroll for testing
export MERID_PROFILE=kalshi_crypto_test
export MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=1

# Verify test behavior
grep 'fake_bankroll_used=False' logs/*.log  # Should be False even with fake source
```

### Production Verification
```bash
# Confirm live profile behavior
export MERID_PROFILE=kalshi_crypto_15m_v2

# Verify no fake bankroll
grep 'FAKE_BANKROLL_SOURCE_USED' logs/*.log  # Should be empty
grep 'bankroll_source=kalshi\|bankroll_source=bankroll_service_v2' logs/*.log  # Should show valid sources
```

## Common Issues and Solutions

### Issue: "fallback" source appears in logs

**Cause**: Kalshi API unavailable or authentication failure
**Solution**: 
1. Check Kalshi API connectivity
2. Verify credentials (KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
3. Check network connectivity to Kalshi endpoints

### Issue: $1000 value detected

**Cause**: Bootstrap fallback or configuration error
**Solution**:
1. Verify `MERID_TOTAL_CAPITAL_USD` is not set to 1000.0
2. Check bankroll service initialization
3. Ensure proper Kalshi balance fetching

### Issue: Test profile still blocked

**Cause**: `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST` not set
**Solution**:
```bash
export MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=1
```

## Configuration Checklist

### Production Deployment
- [ ] `MERID_PROFILE` set to live profile (e.g., `kalshi_crypto_15m_v2`)
- [ ] `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST` is **NOT** set or set to `0`
- [ ] Kalshi credentials properly configured
- [ ] Monitoring alerts configured for `FAKE_BANKROLL_SOURCE_USED`

### Test Environment
- [ ] `MERID_PROFILE` set to test profile (e.g., `kalshi_crypto_test`)
- [ ] `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=1` if fake bankroll needed
- [ ] Test Kalshi credentials or mock bankroll service

## Escalation Path

1. **Level 1**: On-call engineer investigates logs and configuration
2. **Level 2**: System engineer checks Kalshi API connectivity and credentials
3. **Level 3**: Development team investigates bankroll service implementation

**Critical Response Time**: < 5 minutes for fake bankroll invariants in production

## Related Documentation

- [Bankroll Service V2 Documentation](./BANKROLL_SERVICE_V2_CONCURRENCY_AUDIT.md)
- [E2E Invariants Documentation](../merid/core/e2e_invariants.py)
- [15m Loop Execution Gate Documentation](../merid/loop_15m.py)

## Contact

For questions about this invariant:
- **Development**: Check implementation in `merid/core/e2e_invariants.py`
- **Operations**: Use monitoring commands above
- **Escalation**: Follow escalation path for critical alerts
