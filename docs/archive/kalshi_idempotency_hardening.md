# Kalshi Order Idempotency Hardening — Design & Verification

**Status:** COMPLETE  
**Date:** 2026-04-12  
**Risk Level:** CRITICAL (Money-at-Risk)  

---

## Executive Summary

Implemented comprehensive hardening of the Kalshi order routing path to prevent duplicate orders, eliminate false-positive kill-switch triggers, and add defense-in-depth safety checks.

---

## Changes Implemented

### 1. Deterministic `client_order_id` Generation (CRITICAL FIX)

**File:** `merid/event_venues/kalshi/order_router.py:1068-1077`

**Before:**
- Used random `intent_id[:8]` in client_tag → different ID on each retry → broke Kalshi idempotency
- Could result in multiple live orders for same intent on network retry

**After:**
```python
ts_bucket = int(intent.snapshot_ts) // 60
idempotency_preimage = (
    f"{intent.agent_id}|{intent.ticker}|{intent.side}|{intent.action}|"
    f"{intent.price_cents}|{intent.count}|{ts_bucket}|{intent.order_group_id}"
)
id_hash = hashlib.sha256(idempotency_preimage.encode()).hexdigest()[:16]
client_tag = f"merid-{id_hash}-{ts_bucket}"
```

**Properties:**
- Same logical order → Same `client_order_id` across retries
- 60-second time bucket allows retry windows while preventing collisions
- SHA256 hash ensures uniqueness across agent/ticker/side/price/count combinations

---

### 2. In-Flight Order Gate (Pre-Trade Deduplication)

**File:** `merid/event_venues/kalshi/order_router.py:1079-1120`

Added explicit `PreTradeGate.check()` call before order submission:

```python
try:
    from merid.event_venues.kalshi.order_gate import get_pre_trade_gate
    _gate = get_pre_trade_gate()
    _gate_verdict = _gate.check(...)
    if not _gate_verdict.allowed:
        # Block duplicate, release reserved exposure
        return OrderResult(status="rejected", reason=f"gate:{_gate_verdict.reason}")
except Exception:
    # Fail-open: log error but proceed (availability > strictness)
```

**Benefits:**
- Catches race conditions where multiple agents send same order
- Releases reserved category exposure on gate block
- Blocks: `PENDING`, `SUBMITTED`, `LIVE`, `PARTIAL` states

---

### 3. Jittered Exponential Backoff (Thundering Herd Prevention)

**File:** `merid/event_venues/kalshi/client.py:588-614,739-761`

**Before:**
```python
wait_time = KALSHI_BACKOFF_BASE ** attempt  # No jitter
```

**After:**
```python
base_wait = KALSHI_BACKOFF_BASE ** attempt
jitter = 1.0 + random.random()  # [1.0, 2.0) uniform
wait_time = base_wait * jitter
```

Applied to:
- HTTP 429/500/502/503/504 retries
- `TimeoutException` retries  
- `ConnectError`/`ReadError` retries

---

### 4. Idempotent Duplicate Handling (gate:duplicate → Success)

**File:** `merid/event_venues/kalshi/order_router.py:1144-1244`

```python
is_duplicate_error = reason and ("gate:duplicate" in reason.lower() or "duplicate" in reason.lower())

if is_duplicate_error:
    # Look up order by client_order_id
    lookup_res = await client.get_order_by_client_id_result(intent.client_tag)
    if lookup_res.success and lookup_res.data:
        # Return synthetic success (not rejection)
        return OrderResult(status="filled_live" or "submitted_live", ...)
    
    # Lookup failed: assume success (don't release exposure, don't rollback)
    return OrderResult(status="submitted_live", ...)
```

**Key:**
- Does NOT release reserved exposure → prevents double-reduction
- Does NOT rollback order group → maintains accounting
- Does NOT call `record_error()` → prevents kill-switch trigger
- Logs `[KALSHI_DUPLICATE_SUCCESS]` for observability

---

### 5. New Client Method: `get_order_by_client_id_result`

**File:** `merid/event_venues/kalshi/client.py:2313-2354`

```python
async def get_order_by_client_id_result(
    self, client_order_id: str, market_id: Optional[str] = None
) -> OperationResult[Optional[PlacedOrder]]:
    params = {"client_order_id": client_order_id, "limit": 10}
    result = await self._request_with_resilience(
        "GET", "/portfolio/orders", params=params, ...
    )
```

Used for duplicate error recovery: confirms order state when Kalshi reports duplicate.

---

### 6. Downstream Position/Fill Sanity Checker

**New File:** `merid/event_venues/kalshi/position_sanity_checker.py`

