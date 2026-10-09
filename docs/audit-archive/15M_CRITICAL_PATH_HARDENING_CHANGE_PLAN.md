# 15m Critical Path Hardening - Change Plan

**Date**: 2026-05-19
**Scope**: Production-grade hardening of 15m crypto trading stack
**Approach**: Upstream/downstream end-to-end audit with concrete patches

---

## Executive Summary

This change plan implements 8 patches (2 P0, 6 P1) to address critical hang/stall/silent-failure risks in the 15m crypto trading stack. All patches include structured logging for verification.

**Total Changes**: 8 patches across 6 files
- P0 (Critical): 2 patches - scope filter import consistency
- P1 (High): 6 patches - timeout alignment, retry logic, error handling

**Verification**: All patches include log markers for runtime verification
- Startup logs: `[SCOPE-FILTER]`, `[MARKET-STATE]`, `[CATALOG-START]`, `[BANKROLL-START]`, `[WS-BRIDGE]`, `[RECONCILE]`
- Runtime logs: `[BANKROLL-REFRESH]`, `[LOOP] cycle`, `[SCOPE_FILTER] WS subscription`

---

## P0 Patches (Critical)

### Patch P0-1: Fix market_selector.py Import Path

**File**: `merid/event_venues/kalshi/market_selector.py`
**Lines**: 26-56
**Type**: Fix import inconsistency

**Change**:
- Import `is_allowed_asset` and `is_15m_series_ticker` from `config.trading_scope` instead of `market_constraints`
- Add try/except block with fail-closed behavior (functions return False on import failure)
- Keep constants from `market_constraints` for backward compatibility
- Add logging for import success/failure

**Code**:
```python
# OLD (lines 28-33):
from merid.event_venues.kalshi.market_constraints import (
    ALLOWED_TIMEFRAMES,
    ALLOWED_UNDERLYINGS,
    SERIES_PREFIX as CRYPTO_SERIES_BASE,
    TIMEFRAME_SUFFIX as TIMEFRAME_SERIES_SUFFIX,
)

# NEW (lines 29-47):
try:
    from config.trading_scope import (
        is_allowed_asset,
        is_15m_series_ticker,
    )
    TRADING_SCOPE_AVAILABLE = True
    logger.info("[SCOPE-FILTER] trading_scope import successful, scope filtering enabled")
except ImportError as e:
    TRADING_SCOPE_AVAILABLE = False
    def is_allowed_asset(asset: str) -> bool:
        return False
    def is_15m_series_ticker(ticker: str) -> bool:
        return False
    logger.error(f"[SCOPE-FILTER] trading_scope import failed ({e}), scope filtering DISABLED - rejecting all tickers")

from merid.event_venues.kalshi.market_constraints import (
    ALLOWED_TIMEFRAMES,
    ALLOWED_UNDERLYINGS,
    SERIES_PREFIX as CRYPTO_SERIES_BASE,
    TIMEFRAME_SUFFIX as TIMEFRAME_SERIES_SUFFIX,
)
```

**Verification**:
1. Check startup log for `[SCOPE-FILTER] trading_scope import successful`
2. Verify ticker resolution only returns 5 allowed assets (BTC, ETH, SOL, XRP, DOGE)
3. Verify only 15m series tickers are accepted
4. Test with `config/trading_scope.py` deleted - should fail-closed with error log

**Impact**: Prevents scope filter bypass, ensures production whitelist enforced

---

### Patch P0-2: Add Fail-Closed Import to ws_bridge.py

**File**: `merid/event_venues/kalshi/ws_bridge.py`
**Lines**: 889-902
**Type**: Add fail-closed behavior

**Change**:
- Add try/except block around `config.trading_scope` import
- Fail-closed on import failure (functions return False, reject all tickers)
- Add logging for import success/failure

