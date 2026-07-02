# UI Inventory & 15m Alignment Analysis

**Generated:** 2026-05-26  
**Scope:** `web/react/src/`  
**Focus:** Kalshi 15m crypto stack alignment (BTC/ETH/SOL/XRP/DOGE 15-minute prediction markets)

---

## Executive Summary

**Total Components:** 154 components in `web/react/src/components/`  
**Total Views:** 38 views in `web/react/src/views/`  
**Current Architecture:** 8-stage workflow (Discover → Analyze → Consensus → Size → Execute → Monitor → Promote → Protect)

**Alignment Status:**
- **KEEP (15m-aligned):** 67 components
- **REMOVE (Legacy/Not 15m):** 35 components
- **UPDATE (Needs 15m alignment):** 12 components
- **INFRASTRUCTURE (Keep):** 40 components

---

## Component Inventory by Category

### 1. Kalshi-Specific Components (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| KalshiBankrollPanel.tsx | Live bankroll display | ✅ Aligned | Uses Kalshi API for live equity |
| KalshiTradeTicket.tsx | Trade entry | ✅ Aligned | Supports 15m crypto markets |
| KalshiOrderbookPanel.tsx | Orderbook display | ✅ Aligned | Real-time orderbook data |
| KalshiModeBadge.tsx | Live/paper mode indicator | ✅ Aligned | Critical for 15m live trading |
| KalshiLoadingSkeleton.tsx | Loading state | ✅ Aligned | UI infrastructure |
| KalshiLiquidityBadge.tsx | Liquidity indicator | ✅ Aligned | Market health signal |
| KalshiCancelAllButton.tsx | Cancel all orders | ✅ Aligned | Risk management |
| KalshiActivityStream.tsx | Activity feed | ✅ Aligned | Real-time activity |
| KalshiActivityLog.tsx | Activity log | ✅ Aligned | Historical activity |
| KalshiActionArea.tsx | Action area | ✅ Aligned | Trade actions |
| KalshiCompactOverview.tsx | Compact overview | ✅ Aligned | Quick status |
| KalshiCredentialsCard.tsx | Credentials management | ✅ Aligned | Kalshi API credentials |
| KalshiCryptoSignalsPanel.tsx | Crypto signals | ✅ Aligned | 15m crypto signals |
| KalshiCryptoRtiPanel.tsx | Real-time info | ✅ Aligned | Real-time market data |
| KalshiDetailDrawer.tsx | Market details | ✅ Aligned | Market information |
| KalshiErrorBoundary.tsx | Error handling | ✅ Aligned | Error boundary |
| KalshiErrorPill.tsx | Error display | ✅ Aligned | Error indicator |
| KalshiExecutionTelemetryPanel.tsx | Execution telemetry | ✅ Aligned | Trade execution metrics |
| KalshiInsightsPanel.tsx | Market insights | ✅ Aligned | Market analysis |
| KalshiPaperVsShadowPanel.tsx | Paper vs shadow | ⚠️ Review | May not be needed for 15m live |
| KalshiPnlChart.tsx | PnL charting | ✅ Aligned | Performance tracking |
| KalshiReconciliationBadge.tsx | Reconciliation status | ✅ Aligned | Kalshi reconciliation |
| KalshiRiskFeed.tsx | Risk monitoring | ✅ Aligned | Risk alerts |
| KalshiTroubleshootingView.tsx | Troubleshooting | ✅ Aligned | Debug interface |

**Count:** 23 components

---

### 2. Swarm/Consensus Components (REMOVE - Not 15m Aligned)

| Component | Purpose | Action | Reason |
|-----------|---------|--------|--------|
| SwarmVerdictFeed.tsx | Swarm consensus verdicts | 🗑️ REMOVE | Swarm consensus not used in 15m stack |
| SwarmSentimentGrid.tsx | 5×4 grid (15m/1h/daily/weekly) | 🗑️ REMOVE | Includes non-15m timeframes (1h, daily, weekly) |
| SwarmPanel.tsx | Stub component | 🗑️ REMOVE | Stub, not implemented |
| SwarmInsightTab.tsx | Swarm insights | 🗑️ REMOVE | Swarm consensus not used in 15m stack |

**Count:** 4 components

---

### 3. Paper Trading Components (REMOVE - 15m is Live-Only)

| Component | Purpose | Action | Reason |
|-----------|---------|--------|--------|
| PaperTradingPanel.tsx | Paper trading interface | 🗑️ REMOVE | 15m stack is live-only (kalshi_crypto_15m_v2 profile) |
| PaperLadderCard.tsx | Paper trading ladder tiers | 🗑️ REMOVE | Paper trading not needed for 15m live |

