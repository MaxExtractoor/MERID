# Kalshi 15m Crypto Production Monitoring Verification

**SPEC_VERSION:** 1.0.0  
**Date:** 2026-05-16  
**Purpose:** Verify production monitoring stability and CI marker wiring

## Overview

This procedure verifies that the Kalshi 15m crypto production monitoring is stable and that the kalshi_risk CI marker is properly wired into CI gates.

## CI Marker Verification

### 1. Verify kalshi_risk Marker Exists

**Check:** pytest.ini contains kalshi_risk marker definition

```bash
grep "kalshi_risk" pytest.ini
```

**Expected Output:**
```
kalshi_risk: Tests for Kalshi risk infrastructure (exposure caps, kill-switch, risk limits, reconciliation invariants)
```

**Status:** ✅ Complete - Marker added to pytest.ini

### 2. Verify CI Gate Wiring

**Check:** kalshi-pipeline-ci.yml runs kalshi_risk tests

```bash
grep -A 10 "kalshi-risk:" .github/workflows/kalshi-pipeline-ci.yml
```

**Expected Output:**
```
kalshi-risk:
  name: Kalshi Risk Infrastructure
  runs-on: ubuntu-latest
  needs: [formula-checks, version-drift]
```

**Status:** ✅ Complete - CI job added to kalshi-pipeline-ci.yml

### 3. Verify Test Execution

**Check:** Run kalshi_risk tests locally

```bash
pytest tests/ -v -m kalshi_risk
```

**Expected:** All tests with kalshi_risk marker execute successfully

**Status:** ⏳ Requires test execution (manual verification)

## Production Metrics Verification

### 1. Reconciliation Duration Stability

**Metric:** `merid_recon_run_duration_seconds` (avg, p95, p99)

**Verification:**
- Query Grafana dashboard: MERID Kalshi Reconciliation & Gate
- Check "Reconciliation Duration (Kalshi)" panel
- Verify avg duration < 10s (p95 < 30s, p99 < 60s)
- Check for sudden spikes or drift

**Acceptance Criteria:**
- [ ] Avg duration stable within 20% of baseline
- [ ] No unexplained duration spikes > 2x baseline
- [ ] P95 < 30s for 95% of time
- [ ] P99 < 60s for 99% of time

**Status:** ⏳ Requires live verification

### 2. Discrepancy Metrics Stability

**Metric:** `merid_recon_discrepancy_count` (total, critical, warning)

**Verification:**
- Query Grafana dashboard: MERID Kalshi Reconciliation & Gate
- Check "Critical Discrepancy Count (Current)" panel
- Check "Warning Discrepancy Count (Current)" panel
- Check "Discrepancy Counts by Asset" panel

**Acceptance Criteria:**
- [ ] Critical count = 0 (no critical discrepancies)
- [ ] Warning count stable or trending down
- [ ] No unexpected spikes in discrepancy counts
- [ ] Per-asset discrepancies explainable (market events, API issues)

**Status:** ⏳ Requires live verification

### 3. Gate State Stability

**Metric:** `merid_gate_state` (OPEN, LIMITED, BLOCKED)

**Verification:**
- Query Grafana dashboard: MERID Kalshi Reconciliation & Gate
- Check "Gate State (Current)" panel
- Check "Gate State Timeline" panel

**Acceptance Criteria:**
- [ ] Gate state mostly OPEN (> 95% of time)
- [ ] LIMITED transitions explainable (risk limit approach, known issues)
- [ ] BLOCKED transitions explainable (critical issues, maintenance)
- [ ] Gate state transitions logged with reasons

**Status:** ⏳ Requires live verification

### 4. Drift Monitor Status

**Metric:** `kalshi_live_drift_monitor` status (OK, DRIFTING, ERROR)

**Verification:**
- Query drift monitor output: `GET /api/v1/kalshi/drift/status`
- Check status value
- Review drift monitor logs

**Acceptance Criteria:**
- [ ] Status = OK for normal operation
- [ ] DRIFTING status only during known events (market volatility, API issues)
- [ ] ERROR status only during critical failures
- [ ] Alerts configured for consecutive DRIFTING/ERROR states

