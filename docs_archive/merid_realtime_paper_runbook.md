# MERID Real-Time Paper Trading Runbook

> **Goal**: Establish a disciplined "turn it on and watch" loop that surfaces bottlenecks safely before real capital deployment.

## 🎯 Executive Summary

This runbook provides a systematic approach to transitioning MERID from backtesting to real-time paper trading with live market data. Each phase must be completed and validated before proceeding to the next.

---

## Phase 1: Real-Time Data & Safe Execution Environment

### 1.1 Choose "Live but Safe" Mode

**Primary Options:**
- [ ] **Alpaca Paper Trading** - Live market data with simulated fills
  - API: `https://paper-api.alpaca.markets`
  - Docs: https://docs.alpaca.markets/docs/paper-trading
  - Status: ⏳ Not configured

- [ ] **QuantConnect Paper Trading** - Real-time feed to paper matching engine
  - API: `https://www.quantconnect.com/docs/v2/cloud-platform/live-trading`
  - Status: ⏳ Not configured

- [ ] **Internal Paper Matching Engine** - Simulate fills from live quotes
  - Status: ⏳ Not configured

**Hard Rule**: Orders must never reach real venues with real capital.

### 1.2 Wire MERID to Paper Environment

**Market Data Setup:**
- [ ] Subscribe to live tick/bar feeds (not delayed)
- [ ] Confirm bid/ask, size, and basic depth included
- [ ] Verify data arrival rate and timestamps
- [ ] Test data freshness metrics

**Trading API Setup:**
- [ ] Configure paper broker API keys/endpoints
- [ ] Point Execution to paper environment
- [ ] Test order placement and fills
- [ ] Verify position updates via broker UI

**Risk & UI Integration:**
- [ ] Point risk engine to paper environment
- [ ] Configure UI to show paper positions/balances
- [ ] Test PnL calculations with paper trades

### 1.3 Environment Sanity Check

**Verification Checklist:**
- [ ] Data timestamps are plausible (current, not stale)
- [ ] Test order generates fills in paper account
- [ ] Position updates visible in broker UI
- [ ] PnL calculations match broker UI
- [ ] No orders reach real trading venues

**Validation Commands:**
```bash
# Check data freshness
curl "http://127.0.0.1:8010/api/v1/market/data/freshness"

# Test paper order
curl -X POST "http://127.0.0.1:8010/api/v1/trading/orders/paper" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","qty":100,"side":"buy","type":"market"}'
```

---

## Phase 2: Data Pipeline Verification

### 2.1 Trace Single Symbol Through System

**Test Symbol**: AAPL (or other actively traded symbol)

**Verification Points:**
- [ ] Incoming ticks/bars with correct timestamps
- [ ] Derived features/signals in Analytics lane
- [ ] Position and PnL updates on test orders
- [ ] UI reflects all changes in real-time

**Debug Flow**: Broker → Transport → Ingestion → Analytics → Risk → UI

### 2.2 Data Health Metrics

**Required Metrics:**
- [ ] Data freshness per symbol/feed (`now - last_tick_time`)
- [ ] Feed error/timeout rates
- [ ] Message latency statistics
- [ ] Data gap detection

**Dashboard Requirements:**
- [ ] "Is data fresh?" indicator
- [ ] "Are there errors?" status panel
- [ ] Real-time feed health visualization

**API Endpoints:**
```bash
# Data health check
curl "http://127.0.0.1:8010/api/v1/system/data/health"

# Feed status
curl "http://127.0.0.1:8010/api/v1/market/feeds/status"
```

---

## Phase 3: Observation-Only Mode

### 3.1 Enable Shadow/Advisory Mode

**Configuration:**
- [ ] Strategies: Decision-making enabled
- [ ] Risk: Full limit checking enabled
- [ ] Execution: Shadow mode (size=0 or dummy endpoint)
- [ ] Logging: All would-be orders with full context

**Logging Requirements:**
- [ ] Price data at decision time
- [ ] Signal values and thresholds
- [ ] Risk context and limits
- [ ] Would-be order parameters

### 3.2 Expectations vs Actions Analysis

**Review Period**: 1-2 trading sessions

**Validation Checklist:**
- [ ] MERID fires on expected market moves
- [ ] Decisions match backtest behavior
- [ ] No dead strategies detected
- [ ] Risk checks fire appropriately
- [ ] Signal alignment verified

**Debug Priority**: Data → Signals → Strategy Logic → Risk Filters

---

## Phase 4: Full Paper Trading

### 4.1 Enable Actual Paper Orders

**Configuration:**
- [ ] Strategy/Execution: Send real paper orders
- [ ] Risk: Fully active (blocking/downsizing)
- [ ] Position sizing: Small notional (start)
- [ ] Order types: Market orders initially

### 4.2 Real-Time Execution Loop Validation

**Per-Order Validation:**
- [ ] Decision → Order sent
- [ ] Order → Fill received
- [ ] Fill → Position updated
- [ ] Position → PnL updated
- [ ] PnL → Risk posture updated
- [ ] Risk → UI reflects all changes

**Logging Requirements:**
- [ ] Order rejections with reasons
- [ ] Partial fills handling
- [ ] Latency measurements
- [ ] Error codes and recovery

### 4.3 Progressive Complexity

**Rollout Plan:**
1. [ ] Single symbol, single venue, single strategy
2. [ ] Add second symbol
3. [ ] Add second venue
4. [ ] Add second strategy
5. [ ] Increase position sizes

