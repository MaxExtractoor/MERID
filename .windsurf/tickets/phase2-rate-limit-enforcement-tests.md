# Phase 2: Rate-Limit Enforcement Tests

**Priority:** High  
**Baseline:** Commit `c25d2702` - Kalshi WS bridge + explainability integration  
**Component:** `merid/event_venues/kalshi/rest.py`, `merid/event_venues/kalshi/client.py`

## Summary

Implement comprehensive rate-limit enforcement tests to ensure MERID respects Kalshi's documented tier limits, handles 429 responses correctly, and never retries non-retryable 4xx errors.

## Acceptance Criteria

### 1. 429 Response with Retry-After Header
- [x] Mock Kalshi REST endpoint returning 429 with `Retry-After: 5` header
- [x] Assert client waits exactly 5 seconds before retry
- [x] Verify retry succeeds after waiting period
- [x] Test multiple sequential 429s → assert cumulative backoff respects each `Retry-After`

**Reference:** [Kalshi Rate Limits](https://docs.kalshi.com/getting_started/rate_limits)

### 2. 429 Response without Retry-After Header
- [x] Mock 429 response with no `Retry-After` header
- [x] Assert client applies exponential backoff (e.g., 1s, 2s, 4s, 8s)
- [x] Verify backoff caps at reasonable maximum (e.g., 60s)
- [x] Test eventual success after backoff sequence

### 3. Non-Retryable 4xx Errors
- [x] Mock 400 (Bad Request) response
- [x] Assert client never retries, surfaces error immediately to caller
- [x] Mock 401 (Unauthorized) response
- [x] Assert client never retries auth failures (re-auth once, then fail)
- [x] Mock 403 (Forbidden) response
- [x] Assert client surfaces permission error without retry

### 4. Self-Throttling
- [x] Configure client for Basic tier (20 read requests/sec, 10 write requests/sec)
- [x] Send burst of 30 read requests
- [x] Assert client throttles requests to stay at/below 20 req/sec
- [x] Measure actual request rate over 5-second window
- [x] Verify sustained rate compliance

**Reference:** [Kalshi Rate Limits - Tier Limits](https://docs.kalshi.com/getting_started/rate_limits)

## Test File Location

`tests/event_venues/kalshi/test_rate_limits.py`

## Implementation Notes

- Use `respx` library to mock HTTP responses with custom headers
- Track request timestamps to measure actual rate
- Use `time.time()` or `asyncio` time controls for precise timing assertions
- Test both REST client (`KalshiVenueClient`) and any direct API wrappers

## Definition of Done

- [x] All test scenarios pass (17/17 passed)
- [x] Rate-limit logic verified for read and write endpoints
- [x] No false positives (client doesn't throttle below tier limit)
- [x] CI green — added to `hardening-tests` job
