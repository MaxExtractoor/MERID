# MERID UI Facelift Plan
**Date:** 2026-07-02  
**Scope:** Comprehensive frontend facelift for 15-minute Kalshi crypto trading system  
**Status:** Ready for Implementation

---

## Executive Summary

This plan outlines a systematic approach to modernizing the MERID UI-UX for the 15-minute Kalshi crypto trading system (BTC, ETH, SOL, XRP, DOGE). The plan addresses critical gaps, implements 2026 best practices, and leverages modern component libraries while keeping the backend fully intact.

**Key Objectives:**
- Complete the 8-view architecture (3 of 8 views are placeholders)
- Achieve full 5-asset coverage across all views
- Fix 19 critical UX bugs identified in audit
- Implement 2026 trading UI best practices
- Modernize component library with shadcn/ui
- Enhance real-time data visualization

**Estimated Timeline:** 8-10 weeks  
**Risk Level:** Medium (backend remains unchanged)

---

## 1. Design System Foundation

### 1.1 Color System

**Current Issue:** Inconsistent color usage, single color scale for both themes

**2026 Best Practice:** Two color scales for same semantic role (one for dark, one for light)

**Implementation:**
```css
/* Dark mode (default) */
:root {
  --bg-void: #0a0a0a;      /* Page background */
  --bg-primary: #111111;    /* Main app shell */
  --bg-secondary: #161616;  /* Cards, panels */
  --bg-surface: #1c1c1c;    /* Hover states, popovers */
  
  /* Semantic colors - dark mode */
  --green: #22c55e;         /* Vivid for dark mode */
  --red: #ef4444;           /* Vivid for dark mode */
  --warning: #f59e0b;
  --info: #3b82f6;
}

/* Light mode (override) */
[data-theme="light"] {
  --bg-void: #fafafa;
  --bg-primary: #ffffff;
  --bg-secondary: #f5f5f7;
  --bg-surface: #f0f0f2;
  
  /* Semantic colors - one notch darker for light mode */
  --green: #16a34a;         /* Darker to match perceptual weight */
  --red: #dc2626;           /* Darker to match perceptual weight */
  --warning: #d97706;
  --info: #2563eb;
}
```

**Accessibility Enhancement:**
- Add secondary indicators for color-blind users (arrows, icons, typographic treatments)
- Maintain WCAG 2.1 AA contrast ratio (4.5:1 minimum)
- Test with color-blind simulation tools

### 1.2 Typography

**Current Issue:** Single font, inconsistent sizing

**2026 Best Practice:** Two fonts - sans-serif for UI, monospace for numbers

**Implementation:**
```css
/* Font families */
--font-sans: 'Inter', system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', monospace;

/* Type scale */
--text-xs: 0.75rem;    /* 12px */
--text-sm: 0.875rem;   /* 14px */
--text-base: 1rem;     /* 16px */
--text-lg: 1.125rem;   /* 18px */
--text-xl: 1.25rem;    /* 20px */
--text-2xl: 1.5rem;    /* 24px */
--text-3xl: 1.875rem;  /* 30px */

/* Number formatting */
.tabular-nums {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
```

**Usage:**
- Sans-serif for labels, headings, body text
- Monospace with `tabular-nums` for all numbers (prices, quantities, P&L)
- Prevents digit jitter on real-time updates

### 1.3 Elevation System

**Current Issue:** Two-step elevation insufficient for dark mode

**2026 Best Practice:** Four-step elevation for dark mode

**Implementation:**
```css
/* Four-step elevation for dark mode */
--elevation-0: #0a0a0a;  /* Page background */
--elevation-1: #111111;  /* Main app shell */
--elevation-2: #161616;  /* Cards, panels */
--elevation-3: #1c1c1c;  /* Hover states, popovers */

/* Subtle borders for additional definition */
--border-subtle: rgba(255, 255, 255, 0.06);
```

**Component Mapping:**
- Elevation 0: Page background
- Elevation 1: Sidebar, top bar
- Elevation 2: Cards, panels, tables
- Elevation 3: Modals, dropdowns, tooltips

