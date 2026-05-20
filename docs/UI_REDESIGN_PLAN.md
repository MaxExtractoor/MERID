# MERID-Kalshi UI Redesign Plan — Less Is More Approach

**Date**: 2026-05-11  
**Goal**: Reduce CPU/memory load while maintaining Kalshi-focused user-friendly UI/UX  
**Philosophy**: Consolidate, simplify, and optimize for end-to-end MERID-Kalshi integration  
**Scope**: Kalshi-only mode with full trading, risk, and monitoring capabilities

---

## Executive Summary

The current MERID-Kalshi UI has significant bloat that impacts performance and maintainability:
- **35 active views** + 11 legacy views (Kalshi-focused subset)
- **70+ components** with overlapping functionality
- **39 hooks** with duplicate patterns
- **89 files** with pollingInterval (excessive network requests)
- **No code splitting** (all views loaded upfront)
- **Monolithic components** (500-900+ lines each)

This plan consolidates the Kalshi-focused UI into a leaner architecture while preserving all critical trading, risk management, and monitoring functionality for the MERID-Kalshi integration.

---

## Current State Audit

### File Structure Analysis

**Views (35 active + 11 legacy)**
- Largest: Settings.tsx (953 lines), KalshiVolDashboardView.tsx (929), KalshiSentimentView.tsx (748)
- All loaded synchronously in App.tsx (no lazy loading)

**Components (70+ files)**
- Largest: OrderGroupPanel.tsx (825 lines), KalshiTradeTicket.tsx (599), BatchOrderPanel.tsx (536)
- Many overlapping patterns (panels, indicators, badges, charts)

**Hooks (39 files)**
- useApiData.ts (283 lines) - complex polling/backoff logic
- 39 hooks with similar data fetching patterns

**Performance Issues**
1. **89 files use pollingInterval** - constant network requests
2. **89 files use setInterval/setTimeout** - potential memory leaks
3. **No code splitting** - initial bundle includes all views
4. **Large component trees** - deep nesting causes re-render cascades
5. **Duplicate data fetching** - multiple hooks fetch same endpoints

---

## Redesign Principles

### 1. Consolidation Over Duplication
- Merge similar components into configurable primitives
- Single source of truth for data fetching
- Unified status/badge/indicator system
- Kalshi-specific patterns (market data, order flow, risk states)

### 2. Lazy Loading Everywhere
- Route-based code splitting for all major views
- Feature-level splitting for heavy but infrequent features (export modals, advanced charts)\- Avoid over-splitting tiny components (buttons, icons) which hurts performance
- Dynamic imports for non-critical features

### 3. Polling Reduction
- Replace polling with WebSocket subscriptions for high-frequency/bi-directional data (order fills, agent status, market data)
- Use SSE or shorter polling intervals for low-frequency dashboards
- Implement intelligent polling (only when tab is visible)
- Deduplicate identical requests across components

### 4. Component Size Guidelines (Refined)
- **One responsibility per component** - components should do one thing well
- **State limits**: No component managing more than 5 pieces of state or 3 useEffects
- **Encourage container/presentation splits** where appropriate
- **Extract sub-components** when view exceeds ~300 lines
- **Use composition over inheritance**

### 5. State Management Simplification
- Reduce useState calls per component
- Use useReducer for complex state (3+ related state variables)
- Leverage React Query for server state
- Consistent loading/error handling patterns across all data hooks

### 6. File Structure & Co-location
- **Feature-based organization**: Group by Kalshi domain (trading, risk, monitoring, settings)
- **Co-location**: Keep hooks, components, and styles for a feature together
- **Clear data flow**: All data hooks follow consistent pattern (loading/error/data/refetch)
- **Avoid deep nesting**: Max 3 levels of component hierarchy

---

## Design Tokens + Primitives

### Color Tokens (Kalshi States)
```typescript
const KALSHI_STATUS_COLORS = {
  success: { bg: 'bg-emerald-950/30', border: 'border-emerald-500/30', text: 'text-emerald-400' },
  warning: { bg: 'bg-amber-950/30', border: 'border-amber-500/30', text: 'text-amber-400' },
  error: { bg: 'bg-red-950/40', border: 'border-red-500/40', text: 'text-red-400' },
  info: { bg: 'bg-blue-950/30', border: 'border-blue-500/30', text: 'text-blue-400' },
  neutral: { bg: 'bg-slate-800/70', border: 'border-slate-700/40', text: 'text-slate-300' },
} as const;
```

