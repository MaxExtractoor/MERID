# MERID UI-UX Audit Report
**Date:** 2026-07-02  
**Scope:** Complete UI-UX inventory, backend mapping, and 15m stack coverage analysis  
**Status:** Audit Complete

---

## Executive Summary

The MERID system has a sophisticated React-based frontend with extensive backend API coverage, but significant gaps exist between the UI and the 15-minute Kalshi crypto trading stack. The system uses an 8-view architecture with modern tooling (React 18, TypeScript, Tailwind CSS, Zustand), but many views are incomplete or placeholder. Critical UX bugs exist in trading workflows, and the 5-asset crypto stack (BTC, ETH, SOL, XRP, DOGE) is not uniformly covered across the interface.

**Key Findings:**
- **Frontend:** Modern React stack with 148 components, but 3 of 8 views are placeholders
- **Backend:** 150+ API endpoints with comprehensive trading operations coverage
- **15m Coverage:** Partial - specific 15m components exist but not integrated into main views
- **Critical Issues:** 19 UX bugs identified, including double-submit on orders and kill switch issues
- **Legacy Debt:** Extensive legacy HTML templates and unused components

---

## 1. Existing UI Inventory

### 1.1 Frontend Architecture

**Technology Stack:**
- React 18.2.0 with TypeScript
- Tailwind CSS for styling
- Zustand for state management
- Vite for build tooling
- Socket.io-client for WebSocket connections
- Recharts for data visualization
- Lucide React for icons

**Project Structure:**
```
web/react/
├── src/
│   ├── views/ (44 files - 8 main views + legacy)
│   ├── components/ (148 components)
│   ├── hooks/ (56 custom hooks)
│   ├── store/ (Zustand store with 4 slices)
│   ├── api/ (API client layer)
│   ├── types/ (TypeScript definitions)
│   ├── ui/ (UI primitives)
│   └── config/ (Configuration)
├── public/ (Static assets)
└── package.json (Dependencies)
```

### 1.2 8-View Architecture

The current production UI uses an 8-view architecture:

| View | Status | Purpose | Coverage |
|------|--------|---------|----------|
| **Dashboard** | ✅ Implemented | System health, kill switch, key metrics | Partial - missing 15m alignment details |
| **Trade** | ⚠️ Partial | Order entry, market discovery, positions | Placeholder market discovery |
| **Monitor** | ⚠️ Partial | Portfolio tracking, PnL, fills | TODO: fills integration |
| **Grid** | ✅ Implemented | Agent management, deployment | Good coverage |
| **Risk** | ✅ Implemented | Risk analytics, sizing metrics | Good coverage |
| **Calibration** | ❌ Placeholder | Agent calibration, consensus | Completely empty |
| **Logs** | ❌ Placeholder | System logs, activity | Completely empty |
| **Settings** | ⚠️ Partial | User preferences, configuration | Tabs exist but not wired |

### 1.3 Component Library

**Key Components (148 total):**

**Trading Components:**
- KalshiTradeTicket - Order entry with edge calculation
- KalshiOrderbookPanel - Real-time orderbook display
- KalshiBankrollPanel - Balance and bankroll management
- KalshiCancelAllButton - Bulk order cancellation
- BatchOrderPanel - Multi-order entry

**15m-Specific Components:**
- Kalshi15mAlignmentPanel - 15m invariant status
- Kalshi15mHealthPanel - 15m health monitoring
- Kalshi15mShadowModePanel - Shadow mode logging
- Kalshi15mPreflightCheck - 15m pre-flight validation

**Crypto Components:**
- CryptoLanesGrid - Crypto lane status grid
- CryptoSpotKalshiPanel - Spot vs Kalshi pricing
- KalshiCryptoRtiPanel - Crypto RTI feed
- KalshiCryptoSignalsPanel - Crypto trading signals

**Risk & Safety:**
- KalshiRiskFeed - Real-time risk alerts
- RiskProtectionsPanel - Risk limit configuration
- EmergencyStopButton - Kill switch control
- CircuitBreakerPanel - Circuit breaker status