### 1.4 Spacing System

**Implementation:**
```css
--space-1: 0.25rem;   /* 4px */
--space-2: 0.5rem;    /* 8px */
--space-3: 0.75rem;   /* 12px */
--space-4: 1rem;      /* 16px */
--space-5: 1.25rem;   /* 20px */
--space-6: 1.5rem;    /* 24px */
--space-8: 2rem;      /* 32px */
--space-10: 2.5rem;   /* 40px */
--space-12: 3rem;     /* 48px */
```

---

## 2. Component Library Migration

### 2.1 Current Stack Assessment

**Current Components:**
- Custom components (148 total)
- Tailwind CSS v3
- Lucide React icons
- Recharts for charts
- Zustand for state

**Issues:**
- Inconsistent component patterns
- No unified design system
- Accessibility gaps
- Duplicate components

### 2.2 Migration Strategy: shadcn/ui

**Why shadcn/ui:**
- Copy-paste model for full code ownership
- Built with Radix UI primitives (accessibility-first)
- Tailwind CSS v4 native
- AI-agent ready with CLI v4
- Growing ecosystem (97.9k+ GitHub stars)
- Zero runtime style overhead

**Migration Plan:**

**Phase 1: Core Primitives (Week 1-2)**
- Button
- Input
- Card
- Badge
- Separator
- Skeleton
- Alert
- Dialog (ConfirmModal replacement)

**Phase 2: Form Components (Week 3)**
- Select
- Checkbox
- Radio Group
- Switch
- Slider
- Form validation

**Phase 3: Data Display (Week 4)**
- Table
- Tabs
- Accordion
- Collapsible
- Tooltip
- Popover

**Phase 4: Navigation (Week 5)**
- Sidebar (refactor existing)
- Command Palette (enhance existing)
- Breadcrumb
- Pagination

**Phase 5: Complex Components (Week 6)**
- Data Table (virtualized)
- Date Picker
- Rich Select

### 2.3 Component Retirement

**Components to Remove:**
- Legacy HTML templates (web/templates/)
- Duplicate components (consolidate)
- Unused custom components

**Components to Enhance:**
- KalshiTradeTicket → shadcn/ui Form + custom logic
- KalshiOrderbookPanel → shadcn/ui Table + virtualization
- KalshiRiskFeed → shadcn/ui Alert + streaming logic

---

## 3. View Completion Plan

### 3.1 Trade View (Priority: P0)

**Current Status:** Partial - market discovery is placeholder

**Implementation:**

**Week 1: Market Discovery**
```typescript
// Integrate Kalshi market catalog API
const { data: markets } = useQuery({
  queryKey: ['kalshi-markets'],
  queryFn: () => fetch('/api/v1/kalshi/markets').then(r => r.json()),
  staleTime: 30000, // 30 seconds
});

// Filter for 15m crypto markets
const crypto15mMarkets = markets?.filter(m => 
  m.asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'] && 
  m.timeframe === '15m'
);
```

**Week 2: Order Entry**
- Integrate KalshiTradeTicket component
- Add order form with validation
- Add edge calculation display
- Add order preview

**Week 3: Order Management**
- Add orders table with status
- Add cancel order functionality
- Add cancel all with confirmation
- Add order history

**Week 4: Orderbook**
- Integrate KalshiOrderbookPanel
- Add real-time depth updates
- Add price level visualization

### 3.2 Monitor View (Priority: P1)

**Current Status:** Partial - missing fills integration and PnL chart

**Implementation:**

**Week 1: Fills Integration**
```typescript
// Integrate fills from store
const fills = useKalshiStore(state => state.portfolio.fills);

// Add fills table with columns:
// - Timestamp
// - Market
// - Side
// - Quantity
// - Price
// - Fee
// - PnL
```

**Week 2: PnL Chart**
- Add equity curve chart using Recharts
- Add timeframe selector (1D, 1W, 1M, ALL)
- Add interactive tooltip with hover details
- Add performance metrics (Sharpe, Sortino, Calmar)

