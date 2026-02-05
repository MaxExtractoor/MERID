# Resilient Venue Client Recipe

**Status**: Production-ready  
**Reference Implementation**: `merid/event_venues/kalshi/client.py`

This document describes the canonical pattern for building resilient venue clients in MERID.

## Overview

Every venue client should implement three resilience patterns:

1. **Circuit Breaker** - Prevent cascading failures by blocking calls to failing venues
2. **Retry with Backoff** - Automatically retry transient failures with exponential backoff
3. **Explicit Results** - Return `OperationResult` for clear success/failure handling

## Quick Start

```python
from merid.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    OperationResult,
    get_circuit_breaker,
)

class MyVenueClient:
    def __init__(self):
        # One circuit breaker per venue instance
        self._circuit_breaker = get_circuit_breaker(
            f"my_venue_{id(self)}",
            failure_threshold=5,      # Open after 5 failures
            recovery_timeout=30.0,    # Try recovery after 30s
        )
    
    async def get_data(self) -> List[Data]:
        """Backward-compatible method - returns [] on failure."""
        result = await self.get_data_result()
        return result.unwrap_or([])
    
    async def get_data_result(self) -> OperationResult[List[Data]]:
        """Explicit result method - returns error details."""
        result = await self._request_with_resilience(
            "GET", "/data", operation_name="get_data"
        )
        if not result.success:
            return OperationResult.fail(result.error)
        return OperationResult.ok(parse_data(result.data))
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Public API Layer                          │
│  get_market() → Market | None  (backward-compatible)        │
│  get_market_result() → OperationResult[Market] (explicit)   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               _request_with_resilience()                     │
│  - Circuit breaker check                                     │
│  - Retry loop with backoff                                   │
│  - Error classification                                      │
│  - Metrics/logging                                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    HTTP Client (httpx)                       │
└─────────────────────────────────────────────────────────────┘
```

## Configuration Constants

Define these at module level for easy tuning:

```python
# Retry configuration
VENUE_MAX_RETRIES = 3
VENUE_BACKOFF_BASE = 2.0  # 1s, 2s, 4s backoff
VENUE_RETRY_STATUSES = {429, 500, 502, 503, 504}

# Circuit breaker configuration
VENUE_CIRCUIT_FAILURE_THRESHOLD = 5
VENUE_CIRCUIT_RECOVERY_TIMEOUT = 30.0
```

## The Core Request Method

Every resilient venue client needs a `_request_with_resilience` method:

```python
async def _request_with_resilience(
    self,
    method: str,
    path: str,
    *,
    params: Optional[Dict] = None,
    json_data: Optional[Dict] = None,
    operation_name: str = "request",
) -> OperationResult[Dict[str, Any]]:
    """
    Execute HTTP request with circuit breaker and retry logic.
    """
    start_time = time.time()
    last_error = None
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            # 1. Check circuit breaker
            async with self._circuit_breaker:
                response = await self._http_client.request(
                    method=method,
                    url=f"{self.base_url}{path}",
                    params=params,
                    json=json_data,
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                # 2. Handle retryable status codes
                if response.status_code in RETRY_STATUSES:
                    if attempt < MAX_RETRIES:
                        wait_time = BACKOFF_BASE ** attempt
                        logger.warning(f"Retrying {operation_name} in {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    return OperationResult.fail(
                        error, latency_ms=latency_ms, retries=attempt
                    )
                
                # 3. Handle client errors (no retry)
                if 400 <= response.status_code < 500:
                    return OperationResult.fail(
                        error, latency_ms=latency_ms, retries=attempt
                    )
                
                # 4. Success
                return OperationResult.ok(
                    response.json(),
                    latency_ms=latency_ms,
                    retries=attempt,
                )
                
        except CircuitOpenError as e:
            # Circuit is open - fail fast
            return OperationResult.fail(e, circuit_open=True)
            
        except (TimeoutException, ConnectError) as e:
            # Retry on network errors
            last_error = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(BACKOFF_BASE ** attempt)
                continue
    
    # Max retries exhausted
    return OperationResult.fail(last_error, retries=MAX_RETRIES)
```

## Dual API Pattern

Every public method should have two versions:

| Method | Returns | Use Case |
|--------|---------|----------|
| `get_market(id)` | `Market \| None` | Backward compatibility, simple scripts |
| `get_market_result(id)` | `OperationResult[Market]` | Production code, explicit error handling |

