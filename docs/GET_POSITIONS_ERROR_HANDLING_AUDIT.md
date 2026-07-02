# Get Positions Error Handling Audit

## Overview
Audit of error handling around `client.get_positions()` for HTTP status codes (timeout, auth) and other failure modes.

---

## Call Chain

```
position_cache.sync_from_rest()
  → KalshiVenueClient.get_positions()
    → KalshiVenueClient.get_positions_result()
      → KalshiVenueClient._request_with_resilience()
```

---

## Error Handling

### get_positions_result Method
**Location:** `client.py:3054-3124`

**Purpose:** Get positions with explicit result, supports cursor-based pagination

**Error Handling:**
```python
async def get_positions_result(self) -> OperationResult[List[VenuePosition]]:
    """Get positions with explicit result.

    Supports cursor-based pagination to fetch all positions across multiple pages.
    Handles both market_positions and event_positions from Kalshi API.
    This is critical for accounts with many open positions.
    """
    all_positions: List[VenuePosition] = []
    cursor: Optional[str] = None
    total_latency = 0.0
    total_retries = 0
    max_pages = 10  # Safety limit to prevent runaway pagination

    for page in range(max_pages):
        params: Dict[str, Any] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        result = await self._request_with_resilience(
            "GET", "/portfolio/positions", params=params, operation_name="get_positions"
        )

        total_latency += result.latency_ms or 0
        total_retries += result.retries or 0

        if not result.success:
            if all_positions:
                # Return what we have so far on partial failure
                logger.warning(f"get_positions: Partial failure on page {page}, returning {len(all_positions)} positions")
                break
            return OperationResult.fail(
                result.error,
                latency_ms=total_latency,
                retries=total_retries,
            )

        # Parse market_positions (if present)
        for pos_data in result.data.get("market_positions", []):
            position = self._parse_position(pos_data)
            if position:
                all_positions.append(self._to_venue_position(position))

        # Parse event_positions (if present)
        for pos_data in result.data.get("event_positions", []):
            position = self._parse_position(pos_data)
            if position:
                all_positions.append(self._to_venue_position(position))

        # Fallback to legacy "positions" field if present
        if "positions" in result.data:
            for pos_data in result.data.get("positions", []):
                position = self._parse_position(pos_data)
                if position:
                    all_positions.append(self._to_venue_position(position))

        cursor = result.data.get("cursor")
        if not cursor:
            break

        # P1-HARDENING: Yield between pages to prevent event loop blocking
        await asyncio.sleep(0)

        if page >= max_pages - 1:
            logger.warning(f"get_positions: Hit max_pages limit ({max_pages}), returning {len(all_positions)} positions")
            break

    return OperationResult.ok(
        all_positions,
        latency_ms=total_latency,
        retries=total_retries,
    )
```

**Strengths:**
- ✅ Uses _request_with_resilience for comprehensive error handling
- ✅ Partial failure handling (returns what we have so far)
- ✅ Max pages limit (10) to prevent runaway pagination
- ✅ Yields between pages to prevent event loop blocking
- ✅ Handles both market_positions and event_positions
- ✅ Fallback to legacy "positions" field
- ✅ Returns explicit OperationResult with latency and retry metrics

**Weaknesses:**
- ⚠️ Partial failure may return incomplete position data
- ⚠️ No special handling for empty position data
- ⚠️ No validation that returned positions are valid

---

## Error Handling via _request_with_resilience

Since `get_positions_result` delegates to `_request_with_resilience`, it inherits all error handling from that method. See `PLACE_ORDER_ERROR_HANDLING_AUDIT.md` for detailed analysis.

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

### Timeout
**Expected Behavior:** Network timeout during positions fetch

**Current Handling:**
- Treated as timeout error by _request_with_resilience
- Retries with jittered exponential backoff
- Max retries enforced (KALSHI_MAX_RETRIES)

**Strengths:**
- ✅ Retries with backoff
- ✅ Logs timeout with wait time
- ✅ Max retries enforced

**Weaknesses:**
- ⚠️ No special handling for long-running pagination (10 pages * 100 positions = 1000 positions)
- ⚠️ Timeout during pagination may return partial data

**Recommendation:**
1. Consider adding timeout configuration for pagination (longer timeout for multi-page fetches)

---

### Auth Error
**Expected Behavior:** Authentication failure during positions fetch

**Current Handling:**
- Treated as auth error (401/403) by _request_with_resilience
- Re-authenticates once on 401
- No retry on 403 (permission denied)

**Strengths:**
- ✅ Re-authenticates on 401
- ✅ Logs detailed auth error on first occurrence
- ✅ Suppresses subsequent auth error logs

**Weaknesses:**
- ⚠️ Only one re-auth attempt
- ⚠️ No retry on 403

**Recommendation:**
1. Consider multiple re-auth attempts for transient auth issues

---

### Empty Position Data
**Expected Behavior:** Kalshi API returns empty position list

**Current Handling:**
- Returns empty list (correct)
- No special validation

**Strengths:**
- ✅ Correctly returns empty list

**Weaknesses:**
- ⚠️ No validation that empty response is valid (could be API error)

**Recommendation:**
1. Consider adding validation that empty response is expected (e.g., check that we have no open positions in cache)

---

### Partial Failure
**Expected Behavior:** Some pages fail during pagination

**Current Handling:**
- Returns what we have so far
- Logs warning about partial failure
- Continues to next page

**Strengths:**
- ✅ Returns partial data instead of failing completely
- ✅ Logs warning about partial failure

**Weaknesses:**
- ⚠️ May return incomplete position data
- ⚠️ No indication to caller that data is incomplete
- ⚠️ Could cause position reconciliation errors

**Recommendation:**
1. Consider adding a flag to indicate partial failure
2. Consider returning error instead of partial data for critical operations

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
9. ✅ Partial failure handling (returns what we have so far)
10. ✅ Max pages limit prevents runaway pagination
11. ✅ Yields between pages to prevent event loop blocking
12. ✅ Handles both market_positions and event_positions
13. ✅ Fallback to legacy "positions" field

### Weaknesses
1. ⚠️ Partial failure may return incomplete position data
2. ⚠️ No special handling for empty position data validation
3. ⚠️ No special handling for long-running pagination timeouts
4. ⚠️ No indication to caller that data is incomplete
5. ⚠️ Only one re-auth attempt

### Recommendations

#### High Priority
1. **Add partial failure flag:** Return a flag to indicate that data is incomplete
2. **Add empty data validation:** Validate that empty response is expected

#### Medium Priority
3. **Add pagination timeout configuration:** Allow longer timeout for multi-page fetches
4. **Multiple re-auth attempts:** Consider multiple re-auth attempts for transient auth issues

#### Low Priority
5. **Add positions-specific metrics:** Track positions-specific metrics (fetch success rate, pagination depth, partial failure rate)

### Conclusion
The error handling around `client.get_positions()` is **well implemented** with comprehensive coverage of all failure modes. The partial failure handling is a good feature for resilience, but it could be improved by adding a flag to indicate incomplete data. The pagination logic is robust with max pages limit and yielding between pages. The only improvements would be to add validation for empty data and configuration for pagination timeouts.
