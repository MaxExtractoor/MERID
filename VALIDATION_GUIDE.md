# Event Loop Lag Fixes - Validation Guide

## Overview

This guide provides instructions for validating the event loop lag fixes implemented in this PR. The fixes target reducing P95 event-loop lag from 6-8s to <500ms.

## Prerequisites

- System is in paper mode (`MERID_TRADE_MODE=paper`, `MERID_ALLOW_LIVE_TRADES=false`)
- All fixes have been deployed (see fix_history.md for details)
- Event loop monitor is integrated into application startup

## Quick Validation (5 minutes)

### 1. Start the Application

```bash
# Ensure environment is set to paper mode
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false

# Start MERID
python -m web.main
```

### 2. Verify Event Loop Monitor Started

Check the startup logs for:
```
================================================================================
📊 Starting Event Loop Monitor
================================================================================
✅ Event Loop Monitor started (100ms sample interval, 200ms warn, 500ms crit)
```

### 3. Check Health Endpoints

**Main health endpoint** (includes event loop metrics):
```bash
curl http://localhost:8000/api/health | jq .
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": 1711918684,
  "degraded": false,
  "checks": {
    "event_loop": {
      "status": "healthy",
      "degraded": false,
      "p50_lag_ms": 5.2,
      "p95_lag_ms": 15.8,
      "p99_lag_ms": 32.1,
      "max_lag_ms": 45.3,
      "samples_above_warn": 0,
      "samples_above_crit": 0
    },
    ...
  }
}
```

**Detailed event loop health** (dedicated endpoint):
```bash
curl http://localhost:8000/health/event_loop | jq .
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": 1711918684.123,
  "running": true,
  "degraded": false,
  "degraded_since": null,
  "sample_interval_ms": 100.0,
  "warn_threshold_ms": 200.0,
  "crit_threshold_ms": 500.0,
  "total_samples": 3000,
  "stats_1m": {
    "sample_count": 600,
    "mean_ms": 8.5,
    "p50_ms": 5.2,
    "p95_ms": 15.8,
    "p99_ms": 32.1,
    "max_ms": 45.3,
    "samples_above_warn": 0,
    "samples_above_crit": 0
  },
  "stats_5m": {
    "sample_count": 3000,
    "mean_ms": 9.1,
    "p50_ms": 5.8,
    "p95_ms": 18.2,
    "p99_ms": 38.7,
    "max_ms": 62.4,
    "samples_above_warn": 2,
    "samples_above_crit": 0
  }
}
```

**Success criteria for quick validation:**
- ✅ `degraded` = `false`
- ✅ `p95_lag_ms` < 100ms (during steady state)
- ✅ `samples_above_crit` = 0

## Full Validation (30-minute Paper Gate)

### Preparation

1. **Set up monitoring**:
   ```bash
   # Create a monitoring script to poll /health/event_loop every 30s
   cat > monitor_lag.sh <<'EOF'
   #!/bin/bash
   while true; do
     timestamp=$(date -Iseconds)
     stats=$(curl -s http://localhost:8000/health/event_loop | jq '.stats_5m')
     echo "$timestamp $stats" | tee -a lag_metrics.log
     sleep 30
   done
   EOF
   chmod +x monitor_lag.sh

   # Start monitoring in background
   ./monitor_lag.sh &
   MONITOR_PID=$!
   ```

2. **Configure realistic load**:
   - Enable all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE)
   - Enable all active trading agents (verify with `/api/v1/agents/status`)
   - Enable all 11 insight pipeline categories
   - Connect WebSocket feeds

3. **Record baseline**:
   ```bash
   # Capture initial state
   curl http://localhost:8000/health/event_loop > baseline_lag.json
   curl http://localhost:8000/api/v1/loop/status > baseline_loop.json
   ```

### Execution

Run the application for 30 minutes under realistic load:

1. **Let the system stabilize** (first 5 minutes):
   - Agents complete initial market resolution
   - Insight pipelines fetch initial market data
   - WebSockets establish connections

