# Kalshi UI Inventory & Classification

**Date:** 2026-05-12  
**Purpose:** State-and-UX simplification project - Phase 0 inventory

---

## Executive Summary

- **Total Kalshi-specific components:** 30
- **Total Kalshi views:** 3 dedicated + 4 integrated (Overview, OperatorDashboard, ProtectView, SizeView, PromoteView)
- **Total Kalshi API endpoints:** 100+
- **Current state:** Fragmented across multiple views with duplicated data fetching patterns

---

## Classification Framework

- **ESSENTIAL:** Core operational state needed for trading decisions (live status, recent events, errors, fills, actionable controls)
- **USEFUL LATER:** Analytics, historical data, advanced features (can be deferred to drill-down)
- **DUPLICATED:** Redundant displays of same data across multiple views
- **DEAD:** Unused components, stale features, deprecated endpoints

---

## Component Inventory

### ESSENTIAL (10 components)

| Component | Purpose | Data Flow | Notes |
|-----------|---------|-----------|-------|
| `KalshiModeBadge` | Trading mode indicator (PAPER/SHADOW/LIVE) | `KALSHI_GRID_MODE` | Used in all Kalshi views - single source of truth |
| `ExecutionGateStrip` | Execution gate status (CLEAR/LIMITED/BLOCKED) | `SYSTEM_EXECUTION_GATE` | Critical safety signal - shown in all views |
| `KalshiBankrollPanel` | Bankroll, equity, drawdown, PnL | `KALSHI_SIZING_METRICS` + `KALSHI_CONTINUOUS_TRADER_STATUS` | Capital state - essential for risk decisions |
| `KalshiTradeTicket` | Manual order entry (YES/NO, size, limit price) | `KALSHI_MARKET_DETAIL` + paper trading API | Action control - operator needs for manual trades |
| `KalshiCancelAllButton` | Emergency cancel all orders | `KALSHI_ORDERS_BATCH_CANCEL` | Safety control - critical for risk management |
| `KalshiRiskFeed` | Live risk alerts and breach notifications | `RISK_ALERTS` + `KALSHI_RISK_EVENTS` | Real-time risk monitoring |
| `KalshiOrderbookPanel` | Market depth and pricing | `KALSHI_ORDERBOOK` + WS stream | Market state for trading decisions |
| `KalshiLiquidityBadge` | Liquidity quality indicator | `KALSHI_LIQUIDITY_HEALTH` | Market quality signal |
| `KalshiReconciliationBadge` | Reconciliation status (OK/DISCREPANCY) | `RECONCILIATION_STATUS` | Data integrity check |
| `KalshiErrorPill` | Error state display | Derived from API responses | Error visibility for troubleshooting |

### USEFUL LATER (12 components)

| Component | Purpose | Data Flow | Notes |
|-----------|---------|-----------|-------|
| `KalshiPnlChart` | Historical PnL equity curve | `KALSHI_PNL_HISTORY` | Analytics - defer to detail drawer |
| `KalshiInsightsPanel` | AI-generated trading insights | `KALSHI_INSIGHTS` + `KALSHI_RISK_INSIGHTS` | Advisory - nice to have, not critical |
| `KalshiCryptoRtiPanel` | Real-time crypto RTI data | `KALSHI_CRYPTO_RTI` | Market context - useful for analysis |
| `KalshiCryptoSignalsPanel` | Crypto trading signals | `XTF_SIGNALS_ALL` + sentiment APIs | Signal aggregation - analytics |
| `KalshiExecutionTelemetryPanel` | Order execution metrics | `KALSHI_EXECUTION_TELEMETRY` | Performance analysis - defer |
| `KalshiPaperVsShadowPanel` | Paper vs shadow comparison | Deployment comparison endpoints | A/B testing - not operational |
| `KalshiActivityLog` | Activity event log | Derived from fills/orders | Audit trail - troubleshooting view |
| `KalshiCredentialsCard` | Credential management | Settings APIs | Configuration - infrequent use |
| `KalshiLoadingSkeleton` | Loading state placeholder | N/A | UX polish - keep but not essential |
| `KalshiErrorBoundary` | Error boundary for React tree | N/A | Stability - keep |
| `KalshiModeContext` | Mode context provider | N/A | State management - keep |
| `PublishPipelinePanel` | Pipeline publish controls | `KALSHI_PUBLISH_PIPELINE` | Dev workflow - not operational |

### DUPLICATED (5 components)

