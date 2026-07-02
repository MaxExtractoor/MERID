# Time-Boxed Deployment Plan

## Overview
This document provides a time-boxed deployment plan for unified edge system rollout.

## Timeline Summary

- **T-24h:** Infrastructure setup, validation scripts, calibration data logging
- **T-2h:** Pre-flight checks, regime configuration, final validation
- **T+0:** Deployment (restart)
- **T+1h:** First hour observability, immediate monitoring
- **T+24h:** First day monitoring, shadow mode testing
- **T+72h:** Gradual rollout completion

---

## T-24h: Infrastructure Setup

### Objective
Set up infrastructure, run validation scripts, start calibration data logging.

### Tasks

#### 1. Python Environment Setup (30 min)
- [ ] Install Python 3.9+ on production boxes
- [ ] Add Python to PATH
- [ ] Install dependencies: pytest, pandas, numpy
- [ ] Verify Python environment: `python --version`

#### 2. Environment Configuration (15 min)
- [ ] Copy `.env.unified_edge` to `.env` on production boxes
- [ ] Set `MERID_DEPLOYMENT_REGIME=SIM` (shadow mode)
- [ ] Set `MERID_UNIFIED_EDGE_ENABLED=false` (initially disabled)
- [ ] Set `MERID_CALIBRATION_VERSION=placeholder` (initial value)
- [ ] Set `CALIBRATION_DATA_LOGGING_ENABLED=true`
- [ ] Set `CALIBRATION_DATA_LOG_DIR=/var/log/merid/calibration`
- [ ] Verify environment variables are loaded

#### 3. Process Manager Configuration (30 min)
- [ ] Wire `.env` into process manager (systemd/supervisor/k8s)
- [ ] Ensure env vars are passed to child processes
- [ ] Test env var loading in staging
- [ ] Verify process manager restarts correctly

#### 4. Run Validation Scripts in Staging (1 hour)
- [ ] Run `scripts/validate_contract_metadata.py` in staging
- [ ] Verify series→event→market mapping is consistent
- [ ] Run `scripts/trace_one_market.py` for each asset (BTC, ETH, SOL, XRP, DOGE)
- [ ] Inspect full pipeline: metadata → ContractState → unified edge → risk routing
- [ ] Run `scripts/production_bug_hunt.py` on staging logs
- [ ] Check for NaNs, alignment-degraded flags, mis-timed entries

#### 5. Start Calibration Data Logging (15 min)
- [ ] Verify `CALIBRATION_DATA_LOGGING_ENABLED=true`
- [ ] Verify log directory exists: `/var/log/merid/calibration`
- [ ] Restart system to start logging
- [ ] Verify log files are being created
- [ ] Verify log format matches notebook expectations

#### 6. CME CF Proxy Setup (2 hours)
- [ ] Obtain CME CF API key (if available)
- [ ] Set `CME_CF_API_KEY` in `.env`
- [ ] Test CME CF proxy initialization
- [ ] Verify CME CF proxy returns live prices
- [ ] Verify price staleness check works
- [ ] If CME CF unavailable, verify composite fallback works

#### 7. Shadow Mode Testing (2 hours)
- [ ] Set `MERID_DEPLOYMENT_REGIME=SIM`
- [ ] Set `MERID_UNIFIED_EDGE_ENABLED=true` (shadow mode)
- [ ] Run `scripts/shadow_unified_edge.py` for 2-4 hours
- [ ] Compare unified edge vs production decisions
- [ ] Check for pathological cases (edge_R > 5.0, negative edge_R)
- [ ] Verify no NaN/None propagation
- [ ] Verify alignment checks working

### Success Criteria
- Python environment working on production boxes
- Environment variables correctly configured
- Validation scripts pass in staging
- Calibration data logging started
- CME CF proxy working (or composite fallback)
- Shadow mode shows reasonable unified edge decisions

### Rollback Criteria
- Python environment cannot be set up
- Validation scripts fail in staging
- Calibration data logging fails
- CME CF proxy and composite fallback both fail
- Shadow mode shows pathological decisions

---

## T-2h: Pre-Flight Checks

### Objective
Final validation before deployment restart.

### Tasks

#### 1. Final Configuration Check (30 min)
- [ ] Verify `MERID_DEPLOYMENT_REGIME=SIM` (start in shadow mode)
- [ ] Verify `MERID_UNIFIED_EDGE_ENABLED=false` (start disabled)
- [ ] Verify `MERID_CALIBRATION_VERSION=placeholder`
- [ ] Verify `MERID_LIVE_SESSION_MAX_RISK_USD=300`
- [ ] Verify `MERID_RISK_BUDGET_MULTIPLIER=0.0` (SIM regime)
- [ ] Verify `CFB_ALLOW_COMPOSITE_FALLBACK=true`
- [ ] Verify `CALIBRATION_DATA_LOGGING_ENABLED=true`