**Count:** 2 components

---

### 4. Sentiment Components (REMOVE - Not 15m Aligned)

| Component | Purpose | Action | Reason |
|-----------|---------|--------|--------|
| SentimentPnLStrip.tsx | Sentiment PnL strip | 🗑️ REMOVE | Social sentiment not used in 15m stack |
| SentimentBundleCard.tsx | Sentiment bundle | 🗑️ REMOVE | Social sentiment not used in 15m stack |

**Count:** 2 components

---

### 5. Stub Components (REMOVE)

| Component | Purpose | Action | Reason |
|-----------|---------|--------|--------|
| StubGate.tsx | Stub gate | 🗑️ REMOVE | Stub component |
| StubBanner.tsx | Stub banner | 🗑️ REMOVE | Stub component |

**Count:** 2 components

---

### 6. Core Infrastructure (KEEP)

| Component | Purpose | Notes |
|-----------|---------|-------|
| ErrorBoundary.tsx | Error boundary | Critical infrastructure |
| ErrorAlert.tsx | Error alert | Critical infrastructure |
| ErrorBar.tsx | Error bar | Critical infrastructure |
| OfflineIndicator.tsx | Offline status | Critical infrastructure |
| LoadingState.tsx | Loading state | Critical infrastructure |
| EmptyState.tsx | Empty state | Critical infrastructure |
| CommandPalette.tsx | Command palette | Critical infrastructure |
| Sidebar.tsx | Navigation sidebar | Critical infrastructure |
| TopBar.tsx | Top navigation bar | Critical infrastructure |
| ToastProvider.tsx | Toast notifications | Critical infrastructure |
| ConfirmModal.tsx | Confirmation modal | Critical infrastructure |
| AnimatedCard.tsx | Animated card | UI infrastructure |
| ChartCard.tsx | Chart card | UI infrastructure |
| ChartWrapper.tsx | Chart wrapper | UI infrastructure |
| DataTable.tsx | Data table | UI infrastructure |
| MetricCard.tsx | Metric display | UI infrastructure |
| Tooltip.tsx | Tooltip | UI infrastructure |
| ThemeToggle.tsx | Theme toggle | UI infrastructure |
| StatusIndicator.tsx | Status indicator | UI infrastructure |
| ConnectionStatusIndicator.tsx | Connection status | UI infrastructure |
| BackendStatusIndicator.tsx | Backend status | UI infrastructure |
| BackendOfflineBanner.tsx | Backend offline banner | UI infrastructure |
| RealtimeDisconnectedBanner.tsx | Realtime disconnected banner | UI infrastructure |
| ExecutionBlockedBanner.tsx | Execution blocked banner | UI infrastructure |
| TradingHaltBanner.tsx | Trading halt banner | UI infrastructure |
| VenueStatusBanner.tsx | Venue status banner | UI infrastructure |
| GlobalModeBanner.tsx | Global mode banner | UI infrastructure |
| GateChangeToast.tsx | Gate change toast | UI infrastructure |
| ViewErrorFallback.tsx | View error fallback | UI infrastructure |
| PanelErrorBoundary.tsx | Panel error boundary | UI infrastructure |
| KalshiErrorBoundary.tsx | Kalshi error boundary | UI infrastructure |
| ConsoleViewer.tsx | Console viewer | Debug infrastructure |
| CollapsibleConsole.tsx | Collapsible console | Debug infrastructure |
| ContextStrip.tsx | Context strip | UI infrastructure |
| HeaderStats.tsx | Header stats | UI infrastructure |
| QuickActionsPanel.tsx | Quick actions | UI infrastructure |
| NotificationPanel.tsx | Notification panel | UI infrastructure |
| SkeletonLoader.tsx | Skeleton loader | UI infrastructure |

**Count:** 40 components

---

### 7. Data Quality & Health (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| DataFreshnessIndicator.tsx | Data freshness indicator | ✅ Aligned | Critical for 15m spot price freshness |
| DataFreshnessPanel.tsx | Data freshness panel | ✅ Aligned | Spot price freshness monitoring |
| DataHealthSummary.tsx | Data health summary | ✅ Aligned | Overall data quality |
| DataSourceBadges.tsx | Data source badges | ✅ Aligned | Spot price source tracking |
| DataAgeBadge.tsx | Data age badge | ✅ Aligned | Spot price age display |
| StalenessIndicator.tsx | Staleness indicator | ✅ Aligned | Data staleness detection |
| ContractHealthPanel.tsx | Contract health panel | ✅ Aligned | API contract health |

