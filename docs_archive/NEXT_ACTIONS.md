# MERID Next Actions - High-Leverage Tasks

**Context:** Clean Kalshi-only runtime achieved. Crypto/Alpaca/Phase0 successfully gated.  
**Current Blocker:** Agents registered but not producing tasks (0 active tasks in dashboard).

---

## Priority 1: Critical Path (Execution)

### 1. Start Kalshi Agent Grid ⭐⭐⭐
**Issue:** Agents show 0 tasks, grid may not be starting in lifespan  
**Check:**
```python
# In web/main.py:1717-1729, verify this runs without errors:
from merid.prediction.agent_grid import get_agent_grid
agent_grid = get_agent_grid()
await agent_grid.start()
```

**Actions:**
- [ ] Check server logs for "✅ Kalshi Agent Grid started: 24 trading agents"
- [ ] If error, read full traceback and fix import/initialization issue
- [ ] Verify agents transition from "Monitoring" to active states
- [ ] Confirm task count > 0 in `/api/agents/activity`

**Script to test:**
```bash
# Create scripts/test_agent_grid.py to manually start grid
```

---

### 2. Fix Real-Time Feed Connection ⭐⭐
**Issue:** Dashboard shows "Real-time feed disconnected"  
**Impact:** Agents need live market data to generate signals

**Actions:**
- [ ] Check if Kalshi WebSocket publisher is started in lifespan
- [ ] Verify `/api/v1/kalshi/ws` or Kalshi data stream endpoint exists
- [ ] Test WebSocket connection from frontend
- [ ] Check `web/main.py:1709-1715` - legacy WS publishers are skipped, ensure Kalshi WS is not

**Files to check:**
- `web/main.py` - WebSocket publisher startup
- `merid/event_venues/kalshi/` - Kalshi WebSocket client
- `web/react/src/` - Frontend WebSocket connection logic

---

### 3. Refresh Dashboard Execution Gate UI ⭐
**Issue:** Backend shows execution CLEAR, UI shows BLOCKED  
**Likely cause:** Cached state or stale WebSocket connection

**Actions:**
- [ ] Hard refresh browser (Ctrl+Shift+R)
- [ ] Check `/api/v1/operator/execution-gate` endpoint returns correct state
- [ ] Verify UI polls this endpoint or listens to WebSocket updates
- [ ] Update execution gate state in frontend if stale

---

## Priority 2: Agent System Health

### 4. Verify Kalshi Market Data Flow ⭐⭐
**Check:** Agents need market data to generate trades  
**Actions:**
- [ ] Test `/api/v1/kalshi/markets` returns active markets
- [ ] Verify agents can fetch Kalshi market state
- [ ] Check `kalshi_tools.kalshi_list_markets` is registered and working
- [ ] Ensure VenueGate is in correct mode (paper/live) for agent execution

**Test endpoint:**
```bash
curl http://localhost:8000/api/v1/kalshi/markets
# Should return list of active BTC/ETH/SOL/XRP/DOGE markets
```

---

### 5. Configure Agent Trading Intervals ⭐
**Issue:** Agents may be in "Monitoring" because no markets match their strategy  
**Actions:**
- [ ] Check `merid/prediction/agent_grid_config.py` for agent timeframes
- [ ] Verify agents have markets to trade (15m, 1h, daily, weekly)
- [ ] Ensure Kalshi has active markets for BTC, ETH, SOL, XRP, DOGE
- [ ] If no markets match, agents correctly remain in monitoring state

---

### 6. Enable Agent Loop Execution ⭐⭐
**If agents are started but not executing:**  
**Actions:**
- [ ] Check if agent loop is gated by execution guard
- [ ] Verify `ExecutionRouter._should_request_live()` allows Kalshi agents
- [ ] Ensure VenueGate.mode allows order submission (paper or live)
- [ ] Check risk controller is not blocking agent proposals

**Files:**
- `merid/execution/router.py` - ExecutionRouter logic
- `merid/prediction/venue_gate.py` - VenueGate mode
- `merid/risk/` - Risk controller state

---

## Priority 3: Archive/Cleanup (Once Agents Active)

### 7. Archive Legacy Code to `archive/legacy/` ⭐⭐⭐
**Once runtime is fully operational, move non-Kalshi code to archive**

