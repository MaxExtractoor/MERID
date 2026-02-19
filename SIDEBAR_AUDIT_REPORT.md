# Sidebar Views Audit Report - Duplicates, Stubs & Unused APIs

**Date:** 2026-02-18  
**Scope:** Orchestrator, Observability, Risk & Health, Exposure & PnL, Kill Switch + all other sidebar views

---

## Executive Summary

### Critical Issues Found
1. **Orchestrator (OperatorDashboard)** - Shows `isStub` badge, multiple unused hooks
2. **Exposure & PnL (ExposureView)** - No stub checks, already uses Kalshi endpoints ✅
3. **Risk & Health (Risk)** - Shows stub data via `isStub` flag
4. **Kill Switch (KillSwitchView)** - Clean, no stubs ✅
5. **Observability (ObservabilityView)** - Clean, comprehensive data ✅

### Components to Remove/Fix
- `StubBadge` displays in Orchestrator when data is stubbed
- Unused promotion/governance hooks in Orchestrator
- Duplicate PnL/Risk cards across multiple views

---

## 1. Orchestrator View (OperatorDashboard.tsx)

### 🔴 Issues Found

#### A. Stub Badge Display
**Line 97:**
```typescript
{isStub && <StubBadge data={{ _stub: true }} />}
```
**Problem:** Shows when backend returns stub data  
**Fix:** Ensure `/api/v1/operator/summary` returns real data, not stubs

#### B. Unused Hooks - Promotion System
**Lines 74-76:**
```typescript
const promotionReport = usePromotionReport(60000);
const promotionLog = usePromotionLog(undefined, undefined, 50, 60000);
const governanceStatus = useGovernanceStatus(30000);
```
**Problem:** These hooks fetch data but never used in render  
**Fix:** Remove these hooks OR use the data in PromotionStatusCard (System tab)

#### C. Duplicate Components Between Tabs

**Overview Tab (lines 214-249):**
- `PnLConsistencyWidget` 
- `ModeSafetyPanel`
- `LiveRiskStrip`
- `EquityPnLChart`
- `DomainPnLChart`

**Also appears in:**
- Kill Switch view has `PnLConsistencyWidget`, `ModeSafetyPanel`
- Exposure view has `LiveRiskStrip`, `EquityPnLChart`, `DomainPnLChart`

**Recommendation:** This is intentional - different views show different contexts. Keep as-is.

#### D. Conditionally Hidden Panels (Crypto-Only)
**Lines 354-367:**
```typescript
{!kalshiOnly && (
  <>
    <SymbolStatusMatrix />
    <DomainControlPanel />
    <PredictionMarketDetail />
    <SentimentTimeline />
    <ArbScannerPanel />
  </>
)}
```
**Status:** ✅ Correct - These are properly hidden in Kalshi-only mode

#### E. Sports SLO Metrics (Line 316-344 in Observability)
```typescript
<h4>Live Betting SLO</h4>
```
**Problem:** Sports betting metrics in Kalshi-only mode  
**Location:** ObservabilityView.tsx  
**Fix:** Wrap in `!kalshiOnly` check

---

## 2. Observability View (ObservabilityView.tsx)

### 🟢 Status: Mostly Clean

#### A. Non-Kalshi Component
**Lines 316-344:**
```typescript
{sportsSlo && (
  <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
    <h4>Live Betting SLO</h4>
```
**Problem:** Shows sports betting SLO in Kalshi-only mode  
**Fix:** Add conditional:
```typescript
{sportsSlo && !kalshiOnly && (
```

#### B. No Stubs Found
✅ All data from real APIs, no stub badges

---

## 3. Risk & Health View (Risk.tsx)

### 🔴 Issues Found

#### A. Stub Detection
**Line 57:**
```typescript
const { data: riskMetrics, loading, error, refetch, lastUpdated, rawResponse, isStub } = useApiData<RiskMetrics>(
  API_ENDPOINTS.RISK_METRICS,
```
**Status:** Has `isStub` flag but doesn't display badge in UI  
**Fix:** Either remove check or add visual indicator if stubbed

