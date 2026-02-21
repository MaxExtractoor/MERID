# Kalshi View Wiring Matrix

**Purpose:** Map each sidebar view to correct Kalshi-only endpoints and identify legacy noise to remove.

**Status Legend:**
- ✅ **CORRECT** - Already wired to Kalshi-only sources
- ⚠️ **PARTIAL** - Some endpoints correct, others need fixing
- ❌ **BROKEN** - Using legacy/non-Kalshi endpoints
- 🔧 **NEEDS_WIRE** - Not implemented or missing Kalshi integration

---

## Live Trading Group

### 1. Overview (`overview`)
**Component:** `Overview.tsx`  
**Status:** ✅ **CORRECT**

**Current Endpoints:**
```typescript
KALSHI_BALANCE       → /api/v1/kalshi/balance
KALSHI_PNL           → /api/v1/kalshi/pnl
KALSHI_POSITIONS     → /api/v1/kalshi/positions
KALSHI_ORDERS        → /api/v1/kalshi/orders
KALSHI_FILLS         → /api/v1/kalshi/fills
```

**Required Endpoints:**
```typescript
✅ /api/v1/kalshi/balance
✅ /api/v1/kalshi/pnl
✅ /api/v1/kalshi/positions
✅ /api/v1/kalshi/orders
✅ /api/v1/kalshi/fills
✅ /api/system/health (status cards)
✅ /api/v1/kalshi/health (Kalshi venue health)
```

**Action Required:** ✅ None - correctly wired

---

### 2. Terminal (`kalshi-terminal`)
**Component:** `KalshiTerminalView.tsx`  
**Status:** ✅ **CORRECT** (assumed)

**Required Endpoints:**
```typescript
✅ /api/v1/kalshi/markets
✅ /api/v1/kalshi/markets/{ticker}
✅ /api/v1/kalshi/markets/{ticker}/orderbook
✅ /api/v1/kalshi/orders (POST - place order)
✅ /api/v1/kalshi/balance
✅ /api/v1/kalshi/positions
```

**Action Required:** Verify order placement goes through venue_adapter (not direct Kalshi REST)

---

### 3. Markets (`kalshi-dashboard`)
**Component:** `KalshiDashboardView.tsx`  
**Status:** ✅ **CORRECT** (assumed)

**Required Endpoints:**
```typescript
✅ /api/v1/kalshi/markets
✅ /api/v1/kalshi/catalog
✅ /api/v1/kalshi/categories
✅ /api/v1/kalshi/favorites
✅ /api/v1/kalshi/volume-alerts
✅ /api/v1/kalshi/edge
```

**Action Required:** Verify no legacy prediction market endpoints

---

### 4. Agent Grid (`kalshi-grid`)
**Component:** `KalshiGridView.tsx`  
**Status:** ✅ **CORRECT**

**Current Endpoints:**
```typescript
KALSHI_GRID_STATUS   → /api/v1/kalshi-grid/status
KALSHI_GRID_AGENTS   → /api/v1/kalshi-grid/agents
KALSHI_GRID_FILLS    → /api/v1/kalshi-grid/fills
KALSHI_GRID_MATRIX   → /api/v1/kalshi-grid/matrix
```

**Required Endpoints:**
```typescript
✅ /api/v1/kalshi-grid/status
✅ /api/v1/kalshi-grid/agents
✅ /api/v1/kalshi-grid/agents/{name}
✅ /api/v1/kalshi-grid/fills
✅ /api/v1/kalshi-grid/matrix
✅ /api/v1/kalshi-grid/start (POST)
✅ /api/v1/kalshi-grid/stop (POST)
✅ /api/v1/prediction/consensus/summary (for consensus badges)
```

**Action Required:** ✅ None - correctly wired

---

### 5. Portfolio (`kalshi-portfolio`)
**Component:** `KalshiPortfolioView.tsx`  
**Status:** ✅ **CORRECT** (assumed)

**Required Endpoints:**
```typescript
✅ /api/v1/kalshi/positions
✅ /api/v1/kalshi/balance
✅ /api/v1/kalshi/pnl
✅ /api/v1/kalshi/pnl-history
✅ /api/v1/kalshi/risk
```

**Action Required:** Verify uses venue_registry with kalshi_only=True

---

