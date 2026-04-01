# Event Loop Lag Profiling and Fix Summary

**Date**: 2026-04-01
**Branch**: `claude/profile-event-loop-lag-sources`
**Status**: ✅ Profiling infrastructure complete, ready for smoke gate validation

---

## Problem Statement

A 5-minute smoke gate (`tick_opt_smoke_20250401_0425`) revealed critical steady-state event-loop lag issues:

- **P95 lag range**: 953–11,000 ms (target: <500 ms)
- **P95 lag avg**: ≈5,540 ms
- **High-lag profiles**: 10 captured
- **Root cause**: Non-tick subsystems (WebSockets, background services, blocking I/O)

While tick optimizations are correct (19/19 tests passing), they address only the tick loop.
The real bottleneck is event-loop starvation from continuous background tasks.

---

## Solution Architecture

### Phase 1: Deep Profiling Infrastructure ✅ COMPLETE

**Objective**: Capture stack traces during high-lag events to identify exact coroutines causing starvation.

**Implementation** (commits 2890429, fda720e):

1. **HighLagProfile dataclass** (`observability/event_loop_monitor.py:38-59`)
   - Captures coroutine names, stack traces, file:line locations
   - Stores top 10 offending tasks + full stack dump
   - JSON-serializable for API export

2. **Automatic profile capture** (`:144-219`)
   - Triggers when lag ≥ 500ms
   - Uses `asyncio.all_tasks()` to snapshot active coroutines
   - Extracts frame info via `cr_frame`/`gi_frame`
   - Logs top 3 offenders

3. **Three new API endpoints** (`web/api/health.py:361-528`)
   ```
   GET    /health/event_loop/profiles          # View profiles (limit=10)
   DELETE /health/event_loop/profiles          # Clear profiles
   GET    /health/event_loop/profiles/summary  # Aggregate analysis
   ```

**Key Features**:
- **offenders_by_coroutine**: Frequency counts of coroutines in high-lag events
- **offenders_by_module**: Aggregated by file/module for systemic issues
- **max_lag_ms / avg_lag_ms**: Severity metrics
- **avg_task_count**: Task proliferation indicator

### Phase 2: Targeted Yield Fixes ✅ COMPLETE

**Objective**: Add cooperative yield points in identified tight loops.

**Implementation** (commit 255c3ec):

1. **Kalshi WebSocket reconnect** (`merid/event_venues/kalshi/ws.py:577-580`)
   ```python
   for ob_ticker in self._orderbook_tickers:
       await self.subscribe_orderbook(ob_ticker)
       await asyncio.sleep(0)  # Yield after each subscription
   ```

2. **Continuous trader asset-timeframe scan** (`merid/trading/kalshi_continuous_trader.py:248-284`)
   ```python
   for asset in _CRYPTO_ASSETS:  # 5 assets
       for tf in _CRYPTO_TIMEFRAMES:  # 5 timeframes = 25 iterations
           # ... process markets ...
           await asyncio.sleep(0)  # Yield after each combination
   ```

3. **Continuous trader candidate evaluation** (`:527-532`)
   ```python
   for candidate in self._candidates:
       await asyncio.sleep(0)  # Yield before processing each candidate
       # ... evaluate ...
   ```

**Rationale**:
- `await asyncio.sleep(0)` = guaranteed yield point
- Minimal overhead (~0.01ms per yield)
- Critical for fairness in multi-coroutine environments

---

## Validation Strategy

### Phase 3A: Short Smoke Gate (5-10 minutes)

**Commands**:
```bash
# Start MERID backend
MERID_TRADE_MODE=paper MERID_ALLOW_LIVE_TRADES=false python -m web.main

# In another terminal, monitor profiling
watch -n 5 'curl -s http://localhost:8000/health/event_loop/profiles/summary | jq'

# Run smoke gate
python scripts/run_paper_gate.py --duration 300 --output reports/smoke_gate_phase3a.json
```

**Success Criteria**:
- P95 lag <500ms throughout
- Zero or minimal high-lag profiles (<3)
- `degraded=false` on all samples

**If profiles captured**:
1. Analyze `offenders_by_coroutine` and `offenders_by_module`
2. Identify top 3 offenders
3. Add yields or offload to executors
4. Re-test

### Phase 3B: Full Paper Gate (30 minutes)

**After smoke gate passes**:
```bash
python scripts/run_paper_gate.py --duration 1800 --output reports/paper_gate_phase3b.json
```

**Success Criteria**:
- P95 lag <500ms sustained (all 60 samples)
- `degraded=false` throughout
- Zero high-lag profiles
- No tick overlap events

### Phase 3C: Iterative Profiling Loop

**Until P95 <500ms sustained**:
1. Run smoke gate with profiling
2. Analyze `/health/event_loop/profiles/summary`
3. Fix top offenders (yields, executors, backpressure)
4. Document in `fix_history.md`
5. Commit and re-test

---