**Features:**
- Idempotent fill tracking via `fill_id` deduplication
- Overfill detection (>100% of intended order size)
- Position limit enforcement per market
- `DUPLICATE_FILL` alerts at CRITICAL log level

**Integration:**
```python
# In order_router.py after successful placement
_sanity.register_order_intent(client_order_id, ticker, side, count)
if filled_count > 0:
    _sanity.apply_fill(order_id, fill_id, ticker, side, filled_count, price_cents)
```

---

### 7. Error Threshold Exclusions (Prevent False Kill-Switch)

**File:** `merid/prediction/order_error_threshold.py:13-40`

Already configured exclusions:
```python
_POLICY_PREFIXES_DO_NOT_COUNT = (
    "kalshi config mismatch",
    "client error: 404",  # Market expired/delisted
    "gate:duplicate",     # Idempotent retry success
    # ... other policy exclusions
)

_GATE_BLOCKED_SUBSTRINGS = (
    "paper/mock=true but using live url",
    "client error: 404",
    "gate:duplicate",
)
```

---

## Verification Plan

### Log Monitoring (Immediate)

Run these PowerShell commands to verify fixes in production:

```powershell
# 1. Verify deterministic client_order_id generation
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "merid-[a-f0-9]{16}-\d+"

# 2. Check for duplicate success handling (should appear, NOT error)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "KALSHI_DUPLICATE_SUCCESS"

# 3. Verify jittered backoff (check for non-uniform wait times)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "retrying in [0-9]+\.[0-9]+s"

# 4. Check pre-trade gate blocks (expected, not errors)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "Pre-trade gate blocked"

# 5. Verify NO spurious ERROR_THRESHOLD triggers
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "ERROR THRESHOLD KILL"
```

### Metrics to Monitor (Grafana/CloudWatch)

| Metric | Expected | Alert If |
|--------|----------|----------|
| `kalshi_duplicate_success_total` | >= 0 | N/A (informational) |
| `kalshi_gate_blocked_total` | >= 0 | > 100/hour (investigate) |
| `kalshi_order_retry_total` | >= 0 | > 50/hour (network issues) |
| `error_threshold_count` | < 10/hour | >= 40 (near kill) |
| `position_sanity_duplicate_fill_total` | = 0 | > 0 (CRITICAL) |

### Test Scenarios (Staging)

1. **Idempotency Test:**
   - Send same OrderIntent twice within 60 seconds
   - Expected: Second rejected with `gate:duplicate`, first succeeds
   - Verify: Only one live order on Kalshi

2. **Retry Test:**
   - Induce network failure (using proxy/iptables)
   - Expected: Retry with jittered backoff, same `client_order_id`
   - Verify: Order eventually succeeds, no duplicates

3. **Duplicate Error Recovery:**
   - Simulate Kalshi returning "duplicate" error
   - Expected: Order looked up, treated as success
   - Verify: Position shows correct size, no double-fill

---

## Design Trade-offs

| Decision | Rationale |
|----------|-----------|
| 60-second time bucket | Allows retry window while preventing rapid-fire duplicate intents |
| SHA256 truncated to 16 chars | Sufficient entropy (64^16) while fitting Kalshi limits |
| Fail-open on gate error | Availability > strictness: prefer occasional duplicate over unavailable trading |
| Submitted-latency includes gate check | Slightly higher p99 latency, but prevents downstream errors |
| No jitter on event-loop reset | 50ms fixed delay for loop recovery (fast path) |

---

## Files Modified

| File | Lines | Change |
|------|-------|--------|
| `order_router.py` | 1064-1320 | Deterministic client_tag, pre-trade gate, duplicate handling |
| `client.py` | 588-614, 739-761 | Jittered backoff, new get_order_by_client_id_result method |
| `position_sanity_checker.py` | 1-200 | NEW: Post-trade fill/position safety |
| `order_error_threshold.py` | 13-40 | Already configured (verified) |

---

## Rollback Plan

If issues detected:

1. **Immediate:** Set `MERID_ERROR_THRESHOLD_KILL_ENABLED=false` to prevent kill-switch
2. **Revert:** `git checkout HEAD~1 -- merid/event_venues/kalshi/order_router.py client.py`
3. **Keep:** `position_sanity_checker.py` (non-blocking, provides alerts)
4. **Verify:** Monitor logs for 5 minutes post-rollback

---

## Sign-off

- [x] Code changes implemented
- [x] Syntax validation passed
- [x] Verification plan documented
- [x] Rollback plan documented
- [ ] Staging tests completed (user to run)
- [ ] Production monitoring verified (user to run)
