# MERID Dashboard Extension Design & Wiring Plan

**Status**: Design & Wiring Only — No Implementation
**Date**: 2026-03-25
**Purpose**: Systematic design to extend the React dashboard to surface all critical metrics for fear/greed, volatility/sizing, balance/P&L, trades/fees, effective limits, WS health, swarm quality, and crypto spot vs Kalshi contracts.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [SwarmConsensusMatrix Enhancements](#1-swarmconsensusmatrix-enhancements)
3. [Overview Dashboard Improvements](#2-overview-dashboard-improvements)
4. [TopBar & Global Chrome](#3-topbar--global-chrome)
5. [Explicit Metric Mapping Table](#4-explicit-metric-mapping-table)
6. [Missing Metrics & Backend Requirements](#5-missing-metrics--backend-requirements)
7. [Implementation Phases](#6-implementation-phases)

---

## Executive Summary

This document provides a **design-only blueprint** for extending the existing MERID React dashboard (`web/react/src`) to cleanly surface:

- **Fear/Greed**: Including synthetic FG across assets
- **Volatility & Sizing**: Target vol, realized vol, vol band, vol scale, ATR scale, vol targeting
- **Balance & P&L**: Total value, daily P&L, equity curve over time, drawdown, DD tiers
- **Trades & Fees**: Orders placed/filled/cancelled, churn cycle, resting edge, max price, fee drag
- **Effective Limits**: Kelly f, Kelly utilization, effective risk after vol scaling
- **WS Feed Health**: Kalshi WS lag, execution bus, continuous trader heartbeat
- **Swarm Quality**: Consensus/debate, calibration/Brier, forecasters, resolver, critic, auto-promoter
- **Crypto Spot vs Kalshi**: BTC/ETH/SOL/XRP/DOGE spot + contracts (prices, exposures, P&L, basis/hedge)
- **Swarm Status Taxonomy**: ready/forming/conflicted/stale/bullish/bearish across all cells

The design is based on:
- **Existing endpoints** in `web/react/src/config/constants.ts`
- **Current UI components**: `SwarmConsensusMatrix.tsx`, `Overview.tsx`, `TopBar.tsx`, `ExecutionGateStrip.tsx`
- **Systematic mapping**: config → APIs → UI for each metric

---

## 1. SwarmConsensusMatrix Enhancements

**Current State** (`web/react/src/views/SwarmConsensusMatrix.tsx`):
- Displays asset × timeframe grid with per-cell: consensus probability, direction, confidence, status (ready/forming/conflicted/stale), size band, voting agents, disagreements, proposals
- Data source: `KALSHI_CONSENSUS_ALL` endpoint (`/api/v1/kalshi/consensus/all`)
- Simple detail panel with agent proposals, rationale, track records

**Design Upgrade**: Four-zone layout with global header, matrix grid, row aggregates, and detail drawer.

---

### 1.1 Global Header Strip

**Purpose**: Swarm-level overview visible at all times.

**Metrics to Display**:

| Metric | Display | Data Source(s) | Missing Fields |
|--------|---------|----------------|----------------|
| **Synthetic Fear/Greed** | Numeric value + label (e.g., "Greed 72") | `KALSHI_FEAR_GREED_SUMMARY` (`/api/v1/kalshi/sentiment/fear-greed/market-summary`) | Needs cross-asset synthetic FG calculation |
| **Vol Snapshot** | "Target: 15% / Realized: 12% / Band: 10-20%" | `KALSHI_SIZING_METRICS` (`/api/v1/kalshi/sizing-metrics`) | May need aggregate vol metrics endpoint |
| **Vol Scale** | "Vol Scale: 0.85" | `KALSHI_SIZING_METRICS` | Present if backend computes |
| **ATR Scale** | "ATR Scale: 1.1" | `KALSHI_SIZING_METRICS` | Present if backend computes |
| **Heartbeat: Last Consensus Update** | "Updated 12s ago" | Derive from `KALSHI_CONSENSUS_ALL` timestamps | Age calculation client-side |
| **Kalshi WS Health/Lag** | "WS: Healthy / Lag: 45ms" | `KALSHI_GRID_HEALTH` (`/api/v1/kalshi-grid/health`) + `KALSHI_HEALTH` (`/api/v1/kalshi/health`) | WS lag metric may need addition |
| **Execution Bus Health** | "Exec Bus: OK" | New endpoint or extend `SYSTEM_EXECUTION_GATE` | **NEW**: Execution bus status |
| **Deployment Phase** | "Phase: LIVE" | `KALSHI_DEPLOYMENT_STATUS` (`/api/v1/kalshi/deployment/status`) | Present |
| **Auto-Promoter State** | "Auto-Promo: Active" | `AUTO_PROMOTER_STATUS` (`/api/v1/kalshi/deployment/auto-promoter/status`) | Present |
| **State Chips: Ready/Forming/Conflicted/Stale/Bullish/Bearish Counts** | "Ready: 12 / Forming: 3 / Conflicted: 1 / Stale: 0 / Bullish: 8 / Bearish: 5" | Derived from `KALSHI_CONSENSUS_ALL` | Computed client-side from consensus data |

**Layout**:
```
┌────────────────────────────────────────────────────────────────────────┐
│ [FG: 72 Greed] [Vol: 15%→12%, Scale: 0.85, ATR: 1.1]                │
│ [❤️ Consensus: 12s] [WS: OK, 45ms] [Exec: OK] [Phase: LIVE] [Auto: ✓] │
│ [Ready: 12] [Forming: 3] [Conflicted: 1] [Stale: 0] [↑8] [↓5]        │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 1.2 Matrix Grid (Per-Cell Enhancements)

**Current Per-Cell Display**:
- Consensus probability, direction, confidence, status, size band, voting agents, disagreement flags

**Planned Additions**:

| New Metric | Display | Data Source | Missing Fields |
|------------|---------|-------------|----------------|
| **Per-Cell Brier Score** | "Brier: 0.12" | **NEW**: Extend consensus aggregator to compute per-cell Brier | Backend: consensus aggregator |
| **Calibration Grade** | "Cal: A-" | **NEW**: Per-cell calibration metric | Backend: performance tracker |
| **Prob Volatility** | "PV: 0.05 (stable)" | **NEW**: Std dev of probability over rolling window | Backend: consensus aggregator |
| **Vol/Sizing Band Indicator** | Visual bar or % (e.g., "Vol Band: 10-20%") | Map from `KALSHI_SIZING_METRICS` by asset/timeframe | May need per-cell vol band in backend |

**Layout** (per cell):
```
┌─────────────────────┐
│ YES 68% ████████    │
│ ••••• READY         │
│ Size: BASE          │
│ 5 agents  ⚠1        │
│ Brier: 0.12  Cal: A-│
│ PV: 0.05 (stable)   │
│ Vol Band: 10-20%    │
└─────────────────────┘
```

---

### 1.3 Row Aggregates (Per-Asset)

**Purpose**: Summary metrics for each asset (e.g., BTC, ETH, SOL) aggregated across timeframes.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **Total Calls** | "Calls: 45" | Count of total consensus decisions per asset | Derive from `KALSHI_CONSENSUS_ALL` or new aggregate endpoint |
| **Forecaster Count** | "Forecasters: 12" | `METRICS_FORECASTERS` (`/api/v1/kalshi/metrics/forecasters`) filtered by asset | May need asset-level rollup |
| **Total Forecasts** | "Forecasts: 345" | Sum of forecasts across forecasters for asset | **NEW**: Aggregate in backend |
| **Average Brier** | "Avg Brier: 0.14" | Average Brier across all cells for asset | **NEW**: Backend aggregation |
| **Net Directional Bias** | "Bullish: 4, Bearish: 2" | Count of yes/no consensus directions | Derive from `KALSHI_CONSENSUS_ALL` |
| **Effective Risk Utilization** | "Risk Util: 35%" | Share of asset's vol/risk band used | Map from `KALSHI_SIZING_METRICS` + `KALSHI_RISK` | **NEW**: Per-asset effective risk calculation |

**Layout** (row footer):
```
BTC  [Calls: 45] [Forecasters: 12] [Forecasts: 345] [Avg Brier: 0.14] [↑4 ↓2] [Risk: 35%]
```

---

### 1.4 Detail Drawer (Per-Cell)

**Purpose**: Expanded view when clicking a cell, with tabbed interface.

**Tabs**:

#### Tab 1: Debate History/Intensity
- **Data Source**: `SWARM_CRITIC_HISTORY` (`/api/v1/kalshi/swarm/critic/history`) + debate endpoints (if they exist in cognitive_api.py)
- **Display**: Timeline of debate messages, disagreement width, debate lift, critic interventions
- **Missing**: May need per-cell debate filtering or new endpoint

#### Tab 2: Cross-Timeframe Alignment
- **Data Source**: `XTF_SIGNAL` (`/api/v1/xtf/signal/{asset}`) or `XTF_SIGNALS_ALL` (`/api/v1/xtf/signals`)
- **Display**: Show consensus across all timeframes for the same asset, alignment score
- **Missing**: Cross-timeframe alignment metric

#### Tab 3: Critic & Resolver Activity
- **Critic Feed**: `SWARM_CRITIC_HISTORY`
- **Recalibration**: `SWARM_RECALIBRATION` (`/api/v1/kalshi/swarm/recalibration`)
- **Resolver Metrics**: `METRICS_RESOLVER` (`/api/v1/kalshi/metrics/resolver`)
- **Display**: Recent critic messages, edge recalibration events, resolver outcome accuracy

#### Tab 4: Execution Attribution
- **Data Source**: `KALSHI_GRID_AGENT_ORDERS` + `KALSHI_GRID_FILLS` + `KALSHI_PNL`
- **Display**: Orders placed/filled for this cell, P&L attribution if lineage exists
- **Missing**: Need to link orders/fills to specific asset/timeframe cells

**Layout**:
```
┌───────────────────────────────────────────────────────────┐
│ BTC 15m  [Debate | XTF Align | Critic/Resolver | Exec]   │
├───────────────────────────────────────────────────────────┤
│ (Selected tab content)                                    │
└───────────────────────────────────────────────────────────┘
```

---

## 2. Overview Dashboard Improvements

**Current State** (`web/react/src/views/Overview.tsx`):
- Kill switch banner, `ExecutionGateStrip`, reboot controls, health/risk/agent cards, Kalshi balance hero, positions, recent orders/fills, agent activity, console

**Design Upgrade**: Organized into clear zones with comprehensive metrics.

---

### 2.1 Mode & Safety Rail (Top Section)

**Purpose**: Always-visible status bar showing system mode and safety state.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **PM Live/Paper Mode** | "PM: LIVE" badge | `KALSHI_GRID_MODE` (`/api/v1/kalshi-grid/mode`) | Present |
| **Crypto Mode** | "Crypto: LIVE" badge | `PIPELINE_VENUE_MODE` (`/api/v1/pipeline/venue-mode`) | May need crypto-specific mode flag |
| **Global "Live Unlock"** | "Unlocked" / "Locked" indicator | `SYSTEM_MODE_SAFETY` (`/api/v1/system/mode-safety`) | Present |
| **Kill Switch** | Red "HALTED" or green "CLEAR" | `OPERATOR_KILL_SWITCH_STATUS` | Present (already in ExecutionGateStrip) |
| **Execution Gates** | "CLEAR" / "LIMITED" / "BLOCKED" | `SYSTEM_EXECUTION_GATE` | Present (already in ExecutionGateStrip) |
| **Kalshi WS Health** | "WS: Healthy / Degraded / Down" | `KALSHI_GRID_HEALTH` + `KALSHI_HEALTH` | Present |

**Layout**: Extend `ExecutionGateStrip.tsx` or create `ModeSafetyRail.tsx` component.

---

### 2.2 Risk and Limits Strip

**Purpose**: Compare configured vs effective limits, show Kelly metrics, vol scaling.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **Configured Limits** | "Max Exp: $50k, Max DD: 15%" | **NEW**: Config limits endpoint or extend `KALSHI_RISK` | Backend: expose config limits |
| **Effective Limits** | "Eff Exp: $42k, Eff DD: 12%" | `KALSHI_RISK` + vol scaling factors | Backend: effective limits after vol scaling |
| **Kelly f** | "Kelly: 0.15" | `KALSHI_SIZING_METRICS` | May need Kelly fraction in sizing metrics |
| **Kelly Utilization** | "Kelly Util: 65%" | Ratio of actual size to Kelly-optimal | **NEW**: Backend calculation |
| **Vol Scale** | "Vol Scale: 0.85" | `KALSHI_SIZING_METRICS` | Present if backend computes |
| **Vol Band** | "Vol Band: 10-20%" | `KALSHI_SIZING_METRICS` | Present if backend computes |
| **ATR Scale** | "ATR Scale: 1.1" | `KALSHI_SIZING_METRICS` | Present if backend computes |
| **Overall Effective Risk** | "Eff Risk: $35k (70% of max)" | Derived from above | Backend: aggregate effective risk |

**Layout**:
```
┌──────────────────────────────────────────────────────────────┐
│ Risk & Limits                                                │
├──────────────────────────────────────────────────────────────┤
│ Config: Exp $50k / DD 15%  →  Effective: Exp $42k / DD 12%  │
│ Kelly: 0.15 (Util: 65%)  │  Vol Scale: 0.85  │  ATR: 1.1    │
│ Vol Band: 10-20%  │  Effective Risk: $35k (70%)             │
└──────────────────────────────────────────────────────────────┘
```

---

### 2.3 Portfolio Value & P&L Panel

**Purpose**: Total portfolio value, daily P&L, equity curve, drawdown, DD tier, fee drag.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **Total Value (Per Venue)** | "Kalshi: $48,500" | `KALSHI_BALANCE` (`/api/v1/kalshi/balance`) | Present |
| **Total Value (Combined)** | "Total: $48,500" | Aggregate across venues | Multi-venue aggregation if crypto added |
| **Daily P&L** | "+$1,250 (2.5%)" | `KALSHI_PNL` (`/api/v1/kalshi/pnl`) | Present (`daily_pnl_usd`) |
| **Equity Curve Over Time** | Line chart | `/api/operator/equity-series` (or `KALSHI_EQUITY_SERIES` if exists) | Present in operator.py |
| **Current Drawdown** | "DD: -5.2%" | `KALSHI_PNL` (`drawdown_pct`) | Present |
| **Max Drawdown** | "Max DD: -8.5%" | `KALSHI_PNL` or new field | May need historical max DD |
| **DD Tier** | "DD Tier: 2 (Moderate)" | `KALSHI_RISK_DD_GUARD` (`/api/v1/kalshi/risk/dd-guard`) | May need DD tier classification |
| **Fee Drag** | "Fees: -$45 (0.1%)" | **NEW**: Aggregate fees from fills | Backend: sum fees from `KALSHI_FILLS` |

**Layout**:
```
┌──────────────────────────────────────────────────────────────┐
│ Portfolio Value & P&L                                        │
├──────────────────────────────────────────────────────────────┤
│ Total: $48,500  │  Kalshi: $48,500  │  Crypto: $0           │
│ Daily P&L: +$1,250 (2.5%) ↑                                  │
│ [Equity Curve Chart: 7d rolling]                             │
│ Drawdown: -5.2% (Max: -8.5%)  │  DD Tier: 2 (Moderate)      │
│ Fee Drag: -$45 (0.1% of volume)                              │
└──────────────────────────────────────────────────────────────┘
```

---

### 2.4 Positions & Trades Panel

**Purpose**: Open positions with day P&L, in/out-of-band risk flags, trade counts, churn, resting orders.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **Open Positions** | List of positions with ticker, size, P&L | `KALSHI_POSITIONS` (`/api/v1/kalshi/positions`) | Present |
| **Day P&L Per Asset** | "BTC: +$150, ETH: -$20" | Aggregate P&L by asset from positions | May need per-asset rollup |
| **In/Out-of-Band Risk Flags** | "⚠ BTC 15m: Out of band" | Compare position size to vol band | **NEW**: Risk band checker |
| **Orders Placed/Filled/Cancelled** | "Orders: 45 placed, 42 filled, 3 cancelled" | Aggregate from `KALSHI_ORDERS` | Backend: order lifecycle stats |
| **Churn Cycle Metrics** | "Churn: 2.5 (orders per fill)" | Orders placed / fills | **NEW**: Backend calculation |
| **Resting Orders** | List of open orders with resting edge | `KALSHI_ORDERS` (filter `status: resting`) | Present |
| **Resting Edge** | "Resting edge: +2.5¢ avg" | Difference between order price and fair value | **NEW**: Backend calculation |
| **Max Price vs Fair Value** | "Max: 72¢ (FV: 68¢, +4¢)" | Compare order price to consensus prob | Derive from consensus + order data |

**Layout**:
```
┌──────────────────────────────────────────────────────────────┐
│ Positions & Trades                                           │
├──────────────────────────────────────────────────────────────┤
│ [Position List: BTC +$150, ETH -$20, SOL +$30]  ⚠1 OOB      │
│ Orders: 45 placed, 42 filled, 3 cancelled  │  Churn: 2.5    │
│ [Resting Orders: 5 orders, Avg Edge: +2.5¢]                 │
└──────────────────────────────────────────────────────────────┘
```

---

### 2.5 Crypto Spot vs Kalshi Panel

**Purpose**: Side-by-side comparison of crypto spot vs Kalshi contracts for BTC/ETH/SOL/XRP/DOGE.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **Spot Prices** | "BTC Spot: $42,150" | **NEW**: `KALSHI_CRYPTO_RTI` endpoint or external crypto feed | Backend: crypto spot price integration |
| **Kalshi Contract Prices** | "BTC Kalshi: $42,100 (68%)" | `KALSHI_MARKETS` + market catalog | Map Kalshi crypto tickers |
| **Exposures** | "Spot: 0.5 BTC, Kalshi: 100 contracts" | `KALSHI_POSITIONS` + crypto positions | May need crypto position tracking |
| **P&L** | "Spot: +$500, Kalshi: +$200" | Aggregate P&L by venue | Per-venue P&L rollup |
| **Basis/Hedge** | "Basis: +$50 (0.12%)" | Spot - Kalshi price | **NEW**: Backend calculation |

**Assets**: BTC, ETH, SOL, XRP, DOGE

**Layout**:
```
┌──────────────────────────────────────────────────────────────┐
│ Crypto: Spot vs Kalshi                                       │
├──────────────────────────────────────────────────────────────┤
│ BTC │ Spot: $42,150 (0.5)  │  Kalshi: $42,100 (100 ct)      │
│     │ P&L: +$500           │  P&L: +$200  │  Basis: +$50    │
│ ETH │ Spot: $2,250 (2.0)   │  Kalshi: $2,240 (50 ct)        │
│     │ P&L: -$50            │  P&L: +$25   │  Basis: +$10    │
│ (Similar for SOL, XRP, DOGE)                                 │
└──────────────────────────────────────────────────────────────┘
```

---

### 2.6 Swarm Summary Strip

**Purpose**: Compact swarm health and quality metrics.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **Consensus Health** | "Consensus: Healthy" | Derive from `KALSHI_CONSENSUS_ALL` (e.g., % ready) | Backend: consensus health score |
| **Average Brier** | "Avg Brier: 0.15" | `METRICS_FORECASTERS` aggregate | Backend: average Brier across forecasters |
| **Calibration Error** | "Cal Error: 0.08" | `KALSHI_GRID_PERFORMANCE_CALIBRATION` (`/api/v1/kalshi-grid/performance/calibration`) | Present |
| **Forecaster Counts** | "Forecasters: 15 active" | `METRICS_FORECASTERS` | Present |
| **Asset States** | "Ready: 12, Forming: 3, Conflicted: 1, Stale: 0" | Derive from `KALSHI_CONSENSUS_ALL` | Computed client-side |

**Layout**:
```
┌──────────────────────────────────────────────────────────────┐
│ Swarm Summary                                                │
│ Consensus: ✓ Healthy │ Brier: 0.15 │ Cal: 0.08 │ F: 15      │
│ Ready: 12 │ Forming: 3 │ Conflicted: 1 │ Stale: 0           │
└──────────────────────────────────────────────────────────────┘
```

---

### 2.7 Automation Block

**Purpose**: Continuous trader status, deployment phase, auto-promoter.

**Metrics**:

| Metric | Display | Data Source | Missing Fields |
|--------|---------|-------------|----------------|
| **Continuous Trader Status** | "Continuous: Running" | `KALSHI_GRID_STATUS` (`running` field) | Present |
| **Deployment Phase** | "Phase: LIVE" | `KALSHI_DEPLOYMENT_STATUS` | Present |
| **Auto-Promoter Status** | "Auto-Promo: Active, 3 promotions today" | `AUTO_PROMOTER_STATUS` + `AUTO_PROMOTER_PROMOTIONS` | Present |

**Layout**:
```
┌──────────────────────────────────────────────────────────────┐
│ Automation                                                   │
│ Continuous: ✓ Running │ Phase: LIVE │ Auto-Promo: ✓ (3)     │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. TopBar & Global Chrome

**Current State** (`web/react/src/components/TopBar.tsx`):
- PM mode badge, balance, daily P&L, HTTP health indicator, search box (non-functional)

**Design Upgrade**: Enhanced top bar with mode badges, risk state pill, heartbeat row.

---

### 3.1 Mode Badges

**Metrics**:

| Badge | Data Source |
|-------|-------------|
| **PM Live/Paper** | `KALSHI_GRID_MODE` |
| **Crypto Live/Paper** | `PIPELINE_VENUE_MODE` |
| **Global "Live Unlocked / Locked"** | `SYSTEM_MODE_SAFETY` |

**Layout**:
```
[PM: LIVE 🔴] [Crypto: PAPER 🟡] [🔓 Unlocked]
```

---

### 3.2 Risk State Pill

**Purpose**: Compact risk indicator combining multiple metrics.

**Metrics**:

| Metric | Data Source |
|--------|-------------|
| **Risk Utilization** | `KALSHI_RISK` (exposure / max_exposure) |
| **Vol Scale/Band** | `KALSHI_SIZING_METRICS` |
| **Synthetic FG** | `KALSHI_FEAR_GREED_SUMMARY` |
| **Risk State Label** | "Risk-On" / "Balanced" / "Risk-Off" (derived from above) |

**Layout**:
```
[Risk: 65% | Vol: 0.85 | FG: 72 | Risk-On 🟢]
```

---

### 3.3 Heartbeat Row

**Metrics**:

| Metric | Data Source | Missing Fields |
|--------|-------------|----------------|
| **WS Feed Health/Lag** | `KALSHI_GRID_HEALTH` + `KALSHI_HEALTH` | WS lag metric |
| **Last Consensus Update Age** | Derive from `KALSHI_CONSENSUS_ALL` timestamps | Computed client-side |
| **Execution Bus Health** | **NEW**: Execution bus endpoint | Backend: execution bus status |

**Layout**:
```
[❤️ WS: OK 45ms] [⏱️ Consensus: 12s] [🚌 Exec: OK]
```

---

### 3.4 Search Box

**Recommendation**: Either:
1. Wire to command palette (keyboard shortcut to search agents, markets, commands)
2. Remove/hide if not implemented

---

## 4. Explicit Metric Mapping Table

**Format**: UI Slot → Metric(s) → Data Source → Missing Fields

| UI Slot | Metric(s) | Current Data Source | Missing Fields/Notes |
|---------|-----------|---------------------|---------------------|
| **Swarm Matrix: Global Header** | | | |
| → FG Indicator | Synthetic Fear/Greed | `KALSHI_FEAR_GREED_SUMMARY` | **NEW**: Cross-asset synthetic FG |
| → Vol Snapshot | Target vol, Realized vol, Vol band | `KALSHI_SIZING_METRICS` | May need aggregate endpoint |
| → Vol Scale | Vol scale factor | `KALSHI_SIZING_METRICS` | Present if backend computes |
| → ATR Scale | ATR scale factor | `KALSHI_SIZING_METRICS` | Present if backend computes |
| → Consensus Heartbeat | Last update age | `KALSHI_CONSENSUS_ALL` timestamps | Computed client-side |
| → WS Health | Kalshi WS status, lag | `KALSHI_GRID_HEALTH`, `KALSHI_HEALTH` | **NEW**: WS lag metric |
| → Exec Bus Health | Execution bus status | **NEW**: Exec bus endpoint | Backend: execution bus module |
| → Deployment Phase | Current phase | `KALSHI_DEPLOYMENT_STATUS` | Present |
| → Auto-Promoter | Status, promotion count | `AUTO_PROMOTER_STATUS`, `AUTO_PROMOTER_PROMOTIONS` | Present |
| → State Chips | Ready/Forming/Conflicted/Stale/Bullish/Bearish counts | `KALSHI_CONSENSUS_ALL` | Computed client-side |
| **Swarm Matrix: Per-Cell** | | | |
| → Consensus Prob | Consensus probability | `KALSHI_CONSENSUS_ALL` | Present |
| → Direction | Yes/No/Neutral | `KALSHI_CONSENSUS_ALL` | Present |
| → Confidence | Confidence level | `KALSHI_CONSENSUS_ALL` | Present |
| → Status | Ready/Forming/Conflicted/Stale | `KALSHI_CONSENSUS_ALL` | Present |
| → Size Band | Small/Reduced/Base/Large | `KALSHI_CONSENSUS_ALL` | Present |
| → Brier Score | Per-cell Brier | **NEW**: Consensus aggregator | Backend: per-cell Brier calculation |
| → Calibration Grade | Per-cell calibration | **NEW**: Performance tracker | Backend: per-cell calibration |
| → Prob Volatility | Std dev of prob | **NEW**: Consensus aggregator | Backend: rolling prob volatility |
| → Vol/Sizing Band | Vol band indicator | `KALSHI_SIZING_METRICS` | May need per-cell mapping |
| **Swarm Matrix: Row Aggregates** | | | |
| → Total Calls | Count of consensus decisions | `KALSHI_CONSENSUS_ALL` or new aggregate | Backend: per-asset call count |
| → Forecaster Count | Active forecasters | `METRICS_FORECASTERS` | May need per-asset filter |
| → Total Forecasts | Sum of forecasts | **NEW**: Aggregate endpoint | Backend: per-asset forecast count |
| → Average Brier | Avg Brier per asset | **NEW**: Aggregate endpoint | Backend: per-asset Brier avg |
| → Net Directional Bias | Bullish/Bearish counts | `KALSHI_CONSENSUS_ALL` | Computed client-side |
| → Effective Risk Util | Risk utilization % | `KALSHI_SIZING_METRICS`, `KALSHI_RISK` | **NEW**: Per-asset effective risk |
| **Swarm Matrix: Detail Drawer** | | | |
| → Debate History | Debate messages, lift | `SWARM_CRITIC_HISTORY`, cognitive_api debate endpoints | May need per-cell debate filter |
| → XTF Alignment | Cross-timeframe consensus | `XTF_SIGNAL`, `XTF_SIGNALS_ALL` | May need alignment score |
| → Critic Feed | Critic messages | `SWARM_CRITIC_HISTORY` | Present |
| → Recalibration | Edge recalibration events | `SWARM_RECALIBRATION` | Present |
| → Resolver Metrics | Resolver accuracy | `METRICS_RESOLVER` | Present |
| → Execution Attribution | Orders, fills, P&L per cell | `KALSHI_GRID_AGENT_ORDERS`, `KALSHI_GRID_FILLS`, `KALSHI_PNL` | Need cell-to-order lineage |
| **Overview: Mode & Safety** | | | |
| → PM Mode | Live/Paper | `KALSHI_GRID_MODE` | Present |
| → Crypto Mode | Live/Paper | `PIPELINE_VENUE_MODE` | May need crypto mode flag |
| → Global Live Unlock | Locked/Unlocked | `SYSTEM_MODE_SAFETY` | Present |
| → Kill Switch | Status | `OPERATOR_KILL_SWITCH_STATUS` | Present |
| → Execution Gate | Clear/Limited/Blocked | `SYSTEM_EXECUTION_GATE` | Present |
| → Kalshi WS Health | Status | `KALSHI_GRID_HEALTH`, `KALSHI_HEALTH` | Present |
| **Overview: Risk & Limits** | | | |
| → Configured Limits | Max exposure, DD | **NEW**: Config limits endpoint | Backend: expose limits config |
| → Effective Limits | Effective exposure, DD | `KALSHI_RISK` + vol scaling | **NEW**: Effective limits calc |
| → Kelly f | Kelly fraction | `KALSHI_SIZING_METRICS` | May need Kelly in sizing |
| → Kelly Utilization | Actual / Kelly optimal | **NEW**: Backend calculation | Backend: Kelly utilization |
| → Vol Scale | Vol scale factor | `KALSHI_SIZING_METRICS` | Present if backend computes |
| → Vol Band | Vol band range | `KALSHI_SIZING_METRICS` | Present if backend computes |
| → ATR Scale | ATR scale factor | `KALSHI_SIZING_METRICS` | Present if backend computes |
| → Overall Effective Risk | Effective risk total | Aggregate from above | **NEW**: Backend aggregation |
| **Overview: Portfolio & P&L** | | | |
| → Total Value (Venue) | Balance per venue | `KALSHI_BALANCE` | Present (Kalshi only) |
| → Total Value (Combined) | Combined balance | Aggregate | Multi-venue if crypto added |
| → Daily P&L | Daily profit/loss | `KALSHI_PNL` (`daily_pnl_usd`) | Present |
| → Equity Curve | Time-series equity | `/api/operator/equity-series` | Present (operator.py) |
| → Current Drawdown | Current DD % | `KALSHI_PNL` (`drawdown_pct`) | Present |
| → Max Drawdown | Historical max DD | `KALSHI_PNL` or new field | May need max DD tracking |
| → DD Tier | Drawdown tier/level | `KALSHI_RISK_DD_GUARD` | May need tier classification |
| → Fee Drag | Total fees, % of volume | **NEW**: Aggregate from fills | Backend: sum fees from fills |
| **Overview: Positions & Trades** | | | |
| → Open Positions | Position list | `KALSHI_POSITIONS` | Present |
| → Day P&L Per Asset | Per-asset P&L | `KALSHI_POSITIONS` aggregate | May need rollup |
| → In/Out-of-Band Flags | Risk band checker | `KALSHI_POSITIONS` + `KALSHI_SIZING_METRICS` | **NEW**: Band checker |
| → Orders Placed/Filled/Cancelled | Order lifecycle stats | `KALSHI_ORDERS` aggregate | **NEW**: Lifecycle stats endpoint |
| → Churn Cycle | Orders per fill | **NEW**: Backend calculation | Backend: churn metric |
| → Resting Orders | Open orders | `KALSHI_ORDERS` (`status: resting`) | Present |
| → Resting Edge | Avg edge vs fair value | **NEW**: Backend calculation | Backend: resting edge calc |
| → Max Price vs FV | Order price vs consensus | `KALSHI_ORDERS` + `KALSHI_CONSENSUS_ALL` | Need price-to-FV comparison |
| **Overview: Crypto Spot vs Kalshi** | | | |
| → Spot Prices | BTC/ETH/SOL/XRP/DOGE spot | **NEW**: `KALSHI_CRYPTO_RTI` or external feed | Backend: crypto spot integration |
| → Kalshi Contract Prices | Kalshi crypto tickers | `KALSHI_MARKETS` | Map crypto tickers |
| → Exposures | Position counts | `KALSHI_POSITIONS` + crypto positions | Crypto position tracking |
| → P&L | Per-venue P&L | `KALSHI_PNL` + crypto P&L | Per-venue P&L rollup |
| → Basis/Hedge | Spot - Kalshi price | **NEW**: Backend calculation | Backend: basis calculation |
| **Overview: Swarm Summary** | | | |
| → Consensus Health | Health score | `KALSHI_CONSENSUS_ALL` aggregate | Backend: health score |
| → Average Brier | Avg across forecasters | `METRICS_FORECASTERS` | Backend: Brier average |
| → Calibration Error | Calibration metric | `KALSHI_GRID_PERFORMANCE_CALIBRATION` | Present |
| → Forecaster Counts | Active forecaster count | `METRICS_FORECASTERS` | Present |
| → Asset States | Ready/Forming/etc counts | `KALSHI_CONSENSUS_ALL` | Computed client-side |
| **Overview: Automation** | | | |
| → Continuous Trader | Running status | `KALSHI_GRID_STATUS` | Present |
| → Deployment Phase | Current phase | `KALSHI_DEPLOYMENT_STATUS` | Present |
| → Auto-Promoter | Status, promotions | `AUTO_PROMOTER_STATUS`, `AUTO_PROMOTER_PROMOTIONS` | Present |
| **TopBar: Mode Badges** | | | |
| → PM Mode | Live/Paper | `KALSHI_GRID_MODE` | Present |
| → Crypto Mode | Live/Paper | `PIPELINE_VENUE_MODE` | May need crypto mode |
| → Global Unlock | Locked/Unlocked | `SYSTEM_MODE_SAFETY` | Present |
| **TopBar: Risk Pill** | | | |
| → Risk Utilization | Exposure % | `KALSHI_RISK` | Present |
| → Vol Scale/Band | Vol metrics | `KALSHI_SIZING_METRICS` | Present if backend computes |
| → Synthetic FG | Cross-asset FG | `KALSHI_FEAR_GREED_SUMMARY` | **NEW**: Synthetic FG |
| → Risk State Label | Risk-On/Balanced/Off | Derived from above | Computed client-side |
| **TopBar: Heartbeat** | | | |
| → WS Health/Lag | WS status, lag ms | `KALSHI_GRID_HEALTH`, `KALSHI_HEALTH` | **NEW**: WS lag metric |
| → Consensus Age | Time since last update | `KALSHI_CONSENSUS_ALL` | Computed client-side |
| → Exec Bus Health | Bus status | **NEW**: Exec bus endpoint | Backend: exec bus status |

---

## 5. Missing Metrics & Backend Requirements

**Legend**:
- **NEW** = Requires new endpoint or significant backend extension
- **EXTEND** = Extend existing endpoint with additional fields
- **DERIVE** = Can be computed client-side from existing data

### 5.1 New Endpoints Needed

| Endpoint | Purpose | Backend Component | Priority |
|----------|---------|-------------------|----------|
| `/api/v1/kalshi/sizing-metrics/aggregate` | Aggregate vol metrics (target, realized, band, scale, ATR) | Risk engine / Position sizer | High |
| `/api/v1/kalshi/config-limits` | Configured limits (max exposure, DD, etc.) | Config service | High |
| `/api/v1/kalshi/effective-limits` | Effective limits after vol scaling | Risk engine | High |
| `/api/v1/kalshi/orders/lifecycle-stats` | Orders placed/filled/cancelled counts | Order router / Execution bus | Medium |
| `/api/v1/kalshi/orders/churn-metrics` | Churn cycle (orders per fill) | Execution bus | Medium |
| `/api/v1/kalshi/orders/resting-edge` | Resting edge vs fair value | Order router + Consensus aggregator | Medium |
| `/api/v1/kalshi/fees/aggregate` | Total fees, fee drag % | Fill aggregator | Medium |
| `/api/v1/kalshi/crypto-rti` | Real-time crypto spot prices | Crypto price feed integration | High |
| `/api/v1/kalshi/crypto-basis` | Basis (spot - Kalshi) | Crypto comparator | Medium |
| `/api/v1/kalshi/consensus/per-cell-metrics` | Per-cell Brier, calibration, prob volatility | Consensus aggregator | High |
| `/api/v1/kalshi/consensus/row-aggregates` | Per-asset aggregates (calls, Brier, forecasts) | Consensus aggregator | Medium |
| `/api/v1/kalshi/swarm/debate/per-cell` | Debate history filtered by asset/timeframe | Swarm bus / Debate tracker | Low |
| `/api/v1/kalshi/execution-bus/health` | Execution bus status | Execution bus | High |
| `/api/v1/kalshi/ws-lag` | WebSocket lag metrics | WS bridge | Medium |
| `/api/v1/kalshi/synthetic-fg` | Cross-asset synthetic fear/greed | Sentiment aggregator | High |

---

### 5.2 Extensions to Existing Endpoints

| Endpoint | New Fields Needed | Backend Change |
|----------|-------------------|----------------|
| `KALSHI_SIZING_METRICS` | `kelly_f`, `kelly_utilization`, `vol_scale`, `atr_scale`, `vol_band` (if missing) | Add Kelly fraction and utilization to position sizer output |
| `KALSHI_RISK` | `effective_exposure`, `effective_max_daily_loss`, `configured_exposure`, `configured_max_daily_loss` | Expose configured vs effective limits |
| `KALSHI_PNL` | `max_drawdown_pct`, `dd_tier` (if missing) | Track historical max DD and tier |
| `KALSHI_GRID_HEALTH` | `ws_lag_ms`, `exec_bus_status` | Add WS lag and execution bus health |
| `KALSHI_CONSENSUS_ALL` | Per-cell: `brier_score`, `calibration_grade`, `prob_volatility` | Extend consensus view with quality metrics |
| `METRICS_FORECASTERS` | Per-asset aggregates (avg Brier, forecast count) | Add asset-level rollups |
| `KALSHI_FEAR_GREED_SUMMARY` | `synthetic_fg` (cross-asset synthetic FG) | Aggregate FG across all assets |

---

### 5.3 Client-Side Derivations (No Backend Changes)

These metrics can be computed in the React frontend from existing data:

- **Consensus age** (time since last update): Compute from `KALSHI_CONSENSUS_ALL` timestamps
- **State chips counts** (ready/forming/conflicted/stale/bullish/bearish): Filter and count from `KALSHI_CONSENSUS_ALL`
- **Net directional bias** per asset: Count yes/no from `KALSHI_CONSENSUS_ALL`
- **Risk utilization %**: `total_exposure / max_exposure` from `KALSHI_RISK`
- **Risk state label** (Risk-On/Balanced/Off): Heuristic based on risk util, vol scale, FG

---

## 6. Implementation Phases

**This design is NOT proposing implementation phases yet**, but if we were to proceed, here's a logical breakdown:

### Phase 0: Foundation (Backend Metrics)
1. Implement missing backend metrics endpoints (vol aggregates, effective limits, Kelly, churn, fees, exec bus health, WS lag)
2. Extend consensus aggregator with per-cell Brier, calibration, prob volatility
3. Integrate crypto spot price feed (if needed)
4. Add synthetic FG calculation

### Phase 1: SwarmConsensusMatrix Enhancements
1. Implement global header strip with FG, vol, heartbeat, state chips
2. Add per-cell quality metrics (Brier, calibration, prob volatility)
3. Implement row aggregates with asset-level rollups
4. Build detail drawer with tabs (debate, XTF, critic/resolver, execution)

### Phase 2: Overview Dashboard Improvements
1. Implement risk & limits strip
2. Enhance portfolio & P&L panel with equity curve, DD tier, fee drag
3. Add positions & trades panel with churn, resting edge, OOB flags
4. Build crypto spot vs Kalshi comparison panel

### Phase 3: TopBar & Global Chrome
1. Add mode badges and risk state pill
2. Implement heartbeat row with WS lag, consensus age, exec bus
3. Wire or remove search box

### Phase 4: Polish & Integration
1. Unified styling, color schemes
2. Responsive layouts
3. Error handling, loading states
4. Performance optimization (memoization, virtual scrolling)

---

## 7. Conclusion

This design document provides a **comprehensive blueprint** for extending the MERID React dashboard to surface all critical metrics for fear/greed, volatility/sizing, balance/P&L, trades/fees, effective limits, WS health, swarm quality, and crypto spot vs Kalshi.

**Key Takeaways**:
1. **Existing infrastructure is strong**: Most data sources exist in `web/react/src/config/constants.ts`
2. **~15 new/extended backend endpoints** needed for complete coverage
3. **Clear mapping** from UI slots to data sources to backend components
4. **No code changes yet**: This is design & wiring only per instructions

**Next Steps** (when ready for implementation):
1. Review this design with stakeholders
2. Prioritize missing backend metrics (suggest starting with vol aggregates, effective limits, Kelly, exec bus health)
3. Implement Phase 0 (backend metrics) first
4. Incrementally build out UI components in Phases 1-3
5. Polish and integrate in Phase 4

---

## 8. Errata — alignment with `constants.ts` (2026-03-25)

When implementing, prefer these **existing** keys/paths over placeholder names in sections above:

| Document reference | Use in repo |
|--------------------|-------------|
| `KALSHI_FEAR_GREED_SUMMARY` / synthetic FG headline | No constant named `KALSHI_FEAR_GREED_SUMMARY`. Use per-asset `KALSHI_MOOD_FEAR_GREED` (`/api/v1/kalshi/mood/fear-greed/{asset}`), `KALSHI_MOOD_ALL`, `SENTIMENT_VOL_SUMMARY`, `KALSHI_SENTIMENT_BUNDLE` until a dedicated synthetic FG endpoint exists. |
| `PIPELINE_VENUE_MODE` path `/api/v1/pipeline/venue-mode` | Actual path: **`/api/v1/pipeline/venue/mode`** (`PIPELINE_VENUE_MODE`). |
| Equity curve | **`KALSHI_EQUITY_SERIES`** → `/api/v1/operator/equity-series` (also referenced as operator equity-series). |
| `KALSHI_RISK_DD_GUARD` | Not defined in `constants.ts` as of this date; use `KALSHI_RISK` / risk events or add constant when backend exists. |
| Crypto RTI | **`KALSHI_CRYPTO_RTI`** → `/api/v1/kalshi-grid/crypto/rti` already exists — do not duplicate with `/api/v1/kalshi/crypto-rti` unless you intentionally split grid vs kalshi routers. |
| Continuous trader | Prefer **`KALSHI_CONTINUOUS_TRADER_STATUS`** (`/api/v1/kalshi/continuous-trader/status`) for the continuous trader process; `KALSHI_GRID_STATUS` is the agent grid, not the same subsystem. |
| Debate APIs | Prefer `PREDICTION_DEBATES`, `PREDICTION_DEBATE_METRICS`, `PREDICTION_DEBATE_DETAIL` and `DEBATE_*` routes in `constants.ts` alongside `SWARM_CRITIC_HISTORY`. |

---

**End of Design Document**
