# Full Trading Mode Gate Validation Guide

## Overview

This guide describes how to validate MERID's full trading mode (VALIDATION_MODE=0) using the gate validation tooling.

## Objective

Ensure MERID can safely run 30-minute full-load trading gates with:
- **P95 < 500ms** throughout the entire run
- **P99 < 800ms**
- **Max < 1000ms**
- **degraded_samples = 0**
- **No recurring 5-minute event-loop stalls**

## Prerequisites

### Environment Setup

1. **Start MERID server in full trading mode:**
   ```bash
   export VALIDATION_MODE=0  # Full trading mode
   python -m web.main
   ```

2. **Verify full stack is running:**
   - MeridLoop
   - 35 KalshiTradingAgents
   - 8 StreamingAgents
   - KalshiWebSocketBridge (hundreds of tickers)
   - KalshiInsight pipelines
   - KalshiContinuousTrader
   - Fills ledger + reconciliations

## Gate Validation Workflow

### Step 1: Quick Smoke Test (5 minutes)

Verify basic functionality before longer runs:

```bash
python scripts/run_trading_gate.py --duration 5 --output reports/smoke_test.json
```

**Expected outcome:** No major spikes, baseline P95 < 100ms in steady state

### Step 2: 10-Minute Validation Gate

Test the optimizations over multiple 5-minute cycles:

```bash
python scripts/run_trading_gate.py --duration 10 --output reports/gate_10min_$(date +%Y%m%d_%H%M%S).json
```

**Key validation points:**
- Does the first 5-minute catalog refresh spike occur?
- Is the spike reduced from ~1500ms to < 500ms?
- Are 5-minute windows no longer degraded?

### Step 3: 30-Minute Go-Live Gate

Final validation for live trading:

```bash
python scripts/run_trading_gate.py --duration 30 --output reports/gate_30min_$(date +%Y%m%d_%H%M%S).json
```

**Go/No-Go criteria:**
- ✅ P95 < 500ms: Every sample's P95 must be under 500ms
- ✅ P99 < 800ms: Peak P99 across all samples < 800ms
- ✅ Max < 1000ms: No single lag measurement > 1000ms
- ✅ degraded_samples = 0: Zero samples with degraded=true
- ✅ No connection failures: All heartbeat polls succeed

## Analyzing Results

### Automatic Analysis

The `run_trading_gate.py` script automatically runs analysis after gate completion.

### Manual Analysis

Analyze any gate result file:

```bash
python scripts/analyze_gate_results.py reports/gate_10min.json --highlight-5min
```

### Understanding the Output

#### Per-Sample Breakdown

```
  Sample   Elapsed    P50        P95        P99        Max        Status
  --------------------------------------------------------------------------
  ✅ [  0] 30s        12.3ms     45.2ms     67.8ms     89.1ms     False
  ✅ [  1] 60s        11.8ms     43.1ms     65.2ms     87.3ms     False
  ⚠️  [  5] 300s       13.2ms     487.5ms    612.3ms    789.2ms    False       🔴 T+5min
```

**Markers:**
- `✅`: Sample passed (P95 < 500ms, not degraded)
- `⚠️`: Sample at risk or degraded
- `🔴 T+5min`: Sample within ±30s of a 5-minute mark

#### T+5min Window Analysis

When `--highlight-5min` is used, the analyzer shows statistics for samples near 5-minute marks:

```
🔍 T+5min Window Analysis (6 samples):
  P95: min=385.2ms  max=487.5ms  mean=423.7ms
```

**Goal:** All T+5min samples should have P95 < 500ms after optimizations

### Go/No-Go Verdict

The analyzer provides a final verdict:

```
🎯 Go/No-Go Verdict:
  ✅ P95 < 500ms
  ✅ P99 < 800ms
  ✅ Max < 1000ms
  ✅ degraded_samples == 0
  ✅ No connection failures

  ✅✅✅ GO FOR LIVE TRADING — All criteria satisfied
```

## Optimizations Implemented

### 1. Catalog Refresh Optimization

**Before:** Every 5-minute refresh processed all ~5000 markets synchronously, causing 1500ms+ P95 spikes

