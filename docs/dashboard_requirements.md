# Fee and Drawdown Dashboard Requirements

**Last Updated:** 2026-05-14  
**Scope:** Kalshi 15m Crypto Trading Stack (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

## Overview

This document defines the requirements for monitoring dashboards that expose canonical fee and drawdown behavior. These dashboards provide visibility into whether the risk primitives are behaving as intended and aid debugging when Kalshi changes fee schedules or risk parameters drift.

---

## 1. Fee Dashboard

### Purpose
- Verify that fees recorded at execution time match canonical `fees.py` calculations
- Monitor fee spend vs notional traded
- Detect broken paths to `fees.py` or fee schedule changes

### Per-Agent Metrics

| Metric | Description | Source | Visualization |
|--------|-------------|--------|---------------|
| Daily Fee Spend | Total fees paid per day (USD) | `fills_ledger.py` (fee_cents from fills) | Time series line chart |
| Daily Notional Traded | Total notional traded per day (USD) | `fills_ledger.py` (contracts × price) | Time series line chart |
| Fee Rate | Fee / Notional (percentage) | Computed from above | Time series line chart |
| Expected Fee Rate | Expected rate from `fees.py` tiers (7%/5%/3%) | `fees.py` tier logic | Reference line |
| Fee Drift | Actual - Expected fee rate | Computed | Time series (highlight drift > 1%) |
| Fee Tier Distribution | % of fills in each tier (1-99, 100-999, 1000+) | Fill contract counts | Stacked bar chart |
| Missing Fee Count | Number of fills with zero or missing fee | `fills_ledger.py` | Counter (alert if > 0) |

### Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Fee Dashboard - 15m Crypto Agents                                │
├─────────────────────────────────────────────────────────────────┤
│ Agent Selector: [BTC_15M ▼] Time Range: [Last 7 days ▼]         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Daily Fee Spend ($USD)          Daily Notional Traded ($USD)    │
│  ┌─────────────────────┐        ┌─────────────────────┐         │
│  │   Line chart        │        │   Line chart        │         │
│  └─────────────────────┘        └─────────────────────┘         │
│                                                                 │
│  Fee Rate vs Expected         Fee Tier Distribution              │
│  ┌─────────────────────┐        ┌─────────────────────┐         │
│  │   Line chart with    │        │   Stacked bar        │         │
│  │   reference line    │        │   chart              │         │
│  └─────────────────────┘        └─────────────────────┘         │
│                                                                 │
│  Fee Drift                     Missing Fee Count                 │
│  ┌─────────────────────┐        ┌─────────────────────┐         │
│  │   Line chart        │        │   Counter            │         │
│  │   (highlight drift)  │        │   (alert if > 0)     │         │
│  └─────────────────────┘        └─────────────────────┘         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Data Sources

- **Fee Records**: `merid/event_venues/kalshi/fills_ledger.py` - `fee_cents` field from Kalshi fills
- **Fee Calculation**: `merid/event_venues/kalshi/fees.py` - `calculate_kalshi_fee_cents()` for expected values
- **Profile Limits**: `config/profiles/kalshi_crypto_15m.yaml` - For reference tier configuration

### Alert Thresholds

- **Missing Fee Alert**: If any fill has `fee_cents = 0` or `None` → HIGH severity
- **Fee Drift Alert**: If actual fee rate differs from expected by > 1% for > 10 fills → MEDIUM severity
- **Tier Distribution Alert**: If tier distribution shifts by > 20% from baseline → LOW severity

---

## 2. Drawdown Dashboard

### Purpose
- Monitor drawdown trajectory vs profile limits
- Verify halt/unwind events trigger at expected PnL levels
- Detect agents that remain active when they should be halted

### Per-Agent Metrics

| Metric | Description | Source | Visualization |
|--------|-------------|--------|---------------|
| Running PnL | Cumulative PnL over time (USD) | `fills_ledger.py` (pnl field) | Time series line chart |
| Peak Equity | Highest equity reached (USD) | Computed from PnL | Time series line chart |
| Current Drawdown | (Peak - Current) / Peak (percentage) | Computed | Time series line chart |
| Drawdown Halt Limit | Profile `drawdown_halt_pct` (e.g., 10%) | Profile YAML | Reference line |
| Drawdown Unwind Limit | Profile `drawdown_unwind_pct` (e.g., 15%) | Profile YAML | Reference line |
| Max Daily Loss | Daily loss accumulated (USD) | Computed from PnL | Time series line chart |
| Max Daily Loss Limit | Profile `max_daily_loss_usd` (e.g., $200) | Profile YAML | Reference line |
| Halt Events | Timestamp when halt triggered | `_prediction_risk.py` logs | Markers on chart |
| Unwind Events | Timestamp when unwind triggered | `_prediction_risk.py` logs | Markers on chart |
| Agent Status | Active / Halted / Unwind | Agent state | Status indicator |

### Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Drawdown Dashboard - 15m Crypto Agents                           │
├─────────────────────────────────────────────────────────────────┤
│ Agent Selector: [BTC_15M ▼] Time Range: [Last 7 days ▼]         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Running PnL & Peak Equity   Current Drawdown vs Limits         │
│  ┌─────────────────────┐        ┌─────────────────────┐         │
│  │   Line chart        │        │   Line chart with   │         │
│  │   (PnL + peak)      │        │   halt/unwind lines │         │
│  └─────────────────────┘        └─────────────────────┘         │
│                                                                 │
│  Max Daily Loss vs Limit    Agent Status                        │
│  ┌─────────────────────┐        ┌─────────────────────┐         │
│  │   Line chart with   │        │   Status indicator  │         │
│  │   reference line    │        │   (Active/Halted)    │         │
│  └─────────────────────┘        └─────────────────────┘         │
│                                                                 │
│  Halt/Unwind Event Timeline                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Timeline markers with event details                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Data Sources

- **PnL Records**: `merid/event_venues/kalshi/fills_ledger.py` - `pnl` field from fills
- **Drawdown State**: `merid/prediction/risk/_prediction_risk.py` - Runtime drawdown tracking
- **Profile Limits**: `config/profiles/kalshi_crypto_15m.yaml` - `drawdown_halt_pct`, `drawdown_unwind_pct`, `max_daily_loss_usd`
- **Event Logs**: `_prediction_risk.py` logs for halt/unwind events

### Alert Thresholds

- **Halt Miss Alert**: If agent remains active while PnL is below `max_daily_loss_usd` by > 10% → HIGH severity
- **Premature Halt Alert**: If agent halted while drawdown is < 50% of halt threshold → MEDIUM severity
- **Unwind Miss Alert**: If unwind not triggered when drawdown > unwind threshold → MEDIUM severity
- **Daily Loss Exceeded Alert**: If daily loss > `max_daily_loss_usd` by > 5% → HIGH severity

---

## 3. Aggregate Dashboard

### Purpose
- High-level view across all 15m crypto agents
- Detect systemic issues (e.g., fee schedule change affecting all agents)
- Compare agent performance

### Cross-Agent Metrics

| Metric | Description | Visualization |
|--------|-------------|---------------|
| Total Fee Spend (All Agents) | Sum of daily fees across all agents | Time series line chart |
| Total Notional Traded (All Agents) | Sum of notional across all agents | Time series line chart |
| Aggregate Fee Rate | Total fees / Total notional | Time series line chart |
| Agent Drawdown Status | Table showing current drawdown for each agent | Table with color coding |
| Halted Agents Count | Number of agents currently halted | Counter |
| Unwind Mode Agents Count | Number of agents in unwind mode | Counter |
| Profile Drift Detection | Compare current profile vs baseline | Alert panel |

### Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Aggregate Dashboard - 15m Crypto Agents                          │
├─────────────────────────────────────────────────────────────────┤
│ Time Range: [Last 7 days ▼]                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Total Fee Spend vs Notional   Agent Drawdown Status Table       │
│  ┌─────────────────────┐        ┌─────────────────────┐         │
│  │   Line chart        │        │   Table:            │         │
│  │   (all agents)      │        │   Agent | DD | Status│         │
│  └─────────────────────┘        └─────────────────────┘         │
│                                                                 │
│  Halted/Unwind Counters       Profile Drift Alerts              │
│  ┌─────────────────────┐        ┌─────────────────────┐         │
│  │   Counters          │        │   Alert panel       │         │
│  └─────────────────────┘        └─────────────────────┘         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Implementation Notes

### Backend API Requirements

1. **Fee Metrics Endpoint**
   ```
   GET /api/v1/metrics/fees
   Query params: agent, start_date, end_date
   Response: {
     daily_fee_spend: [...],
     daily_notional_traded: [...],
     fee_rate: [...],
     fee_tier_distribution: {...},
     missing_fee_count: int
   }
   ```

2. **Drawdown Metrics Endpoint**
   ```
   GET /api/v1/metrics/drawdown
   Query params: agent, start_date, end_date
   Response: {
     running_pnl: [...],
     peak_equity: [...],
     current_drawdown: [...],
     max_daily_loss: [...],
     halt_events: [...],
     unwind_events: [...],
     agent_status: "active" | "halted" | "unwind"
   }
   ```

3. **Aggregate Metrics Endpoint**
   ```
   GET /api/v1/metrics/aggregate
   Query params: start_date, end_date
   Response: {
     total_fee_spend: [...],
     total_notional_traded: [...],
     aggregate_fee_rate: [...],
     agent_drawdown_status: [...],
     halted_agents_count: int,
     unwind_agents_count: int
   }
   ```

### Frontend Requirements

- Use React with charting library (e.g., Recharts, Chart.js)
- Real-time updates via WebSocket (optional for production)
- Export to CSV functionality
- Responsive design for mobile/tablet

### Alert Integration

- Dashboards should integrate with existing alerting system (e.g., PagerDuty, Slack)
- Alert rules defined in separate `docs/alert_rules.md` document
- Alert thresholds configurable via environment variables

---

## 5. Testing & Validation

### Smoke Tests

1. **Fee Dashboard Smoke Test**
   - Verify fee spend > 0 for active agents
   - Verify fee rate in expected range (3-7%)
   - Verify no missing fees for recent fills

2. **Drawdown Dashboard Smoke Test**
   - Verify drawdown ≤ 100% (sanity check)
   - Verify halt/unwind limits match profile values
   - Verify agent status matches actual runtime state

### Regression Tests

- Compare dashboard metrics against `replay_harness.py` output for historical data
- Verify fee dashboard matches `fills_ledger.py` records
- Verify drawdown dashboard matches `_prediction_risk.py` logs

---

## 6. Future Enhancements

- Add real-time fee calculation preview (enter contracts/price → see fee)
- Add drawdown simulator (enter PnL path → see when halt/unwind triggers)
- Add profile comparison tool (diff two profiles side-by-side)
- Add fee schedule change detector (alert if Kalshi changes tier structure)
- Add backtest vs live comparison overlay
