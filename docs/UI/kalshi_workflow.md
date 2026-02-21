# MERID Kalshi Swarm — Operator Workflow & UI Map

> Canonical reference for the MERID autonomous multi-AI swarm intelligence
> trading platform, fully wired to Kalshi prediction markets.
>
> **14 active views** · **5 sidebar groups** · **8-step operator workflow**

---

## Sidebar Structure

```
TRADING                          SWARM INTELLIGENCE
  Overview                         Agent Grid
  Terminal                         Swarm Matrix
  Markets                          Performance
  Portfolio                        Lane Control

ANALYTICS                        OPERATOR
  Fear / Greed                     Operator
  Vol & Sizing                     Kill Switch

SYSTEM
  Logs
  Settings
```

---

## View Inventory

| View ID | Component | Lines | Purpose |
|---------|-----------|-------|---------|
| `overview` | Overview | 491 | System health, balance, PnL cards, grid start/stop, agent activity |
| `kalshi-terminal` | KalshiTerminalView | 613 | Execution cockpit: orderbook, trade ticket, Kelly sizing, focused orders/fills |
| `kalshi-dashboard` | KalshiDashboardView | ~1440 | Market discovery: search, filter, favorites, edge signals, trade ticket |
| `kalshi-portfolio` | KalshiPortfolioView | 944 | Portfolio management: positions/orders/fills/risk tabs, cancel/amend, order groups, batch orders, PnL chart |
| `kalshi-grid` | KalshiGridView | ~1128 | Agent grid: 5 assets × 4 timeframes, start/stop/pause, kill switch, fills, paper ladder |
| `swarm-consensus` | SwarmConsensusMatrix | 478 | Multi-agent consensus matrix: direction, probability, confidence per asset×timeframe |
| `kalshi-performance` | KalshiAgentPerformanceView | 386 | Agent leaderboard: win rates, Sharpe, calibration, edge accuracy |
| `lane-control` | LaneControlDashboard | 492 | Cross-timeframe signals, deployment phases (paper→shadow→live), auto-promoter |
| `kalshi-sentiment` | KalshiSentimentView | 675 | Fear/Greed gauge, per-category sentiment, component breakdown |
| `kalshi-vol-dashboard` | KalshiVolDashboardView | 853 | Vol targeting, sizing metrics, risk limits, equity chart, volume alerts, AI insights |
| `operator` | OperatorDashboard | 318 | System ops: kill switch, mode control, data freshness, alerts, session log |
| `kill-switch` | KillSwitchView | ~200 | Emergency stop, kill switch reset, per-category toggles |
| `logs` | Logs | ~250 | System log viewer with clear/filter |
| `settings` | Settings | ~200 | User preferences |

---

## 8-Step Operator Workflow

### 1. DISCOVER
**Goal:** Find tradable Kalshi markets with edge.

| View | What it shows |
|------|--------------|
| **Markets** (KalshiDashboardView) | Full catalog browser, search/filter by category, favorites, edge signals overlay |
| **Terminal** (KalshiTerminalView) | Focused market detail, orderbook depth, event siblings |

**Key endpoints:** `KALSHI_MARKETS`, `KALSHI_CATALOG`, `KALSHI_EDGE`, `KALSHI_EVENT(ticker)`

### 2. ANALYZE
**Goal:** Score each market via AI agents, sentiment, and volatility.

| View | What it shows |
|------|--------------|
| **Fear/Greed** (KalshiSentimentView) | Global sentiment gauge (0-100), per-category cards, component breakdown (vol, volume heat, book imbalance) |
| **Vol & Sizing** (KalshiVolDashboardView) | Vol targeting metrics, realized vs target vol, risk limit gauges, volume alerts/anomalies |

**Key endpoints:** `KALSHI_SENTIMENT`, `KALSHI_SIZING_METRICS`, `KALSHI_RISK`, `KALSHI_VOLUME_ALERTS`, `KALSHI_VOLUME_ANOMALIES`

### 3. CONSENSUS
**Goal:** Multi-agent swarm votes on direction, probability, confidence.

| View | What it shows |
|------|--------------|
| **Swarm Matrix** (SwarmConsensusMatrix) | Full consensus matrix: asset × timeframe, direction breakdown, confidence factors, disagreement flags |
| **Vol & Sizing** | Consensus signals summary + consensus rate (read-only footer) |

**Key endpoints:** `KALSHI_CONSENSUS_ALL`, `KALSHI_CONSENSUS_SIGNALS`

### 4. SIZE
**Goal:** Determine position size via Kelly criterion × vol-targeting × drawdown tier.

| View | What it shows |
|------|--------------|
| **Terminal** | Per-market Kelly suggestion (contracts, side) based on edge + sizing metrics |
| **Vol & Sizing** | Kelly fraction, effective fraction, vol scale, ATR, drawdown tier |
| **Portfolio** | Sizing metrics panel (Kelly, Sharpe, Sortino, Calmar, vol scale) |