| Component | Duplicates | Notes |
|-----------|------------|-------|
| `KalshiModeBadge` | Shown in: Overview, KalshiVolDashboardView, KalshiAgentPerformanceView, KalshiSentimentView, ProtectView, SizeView, PromoteView | Should be single instance in header |
| `ExecutionGateStrip` | Shown in: Overview, KalshiVolDashboardView, KalshiAgentPerformanceView, KalshiSentimentView | Should be single global strip |
| `KalshiBankrollPanel` | Shown in: KalshiVolDashboardView, KalshiPortfolioView, KalshiRiskScreen, KalshiTerminalView | Should be single panel with drill-down |
| Balance/PnL displays | Overview hero, OperatorDashboard metrics, SizeView bankroll tab | Multiple implementations of same data |
| Agent status tables | KalshiVolDashboardView agent sizing grid, KalshiGridView health tab, PromoteView agent grid | Duplicated agent status rendering |

### DEAD / STALE (3 components)

| Component | Reason | Action |
|-----------|---------|--------|
| `KalshiPaperVsShadowPanel` | Paper/shadow comparison not used in live ops | Remove or archive |
| `KalshiCredentialsCard` | Credential management should be in settings only | Move to Settings view |
| `PublishPipelinePanel` | Pipeline publish is dev workflow, not operational | Move to dev tools or remove |

---

## View Inventory

### DEDICATED KALSHI VIEWS (3)

| View | Purpose | Essential Data | Classification |
|------|---------|----------------|----------------|
| `KalshiVolDashboardView` | Volatility targeting dashboard (3×2 grid) | Health, risk, sizing, grid status, consensus | **ESSENTIAL** - but needs simplification |
| `KalshiAgentPerformanceView` | Agent performance tracking and calibration | Agent metrics, calibration data, top agents | **USEFUL LATER** - defer to detail drawer |
| `KalshiSentimentView` | Fear/Greed sentiment dashboard | Mood data, sentiment-vol sizing, regime | **USEFUL LATER** - analytics, not operational |

### INTEGRATED KALSHI VIEWS (5)

| View | Kalshi Integration | Essential Data | Classification |
|------|-------------------|----------------|----------------|
| `Overview` | Balance hero, positions, orders, reboot controls | Balance, PnL, positions, recent orders, grid status | **ESSENTIAL** - but has too much detail |
| `OperatorDashboard` | Kalshi balance, PnL, positions, grid status, risk state | Same as Overview + operator-specific metrics | **DUPLICATED** - overlaps with Overview |
| `ProtectView` | Unified risk management (Kalshi risk screen) | Risk summary, kill switch, alerts, sizing metrics | **ESSENTIAL** - but needs consolidation |
| `SizeView` | Unified position sizing (bankroll, lanes, sizing) | Bankroll, lane status, XTF signals, deployment | **USEFUL LATER** - analytics |
| `PromoteView` | Unified deployment pipeline (agent grid) | Grid status, agent summaries, deployment state | **USEFUL LATER** - not operational |

### NON-KALSHI VIEWS (28)

These views are not in scope for Kalshi simplification but may need Kalshi status indicators:
- `ExecuteView`, `DiscoverView`, `MonitorView`, `Logs`, `Settings`, `SwarmConsensusMatrix`, `CalibrationDashboardView`, etc.

---

## API Endpoint Inventory

### ESSENTIAL ENDPOINTS (25)

| Endpoint | Purpose | Polling/WS | Classification |
|----------|---------|------------|----------------|
| `KALSHI_GRID_MODE` | Trading mode (PAPER/SHADOW/LIVE) | Polling (5s) | ESSENTIAL |
| `SYSTEM_EXECUTION_GATE` | Execution gate status | Polling (5s) | ESSENTIAL |
| `KALSHI_HEALTH` | Venue health status | Polling (10s) | ESSENTIAL |
| `KALSHI_BALANCE` | Account balance and portfolio | Polling (10s) | ESSENTIAL |
| `KALSHI_PNL` | Daily PnL | Polling (10s) | ESSENTIAL |
| `KALSHI_POSITIONS` | Open positions | Polling (10s) | ESSENTIAL |
| `KALSHI_ORDERS` | Recent orders | Polling (10s) or WS | ESSENTIAL |
| `KALSHI_FILLS` | Recent fills | WS preferred | ESSENTIAL |
| `KALSHI_RISK` | Risk summary and limits | Polling (10s) | ESSENTIAL |
| `KALSHI_GRID_STATUS` | Agent grid running status | Polling (10s) | ESSENTIAL |
| `KALSHI_GRID_START` | Start grid | Mutation | ESSENTIAL |
| `KALSHI_GRID_STOP` | Stop grid | Mutation | ESSENTIAL |
| `KALSHI_GRID_PAUSE` | Pause grid | Mutation | ESSENTIAL |
| `KALSHI_GRID_RESUME` | Resume grid | Mutation | ESSENTIAL |
| `OPERATOR_KILL_SWITCH_STATUS` | Kill switch state | Polling (10s) | ESSENTIAL |
| `RISK_KILL_SWITCH` | Toggle kill switch | Mutation | ESSENTIAL |
| `RISK_ALERTS` | Risk alerts | Polling (10s) or WS | ESSENTIAL |
| `KALSHI_SIZING_METRICS` | Position sizing data | Polling (10s) | ESSENTIAL |
| `KALSHI_MARKET_DETAIL` | Market details for trade ticket | On-demand | ESSENTIAL |
| `KALSHI_ORDERBOOK` | Market depth | Polling (5s) or WS | ESSENTIAL |
| `KALSHI_ORDERBOOK_STREAM` | WS orderbook stream | WS | ESSENTIAL |
| `KALSHI_ORDERS_BATCH_CANCEL` | Cancel all orders | Mutation | ESSENTIAL |
| `RECONCILIATION_STATUS` | Reconciliation status | Polling (30s) | ESSENTIAL |
| `KALSHI_CONTINUOUS_TRADER_STATUS` | CT status | Polling (10s) | ESSENTIAL |
| `KALSHI_CONTINUOUS_TRADER_STOP` | Stop CT | Mutation | ESSENTIAL |

