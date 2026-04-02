# MERID Staging Full Trading Mode Validation Runbook

> **Purpose**: Validate MERID is ready for live trading by running 10-minute and 30-minute full-stack gates in a staging environment.
> **Audience**: SRE, Trading Lead, Engineering Lead
> **Last updated**: 2026-04-02

---

## Overview

This runbook provides exact commands and procedures for validating MERID's full trading mode performance in a staging environment before going live. The validation uses automated gate scripts that measure event-loop performance under sustained load.

### Why Staging, Not CI?

**CI cannot run 10-30 minute full-stack gates** because:
- CI runners are ephemeral (jobs timeout, resources are constrained)
- Full stack requires persistent environment with all services running
- Meaningful performance validation needs production-like infrastructure
- Gates require VALIDATION_MODE=0 with real WebSocket connections, database, etc.

**This runbook is for staging/pre-production environments only.**

---

## Prerequisites

### Environment Requirements

1. **Staging host** with resources comparable to production:
   - 8+ CPU cores
   - 16+ GB RAM
   - Low-latency network connection to Kalshi API
   - PostgreSQL database running
   - Redis running (if used)

2. **MERID configuration**:
   ```bash
   export MERID_TRADE_MODE=paper
   export MERID_ALLOW_LIVE_TRADES=false
   export VALIDATION_MODE=0  # Full trading mode (not validation-light)
   ```

3. **Full stack components enabled**:
   - MeridLoop
   - 35 KalshiTradingAgents (5 assets × 5 timeframes, some may be disabled)
   - 8-11 StreamingAgents/Insight pipelines
   - KalshiWebSocketBridge (hundreds of tickers)
   - KalshiContinuousTrader
   - Fills ledger + reconciliation tasks
   - Event loop monitor integrated

4. **Validation scripts available**:
   - `scripts/run_trading_gate.py`
   - `scripts/run_paper_gate.py`
   - `scripts/analyze_gate_results.py`

### Pre-Flight Checks

Before starting gates, verify the system is healthy:

```bash
# 1. Confirm environment variables
echo "Trade mode: $MERID_TRADE_MODE"           # must be 'paper'
echo "Live trades: $MERID_ALLOW_LIVE_TRADES"   # must be 'false'
echo "Validation mode: $VALIDATION_MODE"       # must be '0' (full mode)

# 2. Check server is running and healthy
curl -s http://localhost:8000/api/health | jq '{status, degraded}'
# Expected: {"status": "healthy", "degraded": false}

# 3. Check event loop monitor is active
curl -s http://localhost:8000/health/event_loop | jq '{running, degraded, p95_ms: .stats_1m.p95_ms}'
# Expected: {"running": true, "degraded": false, "p95_ms": <100}

# 4. Verify full stack is up
# Check logs for:
#   - "✅ Event Loop Monitor started"
#   - "MeridLoop started"
#   - "KalshiWebSocketBridge connected"
#   - "35 trading agents initialized" (or similar)
```

If any pre-flight check fails, **do not proceed** with gates. Fix issues first.

---

## Step 1: 5-Minute Smoke Test (Optional but Recommended)

Run a quick smoke test to catch obvious issues before longer gates:

```bash
cd /path/to/MERID

# Create reports directory
mkdir -p reports

# Run 5-minute smoke test
python scripts/run_trading_gate.py \
  --duration 5 \
  --output reports/smoke_test_$(date +%Y%m%d_%H%M%S).json
```

**Expected outcome:**
- Gate completes without crashes
- P95 < 200ms in steady state (after initial startup)
- No sustained degraded state

**If smoke test fails**: Investigate before proceeding to longer gates.

---

## Step 2: 10-Minute Validation Gate

This gate validates that the system handles multiple 5-minute cycles cleanly, including periodic catalog refreshes and reconciliation tasks.

### Run the Gate

```bash
cd /path/to/MERID

# Run 10-minute gate
python scripts/run_trading_gate.py \
  --duration 10 \
  --output reports/gate_10min_$(date +%Y%m%d_%H%M%S).json
```

The script will:
1. Check environment is correctly configured
2. Poll `/health/event_loop` every 30 seconds for 10 minutes
3. Record P50/P95/P99/Max lag metrics
4. Automatically run analysis at the end

### Analyze Results

The analyzer runs automatically, but you can re-run it manually:

```bash
python scripts/analyze_gate_results.py \
  reports/gate_10min_YYYYMMDD_HHMMSS.json \
  --highlight-5min
```

### Key Validation Points for 10-Minute Gate

**Focus on T+5min windows:**
- Does the first 5-minute catalog refresh spike occur?
- Is the spike reduced from ~1500ms (pre-optimization) to < 500ms?
- Are 5-minute windows no longer degraded?

**Expected behavior:**
```
🔍 T+5min Window Analysis (2 samples):
  P95: min=250.0ms  max=487.5ms  mean=368.7ms
  ✅ 0 degraded samples in 5-min windows
```

