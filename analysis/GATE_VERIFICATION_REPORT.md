# Gate Verification Report
**Date**: 2026-06-05  
**Task**: Verify and document disabled gates (TOP3_BATCH_GATE, CRYPTO15M_GATE)

---

## Findings

### MERID_DISABLE_TOP3_BATCH_GATE

**Status**: ✅ Intentionally disabled for lean stack

**Location**: `.env` line 367
```bash
MERID_DISABLE_TOP3_BATCH_GATE=true
```

**Implementation**: `merid/event_venues/kalshi/order_router.py` lines 4535-4537
```python
if os.getenv("MERID_DISABLE_TOP3_BATCH_GATE", "").lower() in ("1", "true", "yes"):
    logger.debug("[TOP3-GATE] Skipped (disabled by MERID_DISABLE_TOP3_BATCH_GATE) for %s", intent.ticker)
    return None
```

**Module Status**: 
- **EXISTS**: `merid/trading/top3_edge_allocator.py` - Full implementation with `Top3EdgeAllocator` class
- **EXISTS**: `merid/trading/top3_batch_manager.py` - Batch lifecycle management
- **TESTS**: Comprehensive test suite in `tests/top3/`

**Reason for Disable**: Comment in .env states "module missing: merid.trading.top3_edge_allocator" - this is **incorrect**. The module exists.

**Recommendation**: 
- **RE-ENABLE** the gate for production to use top-3 edge selection
- Remove the incorrect comment from .env
- The gate provides cross-asset edge selection and allocation, which is valuable for risk management

---

### MERID_DISABLE_CRYPTO15M_GATE

**Status**: ✅ Intentionally disabled for lean stack

**Location**: `.env` line 369
```bash
MERID_DISABLE_CRYPTO15M_GATE=true
```

**Implementation**: `merid/event_venues/kalshi/order_gate.py` lines 656-664
```python
# risk envelope instead. Set MERID_DISABLE_CRYPTO15M_GATE=1 to disable.
# Skip check if env disables it (emergency override for lean stack)
if os.getenv("MERID_DISABLE_CRYPTO15M_GATE", "").lower() in ("1", "true", "yes"):
    logger.debug("[CRYPTO15M-GATE] Skipped (disabled by MERID_DISABLE_CRYPTO15M_GATE) for %s", contract_id)
else:
    try:
        from merid.prediction.crypto15mallocator import (
            is_15m_crypto_ticker,
            check_timeframe_budget,
```

**Module Status**:
- **EXISTS**: `merid/prediction/crypto15mallocator.py` - Full implementation
- **ARCHIVE**: `archive/legacy/crypto15mallocator.py` - Legacy version
- **TESTS**: Test suite in `tests/test_crypto15m_allocator.py`

**Reason for Disable**: Comment in .env states "module missing: merid.prediction.crypto15mallocator" - this is **incorrect**. The module exists.

**Functionality**: 
- Checks if ticker is 15m crypto
- Validates timeframe budget
- Enforces per-asset exposure limits

**Recommendation**:
- **RE-ENABLE** the gate for production to use 15m crypto-specific risk checks
- Remove the incorrect comment from .env
- The gate provides 15m crypto-specific risk envelope validation

---

## Summary

Both gates are **intentionally disabled** but the comments in .env are **incorrect** - the modules do exist and are fully implemented.

**Action Required**:
1. Re-enable both gates by setting env vars to `false`
2. Update .env comments to reflect correct status
3. Test gate functionality after re-enabling
4. Monitor for any issues with gate logic

**Risk Assessment**: 
- **Current Risk**: MEDIUM - Gates disabled means less granular risk control
- **Risk if Re-enabled**: LOW - Gates have comprehensive test coverage

---

**Verification Completed**: 2026-06-05