### Spacing Tokens
```typescript
const SPACING = {
  xs: '0.25rem',  // 4px
  sm: '0.5rem',   // 8px
  md: '1rem',     // 16px
  lg: '1.5rem',   // 24px
  xl: '2rem',     // 32px
} as const;
```

### Typography Tokens
```typescript
const TYPOGRAPHY = {
  'label-xs': 'text-[10px] uppercase text-slate-500',
  'label-sm': 'text-xs text-slate-400',
  'value-md': 'text-sm font-semibold text-slate-200',
  'value-lg': 'text-lg font-bold text-slate-100',
} as const;
```

---

## Component Consolidation Strategy

### Phase 1: Indicator Components (Consolidate 5 → 1)

**Current**: StatusIndicator, DataFreshnessIndicator, StalenessIndicator, OfflineIndicator, ConnectionStatusIndicator

**Target**: Single `StatusIndicator` component with clear API
```typescript
interface StatusIndicatorProps {
  status: 'success' | 'warning' | 'error' | 'info' | 'neutral';
  size?: 'xs' | 'sm' | 'md' | 'lg';
  label?: string;
  icon?: React.ReactNode;
  showTimestamp?: boolean;
  timestamp?: Date;
  onClick?: () => void;
}

// Usage:
<StatusIndicator 
  status="success"
  size="md"
  label="Kalshi API Healthy"
  icon={<CheckCircle2 />}
/>
```

**API Contract**:
- `status` maps to KALSHI_STATUS_COLORS tokens
- `size` controls icon and text scaling
- `label` uses TYPOGRAPHY tokens
- No per-screen color overrides (use status tokens)

**Impact**: 
- Delete 4 components (~200 lines)
- Reduce imports across 20+ files
- Single source of truth for status logic
- Consistent visual language across Kalshi dashboard

---

### Phase 2: Badge Components (Consolidate 9 → 2)

**Current**: Badge (ui/common.tsx), Badge (ui/Badge.tsx), DataAgeBadge, DataSourceBadge, OrderLineageBadge, KalshiReconciliationBadge, DebateStatusBadge, RegimeBadge, ConnectionStatusBadge

**Target**: 
- `Badge` - generic badge component
- `DataBadge` - specialized for Kalshi data-related badges (age, source, reconciliation)

**Badge API**:
```typescript
interface BadgeProps {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'neutral';
  size?: 'xs' | 'sm' | 'md';
  children: React.ReactNode;
  onClick?: () => void;
}

// Usage:
<Badge variant="success" size="sm">Paper Mode</Badge>
```

**DataBadge API**:
```typescript
interface DataBadgeProps {
  type: 'age' | 'source' | 'reconciliation' | 'kalshi-status';
  value: string | number;
  timestamp?: Date;
  source?: string;
}

// Usage:
<DataBadge type="age" value="2m ago" timestamp={new Date()} />
<DataBadge type="source" value="Kalshi" source="kalshi-api" />
```

**API Contract**:
- `variant`/`type` maps to KALSHI_STATUS_COLORS
- `size` uses SPACING tokens
- No custom colors (use tokens)

**Impact**:
- Delete 7 components (~400 lines)
- Consolidate badge logic
- Reduce variant complexity
- Consistent Kalshi data labeling

---

### Phase 3: Panel Components (Consolidate 7 → 2)

**Current**: AlertHistoryPanel, ContractHealthPanel, CryptoAlertStatusPanel, NotificationStatusPanel, RiskProtectionsPanel, SessionLogPanel, SocialAdvisoryPanel

**Target**:
- `DataPanel` - generic panel with title, content, actions
- `AlertPanel` - specialized for Kalshi alert/history data

**DataPanel API**:
```typescript
interface DataPanelProps {
  title: string;
  icon?: React.ReactNode;
  status?: 'success' | 'warning' | 'error' | 'info' | 'neutral';
  children: React.ReactNode;
  actions?: React.ReactNode;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
}

// Usage:
<DataPanel 
  title="Kalshi Contract Health"
  icon={<ShieldCheck />}
  status="success"
  actions={<RefreshButton />}
>
  <ContractHealthTable />
</DataPanel>
```