### USEFUL LATER ENDPOINTS (40)

| Category | Endpoints | Purpose |
|----------|-----------|---------|
| Performance | `KALSHI_GRID_PERFORMANCE_*` | Agent performance analytics |
| Calibration | `CALIBRATION_*` | Brier score, calibration metrics |
| Sentiment | `KALSHI_MOOD_*`, `SENTIMENT_VOL_*` | Sentiment analysis |
| Consensus | `KALSHI_CONSENSUS_*`, `KALSHI_CONSENSUS_SIGNALS` | Consensus data |
| Insights | `KALSHI_INSIGHTS`, `KALSHI_RISK_INSIGHTS` | AI insights |
| Volume | `KALSHI_VOLUME_*` | Volume analytics |
| Liquidity | `KALSHI_LIQUIDITY_*` | Liquidity health |
| Deployment | `KALSHI_DEPLOYMENT_*` | Deployment pipeline |
| XTF | `XTF_*` | Cross-timeframe signals |
| Lane | `LANE_STATUS`, `KALSHI_SENTIMENT_LANE_SNAPSHOT` | Lane status |

### DUPLICATED ENDPOINTS (15)

| Endpoint | Duplicates | Notes |
|----------|------------|-------|
| `KALSHI_BALANCE` | Also available via `PORTFOLIO_SNAPSHOT` | Use canonical source |
| `KALSHI_PNL` | Also in `KALSHI_SIZING_METRICS` | Use sizing metrics |
| `KALSHI_POSITIONS` | Also in `KALSHI_GRID_PORTFOLIO` | Use grid portfolio |
| `KALSHI_GRID_STATUS` | Partially duplicated in `KALSHI_GRID_HEALTH` | Use grid status |
| `OPERATOR_KILL_SWITCH_STATUS` | Also `KALSHI_KILL_SWITCH` | Use operator endpoint |
| `KALSHI_RISK` | Partially in `RISK_SUMMARY` | Use Kalshi risk |
| `SENTIMENT_VOL_ASSETS` | Also `KALSHI_SENTIMENT_BUNDLE` | Use canonical sentiment |
| `KALSHI_CONSENSUS_SIGNALS` | Also `KALSHI_CONSENSUS_ALL` | Use signals endpoint |
| `KALSHI_MARKETS` | Also `KALSHI_CATALOG` | Use catalog |
| `KALSHI_ORDERBOOK` | Also `KALSHI_MARKET_DETAIL` | Use orderbook endpoint |
| `KALSHI_GRID_AGENTS` | Also `KALSHI_GRID_MATRIX` | Use agents endpoint |
| `KALSHI_GRID_FILLS` | Also `KALSHI_FILLS` | Use grid fills |
| `KALSHI_GRID_PNL` | Also `KALSHI_PNL` | Use grid PnL |
| `KALSHI_GRID_SESSION` | Partially in `KALSHI_GRID_STATUS` | Use session endpoint |
| `KALSHI_SWARM_*` | Swarm-specific, not operational | Defer to swarm view |

### DEAD / STALE ENDPOINTS (20)

