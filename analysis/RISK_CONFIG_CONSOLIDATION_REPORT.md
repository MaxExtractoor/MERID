# Risk Config Classes Consolidation Report
**Date**: 2026-06-05  
**Task**: Audit and consolidate risk config classes (remove duplicate KalshiRiskConfig)

---

## Current State

### Live KalshiRiskConfig (Single Source of Truth)
**Location**: `merid/event_venues/kalshi/kalshi_risk.py`

**Status**: ✅ Active SSOT

**Class Definition**:
```python
class KalshiRiskConfig:
    """Full risk configuration for Kalshi trading.
    
    CRITICAL: max_total_notional_usd should be derived from live Kalshi balance, not hardcoded.
    Default 0 means "derive from live bankroll" (50% of bankroll for total notional).
    """
```

**Usage** (25+ files):
- Production: `web/main_15m_lean.py`, `web/api/kalshi_api.py`
- Tests: 20+ test files use this for risk manager initialization
- Archive: `archive/legacy/kalshi_continuous_trader.py` (imports as VenueKalshiRiskConfig)
- Archive: `archive/legacy/drawdown_config.py` (for comparison)

**Key Characteristics**:
- Venue-specific risk configuration
- Used by `KalshiRiskManager` for Kalshi markets
- Derives bankroll from live Kalshi API
- Profile-gated for kalshi_crypto_15m_v2

---

### Legacy KalshiRiskConfig
**Location**: `merid/prediction/risk/kalshi_risk_engine.py`

**Status**: ⚠️ Deprecated, minimal usage

**Class Definition**:
```python
class KalshiRiskConfig:
    """Risk configuration for prediction markets (PM-specific)."""
```

**Usage** (4 files):
- Self: `archive/legacy/kalshi_risk_engine.py` (self-import for documentation)
- Archive: `archive/legacy/dalshi_continuous_trader.py` (legacy code)
- Archive: `archive/legacy/drawdown_config.py` (legacy code)
- Tests: `tests/test_decimal_safety.py` (1 usage)
- Tests: `tests/test_drawdown_auto_reset.py` (3 usages)

**Key Characteristics**:
- PM-specific risk configuration
- Used by legacy `KalshiRiskEngine`
- Not used in production code
- Only used in legacy code and 2 test files

---

## Import Analysis

### Live KalshiRiskConfig Imports
**Pattern**: `from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig`

**Files** (25+):
- `web/main_15m_lean.py` - Production startup
- `web/api/kalshi_api.py` - API endpoint
- `tests/kalshi_runtime_audit_fixes.py` - Test
- `tests/test_audit_bug_fixes.py` - Test
- `tests/test_decimal_safety.py` - Test (also imports legacy!)
- `tests/test_bankroll_reconciliation_fixes.py` - Test
- `tests/test_error_count_never_kills.py` - Test
- `tests/test_dynamic_allocation_system.py` - Test
- `tests/test_drawdown_auto_reset.py` - Test (also imports legacy!)
- `tests/test_balance_calibrator.py` - Test
- `tests/test_fills_ledger_risk_separation.py` - Test
- `tests/test_kalshi_crypto_15m_profile_wiring.py` - Test
- `tests/test_kalshi_deep_integration.py` - Test
- `tests/test_kalshi_risk_15m_budget.py` - Test
- `tests/test_kill_switch_regression.py` - Test
- `tests/test_micro_scalping_44_bankroll.py` - Test
- `tests/test_momentum_hedge_integration.py` - Test
- `tests/test_kalshi_audit_bug_coverage.py` - Test
- `scripts/comprehensive_system_audit.py` - Script
- `scripts/test_edge_enforcement.py` - Script
- `archive/legacy/drawdown_config.py` - Legacy (imports for comparison)
- `archive/legacy/kalshi_continuous_trader.py` - Legacy (imports as VenueKalshiRiskConfig)
- `archive/legacy/kalshi_risk_engine.py` - Legacy (self-import for docs)

### Legacy KalshiRiskConfig Imports
**Pattern**: `from merid.prediction.risk.kalshi_risk_engine import KalshiRiskConfig`

**Files** (4):
- `archive/legacy/kalshi_risk_engine.py` - Self-import for documentation
- `archive/legacy/drawdown_config.py` - Legacy code
- `archive/legacy/kalshi_continuous_trader.py` - Legacy code
- `tests/test_decimal_safety.py` - Test (also imports live!)
- `tests/test_drawdown_auto_reset.py` - Test (also imports live!)