**Key endpoints:** `KALSHI_SIZING_METRICS`, `KALSHI_EDGE`

### 5. EXECUTE
**Goal:** Place orders on Kalshi (paper or live mode).

| View | What it shows |
|------|--------------|
| **Terminal** | Trade ticket with live/paper mode, orderbook, Kelly-suggested size |
| **Markets** | Trade ticket slide-over on market selection |
| **Agent Grid** (KalshiGridView) | Autonomous agent execution: start/stop/pause grid, per-agent cycles |

**Key endpoints:** `KALSHI_ORDER_SUBMIT`, `KALSHI_GRID_START`, `KALSHI_GRID_STOP`
**Shared component:** `KalshiTradeTicket` (single source, used by both Terminal and Markets)

### 6. MONITOR
**Goal:** Track positions, PnL, fills, and risk in real-time.

| View | What it shows |
|------|--------------|
| **Portfolio** | Positions tab (full table, unrealized PnL), Orders tab (cancel/amend/batch), Fills tab, Risk tab (drawdown, breaches), PnL chart |
| **Overview** | Balance, equity, position count, daily PnL cards |
| **Operator** | System-wide health, Kalshi balance/PnL summary, data freshness |

**Key endpoints:** `KALSHI_POSITIONS`, `KALSHI_ORDERS`, `KALSHI_FILLS`, `KALSHI_BALANCE`, `KALSHI_PNL`, `KALSHI_RISK`
**Order management:** `OrderGroupPanel`, `BatchOrderPanel`, `OrderGroupAnalytics` — **Portfolio only**

### 7. PROMOTE
**Goal:** Move agents from paper → shadow → live based on performance gates.

| View | What it shows |
|------|--------------|
| **Lane Control** (LaneControlDashboard) | XTF cross-timeframe signals, deployment phases per agent, auto-promoter status/recent promotions |
| **Performance** (KalshiAgentPerformanceView) | Agent leaderboard: win rate, Sharpe, calibration error, edge accuracy |

**Key endpoints:** `AUTO_PROMOTER_STATUS`, `AUTO_PROMOTER_PROMOTIONS`, `KALSHI_DEPLOYMENT_STATUS`, `XTF_SIGNALS_ALL`, `KALSHI_AGENT_PERFORMANCE`

### 8. PROTECT
**Goal:** Emergency controls, circuit breakers, risk halts.

| View | What it shows |
|------|--------------|
| **Kill Switch** (KillSwitchView) | Emergency stop button, kill switch reset, per-category toggles |
| **Operator** (OperatorDashboard) | Kill switch status, mode control (paper/live), trading halt banner, alert history |
| **Overview** | Kill switch status indicator, execution gate strip |

**Key endpoints:** `OPERATOR_EMERGENCY_STOP`, `OPERATOR_RESET_KILL_SWITCH`, `OPERATOR_KILL_SWITCH_STATUS`, `KALSHI_GRID_MODE`, `SYSTEM_EXECUTION_GATE`
**Invariant:** All views read kill switch state from `OPERATOR_KILL_SWITCH_STATUS`. All mode toggles POST to `KALSHI_GRID_MODE`. No divergent state machines.

---

## Quick Reference: "Where do I go to…"

| Task | Go to |
|------|-------|
| Find edge opportunities | **Markets** or **Terminal** |
| Place/manage orders | **Terminal** (single market) or **Portfolio** (bulk/batch) |
| See positions / PnL / fills | **Portfolio** |
| Control agents / start grid | **Agent Grid** |
| View swarm consensus | **Swarm Matrix** |
| Check agent performance | **Performance** |
| Promote agents (paper→live) | **Lane Control** |
| Check sentiment / fear-greed | **Fear/Greed** |
| Monitor vol / sizing / risk | **Vol & Sizing** |
| Emergency stop | **Kill Switch** |
| System ops / mode switch | **Operator** |
| View system logs | **Logs** |

---

## Component Sharing Rules

| Component | Used by | Notes |
|-----------|---------|-------|
| `KalshiTradeTicket` | Terminal, Markets | Single shared component for order placement |
| `ExecutionGateStrip` | Overview, Terminal, Markets, Portfolio, Grid, Vol, Performance, Sentiment, Positions (legacy) | Displays execution gate status across all trading views |
| `KalshiModeBadge` | Terminal, Markets, Portfolio, Grid, Vol, Performance, Sentiment | Shows LIVE/PAPER mode indicator |
| `OrderGroupPanel` | **Portfolio only** | Order group management consolidated here |
| `BatchOrderPanel` | **Portfolio only** | Batch order placement consolidated here |
| `ErrorBar` | All data-fetching views | Consistent error display + retry |

---

## Legacy

- **34 views** and **62+ components** in `_legacy/` directories
- **Zero active imports** from `_legacy/` — confirmed by grep
- These are remnants of an earlier multi-venue crypto exchange architecture
- They are NOT compiled into active routes and should NOT be re-added unless they serve the Kalshi swarm workflow