```python
async def get_market(self, market_id: str) -> Optional[EventMarket]:
    """Backward-compatible - returns None on failure."""
    result = await self.get_market_result(market_id)
    return result.unwrap_or(None)

async def get_market_result(self, market_id: str) -> OperationResult[Optional[EventMarket]]:
    """Explicit result with error details."""
    result = await self._request_with_resilience(
        "GET", f"/markets/{market_id}",
        operation_name=f"get_market({market_id})"
    )
    
    if not result.success:
        return OperationResult.fail(
            result.error,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    market = self._parse_market(result.data)
    return OperationResult.ok(market, latency_ms=result.latency_ms)
```

## Error Classification

| Status Code | Behavior | Rationale |
|-------------|----------|-----------|
| 429 | Retry with backoff | Rate limit - will clear |
| 500-504 | Retry with backoff | Server issues - often transient |
| 400-499 | Fail fast (no retry) | Client error - won't fix on retry |
| Timeout | Retry with backoff | Network issue |
| Connection Error | Retry with backoff | Network issue |

## Circuit Breaker States

```
CLOSED (normal)
    │
    │ failure_count >= threshold
    ▼
OPEN (blocking)
    │
    │ after recovery_timeout
    ▼
HALF_OPEN (testing)
    │
    ├── success → CLOSED
    └── failure → OPEN
```

## Monitoring

```python
def get_circuit_status(self) -> Dict[str, Any]:
    """Expose circuit breaker status for monitoring."""
    return self._circuit_breaker.get_stats()

# Returns:
# {
#     "name": "kalshi_12345",
#     "state": "closed",
#     "failure_count": 0,
#     "failure_threshold": 5,
#     "time_until_retry": 0.0,
#     "recovery_timeout": 30.0,
# }
```

## Testing Resilient Clients

```python
@pytest.mark.asyncio
async def test_returns_fallback_on_error(client):
    """Backward-compatible methods return fallback on failure."""
    respx.get("/markets").mock(return_value=Response(500))
    
    markets = await client.list_markets()
    assert markets == []  # Fallback value

@pytest.mark.asyncio
async def test_result_method_exposes_error(client):
    """Result methods expose error details."""
    respx.get("/markets").mock(return_value=Response(500))
    
    result = await client.list_markets_result()
    assert not result.success
    assert result.error is not None
    assert result.retries > 0
```

## Checklist for New Venue Clients

- [ ] Import resilience primitives from `merid.resilience`
- [ ] Add circuit breaker in `__init__`
- [ ] Add bulkhead for concurrency isolation (optional but recommended)
- [ ] Add `_request_with_resilience` method
- [ ] Convert all public methods to dual API pattern
- [ ] Add `get_circuit_status()` for monitoring
- [ ] Update tests to use `_result` methods for error cases
- [ ] Document retry/circuit-breaker configuration

## Advanced: Bulkhead Pattern

For high-throughput venues, add a bulkhead to isolate concurrent operations:

```python
from merid.resilience import get_bulkhead, BulkheadFullError

class MyVenueClient:
    def __init__(self):
        self._circuit_breaker = get_circuit_breaker("my_venue")
        self._bulkhead = get_bulkhead(
            "my_venue",
            max_concurrent=10,  # Max parallel requests
            max_queued=50,      # Max waiting requests
        )
    
    async def _request_with_resilience(self, ...):
        async with self._bulkhead:  # Limits concurrency
            async with self._circuit_breaker:  # Tracks failures
                # ... make request
```

## Advanced: Prometheus Metrics

Export metrics for monitoring dashboards:

```python
from merid.resilience.metrics import get_metrics_text, get_metrics_json

# Prometheus text format
@app.get("/metrics")
async def metrics():
    return Response(get_metrics_text(), media_type="text/plain")

# JSON format for internal use
@app.get("/api/health/metrics")
async def metrics_json():
    return get_metrics_json()
```

Available metrics:
- `merid_circuit_breaker_state` - Circuit state (0=closed, 1=half_open, 2=open)
- `merid_circuit_breaker_failures_total` - Failure count
- `merid_bulkhead_active` - Active operations
- `merid_bulkhead_rejected_total` - Rejected requests
- `merid_risk_kill_switch_state` - Risk controller state

## Reference

- **Kalshi Client**: `merid/event_venues/kalshi/client.py` - Full reference implementation
- **Polymarket Client**: `merid/event_venues/polymarket/client.py` - Second reference
- **Resilience Primitives**: `merid/resilience/` - CircuitBreaker, Bulkhead, OperationResult
- **Metrics**: `merid/resilience/metrics.py` - Prometheus export
- **Failure Map**: `docs/RESILIENCE_MAP.md` - Critical failure points analysis