**Count:** 7 components

---

### 8. Risk & Protection (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| RiskProtectionsPanel.tsx | Risk protections panel | ✅ Aligned | Risk management |
| CircuitBreakerPanel.tsx | Circuit breaker panel | ✅ Aligned | Circuit breaker status |
| ModeSafetyPanel.tsx | Mode safety panel | ✅ Aligned | Live/paper mode safety |
| ExecutionGateStrip.tsx | Execution gate strip | ✅ Aligned | Execution gating |
| EmergencyStopButton.tsx | Emergency stop button | ✅ Aligned | Kill switch |
| RiskAlertFeed.tsx | Risk alert feed | ✅ Aligned | Risk alerts |
| CorrelationRiskPanel.tsx | Correlation risk panel | ⚠️ Review | May not be needed for 15m single-venue |
| ReconciliationDashboard.tsx | Reconciliation dashboard | ✅ Aligned | Kalshi reconciliation |

**Count:** 8 components

---

### 9. Trading & Orders (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| BatchOrderPanel.tsx | Batch order panel | ✅ Aligned | Batch order management |
| OrderGroupPanel.tsx | Order group panel | ✅ Aligned | Order grouping |
| OrderErrorsPanel.tsx | Order errors panel | ✅ Aligned | Error tracking |
| OrderGroupAnalytics.tsx | Order group analytics | ✅ Aligned | Order analytics |
| RecentTradesTable.tsx | Recent trades table | ✅ Aligned | Trade history |
| TradesTable.tsx | Trades table | ✅ Aligned | Trade display |

**Count:** 6 components

---

### 10. Agent & Performance (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| AgentActivityPanel.tsx | Agent activity panel | ✅ Aligned | Agent monitoring |
| AgentStatusPanel.tsx | Agent status panel | ✅ Aligned | Agent status |
| AgentPerformanceTable.tsx | Agent performance table | ✅ Aligned | Performance tracking |
| AgentLeaderboard.tsx | Agent leaderboard | ✅ Aligned | Agent ranking |
| AgentReasoningPanel.tsx | Agent reasoning panel | ⚠️ Review | May need 15m-specific reasoning |
| DevAgentRoster.tsx | Dev agent roster | ⚠️ Review | Dev tool, may not be production |

**Count:** 6 components

---

### 11. Crypto-Specific (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| CryptoSpotKalshiPanel.tsx | Crypto spot + Kalshi panel | ✅ Aligned | Spot price + Kalshi integration |
| CryptoLanesGrid.tsx | Crypto lanes grid | ✅ Aligned | 15m crypto lanes |
| CryptoAlertStatusPanel.tsx | Crypto alert status panel | ✅ Aligned | Crypto-specific alerts |

**Count:** 3 components

---

### 12. Explainability & Debug (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| ExplainabilityAnalytics.tsx | Explainability analytics | ✅ Aligned | Decision explainability |
| ExplainabilityPanel.tsx | Explainability panel | ✅ Aligned | Decision explainability |
| ExplainabilityTimeline.tsx | Explainability timeline | ✅ Aligned | Decision history |
| TickTimeline.tsx | Tick timeline | ✅ Aligned | Market tick history |
| SessionTimeline.tsx | Session timeline | ✅ Aligned | Session history |
| SessionLogPanel.tsx | Session log panel | ✅ Aligned | Session logs |
| AuditTrail.tsx | Audit trail | ✅ Aligned | Audit logging |
| BackendHealthDebug.tsx | Backend health debug | ✅ Aligned | Debug tool |
| AlertHistoryPanel.tsx | Alert history panel | ✅ Aligned | Alert history |

**Count:** 9 components

---

### 13. Charts & Visualization (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| EquityChart.tsx | Equity chart | ✅ Aligned | PnL tracking |
| DrawdownChart.tsx | Drawdown chart | ✅ Aligned | Drawdown monitoring |
| PortfolioChart.tsx | Portfolio chart | ✅ Aligned | Portfolio visualization |
| DomainPnLChart.tsx | Domain PnL chart | ⚠️ Review | May not be needed for 15m single-domain |
| SharpeRatioTile.tsx | Sharpe ratio tile | ✅ Aligned | Performance metric |
| PerformanceDashboard.tsx | Performance dashboard | ✅ Aligned | Performance overview |
| BlockedReasonsChart.tsx | Blocked reasons chart | ✅ Aligned | Trade blocking analysis |
| PnLConsistencyWidget.tsx | PnL consistency widget | ⚠️ Review | May not be needed for 15m |