**Status:** ⏳ Requires live verification

### 5. API Performance Metrics

**Metric:** `kalshi_api_requests_total`, `kalshi_api_errors_total`, `kalshi_api_latency_seconds`

**Verification:**
- Query API metrics: `GET /api/v1/kalshi/api/metrics`
- Check Grafana dashboard: MERID Kalshi Reconciliation & Gate
- Check "Kalshi API Request Rate" panel
- Check "Kalshi API Error Rate" panel
- Check "Kalshi API Latency (p95)" panel

**Acceptance Criteria:**
- [ ] Request rate stable within expected range
- [ ] Error rate < 1% for normal operation
- [ ] Latency p95 < 1s for normal operation
- [ ] No unexplained latency spikes
- [ ] Error rate correlates with known API issues

**Status:** ⏳ Requires live verification

## Verification Procedure

### Pre-Verification Checklist

- [ ] Kalshi 15m crypto stack running in production
- [ ] Grafana dashboard accessible
- [ ] API endpoints accessible
- [ ] Monitoring agents running
- [ ] Alerting configured and tested

### Verification Steps

1. **CI Marker Verification**
   - Run: `grep "kalshi_risk" pytest.ini`
   - Run: `grep -A 10 "kalshi-risk:" .github/workflows/kalshi-pipeline-ci.yml`
   - Run: `pytest tests/ -v -m kalshi_risk` (dry run)
   - Document results

2. **Reconciliation Duration Verification**
   - Open Grafana dashboard: MERID Kalshi Reconciliation & Gate
   - Navigate to "Reconciliation Duration (Kalshi)" panel
   - Set time range: last 24h
   - Check avg, p95, p99 values
   - Compare with baseline (previous 7 days)
   - Document any anomalies

3. **Discrepancy Metrics Verification**
   - Open Grafana dashboard: MERID Kalshi Reconciliation & Gate
   - Navigate to "Critical Discrepancy Count (Current)" panel
   - Navigate to "Warning Discrepancy Count (Current)" panel
   - Navigate to "Discrepancy Counts by Asset" panel
   - Check for discrepancies
   - Investigate any critical discrepancies
   - Document findings

4. **Gate State Verification**
   - Open Grafana dashboard: MERID Kalshi Reconciliation & Gate
   - Navigate to "Gate State (Current)" panel
   - Navigate to "Gate State Timeline" panel
   - Check gate state history
   - Investigate any LIMITED/BLOCKED transitions
   - Document reasons for transitions

5. **Drift Monitor Verification**
   - Query: `GET /api/v1/kalshi/drift/status`
   - Check status value
   - Review drift monitor logs
   - Check for any DRIFTING/ERROR states
   - Investigate any anomalies
   - Document findings

6. **API Performance Verification**
   - Query: `GET /api/v1/kalshi/api/metrics`
   - Open Grafana dashboard: MERID Kalshi Reconciliation & Gate
   - Navigate to API performance panels
   - Check request rate, error rate, latency
   - Compare with baseline
   - Document any anomalies

### Post-Verification

- Document all findings in verification report
- Create Jira tickets for any issues found
- Update monitoring thresholds if needed
- Verify alerting rules are working
- Schedule next verification (weekly)

## References

- `pytest.ini` - Pytest configuration with markers
- `.github/workflows/kalshi-pipeline-ci.yml` - CI pipeline configuration
- `grafana/dashboards/merid_kalshi_recon_gate.json` - Grafana dashboard
- `merid/reconciliation/reconciliation_metrics.py` - Reconciliation metrics collector
- `merid/event_venues/kalshi/api_metrics.py` - API metrics collector
- `scripts/kalshi_live_drift_monitor.py` - Drift monitor script
- `scripts/drift_alerting.py` - Drift alerting module

## Sign-Off

**Verification Date:** ___________  
**Verifier:** ___________  
**Environment:** ___________  
**Results:** [PASS/FAIL/INCONCLUSIVE]  
**Notes:** ___________
