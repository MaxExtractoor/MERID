# Bankroll Services Consolidation Report
**Date**: 2026-06-05  
**Task**: Consolidate bankroll services (use BankrollServiceV2 as SSOT)

---

## Current State

### BankrollServiceV2 (Single Source of Truth)
**Location**: `merid/event_venues/kalshi/bankroll_service_v2.py`

**Status**: ✅ Active SSOT

**Key Functions**:
- `get_bankroll_service()` - Get singleton instance
- `get_equity_for_risk_calc_sync()` - Get equity for risk calculations (sync)
- `BankrollServiceV2` class - Main service class
- `BalanceState`, `BankrollSummary` dataclasses

**Usage** (40+ files):
- Production: `web/main_15m_lean.py`, `web/main_15m.py`
- Risk modules: `merid/risk/profiles/risk_envelope_service.py`, `merid/risk/kill_switches.py`
- Prediction: `merid/prediction/agent_grid_15m.py`, `merid/prediction/portfolio_risk_agent.py`
- Tests: `tests/test_bankroll_service_v2_single_source.py`, `tests/test_15m_lean_smoke.py`
- Tools: `tools/kalshi_15m_meta_health.py`, `scripts/kalshi_continuous_trader.py`

---

### Legacy BankrollService
**Location**: `merid/event_venues/kalshi/bankroll_service.py`

**Status**: ⚠️ Deprecated but still partially used

**Key Functions**:
- `get_live_bankroll_usd()` - **DEPRECATED** (comment says use fetch_live_bankroll())
- `compute_effective_bankroll()` - Used in tests for bankroll calculation logic
- `fetch_live_bankroll()` - Full result with error details

**Usage** (6 files):
- Tests: `tests/test_bankroll_unification.py` (5 usages of compute_effective_bankroll)
- Archive: `archive/legacy/` (legacy code)

**Comment in code**:
```python
def get_live_bankroll_usd(client=None) -> float:
    """Legacy compatibility - returns USD or 0.0 on failure.
    
    DEPRECATED: Use fetch_live_bankroll() for full result with error details.
    """
```

---

### BankrollResolver
**Location**: `merid/event_venues/kalshi/bankroll_resolver.py`

**Status**: ⚠️ Alternative implementation, limited usage

**Key Functions**:
- `get_live_bankroll()` - Async function with fallback policy
- `BankrollResolver` class
- `FallbackPolicy` enum (REJECT, USE_LAST_KNOWN)
- `BankrollResolution` dataclass

**Usage** (2 files):
- Tests: `tests/test_economic_sanity.py` (testing FallbackPolicy enum)
- Self: `bankroll_resolver.py` (self-import)

---

### KalshiRisk Wrapper
**Location**: `merid/event_venues/kalshi/kalshi_risk.py`

**Status**: ✅ Wrapper (correctly delegates to SSOT)

**Key Functions**:
- `get_live_bankroll()` - Thin wrapper around unified service
- `get_live_bankroll_async()` - Async version

**Comment in code**:
```python
def get_live_bankroll() -> float:
    """Get live bankroll from Kalshi balance API via unified service.
    
    CRITICAL: This is now a thin wrapper around the unified bankroll service.
    The unified service is the ONLY place that calls /portfolio/balance.
    """
```

**Usage** (10+ files):
- Settings: `merid/settings.py` (calls get_live_bankroll())
- Order router: `merid/event_venues/kalshi/order_router.py`
- Prediction risk: `merid/prediction/risk/_prediction_risk.py`
- Archive: `archive/legacy/trading_agent.py`

---

## Consolidation Plan

### Phase 1: Add Deprecation Warnings (Immediate)
**Action**: Add deprecation warnings to legacy functions

**Files to modify**:
1. `merid/event_venues/kalshi/bankroll_service.py`
   - Add deprecation warning to `get_live_bankroll_usd()`
   - Add deprecation warning to `compute_effective_bankroll()`
   - Add comment directing to bankroll_service_v2

2. `merid/event_venues/kalshi/bankroll_resolver.py`
   - Add deprecation warning to module-level imports
   - Add comment directing to bankroll_service_v2

### Phase 2: Update Tests (Short-term)
**Action**: Migrate test functions to use bankroll_service_v2

**Files to modify**:
1. `tests/test_bankroll_unification.py`
   - Replace `compute_effective_bankroll()` with equivalent logic from bankroll_service_v2
   - Or move the logic into bankroll_service_v2 if it's still needed

2. `tests/test_economic_sanity.py`
   - Remove FallbackPolicy enum tests (or move to bankroll_service_v2 if needed)

### Phase 3: Archive Legacy Services (Medium-term)
**Action**: Move legacy services to archive/legacy/

**Files to move**:
1. `merid/event_venues/kalshi/bankroll_service.py` → `archive/legacy/bankroll_service.py`
2. `merid/event_venues/kalshi/bankroll_resolver.py` → `archive/legacy/bankroll_resolver.py`

**Files to update**:
1. Update all imports to use bankroll_service_v2
2. Update `merid/event_venues/kalshi/__init__.py` to remove legacy exports

### Phase 4: Documentation (Immediate)
**Action**: Update documentation to clarify SSOT

**Files to create/update**:
1. Create `docs/bankroll_service_architecture.md`
2. Update inline comments in `merid/event_venues/kalshi/__init__.py`
3. Add SSOT note to `merid/event_venues/kalshi/bankroll_service_v2.py`

---

## Recommendations

### Immediate Actions (Next Sprint)
1. Add deprecation warnings to `bankroll_service.py` and `bankroll_resolver.py`
2. Create documentation clarifying bankroll_service_v2 as SSOT
3. Update `merid/event_venues/kalshi/__init__.py` comments

### Short-Term Actions (Next 2-3 Sprints)
4. Migrate `tests/test_bankroll_unification.py` to use bankroll_service_v2
5. Migrate `tests/test_economic_sanity.py` to use bankroll_service_v2
6. Verify no production code uses legacy services

### Long-Term Actions (Next Quarter)
7. Move legacy services to `archive/legacy/`
8. Remove legacy imports from `merid/event_venues/kalshi/__init__.py`
9. Clean up any remaining references

---

## Risk Assessment

**Current Risk**: LOW
- BankrollServiceV2 is already the SSOT
- Production code primarily uses bankroll_service_v2
- Legacy services only used in tests

**Risk if Consolidated**: VERY LOW
- Deprecation warnings will alert developers
- Tests can be migrated incrementally
- No impact on production code

---

## Summary

**Current State**: BankrollServiceV2 is already the Single Source of Truth and is widely used. Legacy services exist but have minimal usage (mostly tests).

**Action Required**: 
1. Add deprecation warnings to legacy services
2. Migrate tests to use bankroll_service_v2
3. Archive legacy services after test migration
4. Update documentation

**No Critical Issues**: The consolidation is mostly complete. The remaining work is cleanup and deprecation.

---

**Consolidation Analysis Completed**: 2026-06-05