2. **Normal operation** (next 20 minutes):
   - Trading agents evaluate markets on their configured cadence
   - Insight pipelines poll for new markets
   - Monitor continuously samples event loop lag

3. **Capture final state** (last 5 minutes):
   ```bash
   # Final metrics
   curl http://localhost:8000/health/event_loop > final_lag.json
   curl http://localhost:8000/api/v1/loop/status > final_loop.json

   # Stop monitoring
   kill $MONITOR_PID
   ```

### Analysis

Run the analysis script:

```bash
# Create analysis script
cat > analyze_lag.py <<'EOF'
import json
import sys
from pathlib import Path

# Load all samples from log
samples = []
for line in Path("lag_metrics.log").read_text().splitlines():
    timestamp, stats = line.split(" ", 1)
    stats_obj = json.loads(stats)
    samples.append({
        "timestamp": timestamp,
        "p95_ms": stats_obj["p95_ms"],
        "p99_ms": stats_obj["p99_ms"],
        "max_ms": stats_obj["max_ms"],
        "samples_above_warn": stats_obj["samples_above_warn"],
        "samples_above_crit": stats_obj["samples_above_crit"],
    })

# Compute aggregates
p95_values = [s["p95_ms"] for s in samples]
p99_values = [s["p99_ms"] for s in samples]
max_values = [s["max_ms"] for s in samples]

print("=" * 80)
print("EVENT LOOP LAG ANALYSIS (30-minute gate)")
print("=" * 80)
print(f"Total samples: {len(samples)}")
print()
print(f"P95 lag:")
print(f"  Min: {min(p95_values):.1f}ms")
print(f"  Max: {max(p95_values):.1f}ms")
print(f"  Mean: {sum(p95_values) / len(p95_values):.1f}ms")
print(f"  Median: {sorted(p95_values)[len(p95_values) // 2]:.1f}ms")
print()
print(f"P99 lag:")
print(f"  Min: {min(p99_values):.1f}ms")
print(f"  Max: {max(p99_values):.1f}ms")
print(f"  Mean: {sum(p99_values) / len(p99_values):.1f}ms")
print()
print(f"Max lag spike: {max(max_values):.1f}ms")
print()

# Check green-light criteria
total_crit = sum(s["samples_above_crit"] for s in samples)
total_warn = sum(s["samples_above_warn"] for s in samples)
max_p95 = max(p95_values)

print("GREEN-LIGHT CRITERIA:")
print(f"  ✓ P95 lag < 500ms: {max_p95:.1f}ms {'✅ PASS' if max_p95 < 500 else '❌ FAIL'}")
print(f"  ✓ No critical lag spikes: {total_crit} samples {'✅ PASS' if total_crit == 0 else '❌ FAIL'}")
print(f"  ✓ Minimal warnings: {total_warn} samples {'✅ PASS' if total_warn < 10 else '⚠️  WARN'}")
print()

if max_p95 < 500 and total_crit == 0 and total_warn < 10:
    print("🎉 GREEN LIGHT: All criteria met! System is ready for incremental live trading.")
    sys.exit(0)
else:
    print("🔴 RED LIGHT: Criteria not met. Further investigation required.")
    sys.exit(1)
EOF

python analyze_lag.py
```

### Success Criteria

The 30-minute paper gate is successful if:

1. **P95 lag < 500ms sustained**
   - Maximum P95 lag across all 5-minute windows must be < 500ms
   - Median P95 lag should be < 200ms

2. **degraded=false throughout**
   - System should never enter degraded state during the gate
   - If `degraded=true` appears, investigate which coroutines are causing lag

3. **No critical lag spikes**
   - `samples_above_crit` should remain at 0 throughout
   - If any samples exceed 500ms, capture stack traces to identify hot spots

4. **Minimal warnings**
   - `samples_above_warn` should be < 10 total across the entire 30-minute gate
   - Occasional 200-500ms spikes are acceptable if infrequent

