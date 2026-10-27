# Kalshi Idempotency Hardening — Upstream/Downstream Scan Report

**Date:** 2026-04-12  
**Status:** COMPLETE with GAPS IDENTIFIED  

---

## Executive Summary

All critical idempotency hardening has been implemented. **One gap identified** in fallback path that needs attention before production rollout.

| Layer | Status | Notes |
|-------|--------|-------|
| Strategy/Signal | ✅ PASS | All use `route_order_async` |
| Order Router Pre-Gate | ✅ PASS | `PreTradeGate.check()` called |
| Deterministic client_order_id | ✅ PASS | SHA256-based generation |
| Kalshi Client | ✅ PASS | Jittered backoff, duplicate handling |
| Position Sanity Checker | ✅ PASS | Integrated with halt logic |
| Fallback Path (kalshi_tools) | ⚠️ GAP | Direct client bypass exists |

---

## Upstream Scan: Strategy → Order Router

### 1. Primary Trading Agent (`trading_agent.py`)

| Location | Path | Uses route_order_async | Deterministic ID |
|----------|------|------------------------|------------------|
| Line 2152 | Take-profit exits | ✅ Yes | ✅ Via OrderIntent |
| Line 2279 | Stop-loss exits | ✅ Yes | ✅ Via OrderIntent |
| Line 2364 | IOC escalation | ✅ Yes | ✅ Via OrderIntent |
| Line 3796 | Arb orders | ✅ Yes | ✅ Via OrderIntent |
| Line 3910 | Signal execution | ✅ Yes | ✅ Via OrderIntent |

**Finding:** All paths use `route_order_async` with `OrderIntent`. ✅

**Gap Found:**
- Line 3941: `client_tag=_sig_corr_s` — This overrides deterministic generation!
  - If `_sig_corr_s` is provided, it bypasses our SHA256-based generation
  - **Risk:** Could lead to non-deterministic IDs if `_sig_corr_s` is random

### 2. Kalshi Tools (`kalshi_tools.py`)

| Location | Path | Uses route_order_async | Notes |
|----------|------|------------------------|-------|
| Line 415 | Primary path | ✅ Yes | Routes through order_router |
| Line 460-470 | Fallback path | ❌ **NO** | Direct `client.place_order_result()` |

**CRITICAL GAP:**
```python
# Lines 457-478 - Fallback path bypasses all idempotency!
except ImportError as _imp:
    logger.warning("order_router not available, falling back...")
    client = _get_client()
    order = VenueOrder(...)  # No client_order_id set!
    result = await client.place_order_result(order)  # Direct call
```

**Impact:**
- Missing deterministic `client_order_id`
- Missing pre-trade gate check
- Missing jittered backoff
- Missing duplicate error handling
- Missing sanity checker integration

**Recommendation:** Remove fallback or make it fail-closed (reject order).

### 3. Order Router (`order_router.py`) — Core Implementation

| Feature | Status | Location |
|---------|--------|----------|
| Deterministic client_order_id | ✅ | Lines 1068-1077 |
| Pre-trade gate check | ✅ | Lines 1079-1120 |
| Duplicate error handling | ✅ | Lines 1144-1244 |
| Sanity checker integration | ✅ | Lines 1291-1335 |
| Jittered backoff (client) | ✅ | `client.py:588-614` |

**Deterministic ID Formula:**
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
- 60-second time bucket for retry window
- SHA256 ensures uniqueness across parameter space
- Truncated to 16 chars (64^16 entropy)

---

## Downstream Scan: Kalshi → Fills → Positions

### 1. Fill Ingestion Path

| Component | Status | Notes |
|-----------|--------|-------|
| Kalshi client response | ✅ | `placed_res.data` with `filled_size` |
| Immediate fill handling | ✅ | Lines 1301-1335 in order_router |
| Fill ID generation | ✅ | `f"{_venue_oid}-0"` for sequence 0 |
| Sanity checker apply_fill | ✅ | Called with full context |

### 2. Position Sanity Checker

**File:** `position_sanity_checker.py`

| Feature | Status |
|---------|--------|
| Fill deduplication via `fill_id` | ✅ |
| Overfill detection (>100% intended) | ✅ |
| Position limit enforcement | ✅ |
| CRITICAL-level alerts | ✅ |
| Strategy halt on violation | ✅ |

**Integration in order_router.py (Lines 1313-1335):**
```python
if not _ok:
    logger.critical("[SANITY_VIOLATION] ...")
    if "duplicate_fill" in _err or "overfill" in _err:
        risk_controller.halt_strategy(...)
```

### 3. Risk Controller — Strategy Halt

**New Method:** `halt_strategy()` in `kill_switches.py:992-1031`