### Go/No-Go Criteria (10-Minute Gate)

| Criterion | Threshold | Status |
|-----------|-----------|--------|
| P95 < 500ms | Every sample P95 < 500ms | ⬜ |
| No degraded 5-min windows | degraded=false in T+5min samples | ⬜ |
| No connection failures | All HTTP polls succeed | ⬜ |

**Decision:**
- ✅ **GO**: If all criteria met, proceed to 30-minute gate
- ❌ **NO-GO**: If any criterion fails, investigate and fix before proceeding

---

## Step 3: 30-Minute Go-Live Gate

This is the final validation before enabling live trading. It proves the system can sustain production SLOs over a realistic session duration.

### Run the Gate

```bash
cd /path/to/MERID

# Run 30-minute gate (final validation)
python scripts/run_trading_gate.py \
  --duration 30 \
  --output reports/gate_30min_$(date +%Y%m%d_%H%M%S).json
```

**Duration**: 30 minutes of continuous polling (60 samples at 30-second intervals)

### Analyze Results

```bash
python scripts/analyze_gate_results.py \
  reports/gate_30min_YYYYMMDD_HHMMSS.json \
  --highlight-5min
```

### Go/No-Go Criteria (30-Minute Gate)

These are the **official live-ready criteria** that must all be satisfied:

| # | Criterion | Threshold | Pass/Fail |
|---|-----------|-----------|-----------|
| 1 | **P95 < 500ms** | Maximum P95 across all samples < 500ms | ⬜ |
| 2 | **P99 < 800ms** | Maximum P99 across all samples < 800ms | ⬜ |
| 3 | **Max < 1000ms** | No single lag measurement ≥ 1000ms | ⬜ |
| 4 | **degraded_samples = 0** | Zero samples with degraded=true flag | ⬜ |
| 5 | **No connection failures** | All heartbeat polls succeed (failed_polls = 0) | ⬜ |

**All five criteria must show ✅ PASS for live-ready certification.**

### Example Passing Output

```
🎯 Go/No-Go Verdict:
  ✅ P95 < 500ms
  ✅ P99 < 800ms
  ✅ Max < 1000ms
  ✅ degraded_samples == 0
  ✅ No connection failures

  ✅✅✅ GO FOR LIVE TRADING — All criteria satisfied
```

### If Gate Fails

**Do not enable live trading.** Instead:

1. **Review violations**:
   ```bash
   jq '.violations' reports/gate_30min_YYYYMMDD_HHMMSS.json
   ```

2. **Check which samples failed**:
   ```bash
   python scripts/analyze_gate_results.py \
     reports/gate_30min_YYYYMMDD_HHMMSS.json \
     --highlight-5min | grep "⚠️"
   ```

3. **Fetch profiling data** (if degraded samples > 0):
   ```bash
   curl http://localhost:8000/health/event_loop/profiles/summary | jq .
   ```

4. **Look for patterns**:
   - Failures at T+5min marks → Scheduling/periodic task issue
   - Scattered failures → General throughput issue
   - Failures only during startup → May be acceptable (check if isolated)

5. **Fix root cause** and re-run 30-minute gate from scratch.

---

## Step 4: Capture and Archive Results

Once the 30-minute gate **passes**, capture evidence for audit trail:

```bash
# 1. Copy the passing gate result
cp reports/gate_30min_YYYYMMDD_HHMMSS.json \
   reports/LIVE_READY_gate_30min_$(date +%Y%m%d_%H%M%S).json

# 2. Generate final analysis report
python scripts/analyze_gate_results.py \
  reports/LIVE_READY_gate_30min_*.json \
  --highlight-5min \
  > reports/LIVE_READY_analysis_$(date +%Y%m%d_%H%M%S).txt

# 3. Archive to version control or artifact storage
git add reports/LIVE_READY_*
git commit -m "validation: 30-min gate passed, system certified live-ready"

# Or upload to S3/artifact store:
# aws s3 cp reports/LIVE_READY_* s3://merid-artifacts/validation/
```

**Keep these artifacts** for compliance, debugging, and historical baseline comparisons.

---

## Step 5: Update Documentation

After passing validation, update the following:

1. **PRE_LIVE_CHECKLIST.md**:
   - Mark Section 4 (Gate Evidence) items as ✅
   - Record the gate run timestamps and P95/P99 metrics

2. **fix_history.md** (if applicable):
   - Document final validation metrics
   - Note any anomalies observed and how they were resolved

3. **Deployment notes**:
   - Record which git commit/tag was validated
   - Note environment specifications (CPU, RAM, network latency to Kalshi)

---

## Monitoring and Alerts After Go-Live

Once live trading is enabled, set up continuous monitoring:

### 1. Runtime Alerts on Event-Loop Lag

Configure alerts using LoopLagMonitor metrics:

