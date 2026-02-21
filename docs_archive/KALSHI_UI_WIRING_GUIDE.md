# Kalshi UI Wiring Guide — Eliminate Mocks, Use Real APIs

**Date:** 2026-02-17  
**Purpose:** Systematically replace all mock/demo/fallback data in Kalshi UI with real backend APIs

---

## 🎯 **Truth Sources**

All Kalshi UI components must use these real data sources:

| Data Type | Backend Source | Endpoint |
|-----------|---------------|----------|
| **Positions** | `KalshiVenueAdapter` | `GET /api/v1/kalshi/positions` |
| **Orders** | `KalshiVenueAdapter` | `GET /api/v1/kalshi/orders` |
| **Fills** | `KalshiVenueAdapter` | `GET /api/v1/kalshi/fills` |
| **Balance** | `KalshiVenueAdapter` | `GET /api/v1/kalshi/balance` |
| **Risk** | Risk Manager | `GET /api/v1/kalshi/risk` |
| **Reconciliation** | `KalshiReconciler` | `GET /api/v1/kalshi/reconciliation` |
| **Edge Signals** | `SignalStore` | `GET /api/v1/kalshi/edge` or `/ui-summary` |
| **Liquidity Signals** | `SignalStore` | Via `/ui-summary` |
| **Volume Anomalies** | `SignalStore` | Via `/ui-summary` |
| **Risk Events** | `SignalStore` | Via `/ui-summary` |
| **Agent Grid** | `AgentGrid` | `GET /api/v1/kalshi-grid/status` |
| **Markets** | Market Catalog | `GET /api/v1/kalshi/markets` |
| **Orderbook** | Market Data | `GET /api/v1/kalshi/markets/{ticker}/orderbook` |

### **New Unified Endpoint** ✅

**`GET /api/v1/kalshi/ui-summary`**

Returns complete snapshot in one call:
```json
{
  "positions": [...],
  "orders": [...],
  "fills": [...],
  "balance": {...},
  "risk": {...},
  "reconciliation": {...},
  "signals": {
    "edge_top": [...],
    "liquidity": [...],
    "volume_anomalies": [...],
    "risk_events": [...]
  },
  "grid": {
    "status": "running",
    "agents": [...],
    "pnl": {...}
  },
  "mode": "paper",
  "timestamp": 1234567890.0
}
```

**Usage:** Call once on view mount for initial state, then poll individual endpoints for updates.

---

## 🔍 **Audit Findings**

### **Files with Mock/Demo Data**

Based on grep search for `demo|mock|MOCK|synthetic|fallback`:

**Test Files (Expected, OK):**
- `__tests__/KalshiDashboardView.test.tsx` - 22 mocks
- `__tests__/KalshiPortfolioView.test.tsx` - 25 mocks
- `__tests__/KalshiVolDashboardView.test.tsx` - 62 mocks
- `__tests__/KalshiInsightsPanel.test.tsx` - 20 mocks
- `__tests__/KalshiRiskFeed.test.tsx` - 19 mocks
- `__tests__/KalshiPnlChart.test.tsx` - 13 mocks
- `__tests__/KalshiSuite.smoke.test.tsx` - 11 mocks

**Production Components (NEEDS FIXING):**
- `KalshiModeBadge.tsx` - 2 references to demo
- `KalshiModeCompare.tsx` - 1 reference to demo
- `KalshiInsightsPanel.tsx` - 1 reference to mock

**Action Required:** Audit these 3 production components and remove demo references.

---

## 📝 **Component-by-Component Patches**

### **1. KalshiDashboardView.tsx**

**Current State:**
- Uses `useApiData(API_ENDPOINTS.KALSHI_MARKETS)` for markets ✅ (already real)
- Uses `useApiData(API_ENDPOINTS.KALSHI_EDGE)` for edge signals ✅ (already real)
- May have synthetic edge calculation from spread as fallback ⚠️

**Patch Required:**

```typescript
// BEFORE: Synthetic edge calculation
const syntheticEdge = (bid: number, ask: number) => {
  const mid = (bid + ask) / 2;
  // ... synthetic calculation ...
};

// AFTER: Use real edge from API, fallback clearly marked
const getEdgeSignal = (ticker: string) => {
  const signal = edgeData?.signals?.[ticker];
  if (signal) {
    return signal; // Real signal from backend
  }
  // Fallback: Clearly mark as heuristic
  return {
    edge_pct: 0,
    confidence: 0,
    sizing_tier: 'halted',
    // Add flag
    is_heuristic: true, // ← Mark as fallback
  };
};
```

