# First Hour Observability Checklist

## Overview
This checklist defines what to monitor in the first 1-2 hours after deployment restart.

## Pre-Deployment (T-5 min)

### System State
- [ ] Note current system state (running/stopped)
- [ ] Note current regime (SIM/LIVE_SAFE/LIVE_FULL)
- [ ] Note current unified edge status (enabled/disabled)
- [ ] Note current calibration version
- [ ] Backup current `.env` file
- [ ] Backup current logs

### Team Readiness
- [ ] Team available for monitoring
- [ ] Rollback procedure documented
- [ ] Emergency contact list ready
- [ ] Monitoring tools ready

---

## T+0: Deployment (0-15 min)

### Startup Validation
- [ ] System starts successfully
- [ ] `[DEPLOYMENT-REGIME]` log shows correct regime
- [ ] `[SPOT-PROXY-VALIDATION]` log passes
- [ ] `[UNIFIED-EDGE-VALIDATION]` log passes
- [ ] `[CALIBRATION-LOGGER]` log shows enabled
- [ ] No startup errors in logs

### Configuration Verification
- [ ] `MERID_DEPLOYMENT_REGIME` is correct (SIM/LIVE_SAFE/LIVE_FULL)
- [ ] `MERID_UNIFIED_EDGE_ENABLED` is correct
- [ ] `MERID_CALIBRATION_VERSION` is correct
- [ ] `MERID_LIVE_SESSION_MAX_RISK_USD` is correct
- [ ] `MERID_RISK_BUDGET_MULTIPLIER` is correct
- [ ] `CFB_ALLOW_COMPOSITE_FALLBACK` is correct
- [ ] `CALIBRATION_DATA_LOGGING_ENABLED` is correct

### Process Verification
- [ ] Process is running
- [ ] Process is consuming reasonable CPU
- [ ] Process is consuming reasonable memory
- [ ] No zombie processes
- [ ] No crash loops

### Stop and Investigate Triggers
- System fails to start
- Startup validation fails
- Configuration values incorrect
- Process crashes immediately
- CPU/memory usage abnormal

---

## T+15 min: Signal Generation (15-30 min)

### Per-Asset Signal Check
For each asset (BTC, ETH, SOL, XRP, DOGE):
- [ ] At least one `[SIGNAL]` event logged
- [ ] Non-zero attempts at `UnifiedEdgeComputer`
- [ ] At least one `[RISK-DECISION]` outcome
- [ ] Signal count is reasonable (not zero, not excessive)

### Signal Quality Check
- [ ] Edge values are reasonable (0.01-0.10 range)
- [ ] Confidence values are reasonable (0.5-0.9 range)
- [ ] No NaN/None in signal fields
- [ ] No extreme edge values (> 0.50 or < -0.50)
- [ ] No extreme confidence values (> 1.0 or < 0.0)

### Signal Parity Check
- [ ] All 5 assets have signals
- [ ] Signal counts are similar across assets (within 2x)
- [ ] No asset has zero signals while others have many
- [ ] No asset has excessive signals (> 10x others)

### Stop and Investigate Triggers
- No signals for any asset
- No signals for specific asset while others have many
- Extreme edge values
- NaN/None in signal fields
- Signal counts highly imbalanced

---

## T+30 min: Order Flow (30-45 min)

### Order Generation Check (if LIVE_SAFE or LIVE_FULL)
- [ ] At least a trickle of small orders
- [ ] Orders in 15m crypto series (KXBTC15M, KXETH15M, etc.)
- [ ] Order sizes are reasonable (1-10 contracts)
- [ ] Order prices are reasonable (near mid price)
- [ ] No rejected orders due to risk caps

### Order Quality Check
- [ ] Order sides are reasonable (YES/NO)
- [ ] Order timing is reasonable (not at expiry)
- [ ] Order spread is reasonable (< 5 cents)
- [ ] No orders at extreme prices
- [ ] No orders with zero size

### Fill Check (if LIVE_SAFE or LIVE_FULL)
- [ ] At least some fills in 15m crypto series
- [ ] Fill prices are reasonable
- [ ] Fill sizes match order sizes
- [ ] No rejected fills
- [ ] No partial fills (unless expected)

### Stop and Investigate Triggers
- No orders generated (if LIVE_SAFE/LIVE_FULL)
- Orders rejected due to risk caps
- Orders at extreme prices
- Orders with zero size
- No fills (if LIVE_SAFE/LIVE_FULL)

---

## T+45 min: Alignment Check (45-60 min)

### Alignment Status Check
- [ ] No `[ALIGNMENT-DEGRADED]` flags
- [ ] No `[ALIGNMENT-BLOCK-ENTRY]` flags
- [ ] Alignment gaps are < 50 cents for all assets
- [ ] No consecutive alignment failures (> 2)
- [ ] No assets in degraded mode

### Alignment Quality Check
- [ ] Spot proxy is available for all assets
- [ ] Spot prices are reasonable
- [ ] Spot prices are not stale (< 60 seconds old)
- [ ] CFB proxy is working (or composite fallback)
- [ ] No `[SPOT-REF-UNAVAILABLE]` flags

### Stop and Investigate Triggers
- `[ALIGNMENT-DEGRADED]` flags present
- `[ALIGNMENT-BLOCK-ENTRY]` flags present
- Alignment gaps > 50 cents
- Consecutive alignment failures
- Assets in degraded mode
- Spot proxy unavailable

---

## T+60 min: Unified Edge Check (60-75 min)