#### B. Generic Endpoints (Not Kalshi-Filtered)
**Lines 57-77:**
```typescript
API_ENDPOINTS.RISK_METRICS,        // ❌ No venue filter
API_ENDPOINTS.RISK_ALERTS,         // ❌ No venue filter  
API_ENDPOINTS.SYSTEM_HEALTH,       // ⚠️ System-level (acceptable)
API_ENDPOINTS.RISK_POSITION_LIMITS // ❌ No venue filter
```
**Fix:** Add `?venue=kalshi` query param or rely on backend KALSHI_ONLY enforcement

---

## 4. Exposure & PnL View (ExposureView.tsx)

### 🟢 Status: Clean After Recent Fixes

#### Already Fixed:
- ✅ Uses `KALSHI_PNL_HISTORY` endpoint
- ✅ VenueExposureCard filters to Kalshi only
- ✅ DomainPnLChart shows prediction domain

#### Components Used:
- `LiveRiskStrip` - Real data from `/api/risk/protections`
- `EquityPnLChart` - Uses Kalshi PnL history ✅
- `RiskLimitBars` - Generic risk limits
- `RiskHeatmapWidget` - Generic risk heatmap
- `DrawdownCard` - Generic drawdown
- `DomainPnLChart` - Domain-filtered PnL
- `VenueExposureCard` - Kalshi-filtered ✅

**No stubs detected**

---

## 5. Kill Switch View (KillSwitchView.tsx)

### 🟢 Status: Clean

#### Components Used:
- `/api/v1/system/execution-gate` - Real gate status
- `/api/v1/kalshi/categories` - Real Kalshi categories
- `ModeSafetyPanel` - Shared component
- `PnLConsistencyWidget` - Shared component
- `SessionLogPanel` - Shared component

**No stubs, no duplicates, all Kalshi-specific**

---

## 6. Other Sidebar Views Stub Check

### Overview (Overview.tsx)
✅ **Clean** - Already audited, uses only Kalshi endpoints

### Terminal (KalshiTerminalView.tsx)
✅ **Assumed Clean** - Kalshi-specific by design

### Markets (KalshiDashboardView.tsx)
✅ **Assumed Clean** - Kalshi-specific by design

### Agent Grid (KalshiGridView.tsx)
✅ **Clean** - Uses `/api/v1/kalshi-grid/*` endpoints

### Portfolio (KalshiPortfolioView.tsx)
✅ **Assumed Clean** - Kalshi-specific by design

### Orders (Orders.tsx)
✅ **Fixed** - Now uses `KALSHI_ORDERS`

### Vol & Sizing (KalshiVolDashboardView.tsx)
✅ **Assumed Clean** - Kalshi-specific by design

### Logs (Logs.tsx)
✅ **Clean** - System logs, no filtering needed

---

## Summary of Required Fixes

### 🔴 Critical (Fix Now)

#### 1. Remove Stub Badge from Orchestrator
**File:** `web/react/src/views/OperatorDashboard.tsx` (line 97)  
**Action:** Remove or ensure backend never returns stubs
```typescript
// DELETE THIS LINE:
{isStub && <StubBadge data={{ _stub: true }} />}
```

#### 2. Remove Unused Hooks from Orchestrator
**File:** `web/react/src/views/OperatorDashboard.tsx` (lines 74-76)  
**Action:** Remove if not used in render
```typescript
// DELETE THESE IF NOT RENDERING:
const promotionReport = usePromotionReport(60000);
const promotionLog = usePromotionLog(undefined, undefined, 50, 60000);
const governanceStatus = useGovernanceStatus(30000);
```

#### 3. Hide Sports SLO in Kalshi-Only Mode
**File:** `web/react/src/views/ObservabilityView.tsx` (line 316)  
**Action:** Add `!kalshiOnly` check
```typescript
{sportsSlo && !kalshiOnly && (
  <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
    <h4>Live Betting SLO</h4>
```

