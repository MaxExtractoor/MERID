# Kalshi UI/UX Audit Report

**Date:** 2026-02-15  
**Scope:** All Kalshi-related frontend views, components, routes, and API wiring

---

## Part 1 — Current State

### 1.1 Navigation & Information Architecture

| Item | Status | Notes |
|------|--------|-------|
| Kalshi sidebar section | **OK** | "Kalshi Suite" group with 3 items (Grid, Dashboard, Portfolio) |
| 2-click reachability | **OK** | All 3 views accessible from sidebar in 1 click |
| Overview card | **OK** | `KalshiHealthCard` on Overview shows connected/offline, breaker, coverage |
| Duplications | **GAP** | `kalshi-dashboard` and `kalshi-grid` overlap significantly — both show health, metrics, agents |
| Paper Session not in Kalshi section | **GAP** | Paper Trading is in "Trading" group, not linked from Kalshi Suite |

### 1.2 Market Discovery

| Item | Status | File | Notes |
|------|--------|------|-------|
| Market list grid | **OK** | `KalshiDashboardView.tsx` | 3-column card grid with question, ticker, odds, volume, expiry |
| Search by text/ticker | **OK** | `KalshiDashboardView.tsx` | Text search input wired to `?search=` param |
| Filter by category | **OK** | `KalshiDashboardView.tsx` | Dropdown + category chips |
| Filter by asset | **OK** | `KalshiDashboardView.tsx` | Dropdown |
| Filter by timeframe | **OK** | `KalshiDashboardView.tsx` | Dropdown |
| Quick tabs (Crypto Hourly, Top Volume, etc.) | **GAP** | — | No preset filter tabs; user must manually select each filter |
| Favorites / watchlist | **GAP** | — | No favorite/star mechanism |
| "My Positions" quick filter | **GAP** | — | No way to filter to only markets with open positions |
| Edge/EV display in market cards | **GAP** | — | Cards show price but not edge or expected value |

### 1.3 Trade Ticket & Execution

| Item | Status | File | Notes |
|------|--------|------|-------|
| Trade ticket component | **GAP** | — | **No trade ticket exists.** Market detail slide-over shows outcomes, bid/ask, but no order entry |
| YES/NO toggle | **GAP** | — | Not implemented |
| Size input (contracts/dollars) | **GAP** | — | Not implemented |
| Fee display | **GAP** | — | Not shown in any order flow |
| Edge/EV per contract | **GAP** | — | Not computed or displayed |
| Validation/error handling | **GAP** | — | No order submission flow to validate |
| Capped/maxed indicator | **GAP** | — | Not surfaced |

### 1.4 Portfolio & PnL

| Item | Status | File | Notes |
|------|--------|------|-------|
| Positions table | **OK** | `KalshiPortfolioView.tsx` | Ticker, side, size, avg price, unrealized, realized |
| Orders table | **OK** | `KalshiPortfolioView.tsx` | Order ID, ticker, side, size, price, filled, status |
| Fills table | **OK** | `KalshiPortfolioView.tsx` | Time, ticker, side, size, price, fee, net |
| Balance card | **OK** | `KalshiPortfolioView.tsx` | USD, available, locked |
| Realized vs unrealized split | **OK** | `KalshiPortfolioView.tsx` | Separate cards |
| Category breakdown | **PARTIAL** | `KalshiPortfolioView.tsx` | Risk tab shows `category_notional` but no per-asset BTC/ETH PnL view |
| Per-interval BTC/ETH views | **GAP** | — | No way to filter portfolio by asset or timeframe |
| PnL chart / equity curve | **GAP** | — | No visual PnL history; only numeric snapshots |

### 1.5 Risk & Health

| Item | Status | File | Notes |
|------|--------|------|-------|
| Kalshi health on Overview | **OK** | `useDashboard.tsx` → `KalshiHealthCard` | Connected/offline, breaker, coverage |
| Daily PnL + limits | **OK** | `KalshiPortfolioView.tsx` (risk tab) | Shows daily PnL vs max, drawdown vs halt |
| Kill switch | **OK** | Both Grid and Portfolio views | Activate/reset with confirm dialog |
| Category exposure | **OK** | `KalshiPortfolioView.tsx` (risk tab) | Notional by category |
| Circuit breaker state | **OK** | `KalshiGridView.tsx` header badges | Breaker state shown |
| Rate limit display | **OK** | Both Dashboard and Portfolio | Orders/min, orders/hr |
| Recent breaches log | **OK** | `KalshiPortfolioView.tsx` (risk tab) | Timestamped breach list |
| Drawdown governance (warning/downsize/halt) | **GAP** | — | Backend has tiered drawdown but UI doesn't show thresholds or current tier |
| Kelly/vol-target utilization | **GAP** | — | No display of current Kelly fraction, vol scaling, or utilization metrics |
| Live risk feed / alert stream | **GAP** | — | No streaming risk alerts; only polled snapshots |
| Spread/liquidity warnings | **GAP** | — | No thin-book or wide-spread indicators |

---

## Part 2 — Gap Summary & Priority

### Critical Gaps (blocking serious Kalshi use)

1. **No trade ticket** — Cannot place orders from the UI. Market detail is read-only.
2. **No PnL chart** — No equity curve or per-trade PnL visualization.
3. **No quick filter tabs** — Discovery requires manual filter selection each time.

