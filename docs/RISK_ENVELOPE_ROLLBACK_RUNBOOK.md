# Risk Envelope Rollback Runbook

## Overview

This runbook provides step-by-step procedures for rolling back the risk envelope implementation for the `kalshi_crypto_15m_v2` profile in production.

## Feature Flag

**Environment Variable**: `MERID_RISK_ENVELOPE_ENABLED`

- **Default**: `true` (envelope enabled)
- **Set to `false`**: Disables envelope, system falls back to legacy behavior
- **Scope**: Affects only `kalshi_crypto_15m_v2` profile

## Rollback Triggers

### When to Roll Back

Roll back the risk envelope if any of the following conditions occur:

1. **Envelope Mis-Computing Drawdown**
   - Symptoms: Drawdown percentage appears incorrect in logs/metrics
   - Evidence: Drawdown values don't match actual equity changes
   - Severity: P0 - Immediate rollback

2. **Runaway Halts**
   - Symptoms: Envelope halting too frequently (e.g., multiple times per hour)
   - Evidence: Kill switch triggered by drawdown halt repeatedly with small losses
   - Severity: P0 - Immediate rollback

3. **Incorrect Band Transitions**
   - Symptoms: Risk multiplier not changing as expected
   - Evidence: Band stays at 1.0 despite drawdown exceeding thresholds
   - Severity: P1 - Rollback within 1 sprint

4. **Bankroll Integration Failure**
   - Symptoms: Envelope not updating equity from bankroll service
   - Evidence: `safe_update_envelope_equity` returning False repeatedly
   - Severity: P1 - Rollback within 1 sprint

## Rollback Procedure

### Step 1: Verify Issue

Before rolling back, verify the issue is envelope-related:

```bash
# Check envelope status in logs
grep "RISK-ENVELOPE" /var/log/merid/app.log | tail -100

# Check envelope metrics
curl http://localhost:9090/api/v1/prometheus/query?query=risk_envelope_band

# Check drawdown percentage
curl http://localhost:9090/api/v1/prometheus/query?query=kalshi_drawdown_percentage
```

### Step 2: Disable Envelope via Feature Flag

Set environment variable to disable envelope:

```bash
# Option A: Update .env file
echo "MERID_RISK_ENVELOPE_ENABLED=false" >> /etc/merid/.env

# Option B: Set in deployment environment
export MERID_RISK_ENVELOPE_ENABLED=false

# Option C: Set via systemd service
systemctl set-environment MERID_RISK_ENVELOPE_ENABLED=false
```

### Step 3: Restart Services

Restart MERID services to apply the flag:

```bash
# Using systemd
sudo systemctl restart merid.service

# Or using PM2
pm2 restart merid

# Or using supervisor
supervisorctl restart merid
```

### Step 4: Verify Rollback

Confirm envelope is disabled:

```bash
# Check logs for envelope disabled message
grep "RISK-ENVELOPE" /var/log/merid/app.log | tail -20

# Expected log message:
# "[PROFILE-DRAWDOWN] Risk envelope disabled via MERID_RISK_ENVELOPE_ENABLED flag. Using legacy behavior for profile kalshi_crypto_15m_v2"

# Verify trading resumes (if halted)
curl http://localhost:8080/api/v1/kalshi/agents/BTC_15M
```

### Step 5: Monitor System

Monitor for 15-30 minutes after rollback:

- Check that agents are generating signals
- Verify orders are being placed
- Monitor drawdown via legacy metrics
- Check for any error logs

## Re-Enable Procedure

Once the issue is identified and fixed, re-enable the envelope:

### Step 1: Fix the Issue

Apply the fix to the envelope implementation (code change, config change, etc.).

### Step 2: Enable Envelope

```bash
# Set feature flag to true
echo "MERID_RISK_ENVELOPE_ENABLED=true" >> /etc/merid/.env

# Or export
export MERID_RISK_ENVELOPE_ENABLED=true
```

### Step 3: Restart Services

```bash
sudo systemctl restart merid.service
```

### Step 4: Verify Envelope Active

```bash
# Check logs for envelope initialization
grep "RISK-ENVELOPE" /var/log/merid/app.log | tail -20

# Expected log message:
# "[RISK-ENVELOPE] Effective capital: $..."

# Verify envelope metrics are updating
curl http://localhost:9090/api/v1/prometheus/query?query=risk_envelope_band
```

## Rollback Roles and Responsibilities

| Role | Responsibility |
|------|---------------|
| **On-Call Engineer** | Execute rollback steps, monitor system |
| **Tech Lead** | Approve rollback decision, coordinate fix |
| **DevOps** | Update environment variables, restart services |
| **Risk Manager** | Verify envelope behavior, assess trading impact |

## Emergency Contacts

- **On-Call Pager**: [INSERT PAGER NUMBER]
- **Tech Lead**: [INSERT EMAIL/PHONE]
- **DevOps**: [INSERT EMAIL/PHONE]

## Related Documentation

- [Risk Envelope Design](./RISK_ENVELOPE_DESIGN.md)
- [Profile Configuration](../config/profiles/kalshi_crypto_15m.yaml)
- [Startup Validations](../merid/startup_validations.py)
- [Audit Report](./RISK_ENVELOPE_AUDIT_REPORT.md)

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-05-17 | Initial runbook created | Risk Envelope Implementation |
