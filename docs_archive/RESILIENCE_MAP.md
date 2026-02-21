# MERID Resilience Map

**Generated**: 2026-02-04
**Status**: ✅ Complete - Resilience layer implemented and tested

## Critical Failure Points

### 1. Venue HTTP/REST Calls

| Component | Location | Current Handling | Gap |
|-----------|----------|------------------|-----|
| HTTPExecutor | `merid/execution/http_base.py` | ✓ Retries (3x), backoff, timeout, error normalization | Good baseline |
| KalshiVenueClient | `merid/event_venues/kalshi/client.py` | Basic try/except, returns None/[] | No retries, no circuit breaker |
| PolymarketVenueClient | `merid/event_venues/polymarket/client.py` | Basic try/except, returns None/[] | No retries, no circuit breaker |
| Trading Adapters | `trading/adapters/*.py` | Varies by adapter | Inconsistent error handling |

### 2. Order Submission

| Failure Mode | Current Behavior | Risk | Recommended |
|--------------|------------------|------|-------------|
| Timeout mid-order | Unclear state | HIGH - duplicate orders | Idempotency key (HTTPExecutor has it) |
| 5xx on submit | Retry in HTTPExecutor | MEDIUM | Verify idempotency propagates to venues |
| Rate limit (429) | Retry with backoff | LOW | Already handled |
| Auth failure (401/403) | NonRetryableError | LOW | Already handled |
| Malformed response | ValueError/KeyError → None | MEDIUM | Should surface error, not silent None |

### 3. Position Sync

| Component | Failure Mode | Current Behavior | Gap |
|-----------|--------------|------------------|-----|
| Kalshi get_positions | Network error | Returns [] | Silent failure - caller doesn't know |
| Polymarket get_positions | Network error | Returns [] | Silent failure |
| Position reconciliation | Stale data | No staleness detection | Need timestamp + TTL |

### 4. Pricing Feeds

| Component | Failure Mode | Current Behavior | Gap |
|-----------|--------------|------------------|-----|
| get_orderbook | Network error | Returns None | Silent failure |
| Quote staleness | Old quotes | No staleness check | Need max_age validation |
| WebSocket disconnect | Connection drop | Varies | Need reconnect logic |

### 5. Config/Environment Loading

| Component | Location | Current Behavior | Gap |
|-----------|----------|------------------|-----|
| KalshiConfig | `kalshi/models.py` | Reads env vars | No validation of required fields |
| PolymarketConfig | `polymarket/models.py` | Reads env vars | No validation |
| Runtime config | `trading/config/` | Validated | Good |

---

## Existing Resilience Primitives

### HTTPExecutor (`merid/execution/http_base.py`)

```python
# Already implemented:
- Retry with exponential backoff (2^attempt seconds)
- Max retries: 3 (configurable)
- Retry statuses: {429, 500, 502, 503, 504}
- Timeout handling → TimeoutError
- Error normalization → RetryableError / NonRetryableError
- Idempotency keys for POST/PUT/PATCH
- Request metrics + slow request logging (>1000ms)
```

### What's Missing

1. **Circuit Breaker** - No circuit breaker to prevent hammering failing venues
2. **Consistent Error Propagation** - Venue clients swallow errors, return None/[]
3. **Health Checks** - No periodic health probes
4. **Cancellation Support** - No structured cancellation tokens
5. **Bulkhead Pattern** - No isolation between venue failures

---

## Recommended Standard Behaviors

### Retry Policy (by operation type)

| Operation | Retries | Backoff | Circuit Break |
|-----------|---------|---------|---------------|
| Market data (GET) | 3 | Exponential 1-4s | After 5 failures in 30s |
| Order submission (POST) | 2 | Exponential 2-8s | After 3 failures in 60s |
| Order cancel (DELETE) | 3 | Linear 1s | Never (best effort) |
| Position sync (GET) | 2 | Exponential 1-4s | After 5 failures in 30s |
| Auth/login | 1 | None | After 2 failures in 5min |

### Error Classes

```
ExecutionError (base)
├── RetryableError (5xx, timeout, rate limit)
│   ├── TimeoutError
│   └── RateLimitError
├── NonRetryableError (4xx, auth, validation)
│   ├── AuthenticationError
│   └── ValidationError
└── CircuitOpenError (circuit breaker tripped)
```

### Circuit Breaker States

```
CLOSED → (failure_count >= threshold) → OPEN
OPEN → (after cooldown_period) → HALF_OPEN
HALF_OPEN → (success) → CLOSED
HALF_OPEN → (failure) → OPEN
```

---

## Implementation Plan

### Step 1: Resilience Primitives (this block)

- [ ] Create `merid/resilience/` module
- [ ] Implement `CircuitBreaker` class
- [ ] Implement `retry_with_backoff` decorator (reusable)
- [ ] Implement `with_timeout` context manager
- [ ] Add `OperationResult<T>` type for explicit success/failure

### Step 2: Wire Into Venue Clients

- [ ] Update KalshiVenueClient to use primitives
- [ ] Update PolymarketVenueClient to use primitives
- [ ] Update Trading Adapters to use primitives
- [ ] Add circuit breaker per venue

### Step 3: Observability

- [ ] Add structured logging for resilience events
- [ ] Add metrics: retry_count, circuit_state, latency_p99
- [ ] Add health check endpoint

### Step 4: Smoke Tests

- [ ] Test timeout handling
- [ ] Test 5xx retry behavior
- [ ] Test circuit breaker state transitions
- [ ] Test malformed response handling

---

## Appendix: Error Handling Patterns Found

### Pattern A: Silent Failure (BAD)
```python
# Found in venue clients
try:
    response = await self._http_client.get(url)
    ...
except (ConnectionError, RuntimeError, ValueError) as e:
    logger.error(f"Failed: {e}")
    return []  # Caller can't distinguish "no data" from "error"
```

### Pattern B: Error Propagation (GOOD)
```python
# Found in HTTPExecutor
if response.status_code in self.retry_statuses:
    raise RetryableError(...)
```

### Pattern C: Recommended
```python
# Explicit result type
@dataclass
class OperationResult(Generic[T]):
    success: bool
    data: Optional[T]
    error: Optional[ExecutionError]
    retries: int
    latency_ms: float
```