#### 2. Startup Validation (15 min)
- [ ] Run `validate_all()` from `startup_validations.py`
- [ ] Verify all validations pass
- [ ] Check for `[SPOT-PROXY-VALIDATION]` log
- [ ] Check for `[UNIFIED-EDGE-VALIDATION]` log
- [ ] Verify no startup errors

#### 3. Deployment Regime Validation (15 min)
- [ ] Import `deployment_regime.py`
- [ ] Call `get_deployment_regime().validate_configuration()`
- [ ] Verify configuration is consistent with regime
- [ ] Call `get_deployment_regime().log_summary()`
- [ ] Verify regime is SIM

#### 4. Spot Proxy Validation (15 min)
- [ ] Call `validate_spot_proxy_availability()`
- [ ] Verify spot proxy is available
- [ ] Verify CME CF proxy is initialized (if available)
- [ ] Verify composite fallback is available
- [ ] Verify staleness check works

#### 5. Calibration Data Check (15 min)
- [ ] Verify calibration data logs exist
- [ ] Verify log files are being written
- [ ] Verify log format is correct (JSONL)
- [ ] Verify data quality (no NaNs, reasonable values)
- [ ] Verify retention policy is set

#### 6. Final Review (30 min)
- [ ] Review deployment checklist: `docs/UNIFIED_EDGE_DEPLOYMENT_CHECKLIST.md`
- [ ] Review shadow mode guide: `docs/SHADOW_MODE_EXECUTION_GUIDE.md`
- [ ] Review first hour checklist: `docs/FIRST_HOUR_OBSERVABILITY.md`
- [ ] Verify all T-24h tasks completed
- [ ] Verify rollback plan is ready
- [ ] Verify team is available for monitoring

### Success Criteria
- All configuration values correct
- All startup validations pass
- Deployment regime is SIM
- Spot proxy is available
- Calibration data logging is working
- All pre-flight checks pass

### Rollback Criteria
- Configuration values incorrect
- Startup validation fails
- Deployment regime validation fails
- Spot proxy unavailable
- Calibration data logging not working
- Any pre-flight check fails

---

## T+0: Deployment

### Objective
Restart system with new configuration.

### Tasks

#### 1. Backup Current State (5 min)
- [ ] Backup current `.env` file
- [ ] Backup current logs
- [ ] Note current system state
- [ ] Document rollback procedure

#### 2. Apply New Configuration (5 min)
- [ ] Copy `.env.unified_edge` to `.env`
- [ ] Verify all environment variables set
- [ ] Verify regime is SIM
- [ ] Verify unified edge is disabled

#### 3. Restart System (5 min)
- [ ] Stop current process
- [ ] Apply new configuration
- [ ] Start new process
- [ ] Verify process starts successfully

#### 4. Verify Startup (10 min)
- [ ] Check startup logs
- [ ] Verify `[DEPLOYMENT-REGIME]` log shows SIM
- [ ] Verify `[SPOT-PROXY-VALIDATION]` log passes
- [ ] Verify `[UNIFIED-EDGE-VALIDATION]` log passes
- [ ] Verify `[CALIBRATION-LOGGER]` log shows enabled
- [ ] Verify no startup errors

#### 5. Verify Shadow Mode (10 min)
- [ ] Verify no orders are placed (SIM regime)
- [ ] Verify unified edge logs are present
- [ ] Verify risk routing logs are present
- [ ] Verify calibration data logs are present
- [ ] Verify system is running in shadow mode

### Success Criteria
- System restarts successfully
- All startup validations pass
- System is in SIM regime
- No orders are placed
- All logging is working

### Rollback Criteria
- System fails to start
- Startup validation fails
- System not in SIM regime
- Orders are placed (should not happen in SIM)
- Logging not working

---

## T+1h: First Hour Observability

### Objective
Monitor system behavior in first hour after deployment.

### Tasks

#### 1. Signal Generation Check (15 min)
- [ ] For each asset (BTC, ETH, SOL, XRP, DOGE):
  - [ ] Verify at least some `[SIGNAL]` events
  - [ ] Verify non-zero attempts at `UnifiedEdgeComputer`
  - [ ] Verify a few `[RISK-DECISION]` outcomes
- [ ] Check for missing signals (no BTC signals while ETH/SOL active)
- [ ] Check for signal parity across assets

#### 2. Order Flow Check (15 min)
- [ ] Verify at least a trickle of small orders (if LIVE_SAFE/LIVE_FULL)
- [ ] Verify fills in 15m crypto series
- [ ] Verify order sizes are reasonable
- [ ] Verify no rejected orders due to risk caps

#### 3. Alignment Check (15 min)
- [ ] Monitor for `[ALIGNMENT-DEGRADED]` flags
- [ ] Monitor for `[ALIGNMENT-RESTORED]` flags
- [ ] Verify alignment gaps are < 50 cents
- [ ] Verify no consecutive alignment failures

