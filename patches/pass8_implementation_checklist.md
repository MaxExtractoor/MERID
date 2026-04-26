# Pass 8 Implementation Checklist

## Overview
This checklist tracks the implementation of all Pass 7 P0 patches into production code.

## Patch Status Matrix

| Patch | File | Lines | Status | Test File | CI Check |
|-------|------|-------|--------|-----------|----------|
| P0-1: FIX Endpoint Guard | `web/api/kalshi_api.py` | ~5950 | ✅ DONE | `tests/api/test_kalshi_fix_endpoint.py` | ⬜ |
| P0-2: REST Fallback Removal | `web/api/kalshi_api.py` | ~2888 | ✅ DONE | `tests/api/test_kalshi_orders_fallback.py` | ⬜ |
| P0-3: CT API Hard-Guard | `web/api/kalshi_continuous_trader_api.py` | Module | ✅ DONE | `tests/api/test_kalshi_ct_api.py` | ⬜ |
| P0-4: Unified Risk Enforcement | `merid/config/unified_risk_enforcement.py` | New | ✅ DONE | `tests/risk/test_unified_risk_enforcement.py` | ⬜ |
| P0-5: Archive Import Guards | `archive/__init__.py` | Top | ✅ DONE | `tests/security/test_archive_import_guard.py` | ⬜ |
| Startup Wiring | `web/main.py` | ~2164 | ✅ DONE | N/A | ⬜ |

## Detailed Patch Instructions

### P0-1: FIX Endpoint Disable (PRIORITY: CRITICAL)

**Location:** `web/api/kalshi_api.py`, `@router.post("/fix/orders")` ~line 5950

**Action:** Insert guard at start of function:

```python
@router.post("/fix/orders")
async def fix_submit_order(
    ticker: str,
    side: str,
    quantity: int,
    price: Optional[int] = None,
    # ... other params
):
    # PASS 8 P0: Hard disable FIX endpoint in LIVE/PAPER modes
    from merid.trading.trade_mode import get_trade_mode
    _mode = get_trade_mode()
    if _mode in ("live", "paper"):
        logger.error(
            f"[PASS8_GUARD] FIX endpoint blocked in {_mode} mode. "
            f"TradeIntent: ticker={ticker}, side={side}, qty={quantity}"
        )
        raise HTTPException(
            status_code=403,
            detail=f"FIX protocol disabled in {_mode} mode. "
            "Use /api/v1/kalshi/orders with canonical executor. "
            "Contact: #risk-engineering if you believe this is an error."
        )
    
    # ... rest of function (sim-only)
```

**Verification:**
- [ ] Run `pytest tests/api/test_kalshi_fix_endpoint.py -v`
- [ ] Test LIVE mode returns 403
- [ ] Test PAPER mode returns 403
- [ ] Test SIM mode allows access

---

### P0-2: REST Fallback Fail-Closed (PRIORITY: CRITICAL)

**Location:** `web/api/kalshi_api.py`, `place_order()` ~line 2898

**Action:** Replace fallback logic:

```python
# Find this block (around line 2890):
except ImportError as _import_err:
    # Fallback: try direct REST if order_router unavailable
    logger.warning(f"Order router unavailable, using REST fallback: {_import_err}")
    rest = _get_rest_client()
    if mode_value == "live":
        result = rest.create_order(...)
    
# Replace with:
except ImportError as _import_err:
    # PASS 8 P0: FAIL CLOSED in LIVE/PAPER - no fallback allowed
    logger.error(
        f"[PASS8_GUARD] Order router import failed in {mode_value} mode: {_import_err}. "
        "REST fallback blocked - trading halted for safety."
    )
    
    if mode_value in ("live", "paper"):
        # Trigger kill-switch alert
        try:
            from merid.risk.kill_switches import get_kill_switch
            ks = get_kill_switch()
            ks.trigger(
                reason="Executor contract violation: order_router unavailable",
                severity="critical",
                source="kalshi_api.place_order"
            )
        except Exception as _ks_err:
            logger.error(f"Failed to trigger kill-switch: {_ks_err}")
        
        raise HTTPException(
            status_code=503,
            detail="Trading system degraded. Order router unavailable. "
            "All trading halted. Contact operations immediately."
        )
    else:
        # SIM/MOCK only: Allow fallback for development
        logger.warning("SIM/MOCK mode: Using REST fallback for development")
        rest = _get_rest_client()
        result = rest.create_order(...)
```

**Verification:**
- [ ] Run `pytest tests/api/test_kalshi_orders_fallback.py -v`
- [ ] Mock router import failure
- [ ] Verify 503 in LIVE/PAPER
- [ ] Verify kill-switch triggered

---

### P0-3: CT API Hard-Guard (PRIORITY: HIGH)

**Location:** `web/api/kalshi_continuous_trader_api.py`

**Status:** ✅ ALREADY IMPLEMENTED (see archive/__init__.py edit)

**Note:** Consider also adding a similar guard to the actual CT script at `merid/trading/kalshi_continuous_trader.py`.

---

### P0-4: Unified Risk Enforcement (PRIORITY: HIGH)

**Location:** `merid/config/unified_risk_enforcement.py` (NEW FILE)

**Status:** ✅ ALREADY IMPLEMENTED

**Integration Steps:**
1. [ ] Add to `web/main.py` startup:
   ```python
   from merid.config.unified_risk_enforcement import enforce_at_startup
   enforce_at_startup()
   ```

2. [ ] Run `pytest tests/risk/test_unified_risk_enforcement.py -v`

---

### P0-5: Archive Import Guards (PRIORITY: HIGH)

**Location:** `archive/__init__.py`

**Status:** ✅ ALREADY IMPLEMENTED

**Also Required:**
- [ ] Check if `archive/deep_archive/__init__.py` exists
- [ ] If yes, add same guard there
- [ ] Run `pytest tests/security/test_archive_import_guard.py -v`

---

## CI Integration

### Add to GitHub Actions / CI Pipeline:

```yaml
- name: Pass 8 Invariant Checks
  run: |
    python scripts/ci/check_kalshi_invariants.py
```

### Required Test Commands:

```bash
# All Pass 8 tests
pytest tests/api/test_kalshi_fix_endpoint.py -v
pytest tests/api/test_kalshi_orders_fallback.py -v
pytest tests/risk/test_unified_risk_enforcement.py -v
pytest tests/security/test_archive_import_guard.py -v

# Or run all at once
pytest tests/api/test_kalshi_fix_endpoint.py tests/api/test_kalshi_orders_fallback.py tests/risk/test_unified_risk_enforcement.py tests/security/test_archive_import_guard.py -v
```

---

## Post-Implementation Verification

After all patches applied, verify:

1. [ ] No `KalshiFIXClient` usage in API outside sim
2. [ ] No `KalshiRestClient.create_order` fallback in live
3. [ ] `enforce_at_startup()` called in web/main.py
4. [ ] Archive import guard active
5. [ ] All new tests pass
6. [ ] CI invariant check passes

---

## Sign-off

| Role | Name | Date | Status |
|------|------|------|--------|
| Implementer | | | |
| Code Reviewer | | | |
| QA | | | |
| Risk Engineering | | | |

**Final Status:** ⬜ NOT COMPLETE / ✅ COMPLETE