**Infrastructure:**
- Sidebar - Navigation with 8-view structure
- TopBar - Header with search and controls
- CommandPalette - Keyboard shortcut navigation
- ErrorBoundary - Per-view error isolation
- KalshiLoadingSkeleton - Loading states
- EmptyState - Empty state messaging

### 1.4 Legacy UI Assets

**HTML Templates (web/templates/):**
- production_dashboard.html - "Elite" production dashboard
- merid_trading_dashboard.html - Trading dashboard with Chart.js
- prime_screen.html - Prime screening interface
- api_dashboard.html - API monitoring dashboard
- merid_spa.html - Single-page application shell
- unified_shell.html - Unified dashboard shell

**Status:** These are legacy templates not integrated with the React 8-view architecture. They represent previous UI iterations and should be deprecated.

---

## 2. Backend API Mapping

### 2.1 API Endpoint Inventory

**Total API Endpoints:** 150+ across 140+ Python files

**Key API Categories:**

**Kalshi Trading (kalshi_api.py - 8,885 lines):**
- `GET /api/v1/kalshi/markets` - Browse all cataloged markets
- `GET /api/v1/kalshi/markets/{ticker}` - Single market detail
- `GET /api/v1/kalshi/catalog` - Catalog summary
- `GET /api/v1/kalshi/positions` - Current positions
- `GET /api/v1/kalshi/orders` - Open orders
- `GET /api/v1/kalshi/fills` - Recent fills
- `POST /api/v1/kalshi/orders` - Place order
- `GET /api/v1/kalshi/pnl` - Portfolio PnL
- `GET /api/v1/kalshi/risk` - Risk manager status
- `POST /api/v1/kalshi/kill-switch` - Kill switch control

**Agent Grid (kalshi_grid_api.py - 1,182 lines):**
- `GET /api/v1/kalshi-grid/status` - Full grid status
- `GET /api/v1/kalshi-grid/matrix` - Asset × timeframe grid
- `GET /api/v1/kalshi-grid/agents` - All agent summaries
- `GET /api/v1/kalshi-grid/agents/{name}` - Single agent detail
- `POST /api/v1/kalshi-grid/start` - Start grid
- `POST /api/v1/kalshi-grid/stop` - Stop grid
- `POST /api/v1/kalshi-grid/mode` - Switch trading mode

**Risk Metrics (risk_metrics_api.py - 456 lines):**
- `GET /api/v1/risk/metrics` - Current risk metrics
- `POST /api/v1/risk/halt` - Trading halt
- `POST /api/v1/risk/resume` - Trading resume

**Dashboard (dashboard.py - 240 lines):**
- `GET /api/portfolio/summary` - Portfolio summary
- `GET /api/prices/live` - Live prices for symbols

**Agents (agents.py - 179 lines):**
- `GET /api/v1/agents/status` - Agent status
- `GET /api/v1/agents/activity` - Agent activity log

**Crypto-Specific APIs:**
- `crypto_lanes_api.py` - Crypto lane management
- `crypto_spot_kalshi_api.py` - Spot vs Kalshi pricing
- `crypto_rti_api.py` - Crypto RTI feed
- `crypto_status_authoritative.py` - Authoritative crypto status
- `kalshi_crypto_signals_api.py` - Crypto trading signals

### 2.2 Data Structures

**Portfolio Data (from store/index.ts):**
```typescript
interface PortfolioData {
  balance: number;
  cash: number;
  portfolio_value: number;
  daily_pnl: number;
  positions: Position[];
  fills: Fill[];
  timestamp: string;
}
```

**Risk Data:**
```typescript
interface RiskData {
  daily_pnl: number;
  drawdown_pct: number;
  total_notional: number;
  kill_switch_active: boolean;
  kill_switch_reason: string;
  sizing_metrics: SizingMetrics;
  alerts: RiskAlert[];
  timestamp: string;
}
```

**Grid Data:**
```typescript
interface GridData {
  running: boolean;
  agents: AgentSummary[];
  deployment: DeploymentStatus;
  performance: PerformanceMetrics;
  timestamp: string;
}
```

