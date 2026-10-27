# Kalshi UI Simplification Project - Progress Summary

**Date:** 2026-05-12  
**Status:** Phases 0-6 Complete (7-8 Pending)

---

## Overview

This project implements a state-and-UX simplification for the Kalshi integration following the architectural principles:
- Build around backend state (canonical data model)
- Cut the UI down (inventory, classify, remove redundancy)
- Use progressive disclosure (summary → detail drawer → troubleshooting)
- Make sync reliable (single sync strategy)
- Refactor in phases

---

## Completed Phases

### Phase 0: Inventory and Classification ✅

**Deliverables:**
- `docs/KALSHI_UI_INVENTORY.md` - Comprehensive inventory of 30+ components, 8 views, 100+ API endpoints

**Key Findings:**
- 10 essential components (KalshiModeBadge, ExecutionGateStrip, KalshiBankrollPanel, etc.)
- 12 useful-later components (analytics, historical data)
- 5 duplicated components (mode badges, execution gate strips, balance displays)
- 3 dead/stale components (paper vs shadow comparison, credentials card, publish pipeline)

### Phase 1: Canonical Backend State Model ✅

**Deliverables:**
- `docs/KALSHI_CANONICAL_STATE_MODEL.md` - Detailed state model design
- `web/api/kalshi_ui_state_api.py` - Backend aggregation endpoint (`/api/v1/kalshi/ui-state`)
- `web/react/src/types/kalshiUIState.ts` - TypeScript interfaces
- `web/react/src/config/constants.ts` - Added KALSHI_UI_STATE endpoints
- `web/react/src/hooks/useKalshiUIState.ts` - React hook with WebSocket skeleton
- `web/main.py` - Wired kalshi_ui_state_api_router

**State Model Structure:**
```typescript
interface KalshiUIState {
  system: SystemStatus;      // mode, execution gate, kill switch, venue health
  capital: CapitalState;     // balance, PnL, drawdown, limits
  markets: MarketState;      // positions, orders, fills, active tickers
  risk: RiskState;           // limits, breaches, alerts
  grid: GridState;           // running status, agents, cycles, errors
}
```

**Backend Implementation:**
- `_fetch_system_status()` - Aggregates from grid mode, execution gate, kill switch, venue health, reconciliation
- `_fetch_capital_state()` - Aggregates from bankroll service, risk data
- `_fetch_market_state()` - Aggregates from positions, orders, fills (filters test tickers)
- `_fetch_risk_state()` - Aggregates from risk data, alerts
- `_fetch_grid_state()` - Aggregates from agent grid status, metrics, error log

### Phase 2: Compact Overview Panel ✅

**Deliverable:**
- `web/react/src/components/KalshiCompactOverview.tsx`

**Features:**
- 5 compact cards: System Status, Capital, Market Activity, Risk, Grid
- Uses canonical state via `useKalshiUIState` hook
- 10-second polling interval
- Loading skeletons and error handling
- Refresh button with timestamp display

**Card Highlights:**
- System Status: Execution gate, kill switch, venue health, reconciliation
- Capital: Total value, daily PnL, drawdown tier, notional utilization
- Market Activity: Position/order counts, recent fills
- Risk: Daily loss, breaches, recent alerts with unacknowledged count
- Grid: Running status, active agents, cycles, fill rate, errors

### Phase 3: Live Activity Stream ✅

**Deliverable:**
- `web/react/src/components/KalshiActivityStream.tsx`

**Features:**
- Aggregates events from canonical state (fills, orders, alerts, errors)
- Filterable by event type (all, fills, orders, alerts, errors, system)
- Event counts in filter dropdown
- Color-coded icons (green for profit, red for loss, amber for warnings)
- Timestamp display with formatters
- Empty state handling

**Event Types:**
- Fills: Trade executions with PnL
- Orders: Order status changes
- Alerts: Risk limit breaches
- Errors: Agent errors
- System: Kill switch, execution gate changes

### Phase 4: Detail Drawer ✅

**Deliverable:**
- `web/react/src/components/KalshiDetailDrawer.tsx`

**Features:**
- Slide-in drawer from right (responsive)
- Progressive disclosure for market, order, trade, agent details
- Lazy-loaded detail data via `useKalshiDetail` hook
- Backdrop with close button
- Smooth animations

**Detail Views:**
- Market Detail: Pricing, market stats, orderbook, recent trades
- Order Detail: (placeholder - TODO)
- Trade Detail: (placeholder - TODO)
- Agent Detail: Performance metrics, calibration data, recent trades

### Phase 5: Troubleshooting View ✅

**Deliverable:**
- `web/react/src/components/KalshiTroubleshootingView.tsx`

**Features:**
- Tab-based interface (Logs, Failures, Reconciliation)
- Search and filter functionality
- Color-coded log levels (info, warning, error)
- Reconciliation status with discrepancy counts
- Refresh controls