**Week 3: Performance Metrics**
- Add win rate display
- Add profit factor
- Add average win/loss
- Add drawdown visualization

### 3.3 Calibration View (Priority: P1)

**Current Status:** Complete placeholder

**Implementation:**

**Week 1: Agent Calibration Metrics**
```typescript
// Fetch calibration data
const { data: calibration } = useQuery({
  queryKey: ['calibration'],
  queryFn: () => fetch('/api/v1/calibration/metrics').then(r => r.json()),
});
```

**Week 2: Brier Scores**
- Add Brier score chart per agent
- Add rolling Brier score
- Add calibration history

**Week 3: Consensus Weights**
- Add consensus weight visualization
- Add forecaster performance table
- Add weight adjustment controls

**Week 4: Calibration History**
- Add historical calibration chart
- Add calibration event timeline
- Add calibration export

### 3.4 Logs View (Priority: P1)

**Current Status:** Complete placeholder

**Implementation:**

**Week 1: Log Viewer**
- Add log table with columns:
  - Timestamp
  - Level (info, warning, error)
  - Component
  - Message
- Add virtualization for 1000+ entries
- Add auto-scroll to latest

**Week 2: Filtering**
- Add level filter (info, warning, error)
- Add component filter
- Add search functionality
- Add time range selector

**Week 3: Activity Stream**
- Add activity timeline
- Add event grouping
- Add activity export

### 3.5 Settings View (Priority: P2)

**Current Status:** Partial - tabs exist but not wired

**Implementation:**

**Week 1: Backend Integration**
- Wire AgentsTab to `/api/v1/agents/config`
- Wire TradingSettingsTab to `/api/v1/trading/config`
- Wire RiskTab to `/api/v1/risk/config`
- Wire PreferencesTab to `/api/v1/user/preferences`
- Wire NotificationSettingsTab to `/api/v1/notifications/config`

**Week 2: Configuration Persistence**
- Add save functionality
- Add validation
- Add reset to defaults
- Add configuration export/import

**Week 3: 15m-Specific Settings**
- Add 15m profile selection
- Add asset-specific settings
- Add timeframe configuration
- Add kill switch configuration

---

## 4. 15m Stack Coverage Enhancement

### 4.1 DOGE Integration

**Current Gap:** DOGE missing from CryptoLanesGrid filter

**Fix:**
```typescript
// Update CryptoLanesGrid.tsx
const cryptoLanes = useMemo(() => {
  if (!apiData?.lanes) return [];
  
  return apiData.lanes.filter(lane =>
    lane.lane_id.endsWith("_15M") || 
    lane.lane_id.endsWith("_15M_PAPER")
  );
}, [apiData]);

// Add DOGE to asset metadata
const ASSET_META: Record<string, { color: string; icon: string }> = {
  BTC: { color: "text-orange-400", icon: "₿" },
  ETH: { color: "text-blue-400", icon: "Ξ" },
  SOL: { color: "text-purple-400", icon: "◎" },
  XRP: { color: "text-green-400", icon: "✕" },
  DOGE: { color: "text-yellow-400", icon: "Ð" },
};
```

### 4.2 Per-Asset Metrics

**Dashboard Enhancement:**
- Add per-asset PnL cards (BTC, ETH, SOL, XRP, DOGE)
- Add per-asset position counts
- Add per-asset exposure display
- Add per-asset performance metrics

**Monitor Enhancement:**
- Add per-asset positions table
- Add per-asset fills table
- Add per-asset PnL chart

**Risk Enhancement:**
- Add per-asset risk limits
- Add per-asset exposure tracking
- Add per-asset drawdown display

### 4.3 15m Component Integration

**Dashboard Integration:**
```typescript
// Add to Dashboard.tsx
import { 
  Kalshi15mAlignmentPanel, 
  Kalshi15mHealthPanel 
} from '../components';

// Add 15m status section
<section className="space-y-4">
  <Kalshi15mAlignmentPanel />
  <Kalshi15mHealthPanel />
</section>
```