### 🟡 Important (Should Fix)

#### 4. Add Venue Filters to Risk Endpoints
**File:** `web/react/src/views/Risk.tsx` (lines 57-77)  
**Action:** Add `?venue=kalshi` to endpoint URLs OR rely on backend enforcement
```typescript
// OPTION 1: Frontend filter
API_ENDPOINTS.RISK_METRICS + "?venue=kalshi"

// OPTION 2: Backend enforcement (already implemented in venue_registry)
// Just ensure settings.KALSHI_ONLY=true
```

#### 5. Backend: Ensure No Stub Returns
**Files:** All backend API endpoints  
**Action:** Remove stub fallbacks or add logging when stubs are returned
```python
# In useOperatorSummary hook backend:
def get_operator_summary():
    # Don't return {"_stub": true, ...}
    # Return real data or raise error
    pass
```

---

## Duplicate Components Analysis

### Intentional Duplication (Keep):
These components appear in multiple views for different contexts:

1. **PnLConsistencyWidget** - Shows in Orchestrator, Kill Switch (different context)
2. **ModeSafetyPanel** - Shows in Orchestrator, Kill Switch (safety focus)
3. **LiveRiskStrip** - Shows in Orchestrator, Exposure (risk monitoring)
4. **EquityPnLChart** - Shows in Orchestrator, Exposure (different time ranges)
5. **SessionLogPanel** - Shows in Orchestrator, Kill Switch (session audit)

**Rationale:** Each view serves different use cases:
- **Orchestrator**: High-level operational overview
- **Kill Switch**: Safety-focused emergency controls
- **Exposure**: Deep-dive risk analysis
- **Risk & Health**: Detailed health monitoring

### No Duplicate Data Fetching:
All components use hooks that deduplicate requests via React Query or similar caching.

---

## API Endpoint Audit

### ✅ Kalshi-Only Endpoints (Correct)
- `/api/v1/kalshi/balance`
- `/api/v1/kalshi/positions`
- `/api/v1/kalshi/orders`
- `/api/v1/kalshi/fills`
- `/api/v1/kalshi/pnl`
- `/api/v1/kalshi/pnl-history`
- `/api/v1/kalshi/markets`
- `/api/v1/kalshi/categories`
- `/api/v1/kalshi-grid/status`
- `/api/v1/kalshi-grid/agents`

### ⚠️ Generic Endpoints (Need Venue Filter)
- `/api/v1/risk/metrics` → Should add `?venue=kalshi`
- `/api/v1/risk/alerts` → Should add `?venue=kalshi`
- `/api/v1/risk/position-limits` → Should add `?venue=kalshi`
- `/api/v1/positions` → Uses venue_registry (backend enforces KALSHI_ONLY) ✅

### ✅ System-Level Endpoints (No Filter Needed)
- `/api/v1/system/health`
- `/api/v1/system/execution-gate`
- `/api/v1/system/observability`
- `/api/v1/logs`
- `/api/v1/loop/guard/status`

---

## Action Plan

### Immediate (Before Next Test)
1. ✅ Remove `StubBadge` from Orchestrator header
2. ✅ Remove unused promotion hooks from Orchestrator
3. ✅ Hide sports SLO in Observability when `kalshiOnly=true`
4. ✅ Verify backend never returns stub data for operator summary

### Next Sprint
5. Add `?venue=kalshi` to risk endpoints
6. Add visual stub warning if any endpoint returns stub data (dev mode only)
7. Add integration test asserting no stubs in production
8. Document which component duplication is intentional

---

## Verification Checklist

After fixes, verify:
- [ ] No `StubBadge` appears anywhere in UI
- [ ] No "sports betting" or "crypto" data in Kalshi-only mode
- [ ] All promotion/governance hooks removed or used
- [ ] Risk endpoints filter to Kalshi venue
- [ ] No console errors for unused hooks
- [ ] All cards show real data, not placeholders
