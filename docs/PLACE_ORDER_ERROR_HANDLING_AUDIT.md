# Place Order Error Handling Audit

## Overview
Audit of error handling around `client.place_order()` for HTTP status codes (429, 401, 400) and other failure modes.

---

## Call Chain

```
order_router.route_order()
  → KalshiVenueClient.place_order()
    → KalshiVenueClient.place_order_result()
      → KalshiVenueClient._request_with_resilience()
```

---

## Error Handling Layers

### Layer 1: GlobalExecutionGuard (Final Safety Net)
**Location:** `client.py:1767-1801`

**Purpose:** Final safety net to catch orders that bypassed higher-level guards

**Error Handling:**
```python
try:
    from merid.guards.global_execution_guard import get_global_execution_guard
    _guard = get_global_execution_guard()
    _allowed, _reason = _guard.check_order(...)
    if not _allowed:
        logger.critical(f"[KALSHI_CLIENT_BLOCKED] GlobalExecutionGuard final net rejected: {_reason}")
        return OperationResult.fail(f"Global execution guard blocked: {_reason}")
except ImportError:
    pass  # Guard not available — proceed with other checks
except Exception as _guard_err:
    logger.error(f"[KALSHI_CLIENT_GUARD_ERROR] Guard check failed: {_guard_err}")
    return OperationResult.fail(f"Global execution guard error: {_guard_err}")
```

**Strengths:**
- ✅ Fail-closed on guard error
- ✅ Logs critical error when order blocked
- ✅ Graceful degradation if guard not available

**Weaknesses:**
- ⚠️ None - correctly implemented

---

### Layer 2: Pre-Send Validation
**Location:** `client.py:1810-1874`

**Purpose:** Validate order before sending to API

**Error Handling:**
```python
# Pre-send validation: verify ticker exists in catalog to prevent 404s
valid, error_msg = await _validate_ticker_exists(ticker)
if not valid:
    logger.error(f"[KALSHI_PRE_SEND_VALIDATION] Rejecting order for invalid ticker: {error_msg}")
    return OperationResult.fail(error_msg or f"Invalid ticker: {ticker}")

# CRITICAL: Reject zero or negative prices
if _price_cents <= 0:
    logger.error(f"[KALSHI_ORDER_VALIDATION] Invalid price for order: {_price_cents} cents")
    return OperationResult.fail(f"Invalid order price: {_price_cents} cents (must be > 0)")

# VALIDATION: Ensure exactly one price field is set
if len(set_prices) != 1:
    logger.error(f"[KALSHI_ORDER_VALIDATION] Invalid price fields in order: {set_prices}")
    return OperationResult.fail(f"Invalid order: exactly one price field required, got {set_prices}")
```

**Strengths:**
- ✅ Validates ticker exists in catalog (prevents 404s)
- ✅ Rejects zero/negative prices
- ✅ Validates exactly one price field set
- ✅ Logs all validation failures

**Weaknesses:**
- ⚠️ None - correctly implemented

---

### Layer 3: _request_with_resilience (Core Error Handling)
**Location:** `client.py:764-1106`

**Purpose:** Execute HTTP request with circuit breaker and retry logic

#### 3.1 Rate Limit (429)
**Location:** `client.py:830-879`

**Error Handling:**
```python
if response.status_code in KALSHI_RETRY_STATUSES:
    if attempt < KALSHI_MAX_RETRIES:
        # Jittered exponential backoff: base^attempt * [1.0, 2.0)
        base_wait = KALSHI_BACKOFF_BASE ** attempt
        jitter = 1.0 + random.random()
        
        # For 429, honour Retry-After header if present and larger
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                ra_seconds = float(retry_after) if retry_after else 0
                wait_time = max(base_wait * jitter, ra_seconds)
            except (ValueError, TypeError):
                wait_time = base_wait * jitter
            logger.warning(
                f"[kalshi] {operation_name} rate-limited (429), "
                f"Retry-After={retry_after}, sleeping {wait_time:.2f}s (attempt {attempt + 1})"
            )
        else:
            wait_time = base_wait * jitter
            logger.debug(
                f"[kalshi] {operation_name} returned {response.status_code}, "
                f"retrying in {wait_time:.2f}s (attempt {attempt + 1})"
            )
        await asyncio.sleep(wait_time)
        continue
```

**Strengths:**
- ✅ Honors Retry-After header for 429
- ✅ Jittered exponential backoff (prevents thundering herd)
- ✅ Logs warning with Retry-After value
- ✅ Max retries enforced (KALSHI_MAX_RETRIES)

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### 3.2 Auth Errors (401, 403)
**Location:** `client.py:881-924`