### 6. Orders (`orders`)
**Component:** `Orders.tsx`  
**Status:** ❌ **BROKEN** - Using generic trading endpoint

**Current Endpoints:**
```typescript
❌ TRADING_ORDERS_OPEN → /api/v1/trading/orders/open
```

**Required Endpoints:**
```typescript
🔧 /api/v1/kalshi/orders (Kalshi-only orders)
🔧 /api/v1/positions?venue=kalshi (venue_registry filtered)
```

**Action Required:**  
1. Replace `TRADING_ORDERS_OPEN` with `KALSHI_ORDERS`
2. Filter by venue=kalshi or use kalshi_only=true parameter
3. Update component to handle Kalshi order format

**Code Fix:**
```typescript
// In Orders.tsx line 24-26
// OLD:
const { data: rawData } = useApiData<{ orders: RawOrder[] }>(
  API_ENDPOINTS.TRADING_ORDERS_OPEN,

// NEW:
const { data: rawData } = useApiData<{ orders: RawOrder[] }>(
  API_ENDPOINTS.KALSHI_ORDERS,
```

---

### 7. Vol & Sizing (`kalshi-vol-dashboard`)
**Component:** `KalshiVolDashboardView.tsx`  
**Status:** ✅ **CORRECT** (assumed)

**Required Endpoints:**
```typescript
✅ /api/v1/kalshi/volume-alerts
✅ /api/v1/kalshi/volume-anomalies
✅ /api/v1/kalshi/sizing-metrics
✅ /api/v1/kalshi/liquidity-alerts
```

**Action Required:** Verify sizing limits are enforced in order flow

---

## Risk & Limits Group

### 8. Kill Switch (`kill-switch`)
**Component:** `KillSwitchView.tsx`  
**Status:** ⚠️ **PARTIAL** - May control all venues, not just Kalshi

**Required Endpoints:**
```typescript
✅ /api/v1/kalshi/kill-switch (Kalshi-specific)
✅ /api/v1/kalshi/risk
✅ /api/v1/loop/guard/status (domain activation)
```

**Action Required:**  
1. Ensure kill switch only affects prediction domain/Kalshi venue in KALSHI_ONLY mode
2. Add backend guard: if `KALSHI_ONLY=true`, only allow prediction domain toggle
3. Update UI to show "Kalshi Kill Switch" not generic "Kill Switch"

---

### 9. Exposure & PnL (`exposure`)
**Component:** `ExposureView.tsx`  
**Status:** ❌ **BROKEN** - Aggregates all venues

**Current Endpoints:**
```typescript
❌ /api/v1/operator/summary (cross-venue)
❌ EQUITY_SERIES → /api/operator/equity-series (all venues)
```

**Required Endpoints:**
```typescript
🔧 /api/v1/kalshi/pnl
🔧 /api/v1/kalshi/pnl-history
🔧 /api/v1/positions?venue=kalshi&kalshi_only=true
🔧 /api/v1/risk/metrics?venue=kalshi
```

**Action Required:**  
1. Replace generic `/api/v1/operator/summary` with Kalshi-filtered version
2. Add `kalshi_only=true` parameter to all risk/exposure endpoints
3. Update `VenueExposureCard` to show only Kalshi
4. Update `DomainPnLChart` to filter prediction domain only

**Backend Fix Required:**
```python
# In venue_registry.py - ensure these methods respect kalshi_only
def get_all_positions(self, kalshi_only: bool = False):
    if kalshi_only or settings.KALSHI_ONLY:
        return self._kalshi_adapter.get_positions()
```

---

### 10. Risk & Health (`risk`)
**Component:** `Risk.tsx`  
**Status:** ⚠️ **PARTIAL** - Generic risk, needs Kalshi filtering

**Current Endpoints:**
```typescript
✅ RISK_METRICS → /api/v1/risk/metrics
✅ RISK_ALERTS → /api/v1/risk/alerts
⚠️ SYSTEM_HEALTH → /api/v1/system/health (all venues)
✅ RISK_POSITION_LIMITS → /api/v1/risk/position-limits
```

**Required Endpoints:**
```typescript
✅ /api/v1/risk/metrics?venue=kalshi
✅ /api/v1/risk/alerts?venue=kalshi
✅ /api/v1/kalshi/risk (Kalshi-specific)
✅ /api/v1/kalshi/health (venue health)
✅ /api/v1/reconciliation/status?venue=kalshi
```