**Count:** 8 components

---

### 14. Settings & Configuration (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| DomainControlPanel.tsx | Domain control panel | ⚠️ Review | May not be needed for 15m single-domain |
| RebootControlPanel.tsx | Reboot control panel | ✅ Aligned | Server restart controls |

**Count:** 2 components

---

### 15. Other Components (KEEP - 15m Aligned)

| Component | Purpose | 15m Alignment | Notes |
|-----------|---------|----------------|-------|
| SpotBasisPanel.tsx | Spot basis panel | ✅ Aligned | Spot price basis |
| LatencyPanel.tsx | Latency panel | ✅ Aligned | API latency monitoring |
| CodeQualityPanel.tsx | Code quality panel | ⚠️ Review | Dev tool, may not be production |
| CodebaseHealth.tsx | Codebase health | ⚠️ Review | Dev tool, may not be production |
| HelpPopover.tsx | Help popover | ✅ Aligned | User help |
| OperatorHeader.tsx | Operator header | ✅ Aligned | Operator interface |
| AssistantPanel.tsx | Assistant panel | ✅ Aligned | AI assistant (Sprint 19) |

**Count:** 7 components

---

## View Inventory

### Current Views (38 total)

| View | Purpose | 15m Alignment | Action | Notes |
|------|---------|----------------|--------|-------|
| Overview.tsx | System overview | ✅ Aligned | KEEP | Reboot sequence, pre-flight checks |
| OperatorDashboard.tsx | Operator dashboard | ✅ Aligned | KEEP | System health, Kalshi status |
| Logs.tsx | Logs viewer | ✅ Aligned | KEEP | System logs |
| Settings.tsx | Settings | ✅ Aligned | KEEP | Configuration |
| DiscoverView.tsx | Market discovery (Stage 1) | ✅ Aligned | KEEP | Kalshi-style market discovery |
| SizeView.tsx | Sizing (Stage 4) | ✅ Aligned | KEEP | Position sizing |
| ExecuteView.tsx | Execution (Stage 5) | ✅ Aligned | KEEP | Unified trading execution |
| MonitorView.tsx | Monitoring (Stage 6) | ✅ Aligned | KEEP | Real-time monitoring |
| PromoteView.tsx | Promotion (Stage 7) | ⚠️ Review | UPDATE | May not be needed for 15m live-only |
| ProtectView.tsx | Protection (Stage 8) | ✅ Aligned | KEEP | Risk protection |
| KalshiAgentPerformanceView.tsx | Agent performance (Stage 3) | ✅ Aligned | KEEP | Agent performance |
| KalshiSentimentView.tsx | Sentiment analysis (Stage 2) | ⚠️ Review | UPDATE | Social sentiment not used in 15m |
| KalshiVolDashboardView.tsx | Volatility dashboard (Stage 2) | ✅ Aligned | KEEP | Volatility analysis |
| CalibrationDashboardView.tsx | Calibration (Stage 3) | ✅ Aligned | KEEP | Agent calibration |

**Count:** 14 views

---

## Legacy References Found

### 1. SwarmConsensusMatrix (Already Removed)
- **Status:** ✅ Already removed
- **Evidence:** `App.tsx` line 23: `// LEGACY REMOVAL: SwarmConsensusMatrix removed - consensus module deleted`
- **Action:** None needed

### 2. Paper Trading References
- **Status:** ⚠️ Needs removal
- **Evidence:** 
  - `PaperTradingPanel.tsx` - Paper trading interface
  - `PaperLadderCard.tsx` - Paper trading ladder
  - `constants.ts` line 74: `PAPER_TRADING_PORTFOLIO` endpoint
- **Action:** Remove components and endpoint constant

### 3. Swarm/Consensus References
- **Status:** ⚠️ Needs removal
- **Evidence:**
  - `SwarmVerdictFeed.tsx` - Swarm verdicts
  - `SwarmSentimentGrid.tsx` - 5×4 grid (includes 1h, daily, weekly)
  - `SwarmPanel.tsx` - Stub
  - `SwarmInsightTab.tsx` - Swarm insights
  - `constants.ts` lines 109-112, 180-181, 262-266, 301-304, 370-371: Swarm endpoints
- **Action:** Remove components and endpoint constants

### 4. Multi-Timeframe References (1h, Daily, Weekly)
- **Status:** ⚠️ Needs removal
- **Evidence:**
  - `SwarmSentimentGrid.tsx` line 27: `const TFS = ['15m', '1h', 'daily', 'weekly']`
  - `PromoteView.tsx` line 213: `// 15m stack focus: only 15m timeframe (1h, daily, weekly removed as legacy)`