**After:**
- **Startup refresh (refresh_count == 0):** Full processing with ProcessPoolExecutor to bypass GIL
- **Periodic refresh (refresh_count > 0):** Scoped to ~394 active/subscribed markets only
- **Result:** 5-minute catalog refresh now processes 8% of markets (394 vs 5000)

### 2. Process-Based Index Building

**Problem:** CPU-intensive regex and parsing across 5000 markets blocked event loop due to GIL contention

**Solution:**
- Offload heavy regex/parsing to ProcessPoolExecutor workers
- Workers run in separate processes, bypassing GIL
- Main event loop stays responsive during startup indexing

### 3. Desynchronized Scheduling

**Problem:** All 5-minute tasks fired at T+0, T+300, T+600, creating "storms"

**Solution:**
- Catalog refresh: 30-90s random initial offset
- Reconciliation: 40-110s random initial offset
- CFGI refresh: 20-70s random initial offset
- **Result:** 5-minute tasks spread across ~2-minute window

## Troubleshooting

### Gate Fails with P95 > 500ms

1. **Check which samples failed:**
   ```bash
   python scripts/analyze_gate_results.py reports/gate.json --highlight-5min
   ```

2. **Look for patterns:**
   - Are failures concentrated at T+5min marks? → Scheduling issue
   - Are failures scattered? → General throughput issue
   - Are failures only during startup? → Acceptable (pre-settle phase)

3. **Fetch profiling data:**
   ```bash
   curl http://localhost:8000/health/event_loop/profiles/summary
   ```

### No Active Tickers Tracked

If logs show: `Catalog periodic refresh: no active tickers tracked, falling back to full refresh`

**Cause:** WS bridge or trading agents are not calling `catalog.mark_active(ticker)`

**Fix:** Ensure WS subscription handlers call:
```python
from merid.event_venues.kalshi.market_catalog import get_market_catalog
catalog = get_market_catalog()
catalog.mark_active(ticker)
```

### Process Pool Not Working

If logs show: `Process-pool indexing failed: ..., falling back to synchronous`

**Causes:**
- Serialization issue with market data
- Process pool not available in test environment
- Import errors in worker process

**Workaround:** Disable process indexing:
```python
catalog = KalshiMarketCatalog(use_process_indexing=False)
```

## Next Steps After Gate Pass

Once the 30-minute gate passes:

1. **Store results:** Archive the passing gate result JSON for audit trail
2. **Update monitoring:** Set up alerts for P95 > 400ms in production
3. **Go live:** Enable live trading with confidence
4. **Continuous monitoring:** Track P95 over weeks to detect regressions

## Commands Reference

```bash
# Quick smoke test (5 min)
python scripts/run_trading_gate.py --duration 5

# Standard 10-minute gate
python scripts/run_trading_gate.py --duration 10

# Go-live 30-minute gate
python scripts/run_trading_gate.py --duration 30

# Analyze existing results
python scripts/analyze_gate_results.py reports/gate_10min.json --highlight-5min

# Run without auto-analysis
python scripts/run_trading_gate.py --duration 10 --no-analysis

# Skip environment check (CI only)
python scripts/run_trading_gate.py --duration 10 --skip-env-check
```

## Files

- `scripts/run_paper_gate.py`: Core gate runner (polls /health/event_loop)
- `scripts/run_trading_gate.py`: High-level gate orchestrator with env checks
- `scripts/analyze_gate_results.py`: Result analyzer with go/no-go verdict
- `reports/`: Gate result JSON files (auto-created)

## Understanding P95 Semantics

**Important:** The gate measures **P95 of the last 60 seconds** every 30 seconds

- **LoopLagMonitor:** Records 1-second lag samples
- **Rolling window:** Maintains 60 most recent samples
- **P95 calculation:** Computed across those 60 samples
- **Gate sampling:** Reads P95 every 30 seconds

**Implications:**
- A single 1100ms spike in a 60-sample window won't force P95 ≥ 1100ms
- P95 ≈ 1700ms means sustained blocking (most samples in window are bad)
- Isolated spikes during startup settle phase don't count as failures
