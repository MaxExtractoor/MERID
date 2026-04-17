# MERID UI Audit — Trading Dashboard Best Practices

> Audited: 2026-02-06 against codebase state  
> Stack: React 18 + Tailwind + Recharts (installed) + Lucide icons  
> Legend: ✅ Implemented | 🟡 Partial (API only or rough) | ❌ Missing

---

## 1. Core Views — Portfolio

| Item | Status | Evidence |
|------|--------|----------|
| Current equity / PnL (realized + unrealized) | ✅ | `LivePortfolioValue.tsx` (WS), `TradeFloor.tsx` risk strip, `Positions.tsx` summary cards, `OperatorDashboard.tsx` |
| Open positions (size, entry, current price, PnL) | ✅ | `Positions.tsx` — full card grid with per-position PnL, `Trading.tsx` DataTable |
| Exposure by instrument/sector and overall leverage | 🟡 | `Overview.tsx` ExposureBar + top symbol %. `LiveRiskStrip.tsx` shows top exposure. No sector breakdown or leverage ratio widget. |

## 2. Core Views — Orders & Activity

| Item | Status | Evidence |
|------|--------|----------|
| Live order blotter (working, filled, canceled, rejected) | ✅ | `Orders.tsx` — full table with status filter (open/filled/cancelled/rejected). `OpenOrdersPanel.tsx` — real-time WS updates. `TradeFloor.tsx` live orders table. |
| Recent fills stream with timestamps and venue | ✅ | `Trading.tsx` fills table with DataTableEnhanced (timestamp, symbol, side, size, price, venue) |
| Error/reject log surfaced to UI (not just logs) | 🟡 | `Orders.tsx` shows rejected status. `TradeFloor.tsx` shows order_rejected events. No dedicated error/reject panel with reasons. |

## 3. Core Views — Market Data

| Item | Status | Evidence |
|------|--------|----------|
| Key instruments with price, volume, basic indicators | 🟡 | `PriceTicker.tsx` shows price + volume for BTC/ETH/SOL. `LivePriceStream` component. No SMA/EMA/VWAP indicators. |
| Watchlist / screener for core universe | 🟡 | `Overview.tsx` loads watchlist data for 5 symbols. `MarketHeatmap.tsx` shows color-coded grid. No editable watchlist or screener. |

## 4. Swarm & System Health

| Item | Status | Evidence |
|------|--------|----------|
| Swarm status: mode, active agents, queue depth | ✅ | `OperatorStatusBar.tsx` mode badge. `OperatorDashboard.tsx` agent count + active tasks. `DevSwarm.tsx` full stats. |
| Latency charts (decision latency, order round-trip) | ❌ | No latency visualization. Backend has `execution_time_ms` in ExplainabilityPanel but no chart. |
| Error rate, retry counts, circuit-breaker status | ✅ | `LiveRiskStrip.tsx` circuit breaker card. `useRiskProtections.ts` — error_count, state, recent_events. |
| "All green / degraded" summary indicator | ✅ | `OperatorStatusBar.tsx` — CB OK/TRIPPED badge. `Health.tsx` — service status indicators. `getOverallRiskStatus()` helper. |

## 5. Risk & Safety

| Item | Status | Evidence |
|------|--------|----------|
| Risk limits vs current utilization (per-instrument and portfolio) | 🟡 | `useRiskProtections.ts` has `RiskLimitsStatus` with daily_loss_utilization_pct, max_per_symbol_exposure. `LiveRiskStrip.tsx` shows margin utilization %. **No visual bar/gauge for limit utilization.** |
| Drawdown and daily loss vs. thresholds | 🟡 | `LiveRiskStrip.tsx` shows daily drawdown % and max drawdown %. `TradeFloor.tsx` has `DrawdownChart` component. **No threshold lines on charts.** |
| Breach alerts / heatmap (near/over limits) | 🟡 | `LiveRiskStrip.tsx` alert counts (critical/warning). `useRiskMetrics.ts` tracks threshold_breached events. **No risk heatmap widget.** |
| Position-size / risk-per-trade helper | ❌ | No position-size calculator widget. |

## 6. Control Plane

| Item | Status | Evidence |
|------|--------|----------|
| Buttons/API for pause, resume, shutdown (with confirmation) | ✅ | `OperatorControlPlane.tsx` — pause/resume swarm, shutdown with confirmation, system stop. Backend: POST /pause, /resume, /shutdown. |
| Clear indication of current trading mode and venue connectivity | ✅ | `OperatorStatusBar.tsx` — mode badge (PAPER/LIVE/etc), WS connected indicator. `TradeFloor.tsx` — mode badge + WS status. |
| Ability to disable a specific strategy/agent | ❌ | No per-agent disable toggle. `AgentStatusPanel` shows agents but no enable/disable control. |

## 7. Explainability & Audit

| Item | Status | Evidence |
|------|--------|----------|
| Trade detail view with rationale (why this trade/size/timing) | ✅ | `ExplainabilityPanel.tsx` — full decision detail with factors, weights, alternatives, data sources, confidence. `TradeFloor.tsx` shows reasoning per event. `OpinionFeed.tsx` + `AgentOpinionChart.tsx`. |
| Links from trades to risk events and audit trail | 🟡 | `OperatorActivityStream.tsx` has audit trail tab. `ExplainabilityPanel` shows per-decision detail. **No direct linking between a specific trade and its audit entry.** |

---

## Summary Scorecard

| Category | Score | Notes |
|----------|-------|-------|
| Portfolio | 2.5/3 | Missing sector/leverage breakdown |
| Orders & Activity | 2.5/3 | Missing dedicated error/reject panel |
| Market Data | 1/2 | No indicators, no editable watchlist |
| Swarm & System Health | 3/4 | Missing latency charts |
| Risk & Safety | 1/4 | Data exists but **no visual bar/gauge/heatmap widgets** |
| Control Plane | 2/3 | Missing per-agent disable |
| Explainability & Audit | 1.5/2 | Missing trade→audit linking |
| **TOTAL** | **13.5/21 (64%)** | |

---

## Priority Gaps to Close (ordered by 3am-value)

### P0 — Safety-Critical Visualization (this session)
1. **Streaming PnL / equity line chart** — Recharts `LineChart` with live buffer
2. **Risk limit utilization bars** — horizontal bars showing current vs limit
3. **Risk heatmap** — instruments colored by PnL or % of limit
4. **Drawdown card with sparkline** — equity, day PnL, max drawdown, threshold line

### P1 — Control Enhancements (next session)
5. Per-agent enable/disable toggle
6. Dedicated error/reject log panel
7. Latency chart (decision + order round-trip)

### P2 — Nice-to-Have Analytics
8. Editable watchlist / screener
9. SMA/EMA/VWAP overlays on price charts
10. Position-size calculator widget
11. Trade → audit trail deep linking

---

## API Endpoints Needed for P0

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /api/metrics/equity_series?window=1d` | Time-series equity data for chart | ❌ New |
| `GET /api/metrics/risk_utilization` | Per-limit current vs max for bars | ❌ New |
| `GET /api/risk/protections` | Circuit breaker + limits (existing) | ✅ Exists |
| `GET /api/v1/risk/metrics` | PnL, drawdown, margin (existing) | ✅ Exists |
| `GET /api/operator/summary` | Bundled dashboard data (existing) | ✅ Exists |