**Action Required:**  
1. Add `venue=kalshi` filter to risk endpoints
2. Include reconciliation status from Kalshi reconciler
3. Show venue adapter health from `kalshi_venue_adapter`

---

### 11. Observability (`observability`)
**Component:** `ObservabilityView.tsx`  
**Status:** ✅ **CORRECT** - System-level, no filtering needed

**Current Endpoints:**
```typescript
✅ OBSERVABILITY_SUMMARY → /api/v1/system/observability
✅ OBSERVABILITY_ALERTS → /api/v1/system/alerts
✅ ORCHESTRATOR_SUMMARY → /api/v1/orchestrator/summary
```

**Required Endpoints:**
```typescript
✅ /api/v1/system/observability
✅ /api/v1/loop/guard/status
✅ /api/v1/kalshi-grid/status (agent grid health)
✅ /api/v1/reconciliation/status?venue=kalshi
```

**Action Required:**  
1. Add section for Kalshi-specific observability (WS bridge, agent grid)
2. Show prediction domain status from loop guard
3. Include reconciliation checks

---

## System Group

### 12. Orchestrator (`operator`)
**Component:** `OperatorDashboard.tsx`  
**Status:** ⚠️ **PARTIAL** - Shows all domains, needs Kalshi focus

**Current Endpoints:**
```typescript
⚠️ OPERATOR_SUMMARY → /api/v1/operator/summary (all domains)
❌ EQUITY_SERIES → /api/operator/equity-series (404 - not implemented)
❌ OPERATOR_RISK_UTILIZATION → /api/operator/risk-utilization (404)
```

**Required Endpoints:**
```typescript
✅ /api/v1/orchestrator/summary
✅ /api/v1/loop/guard/status
✅ /api/v1/kalshi-grid/status
🔧 /api/v1/domain/status?domain=prediction
✅ /api/v1/trade-mode
✅ /api/v1/paper-ladder/status
```

**Action Required:**  
1. Filter operator summary to show only prediction domain
2. Remove broken equity-series endpoint (404s)
3. Focus on Kalshi agent grid controls (start/stop/pause)
4. Show prediction domain activation status

---

### 13. Logs (`logs`)
**Component:** `Logs.tsx`  
**Status:** ✅ **CORRECT** - No filtering needed

**Current Endpoints:**
```typescript
✅ LOGS → /api/v1/logs
✅ LOGS_STATS → /api/v1/logs/stats
```

**Required Endpoints:**
```typescript
✅ /api/v1/logs
✅ /api/v1/logs/stats
✅ /api/v1/logs?filter=prediction (optional filter)
```

**Action Required:** Optional - add domain filter for prediction/Kalshi logs

---

## Summary of Required Fixes

### 🔴 Critical (Blocking)
1. **Orders view** - Replace `TRADING_ORDERS_OPEN` → `KALSHI_ORDERS`
2. **Exposure view** - Add `kalshi_only=true` to all endpoints
3. **Operator view** - Remove 404 endpoints, focus on prediction domain

### 🟡 Important (Non-blocking)
4. **Kill Switch** - Ensure only affects Kalshi in KALSHI_ONLY mode
5. **Risk view** - Add `venue=kalshi` filters
6. **Observability** - Add Kalshi-specific health checks

### 🟢 Nice to Have
7. **Logs** - Add prediction domain filter option
8. **All views** - Add KALSHI_ONLY enforcement in backend handlers

---

## Backend Enforcement Pattern

For all endpoints serving these views, add this pattern:

```python
from merid.settings import settings

@router.get("/api/v1/positions")
async def get_positions(venue: Optional[str] = None):
    kalshi_only = settings.KALSHI_ONLY or (venue == "kalshi")
    
    registry = get_venue_registry()
    positions = await registry.get_all_positions(kalshi_only=kalshi_only)
    
    return {"positions": positions}
```

---

## Next Steps

1. ✅ Document current state (this file)
2. 🔧 Fix Orders view endpoint
3. 🔧 Fix Exposure view filtering
4. 🔧 Remove 404 endpoints from Operator
5. 🔧 Add venue filters to Risk endpoints
6. 🔧 Add KALSHI_ONLY guards in backend
7. ✅ Test full Kalshi pipeline end-to-end
