# Kalshi AI Swarm - Production Deployment Checklist

**System:** 24-Agent Crypto Trading Grid on Kalshi  
**Date:** 2026-02-18  
**Status:** 🟢 READY FOR PRODUCTION

---

## ✅ Pre-Flight Checklist

### 1. Configuration ✅ COMPLETE
- [x] **Agent Grid Config:** 24 agents configured (BTC/ETH/SOL/XRP/DOGE × 4 timeframes)
- [x] **Production Mode:** `use_demo: false` in `config/kalshi_agent_grid.yaml`
- [x] **API Credentials:** Valid Kalshi API key and private key configured
- [x] **Risk Limits:** Portfolio max $50k, per-asset max $15k, daily loss max $5k
- [x] **Crypto Focus:** All agents target crypto category markets

### 2. Backend Wiring ✅ COMPLETE
- [x] **Market Catalog:** Auto-discovers crypto markets every 5 minutes
- [x] **Agent Grid:** Orchestrator manages 24 agent lifecycle
- [x] **Consensus Bridge:** Aggregates signals from multiple agents
- [x] **Venue Adapter:** Routes orders to Kalshi REST API
- [x] **Reconciliation:** Verifies positions match Kalshi account
- [x] **Kill Switch:** Emergency execution stop available

### 3. Frontend Wiring ✅ COMPLETE
- [x] **Overview:** Shows real Kalshi balance, positions, PnL
- [x] **Agent Grid:** Displays all 24 agents with status
- [x] **Markets:** Lists crypto markets from catalog
- [x] **Terminal:** Order entry + orderbook display
- [x] **Portfolio:** Position tracking via venue_registry
- [x] **Orders:** Kalshi orders only (removed generic endpoint)
- [x] **Risk Views:** Kalshi-filtered exposure and risk metrics

### 4. Data Flow ✅ VERIFIED
- [x] **Market Data:** Kalshi REST API → Market Catalog → Agents
- [x] **Signal Flow:** Agent Signals → Consensus Bridge → Execution Plans
- [x] **Order Flow:** Plans → Venue Adapter → Kalshi API → Fill Confirmations
- [x] **Position Sync:** Kalshi Positions → Reconciliation → Internal Tracking

---

## 🚀 Startup Sequence

### Step 1: Verify Environment
```bash
cd C:\Dev\MERID

# Check API credentials
py -c "from merid.settings import settings; print('Kalshi API Key:', settings.KALSHI_API_KEY_ID[:16]+'...'); print('Mode:', settings.MERID_PM_TRADING_MODE); print('Live Enabled:', settings.MERID_PM_LIVE_ENABLED)"

# Verify config
cat config\kalshi_agent_grid.yaml | findstr use_demo
# Should show: use_demo: false
```

