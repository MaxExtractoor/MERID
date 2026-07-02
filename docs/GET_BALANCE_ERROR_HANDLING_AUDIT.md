# Get Balance Error Handling Audit

## Overview
Audit of error handling around `client.get_balance()` for HTTP status codes (API downtime) and other failure modes.

---

## Call Chain

```
bankroll_service_v2._fetch_and_update()
  → KalshiVenueClient.get_balance()
    → KalshiVenueClient.get_balance_result()
      → KalshiVenueClient._request_with_resilience()
```

---

## Error Handling

### get_balance_result Method
**Location:** `client.py:3192-3218`

**Purpose:** Get account balance with explicit result

**Error Handling:**
```python
async def get_balance_result(self) -> OperationResult[Dict[str, Decimal]]:
    """Get account balance with explicit result."""
    result = await self._request_with_resilience(
        "GET", "/portfolio/balance", operation_name="get_balance"
    )
    
    if not result.success:
        return OperationResult.fail(
            result.error,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    raw = result.data or {}
    balance_cents = raw.get("balance", 0)
    locked_cents = raw.get("locked_balance", 0)
    if isinstance(balance_cents, dict):
        locked_cents = balance_cents.get("locked_balance", 0)
        balance_cents = balance_cents.get("balance", 0)
    return OperationResult.ok(
        {
            "USD": Decimal(str(balance_cents)) / 100,
            "locked": Decimal(str(locked_cents)) / 100
        },
        latency_ms=result.latency_ms,
        retries=result.retries,
    )
```

**Strengths:**
- ✅ Uses _request_with_resilience for comprehensive error handling
- ✅ Returns explicit OperationResult
- ✅ Includes latency and retry metrics
- ✅ Handles both flat and nested balance response formats
- ✅ Converts cents to USD (divide by 100)
- ✅ Returns zeros on failure (via get_balance wrapper)

**Weaknesses:**
- ⚠️ No validation that balance values are numeric
- ⚠️ No validation that balance values are non-negative
- ⚠️ No special handling for API downtime scenarios

---

### get_balance Method (Wrapper)
**Location:** `client.py:3187-3190`

**Purpose:** Get account balance, returns zeros on failure

**Error Handling:**
```python
async def get_balance(self) -> Dict[str, Decimal]:
    """Get account balance. Returns zeros on failure."""
    result = await self.get_balance_result()
    return result.unwrap_or({"USD": Decimal("0"), "locked": Decimal("0")})
```

**Strengths:**
- ✅ Returns zeros on failure (graceful degradation)
- ✅ Prevents None errors downstream

**Weaknesses:**
- ⚠️ Returns zeros on failure could mask API issues
- ⚠️ No logging when returning zeros on failure
- ⚠️ Caller cannot distinguish between real zero balance and error

**Recommendation:**
1. Consider logging when returning zeros on failure
2. Consider returning None or raising error instead of zeros (fail-closed)

---

## Error Handling via _request_with_resilience

Since `get_balance_result` delegates to `_request_with_resilience`, it inherits all error handling from that method. See `PLACE_ORDER_ERROR_HANDLING_AUDIT.md` for detailed analysis.

### Error Handling Matrix