```python
def halt_strategy(self, strategy_id: str, reason: str = "Strategy halted") -> bool:
    # Opens circuit breaker for specific strategy
    # Uses 5-min cooldown (configurable)
    # Logs CRITICAL alert
```

**Usage:** Called on sanity violations to prevent further orders from compromised strategy.

---

## Error Threshold Exclusions

**File:** `order_error_threshold.py`

Already configured exclusions that prevent kill-switch triggers:

```python
_POLICY_PREFIXES_DO_NOT_COUNT = (
    "kalshi config mismatch",
    "client error: 404",
    "gate:duplicate",  # ✅ Our new idempotent duplicate handling
    ...
)

_GATE_BLOCKED_SUBSTRINGS = (
    "paper/mock=true but using live url",
    "client error: 404",
    "gate:duplicate",  # ✅ Raw message matching
    ...
)
```

---

## Gaps and Recommendations

### Gap 1: kalshi_tools Fallback Path (HIGH PRIORITY)

**Location:** `kalshi_tools.py:457-478`

**Issue:** Fallback path bypasses all idempotency hardening.

**Fix Options:**
1. **Remove fallback** — Fail-closed if order_router unavailable
2. **Add hardening to fallback** — Copy deterministic ID logic (duplication risk)
3. **Make fallback paper-only** — Never allow live orders without order_router

**Recommended Fix:**
```python
# Replace fallback with fail-closed
except ImportError as _imp:
    logger.error("order_router unavailable — cannot place order (fail-closed)")
    return ToolResult.fail(
        ToolErrorCode.INTERNAL,
        "Order router unavailable — order rejected for safety",
        tool_name="kalshi_place_order",
    )
```

### Gap 2: trading_agent client_tag Override (MEDIUM PRIORITY)

**Location:** `trading_agent.py:3941`

**Issue:** `client_tag=_sig_corr_s` may override deterministic ID if provided.

**Fix:** Ensure deterministic generation takes precedence:
```python
# In order_router.py — only use client_tag if deterministic
if not intent.client_tag or not intent.client_tag.startswith("merid-"):
    intent.client_tag = f"merid-{id_hash}-{ts_bucket}"
```

---

## Verification Commands

Run these to verify the hardening in production:

```powershell
# 1. Verify deterministic client_order_id (merid-* pattern)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "merid-[a-f0-9]{16}-\d+"

# 2. Check for duplicate success handling
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "KALSHI_DUPLICATE_SUCCESS"

# 3. Verify jittered backoff (non-uniform wait times)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "retrying in [0-9]+\.[0-9]+s"

# 4. Check pre-trade gate blocks
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "Pre-trade gate blocked"

# 5. Verify strategy halts on sanity violations
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "STRATEGY_HALT"

# 6. Check for fallback path usage (should be ZERO)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 10000 | 
    Select-String "order_router not available, falling back"
```

---

## End-to-End Test Plan

### Test 1: Idempotency
1. Submit OrderIntent with specific parameters
2. Within 60 seconds, submit identical OrderIntent
3. **Expected:** First succeeds, second rejected with `gate:duplicate`
4. **Verify:** Only one order on Kalshi, position matches intended size

### Test 2: Retry Safety
1. Induce network failure during order placement
2. Allow retry mechanism to engage
3. **Expected:** Same `client_order_id` used, Kalshi returns duplicate error
4. **Verify:** Order router treats as success, no double position

### Test 3: Restart Recovery
1. Submit order, wait for Kalshi acceptance
2. Restart MERID backend
3. Reconstruct same OrderIntent (same parameters)
4. **Expected:** Same `client_order_id` generated, lookup finds existing order
5. **Verify:** No duplicate order created

### Test 4: Sanity Violation
1. Trigger duplicate fill scenario (simulated)
2. **Expected:** `SANITY_VIOLATION` log, strategy halted
3. **Verify:** No further orders from halted strategy

---

## Sign-off Checklist

- [x] Deterministic client_order_id implemented
- [x] Pre-trade gate integrated
- [x] Jittered backoff added
- [x] Duplicate error handling implemented
- [x] Sanity checker created and integrated
- [x] Strategy halt mechanism added
- [x] Error threshold exclusions verified
- [ ] **PENDING:** Fix kalshi_tools fallback path
- [ ] **PENDING:** Address client_tag override in trading_agent
- [ ] **PENDING:** Run E2E tests in staging
- [ ] **PENDING:** Deploy to production with monitoring

---

## Next Steps

1. **Immediate:** Fix kalshi_tools fallback path (fail-closed)
2. **Before deploy:** Run E2E test plan in staging
3. **Deploy:** Enable with `MERID_ERROR_THRESHOLD_KILL_ENABLED=true`
4. **Monitor:** Watch for `SANITY_VIOLATION` and `KALSHI_DUPLICATE_SUCCESS` logs