**Verification:**
- [ ] All edge values come from `API_ENDPOINTS.KALSHI_EDGE` or `/ui-summary`
- [ ] Synthetic edge only used if API returns empty
- [ ] Synthetic edge labeled with `is_heuristic: true` flag

---

### **2. KalshiPortfolioView.tsx**

**Current State:**
- Uses `useApiData(API_ENDPOINTS.KALSHI_POSITIONS)` ✅
- Uses `useApiData(API_ENDPOINTS.KALSHI_ORDERS)` ✅
- Uses `useApiData(API_ENDPOINTS.KALSHI_FILLS)` ✅
- Uses `useApiData(API_ENDPOINTS.KALSHI_BALANCE)` ✅
- Uses `useApiData(API_ENDPOINTS.KALSHI_RISK)` ✅

**Patch Required:**

Check for any hardcoded defaults or demo arrays:

```typescript
// BEFORE: Hardcoded demo position
const positions = positionsData?.positions || [
  { ticker: 'BTC-DEMO', size: 10, avg_price: 0.55, unrealized_pnl: 50 }
];

// AFTER: Real data only, clear empty state
const positions = positionsData?.positions || [];

// In JSX, show empty state explicitly:
{positions.length === 0 ? (
  <div className="text-gray-500">No open positions</div>
) : (
  // ... render positions ...
)}
```

**Balance Card:**
```typescript
// BEFORE: Default balance
const balance = balanceData || { usd: 10000, locked: 0, available: 10000 };

// AFTER: Real balance or loading state
const balance = balanceData;

{!balance ? (
  <Skeleton className="h-20" />
) : (
  <div>
    <div className="text-2xl">${balance.usd.toFixed(2)}</div>
    <div className="text-sm text-gray-500">
      Locked: ${balance.locked.toFixed(2)}
    </div>
  </div>
)}
```

**Verification:**
- [ ] No hardcoded default positions/orders/fills
- [ ] Loading states show skeletons, not fake data
- [ ] Empty states clearly say "No data" instead of showing demo rows

---

### **3. KalshiTerminalView.tsx**

**Current State:**
- Uses real orderbook API ✅
- Uses real PnL history ✅
- May have demo activity log ⚠️

**Patch Required:**

```typescript
// BEFORE: Demo activity appended
const activityLog = [
  { type: 'demo', message: 'Example fill for testing' },
  ...realActivity
];

// AFTER: Real activity only
const activityLog = realActivity;

// In JSX
{activityLog.length === 0 ? (
  <div className="text-gray-500 text-center py-8">
    No recent activity
  </div>
) : (
  activityLog.map(item => /* render */)
)}
```

**PnL Strip:**
```typescript
// BEFORE: Synthetic PnL curve
const pnlData = pnlHistory || generateSyntheticCurve();

// AFTER: Real PnL or empty chart
const pnlData = pnlHistory;

{!pnlData || pnlData.length === 0 ? (
  <div className="text-gray-500">No PnL history yet</div>
) : (
  <KalshiPnlChart data={pnlData} />
)}
```

**Verification:**
- [ ] Orderbook uses `/api/v1/kalshi/markets/{ticker}/orderbook`
- [ ] Activity log uses real fills/orders, no demo events
- [ ] PnL chart shows empty state if no history

---

### **4. KalshiRiskFeed.tsx**

**Current State:**
- Uses `useKalshiRiskStream()` hook ✅
- May append example events in dev mode ⚠️

**Patch Required:**

```typescript
// BEFORE: Example events for development
const allEvents = [
  ...riskEvents,
  { type: 'demo', severity: 'info', message: 'Example event' }
];

// AFTER: Real events only
const allEvents = riskEvents;

// Remove any dev mode logic that adds fake events
```

**Event Severity Mapping:**
```typescript
// Ensure severity comes from backend, not remapped
const severityColor = (severity: string) => {
  // Use backend severity directly
  switch (severity) {
    case 'critical': return 'text-red-400';
    case 'warning': return 'text-yellow-400';
    case 'info': return 'text-blue-400';
    default: return 'text-gray-400';
  }
};
// DO NOT remap or guess severity client-side
```