### Important Gaps (significantly degrade UX)

4. **No edge/EV display** — Price alone doesn't communicate opportunity quality.
5. **No "My Positions" filter** — Hard to find markets you're already in.
6. **No Kelly/vol utilization display** — Risk panel doesn't show sizing metrics.
7. **No per-asset portfolio filter** — Can't see BTC-only or ETH-only PnL.
8. **Dashboard/Grid overlap** — Two views doing similar things; confusing.

### Nice-to-Have (polish)

9. **Favorites/watchlist** — Common trading app feature.
10. **Drawdown tier indicators** — Show which governance tier is active.
11. **Live risk alert stream** — Real-time risk events.
12. **Spread/liquidity badges** — Warn on thin books.

---

## Part 3 — Implementation Plan

### Phase 1: Trade Ticket + Explorer Tabs (highest impact)
- Add `KalshiTradeTicket` component with YES/NO toggle, size, fees, edge
- Add quick-filter tabs to `KalshiDashboardView` (Crypto Hourly, Top Volume, My Positions)
- Wire trade ticket into market detail slide-over

### Phase 2: Risk & Sizing Panel
- Add Kelly utilization, vol-target, and drawdown tier display to Portfolio risk tab
- Add per-asset portfolio filter (BTC/ETH/SOL tabs)

### Phase 3: Tests
- Component tests for trade ticket, explorer tabs, risk panel
- Verify all Kalshi views render without errors

---

---

## Part 4 — Implementation Status

### Delivered

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 1 | **KalshiTradeTicket** — YES/NO toggle, size (contracts/USD), limit price, fee display, edge, payout viz | `components/KalshiTradeTicket.tsx` | **Done** |
| 2 | **Quick-filter tabs** — All, Crypto Hourly, Crypto 15m, Top Volume, New Markets, My Positions | `views/KalshiDashboardView.tsx` | **Done** |
| 3 | **Sort controls** — Volume, Expiry, Spread | `views/KalshiDashboardView.tsx` | **Done** |
| 4 | **My Positions filter** — Badge count + filter by position tickers | `views/KalshiDashboardView.tsx` | **Done** |
| 5 | **Trade ticket wired** — Market detail slide-over shows trade ticket for active markets | `views/KalshiDashboardView.tsx` | **Done** |
| 6 | **Position badge** — "You have an open position" indicator in market detail | `views/KalshiDashboardView.tsx` | **Done** |
| 7 | **Per-asset portfolio filter** — BTC/ETH/SOL filter chips on portfolio | `views/KalshiPortfolioView.tsx` | **Done** |
| 8 | **Sizing metrics panel** — Kelly util, vol scale, effective fraction, ATR, drawdown tier | `views/KalshiPortfolioView.tsx` | **Done** |
| 9 | **Risk-adjusted metrics** — Sharpe, Sortino, Calmar in risk tab | `views/KalshiPortfolioView.tsx` | **Done** |
| 10 | **Drawdown tier indicator** — Normal/Warning/Downsize/Halt with thresholds | `views/KalshiPortfolioView.tsx` | **Done** |
| 11 | **KalshiModeBadge** — PAPER/SHADOW/LIVE badge on all 3 Kalshi views | `components/KalshiModeBadge.tsx` | **Done** |
| 12 | **API endpoints** — `KALSHI_SIZING_METRICS`, `KALSHI_PNL_HISTORY` added | `config/constants.ts` | **Done** |
| 13 | **Component tests** — Dashboard (15 tests), Portfolio (16 tests), TradeTicket (15 tests) | `__tests__/` | **Done** |

### New Files Created

- `web/react/src/components/KalshiTradeTicket.tsx` — Trade ticket component
- `web/react/src/components/KalshiModeBadge.tsx` — Mode badge component
- `web/react/src/views/__tests__/KalshiDashboardView.test.tsx` — Dashboard tests
- `web/react/src/views/__tests__/KalshiPortfolioView.test.tsx` — Portfolio tests
- `web/react/src/components/__tests__/KalshiTradeTicket.test.tsx` — Trade ticket tests

### Modified Files

- `web/react/src/views/KalshiDashboardView.tsx` — Quick tabs, sort, trade ticket, position badge, mode badge
- `web/react/src/views/KalshiPortfolioView.tsx` — Asset filter, sizing panel, drawdown tier, mode badge
- `web/react/src/views/KalshiGridView.tsx` — Mode badge
- `web/react/src/config/constants.ts` — New API endpoints

---

## Files Audited

| File | Purpose | Lines |
|------|---------|-------|
| `views/KalshiGridView.tsx` | Agent grid matrix, controls, fills | 762 |
| `views/KalshiDashboardView.tsx` | Market discovery, catalog, health | 452 |
| `views/KalshiPortfolioView.tsx` | Positions, orders, fills, risk | 440 |
| `components/Sidebar.tsx` | Navigation structure | 113 |
| `hooks/useDashboard.tsx` | KalshiHealthCard, health hooks | 511 |
| `config/constants.ts` | API endpoints, Kalshi section | 600 |
| `types/views.ts` | View type union | 47 |
| `App.tsx` | Route/view mapping | 166 |