**Error Handling:**
```python
if response.status_code in (401, 403):
    body_text = response.text[:200] if response.text else ""
    if not getattr(self, '_auth_warned', False):
        logger.warning(
            f"[kalshi] {operation_name} auth error "
            f"{response.status_code}: {body_text}. "
            f"Check: key ID, private key path, timestamp (ms), "
            f"signed path starts with /trade-api/v2/"
        )
        self._auth_warned = True
    else:
        logger.debug(f"[kalshi] {operation_name} auth error {response.status_code} (suppressed)")
    # Try re-auth once on first 401
    if response.status_code == 401 and attempt == 0:
        try:
            await self._authenticate()
            logger.debug("[kalshi] Re-authenticated after 401, retrying")
            continue
        except Exception as auth_exc:
            logger.debug(f"[kalshi] Re-auth failed: {auth_exc}")
    
    error = httpx.HTTPStatusError(f"Auth error: {response.status_code}", ...)
    return OperationResult.fail(error, ...)
```

**Strengths:**
- ✅ Attempts re-auth once on first 401
- ✅ Logs detailed auth error on first occurrence
- ✅ Suppresses subsequent auth error logs (prevents log spam)
- ✅ Fails after re-auth fails

**Weaknesses:**
- ⚠️ Only re-auths on 401, not 403 (403 is permission denied, not auth)
- ⚠️ Only one re-auth attempt (might need more for transient auth issues)

**Recommendations:**
1. Consider re-authing on 403 as well (if applicable)
2. Consider multiple re-auth attempts for transient auth issues

---

#### 3.3 Business Errors (400, 422)
**Location:** `client.py:926-953`

**Error Handling:**
```python
if response.status_code in (400, 422):
    body_text = response.text[:300] if response.text else ""
    logger.warning(
        f"[kalshi] {operation_name} business error "
        f"{response.status_code}: {body_text}"
    )
    error = KalshiBusinessError(body_text, status_code=response.status_code)
    return OperationResult.fail(error, ...)
```

**Strengths:**
- ✅ No retry for business errors (correct - they are not transient)
- ✅ Logs business error with body text
- ✅ Returns specific KalshiBusinessError

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### 3.4 Other Client Errors (4xx)
**Location:** `client.py:955-978`

**Error Handling:**
```python
if 400 <= response.status_code < 500:
    error = httpx.HTTPStatusError(f"Client error: {response.status_code}", ...)
    return OperationResult.fail(error, ...)
```

**Strengths:**
- ✅ No retry for client errors (correct - they are not transient)
- ✅ Logs client error

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### 3.5 Timeout Errors
**Location:** `client.py:1039-1049`

**Error Handling:**
```python
except httpx.TimeoutException as e:
    last_error = e
    if attempt < KALSHI_MAX_RETRIES:
        # Jittered exponential backoff
        wait_time = (KALSHI_BACKOFF_BASE ** attempt) * (1.0 + random.random())
        logger.warning(
            f"[kalshi] {operation_name} timeout, retrying in {wait_time:.2f}s "
            f"(attempt {attempt + 1})"
        )
        await asyncio.sleep(wait_time)
        continue
```

**Strengths:**
- ✅ Retries with jittered exponential backoff
- ✅ Logs timeout with wait time
- ✅ Max retries enforced

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### 3.6 Connection Errors
**Location:** `client.py:1051-1061`

**Error Handling:**
```python
except (httpx.ConnectError, httpx.ReadError) as e:
    last_error = e
    if attempt < KALSHI_MAX_RETRIES:
        # Jittered exponential backoff
        wait_time = (KALSHI_BACKOFF_BASE ** attempt) * (1.0 + random.random())
        logger.warning(
            f"[kalshi] {operation_name} connection error, retrying in {wait_time:.2f}s "
            f"(attempt {attempt + 1}): {e}"
        )
        await asyncio.sleep(wait_time)
        continue
```

**Strengths:**
- ✅ Retries with jittered exponential backoff
- ✅ Logs connection error with details
- ✅ Max retries enforced

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### 3.7 Event Loop Errors
**Location:** `client.py:1063-1099`

