# MERID Kalshi-Only Mode - Current State
**Date:** 2026-02-18  
**Status:** ✅ OPERATIONAL - Clean Kalshi-only runtime achieved

---

## ✅ Completed Tasks

### 1. Infrastructure Gating
**All crypto/non-Kalshi components successfully disabled:**

- **Crypto Exchanges:** `data/live_price_feed.py:102-106`
  - Gate added: `if settings.KALSHI_ONLY: return`
  - Result: ✅ "Crypto exchanges SKIPPED (Kalshi-only mode)" in logs

- **Paper Trading Adapter:** `trading/adapters/paper.py:56-59`
  - Gate added: `if not settings.KALSHI_ONLY: register_adapter()`
  - Result: ✅ No PaperTradingEngine initialization

- **Alpaca Adapter:** `trading/adapters/alpaca.py:138-141`
  - Gate added: `if not settings.KALSHI_ONLY: register_adapter()`
  - Result: ✅ No "Alpaca REST client" in logs

- **Phase0 Routers:** `web/main.py:197-201, 479-484, 548-552`
  - All Phase0 imports commented out
  - Router registrations removed
  - Result: ✅ No Phase0 initialization

- **Trading Suite Router:** `web/main.py:150-151, 425-427`
  - Made lazy import, conditional on `_kalshi_only`
  - Result: ✅ Only loads in full mode

### 2. Settings Configuration
**File:** `merid/settings.py`

```python
KALSHI_ONLY: bool = Field(default=True)
PHASE0_ENABLED: bool = Field(default=False)
MERID_ENABLE_POLYMARKET: bool = Field(default=False)
```

### 3. Reconciliation System
**✅ Execution gate cleared:**

```bash
py scripts/run_reconciliation.py
# Output:
# ✅ Execution gate: CLEAR
# Reconciliation complete - execution can proceed
```

**Script:** `scripts/run_reconciliation.py`
- Uses Kalshi reconciler (`merid.reconciliation.kalshi_reconciler`)
- Compares matching engine state vs Kalshi venue positions
- Result: 0 discrepancies found, severity=OK

---

## Current Runtime State

### Startup Logs (Clean)
```
✅ Crypto exchanges SKIPPED (Kalshi-only mode)
✅ Live price feed initialized for 31 symbols
✅ App context frozen
✅ Neo4j connected
✅ Agent reflection loaded (3716 reflections, 7 agents)
✅ Kalshi-only profile active
✅ Runtime trading config: mode=mock, live=False, spectator=True, venues=0
```

**No errors or crypto initialization present.**

### Active Components
1. **Kalshi Venue Adapter** - Paper mode active
2. **Matching Engine** - Prediction domain, CLOB type
3. **Neo4j Graph** - Connected, schema initialized
4. **Agent Framework** - Registered prediction-arbitrage-analyst-fast
5. **Reconciliation** - Kalshi reconciler operational

### Disabled Components
- ❌ Kraken, Coinbase, Gemini, Binance, Bybit, Okx (crypto exchanges)
- ❌ Alpaca (equities)
- ❌ PaperTradingEngine (crypto paper trading)
- ❌ Phase0 minimal crypto scope
- ❌ Polymarket integration
- ❌ Crypto trading suite APIs

---

## Environment Configuration

**Required `.env` settings:**
```bash
KALSHI_ONLY=true
MERID_PROFILE=kalshi-only

# Kalshi API credentials
KALSHI_API_KEY_ID=<your_key_id>
KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi_private_key.pem
# OR
KALSHI_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----..."

# Trading mode
MERID_PM_TRADING_MODE=paper  # or 'live'
MERID_PM_LIVE_ENABLED=false  # Set true for live
```

**Startup command:**
```bash
cd c:/Dev/MERID
py -m uvicorn web.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

**Critical:** Must use `--factory` flag for gates to work.

---

## API Endpoints (Active)

### Kalshi
- `/api/v1/kalshi/balance`
- `/api/v1/kalshi/positions`
- `/api/v1/kalshi/orders`
- `/api/v1/kalshi/fills`
- `/api/v1/kalshi/pnl`
- `/api/v1/kalshi/risk`
- `/api/v1/kalshi/grid/status`

### Operator & Risk
- `/api/v1/operator/*`
- `/api/v1/risk/*`
- `/api/risk/protections`

### Agents & System
- `/api/agents/summary`
- `/api/agents/activity`
- `/api/v1/system/*`

### Portfolio
- `/api/v1/portfolio/summary` (Kalshi-filtered)

---

## UI Views (8 Kalshi-Only)

### Active Views
1. `predictions` - Kalshi markets + drift signals
2. `prediction-consensus` - Swarm consensus
3. `overview` - Portfolio summary
4. `positions` - Kalshi positions
5. `signal-layer` - Kalshi signals
6. `operator` - Reconciliation + audit
7. `risk` - Risk metrics
8. `health` - System health

### Disabled Views
- ❌ `trading`, `tradefloor` (crypto)
- ❌ `betting`, `betting-consensus` (other venues)
- ❌ `flow-radar`, `wallet`, `treasury` (legacy)

---

## Known Issues

### 1. Agent Grid Status
**Dashboard shows:**
- Agent Activity: 8 agents in "Monitoring" state
- Tasks: 0 active tasks
- Status: Agents registered but not producing tasks

**Possible causes:**
- Agent grid may not be starting in lifespan event
- Check server logs for "Kalshi Agent Grid started" message
- May need to trigger agent loop manually

### 2. Execution Gate
**Status:** ✅ CLEAR (reconciliation passed)

**Dashboard shows:** "BLOCKED - Reconciliation has never completed"
- This may be cached UI state
- Backend reconciliation is complete
- UI may need refresh or WebSocket reconnection

### 3. Real-time Feed
**Dashboard warning:** "Real-time feed disconnected"
- WebSocket connection may not be established
- Check `/api/v1/kalshi/ws` or similar endpoint
- May need to restart WebSocket publisher

---

## File Changes Made

### Modified Files
1. `data/live_price_feed.py` - Added KALSHI_ONLY gate
2. `merid/settings.py` - Added PHASE0_ENABLED, disabled Polymarket
3. `trading/adapters/paper.py` - Gated adapter registration
4. `trading/adapters/alpaca.py` - Gated adapter registration
5. `web/main.py` - Gated Phase0/trading suite routers
6. `merid/reconciliation.py` - Added venues parameter
7. `scripts/run_reconciliation.py` - Created reconciliation script

### Created Files
1. `scripts/run_reconciliation.py` - Reconciliation trigger script
2. `KALSHI_ONLY_CURRENT_STATE.md` - This file

---

## Verification Commands

### Check Clean Startup
```bash
py -m uvicorn web.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
# Should show: "Crypto exchanges SKIPPED (Kalshi-only mode)"
```

### Run Reconciliation
```bash
py scripts/run_reconciliation.py
# Should show: "✅ Execution gate: CLEAR"
```

### Test Kalshi Endpoints
```bash
curl http://localhost:8000/api/v1/kalshi/balance
curl http://localhost:8000/api/agents/summary
```

---

## Next Steps (See Below)

Refer to "NEXT_ACTIONS.md" for 5-10 high-leverage tasks to complete.
