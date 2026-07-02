# BankrollServiceV2 Concurrency Audit

## Overview
Audit of `BankrollServiceV2` for race conditions between reads during order sizing and writes during background refresh.

---

## Components Audited

### 1. Lock Protection

#### Instance Lock
```python
# Thread safety
self._lock = asyncio.Lock()
```

**Strengths:**
- ✅ Async lock for async context
- ✅ Protects all state mutations

**Weaknesses:**
- ⚠️ None - correctly implemented

---

#### Singleton Initialization Lock
```python
# Global singleton instance
_BANKROLL_SERVICE_V2: Optional[BankrollServiceV2] = None
_BANKROLL_LOCK = asyncio.Lock()

async def get_bankroll_service(
    max_riskable_frac: Optional[Decimal] = None,
    refresh_interval_seconds: float = 30.0,
) -> BankrollServiceV2:
    """Get or create the global bankroll service v2."""
    global _BANKROLL_SERVICE_V2
    
    if _BANKROLL_SERVICE_V2 is None:
        async with _BANKROLL_LOCK:  # ✅ Protected by lock
            if _BANKROLL_SERVICE_V2 is None:
                _BANKROLL_SERVICE_V2 = BankrollServiceV2(...)
                await _BANKROLL_SERVICE_V2.start()
    
    return _BANKROLL_SERVICE_V2
```

**Strengths:**
- ✅ Double-checked locking pattern for thread-safe singleton
- ✅ Uses `asyncio.Lock()` for async context

**Weaknesses:**
- ⚠️ None - correctly implemented

---

### 2. Write Operations

#### _fetch_and_update() (Lines 226-298)
**Purpose:** Fetch from Kalshi and update internal state

**Lock Usage:**
```python
async def _fetch_and_update(self):
    """Fetch from Kalshi and update internal state."""
    result = await self._client.get_balance()
    
    async with self._lock:  # ✅ Protected by mutex
        self._fetch_count += 1
        
        if isinstance(result, BalanceSuccess):
            # Fresh data - update everything
            self._current = result.bankroll
            self._last_success = datetime.now(timezone.utc)
            self._last_error = None
            self._last_error_time = None
            
            # BANKROLL-SNAPSHOT for debugging portfolio vs cash separation
            equity = float(result.bankroll.equity_usd)
            available = float(result.bankroll.available_cash_usd)
            locked = float(result.bankroll.locked_cash_usd)
            logger.info(...)
            
        elif isinstance(result, BalanceTemporaryError):
            # Temporary error - FAIL-CLOSED: transition to ERROR to block trading
            self._error_count += 1
            self._last_error = result.reason
            self._last_error_time = datetime.now(timezone.utc)
            
            if self._current:
                # Transition to ERROR (not STALE) to block trading
                self._current = self._current.with_state(BalanceState.ERROR)
                logger.error(...)
            else:
                logger.error(...)
                
        elif isinstance(result, BalancePermanentError):
            # Permanent error - disable trading
            self._error_count += 1
            self._last_error = result.reason
            self._last_error_time = datetime.now(timezone.utc)
            
            if self._current:
                self._current = self._current.with_state(BalanceState.ERROR)
            
            logger.error(...)
        
        # Notify subscribers
        summary = self._build_summary_locked()
    
    # Notify outside lock
    for cb in self._subscribers:
        try:
            cb(summary)
        except Exception as e:
            logger.warning(f"[subscriber] Error: {e}")
```

**Strengths:**
- ✅ Protected by `async with self._lock`
- ✅ Subscriber notifications happen outside lock (prevents deadlocks)
- ✅ Fail-closed behavior (ERROR state blocks trading)
- ✅ Distinguishes temporary vs permanent errors

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

### 3. Read Operations

#### get_current_bankroll() (Lines 385-391)
**Purpose:** Get current bankroll (may be stale)

**Lock Usage:**
```python
async def get_current_bankroll(self) -> Optional[InternalBankroll]:
    """Get current bankroll (may be stale).
    
    Returns None only if never successfully fetched.
    """
    async with self._lock:  # ✅ Protected by mutex
        return self._current
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Fast operation (minimal lock hold time)

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### get_summary() (Lines 393-421)
**Purpose:** Get current summary for UI display

**Lock Usage:**
```python
async def get_summary(self, caller_module: str = "unknown") -> BankrollSummary:
    """Get current summary for UI display.
    
    Args:
        caller_module: Name of calling module for logging attribution
    """
    async with self._lock:  # ✅ Protected by mutex
        summary = self._build_summary_locked()
        
        # PRODUCTION AUDIT (Step 2): Log whether using cached (STALE) or fresh (FRESH) data
        if summary.state == BalanceState.FRESH:
            data_source = "FRESH"
        elif summary.state == BalanceState.STALE:
            data_source = "CACHED_STALE"
        elif summary.state == BalanceState.ERROR:
            data_source = "ERROR_BLOCKED"
        else:
            data_source = "UNKNOWN"
        
        logger.info(...)
        return summary
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Logs data source (FRESH/STALE/ERROR)
- ✅ Caller module attribution for debugging

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### get_portfolio_value_cents() (Lines 423-433)
**Purpose:** Get portfolio value from position cache (single source of truth)

