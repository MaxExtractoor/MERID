# UI Redesign — Next Steps (Compressed Phases)

## Phase A: Day-1 Operational Views (Week 1-2)

### Goal: Core operator loop — Dashboard + Trade + Monitor + Logs

**Tasks:**
1. ✅ Create Zustand store structure (store/index.ts)
2. ✅ Create WebSocket client (services/websocket.ts)
3. ✅ Build minimal Dashboard view (views/Dashboard.tsx)
4. ✅ Build Trade view placeholder (views/Trade.tsx)
5. ✅ Build Monitor view (views/Monitor.tsx)
6. ⏳ Update types/views.ts to include new view types
7. ⏳ Update App.tsx VIEW_COMPONENTS to include new views
8. ⏳ Replace sidebarManifest.ts with sidebarManifest.new.ts
9. ⏳ Wire Dashboard to store and WebSocket
10. ⏳ Run side-by-side with old UI for validation

**Deliverables:**
- Store with portfolio, risk, grid, system slices
- WebSocket client with reconnection logic
- Dashboard view with system health, kill switch, key metrics
- Trade view with market discovery placeholder
- Monitor view with portfolio and positions
- Updated sidebar with 8-view structure
- App.tsx routing for new views

**Guardrails:**
- UI never recomputes PnL, risk, or balances — only renders what backend provides
- Interface freeze: PortfolioData, RiskData, GridData, SystemData are contracts
- One connection per domain: Single WebSocket client, single polling layer

---

## Phase B: Grid + Risk Views (Week 3-4)

### Goal: Agent management and risk analytics

**Tasks:**
1. Build Grid view (views/Grid.tsx)
   - Agent matrix (5 assets × 15m)
   - Agent status cards
   - Deployment pipeline visualization
   - Auto-promoter controls
   - Performance metrics
   - Series ticker status
2. Build Risk view (views/Risk.tsx)
   - Risk summary cards
   - Risk gauges
   - Drawdown tier display
   - Sizing metrics
   - Performance ratios
   - Category exposure
   - Risk alerts
3. Add polling for grid status (10s interval)
4. Add polling for risk data (10s interval)
5. Wire Grid and Risk to store

**Deliverables:**
- Grid view with agent management
- Risk view with risk analytics
- Polling service for slow-moving data
- Store integration for grid and risk slices

---

## Phase C: Calibration + Settings + Cleanup (Week 5-6)

### Goal: Deep analytics and configuration

**Tasks:**
1. Build Calibration view (views/Calibration.tsx)
   - Calibration scores (Brier scores)
   - Realized edge tracking
   - Consensus weights
   - Forecaster performance
   - Calibration history chart
2. Update Settings view (views/Settings.tsx)
   - Profile selection
   - Risk limits configuration
   - Agent grid configuration
   - API credentials
3. Remove old views and components
   - Delete Overview, ExecuteView, DiscoverView, MonitorView, PromoteView, ProtectView
   - Delete kalshi-grid, kalshi-performance, calibration-dashboard, lane-control
   - Delete kalshi-risk-context, kalshi-sentiment, kalshi-vol-dashboard
   - Delete kill-switch view
4. Remove duplicate components
   - Consolidate risk panels
   - Consolidate status indicators
   - Consolidate chart components
5. Update tests for new views

**Deliverables:**
- Calibration view with agent calibration
- Updated Settings view
- Cleaned up codebase (old views removed)
- Updated tests

---

## Phase D: Testing & Polish (Week 7-8)

### Goal: Validate and polish new UI

**Tasks:**
1. Write unit tests for store
2. Write integration tests for WebSocket
3. Write E2E tests for critical flows (trade, kill switch, deployment)
4. Performance testing (bundle size, render performance)
5. Accessibility testing
6. Browser testing (Chrome, Firefox, Safari)
7. Fix bugs
8. Polish UI (spacing, colors, typography)

**Deliverables:**
- Unit tests for store
- Integration tests for WebSocket
- E2E tests for critical flows
- Performance report
- Accessibility report
- Browser compatibility report
- Bug fixes
- UI polish

---

## Backend Guardrails

### Rule 1: UI Never Recomputes
- UI only renders what backend provides via WebSocket/polling
- No PnL, risk, or balance calculations in frontend
- All derived metrics come from backend

### Rule 2: Interface Freeze
- PortfolioData, RiskData, GridData, SystemData are contracts
- Do not change shape mid-migration
- Add new fields behind the scenes, map in store

### Rule 3: One Connection Per Domain
- Single WebSocket client for live events
- Single polling layer for slow-moving metrics
- No component-local WebSocket hacks

---

## Current Status

### Completed
- ✅ Store structure (store/index.ts)
- ✅ WebSocket client (services/websocket.ts)
- ✅ Dashboard view (views/Dashboard.tsx)
- ✅ Trade view placeholder (views/Trade.tsx)
- ✅ Monitor view (views/Monitor.tsx)
- ✅ New sidebar manifest (sidebarManifest.new.ts)
- ✅ Update types/views.ts to include new view types
- ✅ Update App.tsx VIEW_COMPONENTS
- ✅ Replace sidebarManifest.ts with sidebarManifest.new.ts
- ✅ Wire Dashboard to store and WebSocket

### In Progress
- ⏳ Test Dashboard view with store and WebSocket
- ⏳ Run side-by-side with old UI for validation

### Next Immediate Steps
1. Start dev server: `cd web/react && npm run dev`
2. Navigate to /dashboard route
3. Verify WebSocket connection (check console for connection logs)
4. Verify store updates (check if portfolio/risk data populates)
5. Verify Dashboard renders correctly (system health, kill switch, metrics, alerts)
6. Test side-by-side with old UI (navigate between old and new views)
7. Fix any rendering issues or data flow issues