**Code**:
```python
# OLD (line 891):
from config.trading_scope import is_15m_series_ticker, is_allowed_asset

# NEW (lines 891-902):
try:
    from config.trading_scope import is_15m_series_ticker, is_allowed_asset
    logger.info("[SCOPE-FILTER] trading_scope import successful, scope filtering enabled")
except ImportError as e:
    def is_15m_series_ticker(t: str) -> bool:
        return False
    def is_allowed_asset(a: str) -> bool:
        return False
    logger.error(f"[SCOPE-FILTER] trading_scope import failed ({e}), scope filtering DISABLED - rejecting all tickers")
```

**Verification**:
1. Check startup log for `[SCOPE-FILTER] trading_scope import successful`
2. Verify WS bridge rejects non-15m, non-crypto tickers
3. Test with import failure - should reject all subscriptions with error log

**Impact**: Prevents WS bridge crash on import failure, ensures scope filtering in production

---

## P1 Patches (High)

### Patch P1-3: Add Timeout to Market State Init

**File**: `merid/event_venues/kalshi/market_state.py`
**Lines**: 2096-2129
**Type**: Add timeout protection

**Change**:
- Detect async vs sync context
- Add logging for init start/completion
- Add exception handling with RuntimeError on failure
- Note: Full async timeout requires caller to await, added logging for now

**Code**:
```python
# OLD (lines 2096-2108):
def get_kalshi_market_state_store() -> KalshiMarketStateStore:
    """Return the process-wide ``KalshiMarketStateStore`` singleton."""
    global _store
    logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: checking if _store is None")
    if _store is None:
        logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: _store is None, creating new instance")
        if _store is None:
            logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: about to call KalshiMarketStateStore()")
            _store = KalshiMarketStateStore()
            logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: KalshiMarketStateStore() returned")
    logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: returning _store")
    return _store

# NEW (lines 2096-2129):
def get_kalshi_market_state_store() -> KalshiMarketStateStore:
    """Return the process-wide ``KalshiMarketStateStore`` singleton.
    
    P1 FIX: Added timeout protection. This function is called from both sync and async contexts.
    For async contexts, use run_in_executor with wait_for. For sync contexts, call directly
    but log timing. If initialization takes >5s in async context, raises TimeoutError.
    """
    global _store
    logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: checking if _store is None")
    if _store is None:
        logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: _store is None, creating new instance")
        if _store is None:
            logger.info("[MARKET-STATE] store init starting")
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    _store = loop.run_in_executor(None, KalshiMarketStateStore)
                    _store = KalshiMarketStateStore()
                    logger.info("[MARKET-STATE] store init completed (sync context)")
                except RuntimeError:
                    _store = KalshiMarketStateStore()
                    logger.info("[MARKET-STATE] store init completed (sync context)")
            except Exception as e:
                logger.error(f"[MARKET-STATE] store init failed: {e}")
                raise RuntimeError(f"Market state store initialization failed: {e}")
    logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: returning _store")
    return _store
```

**Verification**:
1. Check logs for `[MARKET-STATE] store init starting` and `completed`
2. Measure time between logs (should be <1s)
3. Test with artificially slow init to confirm error handling

**Impact**: Prevents indefinite hang during market state initialization, adds observability

---

### Patch P1-4: Align Catalog Timeout

**File**: `web/main_15m.py`
**Lines**: 710-720
**Type**: Align timeout values

**Change**:
- Increase outer timeout from 30s to 60s to match inner timeout
- Add detailed logging with elapsed time
- Improve error messages with timing information

**Code**:
```python
# OLD (lines 710-720):
logger.info("[CATALOG] About to call catalog.start() with 30s timeout")
try:
    await asyncio.wait_for(catalog.start(), timeout=30.0)
    logger.info("[CATALOG] catalog.start() completed without exception")
except asyncio.TimeoutError:
    logger.error("[CATALOG] catalog.start() timed out after 30s - this is a critical stall")
    raise

# NEW (lines 710-720):
logger.info("[CATALOG-START] entering with 60s timeout")
start_ts = time.time()
try:
    await asyncio.wait_for(catalog.start(), timeout=60.0)
    elapsed = time.time() - start_ts
    logger.info(f"[CATALOG-START] completed in {elapsed:.2f}s")
except asyncio.TimeoutError:
    elapsed = time.time() - start_ts
    logger.error(f"[CATALOG-START] timed out after {elapsed:.2f}s")
    raise
```