**Lock Usage:**
```python
async def get_portfolio_value_cents(self) -> int:
    """Get portfolio value from position cache (single source of truth).
    
    This is the RECOMMENDED method for all modules that need portfolio value.
    Do not duplicate this logic in other files.
    
    Returns:
        Portfolio value in cents (cost basis + unrealized PnL)
    """
    async with self._lock:  # ✅ Protected by mutex
        return self._calculate_portfolio_value_cents_locked()
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Single source of truth for portfolio value

**Weaknesses:**
- ⚠️ **Calls position_cache.get_all_positions() under lock**
- ⚠️ Position cache read is NOT protected by mutex (see position_cache audit)
- ⚠️ Could see inconsistent position data

**Recommendation:**
1. Consider taking snapshot of positions before lock (or document as "eventually consistent")

---

#### get_equity_for_risk_calc() (Lines 446-462)
**Purpose:** Get equity for position sizing

**Lock Usage:**
```python
async def get_equity_for_risk_calc(self) -> Optional[Decimal]:
    """Get equity for position sizing.

    Returns None if in ERROR state or never fetched.
    Returns equity only if FRESH (fail-closed - no STALE fallback).
    """
    async with self._lock:  # ✅ Protected by mutex
        if self._current is None:
            return None
        if self._current.state == BalanceState.ERROR:
            return None
        if self._current.state == BalanceState.STALE:
            # BUG-FIX: STALE also returns None to block trading
            # Previously STALE was allowed for degraded trading, but this caused
            # bankroll=0 bug when stale data was incorrect
            return None
        return self._current.equity_usd
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Fail-closed behavior (STALE returns None)
- ✅ Prevents bankroll=0 bug

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### get_stats() (Lines 492-502)
**Purpose:** Get service stats for health checks

**Lock Usage:**
```python
async def get_stats(self) -> Dict[str, Any]:
    """Get service stats for health checks."""
    async with self._lock:  # ✅ Protected by mutex
        return {
            "fetches_total": self._fetch_count,
            "errors_total": self._error_count,
            "last_success": self._last_success.isoformat() if self._last_success else None,
            "last_error": self._last_error,
            "last_error_time": self._last_error_time.isoformat() if self._last_error_time else None,
            "current_state": self._current.state.name if self._current else "UNKNOWN",
        }
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Fast operation

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

### 4. Background Refresh

#### _refresh_loop() (Lines 187-209)
**Purpose:** Background loop to keep bankroll fresh

**Lock Usage:**
```python
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

**Strengths:**
- ✅ Exponential backoff on failures
- ✅ Max retries (5) to prevent infinite loops
- ✅ Logs warnings and errors

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### _fetch_and_update_with_retry() (Lines 211-224)
**Purpose:** Fetch from Kalshi with retry logic for transient failures

**Lock Usage:**
```python
async def _fetch_and_update_with_retry(self, max_retries: int = 3):
    """Fetch from Kalshi with retry logic for transient failures."""
    for attempt in range(max_retries):
        try:
            await self._fetch_and_update()
            return  # Success
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(f"[fetch_retry] Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"[fetch_retry] All {max_retries} attempts failed: {e}")
                raise
```

**Strengths:**
- ✅ Exponential backoff (1s, 2s, 4s)
- ✅ Max retries (3) to prevent infinite loops
- ✅ Logs warnings and errors

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

### 5. Sync Helpers

#### get_equity_for_risk_calc_sync() (Lines 544-572)
**Purpose:** Synchronous wrapper to get equity for position sizing

**Lock Usage:**
```python
def get_equity_for_risk_calc_sync() -> Optional[float]:
    """Synchronous wrapper to get equity for position sizing.
    
    Returns None if:
    - Bankroll never fetched (UNKNOWN state)
    - Bankroll in ERROR state
    - Any exception occurs
    
    Returns float equity USD if FRESH or STALE (caller decides if STALE usable).
    
    This is the PM SIZING WIRING POINT - ensures all position sizing uses
    the unified v2 bankroll service as the single source of truth.
    """
    try:
        loop = asyncio.get_running_loop()
        # We're in async context but being called synchronously
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _get_equity_async()
            )
            return future.result()
    except RuntimeError:
        # No running loop, we can use asyncio.run
        try:
            return asyncio.run(_get_equity_async())
        except Exception:
            return None
```

**Strengths:**
- ✅ Handles both async and sync contexts
- ✅ Returns None on errors (fail-closed)