**Categories to archive:**
```
archive/legacy/
├── crypto_exchanges/     # Kraken, Coinbase, etc.
├── equities/             # Alpaca integration
├── paper_trading/        # PaperTradingEngine (non-Kalshi)
├── crypto_trading/       # Trading suite, arbitrage
├── phase0/               # Phase0 experiment
├── other_venues/         # Polymarket, etc.
└── legacy_ui/            # Non-Kalshi React views
```

**Actions:**
- [ ] Scan repo and identify files to move
- [ ] Generate `git mv` commands
- [ ] Update imports in active code
- [ ] Create `archive/legacy/README.md`
- [ ] Verify app still starts cleanly after move

---

### 8. Create Archive Move Script ⭐⭐
**Automate the archive refactor with validation**

**Script:** `scripts/archive_legacy_code.py`
```python
# 1. Move files to archive/legacy/
# 2. Update imports in active code
# 3. Verify app starts
# 4. Run tests
# 5. Commit changes
```

---

## Priority 4: Monitoring & Observability

### 9. Create Agent Health Dashboard ⭐
**Real-time monitoring of agent activity**

**Actions:**
- [ ] Add `/api/agents/health` endpoint with detailed metrics
- [ ] Show per-agent task counts, success rates, errors
- [ ] Display agent state transitions (Monitoring → Active → Trading)
- [ ] Add WebSocket updates for live agent status

**Dashboard metrics:**
- Active agents count
- Total tasks completed (last hour, today)
- Order success rate
- Risk controller blocks
- Execution gate status

---

### 10. Implement Reconciliation Schedule ⭐
**Auto-run reconciliation every N minutes**

**Actions:**
- [ ] Create background task to run reconciliation every 15 minutes
- [ ] Store reconciliation history in database
- [ ] Alert on critical discrepancies
- [ ] Add `/api/v1/reconciliation/status` endpoint

**File:** `merid/reconciliation/scheduler.py`

---

## Bonus Tasks (Lower Priority)

### 11. Kalshi API Rate Limiting ⭐
- [ ] Track Kalshi API rate limits
- [ ] Implement exponential backoff
- [ ] Cache market data to reduce API calls

### 12. Agent Performance Metrics ⭐
- [ ] Track agent PnL by timeframe
- [ ] Calculate Sharpe ratio per agent
- [ ] Store agent trade history

### 13. Frontend Polish ⭐
- [ ] Add loading states to all Kalshi views
- [ ] Improve error messages
- [ ] Add tooltips for risk metrics

### 14. Comprehensive Tests ⭐
- [ ] Add integration tests for Kalshi-only mode
- [ ] Test agent grid startup/shutdown
- [ ] Test reconciliation with discrepancies

### 15. Documentation ⭐
- [ ] Update README with Kalshi-only quickstart
- [ ] Document agent configuration
- [ ] Create operator runbook

---

## Execution Order

**Immediate (Now):**
1. Task #1: Start Kalshi Agent Grid
2. Task #2: Fix Real-Time Feed
3. Task #3: Refresh Dashboard UI

**Once Agents Active:**
4. Task #4: Verify Market Data Flow
5. Task #5: Configure Trading Intervals
6. Task #6: Enable Agent Loop

**After Runtime Stable:**
7. Task #7: Archive Legacy Code
8. Task #8: Create Archive Script

**Ongoing:**
9. Task #9: Health Dashboard
10. Task #10: Reconciliation Schedule

---

## Success Criteria

**✅ Phase A Complete (Now):** Clean Kalshi-only startup, no crypto/Alpaca
**⏳ Phase B In Progress:** Agents producing tasks, execution flowing
**🎯 Phase C Goal:** Archive refactor complete, all legacy code moved

**Target State:**
- Agent Activity shows >0 active agents with tasks
- Execution gate shows CLEAR
- Real-time feed connected
- Agents generating Kalshi order proposals
- Risk controller allowing approved trades
- Dashboard showing live P&L and positions

---

## How to Proceed

**Option A: Debug Agent Grid (Recommended)**
```bash
# Check server logs for agent startup errors
# Look for "Kalshi Agent Grid started" or exceptions
```

**Option B: Manual Agent Test**
```bash
# Create test script to start agent grid independently
py scripts/test_agent_grid.py
```

**Option C: Skip to Archive**
```bash
# If agents are working and just need time to generate tasks,
# proceed with archive refactor while monitoring
```

---

**Last Updated:** 2026-02-18 05:59 AM  
**Status:** Ready for Task #1 - Start Agent Grid Debugging