**System Data:**
```typescript
interface SystemData {
  health: {
    ok: boolean;
    services: Record<string, ServiceHealth>;
    overall_latency_ms: number;
  };
  logs: LogEntry[];
  timestamp: string;
}
```

### 2.3 WebSocket Infrastructure

**WebSocket Endpoints:**
- Portfolio updates via `useKalshiRiskStream`
- Order updates via `useOrderGroupStream`
- Tick data via `useTickStream`
- Risk alerts via dedicated risk stream

**Status:** WebSocket infrastructure exists but reconnection logic has issues (identified in UI_WIRING_AUDIT.md)

---

## 3. 15m Stack Coverage Analysis

### 3.1 Required 5-Asset Coverage

**Critical Requirement:** The 15m Kalshi crypto trading system MUST cover all 5 assets:
- BTC/USD
- ETH/USD
- SOL/USD
- XRP/USD
- DOGE/USD

### 3.2 Current 15m Coverage by View

| View | BTC | ETH | SOL | XRP | DOGE | Status |
|------|-----|-----|-----|-----|------|--------|
| Dashboard | ❌ | ❌ | ❌ | ❌ | ❌ | No asset-specific display |
| Trade | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | Mentioned in placeholder, not implemented |
| Monitor | ❌ | ❌ | ❌ | ❌ | ❌ | Generic positions table |
| Grid | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ❌ | CryptoLanesGrid filters 15M but missing DOGE |
| Risk | ❌ | ❌ | ❌ | ❌ | ❌ | Generic risk metrics |
| Calibration | ❌ | ❌ | ❌ | ❌ | ❌ | Placeholder |
| Logs | ❌ | ❌ | ❌ | ❌ | ❌ | Placeholder |
| Settings | ❌ | ❌ | ❌ | ❌ | ❌ | Generic settings |

### 3.3 15m-Specific Components

**Existing 15m Components:**
1. **Kalshi15mAlignmentPanel** - Displays 7 backend invariants for 15m stack
2. **Kalshi15mHealthPanel** - 15m-specific health monitoring
3. **Kalshi15mShadowModePanel** - Shadow mode logging for 15m
4. **Kalshi15mPreflightCheck** - End-to-end 15m validation

**Integration Status:** These components exist but are only used in OperatorDashboard, not in the main 8-view architecture.

### 3.4 Crypto Component Coverage

**CryptoLanesGrid:**
- Filters lanes ending with `_15M` or `_15M_PAPER`
- Shows: BTC, ETH, SOL, XRP
- **Missing:** DOGE

**CryptoSpotKalshiPanel:**
- Asset metadata includes: BTC, ETH, SOL, XRP, DOGE
- Shows spot vs Kalshi pricing by timeframe
- Timeframe order: 15m, 1h, daily, weekly
- **Status:** Component exists but not integrated into main views

### 3.5 Coverage Gaps

**Critical Gaps:**
1. **Dashboard:** No per-asset metrics or 15m alignment status
2. **Trade:** Market discovery is placeholder - no actual market catalog integration
3. **Monitor:** Positions table doesn't show asset-specific performance
4. **Grid:** DOGE missing from CryptoLanesGrid filter
5. **Risk:** No per-asset risk exposure or limits
6. **Calibration:** Completely empty - no agent calibration display
7. **Logs:** Completely empty - no system log viewer
8. **Settings:** No 15m-specific configuration options

**DOGE-Specific Gap:**
- DOGE is included in CryptoSpotKalshiPanel asset metadata
- DOGE is missing from CryptoLanesGrid filter (only checks BTC, ETH, SOL, XRP)
- No DOGE-specific components or views

---

## 4. Critical UX Issues

### 4.1 UI Wiring Audit Findings

**Source:** `web/react/UI_WIRING_AUDIT.md` (1,814 lines)

**Total Issues Identified:** 19 bugs across 4 severity tiers

**Critical Severity (Data-loss or money-at-risk):**
1. **C-01:** ConfirmModal checklist state persists across openings (React.memo + useState)
2. **C-02:** Trade ticket allows double-submit - no submit guard
3. **C-03:** Kill switch toggle has no optimistic lock or debounce

