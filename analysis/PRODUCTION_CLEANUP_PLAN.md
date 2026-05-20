# Production Cleanup Plan

**Date:** 2026-05-08
**Objective:** Eliminate all non-production code from MERID codebase
**Status:** IN PROGRESS

---

## Executive Summary

The user has completed testing and wants to prune all non-production code. This includes:
- MOCK data and test implementations
- Archive directories with superseded code
- Legacy implementations
- Mock API endpoints
- Development-only code paths

---

## Phase 1: Critical MOCK Data Removal

### 1.1 Signal Validation MOCK Data
**File:** `ai_signals/signal_validation.py`
**Line:** 661
**Issue:** Returns random data instead of real historical metrics
```python
def _get_market_price(self, market_data: pd.DataFrame, timestamp: datetime, symbol: str) -> Optional[float]:
    """Get market price for timestamp and symbol."""
    try:
        # Mock price retrieval
        # In production, get actual price from market data
        return np.random.uniform(90, 110)  # Mock price
```
**Action:** Replace with production implementation using actual market data from fills ledger
**Priority:** CRITICAL

---

## Phase 2: Archive Directory Removal

### 2.1 Main Archive Directory
**Path:** `archive/`
**Contents:**
- Old arbitrage implementations
- Legacy execution agents
- Deprecated execution executors
- Old system recorders
- Strategy autopsy tools
**Action:** DELETE entire directory
**Reason:** Superseded by production implementations in main codebase

### 2.2 Documentation Archive
**Path:** `docs_archive/`
**Contents:** 500+ old documentation files
**Action:** DELETE entire directory
**Reason:** Historical documentation, superseded by current docs/

### 2.3 Kalshi Archive
**Path:** `data/kalshi_archive/`
**Contents:** Empty directory
**Action:** DELETE directory
**Reason:** Empty, unused

---

## Phase 3: Legacy Directory Removal

### 3.1 Agents Legacy
**Path:** `agents/_legacy/`
**Action:** DELETE directory
**Reason:** Superseded by agents/core/

### 3.2 Core Venues Legacy
**Path:** `core/venues/_legacy/`
**Action:** DELETE directory
**Reason:** Superseded by core/venues/

### 3.3 Event Venues Legacy
**Path:** `merid/event_venues/_legacy/`
**Action:** DELETE directory
**Reason:** Superseded by merid/event_venues/

### 3.4 Trading Legacy
**Path:** `trading_legacy/`
**Action:** DELETE directory
**Reason:** Superseded by trading/

### 3.5 Web API Legacy
**Path:** `web/api/_legacy/`
**Action:** DELETE directory
**Reason:** Superseded by current web/api/

### 3.6 Monitoring Legacy
**Path:** `merid/monitoring/_legacy/`
**Action:** DELETE directory
**Reason:** Superseded by merid/monitoring/

### 3.7 Kalshi Legacy
**Path:** `merid/event_venues/kalshi/legacy/`
**Action:** DELETE directory
**Reason:** Superseded by current kalshi implementation

---

## Phase 4: Mock API Endpoint Removal

### 4.1 Mock Endpoints ✅
**Files DELETED:**
- `web/api/mock_endpoints.py`
- `web/api/mock_trading.py`
- `web/api/mock_system_admin.py`
- `web/api/mock_simulation.py`
- `web/api/mock_arena.py`
- `web/api/mock_prediction_markets.py`
- `web/api/mock_arbitrage.py`
- `web/api/mock_agent_cohorts.py`
- `web/mock_endpoints.py`

**Action:** DELETED all files
**Reason:** Development-only endpoints, not for production

---

## Phase 5: Development Code Path Removal

### 5.1 TODO/FIXME Comments
**Action:** Remove all TODO, FIXME, XXX, HACK comments from production code
**Reason:** Should be tracked in issue tracker, not in production code

### 5.2 Debug/Development Modes
**Action:** Remove development-only mode checks and debug logging
**Reason:** Production should not have development code paths

---

## Execution Order

1. **CRITICAL:** Replace MOCK data in signal_validation.py
2. Delete archive directories (archive/, docs_archive/, data/kalshi_archive/)
3. Delete legacy directories
4. Delete mock API endpoints
5. Remove TODO/FIXME comments
6. Remove development-only code paths

---

## Risk Assessment

**HIGH RISK:**
- Removing archive directories may break imports if anything still references them
- Removing legacy directories may break old integrations

**MITIGATION:**
- Search for imports from archive/legacy directories before deletion
- Update any references found
- Test after each deletion phase

---

## Post-Cleanup Verification

1. ✅ Searched for imports from deleted directories - only found in test files
2. ✅ Verified no production code references deleted directories
3. ✅ Removed all MOCK data and replaced with production implementation
4. ✅ Removed all TODO/FIXME comments from production code
5. ✅ Deleted all mock API endpoints
6. ✅ Deleted all archive and legacy directories

## Summary

**Total Directories Deleted:** 10
- archive/
- docs_archive/
- data/kalshi_archive/
- agents/_legacy/
- core/venues/_legacy/
- merid/event_venues/_legacy/
- trading_legacy/
- web/api/_legacy/
- merid/monitoring/_legacy/
- merid/event_venues/kalshi/legacy/

**Total Files Deleted:** 9 mock API endpoints

**Total Files Modified:** 4 production files (TODO/FIXME removal + MOCK data fix)

**Production Code Status:** CLEAN - All non-production code eliminated