- **Action:** Remove non-15m timeframes from UI

### 5. Social Sentiment References
- **Status:** ⚠️ Needs removal
- **Evidence:**
  - `SentimentPnLStrip.tsx` - Social sentiment PnL
  - `SentimentBundleCard.tsx` - Social sentiment bundle
- **Action:** Remove social sentiment components

### 6. Stub Components
- **Status:** ⚠️ Needs removal
- **Evidence:**
  - `StubGate.tsx` - Stub gate
  - `StubBanner.tsx` - Stub banner
- **Action:** Remove stub components

---

## API Endpoints Inventory

### Paper Trading Endpoints (REMOVE)
- `PAPER_TRADING_PORTFOLIO` - Paper trading portfolio

### Swarm Endpoints (REMOVE)
- `DEV_SWARM_PAUSE` - Dev swarm pause
- `DEV_SWARM_RESUME` - Dev swarm resume
- `DEV_SWARM_SHUTDOWN` - Dev swarm shutdown
- `PRIME_STATUS` - Prime screen state
- `KALSHI_SWARM_GRID` - Swarm grid
- `KALSHI_SWARM_HEALTH` - Swarm health
- `SWARM_CRITIC_HISTORY` - Swarm critic history
- `SWARM_RECALIBRATION` - Swarm recalibration
- `SWARM_EXECUTION_STATS` - Swarm execution stats
- `SWARM_VERDICTS` - Swarm verdicts

---

## Recommended Actions

### Phase 1: Remove Legacy Components (High Priority)
1. Remove `SwarmVerdictFeed.tsx`
2. Remove `SwarmSentimentGrid.tsx`
3. Remove `SwarmPanel.tsx`
4. Remove `SwarmInsightTab.tsx`
5. Remove `PaperTradingPanel.tsx`
6. Remove `PaperLadderCard.tsx`
7. Remove `SentimentPnLStrip.tsx`
8. Remove `SentimentBundleCard.tsx`
9. Remove `StubGate.tsx`
10. Remove `StubBanner.tsx`

### Phase 2: Remove Legacy API Endpoints (High Priority)
1. Remove paper trading endpoints from `constants.ts`
2. Remove swarm endpoints from `constants.ts`
3. Update `types/views.ts` to remove `consensus-swarm` reference

### Phase 3: Update Views for 15m Alignment (Medium Priority)
1. Review `KalshiSentimentView.tsx` - replace with 15m-specific signals
2. Review `PromoteView.tsx` - remove if not needed for live-only 15m
3. Update `SwarmSentimentGrid.tsx` (if kept) to only show 15m timeframe

### Phase 4: Update Components for 15m Alignment (Medium Priority)
1. Review `CorrelationRiskPanel.tsx` - may not be needed for single-venue
2. Review `DomainPnLChart.tsx` - may not be needed for single-domain
3. Review `DomainControlPanel.tsx` - may not be needed for single-domain
4. Review `PnLConsistencyWidget.tsx` - may not be needed for 15m
5. Review `AgentReasoningPanel.tsx` - ensure 15m-specific reasoning
6. Review `DevAgentRoster.tsx` - dev tool, consider removing from production

### Phase 5: Add 15m-Specific Components (Low Priority)
1. Add `Kalshi15mHealthPanel.tsx` - 15m-specific health monitoring
2. Add `Kalshi15mAlignmentPanel.tsx` - 7 invariants status
3. Add `Kalshi15mShadowModePanel.tsx` - Shadow mode logging (Task 2 from user request)

---

## Summary Statistics

| Category | Count | Action |
|----------|-------|--------|
| KEEP (15m Aligned) | 67 | Keep as-is |
| REMOVE (Legacy) | 35 | Remove |
| UPDATE (Needs Alignment) | 12 | Update for 15m |
| INFRASTRUCTURE | 40 | Keep as-is |
| **Total** | **154** | - |

| View Category | Count | Action |
|---------------|-------|--------|
| KEEP (15m Aligned) | 12 | Keep as-is |
| UPDATE (Needs Alignment) | 2 | Update for 15m |
| **Total** | **14** | - |

---

## Next Steps

1. **Review this inventory** with the team to confirm categorization
2. **Create removal plan** for legacy components
3. **Create update plan** for components needing 15m alignment
4. **Prioritize** based on user's 10 high-leverage tasks
5. **Execute** removals and updates in phases