**AlertPanel API**:
```typescript
interface AlertPanelProps {
  title: string;
  alerts: KalshiAlert[];
  onAcknowledge?: (alertId: string) => void;
  onFilter?: (severity: string) => void;
  maxVisible?: number;
}

// Usage:
<AlertPanel 
  title="Kalshi Risk Alerts"
  alerts={kalshiAlerts}
  onAcknowledge={handleAck}
/>
```

**API Contract**:
- `status` maps to KALSHI_STATUS_COLORS
- Panel styling uses SPACING tokens
- Consistent collapse/expand behavior

**Impact**:
- Delete 5 components (~800 lines)
- Reusable panel pattern
- Consistent UI across Kalshi dashboard

---

### Phase 4: Chart Components (Consolidate 4 → 1)

**Current**: KalshiPnlChart, PortfolioChart, DomainPnLChart, DrawdownChart

**Target**: Single `TimeSeriesChart` component for Kalshi metrics
```typescript
interface TimeSeriesChartProps {
  data: TimeSeriesDataPoint[];
  type: 'line' | 'area' | 'bar';
  metric: 'pnl' | 'equity' | 'drawdown' | 'volume' | 'fills';
  height?: number;
  showTooltip?: boolean;
  showLegend?: boolean;
  colorScheme?: 'kalshi-blue' | 'kalshi-green' | 'kalshi-orange';
  onPointClick?: (point: TimeSeriesDataPoint) => void;
}

// Usage:
<TimeSeriesChart 
  data={kalshiPnlData}
  type="area"
  metric="pnl"
  colorScheme="kalshi-green"
  onPointClick={handlePnlClick}
/>
```

**API Contract**:
- `metric` determines y-axis label and formatting
- `colorScheme` maps to Kalshi brand colors
- Consistent tooltip/legend behavior
- Lightweight wrapper around charting library (no heavy dependencies)

**Impact**:
- Delete 3 components (~300 lines)
- Unified charting library wrapper
- Consistent chart styling across Kalshi views
- Reduced bundle size from charting deduplication

---

### Phase 5: Hook Consolidation (39 → 12)

**Current**: 39 hooks with overlapping patterns

**Target**: Consolidate into 12 core hooks
1. `useApiData` - keep as-is (core data fetching)
2. `useWebSocket` - keep as-is (real-time data)
3. `usePolling` - NEW (intelligent polling wrapper)
4. `useLocalStorage` - keep as-is
5. `useDebounce` - NEW (debounced inputs)
6. `useThrottle` - NEW (throttled updates)
7. `useVisibility` - NEW (tab visibility detection)
8. `useOptimizedData` - keep as-is
9. `useRiskProtections` - keep as-is
10. `useKalshiData` - NEW (consolidated Kalshi hooks)
11. `useOperatorData` - NEW (consolidated operator hooks)
12. `useDebateData` - NEW (consolidated debate hooks)

**Delete**: 27 hooks (~1500 lines)

**Impact**:
- Massive code reduction
- Easier to maintain
- Clear separation of concerns

---

## View Restructuring Strategy

### Phase 1: Route-Based Code Splitting

**Current**: All views imported directly in App.tsx

**Target**: Lazy load all views
```tsx
const Overview = lazy(() => import('./views/Overview'));
const OperatorDashboard = lazy(() => import('./views/OperatorDashboard'));
// ... all views
```

**Impact**:
- Reduce initial bundle size by ~60%
- Faster initial page load
- Load views on-demand

---

### Phase 2: View Size Reduction

**Target**: Split large views into sub-components

**Settings.tsx (953 lines) → 3 files**
- Settings.tsx (200 lines) - layout and tab switching
- PreferencesTab.tsx (250 lines)
- TradingTab.tsx (250 lines)
- NotificationsTab.tsx (200 lines)

**KalshiVolDashboardView.tsx (929 lines) → 4 files**
- KalshiVolDashboardView.tsx (200 lines) - layout
- AgentSizingGrid.tsx (250 lines) - extracted
- VolatilityChart.tsx (250 lines) - extracted
- RiskMetricsPanel.tsx (200 lines) - extracted