```python
# Alert if P95 > 400ms for N consecutive minutes
if event_loop_p95_ms > 400 for 5 minutes:
    send_alert("Event loop degrading", priority=HIGH)

# Kill-switch if P95 > 500ms sustained
if event_loop_p95_ms > 500 for 3 minutes:
    trigger_kill_switch()
    send_alert("Event loop critically degraded", priority=CRITICAL)
```

**Endpoints to poll**:
- `GET /health/event_loop` - 1-minute and 5-minute rolling stats
- `GET /api/health` - Overall system health including event loop

### 2. Initial Live Limits

Start with conservative limits:

| Parameter | Initial Value | Notes |
|-----------|---------------|-------|
| Per-contract size cap | 10% of normal | e.g., $10 instead of $100 |
| Per-minute notional cap | $50 | Across all markets |
| Assets enabled | 1 (BTC only) | Expand gradually |
| Timeframes enabled | 1 (daily only) | Expand after 1 week stable |
| Kill-switch P95 threshold | 400ms | Tighter than validation (500ms) |

### 3. Gradual Expansion Plan

After 1 week stable at initial limits:
- Increase per-contract cap to 25% of normal
- Add 1 more asset (ETH)
- Monitor for 3 days

After 2 weeks total:
- Increase to 50% of normal caps
- Add more timeframes (1h, weekly)
- Monitor for 1 week

After 1 month total:
- Full limits (if no incidents)
- All assets and timeframes enabled

---

## Troubleshooting

### Gate Fails with P95 > 500ms

**Symptoms**: Some samples show P95 ≥ 500ms

**Diagnostic steps**:
1. Check if failures are at T+5min marks (periodic task issue)
2. Check if failures are scattered (general throughput issue)
3. Fetch profiling data to identify hot coroutines

**Common causes**:
- Catalog refresh not scoped to active tickers
- Reconciliation tasks blocking event loop
- Too many concurrent WebSocket handlers
- Blocking I/O in async context

### No Active Tickers Tracked

**Symptoms**: Logs show: `"Catalog periodic refresh: no active tickers tracked, falling back to full refresh"`

**Fix**: Ensure WS subscription handlers call `catalog.mark_active(ticker)`:
```python
from merid.event_venues.kalshi.market_catalog import get_market_catalog
catalog = get_market_catalog()
catalog.mark_active(ticker)  # Mark as active on every WS message
```

### Process Pool Indexing Fails

**Symptoms**: Logs show: `"Process-pool indexing failed: ..., falling back to synchronous"`

**Causes**:
- Serialization issue with market data
- Import errors in worker process
- Process pool not available in environment

**Workaround**: Disable process indexing if synchronous fallback works fine:
```python
catalog = KalshiMarketCatalog(use_process_indexing=False)
```

### Degraded State Persists

**Symptoms**: `degraded=true` for multiple consecutive samples

**Fix**:
1. Capture stack traces of running coroutines
2. Look for tight loops without `await asyncio.sleep(0)` yields
3. Check for blocking HTTP calls not using `httpx.AsyncClient`
4. Review recent code changes for async/await violations

---

## Command Reference

```bash
# Environment check
echo "Trade mode: $MERID_TRADE_MODE"
echo "Live trades: $MERID_ALLOW_LIVE_TRADES"
echo "Validation mode: $VALIDATION_MODE"

# Health endpoints
curl -s http://localhost:8000/api/health | jq '{status, degraded}'
curl -s http://localhost:8000/health/event_loop | jq '.stats_1m'

# Run gates
python scripts/run_trading_gate.py --duration 5   # 5-min smoke test
python scripts/run_trading_gate.py --duration 10  # 10-min validation
python scripts/run_trading_gate.py --duration 30  # 30-min go-live gate

# Analyze results
python scripts/analyze_gate_results.py reports/gate_10min.json --highlight-5min
python scripts/analyze_gate_results.py reports/gate_30min.json --highlight-5min

# Profiling (if issues found)
curl http://localhost:8000/health/event_loop/profiles/summary | jq .
```

---

## References

- [VALIDATION_GUIDE.md](../VALIDATION_GUIDE.md) - Technical details on event loop monitoring
- [FULL_TRADING_MODE_GATE_VALIDATION.md](FULL_TRADING_MODE_GATE_VALIDATION.md) - Optimization details
- [PRE_LIVE_CHECKLIST.md](PRE_LIVE_CHECKLIST.md) - Complete pre-live checklist
- [fix_history.md](../fix_history.md) - Event loop optimization history

---

## Sign-Off

After successful 30-minute gate validation, the following stakeholders must approve before live flip:

```
SRE Lead:          ________________  Date: ______  Gate file: __________________
Trading Lead:      ________________  Date: ______  Reviewed: YES / NO
Engineering Lead:  ________________  Date: ______  Commit SHA: _________________
Risk Manager:      ________________  Date: ______  Limits approved: YES / NO
```

**Only proceed with live trading after all sign-offs are complete.**