**Grid Integration:**
- Add 15m agent matrix visualization
- Add per-asset agent status
- Add 15m deployment controls

**Risk Integration:**
- Add 15m-specific risk metrics
- Add 15m kill switch controls
- Add 15m risk alerts

---

## 5. Critical Bug Fixes

### 5.1 P0 Bugs (Money-at-Risk)

**C-01: ConfirmModal State Persistence**
```typescript
// Fix: Add key prop to force remount
<ConfirmModal 
  key={`confirm-${action}-${timestamp}`}
  isOpen={isOpen}
  onConfirm={onConfirm}
  onCancel={onCancel}
/>
```

**C-02: Trade Ticket Double-Submit**
```typescript
// Fix: Add submit guard
const [isSubmitting, setIsSubmitting] = useState(false);

const handleSubmit = async () => {
  if (isSubmitting) return;
  setIsSubmitting(true);
  try {
    await submitOrder();
  } finally {
    setIsSubmitting(false);
  }
};

<button 
  onClick={handleSubmit}
  disabled={isSubmitting}
>
  {isSubmitting ? 'Submitting...' : 'Submit Order'}
</button>
```

**C-03: Kill Switch Optimistic Locking**
```typescript
// Fix: Add debounce and optimistic lock
import { useDebouncedCallback } from 'use-debounce';

const toggleKillSwitch = useDebouncedCallback(async () => {
  if (isToggling) return;
  setIsToggling(true);
  try {
    await fetch('/api/v1/kalshi/kill-switch', { method: 'POST' });
  } finally {
    setIsToggling(false);
  }
}, 500);
```

### 5.2 P1 Bugs (Broken State)

**H-01: Hash Routing in PositionsView**
```typescript
// Fix: Use React Router instead of hash routing
import { useNavigate } from 'react-router-dom';

const navigate = useNavigate();

const handleViewDecision = (positionId: string) => {
  navigate(`/positions/${positionId}`);
};
```

**H-02: Agent Focus Clearing**
```typescript
// Fix: Only clear if agent is found
const setAgentFocus = (agentId: string) => {
  const agent = agents.find(a => a.id === agentId);
  if (agent) {
    setFocusedAgent(agentId);
  }
};
```

**H-03: WebSocket Reconnection**
```typescript
// Fix: Add URL/token change detection
useEffect(() => {
  if (wsUrl !== currentUrlRef.current) {
    currentUrlRef.current = wsUrl;
    reconnect();
  }
}, [wsUrl]);
```

**H-05: Double-Fetching**
```typescript
// Fix: Disable initial fetch when polling
const { data } = useQuery({
  queryKey: ['data'],
  queryFn: fetchData,
  refetchInterval: 10000,
  enabled: !isPolling, // Disable initial fetch when polling
});
```

### 5.3 P2 Bugs (Degraded UX)

**M-01: Cancel Order Refetch**
```typescript
// Fix: Await refetch before re-enabling
const handleCancelOrder = async (orderId: string) => {
  setIsCancelling(true);
  try {
    await cancelOrder(orderId);
    await refetch(); // Wait for refetch
  } finally {
    setIsCancelling(false);
  }
};
```

**M-03: Escape Key Handling**
```typescript
// Fix: Auto-focus on open
useEffect(() => {
  if (isOpen) {
    buttonRef.current?.focus();
  }
}, [isOpen]);
```

---

## 6. Real-Time Data Enhancement

### 6.1 WebSocket Improvements

**Current Issues:**
- Reconnection doesn't detect URL/token changes
- No staleness indicators
- No connection state visualization

**Enhancements:**