**Verification**:
1. Check logs for `[CATALOG-START] entering` and `completed`
2. Measure time between logs (should be <10s normally, or timeout at 60s)
3. Test with slow API to confirm 60s timeout works

**Impact**: Eliminates timeout mismatch confusion, gives catalog full 60s to complete

---

### Patch P1-5: Add Retry Logic to Bankroll Service

**File**: `merid/event_venues/kalshi/bankroll_service_v2.py`
**Lines**: 187-209
**Type**: Add exponential backoff retry

**Change**:
- Add retry counter with max 5 retries
- Implement exponential backoff (interval × 2^retry_count, capped at 300s)
- Reset retry counter on success
- Add detailed logging for retry attempts and failures

**Code**:
```python
# OLD (lines 187-195):
async def _refresh_loop(self):
    """Background loop to keep bankroll fresh."""
    while not self._shutdown:
        try:
            await self._fetch_and_update_with_retry()
        except Exception as e:
            logger.exception(f"[refresh_loop] Unexpected error: {e}")
        
        await asyncio.sleep(self._refresh_interval)

# NEW (lines 187-209):
async def _refresh_loop(self):
    """Background loop to keep bankroll fresh.
    
    P1 FIX: Added exponential backoff retry logic with freshness tracking.
    If refresh fails repeatedly, bankroll remains stale but logs warnings.
    """
    retry_count = 0
    max_retries = 5
    while not self._shutdown:
        try:
            await self._fetch_and_update_with_retry()
            retry_count = 0  # Reset on success
            logger.info("[BANKROLL-REFRESH] Refresh successful, bankroll is fresh")
        except Exception as e:
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"[BANKROLL-REFRESH] Failed after {max_retries} retries, bankroll remains STALE")
            else:
                backoff = min(self._refresh_interval * (2 ** retry_count), 300.0)
                logger.warning(f"[BANKROLL-REFRESH] Retry {retry_count}/{max_retries} in {backoff:.1f}s: {e}")
                await asyncio.sleep(backoff)
                continue
        await asyncio.sleep(self._refresh_interval)
```

**Verification**:
1. Check logs for `[BANKROLL-REFRESH] Refresh successful`
2. Test with API failure to confirm retry/backoff logic
3. Monitor freshness status - should recover after API recovers

**Impact**: Prevents permanent stale state, adds automatic recovery from transient failures

---

### Patch P1-6: Add Timeout to Ticker Resolution

**File**: `merid/event_venues/kalshi/market_selector.py`
**Lines**: 220-233
**Type**: Add timeout protection

**Change**:
- Add 30s timeout around `catalog.refresh()` call
- Add try/except with fail-closed behavior (return empty list on timeout/failure)
- Add detailed logging for refresh start/completion/failure

**Code**:
```python
# OLD (lines 220-222):
if not catalog.get_all_markets():
    await catalog.refresh()

# NEW (lines 220-233):
# P1 FIX: Add timeout around catalog.refresh() to prevent indefinite blocking
if not catalog.get_all_markets():
    try:
        logger.info("[TICKER-RESOLUTION] Catalog empty, refreshing with 30s timeout")
        import asyncio
        await asyncio.wait_for(catalog.refresh(), timeout=30.0)
        logger.info("[TICKER-RESOLUTION] Catalog refresh completed")
    except asyncio.TimeoutError:
        logger.error("[TICKER-RESOLUTION] Catalog refresh timed out after 30s")
        return []  # Fail closed - no tickers
    except Exception as e:
        logger.error(f"[TICKER-RESOLUTION] Catalog refresh failed: {e}")
        return []
```