| Endpoint | Reason | Action |
|----------|---------|--------|
| `KALSHI_PUBLISH_PIPELINE` | Dev workflow, not operational | Remove from UI constants |
| `KALSHI_PUBLISH_PIPELINE_TRIGGER` | Dev workflow, not operational | Remove from UI constants |
| `KALSHI_FAVORITES` | Not implemented on backend | Remove or implement |
| `KALSHI_FAVORITES_TOGGLE` | Not implemented on backend | Remove or implement |
| `KALSHI_CATEGORIES` | Not implemented on backend | Remove or implement |
| `KALSHI_NEWS_SIGNALS` | Removed in code (commented) | Already removed |
| `KALSHI_SENTIMENT_LANE_SNAPSHOT` | Lane-specific, not general ops | Defer to lane view |
| `KALSHI_DEBATE_STATS` | Debate-specific, not operational | Defer to debate view |
| `DEBATE_*` | Debate-specific, not operational | Defer to debate view |
| `PREDICTION_*` | Prediction markets, not Kalshi | Defer to prediction view |
| `KALSHI_EVENT` | Event-specific, not general ops | Defer to event view |
| `KALSHI_EXPORT` | Bulk export, not operational | Defer to analytics |
| `KALSHI_VOLUME_HISTORY` | Historical volume, not operational | Defer to analytics |
| `KALSHI_VOLUME_SMOOTHED` | Historical volume, not operational | Defer to analytics |
| `KALSHI_EDGE` | Edge analytics, not operational | Defer to analytics |
| `KALSHI_RISK_EVENTS` | Historical risk events | Defer to troubleshooting |
| `KALSHI_RISK_DOWNSIZE` | Downsize control, not essential | Defer to risk view |
| `KALSHI_ORDER_ERRORS` | Error log, not operational | Defer to troubleshooting |
| `KALSHI_LATENCY` | Latency metrics, not operational | Defer to monitoring |
| `KALSHI_ORDER_GROUP_*` | Order groups, not used in live ops | Defer to advanced features |

---

## Data Flow Analysis

### Current State

**Problem:** Each view independently fetches data with different polling intervals, causing:
- Redundant API calls (same data fetched multiple times)
- Stale data across views (different refresh rates)
- Inconsistent state (views show different values at same time)
- No single source of truth

**Example:** Balance is fetched in:
- Overview (10s polling)
- OperatorDashboard (10s polling)
- SizeView (10s polling)
- KalshiBankrollPanel (10s polling)

### Target State

**Solution:** Single canonical state model with:
1. **Backend state aggregation endpoint** - `/api/v1/kalshi/ui-state` (new)
2. **WebSocket push** for real-time updates (fills, orders, risk events)
3. **Client-side cache** with RTK Query or similar
4. **Progressive disclosure** - fetch detail data on-demand

---

## Proposed Canonical State Model

```typescript
interface KalshiUIState {
  // System status (always present)
  system: {
    mode: 'paper' | 'shadow' | 'live';
    execution_gate: 'clear' | 'limited' | 'blocked';
    execution_gate_reasons: string[];
    kill_switch_active: boolean;
    kill_switch_reason: string | null;
    grid_running: boolean;
    grid_agent_count: number;
  };

  // Capital state (always present)
  capital: {
    balance_usd: number;
    portfolio_usd: number;
    total_value_usd: number;
    daily_pnl_usd: number;
    drawdown_pct: number;
    drawdown_tier: 'normal' | 'warning' | 'downsize' | 'halt';
  };

  // Market state (always present)
  markets: {
    open_positions: number;
    active_tickers: string[];
    recent_fills: FillSummary[];
    recent_orders: OrderSummary[];
  };

  // Risk state (always present)
  risk: {
    daily_loss_usd: number;
    daily_loss_limit_usd: number;
    total_notional_usd: number;
    notional_limit_usd: number;
    breach_count: number;
    recent_alerts: RiskAlertSummary[];
  };

  // Detail state (lazy-loaded on drill-down)
  details?: {
    agent_performance?: AgentPerformanceData;
    sentiment?: SentimentData;
    calibration?: CalibrationData;
    analytics?: AnalyticsData;
  };
}
```

---

## Phase 1: Canonical Backend State

**Goal:** Create `/api/v1/kalshi/ui-state` endpoint that aggregates all essential state.

**Implementation:**
1. Create `web/api/kalshi_ui_state_api.py`
2. Aggregate from existing endpoints (mode, execution gate, balance, PnL, positions, risk, grid status)
3. Add WebSocket push for real-time updates (fills, orders, risk events)
4. Add detail endpoints for lazy-loaded data

---

## Phase 2-8: Subsequent Phases

See TODO list for detailed phase breakdown.

---

## Next Steps

1. **Review and approve** this inventory classification
2. **Define canonical state model** in detail
3. **Implement backend aggregation endpoint**
4. **Create new compact overview panel**
5. **Build live activity stream**
6. **Implement detail drawer**
7. **Build troubleshooting view**
8. **Migrate existing screens one at a time**