**KalshiSentimentView.tsx (748 lines) → 3 files**
- KalshiSentimentView.tsx (200 lines) - layout
- SentimentChart.tsx (300 lines) - extracted
- SentimentFeed.tsx (200 lines) - extracted

---

### Phase 3: Legacy View Cleanup

**Delete all 11 legacy views** (already moved to _legacy/):
- BurninStatsView.tsx
- KalshiAllMarketsView.tsx
- KalshiRiskContextView.tsx
- KalshiRiskScreen.tsx
- KillSwitchView.tsx
- LaneControlDashboard.tsx
- OperatorActivityStream.tsx
- OperatorControlPlane.tsx
- OperatorStatusBar.tsx
- OrdersView.tsx
- PositionsView.tsx

**Impact**: Delete ~3000 lines of dead code

---

## Performance Optimization Strategy

### Phase 1: Polling Reduction

**Current**: 89 files with pollingInterval

**Target**: Reduce to <20 files

**WebSocket Deployment Scope**:
- **High-frequency/bi-directional (use WebSocket)**:
  - Order fills stream (`/ws/fills`)
  - Agent status updates (`/ws/agents`)
  - Kalshi market data stream (`/ws/kalshi/markets`)
  - Risk state changes (`/ws/risk`)

- **Low-frequency/one-way (use SSE or polling)**:
  - System health checks (poll every 30s)
  - Catalog refresh (poll every 5min)
  - Historical PnL data (poll on demand)
  - Calibration metrics (poll every 60s)

**WebSocket Fallback Strategy**:
1. **Connection failure**: Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, 15s max)
2. **Corporate proxy support**: Support both WS and WSS protocols, auto-detect
3. **Heartbeat**: Send ping every 30s, disconnect if no pong in 60s
4. **Graceful degradation**: Fall back to polling if WebSocket unavailable
5. **Network flakiness**: Buffer messages locally, replay on reconnect

**Actions**:
1. Replace polling with WebSocket subscriptions for high-frequency data
   - Order fills → WebSocket (`/ws/fills`)
   - Agent status → WebSocket (`/ws/agents`)
   - Risk state → WebSocket (`/ws/risk`)
   - Kalshi market data → WebSocket (`/ws/kalshi/markets`)

2. Implement intelligent polling for remaining endpoints
   - Only poll when tab is visible (useVisibility hook)
   - Backoff on error (already in useApiData)
   - Stop polling when user is inactive

3. Deduplicate requests
   - Use React Query's built-in deduplication
   - Share data across components via KalshiDataContext
   - Cache responses with TTL (30s default)

**Impact**: 
- Reduce network requests by ~70%
- Lower CPU usage
- Better battery life on mobile
- Real-time Kalshi order fills and market data

---

### Phase 2: Re-render Optimization

**Actions**:
1. Add React.memo to all large components
2. Use useCallback for all event handlers
3. Use useMemo for expensive computations
4. Implement virtual scrolling for large lists
5. Use React.lazy for heavy panels

**Impact**:
- Reduce unnecessary re-renders
- Smoother UI interactions
- Lower memory usage

---

### Phase 3: Bundle Size Optimization

**Code Splitting Scope**:
- **Route-level splitting** (apply to all major views):
  - Overview, OperatorDashboard, KalshiVolDashboardView, etc.
  - Load view code only when route is accessed
  - Add Suspense boundaries with loading skeletons

- **Feature-level splitting** (apply to heavy but infrequent features):
  - Export modals (CSV, PDF export)
  - Advanced chart configurations
  - Kalshi trade ticket (lazy load on first use)
  - Reconciliation dashboard

- **Avoid over-splitting** (keep inline):
  - Buttons, icons, badges, indicators
  - Small utility components (<5KB)
  - Design system primitives

**Actions**:
1. Route-based code splitting for all 35 views
2. Feature-level splitting for 5-6 heavy features
3. Tree-shake unused dependencies
4. Replace heavy libraries with lighter alternatives (e.g., chart libraries)
5. Use dynamic imports for non-critical features
6. Implement asset compression (gzip, brotli)