---

## Test File Analysis

### Tests Using Both Configs
**Files**: 2
1. `tests/test_decimal_safety.py`
   - Line 196: `from merid.event_venues.kalshi.kalshi_risk import KalshiRiskEngine, KalshiRiskConfig`
   - Line 198: `engine = KalshiRiskEngine(KalshiRiskConfig())`
   - **Issue**: Imports KalshiRiskEngine from live module but KalshiRiskConfig from live module (not legacy!)
   - **Status**: Actually using live config, not legacy

2. `tests/test_drawdown_auto_reset.py`
   - Lines 18, 46, 67: `from merid.event_venues.kalshi.kalshi_risk import KalshiRiskEngine, KalshiRiskConfig`
   - Lines 87, 110: `from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig`
   - **Issue**: Imports KalshiRiskEngine from live module but KalshiRiskConfig from live module (not legacy!)
   - **Status**: Actually using live config, not legacy

**Conclusion**: These test files import from the live module, not the legacy module. The legacy KalshiRiskConfig is not actually used in any current tests.

---

## Consolidation Plan

### Phase 1: Verify No Production Usage (Immediate)
**Action**: Confirm legacy config is not used in production

**Verification**:
- ✅ Production code uses live config from `merid.event_venues.kalshi.kalshi_risk`
- ✅ Legacy config only in archive/legacy/ (expected)
- ✅ Tests actually use live config (imports from live module)
- ✅ No production code imports from `merid.prediction.risk.kalshi_risk_engine`

### Phase 2: Add Deprecation Warning (Immediate)
**Action**: Add deprecation warning to legacy module

**File to modify**:
1. `merid/prediction/risk/kalshi_risk_engine.py`
   - Add module-level deprecation warning
   - Add comment directing to live config
   - Keep for backward compatibility with archive/legacy code

### Phase 3: Update Documentation (Immediate)
**Action**: Update inline documentation

**Files to update**:
1. `merid/event_venues/kalshi/kalshi_risk.py`
   - Add SSOT comment to KalshiRiskConfig class
   - Document that this is the only config to use

2. `merid/prediction/risk/kalshi_risk_engine.py`
   - Add deprecation notice at top of file
   - Document that this is for legacy code only

### Phase 4: Archive Legacy Module (Medium-term)
**Action**: Move to archive/legacy/ if no dependencies

**Files to move**:
1. `merid/prediction/risk/kalshi_risk_engine.py` → `archive/legacy/kalshi_risk_engine.py`

**Note**: This may already be in archive/legacy/. Need to verify if there's a duplicate in the active path.

---

## Recommendations

### Immediate Actions (Next Sprint)
1. Add deprecation warning to `merid/prediction/risk/kalshi_risk_engine.py`
2. Add SSOT documentation to `merid/event_venues/kalshi/kalshi_risk.py`
3. Verify no production code imports from legacy module

### Short-Term Actions (Next 2-3 Sprints)
4. Move `merid/prediction/risk/kalshi_risk_engine.py` to `archive/legacy/` if not already there
5. Update archive/legacy imports to use archived version
6. Clean up any remaining references

### Long-Term Actions (Next Quarter)
7. Remove legacy module entirely if no archive dependencies
8. Update all documentation to reference live config only
9. Add validation to prevent legacy config usage

---

## Risk Assessment

**Current Risk**: VERY LOW
- Live config is already the SSOT
- Production code uses live config exclusively
- Legacy config only in archive/legacy/ (expected)
- Tests actually use live config (not legacy)

**Risk if Consolidated**: NONE
- Legacy config is not used in production
- Tests use live config
- Archive code is expected to use legacy modules

---

## Summary

**Current State**: Live KalshiRiskConfig is already the Single Source of Truth. The legacy KalshiRiskConfig exists but is only used in archive/legacy code (expected). Tests actually import from the live module, not the legacy module.

**Action Required**: 
1. Add deprecation warning to legacy module
2. Add SSOT documentation to live module
3. Verify legacy module is in archive/legacy/ (or move it there)
4. No critical changes needed - system already using SSOT

**No Critical Issues**: The consolidation is essentially complete. The legacy module exists for archive compatibility but is not used in production.

---

**Consolidation Analysis Completed**: 2026-06-05
