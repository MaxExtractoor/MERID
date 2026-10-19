# UI View Glossary

> **Purpose**: Single source of truth for what each view does, which components it owns,
> and what is explicitly banned. Use this in code review to reject additions that violate
> view boundaries.
>
> **Last updated**: 2026-03-19 (auto-generated from source inventory)
>
> **Refactor status**: Phase 1 complete — 4 high-impact deletions, 3 simplifications applied

---

## Table of Contents

1. [View Inventory & Primary Questions](#1-view-inventory--primary-questions)
2. [Component-to-View Cross-Reference Matrix](#2-component-to-view-cross-reference-matrix)
3. [Duplicate Analysis & Home-View Assignments](#3-duplicate-analysis--home-view-assignments)
4. [View Boundary Rules](#4-view-boundary-rules)
5. [Normalization: Grid vs Swarm vs Lane vs Performance](#5-normalization-grid-vs-swarm-vs-lane-vs-performance)
6. [API Endpoint Alignment](#6-api-endpoint-alignment)
7. [Deletion / Move Recommendations](#7-deletion--move-recommendations)

---

## 1. View Inventory & Primary Questions

Each view must answer **one crisp question** in ≤60 seconds.

| # | View | File | Primary Question |
|---|------|------|-----------------|
| 1 | **Overview** | `Overview.tsx` | "Are we safe and making money right now?" |
| 2 | **Terminal** | `KalshiTerminalView.tsx` | "What's happening in this specific market and what orders can I place?" |
| 3 | **Dashboard** | `KalshiDashboardView.tsx` | "Which markets have edge right now and what should I trade next?" |
| 4 | **All Markets** | `KalshiAllMarketsView.tsx` | "What is the universe of available markets and how is coverage distributed?" |
| 5 | **Portfolio** | `KalshiPortfolioView.tsx` | "What am I holding, what's my P&L, and how is risk distributed?" |
| 6 | **Positions** | `PositionsView.tsx` | "What are my open positions and how is exposure distributed?" |
| 7 | **Orders** | `OrdersView.tsx` | "What's the lifecycle of my orders and what needs intervention?" |
| 8 | **Agent Grid** | `KalshiGridView.tsx` | "What are my agents doing by lane/market, and are any misbehaving?" |
| 9 | **Swarm Matrix** | `SwarmConsensusMatrix.tsx` | "What is the consensus direction per asset×timeframe, and where do agents disagree?" |
| 10 | **Performance** | `KalshiAgentPerformanceView.tsx` | "Which agents/strategies work, and how should they be recalibrated?" |
| 11 | **Calibration** | `CalibrationDashboardView.tsx` | "How accurate are our forecasters and is the resolution pipeline healthy?" |
| 12 | **Lane Control** | `LaneControlDashboard.tsx` | "How aggressively should I trade each lane, and what deployment gates are blocking?" |
| 13 | **Fear/Greed (Sentiment)** | `KalshiSentimentView.tsx` | "What is the current sentiment regime and how should it bias sizing?" |
| 14 | **Vol & Sizing** | `KalshiVolDashboardView.tsx` | "What are current volatility levels and how do they affect position sizing?" |
| 15 | **Operator** | `OperatorDashboard.tsx` | "Is the system safe, and do I need to pull a lever?" |
| 16 | **Risk Screen** | `KalshiRiskScreen.tsx` | "What are the active risk alerts and what is overall risk posture?" |
| 17 | **Kill Switch** | `KillSwitchView.tsx` | "Is trading halted, and can I safely re-enable it?" |
| 18 | **Logs** | `Logs.tsx` | "What happened?" |
| 19 | **Settings** | `Settings.tsx` | "How is the system configured?" |

**Sub-views** (rendered inside OperatorDashboard, not standalone):
- `OperatorStatusBar.tsx` — Status strip (mode, WS, circuit breaker, alerts)
- `OperatorControlPlane.tsx` — Action buttons (pause/resume swarm, switch mode, shutdown)
- `OperatorActivityStream.tsx` — Tabbed feed (orders, decisions, audit trail)

---

## 2. Component-to-View Cross-Reference Matrix

### Shared Components (appear in 2+ views)

| Component | Overview | Terminal | Dashboard | AllMkts | Portfolio | Positions | Orders | Grid | Swarm | Perf | Calibr | Lane | Sentiment | Vol | Operator | Risk | Kill | Logs | Settings |
|-----------|:--------:|:--------:|:---------:|:-------:|:---------:|:---------:|:------:|:----:|:-----:|:----:|:------:|:----:|:---------:|:---:|:--------:|:----:|:----:|:----:|:--------:|
| `ExecutionGateStrip` | ✅ | ✅ | — | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | — | — | ✅ | ✅ | ✅ | ✅ | — | — | — |
| `KalshiModeBadge` | — | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | — | — | ✅ | ✅ | — | — | ✅ | — | — |
| `ConfirmModal` | ✅ | — | — | — | ✅ | — | ✅ | ✅ | — | — | — | — | — | ✅ | ✅ | — | ✅ | — | — |
| `ErrorAlert` / `ErrorBar` | — | — | — | ✅ | ✅ | — | — | — | ✅ | — | — | ✅ | — | — | — | — | ✅ | ✅ | ✅ |
| `EmergencyStopButton` | — | — | — | — | — | — | — | ✅ | — | — | — | — | — | — | — | — | ✅ | — | — |
| `KalshiPnlChart` | — | — | — | — | ✅ | — | — | — | — | — | — | — | — | — | — | ✅ | — | — | — |
| `ModeSafetyPanel` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✅ | — | ✅ | — | — |
| `SessionLogPanel` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✅ | — | ✅ | — | — |
| `KalshiReconciliationBadge` | — | — | — | — | ✅ | — | — | ✅ | — | — | — | — | — | — | — | — | — | — | — |
| `KalshiCancelAllButton` | — | — | — | — | — | — | ✅ | ✅ | — | — | — | — | — | — | — | — | — | — | — |
| `MetricCard` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✅ | — | — | — | ✅ |
| `DataAgeBadge` | — | — | — | — | ✅ | — | — | — | — | — | — | — | — | — | ✅ | — | — | — | — |

### View-Exclusive Components

| View | Exclusive Components |
|------|---------------------|
| **Overview** | `CollapsibleConsole`, `AgentActivityPanel`, `SystemHealthCard`, `KalshiHealthCard`, `AgentStatusCard`, `RiskProtectionCard`, `KalshiBalanceHero`★, `KalshiPositionsCard`★, `KalshiRecentOrders`★, `RebootControlPanel`★ |
| **Terminal** | `KalshiTradeTicket`†, `KalshiOrderbookPanel`†, `KalshiActivityLog` |
| **Dashboard** | `OperatorHeader`, `DebateStatusBadge`, `DebateContextPanel`, `SkeletonMetricRow`, `SkeletonTable` |
| **All Markets** | `RegimeBadge` |
| **Portfolio** | `KalshiRiskFeed`, `OrderGroupPanel`, `BatchOrderPanel`, `OrderGroupAnalytics`, `CircuitBreakerPanel`, `LatencyPanel`, `OrderErrorsPanel`, `RiskAlertFeed` |
| **Grid** | `PaperLadderCard`, `SwarmInsightTab` |
| **Swarm Matrix** | *(no external components — self-contained)* |
| **Calibration** | `CorrelationRiskPanel` |
| **Vol & Sizing** | `KalshiInsightsPanel`, `PublishPipelinePanel` |
| **Operator** | `StalenessIndicator`, `VenueHealthGrid`, `DataFreshnessPanel`, `ModeControlPanel`, `ExplainabilityTimeline`, `TickTimeline`, `TelegramLogViewer`, `AlertHistoryPanel`, `TradingHaltBanner`, `ContractHealthPanel` |
| **Logs** | `DataTableEnhanced`, `EmptyState` |

> ★ = Inline/internal component defined within the view file  
> † = `KalshiTradeTicket` and `KalshiOrderbookPanel` also appear in Dashboard

---

## 3. Duplicate Analysis & Home-View Assignments

### High-Priority Duplicates

| Component / Data | Current Surfaces | Proposed Home | Other Surfaces | Action |
|-----------------|-----------------|---------------|----------------|--------|
| **Positions table/list** | Overview (KalshiPositionsCard), Portfolio, Positions | **Positions** (full table) | Overview: top-3 summary + "View all" link; Portfolio: risk-weighted summary only | **Remove** full table from Overview & Portfolio |
| **Orders table** | Overview (KalshiRecentOrders), Orders, Terminal | **Orders** (full table with amend/cancel) | Overview: last-5 summary; Terminal: per-market orders only | **Remove** full table from Overview |
| **KalshiTradeTicket** | Terminal, Dashboard | **Terminal** (full trade ticket) | Dashboard: link to Terminal with market pre-selected | **Remove** from Dashboard or keep as compact variant |
| **KalshiOrderbookPanel** | Terminal, Dashboard | **Terminal** | Dashboard: remove or show spread-only summary | **Remove** from Dashboard |
| **Kill switch controls** | Overview, Portfolio, Grid, Operator, Kill Switch | **Kill Switch** (full controls) | Overview: status badge only; Operator: toggle + status; Others: `ExecutionGateStrip` banner only | **Simplify** to status-only in non-home views |
| **Balance / PnL metrics** | Overview, Terminal, Portfolio, Operator | **Portfolio** (detailed) | Overview: single KPI row; Terminal: compact bar; Operator: summary metric | Keep as summaries — **no full cards** outside Portfolio |
| **Risk alerts feed** | Portfolio (RiskAlertFeed), Risk Screen, Operator (AlertHistoryPanel) | **Risk Screen** (full feed) | Portfolio: top-3 active alerts; Operator: count badge | **Remove** full feed from Portfolio |
| **ModeSafetyPanel** | Operator, Kill Switch | **Kill Switch** (full panel) | Operator: compact mode indicator | **Remove** from Operator or keep summary-only |
| **SessionLogPanel** | Operator, Kill Switch | **Kill Switch** | Operator: remove | **Remove** from Operator |

### Medium-Priority Duplicates

| Component / Data | Current Surfaces | Recommendation |
|-----------------|-----------------|----------------|
| `KalshiPnlChart` | Portfolio, Risk Screen | Keep in both — different context (portfolio review vs risk monitoring) |
| `KalshiReconciliationBadge` | Portfolio, Grid | Keep in both — lightweight badge, not a full card |
| `KalshiCancelAllButton` | Orders, Grid | Keep in both — actionable safety control |
| `MetricCard` | Operator, Settings | Generic component — no issue |
| `DataAgeBadge` | Portfolio, Operator | Lightweight indicator — no issue |

---

## 4. View Boundary Rules

### Per-View Allowed/Banned Card Types

| View | Allowed | Banned |
|------|---------|--------|
| **Overview** | ≤7 KPI metrics, 3–4 summary cards, mode badge, kill switch status indicator, "View all" links | Full tables, editable controls (except mode toggle & kill switch), trade tickets, orderbooks |
| **Terminal** | Per-market depth, order tickets, market browser, fills for selected market | Global portfolio views, multi-agent grids, risk management panels |
| **Dashboard** | Market cards with edge signals, quick-filter tabs, debate context, market sorting | Full order management, risk controls, agent configuration |
| **All Markets** | Coverage stats, market table with pagination, category filters, universe controls | Trade tickets, position details, agent-level data |
| **Portfolio** | Position breakdown, P&L chart, risk summary, reconciliation, order group panels | Agent configuration, market browsing, full logs |
| **Positions** | Position table with filters/sorting, risk metrics | Order management, trade tickets, agent data |
| **Orders** | Order table with status filters, amend/cancel actions, fills table | Position details, market browsing, agent data |
| **Agent Grid** | Agent matrix (asset×timeframe), per-agent status, grid controls, recent fills | Full portfolio tables, market discovery, settings |
| **Swarm Matrix** | Consensus heatmap, per-cell drill-down with agent votes | Controls/sliders, order management, risk settings |
| **Performance** | Historical metrics (P&L, win rate, Sharpe), leaderboard, calibration error, export | Live trading controls, order placement, market browsing |
| **Calibration** | Forecaster Brier scores, resolver status, recalibration data, critic history | Trading controls, position data, market browsing |
| **Lane Control** | Lane state matrix, XTF alignment, deployment phases, auto-promoter status, gate results | Full portfolio, order management, market tables |
| **Sentiment** | Global gauge, per-category scores, component breakdown, extreme markets table | Trading controls, order management, agent configuration |
| **Vol & Sizing** | Vol targets, risk limits, agent sizing grid, equity chart, alerts, AI insights | Full order tables, market browsing, agent deployment |
| **Operator** | System health grid, mode controls, data freshness, activity stream, key metrics, kill switch toggle | Full position/order tables, trade tickets, market discovery |
| **Risk Screen** | Risk summary, connectivity status, alert feed with acknowledge, P&L chart | Trading controls, market browsing, agent configuration |
| **Kill Switch** | Kill switch state, risk state meters, category mode toggles, emergency stop, safety panel, session log | Market data, agent performance, portfolio details |
| **Logs** | Log table with level/component filters, search, auto-refresh, log stats | Trading controls, portfolio data, risk management |
| **Settings** | User preferences, trading settings, notification settings, risk settings, agent settings | Live data, trading actions, monitoring |

---

## 5. Normalization: Grid vs Swarm vs Lane vs Performance

These four views currently have overlapping agent data. Enforce these boundaries:

| Concern | Home View | Data Type | Other Views |
|---------|-----------|-----------|-------------|
| **Real-time agent state** (enabled, running, last cycle, errors) | Agent Grid | Live status | Operator: agent count badge only |
| **Consensus & voting** (direction, probability, confidence, disagreement) | Swarm Matrix | Live consensus | Dashboard: small consensus badge per market |
| **Historical metrics** (P&L, win rate, Sharpe, calibration error) | Performance | Aggregated stats | Grid: sparkline or badge, not full tables |
| **Forecaster accuracy** (Brier scores, resolution stats) | Calibration | Accuracy data | Performance: link to Calibration for drill-down |
| **Lane state & deployment** (XTF alignment, promotion gates) | Lane Control | Control data | Grid: deployment phase badge only |
| **Sizing & vol controls** (vol targets, risk limits, sliders) | Vol & Sizing | Control sliders | Lane Control: sizing factor display (read-only) |
| **Sentiment regime** (fear/greed score, components) | Sentiment | Regime data | Vol & Sizing: regime badge; Dashboard: regime indicator |

**Rule**: If you see the same "agent list" table in multiple views with slightly different columns, collapse into one master grid and use tabs/filters.

---

## 6. API Endpoint Alignment

Each view should hit a **small, coherent set** of endpoints. Flag views calling >5 unrelated endpoint groups.

| View | Primary Endpoint Groups | Concern |
|------|------------------------|---------|
| **Overview** | balance, pnl, positions, orders, fills, kill_switch, grid_status, catalog | ⚠️ **Too broad** — hits 8+ groups. Reduce to: balance, pnl, kill_switch, grid_status (summaries only) |
| **Terminal** | kill_switch, venue_mode, markets, order_errors, balance, risk_summary, positions, orders, fills, edge_signals, sizing | ⚠️ **Borderline** — justified for a trading terminal, but consider lazy-loading orderbook/fills |
| **Dashboard** | venue_mode, markets, catalog, health, positions, edge, sizing, balance, consensus, news | ⚠️ **Broad** — consider removing positions (link to Portfolio) |
| **Portfolio** | health, positions, orders, balance, risk_summary, sizing, kill_switch, grid_mode, session | ✅ Coherent for portfolio management |
| **Positions** | positions, risk_summary, grid_portfolio | ✅ Focused |
| **Orders** | orders, fills | ✅ Very focused |
| **Agent Grid** | grid_status (agents, venue, metrics, portfolio_risk) | ✅ Focused |
| **Swarm Matrix** | swarm_consensus | ✅ Very focused |
| **Performance** | grid_performance (agents, summary, top, calibration, agent detail) | ✅ Focused |
| **Calibration** | metrics_forecasters, metrics_resolver, swarm_recalibration, swarm_critic_history, swarm_execution_stats | ✅ Coherent |
| **Lane Control** | lane XTF signals, deployment status, auto-promoter | ✅ Focused |
| **Sentiment** | sentiment data, lane sentiment snapshot | ✅ Focused |
| **Vol & Sizing** | health, sizing, risk_summary, grid agents, alerts, volume, insights | ⚠️ **Broad** — consider splitting alerts to Risk Screen |
| **Operator** | operator_summary, balance, pnl, positions, grid_status, risk_state, agent_activity | ⚠️ **Broad** — justified as ops console, but positions should be count-only |
| **Risk Screen** | risk_summary, risk_alerts, ws risk stream | ✅ Focused |
| **Kill Switch** | kill_switch_status, risk_state, category_config, block_reasons | ✅ Focused |
| **Logs** | logs, logs_stats | ✅ Very focused |
| **Settings** | user preferences, trading settings, notifications, risk, agent settings | ✅ Coherent |

---

## 7. Deletion / Move Recommendations

Priority-ordered list of concrete actions. Each entry answers: *"If this disappeared from this page, what concrete action would be harder?"*

### 🔴 Delete (no action lost)

| # | Component | Remove From | Reason | Status |
|---|-----------|-------------|--------|--------|
| 1 | `KalshiPositionsCard` (full inline table) | Overview | Duplicates Positions view; replaced with `PositionsSummaryCard` (3-line summary + "View all" link) | ✅ DONE |
| 2 | `KalshiRecentOrders` (full inline table) | Overview | Duplicates Orders view; replaced with `OrdersSummaryCard` (count + status breakdown + "View all" link) | ✅ DONE |
| 3 | `RebootControlPanel` | Overview | Operator concern; moved to OperatorDashboard. Overview shows compact info box + link. Extracted to `components/RebootControlPanel.tsx`. | ✅ DONE |
| 4 | `SessionLogPanel` | OperatorDashboard | Already on Kill Switch; redundant | ✅ DONE |
| 5 | `RiskAlertFeed` (full feed) | KalshiPortfolioView | Duplicates Risk Screen; replaced with top-3 inline summary | ✅ DONE |
| 6 | `KalshiOrderbookPanel` | KalshiDashboardView | Terminal owns depth data; removed from Dashboard | ✅ DONE |

### 🟡 Simplify (keep summary, remove detail)

| # | Component | Simplify In | To What | Status |
|---|-----------|-------------|---------|--------|
| 7 | `KalshiTradeTicket` | KalshiDashboardView | "Trade in Terminal" button + `sessionStorage` ticker handoff + `merid:navigate` event | ✅ DONE |
| 8 | Kill switch toggle | Overview, Portfolio, Terminal, Operator, RiskProtectionsPanel | Replaced with read-only status badges + "Manage on Kill Switch view" hints. Toggle removed from all views except KillSwitchView. | ✅ DONE |
| 9 | Balance / P&L cards | Overview | `KalshiBalanceHero` → compact `KalshiBalanceKpiRow` (single-line strip + Portfolio link). Terminal already compact. Portfolio keeps full hero. | ✅ DONE |
| 10 | `ModeSafetyPanel` | OperatorDashboard | Compact mode indicator inline; Kill Switch owns the full panel | ✅ DONE |
| 11 | Agent list in Vol & Sizing | KalshiVolDashboardView | Simplified to 3 columns: Agent, WR%, Size f. Removed PF, Sharpe, Fills. Renamed to "Agent Sizing Grid". | ✅ DONE |

### 🟢 Keep as-is (justified duplication)

| Component | Views | Justification |
|-----------|-------|---------------|
| `ExecutionGateStrip` | 11 views | Global safety banner — must be visible everywhere trading can occur |
| `KalshiModeBadge` | 10 views | Lightweight mode indicator — prevents wrong-mode trades |
| `ConfirmModal` | 7 views | Generic UX pattern — not domain-specific duplication |
| `KalshiPnlChart` | Portfolio, Risk | Different contexts: review vs monitoring |
| `KalshiCancelAllButton` | Orders, Grid | Safety control needed wherever orders are managed |
| `EmergencyStopButton` | Grid, Kill Switch | Critical safety — justified redundancy |

---

## Appendix: File Sizes (lines)

| View | Lines | Complexity Note |
|------|-------|----------------|
| `Overview.tsx` | ~340 | Phase 2: RebootControlPanel extracted + removed, KalshiBalanceHero → KalshiBalanceKpiRow, kill switch → read-only badge, reboot state/callbacks removed |
| `KalshiTerminalView.tsx` | ~750 | Phase 2: Kill switch toggle removed → read-only badge; handleKillSwitch + Ctrl+Shift+K shortcut removed |
| `KalshiDashboardView.tsx` | ~1500 | Refactored: OrderbookPanel deleted, KalshiTradeTicket → "Trade in Terminal" button, dead state cleaned |
| `KalshiAllMarketsView.tsx` | 623 | Self-contained, reasonable |
| `KalshiPortfolioView.tsx` | ~735 | Phase 2: Kill switch toggle removed → read-only badge + "Manage on Kill Switch view" hint |
| `KalshiGridView.tsx` | 1358 | ⚠️ **Largest view** — strong refactor candidate |
| `KalshiVolDashboardView.tsx` | ~890 | Phase 2: Agent grid simplified to 3 sizing-relevant columns (Agent, WR%, Size f) |
| `KalshiSentimentView.tsx` | 680 | Self-contained |
| `LaneControlDashboard.tsx` | 505 | Reasonable |
| `SwarmConsensusMatrix.tsx` | 485 | Clean, focused |
| `CalibrationDashboardView.tsx` | 429 | Reasonable |
| `OrdersView.tsx` | 415 | Clean, focused |
| `KillSwitchView.tsx` | 410 | Reasonable |
| `KalshiRiskScreen.tsx` | 389 | Focused |
| `KalshiAgentPerformanceView.tsx` | 387 | Focused |
| `OperatorDashboard.tsx` | ~460 | Phase 2: RebootControlPanel + ConfirmModal added (moved from Overview), kill switch toggle → read-only badge |
| `Logs.tsx` | 507 | Reasonable |
| `Settings.tsx` | 1129 | ⚠️ Large — many settings sections |
| `PositionsView.tsx` | 290 | Clean, small |
| `RebootControlPanel.tsx` | ~165 | **NEW** — Extracted shared component from Overview (Phase 2) |

---

## Changelog

### Phase 2 (UI De-duplication — Surgical Refactor)

1. **RebootControlPanel** — Extracted from `Overview.tsx` → `components/RebootControlPanel.tsx`, wired into `OperatorDashboard.tsx` with full state/callbacks/ConfirmModal. Overview replaced with compact info box linking to Operator Dashboard.
2. **Kill switch toggles** — Removed toggle buttons from `KalshiTerminalView`, `KalshiPortfolioView`, `OperatorDashboard`, and `RiskProtectionsPanel`. All replaced with read-only status badges + "Manage on Kill Switch view" hints. `KillSwitchView` remains the single control surface.
3. **Balance / P&L** — `KalshiBalanceHero` in Overview replaced with compact `KalshiBalanceKpiRow` (single-line strip with Portfolio link). Terminal already compact. Portfolio keeps full hero.
4. **Agent Sizing Grid** — `KalshiVolDashboardView` agent table simplified from 6 columns to 3 (Agent, WR%, Size f). PF, Sharpe, Fills removed. Renamed to "Agent Sizing Grid".
5. **Build** — TypeScript compiles cleanly (3 pre-existing errors unrelated to Phase 2).