**Tabs:**
- Logs: Searchable, filterable log entries with source and timestamp
- Failures: Risk events with resolved/unresolved toggle
- Reconciliation: Status display, discrepancy list with amounts

### Phase 6: Minimal Action Area ✅

**Deliverable:**
- `web/react/src/components/KalshiActionArea.tsx`

**Features:**
- Primary controls only (grid start/stop, kill switch, mode toggle)
- Confirmation modals for destructive actions
- Loading states during API calls
- Disabled states when actions not available
- Status messages (kill switch reason)

**Controls:**
- Grid Start/Stop: Toggles agent grid running state
- Kill Switch: Activates/deactivates global kill switch
- Mode Toggle: Switches between paper and live modes

---

## Pending Phases

### Phase 7: Reliable WebSocket Sync ⏳

**Status:** Skeleton implemented, full implementation pending

**Current State:**
- WebSocket endpoint created (`/api/v1/kalshi/ui-state/ws`)
- React hook has WebSocket connection logic
- Event type definitions in place

**Remaining Work:**
1. Backend event subscription to fills, orders, risk events, kill switch changes, execution gate changes
2. Event bus integration for real-time push
3. Reconnection logic with exponential backoff
4. Event deduplication and ordering
5. Client-side state merge logic
6. Error handling and fallback to polling

**Complexity:** High - Requires integration with existing event infrastructure

### Phase 8: Screen Migration ⏳

**Status:** Not started

**Remaining Work:**
1. Create feature flag system
2. Migrate KalshiVolDashboardView to use new components
3. Migrate KalshiAgentPerformanceView
4. Migrate KalshiSentimentView
5. Update Overview to use new components
6. Validate each migration
7. Remove old views after validation

**Approach:** One screen at a time with feature flags for safe rollout

---

## Architecture Benefits

### Single Source of Truth
- All UI state from `/api/v1/kalshi/ui-state` endpoint
- Eliminates duplicate API calls across views
- Consistent state across all components

### Progressive Disclosure
- Overview shows essential state only
- Detail drawer reveals deeper information on demand
- Troubleshooting view for logs and errors

### Reduced Complexity
- 30+ components classified (10 essential, 12 useful-later, 5 duplicated, 3 dead)
- Clear path to remove dead/duplicated code
- Simplified data fetching patterns

### Maintainable Codebase
- Canonical state model makes changes predictable
- Clear separation between essential and advanced features
- Easy to add new detail views

---

## Next Steps

1. **Phase 7 (High Priority):** Implement WebSocket sync
   - Subscribe to event bus for fills, orders, risk events
   - Implement push mechanism
   - Add reconnection logic
   - Test real-time updates

2. **Phase 8 (Low Priority):** Migrate existing screens
   - Start with KalshiVolDashboardView
   - Use feature flags for safe rollout
   - Validate each migration
   - Remove old views

3. **Cleanup:** Remove dead/duplicated components
   - Remove 3 dead components
   - Consolidate 5 duplicated components
   - Update imports across codebase

---

## Files Created/Modified

### Created:
- `docs/KALSHI_UI_INVENTORY.md`
- `docs/KALSHI_CANONICAL_STATE_MODEL.md`
- `docs/KALSHI_UI_SIMPLIFICATION_PROGRESS.md` (this file)
- `web/api/kalshi_ui_state_api.py`
- `web/react/src/types/kalshiUIState.ts`
- `web/react/src/hooks/useKalshiUIState.ts`
- `web/react/src/components/KalshiCompactOverview.tsx`
- `web/react/src/components/KalshiActivityStream.tsx`
- `web/react/src/components/KalshiDetailDrawer.tsx`
- `web/react/src/components/KalshiTroubleshootingView.tsx`
- `web/react/src/components/KalshiActionArea.tsx`

### Modified:
- `web/react/src/config/constants.ts` - Added KALSHI_UI_STATE endpoints
- `web/main.py` - Registered kalshi_ui_state_api_router

---

## Testing Recommendations

1. **Backend API Testing:**
   - Test `/api/v1/kalshi/ui-state` endpoint
   - Verify data aggregation from all sources
   - Test error handling and fallbacks

2. **Frontend Component Testing:**
   - Test KalshiCompactOverview with mock data
   - Test KalshiActivityStream filtering
   - Test KalshiDetailDrawer lazy loading
   - Test KalshiTroubleshootingView tabs
   - Test KalshiActionArea controls

3. **Integration Testing:**
   - Test end-to-end data flow from backend to UI
   - Test error states and loading states
   - Test confirmation modals

4. **Performance Testing:**
   - Measure API response time for aggregation endpoint
   - Test with large numbers of positions/orders
   - Verify polling doesn't overload backend

---

## Conclusion

Phases 0-6 are complete, providing a solid foundation for the simplified Kalshi UI. The canonical state model is implemented and serving data, all essential UI components are built, and the architecture follows the stated principles.

The remaining work (Phase 7 WebSocket sync and Phase 8 screen migration) can be completed incrementally without disrupting the existing system.
