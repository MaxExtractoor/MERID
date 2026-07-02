# MERID Restart Report Template

**Date:** YYYY-MM-DD  
**Time:** HH:MM UTC  
**Operator:** [Your Name]  
**Restart Reason:** [e.g., deployment, crash, maintenance, config change]  
**Profile:** `kalshi_crypto_15m_v2`  
**Mode:** [PAPER/LIVE]

---

## Executive Summary

[Brief 2-3 sentence summary of the restart outcome - success/failure, key issues, current status]

---

## Pre-Restart Checklist

- [ ] Backup current configuration files
- [ ] Document current running state (cycle number, positions, bankroll)
- [ ] Verify Kalshi API credentials are valid
- [ ] Check rate limit status
- [ ] Review recent error logs
- [ ] Validate profile configuration (`validate_all_kalshi_15m()`)
- [ ] Confirm drift metrics are cleared/reset if needed

---

## Restart Procedure

### 1. Shutdown
```bash
# Command used to stop the system
# [Record any shutdown errors or warnings]
```

**Status:** ✓/✗  
**Notes:** [Any issues during shutdown]

### 2. Configuration Changes
**Files Modified:**
- [ ] `config/profiles/kalshi_crypto_15m.yaml`
- [ ] `config/kalshi_agent_grid.yaml`
- [ ] `.env`
- [ ] Other: `___________`

**Changes Made:**
```yaml
# Record specific configuration changes
```

### 3. Startup
```bash
# Command used to start the system
# [Record any startup errors or warnings]
```

**Startup Time:** ___ seconds  
**Status:** ✓/✗  
**Notes:** [Any issues during startup]

---

## Validation Results

### Startup Validations
- [ ] `validate_no_sentiment_in_kalshi_stack` - PASS/FAIL
- [ ] `validate_no_legacy_strategy_in_kalshi_stack` - PASS/FAIL
- [ ] `validate_catalog_refresh_interval` - PASS/FAIL
- [ ] `validate_profile_combination` - PASS/FAIL
- [ ] Other: `___________` - PASS/FAIL

### Infrastructure Checks
- [ ] Kalshi API connectivity - PASS/FAIL
- [ ] Redis connection (if used) - PASS/FAIL
- [ ] Catalog refresh successful - PASS/FAIL
- [ ] Market state store populated - PASS/FAIL
- [ ] Risk envelope service initialized - PASS/FAIL

### Logging Infrastructure
- [ ] STRATEGY_DECISION events emitting - PASS/FAIL
- [ ] Drift metrics collector active - PASS/FAIL
- [ ] Risk envelope drift collection - PASS/FAIL
- [ ] Data freshness violation tracking - PASS/FAIL
- [ ] Scheduler catalog mismatch tracking - PASS/FAIL

---

## Post-Restart Observations

### First Cycle (Cycle #___)
- **Start Time:** HH:MM:SS UTC
- **Duration:** ___ seconds
- **Markets Resolved:** ___
- **Signals Generated:** ___
- **Orders Submitted:** ___
- **Fills Received:** ___
- **Errors:** [List any errors]

### Subsequent Cycles
- **Cycle #___:** [Summary]
- **Cycle #___:** [Summary]

### Drift Metrics
- **Risk Envelope Violations:** ___
- **Data Freshness Violations:** ___
- **Scheduler Catalog Mismatches:** ___
- **Other Drift Alerts:** [List]

---

## Issues Encountered

### Issue #1: [Title]
**Severity:** [CRITICAL/HIGH/MEDIUM/LOW]  
**Description:**  
[Detailed description of the issue]

**Root Cause:**  
[What caused the issue]

**Resolution:**  
[How it was fixed]

**Prevention:**  
[How to prevent this in the future]

### Issue #2: [Title]
**Severity:** [CRITICAL/HIGH/MEDIUM/LOW]  
**Description:**  
[Detailed description of the issue]

**Root Cause:**  
[What caused the issue]

**Resolution:**  
[How it was fixed]

**Prevention:**  
[How to prevent this in the future]

---

## Performance Metrics

| Metric | Pre-Restart | Post-Restart | Delta |
|--------|-------------|--------------|-------|
| Cycle Duration (avg) | ___s | ___s | ___% |
| Catalog Refresh Time | ___s | ___s | ___% |
| Signal Generation Time | ___s | ___s | ___% |
| Risk Check Time | ___s | ___s | ___% |
| Order Submission Time | ___s | ___s | ___% |
| Memory Usage | ___MB | ___MB | ___% |
| CPU Usage | ___% | ___% | ___% |

---

## Configuration Snapshot

### Profile: `kalshi_crypto_15m_v2`
```yaml
# Key configuration values at time of restart
bankroll_usd: ___
per_trade_risk_pct: ___
max_cycle_risk_pct: ___
catalog_refresh_interval_s: ___
edge_computation_mode: "___"
```

### Environment Variables
```bash
MERID_PROFILE=kalshi_crypto_15m_v2
MERID_TRADING_MODE=PAPER
MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S=___
MERID_UNIFIED_EDGE_ENABLED=___
```

---

## Action Items

### Immediate (Next 24h)
- [ ] [Action item 1]
- [ ] [Action item 2]
- [ ] [Action item 3]

### Short-term (Next Week)
- [ ] [Action item 1]
- [ ] [Action item 2]

### Long-term (Next Sprint)
- [ ] [Action item 1]
- [ ] [Action item 2]

---

## Lessons Learned

1. [Lesson 1]
2. [Lesson 2]
3. [Lesson 3]

---

## Sign-off

**Restart Status:** ✓ SUCCESS / ✗ FAILED / ⚠ PARTIAL

**Recommendation:** [e.g., Safe to proceed, Monitor closely, Rollback required]

**Approved By:** ___________  
**Date:** YYYY-MM-DD

---

## Appendix

### Relevant Log Snippets
```log
# Paste important log lines here
```

### Error Messages
```
# Paste error messages here
```

### References
- [Link to related documentation]
- [Link to related tickets/issues]
- [Link to previous restart reports]