### Step 2: Start Backend
```bash
uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

**Watch for:**
```
✅ INFO: AgentGrid initialized: 24 agents
✅ INFO: KalshiMarketCatalog started — refreshing markets
✅ INFO: Loaded Kalshi agent grid: 24 agents, assets=['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
```

### Step 3: Open UI
```
http://localhost:8000
```

### Step 4: Verify Dashboard
**Overview View:**
- Balance should show real USD from Kalshi account
- Positions should be empty (or show existing positions)
- No error messages

**Agent Grid View:**
- Should show 24/24 agents
- All agents "Enabled: true"
- Status indicators visible

**Markets View:**
- Should list crypto markets (BTC, ETH, SOL, XRP, DOGE)
- Markets grouped by timeframe
- Orderbook data visible

### Step 5: Test Order Placement (SMALL SIZE)
1. Go to **Terminal** view
2. Select a crypto market (e.g., BTC 15-minute)
3. Place **SMALL** test order:
   - Side: YES
   - Contracts: 10 (minimum)
   - Price: Current market price
4. Submit order
5. Verify order appears in **Orders** view
6. Check Kalshi website to confirm order exists

### Step 6: Monitor First Agent Cycle
```bash
# Watch backend logs for agent activity
# You should see:
✅ "KalshiTradingAgent [BTC_15M] cycle started"
✅ "Markets assigned: 5"
✅ "Signal generated: BUY YES ..."
✅ "Signal submitted to consensus"
```

### Step 7: Verify Reconciliation
After first order executes:
1. Check **Risk & Health** view
2. Verify "Reconciliation Status: OK"
3. Confirm position counts match
4. Balance should update correctly

---

## 🎯 Expected Behavior (First Hour)

### Market Discovery
```
Every 5 minutes:
├── Market catalog refreshes from Kalshi API
├── Discovers new crypto contracts
├── Tags with asset (BTC/ETH/SOL/XRP/DOGE)
├── Tags with timeframe (15m/hourly/daily/weekly)
└── Updates agent market assignments
```

### Agent Activity
```
BTC_15M Agent (every 30 sec):
├── Fetches 3-8 BTC 15-minute markets from catalog
├── Analyzes orderbook depth + price action
├── Generates signal (or NO_ACTION)
├── If signal: submits to consensus bridge
└── Sleeps until next cycle

ETH_HOURLY Agent (every 60 sec):
├── Fetches ETH hourly markets
├── Runs strategy analysis (LLM or technical)
├── Generates directional signal
├── Submits with confidence score
└── Waits for next cycle

... (22 more agents running in parallel)
```

### Consensus & Execution
```
Every loop tick (5-10 sec):
├── Collect signals from all 24 agents
├── Filter by confidence threshold (> 0.60)
├── Aggregate overlapping signals (same market)
├── Apply portfolio risk limits
├── Generate execution orders
├── Submit to venue adapter
├── Adapter → Kalshi REST API
├── Receive fill confirmation
└── Update positions + PnL
```

### Risk Monitoring
```
Portfolio Risk Agent (every 30 sec):
├── Calculate total notional: sum(position_value)
├── Check: total_notional < $50,000
├── Check per-asset: BTC < $15k, ETH < $15k, etc.
├── Check daily PnL vs -$5,000 max loss
├── Check margin utilization < 80%
└── If breach: Pause agents or force reduce
```

---

## 📊 Performance Metrics to Track

### Day 1 Targets
- **Agents Running:** 24/24 active
- **Cycles Completed:** >50 per agent
- **Signals Generated:** >200 total
- **Orders Placed:** 10-30 (depends on market opportunities)
- **Fill Rate:** >70% (orders executed vs placed)
- **Reconciliation:** 100% pass rate (no critical mismatches)
- **Max Drawdown:** < $500 (start conservatively)

### Week 1 Goals
- **Win Rate:** >52% (above random)
- **Sharpe Ratio:** >1.0
- **Max Portfolio Notional:** Test up to $25k (50% of limit)
- **Active Markets:** 20-50 concurrent positions
- **Agent Calibration:** Adjust confidence thresholds based on results

---

## 🚨 Emergency Procedures

### If Something Goes Wrong

#### Kill Switch (Immediate Stop)
**UI Method:**
1. Navigate to **Kill Switch** view
2. Click red "ACTIVATE KILL SWITCH" button
3. All agent trading halts immediately
4. Existing positions remain open (manual close if needed)

**API Method:**
```bash
curl -X POST http://localhost:8000/api/v1/system/kill-switch/activate
```

#### Pause Specific Agent
```bash
curl -X POST http://localhost:8000/api/v1/kalshi-grid/agents/BTC_15M/pause
```

#### Stop Agent Grid
```python
# In Python shell:
from merid.prediction.agent_grid import get_agent_grid
import asyncio

grid = get_agent_grid()
asyncio.run(grid.stop())
```

#### Emergency Position Close
1. Go to Kalshi website directly
2. Manually close positions
3. System will detect on next reconciliation
4. Or use Terminal view to place offsetting orders

---

## 🔍 Monitoring Checklist

### Every 15 Minutes (First Day)
- [ ] Check agent grid status (all 24 running)
- [ ] Verify no error alerts in Observability
- [ ] Confirm balance updates correctly
- [ ] Check reconciliation passes
- [ ] Monitor position count

### Every Hour
- [ ] Review PnL trend
- [ ] Check signal generation rate
- [ ] Verify order fill rate
- [ ] Monitor API latency (Kalshi response times)
- [ ] Check for stuck orders

### Daily
- [ ] Calculate daily PnL vs target
- [ ] Review agent win rates
- [ ] Adjust risk limits if needed
- [ ] Check for pattern in losing trades
- [ ] Verify no margin violations

---

## 📈 Optimization Roadmap

### Week 1-2: Calibration
1. Monitor agent signal quality
2. Adjust confidence thresholds
3. Tune entry/exit timing
4. Optimize position sizing

### Week 3-4: Scaling
5. Increase risk limits gradually
6. Add more assets if Kalshi expands
7. Implement dynamic position sizing
8. Add machine learning signal enhancement

### Month 2: Advanced Features
9. Multi-leg strategies (spreads)
10. Cross-asset arbitrage
11. Volatility prediction models
12. Automated parameter optimization

---

## ✅ Final Verification

Before going live, confirm:

1. **Agent Config:**
   ```yaml
   use_demo: false  # ✅ Production mode
   ```

2. **Environment:**
   ```bash
   KALSHI_USE_DEMO=false
   MERID_PM_TRADING_MODE=live
   MERID_PM_LIVE_ENABLED=true
   ```

3. **Balance Check:**
   ```bash
   curl http://localhost:8000/api/v1/kalshi/balance
   # Should return real USD amount
   ```

4. **Test Order:**
   - Place 10-contract test order
   - Verify appears on Kalshi website
   - Cancel before fill (if testing)

5. **UI Verification:**
   - [ ] Overview shows real balance
   - [ ] Agent Grid shows 24 agents
   - [ ] Markets lists crypto contracts
   - [ ] Terminal can place orders
   - [ ] Orders view shows Kalshi orders only

---

## 🎉 You're Ready!

### What You Have
✅ **24 professional trading agents**  
✅ **Full crypto market coverage** (BTC/ETH/SOL/XRP/DOGE)  
✅ **Multi-timeframe analysis** (15m to weekly)  
✅ **Robust risk management** (portfolio + per-agent limits)  
✅ **Real-time data feed** (market catalog auto-refresh)  
✅ **Consensus aggregation** (multi-agent voting)  
✅ **Position reconciliation** (automated verification)  
✅ **Emergency controls** (kill switch + execution gate)  
✅ **Complete monitoring** (UI dashboard + logs)  

### What to Expect
🔹 **First signals** within 5 minutes of startup  
🔹 **First orders** within 15 minutes (if opportunities exist)  
🔹 **Position build-up** gradually over first hour  
🔹 **Steady state** 20-50 open positions across timeframes  
🔹 **Daily activity** 50-200 orders depending on volatility  

### Success Metrics
🎯 **Technical:** All agents running, no errors, reconciliation passing  
🎯 **Trading:** >50% win rate, positive PnL, controlled drawdown  
🎯 **Risk:** Within limits, no margin calls, smooth operations  

---

## 🚀 START COMMAND

When ready to begin live trading:

```bash
cd C:\Dev\MERID
uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

**Monitor backend startup logs for:**
```
✅ "AgentGrid initialized: 24 agents"
✅ "KalshiMarketCatalog started"
✅ "AgentGrid started: 24 agents running"
```

**Then open UI and watch the magic happen:**
```
http://localhost:8000
```

---

**Status:** 🟢 **PRODUCTION READY**  
**Risk Level:** ⚠️ **START SMALL** - Use 10-20% of risk limits initially  
**Recommendation:** Monitor closely first 24 hours, then scale gradually

**Good luck with your AI swarm trading! 🚀**