## Troubleshooting

### Degraded State Appears

If `/api/health` shows `degraded=true`:

1. **Check which coroutines are running**:
   ```bash
   # Install yappi for coroutine profiling
   pip install yappi

   # Add profiling to the application (run this in Python console)
   import yappi
   yappi.set_clock_type("wall")
   yappi.start()

   # Let it run for 30 seconds
   import time; time.sleep(30)

   # Stop and print stats
   yappi.stop()
   stats = yappi.get_func_stats()
   stats.sort("ttot", "desc")
   stats.print_all(columns={0: ("name", 100), 1: ("ncall", 10), 2: ("tsub", 8), 3: ("ttot", 8)})
   ```

2. **Look for tight loops**:
   - Search for coroutines with high `ncall` (call count) but low `tsub` (time per call)
   - These indicate tight loops without sufficient yields

3. **Check for blocking I/O**:
   - Look for coroutines with high `ttot` (total time) - these may be blocking
   - Verify all I/O uses async clients or `run_in_executor()`

### P95 Lag > 500ms

If P95 lag exceeds 500ms:

1. **Capture detailed metrics**:
   ```bash
   curl http://localhost:8000/health/event_loop | jq . > high_lag.json
   ```

2. **Check task count**:
   ```bash
   # Count asyncio tasks
   python -c "
   import asyncio
   tasks = asyncio.all_tasks()
   print(f'Total tasks: {len(tasks)}')
   for task in sorted(tasks, key=lambda t: t.get_name()):
       print(f'  {task.get_name()}')
   "
   ```

3. **Profile specific hot spots**:
   - If `KalshiTradingAgent._run_loop` dominates, check market count and cycle interval
   - If `_category_loop` dominates, check market fetch performance and processing time
   - If WebSocket handlers dominate, check queue depth and message processing time

### Functional Regression

If agents are not placing orders or pipelines are not emitting insights:

1. **Verify yields didn't break logic**:
   - Check that `await asyncio.sleep(0)` is only in loops, not in critical sections
   - Ensure no yields were added between atomic operations

2. **Check agent state**:
   ```bash
   curl http://localhost:8000/api/v1/agents/status | jq .
   ```

3. **Check insight pipeline stats**:
   ```bash
   curl http://localhost:8000/api/v1/insights/stats | jq .
   ```

## Next Steps After Validation

### If Green Light Achieved

1. **Update fix_history.md**:
   - Add final metrics from 30-minute gate
   - Document current state: "P95 lag < XXXms, degraded=false, ready for incremental live trading"

2. **Create incremental live trading plan**:
   - Start with 1 asset, 1 timeframe, very low risk caps
   - Strict kill-switch thresholds (P95 lag > 2s triggers kill-switch)
   - Monitor for 1 week before expanding

3. **Enable additional monitoring**:
   - Set up alerts for `degraded=true` events
   - Track P95 lag trends over time
   - Monitor correlation between lag and trading volume

### If Red Light (Criteria Not Met)

1. **Iterate on fixes**:
   - Use profiling data to identify remaining hot spots
   - Implement additional yields or consolidate tasks
   - Consider worker pool pattern for insight pipelines

2. **Update fix_history.md**:
   - Document findings from 30-minute gate
   - Add new anomalies discovered during profiling
   - Plan next iteration of fixes

3. **Re-run validation**:
   - Repeat 30-minute paper gate after implementing new fixes
   - Continue iterating until green-light criteria are met

## References

- `fix_history.md` - Detailed documentation of all fixes applied
- `observability/event_loop_monitor.py` - Event loop monitoring implementation
- `web/api/health.py` - Health endpoints with lag metrics
- [Python asyncio yielding patterns](https://til.simonwillison.net/python/yielding-in-asyncio)
- [Monitor asyncio event loop performance](https://oneuptime.com/blog/post/2026-02-06-monitor-asyncio-event-loop-performance-opentelemetry/view)