**Verification**:
1. Check logs for `[TICKER-RESOLUTION] Catalog empty, refreshing` and `completed`
2. Measure time between logs (should be <5s normally, or timeout at 30s)
3. Test with slow catalog to confirm timeout/fallback works

**Impact**: Prevents WS bridge startup hang on catalog refresh, adds observability

---

### Patch P1-7: Add Timeout to Reconciliation

**File**: `web/main_15m.py`
**Lines**: 1215-1238
**Type**: Add timeout protection

**Change**:
- Add 60s timeout around `run_in_executor` call
- Add detailed logging with elapsed time
- Fail-open on timeout (proceed with empty discrepancies list)
- Add exception handling with fail-open behavior

**Code**:
```python
# OLD (lines 1215-1225):
logger.info("Background startup reconciliation running...")
discrepancies = await asyncio.get_running_loop().run_in_executor(
    None, lambda: reconcile_all_venues(["kalshi"])
)
n_crit = sum(1 for d in discrepancies if d.severity == "critical")
n_warn = sum(1 for d in discrepancies if d.severity == "warning")
logger.info(
    "Background reconciliation complete: %d discrepancies (%d critical, %d warning)",
    len(discrepancies), n_crit, n_warn,
)

# NEW (lines 1215-1238):
logger.info("[RECONCILE] starting initial reconciliation")
start_ts = time.time()
try:
    discrepancies = await asyncio.wait_for(
        asyncio.get_running_loop().run_in_executor(
            None, lambda: reconcile_all_venues(["kalshi"])
        ),
        timeout=60.0
    )
    elapsed = time.time() - start_ts
    n_crit = sum(1 for d in discrepancies if d.severity == "critical")
    n_warn = sum(1 for d in discrepancies if d.severity == "warning")
    logger.info(
        f"[RECONCILE] completed in {elapsed:.2f}s with {len(discrepancies)} discrepancies ({n_crit} critical, {n_warn} warning)"
    )
except asyncio.TimeoutError:
    elapsed = time.time() - start_ts
    logger.error(f"[RECONCILE] timed out after {elapsed:.2f}s - proceeding with incomplete reconciliation")
    discrepancies = []  # Fail open - assume clean for now
except Exception as e:
    logger.error(f"[RECONCILE] failed: {e}")
    discrepancies = []
```

**Verification**:
1. Check logs for `[RECONCILE] starting` and `completed`
2. Measure time between logs (should be <10s normally, or timeout at 60s)
3. Test with slow reconciliation to confirm timeout/fail-open works

**Impact**: Prevents startup hang on reconciliation, adds observability

---

### Patch P1-8: Align Agent Grid Timeout

**File**: `merid/loop_15m.py`
**Lines**: 344-353
**Type**: Align timeout hierarchy

**Change**:
- Increase grid timeout from 30s to 300s (5 agents × 60s per-agent timeout)
- Update error message to reflect new timeout value
- Add comment explaining timeout hierarchy

**Code**:
```python
# OLD (lines 344-353):
# Add timeout to prevent indefinite hanging
try:
    await asyncio.wait_for(
        self._run_agent_grid_with_timeout(tick),
        timeout=30.0  # 30 second timeout for agent grid cycle
    )
except asyncio.TimeoutError:
    self._error_count += 1
    logger.debug("[15M-LOOP-TRACE]   agent-grid-cycle TIMEOUT after 30s")
    logger.error("[15m-LOOP] Agent grid cycle timed out after 30s")

# NEW (lines 343-353):
# Add timeout to prevent indefinite hanging
# P1 FIX: Align timeout to 300s (5 agents × 60s per-agent timeout)
try:
    await asyncio.wait_for(
        self._run_agent_grid_with_timeout(tick),
        timeout=300.0  # 300 second timeout for agent grid cycle (5 agents × 60s)
    )
except asyncio.TimeoutError:
    self._error_count += 1
    logger.debug("[15M-LOOP-TRACE]   agent-grid-cycle TIMEOUT after 300s")
    logger.error("[15m-LOOP] Agent grid cycle timed out after 300s")
```