**Weaknesses:**
- ⚠️ **Creates new event loop via asyncio.run()**
- ⚠️ Could conflict with existing event loop
- ⚠️ ThreadPoolExecutor overhead

**Recommendation:**
1. Consider using `asyncio.run_coroutine_threadsafe()` if in async context

---

#### get_summary_sync() (Lines 596-618)
**Purpose:** Synchronous wrapper to get bankroll summary

**Lock Usage:**
```python
def get_summary_sync(caller_module: str = "unknown") -> Optional[BankrollSummary]:
    """Synchronous wrapper to get bankroll summary.
    
    Args:
        caller_module: Name of calling module for logging attribution
    
    Returns None on any error. Use this for logging/display where
    you don't want async complexity.
    """
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _get_summary_async(caller_module)
            )
            return future.result()
    except RuntimeError:
        try:
            return asyncio.run(_get_summary_async(caller_module))
        except Exception:
            return None
```

**Strengths:**
- ✅ Handles both async and sync contexts
- ✅ Returns None on errors (fail-closed)

**Weaknesses:**
- ⚠️ **Creates new event loop via asyncio.run()**
- ⚠️ Could conflict with existing event loop
- ⚠️ ThreadPoolExecutor overhead

**Recommendation:**
1. Consider using `asyncio.run_coroutine_threadsafe()` if in async context

---

## Race Condition Analysis

### Potential Race Conditions

#### 1. Read During Write
**Scenario:** `get_equity_for_risk_calc()` called while `_fetch_and_update()` is updating state

**Current Protection:**
- Both use `async with self._lock`
- Mutex ensures mutual exclusion

**Risk:** LOW - mutex protection is correct

**Recommendation:** None - correctly protected

---

#### 2. Concurrent Reads
**Scenario:** Multiple agents call `get_equity_for_risk_calc()` concurrently

**Current Protection:**
- All reads use `async with self._lock`
- Mutex ensures mutual exclusion

**Risk:** LOW - mutex protection is correct

**Impact:**
- Reads are serialized (could cause contention under high load)

**Recommendation:**
1. Consider read-write lock pattern (allow concurrent reads, block writes)

---

#### 3. Position Cache Read Under Lock
**Scenario:** `get_portfolio_value_cents()` calls `position_cache.get_all_positions()` under lock

**Current Protection:**
- Bankroll service uses `async with self._lock`
- Position cache read is NOT protected by mutex (see position_cache audit)

**Risk:** MEDIUM - could see inconsistent position data

**Impact:**
- Could see partially updated positions during WS fill
- Could cause portfolio value calculation to be incorrect

**Recommendation:**
1. Consider taking snapshot of positions before lock (or document as "eventually consistent")

---

#### 4. Sync Wrapper Event Loop Conflict
**Scenario:** `get_equity_for_risk_calc_sync()` called from async context

**Current Protection:**
- Detects running loop via `asyncio.get_running_loop()`
- Uses ThreadPoolExecutor to run `asyncio.run()`

**Risk:** MEDIUM - could conflict with existing event loop

**Impact:**
- `asyncio.run()` creates new event loop, could conflict with existing loop
- ThreadPoolExecutor overhead

**Recommendation:**
1. Consider using `asyncio.run_coroutine_threadsafe()` if in async context

---

## Recommendations

### High Priority
1. **Consider read-write lock pattern**
   - Use `asyncio.Lock` for writes
   - Use `asyncio.Semaphore` for reads (allow concurrent reads)
   - Improves read performance under high load

2. **Fix sync wrapper event loop conflict**
   - Use `asyncio.run_coroutine_threadsafe()` if in async context
   - Prevents event loop conflicts

### Medium Priority
3. **Document position cache read as eventually consistent**
   - Add comment in `get_portfolio_value_cents()` about position cache race condition
   - Or take snapshot of positions before lock

4. **Add lock timeout to mutex acquisitions**
   - Use `asyncio.wait_for(self._lock.acquire(), timeout=5.0)`
   - Prevents deadlocks if exception occurs

### Low Priority
5. **Add metrics for lock contention**
   - Track mutex wait time
   - Track mutex acquisition failures
   - Alert on high contention

---

## Conclusion

**Overall Assessment:** The concurrency protection is **well implemented** with proper mutex protection for all operations.

**Strengths:**
- All operations protected by `asyncio.Lock`
- Singleton initialization correctly protected
- Subscriber notifications happen outside lock (prevents deadlocks)
- Fail-closed behavior (ERROR/STALE blocks trading)
- Exponential backoff on failures
- Good logging and error handling

**Weaknesses:**
- Reads are serialized (could cause contention under high load)
- Position cache read under lock has race condition (position cache not protected)
- Sync wrappers create new event loop (could conflict with existing loop)

**Critical Fixes Needed:**
1. Consider read-write lock pattern for better read performance
2. Fix sync wrapper event loop conflict
3. Document position cache read as eventually consistent