**Connection State Indicator:**
```typescript
const ConnectionStatus = () => {
  const { status, lastUpdate } = useWebSocket();
  
  const isStale = Date.now() - lastUpdate > 5000;
  
  return (
    <div className={cn(
      "flex items-center gap-2",
      status === 'connected' && !isStale ? "text-green-400" : "text-red-400"
    )}>
      <div className={cn(
        "w-2 h-2 rounded-full",
        status === 'connected' && !isStale ? "bg-green-400 animate-pulse" : "bg-red-400"
      )} />
      <span className="text-xs">
        {status === 'connected' && !isStale ? 'Live' : 'Disconnected'}
      </span>
      {isStale && <span className="text-xs text-yellow-400">(Stale)</span>}
    </div>
  );
};
```

**Tick Flash Animation:**
```typescript
const TickFlash = ({ value, previousValue }: { value: number; previousValue: number }) => {
  const isUp = value > previousValue;
  const isDown = value < previousValue;
  
  return (
    <span className={cn(
      "transition-colors duration-200",
      isUp && "text-green-400 flash-green",
      isDown && "text-red-400 flash-red"
    )}>
      {value}
    </span>
  );
};
```

### 6.2 Data Throttling

**Current Issue:** UI updates on every micro-change

**Fix:**
```typescript
// Throttle UI updates to 60fps
import { useThrottledValue } from './hooks/useThrottledValue';

const throttledValue = useThrottledValue(liveValue, 16); // 16ms = ~60fps
```

### 6.3 Staleness Chain

**Implementation:**
```typescript
// Real-time → Delayed → Stale chain
const DataFreshness = ({ timestamp }: { timestamp: number }) => {
  const age = Date.now() - timestamp;
  
  if (age < 1000) return <Badge variant="success">Live</Badge>;
  if (age < 5000) return <Badge variant="warning">Delayed</Badge>;
  return <Badge variant="danger">Stale</Badge>;
};
```

---

## 7. Chart Library Enhancement

### 7.1 Current Stack

**Current:** Recharts v2

**Issues:**
- Limited real-time performance
- No candlestick support
- No drawing tools

### 7.2 Enhancement Strategy

**Option 1: Keep Recharts + Add react-candlesticks**
- Pros: Familiar API, lightweight
- Cons: Two chart libraries

**Option 2: Migrate to lightweight-charts**
- Pros: Best performance, TradingView-proven
- Cons: Not React-native, requires wrapper

**Option 3: Migrate to @mg-exchange/charts**
- Pros: Built for trading, 21 indicators, 47 drawing tools
- Cons: Newer library, smaller ecosystem

**Recommendation:** Option 2 - lightweight-charts with React wrapper

**Implementation:**
```typescript
import { createChart, IChartApi, ISeriesApi } from 'lightweight-charts';
import { useEffect, useRef } from 'react';

const TradingChart = ({ data }: { data: CandleData[] }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  
  useEffect(() => {
    if (!chartContainerRef.current) return;
    
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: 'solid', color: '#0a0a0a' },
        textColor: '#ffffff',
      },
      grid: {
        vertLines: { color: '#1c1c1c' },
        horzLines: { color: '#1c1c1c' },
      },
    });
    
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });
    
    candlestickSeries.setData(data);
    
    chartRef.current = chart;
    
    return () => {
      chart.remove();
    };
  }, [data]);
  
  return <div ref={chartContainerRef} style={{ height: 400 }} />;
};
```

---

## 8. State Management Optimization

### 8.1 Current Stack

**Current:** Zustand with 4 slices (portfolio, risk, grid, system)

**Assessment:** Good choice for 2026

**Why Zustand Wins in 2026:**
- Tiny (1.2 KB gzipped)
- Zero boilerplate
- Selectors out of the box
- Works with React concurrent features
- Only re-renders when subscribed slice changes

### 8.2 Enhancement: Add TanStack Query

**Current Issue:** Server state mixed with client state

**Solution:** Add TanStack Query for server state