**Target**: Reduce bundle size by 50%

---

## Implementation Roadmap

### Tier 1: Critical Performance Fixes (Week 1)

**Priority**: HIGH  
**Impact**: Immediate CPU/memory reduction

1. **Implement route-based code splitting**
   - Update App.tsx to use lazy loading for all 35 views
   - Add Suspense boundaries with Kalshi-branded loading skeletons
   - Test initial load time (target: <2s)

2. **Replace polling with WebSocket for Kalshi high-frequency data**
   - Implement WebSocket for order fills (`/ws/fills`)
   - Implement WebSocket for agent status (`/ws/agents`)
   - Implement WebSocket for risk state (`/ws/risk`)
   - Implement WebSocket for Kalshi market data (`/ws/kalshi/markets`)
   - Add fallback to polling with exponential backoff
   - Remove polling from top 10 most-polling files

3. **Add intelligent polling hook**
   - Create `usePolling` with visibility detection
   - Create `useVisibility` hook for tab detection
   - Migrate remaining polling files to use intelligent polling
   - Test CPU usage reduction

4. **Set up observability dashboards**
   - Bundle size monitoring (webpack-bundle-analyzer)
   - Network request rate per user (Datadog/CloudWatch)
   - Key view load times (Overview, KalshiVolDashboardView, OperatorDashboard)
   - WebSocket connection health and fallback rate

**Concrete Success Criteria**:
- [ ] Initial bundle size reduced by 40% (2MB → 1.2MB)
- [ ] Network requests reduced by 50% on key screens (Overview, KalshiVolDashboardView)
- [ ] CPU usage reduced by 30% (idle)
- [ ] WebSocket connection success rate >95%
- [ ] Fallback to polling rate <5%

---

### Tier 2: Component Consolidation (Week 2-3)

**Priority**: HIGH  
**Impact**: Code maintainability + bundle size + UX clarity

1. **Define design tokens** (Week 2, Day 1-2)
   - Create KALSHI_STATUS_COLORS
   - Create SPACING tokens
   - Create TYPOGRAPHY tokens
   - Document token usage guidelines

2. **Consolidate indicator components** (Week 2, Day 3-4)
   - Define StatusIndicator API contract
   - Implement StatusIndicator with variants
   - Migrate all 5 indicator components
   - Delete 4 old components

3. **Consolidate badge components** (Week 2, Day 5)
   - Define Badge and DataBadge API contracts
   - Implement Badge and DataBadge
   - Migrate all 9 badge components
   - Delete 7 old components

4. **Consolidate panel components** (Week 3, Day 1-2)
   - Define DataPanel and AlertPanel API contracts
   - Implement DataPanel and AlertPanel
   - Migrate all 7 panel components
   - Delete 5 old components

5. **Consolidate chart components** (Week 3, Day 3-4)
   - Define TimeSeriesChart API contract
   - Implement TimeSeriesChart with Kalshi color schemes
   - Migrate all 4 chart components
   - Delete 3 old components

6. **UX testing** (Week 3, Day 5)
   - Verify consistent visual language
   - Test all component variants
   - Validate no per-screen color overrides

**Concrete Success Criteria**:
- [ ] Delete ~1700 lines of code
- [ ] Reduce component imports by 40%
- [ ] All components use design tokens (no hardcoded colors)
- [ ] Component API contracts documented and stable
- [ ] UX consistency validated across all Kalshi views
- [ ] Fewer visual variants (5 indicators → 1, 9 badges → 2, 7 panels → 2, 4 charts → 1)

---

### Tier 3: Hook Consolidation (Week 3-4)

**Priority**: MEDIUM  
**Impact**: Code maintainability + data consistency

1. **Create new unified hooks** (Week 3, Day 5 + Week 4, Day 1)
   - Implement `usePolling` with visibility detection and backoff
   - Implement `useVisibility` for tab detection
   - Implement `useDebounce` for input throttling
   - Implement `useThrottle` for update throttling

2. **Consolidate Kalshi hooks** (Week 4, Day 2)
   - Create `useKalshiData` (consolidates 8 Kalshi-specific hooks)
   - Migrate all Kalshi data fetching to useKalshiData
   - Ensure consistent loading/error handling
   - Delete 7 old Kalshi hooks