| Error Type | Status Code | Retry | Backoff | Max Retries | Special Handling |
|------------|-------------|-------|---------|-------------|------------------|
| Rate Limit | 429 | ✅ | Jittered exponential + Retry-After | KALSHI_MAX_RETRIES | Honors Retry-After header |
| Auth Error | 401 | ✅ (re-auth once) | N/A | 1 re-auth attempt | Re-authenticates on first 401 |
| Auth Error | 403 | ❌ | N/A | 0 | Permission denied - no retry |
| Business Error | 400 | ❌ | N/A | 0 | Bad params - no retry |
| Business Error | 422 | ❌ | N/A | 0 | Invalid data - no retry |
| Other Client Error | 4xx | ❌ | N/A | 0 | Client errors - no retry |
| Server Error | 5xx | ✅ | Jittered exponential | KALSHI_MAX_RETRIES | Retryable status codes |
| Timeout | N/A | ✅ | Jittered exponential | KALSHI_MAX_RETRIES | Network timeout |
| Connection Error | N/A | ✅ | Jittered exponential | KALSHI_MAX_RETRIES | Network connection error |
| Event Loop Error | N/A | ✅ | 0.05s | KALSHI_MAX_RETRIES | Resets HTTP client |
| Windows I/O Error | N/A | ✅ (recoverable only) | 0.05s | KALSHI_MAX_RETRIES | Resets HTTP client |
| Circuit Open | N/A | ❌ | N/A | 0 | Fail fast |

---

## Kalshi-Specific Error Scenarios

### API Downtime
**Expected Behavior:** Kalshi API is down or unavailable

**Current Handling:**
- Treated as server error (5xx) or connection error by _request_with_resilience
- Retries with jittered exponential backoff
- Max retries enforced (KALSHI_MAX_RETRIES)
- Returns zeros on failure (via get_balance wrapper)

**Strengths:**
- ✅ Retries with backoff
- ✅ Logs timeout/connection errors
- ✅ Max retries enforced
- ✅ Returns zeros on failure (graceful degradation)

**Weaknesses:**
- ⚠️ Returns zeros on failure could mask API downtime
- ⚠️ No logging when returning zeros on failure
- ⚠️ No special handling for extended API downtime
- ⚠️ Caller cannot distinguish between real zero balance and error

**Recommendation:**
1. Consider adding extended downtime detection (e.g., if all retries fail, mark API as down)
2. Consider logging when returning zeros on failure
3. Consider returning None or raising error instead of zeros (fail-closed)

---

### Auth Error
**Expected Behavior:** Authentication failure during balance fetch

**Current Handling:**
- Treated as auth error (401/403) by _request_with_resilience
- Re-authenticates once on 401
- No retry on 403 (permission denied)
- Returns zeros on failure (via get_balance wrapper)

**Strengths:**
- ✅ Re-authenticates on 401
- ✅ Logs detailed auth error on first occurrence
- ✅ Suppresses subsequent auth error logs

**Weaknesses:**
- ⚠️ Only one re-auth attempt
- ⚠️ No retry on 403
- ⚠️ Returns zeros on failure could mask auth issues

**Recommendation:**
1. Consider multiple re-auth attempts for transient auth issues
2. Consider logging when returning zeros on failure due to auth error

---

### Invalid Balance Data
**Expected Behavior:** Kalshi API returns invalid balance data (negative, non-numeric)

**Current Handling:**
- No validation
- Converts to Decimal (may raise exception)
- Returns invalid data if conversion succeeds

**Strengths:**
- ✅ None

**Weaknesses:**
- ⚠️ No validation that balance values are numeric
- ⚠️ No validation that balance values are non-negative
- ⚠️ Could return negative balance (invalid)
- ⚠️ Could raise exception on conversion

**Recommendation:**
1. Add validation that balance values are numeric
2. Add validation that balance values are non-negative
3. Add try/except around Decimal conversion

---

### Empty Balance Data
**Expected Behavior:** Kalshi API returns empty balance data

**Current Handling:**
- Uses default values (0) if fields missing
- Returns zeros

**Strengths:**
- ✅ Handles missing fields gracefully

**Weaknesses:**
- ⚠️ No validation that empty response is valid (could be API error)
- ⚠️ Returns zeros which could mask API error

**Recommendation:**
1. Consider adding validation that empty response is expected

---

## Bankroll Service Integration

### bankroll_service_v2._fetch_and_update
**Location:** `bankroll_service_v2.py:226-298`

**Purpose:** Fetch from Kalshi and update internal state