**Implementation:**
```typescript
// Keep Zustand for client state (UI state, user preferences)
const useUIStore = create<UIStore>((set) => ({
  sidebarCollapsed: false,
  currentView: 'dashboard',
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
  setCurrentView: (view) => set({ currentView: view }),
}));

// Use TanStack Query for server state (portfolio, risk, grid)
const usePortfolio = () => {
  return useQuery({
    queryKey: ['portfolio'],
    queryFn: () => fetch('/api/v1/kalshi/positions').then(r => r.json()),
    staleTime: 5000,
    refetchInterval: 10000,
  });
};

const useRisk = () => {
  return useQuery({
    queryKey: ['risk'],
    queryFn: () => fetch('/api/v1/risk/metrics').then(r => r.json()),
    staleTime: 5000,
    refetchInterval: 10000,
  });
};
```

**Benefits:**
- Automatic caching
- Background refetching
- Optimistic updates
- Loading/error states handled
- No stale data issues

---

## 9. Accessibility Enhancement

### 9.1 Current Gaps

- Red/green-only signals (color-blind unsafe)
- Missing ARIA labels
- Inconsistent keyboard navigation
- No screen reader support

### 9.2 Enhancements

**Color-Blind Safety:**
```typescript
// Add secondary indicators
const PnLDisplay = ({ value }: { value: number }) => (
  <div className={cn(
    "flex items-center gap-2",
    value >= 0 ? "text-green-400" : "text-red-400"
  )}>
    {value >= 0 ? <ArrowUp className="w-4 h-4" /> : <ArrowDown className="w-4 h-4" />}
    <span className="tabular-nums">{value.toFixed(2)}</span>
  </div>
);
```

**Keyboard Navigation:**
```typescript
// Add keyboard shortcuts
useEffect(() => {
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.ctrlKey && e.key === 'r') {
      e.preventDefault();
      refreshAll();
    }
    if (e.key === 'Escape') {
      closeModal();
    }
  };
  
  window.addEventListener('keydown', handleKeyDown);
  return () => window.removeEventListener('keydown', handleKeyDown);
}, []);
```

**ARIA Labels:**
```typescript
<button
  aria-label="Cancel order for {ticker}"
  onClick={() => cancelOrder(orderId)}
>
  Cancel
</button>
```

---

## 10. Mobile Responsiveness

### 10.1 Current State

**Issues:**
- Desktop-first design
- No mobile-specific layouts
- Touch targets too small

### 10.2 Mobile Strategy

**Drawer Pattern:**
```typescript
// Click row → drawer slides in from right
const RowDetailDrawer = ({ row, isOpen, onClose }: Props) => (
  <Drawer isOpen={isOpen} onClose={onClose}>
    <DrawerContent>
      <DetailPanel data={row} />
    </DrawerContent>
  </Drawer>
);
```

**Mobile Navigation:**
- Bottom navigation bar (persistent)
- Hamburger menu for secondary views
- Swipe gestures for navigation

**Touch Targets:**
```css
/* Minimum 44x44px touch targets */
.touch-target {
  min-width: 44px;
  min-height: 44px;
}
```

**Responsive Tables:**
- Collapse to cards on mobile
- Horizontal scroll for complex tables
- Virtualization for large datasets

---

## 11. Implementation Timeline

### Phase 1: Foundation (Week 1-2)
- Design system implementation (colors, typography, spacing)
- shadcn/ui core primitives migration
- Critical bug fixes (P0)

### Phase 2: Trade View (Week 3-4)
- Market discovery integration
- Order entry implementation
- Order management
- Orderbook integration

### Phase 3: Monitor & Calibration (Week 5-6)
- Monitor view completion (fills, PnL chart)
- Calibration view implementation
- Logs view implementation

### Phase 4: 15m Coverage (Week 7)
- DOGE integration
- Per-asset metrics
- 15m component integration

### Phase 5: Polish (Week 8-10)
- Settings view wiring
- Accessibility enhancements
- Mobile responsiveness
- Performance optimization
- Testing

---

## 12. Testing Strategy

### 12.1 Unit Tests

**Components:**
- Test all shadcn/ui components
- Test custom components
- Test utility functions

**Hooks:**
- Test custom hooks
- Test WebSocket hooks
- Test data fetching hooks

