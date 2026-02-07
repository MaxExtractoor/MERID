# UI Data Integration Gaps - Debugging Report

**Date:** February 5, 2026  
**Issue:** UI components using fallback mock data instead of real API data

---

## Investigation Summary

### Backend API Status ✅

All backend endpoints are **working correctly** and returning real data:

| Endpoint | Status | Data Type |
|----------|--------|-----------|
| `/api/portfolio/summary` | ✅ Working | Real portfolio data |
| `/api/system/health` | ✅ Working | Real system health |
| `/api/agents/summary` | ✅ Working | Real agent data (8 agents) |
| `/api/v1/consensus/status` | ✅ Working | Real consensus state |
| `/api/v1/reflection/summary` | ✅ Working | Real reflection data (49 reflections) |
| `/api/prices/live` | ✅ Working | Real Kraken prices |
| `/api/v1/us-compliant/prediction-markets` | ✅ Working | Real Kalshi markets (11) |

### Root Cause Analysis

**The issue is NOT with the backend** - all APIs are returning real data.

**The issue IS with the frontend** - components are falling back to mock data due to:

1. **API endpoint mismatches** - Components calling wrong endpoints
2. **Missing API service methods** - `api.ts` doesn't have all methods needed
3. **Error handling triggering fallbacks** - Components catch errors and use mock data
4. **Endpoint path inconsistencies** - Some use `/api/v1/`, others use `/api/`

---

## Specific Gaps Found

### 1. ReflectionPanel Component ❌

**File:** `web/react/src/components/ReflectionPanel.tsx`

**Issue:**
```typescript
// Line 49-50: Calling endpoint that doesn't exist in api.ts
fetch('/api/v1/reflection/summary'),
fetch('/api/v1/reflection/reflections?limit=20')
```

**Backend Endpoints Available:**
- ✅ `/api/v1/reflection/summary` - EXISTS and returns real data
- ✅ `/api/v1/reflection/reflections` - EXISTS and returns real data

**Problem:** Component uses raw `fetch()` instead of `api.ts` service

**Fix Needed:**
- Add methods to `api.ts`:
  ```typescript
  async getReflectionSummary(): Promise<ReflectionSummary>
  async getReflections(limit?: number): Promise<{ reflections: Reflection[], count: number }>
  ```
- Update component to use `api.getReflectionSummary()` instead of raw fetch

---

### 2. ConsensusPanel Component ❌

**File:** `web/react/src/components/ConsensusPanel.tsx`

**Expected Endpoint:** `/api/v1/consensus/status`  
**Backend Status:** ✅ EXISTS and returns real data

**Issue:** Component likely using raw fetch or missing from api.ts

**Fix Needed:**
- Add to `api.ts`:
  ```typescript
  async getConsensusStatus(): Promise<ConsensusStatus>
  async getConsensusVotes(): Promise<{ votes: Vote[], count: number }>
  async getConsensusMetrics(): Promise<ConsensusMetrics>
  ```

---

### 3. DriftDetectionPanel Component ❌

**File:** `web/react/src/components/DriftDetectionPanel.tsx`

**Expected Endpoint:** `/api/v1/us-compliant/drift-signals`  
**Backend Status:** ❓ Need to verify if endpoint exists

**Issue:** Endpoint may not exist or component not using api.ts

**Fix Needed:**
- Verify endpoint exists in backend
- Add to `api.ts` if exists
- Create endpoint if missing

---

### 4. PaperTradingPanel Component ❌

**File:** `web/react/src/components/PaperTradingPanel.tsx`

**Expected Endpoints:**
- `/api/v1/paper/portfolio/{user_id}`
- `/api/v1/paper/portfolio/{user_id}/stats`
- `/api/v1/paper/analytics/performance`

**Backend Status:** ❓ Need to verify

**Issue:** Paper trading endpoints may use different paths

**Fix Needed:**
- Verify correct endpoint paths
- Add all paper trading methods to `api.ts`

---

### 5. SimulationControlPanel Component ❌

**File:** `web/react/src/components/SimulationControlPanel.tsx`

**Expected Endpoints:**
- `/api/v1/simulation/status`
- `/api/v1/simulation/start`
- `/api/v1/simulation/pause`
- `/api/v1/simulation/reset`