**Verification:**
- [ ] All events come from `/kalshi/risk/events` or `/ws/risk`
- [ ] No example/demo events appended
- [ ] Severity colors use backend fields directly

---

### **5. KalshiPnlChart.tsx**

**Current State:**
- Receives data from parent ✅
- May generate synthetic curve if no data ⚠️

**Patch Required:**

```typescript
// BEFORE: Generate synthetic data
if (!data || data.length === 0) {
  data = generateSyntheticEquityCurve();
}

// AFTER: Show empty chart
if (!data || data.length === 0) {
  return (
    <div className="h-full flex items-center justify-center text-gray-500">
      No PnL data available
    </div>
  );
}
```

**Verification:**
- [ ] No synthetic curve generation
- [ ] Clear empty state when no data

---

### **6. KalshiOrderbookPanel.tsx**

**Current State:**
- Uses `useApiData(KALSHI_ORDERBOOK)` ✅
- May transform stale snapshot ⚠️

**Patch Required:**

```typescript
// BEFORE: Client-side orderbook transform
const transformedBook = clientSideAggregation(rawSnapshot);

// AFTER: Use backend orderbook directly
const orderbook = orderbookData;

// Let backend handle aggregation
```

**Verification:**
- [ ] Uses `/api/v1/kalshi/markets/{ticker}/orderbook`
- [ ] No client-side orderbook transforms
- [ ] Displays backend data as-is

---

### **7. KalshiActivityLog.tsx**

**Current State:**
- Uses fills + orders ✅
- May have stub arrays ⚠️

**Patch Required:**

```typescript
// BEFORE: Default stub activities
const activities = realActivities.length > 0 ? realActivities : STUB_ACTIVITIES;

// AFTER: Real activities only
const activities = realActivities;

{activities.length === 0 ? (
  <div className="text-gray-500 text-center py-4">
    No activity yet
  </div>
) : (
  activities.map(/* render */)
)}
```

**Verification:**
- [ ] No STUB_ACTIVITIES or MOCK_FILLS constants
- [ ] Clear empty state

---

### **8. KalshiModeBadge.tsx** ⚠️

**Found:** 2 demo references

**Action:** Read file and audit

```bash
# Check what the demo references are
grep -n "demo\|mock" web/react/src/components/KalshiModeBadge.tsx
```

**Expected Fix:** Likely checking if mode is "demo" vs "paper" vs "live". Ensure it reads from backend `/api/v1/kalshi/health` or `/ui-summary` mode field.

---

### **9. KalshiModeCompare.tsx** ⚠️

**Found:** 1 demo reference

**Action:** Read file and audit

**Expected Fix:** Similar to ModeBadge, ensure mode comes from backend.

---

### **10. KalshiInsightsPanel.tsx** ⚠️

**Found:** 1 mock reference

**Action:** Read file and audit

**Expected Fix:** Remove any MOCK_INSIGHTS constants, use real signals from `/ui-summary`.

---

## 🧪 **UI Tests to Add**

### **Test: No Demo Data Assertion**

Create `tests/ui-real-data.test.tsx`:

```typescript
import { render } from '@testing-library/react';
import KalshiDashboardView from '../views/KalshiDashboardView';
import KalshiPortfolioView from '../views/KalshiPortfolioView';
import KalshiTerminalView from '../views/KalshiTerminalView';

// Mock API with realistic data
jest.mock('../hooks/useApiData', () => ({
  useApiData: (endpoint: string) => {
    if (endpoint.includes('positions')) {
      return { data: [], loading: false, error: null };
    }
    // ... other endpoints
    return { data: null, loading: false, error: null };
  },
}));

describe('Kalshi UI - No Demo Data', () => {
  test('DashboardView does not render with mock markets', () => {
    const { container } = render(<KalshiDashboardView />);
    
    // Assert no MOCK_MARKETS constant is read
    expect(container.textContent).not.toContain('MOCK-');
    expect(container.textContent).not.toContain('DEMO-');
  });
  
  test('PortfolioView shows empty state, not demo positions', () => {
    const { getByText } = render(<KalshiPortfolioView />);
    
    // Should show "No open positions", not render fake rows
    expect(getByText(/no open positions/i)).toBeInTheDocument();
  });
  
  test('TerminalView does not use synthetic PnL curve', () => {
    const { container } = render(<KalshiTerminalView ticker="BTC-TEST" />);
    
    // Should show "No PnL data", not a generated curve
    expect(container.textContent).toMatch(/no pnl|no data/i);
  });
});
```