3. **Consolidate operator hooks** (Week 4, Day 3)
   - Create `useOperatorData` (consolidates 5 operator hooks)
   - Migrate all operator data fetching to useOperatorData
   - Ensure consistent loading/error handling
   - Delete 4 old operator hooks

4. **Consolidate debate hooks** (Week 4, Day 4)
   - Create `useDebateData` (consolidates 4 debate hooks)
   - Migrate all debate data fetching to useDebateData
   - Ensure consistent loading/error handling
   - Delete 3 old debate hooks

5. **Delete remaining redundant hooks** (Week 4, Day 5)
   - Delete 13 other redundant hooks
   - Update all imports
   - Test all data flows

**Concrete Success Criteria**:
- [ ] Delete ~1500 lines of code
- [ ] Reduce hook count from 39 → 12
- [ ] All data hooks follow consistent loading/error pattern
- [ ] No duplicate data fetching across components
- [ ] Kalshi data flow end-to-end verified

---

### Tier 4: View Restructuring (Week 4-5)

**Priority**: MEDIUM  
**Impact**: Code maintainability + file organization

1. **Define file structure standards** (Week 4, Day 5)
   - Document feature-based organization
   - Document co-location guidelines
   - Document data flow patterns
   - Update team coding standards

2. **Split Settings.tsx** (Week 5, Day 1)
   - Settings.tsx (200 lines) - layout and tab switching
   - PreferencesTab.tsx (250 lines) - user preferences
   - TradingTab.tsx (250 lines) - Kalshi trading settings
   - NotificationsTab.tsx (200 lines) - notification settings

3. **Split KalshiVolDashboardView.tsx** (Week 5, Day 2)
   - KalshiVolDashboardView.tsx (200 lines) - layout
   - AgentSizingGrid.tsx (250 lines) - agent sizing table
   - VolatilityChart.tsx (250 lines) - volatility visualization
   - RiskMetricsPanel.tsx (200 lines) - risk metrics display

4. **Split KalshiSentimentView.tsx** (Week 5, Day 3)
   - KalshiSentimentView.tsx (200 lines) - layout
   - SentimentChart.tsx (300 lines) - sentiment visualization
   - SentimentFeed.tsx (200 lines) - sentiment data feed

5. **Delete all legacy views** (Week 5, Day 4)
   - Delete all 11 legacy views from _legacy/
   - Update all imports
   - Test all routes

6. **Apply component size guidelines** (Week 5, Day 5)
   - Review all components for responsibility violations
   - Split any components managing >5 state or >3 useEffects
   - Add container/presentation splits where needed

**Concrete Success Criteria**:
- [ ] Delete ~3000 lines of code
- [ ] All views follow feature-based organization
- [ ] All components meet size guidelines (≤300 lines, ≤5 state, ≤3 useEffects)
- [ ] Container/presentation splits applied where appropriate
- [ ] File structure documented and team trained

---

### Tier 5: Final Polish (Week 5-6)

**Priority**: LOW  
**Impact**: UX refinement + mobile performance

1. **Add virtual scrolling** (Week 5, Day 5 + Week 6, Day 1)
   - Implement virtual scrolling for Kalshi agent grid (>100 rows)
   - Implement virtual scrolling for order history (>500 rows)
   - Implement virtual scrolling for alert history (>200 rows)
   - Use react-window or react-virtualized

2. **Implement skeleton loading** (Week 6, Day 2)
   - Add Kalshi-branded loading skeletons for all views
   - Add skeleton states for data fetching
   - Ensure smooth transitions from skeleton to content

3. **Add error boundaries** (Week 6, Day 3)
   - Add error boundaries to all 35 views
   - Add Kalshi-branded error states
   - Add retry mechanisms for failed loads

4. **Optimize animations** (Week 6, Day 4)
   - Replace JS animations with CSS transitions
   - Use transform/opacity for GPU acceleration
   - Reduce animation durations to <200ms

5. **Test on mobile devices** (Week 6, Day 5)
   - Test on iOS Safari
   - Test on Android Chrome
   - Validate responsive design
   - Test WebSocket behavior on mobile networks