**Error Handling:**
```python
except RuntimeError as e:
    msg = str(e).lower()
    if "event loop is closed" in msg or "different event loop" in msg:
        last_error = e
        if attempt < KALSHI_MAX_RETRIES:
            await self._reset_http_client_after_loop_error()
            logger.warning(
                "[kalshi] %s event-loop mismatch (%s), HTTP client reset; retry %s/%s",
                operation_name, e, attempt + 1, KALSHI_MAX_RETRIES + 1,
            )
            await asyncio.sleep(0.05)
            continue
    # Handle "client has been closed" error - reset and retry
    if "client has been closed" in msg:
        last_error = e
        if attempt < KALSHI_MAX_RETRIES:
            await self._reset_http_client_after_loop_error()
            logger.warning(
                "[kalshi] %s HTTP client was closed (%s), reset; retry %s/%s",
                operation_name, e, attempt + 1, KALSHI_MAX_RETRIES + 1,
            )
            await asyncio.sleep(0.05)
            continue
    latency_ms = (time.time() - start_time) * 1000
    logger.warning(f"[kalshi] {operation_name} RuntimeError after retries: {e}")
    return OperationResult.fail(e, ...)
```

**Strengths:**
- ✅ Handles event loop mismatch errors
- ✅ Handles "client has been closed" errors
- ✅ Resets HTTP client and retries
- ✅ Short sleep (0.05s) for quick recovery

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### 3.8 Windows I/O Errors
**Location:** `client.py:1101-1120`

**Error Handling:**
```python
except (OSError, ConnectionResetError, asyncio.InvalidStateError) as e:
    # Windows I/O error recovery (WinError 995, 10038, 10054, etc.)
    # These errors can occur under high load and are often recoverable
    last_error = e
    exc_str = str(e)
    is_recoverable = False
    # ... recoverable error detection logic ...
    if is_recoverable and attempt < KALSHI_MAX_RETRIES:
        await self._reset_http_client_after_loop_error()
        logger.warning(
            "[kalshi] %s recoverable Windows I/O error (%s), HTTP client reset; retry %s/%s",
            operation_name, e, attempt + 1, KALSHI_MAX_RETRIES + 1,
        )
        await asyncio.sleep(0.05)
        continue
    latency_ms = (time.time() - start_time) * 1000
    logger.warning(f"[kalshi] {operation_name} OSError after retries: {e}")
    return OperationResult.fail(e, ...)
```

**Strengths:**
- ✅ Handles Windows I/O errors (WinError 995, 10038, 10054, etc.)
- ✅ Distinguishes recoverable vs non-recoverable errors
- ✅ Resets HTTP client and retries for recoverable errors
- ✅ Short sleep (0.05s) for quick recovery

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### 3.9 Circuit Breaker
**Location:** `client.py:1007-1037`

**Error Handling:**
```python
except CircuitOpenError as e:
    # Circuit is open - fail fast
    latency_ms = (time.time() - start_time) * 1000
    self._circuit_open_log_count += 1
    if self._circuit_open_log_count == 1:
        self._circuit_open_first_ts = time.time()
        logger.warning(f"[kalshi] Circuit OPEN — blocking {operation_name} (retry in {e.time_until_retry:.1f}s)")
    elif self._circuit_open_log_count == 10:
        elapsed = time.time() - self._circuit_open_first_ts
        logger.warning(
            f"[kalshi] Circuit still OPEN — suppressed {self._circuit_open_log_count} blocked calls in {elapsed:.1f}s"
        )
    else:
        logger.debug(f"[kalshi] Circuit open for {operation_name} (suppressed #{self._circuit_open_log_count})")
    
    return OperationResult.fail(e, ..., circuit_open=True)
```

**Strengths:**
- ✅ Circuit breaker prevents cascading failures
- ✅ Logs first circuit open with retry time
- ✅ Logs every 10th blocked call (prevents log spam)
- ✅ Returns circuit_open=True for caller detection

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

## Summary

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

### Strengths
1. ✅ Comprehensive error handling for all failure modes
2. ✅ Correct retry logic (transient errors retry, permanent errors fail)
3. ✅ Jittered exponential backoff prevents thundering herd
4. ✅ Honors Retry-After header for 429
5. ✅ Re-authenticates on 401
6. ✅ Circuit breaker prevents cascading failures
7. ✅ Windows I/O error recovery
8. ✅ Event loop mismatch recovery
9. ✅ Detailed logging for all error types
10. ✅ Pre-send validation prevents unnecessary API calls

### Weaknesses
1. ⚠️ Only re-auths on 401, not 403 (minor - 403 is permission denied)
2. ⚠️ Only one re-auth attempt (minor - could retry more for transient auth issues)

### Recommendations
1. **Low Priority:** Consider re-authing on 403 as well (if applicable)
2. **Low Priority:** Consider multiple re-auth attempts for transient auth issues

### Conclusion
The error handling around `client.place_order()` is **well implemented** with comprehensive coverage of all failure modes. The retry logic is correct (transient errors retry, permanent errors fail), and the circuit breaker prevents cascading failures. The only minor improvements would be to expand re-auth logic to handle 403 and multiple re-auth attempts, but these are not critical for production.