**Success Criteria**: Each step must run "boringly" (no surprises) for at least one full session.

---

## Phase 5: Systematic Debugging

### 5.1 Behavior Classification

**Bug Categories:**
- [ ] **Data Issues**: Stale, out-of-order, gaps
- [ ] **Decision Logic**: Strategy misfires, wrong signals
- [ ] **Execution Problems**: Stuck orders, missing fills
- [ ] **UI Issues**: Lag, mismatched numbers

### 5.2 Replay & Isolation

**Debug Process:**
1. [ ] Capture problematic interval data
2. [ ] Run local replay of period
3. [ ] Inspect variables at each stage
4. [ ] Reproduce bug deterministically

**Replay Commands:**
```bash
# Capture interval
python scripts/capture_interval.py --start "2024-01-26 09:30" --end "2024-01-26 10:30"

# Run replay
python scripts/replay_interval.py --data captured_data.json
```

### 5.3 Fix & Validate

**Fix Process:**
1. [ ] One change per cause
2. [ ] Add test/invariant for fix
3. [ ] Redeploy and re-run scenario
4. [ ] Confirm fix via replay

**Example Invariants:**
- P&L from raw trades matches account P&L within 0.01%
- Position updates within 100ms of fill receipt
- No orders sent when risk limits exceeded

---

## Phase 6: SRE & Lifecycle Drills

### 6.1 Startup/Shutdown Practice

**State Transitions:**
- [ ] Cold start → WARMING_UP → LIVE
- [ ] LIVE → DRAINING → SAFE_MODE → OFFLINE

**Verification:**
- [ ] No trades before LIVE state
- [ ] No open orders after SAFE_MODE
- [ ] UI state matches system state
- [ ] Graceful shutdown completes

### 6.2 Chaos/Game-Day Drills

**Failure Scenarios:**
- [ ] Data feed loss (simulate disconnect)
- [ ] Risk engine failure (kill process)
- [ ] Paper broker API outage (mock 503s)
- [ ] Network partition (block traffic)
- [ ] Database failure (stop service)

**Expected Behavior:**
- [ ] System enters SAFE_MODE
- [ ] All trading stops
- [ ] UI shows failure state
- [ ] Recovery when service restored

---

## Phase 7: Go/No-Go Decision Gates

### 7.1 Explicit Readiness Criteria

**Quantitative Gates:**
- [ ] **Trading Days**: 10+ days in paper with real-time data
- [ ] **Trade Count**: 50+ trades executed
- [ ] **Incidents**: 0 Sev-0 incidents
- [ ] **PnL Consistency**: Within 5% of backtest expectations
- [ ] **Risk Metrics**: Max drawdown within expected bounds
- [ **Latency**: Order-to-fill < 100ms 95th percentile

**Qualitative Gates:**
- [ ] Lifecycle drills passed 3+ times
- [ ] All failure scenarios tested
- [ ] Team confident in procedures
- [ ] Documentation complete and reviewed

### 7.2 Gate Enforcement

**Rules:**
- [ ] No gate waivers allowed
- [ ] Failed gate → fix → re-run full validation
- [ ] All gates must pass simultaneously
- [ ] Sign-off required from: Trading, Risk, Engineering

**Go/No-Go Form:**
```markdown
- [ ] Engineering Lead: __________________ Date: _______
- [ ] Risk Manager: ______________________ Date: _______
- [ ] Trading Lead: _______________________ Date: _______
- [ ] SRE Lead: ___________________________ Date: _______
```

---

## 🚨 Emergency Procedures

### Immediate Stop Conditions
- Real capital at risk (paper boundary breach)
- Data feed corruption detected
- Risk system failure
- Unexpected position behavior

### Stop Commands
```bash
# Emergency stop
curl -X POST "http://127.0.0.1:8010/api/v1/system/emergency_stop"

# Force safe mode
curl -X POST "http://127.0.0.1:8010/api/v1/system/force_safe_mode"
```

---

## 📊 Progress Tracking

### Current Status
- **Phase**: 1 - Environment Setup
- **Last Updated**: 2024-01-26
- **Next Milestone**: Paper broker configuration
- **Blockers**: None identified

### Session Artifacts
- [ ] Configuration files
- [ ] Test results and logs
- [ ] Performance metrics
- [ ] Incident reports (if any)

---

## 📚 Reference Materials

### Documentation
- [Alpaca Paper Trading](https://docs.alpaca.markets/docs/paper-trading)
- [QuantConnect Paper Trading](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading)
- [Paper Trading Guide](https://blog.traderspost.io/article/paper-trading-strategy-development-guide)
- [Debugging Techniques](https://bluechipalgos.com/blog/debugging-techniques-for-trading-algorithms/)
- [TradingView Paper Trading](https://www.tradingview.com/support/solutions/43000516466-paper-trading-main-functionality/)

### Internal References
- MERID Architecture Documentation
- Risk Management Framework
- API Specification
- Monitoring & Alerting Setup

---

## 🔄 Runbook Usage

### Before Each Session
1. Review current phase and checklist items
2. Verify environment status
3. Confirm team availability
4. Check monitoring/alerting systems

### During Each Session
1. Follow phase-specific procedures
2. Document all observations
3. Log any deviations or issues
4. Capture performance metrics

### After Each Session
1. Complete checklist items
2. Review logs and metrics
3. Document lessons learned
4. Update runbook if needed
5. Plan next session

---

**Remember**: The goal is not speed, but systematic validation. Each phase builds confidence and surfaces issues before they become critical.
