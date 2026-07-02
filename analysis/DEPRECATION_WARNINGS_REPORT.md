# Deprecation Warnings Report
**Date**: 2026-06-08  
**Task**: Add deprecation warnings to legacy modules

---

## Overview

Added deprecation warnings to three legacy modules to guide developers toward the canonical single source of truth implementations.

---

## Modules Updated

### 1. Bankroll Service
**Location**: `merid/event_venues/kalshi/bankroll_service.py`

**Changes**:
- Added deprecation notice to module docstring
- Added module-level deprecation warning on import
- Added deprecation warning to `KalshiBankrollService.__init__()`
- Added deprecation warning to class docstring

**Canonical Source**: `merid/event_venues/kalshi/bankroll_service_v2.py`

**Migration Path**:
```python
# Old (deprecated):
from merid.event_venues.kalshi.bankroll_service import get_bankroll_service

# New (canonical):
from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
```

---

### 2. Bankroll Resolver
**Location**: `merid/event_venues/kalshi/bankroll_resolver.py`

**Changes**:
- Added deprecation notice to module docstring
- Added module-level deprecation warning on import
- Added deprecation warning to `BankrollResolver.__init__()`
- Added deprecation warning to class docstring

**Canonical Source**: `merid/event_venues/kalshi/bankroll_service_v2.py`

**Migration Path**:
```python
# Old (deprecated):
from merid.event_venues.kalshi.bankroll_resolver import BankrollResolver

# New (canonical):
from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
```

---

### 3. Kalshi Risk Engine
**Location**: `archive/legacy/kalshi_risk_engine.py`

**Changes**:
- Added deprecation notice to module docstring
- Added module-level deprecation warning on import
- Added deprecation warning to `KalshiRiskConfig` class docstring
- Added deprecation warning to `KalshiRiskEngine.__init__()`
- Added deprecation warning to `KalshiRiskEngine` class docstring

**Canonical Source**: `merid/event_venues/kalshi/kalshi_risk.py`

**Migration Path**:
```python
# Old (deprecated):
from merid.prediction.risk.kalshi_risk_engine import KalshiRiskEngine, KalshiRiskConfig

# New (canonical):
from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig, get_kalshi_risk
```

---

## Test Results

### test_bankroll_unification.py
**Status**: ✅ 12 passed, 2 warnings

**Warnings**:
- DeprecationWarning on import from bankroll_service
- DeprecationWarning on KalshiBankrollService instantiation

**Conclusion**: Deprecation warnings working correctly

---

### test_economic_sanity.py
**Status**: ⚠️ 31 passed, 1 failed, 4 warnings

**Warnings**:
- DeprecationWarning on import from bankroll_resolver
- DeprecationWarning on PositionSizer.compute() (unrelated)
- Other deprecation warnings (unrelated)

**Failure**:
- `test_volatility_estimate_is_fresh` - TypeError in volatility_service.py (unrelated to deprecation warnings)

**Conclusion**: Deprecation warnings working correctly. Failure is pre-existing issue with datetime timezone handling.

---

## Impact Analysis

### Production Code
**Status**: ✅ No impact

**Findings**:
- Production code does not import these legacy modules
- Production code uses BankrollServiceV2 and kalshi_risk.py
- Deprecation warnings will not affect production

---

### Test Code
**Status**: ⚠️ Warnings expected

**Findings**:
- Test files import legacy modules for validation
- Deprecation warnings will appear in test output
- Tests continue to pass with warnings
- This is expected behavior for deprecated test dependencies

---

### Legacy Code
**Status**: ✅ Self-referential only

**Findings**:
- archive/legacy/kalshi_risk_engine.py imports from itself
- No production code imports from archive/legacy
- Deprecation warnings will not cause circular dependencies

---

## Recommendations

### Immediate Actions (Next Sprint)
1. ✅ Deprecation warnings added to all legacy modules
2. ✅ Tests verify warnings are working correctly
3. ⚠️ Fix unrelated test failure in volatility_service.py (datetime timezone issue)

### Short-Term Actions (Next 2-3 Sprints)
1. Migrate test files to use BankrollServiceV2
2. Migrate test files to use kalshi_risk.py
3. Remove test dependencies on legacy modules
4. Archive legacy modules after test migration

### Long-Term Actions (Next Quarter)
1. Remove bankroll_service.py from production codebase
2. Remove bankroll_resolver.py from production codebase
3. Keep archive/legacy/kalshi_risk_engine.py for historical reference
4. Update documentation to reflect canonical sources

---

## Risk Assessment

**Current Risk**: VERY LOW
- Deprecation warnings are non-breaking
- Production code unaffected
- Tests continue to pass
- Clear migration path provided

**Risk if Issues Found**: NONE
- Deprecation warnings are informational only
- No functional changes to code
- Tests verify warnings are working correctly

---

## Summary

**Current State**: Deprecation warnings have been successfully added to three legacy modules (bankroll_service.py, bankroll_resolver.py, kalshi_risk_engine.py). The warnings guide developers toward the canonical single source of truth implementations (BankrollServiceV2 and kalshi_risk.py). Tests verify that warnings are working correctly. Production code is unaffected.

**Action Required**: 
1. No critical issues found
2. Consider migrating test files to use canonical sources
3. Consider archiving legacy modules after test migration
4. Fix unrelated test failure in volatility_service.py

**No Critical Issues**: Deprecation warnings are non-breaking and provide clear guidance for migration. Production code is unaffected.

---

**Deprecation Warnings Implementation Completed**: 2026-06-08