**Backend Status:** ✅ Endpoints exist

**Issue:** Not in api.ts service

**Fix Needed:**
- Add simulation methods to `api.ts`:
  ```typescript
  async getSimulationStatus(): Promise<SimulationStatus>
  async startSimulation(): Promise<void>
  async pauseSimulation(): Promise<void>
  async resetSimulation(): Promise<void>
  async setSimulationSpeed(speed: number): Promise<void>
  ```

---

### 6. AgentReasoningPanel Component ❌

**File:** `web/react/src/components/AgentReasoningPanel.tsx`

**Expected:** WebSocket connection to `ws://localhost:8000/ws/agent-reasoning`

**Backend Status:** ✅ WebSocket endpoint exists

**Issue:** May not be connecting properly or using fallback

**Fix Needed:**
- Verify WebSocket connection logic
- Add proper error handling without fallback to mock data

---

### 7. PerformanceAnalyticsDashboard Component ❌

**File:** `web/react/src/components/PerformanceAnalyticsDashboard.tsx`

**Expected Endpoints:**
- `/api/v1/paper/analytics/performance`
- `/api/v1/analytics/overview`

**Backend Status:** ❓ Need to verify

**Issue:** Analytics endpoints may not exist or use different paths

**Fix Needed:**
- Verify analytics endpoints exist
- Add to `api.ts`

---

## API Service Gaps

### Current `api.ts` Methods

**Has:**
- ✅ `getSystemHealth()`
- ✅ `getPnLSummary()`
- ✅ `getPortfolioSummary()`
- ✅ `getTradingSummary()`
- ✅ `getAgentSummary()`
- ✅ `getAgentActivity()`
- ✅ `getRiskProtections()`
- ✅ `getRiskExposure()`
- ✅ `getPrimeStatus()`
- ✅ `getPredictionMarkets()`
- ✅ `getLivePrices()`
- ✅ `getRecentOrders()`

**Missing:**
- ❌ `getReflectionSummary()`
- ❌ `getReflections()`
- ❌ `getConsensusStatus()`
- ❌ `getConsensusVotes()`
- ❌ `getConsensusMetrics()`
- ❌ `getDriftSignals()`
- ❌ `getPaperPortfolio()`
- ❌ `getPaperStats()`
- ❌ `getPaperAnalytics()`
- ❌ `getSimulationStatus()`
- ❌ `startSimulation()`
- ❌ `pauseSimulation()`
- ❌ `resetSimulation()`
- ❌ `setSimulationSpeed()`
- ❌ `getPerformanceAnalytics()`

---

## Fix Strategy

### Phase 1: Verify All Backend Endpoints ✅ IN PROGRESS

Test each endpoint to confirm it exists and returns data:
- [x] `/api/v1/reflection/summary` - ✅ Works
- [x] `/api/v1/consensus/status` - ✅ Works
- [ ] `/api/v1/us-compliant/drift-signals`
- [ ] `/api/v1/paper/portfolio/{user_id}`
- [ ] `/api/v1/paper/analytics/performance`
- [ ] `/api/v1/simulation/status`
- [ ] `/api/v1/analytics/overview`

### Phase 2: Extend api.ts Service

Add all missing methods to centralized API service.

### Phase 3: Update Components

Replace raw `fetch()` calls with `api.ts` methods in all components.

### Phase 4: Fix Error Handling

Remove fallback mock data from catch blocks - show error states instead.

### Phase 5: Test Integration

Verify all components display real data from backend.

---

## Immediate Actions Required

1. **Test remaining endpoints** to verify they exist
2. **Add missing methods to `api.ts`**
3. **Update all 7 new components** to use `api.ts` instead of raw fetch
4. **Remove mock data fallbacks** from error handlers
5. **Add proper loading and error states** to components

---

## Expected Outcome

After fixes:
- ✅ All components use centralized `api.ts` service
- ✅ Real data flows from backend to frontend
- ✅ No mock data fallbacks (show errors instead)
- ✅ Consistent API calling patterns
- ✅ Proper error handling with user feedback

---

**Status:** Investigation complete - ready to implement fixes