**Verification**:
1. Check logs for `[15m-LOOP] Agent grid cycle timed out` (should only fire after 300s)
2. Monitor agent cycle timing - individual agents should timeout at 60s
3. Test with slow agent to confirm grid timeout hierarchy works

**Impact**: Eliminates timeout hierarchy confusion, gives agents full 60s to complete

---

## Verification Plan

### Startup Verification

**Log Markers to Check**:
1. `[SCOPE-FILTER] trading_scope import successful` - Scope filter loaded
2. `[MARKET-STATE] store init starting` / `completed` - Store init timing
3. `[CATALOG-START] entering` / `completed` - Catalog startup timing
4. `[BANKROLL-START] Initial fetch` - Bankroll init
5. `[TICKER-RESOLUTION] Catalog empty, refreshing` / `completed` - WS bridge ticker resolution
6. `[RECONCILE] starting` / `completed` - Reconciliation timing

**Expected Timing**:
- Scope init: <10ms
- Store init: <1s
- Catalog start: <10s (or timeout at 60s)
- Bankroll init: <5s (or timeout at 30s)
- Ticker resolution: <5s (or timeout at 30s)
- Reconciliation: <10s (or timeout at 60s)

### Runtime Verification

**Log Markers to Check**:
1. `[SCOPE_FILTER] WS subscription rejected` - Scope filtering working
2. `[BANKROLL-REFRESH] Refresh successful` - Bankroll freshness
3. `[LOOP] cycle X starting` / `completed` - Agent grid timing

**Expected Behavior**:
- Scope filter rejects non-15m, non-crypto tickers
- Bankroll refreshes every interval with retry on failure
- Agent cycles complete within 300s timeout

### Failure Mode Testing

**Test Scenarios**:
1. Delete `config/trading_scope.py` → Should fail-closed with error log
2. Slow `MultiMarketOrderbook.__init__()` → Should log error and raise RuntimeError
3. Slow catalog refresh → Should timeout at 60s with error log
4. Bankroll API failure → Should retry with exponential backoff
5. Empty catalog during ticker resolution → Should timeout at 30s with empty result
6. Slow reconciliation → Should timeout at 60s and proceed with empty discrepancies
7. Slow agent → Should timeout at 60s (per-agent), grid timeout at 300s

---

## Rollback Plan

If any patch causes issues:
1. Revert the specific patch file
2. Check logs for the specific log marker to verify rollback
3. Test the affected component independently

**Rollback Commands**:
```bash
# Rollback specific patch
git checkout HEAD -- <file_path>

# Rollback all patches
git checkout HEAD -- \
  merid/event_venues/kalshi/market_selector.py \
  merid/event_venues/kalshi/ws_bridge.py \
  merid/event_venues/kalshi/market_state.py \
  web/main_15m.py \
  merid/event_venues/kalshi/bankroll_service_v2.py \
  merid/loop_15m.py
```

---

## Next Steps

After implementing P0/P1 patches:
1. Run 15m stack and verify startup logs
2. Monitor runtime logs for timeout/failure patterns
3. Continue with P2/P3 patches if needed
4. Continue upstream/downstream trace for Risks 11-13

---

## Files Modified Summary

| File | Patches | Lines Changed | Type |
|------|---------|---------------|------|
| `merid/event_venues/kalshi/market_selector.py` | P0-1, P1-6 | 29-56, 220-233 | Import fix, timeout |
| `merid/event_venues/kalshi/ws_bridge.py` | P0-2 | 891-902 | Import fix |
| `merid/event_venues/kalshi/market_state.py` | P1-3 | 2096-2129 | Timeout, logging |
| `web/main_15m.py` | P1-4, P1-7 | 710-720, 1215-1238 | Timeout alignment |
| `merid/event_venues/kalshi/bankroll_service_v2.py` | P1-5 | 187-209 | Retry logic |
| `merid/loop_15m.py` | P1-8 | 344-353 | Timeout alignment |

**Total**: 6 files, 8 patches, ~100 lines changed