### **Test: API Integration**

```typescript
describe('Kalshi UI - Real API Integration', () => {
  test('PortfolioView calls correct position API', async () => {
    const mockFetch = jest.spyOn(global, 'fetch');
    render(<KalshiPortfolioView />);
    
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/kalshi/positions'),
        expect.any(Object)
      );
    });
  });
  
  test('DashboardView uses ui-summary for initial load', async () => {
    const mockFetch = jest.spyOn(global, 'fetch');
    render(<KalshiDashboardView />);
    
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/kalshi/ui-summary'),
        expect.any(Object)
      );
    });
  });
});
```

---

## 📋 **Checklist**

### **Backend** ✅
- [x] `/api/v1/kalshi/ui-summary` endpoint created
- [x] Returns positions, orders, fills, balance from venue adapter
- [x] Returns risk summary
- [x] Returns reconciliation status
- [x] Returns signals from signal store
- [x] Returns agent grid status

### **Frontend Audit** 🔄
- [ ] KalshiDashboardView.tsx - Remove synthetic edge fallback
- [ ] KalshiPortfolioView.tsx - Remove hardcoded defaults
- [ ] KalshiTerminalView.tsx - Remove demo activity
- [ ] KalshiRiskFeed.tsx - Remove example events
- [ ] KalshiPnlChart.tsx - Remove synthetic curve
- [ ] KalshiOrderbookPanel.tsx - Use backend orderbook only
- [ ] KalshiActivityLog.tsx - Remove stub arrays
- [ ] KalshiModeBadge.tsx - Audit demo references
- [ ] KalshiModeCompare.tsx - Audit demo references
- [ ] KalshiInsightsPanel.tsx - Audit mock references

### **Testing**
- [ ] Add `ui-real-data.test.tsx` with no-demo assertions
- [ ] Add API integration tests
- [ ] Update existing tests to use realistic mock data

### **Documentation**
- [ ] Update API documentation with `/ui-summary` endpoint
- [ ] Add migration guide for UI developers

---

## 🚀 **Migration Steps**

### **Phase 1: Add Unified Endpoint** ✅
- [x] Create `web/api/kalshi_ui.py` with `/ui-summary` endpoint
- [x] Wire to venue adapter, reconciler, signal store, agent grid

### **Phase 2: Audit Components** (Current)
- [ ] Read KalshiModeBadge.tsx
- [ ] Read KalshiModeCompare.tsx
- [ ] Read KalshiInsightsPanel.tsx
- [ ] Document specific fixes needed

### **Phase 3: Patch Components**
- [ ] Apply fixes to each component
- [ ] Replace demo/mock data with API calls
- [ ] Add loading/empty states

### **Phase 4: Add Tests**
- [ ] Create no-demo assertions
- [ ] Add API integration tests
- [ ] Run full test suite

### **Phase 5: Verify**
- [ ] Start MERID backend + loop
- [ ] Open Kalshi UI
- [ ] Verify all data is real (no mock tickers, no demo positions)
- [ ] Check network tab: only real API calls

---

## 🎯 **Success Criteria**

UI wiring is complete when:

1. **No mock constants** - `grep -r "MOCK_\|DEMO_\|STUB_" web/react/src/ | grep -v __tests__` returns 0 results
2. **All API calls real** - Network tab shows only `/api/v1/kalshi/*` endpoints
3. **Empty states visible** - Components show "No data" instead of fake rows
4. **Tests pass** - No-demo assertions pass
5. **OpenClaw integration works** - Can query MERID and get real data

---

## 📝 **Next Actions**

**Immediate:**
1. Audit the 3 production components with demo/mock references
2. Provide specific patches
3. Test `/ui-summary` endpoint

**Then:**
4. Apply patches to all components
5. Add UI tests
6. Verify end-to-end

**Would you like me to:**
- Read the 3 components (ModeBadge, ModeCompare, InsightsPanel) and provide specific patches?
- Create the UI test file with no-demo assertions?
- Test the `/ui-summary` endpoint?