## API Usage Examples

### View Recent Profiles
```bash
curl http://localhost:8000/health/event_loop/profiles?limit=5 | jq
```

**Response**:
```json
{
  "profile_count": 5,
  "total_profiles": 10,
  "profiles": [
    {
      "captured_at": "2026-04-01T14:30:45.123Z",
      "lag_ms": 1250.5,
      "active_task_count": 87,
      "top_tasks": [
        {
          "name": "kalshi-ws-processor",
          "coro": "_process_queue",
          "file": "/home/runner/work/MERID/MERID/merid/event_venues/kalshi/ws.py",
          "line": 456,
          "function": "_process_queue",
          "stack": "..."
        }
      ]
    }
  ]
}
```

### Get Aggregate Analysis
```bash
curl http://localhost:8000/health/event_loop/profiles/summary | jq
```

**Response**:
```json
{
  "total_profiles": 10,
  "offenders_by_coroutine": {
    "_process_queue": 8,
    "_refresh_candidates": 5,
    "_run_consensus": 3
  },
  "offenders_by_module": {
    "merid.event_venues.kalshi.ws": 8,
    "merid.trading.kalshi_continuous_trader": 5,
    "merid.loop": 3
  },
  "max_lag_ms": 2450.0,
  "avg_lag_ms": 1120.5,
  "avg_task_count": 92.3
}
```

### Clear Profiles (Between Test Runs)
```bash
curl -X DELETE http://localhost:8000/health/event_loop/profiles
```

---

## Expected Outcomes

### Immediate Benefits (Phase 2 Yields)
- ✅ Reduce starvation during WS reconnect (20+ orderbooks)
- ✅ Reduce starvation during market scans (25 asset-timeframe combos)
- ✅ Reduce starvation during candidate evaluation (50+ candidates)

### Medium-Term Benefits (Phase 3 Profiling)
- 🔄 Data-driven identification of remaining hot spots
- 🔄 File:line references for surgical fixes
- 🔄 Iterative validation loop (profile → fix → re-test)

### Long-Term Goal
- 🎯 P95 lag <500ms sustained over 30-minute paper gates
- 🎯 Zero high-lag profiles under realistic load
- 🎯 `degraded=false` throughout
- 🎯 Enable live trading rollout per `LIVE_ROLLOUT_PLAN.md`

---

## Safety Guarantees

**No Functional Changes**:
- All yields are cooperative (`await asyncio.sleep(0)`)
- No blocking sleeps that delay critical operations
- Profiling is non-intrusive (captures state, doesn't modify)
- No changes to trading logic, risk, or execution gates

**Preserved Correctness**:
- Yields only in iteration loops (safe points)
- No yields in critical sections (locks, transactions)
- Profile capture is synchronous (no races)

**Monitoring**:
- Profile count in `/health/event_loop`
- Profile summary API for aggregate analysis
- High-lag events logged at WARNING

---

## Next Steps

1. **Execute Phase 3A smoke gate** (5-10 minutes)
   - Monitor `/health/event_loop/profiles/summary`
   - Expect 0-3 profiles during startup
   - If >3 profiles, analyze and fix top offenders

2. **Execute Phase 3B full gate** (30 minutes, after smoke passes)
   - Confirm P95 <500ms sustained
   - Confirm zero profiles
   - Update `fix_history.md` with results

3. **Iterate if needed** (Phase 3C)
   - Profile → Fix → Test loop
   - Document each iteration
   - Continue until sustained P95 <500ms

4. **Final readiness check** (Phase 4)
   - Update `PRE_LIVE_CHECKLIST.md`
   - Confirm no open anomalies
   - Prepare for live rollout

---

## References

- **fix_history.md Phase 3**: Complete documentation of profiling infrastructure and fixes
- **VALIDATION_GUIDE.md**: Procedures for smoke gates and paper gates
- **PRE_LIVE_CHECKLIST.md**: Final readiness criteria before live trading
- **LIVE_ROLLOUT_PLAN.md**: Conservative rollout plan with caps and kill switches
- **Problem statement**: Original issue describing 5-minute smoke gate failure

---

## Files Modified

**observability/event_loop_monitor.py**:
- Added `HighLagProfile` dataclass
- Added `_capture_high_lag_profile()` method
- Added `get_profiles()`, `clear_profiles()` methods
- Enhanced `get_current_status()` with profile counts

**web/api/health.py**:
- Added `GET /health/event_loop/profiles`
- Added `DELETE /health/event_loop/profiles`
- Added `GET /health/event_loop/profiles/summary`

**merid/event_venues/kalshi/ws.py**:
- Added yield in orderbook reconnect loop

**merid/trading/kalshi_continuous_trader.py**:
- Added yield in asset-timeframe scan loop
- Added yield in candidate evaluation loop

**fix_history.md**:
- Added Phase 3 section with comprehensive documentation

---

**Status**: Ready for smoke gate validation ✅