**Concrete Success Criteria**:
- [ ] Virtual scrolling implemented for 3+ large lists
- [ ] Skeleton loading states for all views
- [ ] Error boundaries for all views with Kalshi-branded errors
- [ ] All animations use CSS transitions
- [ ] Mobile performance validated (load time <3s, smooth scrolling)

---

## Metrics & Success Criteria

### Before Redesign (Estimated)
- Initial bundle size: ~2MB
- Time to interactive: ~3s
- Network requests per minute: ~200
- CPU usage (idle): ~15%
- Component count: 70+
- Hook count: 39
- Lines of code: ~25,000

### After Redesign (Target)
- Initial bundle size: ~1MB (-50%)
- Time to interactive: ~1.5s (-50%)
- Network requests per minute: ~60 (-70%)
- CPU usage (idle): ~8% (-47%)
- Component count: ~35 (-50%)
- Hook count: 12 (-69%)
- Lines of code: ~17,000 (-32%)

**UX Outcomes (New)**:
- Fewer visual variants (5 indicators → 1, 9 badges → 2, 7 panels → 2, 4 charts → 1)
- Consistent patterns across all Kalshi views (design tokens)
- Fewer clicks to common tasks (unified panels, consolidated actions)
- Clearer visual hierarchy (status tokens, spacing tokens)
- Reduced cognitive load (single source of truth for each UI primitive)
- Faster task completion (lazy loading, virtual scrolling)
- Better mobile experience (responsive design, touch-optimized)

### Success Criteria (Per Phase)

**Week 1 (Tier 1)**:
- [ ] Initial bundle size reduced by 40% (2MB → 1.2MB)
- [ ] Network requests reduced by 50% on key screens
- [ ] CPU usage reduced by 30% (idle)
- [ ] WebSocket connection success rate >95%
- [ ] Observability dashboards operational

**Weeks 2-3 (Tier 2)**:
- [ ] Delete ~1700 lines of code
- [ ] Component imports reduced by 40%
- [ ] All components use design tokens
- [ ] Component API contracts documented
- [ ] UX consistency validated

**Weeks 3-4 (Tier 3)**:
- [ ] Delete ~1500 lines of code
- [ ] Hook count reduced from 39 → 12
- [ ] All data hooks follow consistent pattern
- [ ] No duplicate data fetching
- [ ] Kalshi data flow verified

**Weeks 4-5 (Tier 4)**:
- [ ] Delete ~3000 lines of code
- [ ] All views follow feature-based organization
- [ ] All components meet size guidelines
- [ ] File structure documented

**Weeks 5-6 (Tier 5)**:
- [ ] Virtual scrolling for 3+ large lists
- [ ] Skeleton loading for all views
- [ ] Error boundaries for all views
- [ ] CSS-only animations
- [ ] Mobile performance validated

**Overall**:
- [ ] No regressions in Kalshi trading functionality
- [ ] All existing tests passing
- [ ] User acceptance testing passed
- [ ] UX outcomes achieved (fewer variants, consistent patterns, fewer clicks)

---

## Risk Assessment

### Low Risk
- Component consolidation (internal refactoring)
- Hook consolidation (internal refactoring)
- Legacy view deletion (already unused)

### Medium Risk
- Route-based code splitting (may affect SEO, but not critical for internal Kalshi dashboard)
- WebSocket implementation (requires backend changes to Kalshi WebSocket endpoints)
- Intelligent polling (may affect data freshness if visibility detection fails)
- Virtual scrolling (may affect accessibility if not implemented correctly)

### High Risk
- None identified

**Guardrails & Mitigation Strategy**:
- **Feature flags**: Gradual rollout for WebSocket migration and virtual scroll
- **Observability**: 
  - Bundle size monitoring (webpack-bundle-analyzer)
  - Network request rate per user (Datadog/CloudWatch)
  - Key view load times (Overview, KalshiVolDashboardView, OperatorDashboard)
  - WebSocket connection health and fallback rate
  - Error monitoring around new WebSocket flows and lazy-loaded routes
- **Rollback plan**: Each tier has documented rollback procedure
- **Monitoring**: Closely monitor metrics post-deployment for 48 hours
- **Testing**: Extensive testing before each tier deployment
- **Canary**: Deploy to subset of users first for WebSocket migration