### 12.2 Integration Tests

**API Integration:**
- Test all API endpoints
- Test WebSocket connections
- Test error handling

**State Management:**
- Test Zustand store
- Test TanStack Query caching
- Test optimistic updates

### 12.3 E2E Tests

**Critical Flows:**
- Order placement
- Kill switch activation
- Agent grid start/stop
- Navigation between views

### 12.4 Accessibility Tests

**Automated:**
- axe-core for accessibility violations
- Lighthouse for accessibility score

**Manual:**
- Keyboard navigation
- Screen reader testing
- Color-blind simulation

---

## 13. Performance Optimization

### 13.1 Bundle Size

**Current Issues:**
- Large bundle size
- Unused components

**Optimizations:**
- Code splitting by route
- Tree shaking
- Dynamic imports for heavy components
- Remove unused dependencies

### 13.2 Render Performance

**Current Issues:**
- Unnecessary re-renders
- No virtualization

**Optimizations:**
- React.memo for expensive components
- Virtualization for large lists (react-window)
- Throttle/debounce updates
- Optimistic updates

### 13.3 Network Performance

**Current Issues:**
- No request deduplication
- No caching strategy

**Optimizations:**
- TanStack Query for caching
- Request deduplication
- WebSocket for real-time data
- HTTP/2 for API calls

---

## 14. Migration Checklist

### Pre-Migration
- [ ] Backup current codebase
- [ ] Create feature branch
- [ ] Set up staging environment
- [ ] Document current state

### Migration
- [ ] Implement design system
- [ ] Migrate to shadcn/ui
- [ ] Complete Trade view
- [ ] Complete Monitor view
- [ ] Complete Calibration view
- [ ] Complete Logs view
- [ ] Wire Settings view
- [ ] Add DOGE coverage
- [ ] Fix critical bugs
- [ ] Add TanStack Query
- [ ] Enhance charts

### Post-Migration
- [ ] Run all tests
- [ ] Performance testing
- [ ] Accessibility testing
- [ ] User acceptance testing
- [ ] Deploy to staging
- [ ] Monitor for issues
- [ ] Deploy to production

---

## 15. Success Metrics

### 15.1 Coverage Metrics

- [ ] All 8 views fully implemented
- [ ] All 5 assets (BTC, ETH, SOL, XRP, DOGE) covered
- [ ] All 19 critical bugs fixed
- [ ] 100% accessibility compliance (WCAG 2.1 AA)

### 15.2 Performance Metrics

- [ ] Bundle size < 500KB (gzipped)
- [ ] First Contentful Paint < 1s
- [ ] Time to Interactive < 3s
- [ ] Lighthouse score > 90

### 15.3 User Experience Metrics

- [ ] Task completion rate > 95%
- [ ] User satisfaction score > 4.5/5
- [ ] Error rate < 1%
- [ ] Session duration increase > 20%

---

## 16. Risks and Mitigations

### 16.1 Risk: Breaking Changes

**Mitigation:**
- Feature flags for new features
- Gradual rollout
- A/B testing
- Rollback plan

### 16.2 Risk: Performance Regression

**Mitigation:**
- Performance testing before deployment
- Monitoring in production
- Performance budgets
- Optimization sprints

### 16.3 Risk: User Adoption

**Mitigation:**
- User training
- Documentation
- Support during transition
- Feedback collection

---

## 17. Conclusion

This facelift plan provides a comprehensive roadmap for modernizing the MERID UI-UX while keeping the backend fully intact. The plan addresses critical gaps, implements 2026 best practices, and leverages modern component libraries.

**Key Benefits:**
- Complete 8-view architecture
- Full 5-asset coverage
- Modern, accessible UI
- Improved performance
- Better developer experience

**Next Steps:**
1. Review and approve plan
2. Set up staging environment
3. Begin Phase 1 implementation
4. Weekly progress reviews
5. Deploy to production after testing

---

**Plan Created:** 2026-07-02  
**Author:** Cascade AI Assistant  
**Status:** Ready for Review