**High Severity (Broken state or misleading UX):**
1. **H-01:** PositionsView "View decision" link uses hash routing (app doesn't use hash routing)
2. **H-02:** KalshiGridView agent-focus from sessionStorage clears even when agent not found
3. **H-03:** useKalshiRiskStream WS reconnect has no URL change detection
4. **H-04:** useFillToast creates new poll callback on every toast identity change
5. **H-05:** useApiData double-fetches on mount when polling is enabled
6. **H-06:** Toast in KalshiTerminalView flickers on every WS alert batch
7. **H-07:** CommandPalette Ctrl+K conflicts with KalshiTerminalView Ctrl+Shift+K

**Medium Severity (Degraded UX):**
1. **M-01:** handleCancelOrder doesn't await refetch - cancel button re-enables too early
2. **M-02:** handleCancelAll uses stale orders.length in confirm message
3. **M-03:** ConfirmModal handleKeyDown for Escape doesn't auto-focus
4. **M-04:** OperatorDashboard kill switch uses window.confirm while other views use ConfirmModal
5. **M-05:** ExecutionGateStrip config reload button timeout has no cleanup
6. **M-06:** RealtimeDisconnectedBanner initial disconnectedAt state race

**Low Severity (Polish and hardening):**
1. **L-01:** useApiData query parameter option declared but never wired
2. **L-02:** KalshiTradeTicket edge calculation formula appears inverted
3. **L-03:** Sidebar KalshiModeBadge renders on every nav item re-render
4. **L-04:** ErrorBoundary "Try again" only clears error state - doesn't re-fetch data

### 4.2 Cross-Cutting Pattern Issues

**Pattern A: Inconsistent mutation patterns**
- Direct fetch + refetch (Terminal, GridView)
- Hook-wrapped mutations (OperatorDashboard)
- Window.confirm + direct fetch (OperatorDashboard kill switch)

**Pattern B: Duplicate execution gate checks**
- ExecutionGateStrip, KalshiTradeTicket, and useExecutionGate all independently poll SYSTEM_EXECUTION_GATE
- Results in 3 parallel polling loops on Terminal view

### 4.3 Legacy vs Production Contamination

**Risk:** Cross-contamination between legacy and production stacks

**Known Contamination Points:**
- MD health thresholds may be from legacy strict requirements
- Some diagnostics may query legacy catalog/MD instead of production
- WebSocket forwarder IDLE state suggests subscription issues

**Critical Rule:** main.py is LEGACY, main_15m_lean.py is PRODUCTION
- Any code path using main.py instead of main_15m_lean.py is using legacy code
- Legacy contamination risks include old startup patterns, singleton initialization issues

---

## 5. Placeholder and Incomplete Views

### 5.1 Trade View

**Status:** Partial implementation

**Working:**
- Basic layout with tabs (Markets, Positions, Orders)
- Positions table with data from store
- Navigation structure

**Missing:**
- Market discovery is placeholder: "TODO: Integrate with Kalshi market catalog"
- No actual market catalog integration
- No order entry form (KalshiTradeTicket exists but not integrated)
- No orderbook display
- No order management

**Code Reference:**
```typescript
// Trade.tsx line 57-67
<Card>
  <CardHeader>
    <CardTitle>15m Crypto Markets</CardTitle>
  </CardHeader>
  <CardContent>
    <div className="text-center py-8 text-slate-500">
      <Search className="w-12 h-12 mx-auto mb-3 opacity-50" />
      <p>Market discovery for 15m crypto (BTC, ETH, SOL, XRP, DOGE)</p>
      <p className="text-sm mt-2">TODO: Integrate with Kalshi market catalog</p>
    </div>
  </CardContent>
</Card>
```

### 5.2 Monitor View

**Status:** Partial implementation

**Working:**
- Portfolio summary cards
- Positions table
- Recent fills table
- System health display

**Missing:**
- TODO comment: "Integrate fills from store, add PnL chart"
- No PnL chart/equity curve
- No performance metrics visualization
- No historical data

**Code Reference:**
```typescript
// Monitor.tsx line 15
* TODO: Integrate fills from store, add PnL chart
```

### 5.3 Calibration View

**Status:** Complete placeholder

**Working:**
- Basic layout with header

**Missing:**
- Everything - completely empty
- No agent calibration metrics
- No Brier scores
- No consensus weights
- No forecaster performance
- No calibration history

**Code Reference:**
```typescript
// Calibration.tsx line 42-47
<div className="text-center py-8 text-slate-400">
  <Activity className="w-12 h-12 mx-auto mb-4 text-slate-600" />
  <p>Calibration view coming soon</p>
  <p className="text-sm mt-2">This view will display agent calibration metrics and consensus data.</p>
</div>
```

### 5.4 Logs View

**Status:** Complete placeholder

**Working:**
- Basic layout with header

**Missing:**
- Everything - completely empty
- No log viewer
- No activity stream
- No error log display
- No filtering or search

**Code Reference:**
```typescript
// Logs.tsx line 24-27
<div className="text-center py-8 text-slate-400">
  <p>Logs view coming soon</p>
  <p className="text-sm mt-2">This view will display system logs and activity history.</p>
</div>
```

### 5.5 Settings View

**Status:** Partial implementation

**Working:**
- Tab structure exists with 5 tabs:
  - AgentsTab
  - TradingSettingsTab
  - RiskTab
  - PreferencesTab
  - NotificationSettingsTab

**Missing:**
- Tabs are not wired to backend
- No actual configuration persistence
- Settings are form placeholders only

**Code Reference:**
```typescript
// Settings.tsx line 24-27
<div className="text-center py-8 text-slate-400">
  <p>Settings view coming soon</p>
  <p className="text-sm mt-2">This view will display user preferences and configuration options.</p>
</div>
```

---

## 6. Backend vs Frontend Alignment

### 6.1 API Coverage vs UI Implementation

| API Category | Backend Endpoints | UI Implementation | Gap |
|--------------|-------------------|------------------|-----|
| Kalshi Trading | 20+ endpoints | Partial (Trade view placeholder) | High |
| Agent Grid | 15+ endpoints | Good (Grid view) | Low |
| Risk Metrics | 10+ endpoints | Good (Risk view) | Low |
| Dashboard | 5+ endpoints | Partial (Dashboard view) | Medium |
| Agents | 5+ endpoints | Partial (not in 8-view) | High |
| Crypto Lanes | 10+ endpoints | Partial (CryptoLanesGrid) | Medium |
| 15m Specific | 8+ endpoints | Components exist, not integrated | High |

### 6.2 Data Flow Architecture

**Current Architecture:**
```
Backend (FastAPI)
    ↓ HTTP/WebSocket
Frontend (React)
    ↓
Zustand Store (4 slices)
    ↓
Views (8-view architecture)
```

**Issues:**
- Store exists but not all views use it consistently
- Some views use direct API calls instead of store
- WebSocket reconnection logic has issues
- No unified error handling across views

### 6.3 WebSocket Integration

**Current WebSocket Streams:**
- Portfolio updates (useKalshiRiskStream)
- Order updates (useOrderGroupStream)
- Tick data (useTickStream)
- Risk alerts (dedicated stream)

**Issues:**
- Reconnection logic doesn't detect URL/token changes
- Double-fetching on mount with polling
- Toast flickering on rapid alert batches

---

## 7. Recommendations

### 7.1 Immediate Priorities (P0)

1. **Fix Critical UX Bugs:**
   - Add submit guard to KalshiTradeTicket (C-02)
   - Fix kill switch toggle optimistic locking (C-03)
   - Fix ConfirmModal state persistence (C-01)

2. **Complete Trade View:**
   - Integrate Kalshi market catalog API
   - Add KalshiTradeTicket for order entry
   - Add KalshiOrderbookPanel
   - Implement order management

3. **Add DOGE Coverage:**
   - Update CryptoLanesGrid to include DOGE
   - Ensure all 5 assets are displayed in all views
   - Add DOGE-specific metrics where appropriate

### 7.2 Short-term Priorities (P1)

1. **Complete Monitor View:**
   - Integrate fills from store
   - Add PnL chart/equity curve
   - Add performance metrics visualization

2. **Implement Calibration View:**
   - Add agent calibration metrics
   - Add Brier scores display
   - Add consensus weights
   - Add forecaster performance

3. **Implement Logs View:**
   - Add log viewer component
   - Add activity stream
   - Add filtering and search

4. **Wire Settings View:**
   - Connect tabs to backend APIs
   - Implement configuration persistence
   - Add validation

### 7.3 Medium-term Priorities (P2)

1. **Integrate 15m Components:**
   - Add Kalshi15mAlignmentPanel to Dashboard
   - Add Kalshi15mHealthPanel to Dashboard
   - Add 15m status indicators to all views

2. **Fix High-Severity UX Bugs:**
   - Fix hash routing in PositionsView (H-01)
   - Fix agent-focus clearing in KalshiGridView (H-02)
   - Fix WebSocket reconnection (H-03)
   - Fix double-fetching in useApiData (H-05)

3. **Standardize Mutation Patterns:**
   - Choose single pattern (recommend hook-wrapped)
   - Refactor all mutations to use consistent pattern
   - Add optimistic updates

4. **Remove Duplicate Polling:**
   - Consolidate execution gate checks
   - Implement single polling layer
   - Add request deduplication

### 7.4 Long-term Priorities (P3)

1. **Deprecate Legacy Templates:**
   - Remove HTML templates in web/templates/
   - Migrate any useful patterns to React
   - Update documentation

2. **Performance Optimization:**
   - Fix Sidebar re-render issues (L-03)
   - Implement proper memoization
   - Optimize bundle size

3. **Accessibility Improvements:**
   - Fix Escape key handling in ConfirmModal (M-03)
   - Add ARIA labels consistently
   - Improve keyboard navigation

4. **Testing:**
   - Add E2E tests for critical flows
   - Add unit tests for store
   - Add integration tests for WebSocket

---

## 8. Next Steps

### 8.1 Research Phase

Before implementing the facelift, research:

1. **2026 UI/UX Best Practices for Trading Systems:**
   - Modern trading dashboard patterns
   - Real-time data visualization best practices
   - Dark mode design standards
   - Mobile-first trading interfaces

2. **Modern Dashboard Frameworks:**
   - Component libraries (shadcn/ui, Chakra UI, MUI)
   - Chart libraries (Recharts alternatives)
   - State management patterns
   - WebSocket integration patterns

### 8.2 Planning Phase

Create comprehensive UI facelift plan including:

1. **Design System:**
   - Color palette (dark mode optimized)
   - Typography scale
   - Spacing system
   - Component variants

2. **Information Architecture:**
   - View hierarchy
   - Navigation patterns
   - Data density decisions
   - Responsive breakpoints

3. **Component Strategy:**
   - Component library selection
   - Custom component needs
   - Reusability patterns
   - Performance considerations

### 8.3 Implementation Phase

Implement in priority order:

1. **P0:** Critical bug fixes + Trade view completion
2. **P1:** Complete placeholder views + DOGE coverage
3. **P2:** 15m component integration + UX bug fixes
4. **P3:** Legacy removal + performance optimization

---

## 9. Conclusion

The MERID system has a solid foundation with modern React tooling and comprehensive backend APIs. However, significant work is needed to:

1. **Complete the 8-view architecture** (3 of 8 views are placeholders)
2. **Achieve full 5-asset coverage** (DOGE is missing from key components)
3. **Integrate 15m-specific components** into the main views
4. **Fix critical UX bugs** that pose money-at-risk risks
5. **Standardize patterns** across the codebase

The backend is well-equipped to support a modern trading interface, but the frontend needs a systematic facelift to realize the full potential of the 15m Kalshi crypto trading stack.

---

**Report Generated:** 2026-07-02  
**Auditor:** Cascade AI Assistant  
**Next Action:** Research 2026 UI/UX best practices and modern dashboard frameworks