#### 4. Unified Edge Check (15 min)
- [ ] Monitor for `[UNIFIED-EDGE-APPLIED]` logs
- [ ] Monitor for `[UNIFIED-EDGE-ERROR]` logs
- [ ] Verify edge values are reasonable (0.01-0.10)
- [ ] Verify edge_R values are reasonable (0.5-2.0)
- [ ] Verify no pathological cases

#### 5. Risk Routing Check (15 min)
- [ ] Monitor for `[RISK-ROUTING-ALLOCATE]` logs
- [ ] Monitor for `[RISK-ROUTING-VIOLATION]` logs
- [ ] Verify risk allocation is within caps
- [ ] Verify no invariant violations

#### 6. Calibration Data Check (15 min)
- [ ] Verify calibration data logs are being written
- [ ] Verify log files are growing
- [ ] Verify data quality (no NaNs, reasonable values)
- [ ] Verify all assets are logged

### Success Criteria
- All assets have signals
- Unified edge decisions are reasonable
- No alignment degradation
- No risk routing violations
- Calibration data logging working

### Rollback Criteria
- No signals for any asset
- Pathological unified edge decisions
- Frequent alignment degradation
- Risk routing violations
- Calibration data logging not working

---

## T+24h: First Day Monitoring

### Objective
Monitor system behavior for first 24 hours.

### Tasks

#### 1. Shadow Mode Testing (4 hours)
- [ ] Run `scripts/shadow_unified_edge.py` for 4 hours
- [ ] Compare unified edge vs production decisions
- [ ] Check for pathological cases
- [ ] Verify decision divergence is reasonable

#### 2. Calibration Data Collection (continuous)
- [ ] Verify calibration data logs are continuous
- [ ] Verify data quality over 24 hours
- [ ] Verify no gaps in logging
- [ ] Verify retention policy is working

#### 3. Performance Monitoring (continuous)
- [ ] Monitor system performance
- [ ] Monitor memory usage
- [ ] Monitor CPU usage
- [ ] Monitor disk usage (logs)

#### 4. Error Monitoring (continuous)
- [ ] Monitor for `[UNIFIED-EDGE-ERROR]` logs
- [ ] Monitor for `[ALIGNMENT-DEGRADED]` logs
- [ ] Monitor for `[RISK-ROUTING-VIOLATION]` logs
- [ ] Monitor for any unexpected errors

### Success Criteria
- Shadow mode shows reasonable decisions
- Calibration data logging continuous
- System performance stable
- No unexpected errors

### Rollback Criteria
- Shadow mode shows pathological decisions
- Calibration data logging has gaps
- System performance degrades
- Frequent unexpected errors

---

## T+72h: Gradual Rollout

### Objective
Gradually rollout unified edge to production.

### Tasks

#### 1. Enable Unified Edge in Shadow Mode (T+24h)
- [ ] Set `MERID_UNIFIED_EDGE_ENABLED=true`
- [ ] Keep `MERID_DEPLOYMENT_REGIME=SIM`
- [ ] Restart system
- [ ] Monitor for 24 hours
- [ ] Verify unified edge decisions are reasonable

#### 2. Move to LIVE_SAFE (T+48h)
- [ ] Set `MERID_DEPLOYMENT_REGIME=LIVE_SAFE`
- [ ] Set `MERID_UNIFIED_EDGE_ENABLED=false` (conservative)
- [ ] Set `MERID_RISK_BUDGET_MULTIPLIER=0.5`
- [ ] Restart system
- [ ] Monitor for 24 hours
- [ ] Verify orders are placed with conservative caps

#### 3. Move to LIVE_FULL (T+72h)
- [ ] Set `MERID_DEPLOYMENT_REGIME=LIVE_FULL`
- [ ] Set `MERID_UNIFIED_EDGE_ENABLED=true`
- [ ] Set `MERID_CALIBRATION_VERSION=v1` (after calibration)
- [ ] Set `MERID_RISK_BUDGET_MULTIPLIER=1.0`
- [ ] Restart system
- [ ] Monitor for 48-72 hours
- [ ] Verify unified edge is fully enabled

### Success Criteria
- Each regime transition is smooth
- No unexpected behavior
- Performance is stable
- Risk caps are respected

### Rollback Criteria
- Regime transition fails
- Unexpected behavior
- Performance degrades
- Risk caps violated

---

## Rollback Plan

### Immediate Rollback
If any critical issue occurs:
1. Stop current process
2. Restore previous `.env` file
3. Restart system
4. Verify system is stable
5. Investigate logs for root cause

### Regime Rollback
If regime transition fails:
1. Revert to previous regime
2. Restart system
3. Verify system is stable
4. Investigate logs for root cause

### Partial Rollback
If specific feature fails:
1. Disable specific feature via env var
2. Restart system
3. Verify system is stable
4. Investigate logs for root cause

---

## Contact

For issues during deployment:
- Check logs for error tags
- Run validation scripts
- Review troubleshooting guides
- Rollback if issues cannot be resolved quickly
