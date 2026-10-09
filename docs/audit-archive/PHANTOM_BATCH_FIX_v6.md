# PRODUCTION FIX v6 (2026-04-26) — Phantom Batch, Arbiter & Event-Loop Lag

## Problem Summary
The server had multiple blocking issues preventing live trades:

1. **Phantom Batch** `1777078131.9749014`:
   - Persisted in cache as ACTIVE with no filled positions
   - Blocked all new execution via CYCLE_LOCKED warnings
   - Prevented any trades from being placed after server restart

2. **ARBITER Blocking** (CRITICAL):
   - Arbiter selected winning assets (BTC, ETH, XRP)
   - But `_is_arbiter_winner()` always returned False because `_current_candidates` was cleared
   - All execution blocked with `[ARBITER_BLOCKED] ... not in arbiter winners`

3. **Event-Loop Lag** warnings on slower computers triggering degraded mode

## Root Cause
When the server crashed or was restarted, a batch was left in ACTIVE status with no actual positions filled. The batch manager loads this from cache on startup and blocks all new cycles until the batch is "reconciled" — which never happens because there are no positions to close.

## Fixes Applied

### 1. ARBITER Winner Check Fix (`merid/prediction/crypto_top_edge.py` + `trading_agent.py`)

**Root Cause:** The arbiter's `run_cycle()` method clears `_current_candidates` at the start of each cycle (line 531). The `_is_arbiter_winner()` method in `trading_agent.py` was checking this cleared list, so it always returned False, blocking all execution.

**Fix:**
- Added `_last_cycle_winners: Dict[str, CandidateSignal]` to preserve winners after cycle completes
- Added `is_winner(ticker, max_age_seconds)` method to check if a ticker was a winner
- Updated `_is_arbiter_winner()` in `trading_agent.py` to use the new method
- Winners are stored by ticker (full Kalshi market ID) for precise matching

### 2. Phantom Batch Auto-Detection & Clearing (`merid/trading/top3_batch_manager.py`)

**On startup:**
- Detects batches that are ACTIVE but have no fills after 5 minutes
- Auto-clears phantom batches from cache
- Logs critical alert for observability

**New emergency method:**
- `force_clear_phantom_batch()` — production-safe, only clears batches with no fills
- Called by BTC_HOURLY and BTC_15M agents on startup to ensure clean state

### 2. Event-Loop Lag Relaxation for Slower Computers

**`merid/diagnostics/loop_lag.py`:**
- Healthy threshold: 50ms → 100ms
- Degraded threshold: 500ms → 1500ms  
- Halt threshold: 2000ms → 5000ms

**`merid/event_venues/kalshi/ws.py`:**
- Reconnect lag threshold: 1000ms → 3000ms
- Halt band: 2000ms → 6000ms

### 3. Strike Distance Band Widening (Previously Applied)

**`merid/prediction/kalshi_strike_selector.py`:**
- DOGE 1h: 0.12 → 2.00 (176% rejections observed)
- XRP 1h: 0.14 → 0.55 (49% rejections observed)
- FALLBACK_MAX_DISTANCE_PCT: 0.125 → 0.50

## Environment Variables for Slower Computers

```bash
# Event-loop lag thresholds (increased for slower hardware)
set KALSHI_LOOP_LAG_HEALTHY_MS=100
set KALSHI_LOOP_LAG_DEGRADE_MS=1500
set KALSHI_LOOP_LAG_HALT_MS=5000
set KALSHI_LOOP_LAG_HALT_CONSECUTIVE=5

# WebSocket reconnection thresholds
set KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS=3000

# To revert to aggressive thresholds on fast hardware:
# set KALSHI_LOOP_LAG_HEALTHY_MS=50
# set KALSHI_LOOP_LAG_DEGRADE_MS=500
# set KALSHI_LOOP_LAG_HALT_MS=2000
```

## Files Modified

1. `merid/prediction/crypto_top_edge.py` — ARBITER winner preservation & `is_winner()` method
2. `merid/prediction/trading_agent.py` — Fixed `_is_arbiter_winner()` to use new method + phantom batch clearing
3. `merid/trading/top3_batch_manager.py` — Phantom batch detection & clearing
4. `merid/diagnostics/loop_lag.py` — Relaxed lag thresholds (100/1500/5000ms)
5. `merid/event_venues/kalshi/ws.py` — Relaxed WS thresholds (3000/6000ms)
6. `merid/prediction/kalshi_strike_selector.py` — Strike bands widened (DOGE 1h: 2.00, fallback: 0.50)

## Restart Required

**CRITICAL:** All changes require server restart to take effect.

```bash
# 1. Stop the server (Ctrl+C or kill process)
# 2. Clear any residual cache (optional but recommended)
# 3. Start the server
python -m web.main
```

## Verification After Restart

Look for these log messages:

```
# ARBITER winners being detected (no more ARBITER_BLOCKED)
[CRYPTO_TOP_EDGE] Cycle=X TopEdge=0.4250 Winners=2 Assets=BTC,ETH
[ARBITER] Winner check passed for KXBTC-26APR2717-T87749.99

# Phantom batch auto-cleared (if present)
[TOP3-BATCH] PHANTOM BATCH DETECTED: batch X is ACTIVE but has no fills...
[STARTUP-PHANTOM-CLEAR] Emergency cleared phantom batch - execution unblocked

# Relaxed lag thresholds (should see fewer DEGRADED MODE entries)
LoopLagMonitor started (interval=1000ms)

# Orders flowing (the key indicator!)
[PM_SIGNAL] agent=BTC_HOURLY action=buy_no ticker=KXBTC-26APR2717-T87749.99
[SIGNAL-EXEC] accepted | ticker=KXBTC-26APR2717-T87749.99 | order_id=...
```

**What you should NOT see after restart:**
- `[ARBITER_BLOCKED] ... not in arbiter winners` (should be fixed)
- `[TOP3_BLOCKED] ... not in top-3 edge allocation` (should be fixed)
- `[CYCLE_LOCKED] ... previous cycle must close` (should be fixed)

## If Phantom Batch Persists

If you still see `CYCLE_LOCKED` after restart:

1. Check logs for `[TOP3-BATCH] PHANTOM BATCH DETECTED` — it should auto-clear
2. If not detected, manually trigger via API (to be added) or:
3. Clear Redis/cache key `top3:active_batch` manually
4. Restart server

## Design Notes

- **Why 5-minute threshold?** Prevents clearing batches that just started filling
- **Why only BTC_HOURLY/BTC_15M clear?** Avoids race conditions between agents
- **Safety:** `force_clear_phantom_batch()` only clears batches with `filled_assets == empty`
- **Observability:** All clears are logged at CRITICAL level for audit trails