---

## File Structure Standards

### Feature-Based Organization
```
src/
├── kalshi/
│   ├── trading/
│   │   ├── components/      # Trading-specific components
│   │   ├── hooks/           # Trading data hooks
│   │   ├── views/           # Trading views
│   │   └── utils/           # Trading utilities
│   ├── risk/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── views/
│   │   └── utils/
│   └── monitoring/
│       ├── components/
│       ├── hooks/
│       ├── views/
│       └── utils/
├── ui/
│   ├── primitives/         # Design system primitives (Badge, StatusIndicator, etc.)
│   ├── tokens.ts           # Design tokens (colors, spacing, typography)
│   └── icons/              # Icon library
└── shared/
    ├── hooks/             # Shared hooks (useApiData, useLocalStorage)
    └── utils/             # Shared utilities
```

### Co-Location Guidelines
- Keep related components, hooks, and styles in the same feature folder
- Example: `kalshi/trading/components/KalshiTradeTicket.tsx` with `kalshi/trading/hooks/useKalshiOrderData.ts`
- Avoid cross-feature imports (use shared folder for common utilities)

### Data Flow Patterns
- **All data hooks** must return: `{ data, loading, error, refetch, lastUpdated }`
- **Loading state**: Show Kalshi-branded skeleton
- **Error state**: Show Kalshi-branded error with retry button
- **Empty state**: Show Kalshi-branded empty state with action
- **Consistent naming**: `use[Domain][Data]` (e.g., `useKalshiBalance`, `useAgentStatus`)

---

## Next Steps

1. **Review this plan** with Kalshi product and engineering teams
2. **Get approval** for implementation and timeline
3. **Start Tier 1** (critical performance fixes)
4. **Measure impact** after each tier against concrete success criteria
5. **Adjust plan** based on results and metrics
6. **Complete all tiers** within 6 weeks
7. **Document lessons learned** for future refactoring initiatives

---

## Appendix: Detailed Component Mapping

### Indicator Components
| Current | Target | Lines | Notes |
|---------|--------|-------|-------|
| StatusIndicator | StatusIndicator | Keep | Base component |
| DataFreshnessIndicator | StatusIndicator (variant) | Delete | Merged |
| StalenessIndicator | StatusIndicator (variant) | Delete | Merged |
| OfflineIndicator | StatusIndicator (variant) | Delete | Merged |
| ConnectionStatusIndicator | StatusIndicator (variant) | Delete | Merged |

### Badge Components
| Current | Target | Lines | Notes |
|---------|--------|-------|-------|
| Badge (ui/common.tsx) | Badge | Keep | Generic |
| Badge (ui/Badge.tsx) | Badge | Delete | Duplicate |
| DataAgeBadge | DataBadge | Delete | Merged |
| DataSourceBadge | DataBadge | Delete | Merged |
| OrderLineageBadge | DataBadge | Delete | Merged |
| KalshiReconciliationBadge | DataBadge | Delete | Merged |
| DebateStatusBadge | Badge | Delete | Merged |
| RegimeBadge | Badge | Delete | Merged |
| ConnectionStatusBadge | Badge | Delete | Merged |

### Panel Components
| Current | Target | Lines | Notes |
|---------|--------|-------|-------|
| AlertHistoryPanel | AlertPanel | Keep | Base |
| ContractHealthPanel | DataPanel | Delete | Merged |
| CryptoAlertStatusPanel | DataPanel | Delete | Merged |
| NotificationStatusPanel | DataPanel | Delete | Merged |
| RiskProtectionsPanel | DataPanel | Delete | Merged |
| SessionLogPanel | DataPanel | Delete | Merged |
| SocialAdvisoryPanel | DataPanel | Delete | Merged |

### Chart Components
| Current | Target | Lines | Notes |
|---------|--------|-------|-------|
| KalshiPnlChart | TimeSeriesChart | Keep | Base |
| PortfolioChart | TimeSeriesChart | Delete | Merged |
| DomainPnLChart | TimeSeriesChart | Delete | Merged |
| DrawdownChart | TimeSeriesChart | Delete | Merged |

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-11  
**Status**: Draft for Review