### Unified Edge Status Check
- [ ] `[UNIFIED-EDGE-APPLIED]` logs present (if enabled)
- [ ] No `[UNIFIED-EDGE-ERROR]` logs
- [ ] No `[UNIFIED-EDGE-BLOCKED]` logs
- [ ] No `[UNIFIED-EDGE-MISSING-STATE]` logs
- [ ] No `[UNIFIED-EDGE-MISSING-BID]` logs
- [ ] No `[UNIFIED-EDGE-MISSING-ASK]` logs

### Edge Quality Check
- [ ] Edge values in reasonable range (0.01-0.10)
- [ ] Edge_R values in reasonable range (0.5-2.0)
- [ ] No pathological edge_R values (> 5.0)
- [ ] No negative edge_R values (for taken trades)
- [ ] No NaN/None in edge fields

### Unified Edge Decision Check
- [ ] Decision distribution is reasonable
- [ ] Not all decisions are "take" or "skip"
- [ ] Decision reasons are logged
- [ ] No unexpected decision patterns

### Stop and Investigate Triggers
- `[UNIFIED-EDGE-ERROR]` logs present
- Pathological edge_R values (> 5.0)
- Negative edge_R values (for taken trades)
- NaN/None in edge fields
- All decisions are "take" or "skip"

---

## T+75 min: Risk Routing Check (75-90 min)

### Risk Routing Status Check
- [ ] `[RISK-ROUTING-ALLOCATE]` logs present
- [ ] No `[RISK-ROUTING-VIOLATION]` logs
- [ ] No `[RISK-ROUTING-SAFE-MODE]` logs
- [ ] Risk allocation is within caps
- [ ] Per-asset caps respected
- [ ] Group caps respected

### Risk Allocation Check
- [ ] Total allocated ≤ global cap
- [ ] Per-asset allocation ≤ per-asset cap
- [ ] Group allocation ≤ group cap
- [ ] Risk budget not exhausted
- [ ] No invariant violations

### Risk Quality Check
- [ ] Risk per contract is reasonable
- [ ] Total risk is reasonable
- [ ] Risk distribution is reasonable
- [ ] No excessive risk concentration

### Stop and Investigate Triggers
- `[RISK-ROUTING-VIOLATION]` logs present
- `[RISK-ROUTING-SAFE-MODE]` logs present
- Risk allocation exceeds caps
- Invariant violations
- Excessive risk concentration

---

## T+90 min: Calibration Data Check (90-105 min)

### Calibration Data Logging Check
- [ ] Calibration data logs are being written
- [ ] Log files are growing
- [ ] Log format is correct (JSONL)
- [ ] All assets are logged
- [ ] All log types are present (metadata, orderbook, spot, unified_edge, risk_routing)

### Data Quality Check
- [ ] No NaN/None in logged data
- [ ] Values are reasonable
- [ ] Timestamps are correct
- [ ] No gaps in logging
- [ ] No duplicate entries

### Log Retention Check
- [ ] Old logs are cleaned up (if > retention period)
- [ ] Log directory size is reasonable
- [ ] Disk space is sufficient
- [ ] No disk space warnings

### Stop and Investigate Triggers
- Calibration data logs not being written
- Log files not growing
- NaN/None in logged data
- Gaps in logging
- Disk space issues

---

## T+105 min: System Health Check (105-120 min)

### Performance Check
- [ ] CPU usage is reasonable (< 80%)
- [ ] Memory usage is reasonable (< 80%)
- [ ] Disk usage is reasonable (< 80%)
- [ ] Network usage is reasonable
- [ ] No performance bottlenecks

### Error Check
- [ ] No unexpected errors in logs
- [ ] No crash loops
- [ ] No memory leaks
- [ ] No resource exhaustion
- [ ] No hanging processes

### Log Check
- [ ] All expected log tags present
- [ ] Log volume is reasonable
- [ ] Log rotation working
- [ ] No log file corruption
- [ ] No missing log entries

### Stop and Investigate Triggers
- CPU usage > 80%
- Memory usage > 80%
- Disk usage > 80%
- Unexpected errors
- Crash loops
- Memory leaks
- Resource exhaustion

---

## Summary Checklist

### All Assets (BTC, ETH, SOL, XRP, DOGE)
- [ ] Signals generated
- [ ] Unified edge decisions made
- [ ] Risk routing decisions made
- [ ] Alignment checks passed
- [ ] Calibration data logged

### System
- [ ] Started successfully
- [ ] Configuration correct
- [ ] Performance stable
- [ ] No errors
- [ ] Logging working

### Stop and Investigate Summary
If any of the following occur, stop and investigate:
- No signals for any asset
- No signals for specific asset while others have many
- Pathological unified edge decisions
- Frequent alignment degradation
- Risk routing violations
- Calibration data logging not working
- Performance issues
- Unexpected errors

---

## Immediate Actions

### If All Checks Pass
- Continue monitoring for next 24 hours
- Proceed to shadow mode testing (if SIM regime)
- Proceed to regime transition (if ready)

### If Any Check Fails
- Investigate logs for root cause
- Run validation scripts
- Consider rollback if issue cannot be resolved quickly
- Document issue and resolution

### Rollback Procedure
1. Stop current process
2. Restore previous `.env` file
3. Restart system
4. Verify system is stable
5. Investigate logs for root cause
6. Document issue and resolution

---

## Contact

For issues during first hour:
- Check logs for error tags
- Run validation scripts
- Review troubleshooting guides
- Rollback if issues cannot be resolved quickly
