# Cancel Order Error Handling Audit

## Overview
Audit of error handling around `client.cancel_order()` for HTTP status codes (filled, not found) and other failure modes.

---

## Call Chain

```
order_router.cancel_order()
  → KalshiVenueClient.cancel_order()
    → KalshiVenueClient.cancel_order_result()
      → KalshiVenueClient._request_with_resilience()
```

---

## Error Handling

### cancel_order_result Method
**Location:** `client.py:1917-1942`

**Purpose:** Cancel order with explicit result

**Error Handling:**
```python
async def cancel_order_result(
    self, order_id: str, market_id: Optional[str] = None
) -> OperationResult[bool]:
    """Cancel order with explicit result.

    Uses Kalshi's cancel endpoint: POST /portfolio/orders/{order_id}/cancel
    """
    result = await self._request_with_resilience(
        "POST",
        f"/portfolio/orders/{order_id}/cancel",
        json_data={"order_id": order_id},
        operation_name=f"cancel_order({order_id})",
    )

    if not result.success:
        return OperationResult.fail(
            result.error,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    return OperationResult.ok(
        True,
        latency_ms=result.latency_ms,
        retries=result.retries,
    )
```

**Strengths:**
- ✅ Uses _request_with_resilience for comprehensive error handling
- ✅ Returns explicit OperationResult
- ✅ Includes latency and retry metrics

**Weaknesses:**
- ⚠️ No special handling for "order already filled" scenario
- ⚠️ No special handling for "order not found" scenario
- ⚠️ No idempotency check (canceling already canceled order)

---

## Error Handling via _request_with_resilience

Since `cancel_order_result` delegates to `_request_with_resilience`, it inherits all error handling from that method. See `PLACE_ORDER_ERROR_HANDLING_AUDIT.md` for detailed analysis.

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

### Order Already Filled
**Expected Behavior:** Kalshi API returns 400 or 422 with error message like "Order already filled"

**Current Handling:**
- Treated as business error (400/422)
- No retry (correct - order is already filled, cannot cancel)
- Returns OperationResult.fail with error message

**Strengths:**
- ✅ Correctly treats as permanent error (no retry)

**Weaknesses:**
- ⚠️ No special handling to distinguish "already filled" from other 400/422 errors
- ⚠️ Caller must parse error message to determine if order was filled

**Recommendation:**
1. Consider parsing error message to detect "already filled" and return specific error type
2. Consider logging "order already filled" as info instead of warning

---

### Order Not Found
**Expected Behavior:** Kalshi API returns 404 with error message like "Order not found"

**Current Handling:**
- Treated as client error (404)
- No retry (correct - order doesn't exist)
- Returns OperationResult.fail with error message

**Strengths:**
- ✅ Correctly treats as permanent error (no retry)

**Weaknesses:**
- ⚠️ No special handling to distinguish "not found" from other 404 errors
- ⚠️ Caller must parse error message to determine if order was not found

**Recommendation:**
1. Consider parsing error message to detect "not found" and return specific error type
2. Consider logging "order not found" as info instead of warning

---

### Order Already Canceled
**Expected Behavior:** Kalshi API may return 400 or 422 with error message like "Order already canceled"

**Current Handling:**
- Treated as business error (400/422)
- No retry (correct - order is already canceled)
- Returns OperationResult.fail with error message

**Strengths:**
- ✅ Correctly treats as permanent error (no retry)

**Weaknesses:**
- ⚠️ No idempotency check (could query order status before canceling)
- ⚠️ No special handling to distinguish "already canceled" from other 400/422 errors
- ⚠️ Caller must parse error message to determine if order was already canceled

**Recommendation:**
1. Consider adding idempotency check (query order status before canceling)
2. Consider parsing error message to detect "already canceled" and return success (idempotent)
3. Consider logging "order already canceled" as info instead of warning

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
9. ✅ Detailed logging for all error types

### Weaknesses
1. ⚠️ No special handling for "order already filled" scenario
2. ⚠️ No special handling for "order not found" scenario
3. ⚠️ No idempotency check (canceling already canceled order)
4. ⚠️ No specific error types for common cancel scenarios

### Recommendations

#### High Priority
1. **Add idempotency check:** Query order status before canceling to avoid unnecessary API calls
2. **Parse error messages:** Detect common scenarios (already filled, not found, already canceled) and return specific error types

#### Medium Priority
3. **Log level adjustment:** Log idempotent errors (already filled, already canceled) as info instead of warning
4. **Return success for idempotent cancels:** If order is already canceled, return success instead of error

#### Low Priority
5. **Add cancel-specific metrics:** Track cancel-specific metrics (cancel success rate, cancel failure reasons)

### Conclusion
The error handling around `client.cancel_order()` is **adequate** but lacks special handling for common cancel-specific scenarios. The generic error handling from `_request_with_resilience` is comprehensive, but the caller must parse error messages to distinguish between different failure modes. Adding idempotency checks and specific error types would improve the robustness and usability of the cancel operation.