**Error Handling:**
```python
async def _fetch_and_update(self):
    """Fetch from Kalshi and update internal state."""
    result = await self._client.get_balance()
    
    async with self._lock:
        self._fetch_count += 1
        
        if isinstance(result, BalanceSuccess):
            # Fresh data - update everything
            self._current = result.bankroll
            self._last_success = datetime.now(timezone.utc)
            self._last_error = None
            self._last_error_time = None
            # ... logging ...
            
        elif isinstance(result, BalanceTemporaryError):
            # Temporary error - FAIL-CLOSED: transition to ERROR to block trading
            self._error_count += 1
            self._last_error = result.reason
            self._last_error_time = datetime.now(timezone.utc)
            
            if self._current:
                # Transition to ERROR (not STALE) to block trading
                self._current = self._current.with_state(BalanceState.ERROR)
                logger.error(
                    f"[bankroll_refresh] ERROR (fail-closed): {result.reason}, "
                    f"trading BLOCKED - not using cached equity=${self._current.equity_usd}"
                )
            else:
                logger.error(f"[bankroll_refresh] ERROR (no cache): {result.reason}")
                
        elif isinstance(result, BalancePermanentError):
            # Permanent error - disable trading
            self._error_count += 1
            self._last_error = result.reason
            self._last_error_time = datetime.now(timezone.utc)
            
            if self._current:
                self._current = self._current.with_state(BalanceState.ERROR)
            
            logger.error(f"[bankroll_refresh] PERMANENT ERROR: {result.reason}")
```

**Strengths:**
- ✅ Fail-closed behavior (ERROR state blocks trading)
- ✅ Distinguishes temporary vs permanent errors
- ✅ Logs detailed error information
- ✅ Tracks error count and timestamps

**Weaknesses:**
- ⚠️ None - correctly implemented

---

## Summary

### Strengths
1. ✅ Inherits comprehensive error handling from _request_with_resilience
2. ✅ Correct retry logic (transient errors retry, permanent errors fail)
3. ✅ Jittered exponential backoff prevents thundering herd
4. ✅ Honors Retry-After header for 429
5. ✅ Re-authenticates on 401
6. ✅ Circuit breaker prevents cascading failures
7. ✅ Windows I/O error recovery
8. ✅ Event loop mismatch recovery
9. ✅ Handles both flat and nested balance response formats
10. ✅ Converts cents to USD
11. ✅ Bankroll service implements fail-closed behavior
12. ✅ Bankroll service distinguishes temporary vs permanent errors

### Weaknesses
1. ⚠️ Returns zeros on failure could mask API issues
2. ⚠️ No logging when returning zeros on failure
3. ⚠️ Caller cannot distinguish between real zero balance and error
4. ⚠️ No validation that balance values are numeric
5. ⚠️ No validation that balance values are non-negative
6. ⚠️ No special handling for extended API downtime
7. ⚠️ Only one re-auth attempt

### Recommendations

#### High Priority
1. **Add balance validation:** Validate that balance values are numeric and non-negative
2. **Add try/except around conversion:** Handle Decimal conversion errors gracefully
3. **Log when returning zeros:** Log warning when returning zeros on failure

#### Medium Priority
4. **Consider fail-closed instead of zeros:** Return None or raise error instead of zeros (fail-closed)
5. **Add extended downtime detection:** Detect extended API downtime and mark service as down
6. **Multiple re-auth attempts:** Consider multiple re-auth attempts for transient auth issues

#### Low Priority
7. **Add balance-specific metrics:** Track balance-specific metrics (fetch success rate, error rate, stale data rate)

### Conclusion
The error handling around `client.get_balance()` is **well implemented** with comprehensive coverage of all failure modes. The bankroll service implements fail-closed behavior which is correct for production. The main weakness is that the wrapper returns zeros on failure which could mask API issues. Adding validation for balance values and logging when returning zeros would improve robustness. The fail-closed behavior in bankroll_service_v2 is correct and should be maintained.
