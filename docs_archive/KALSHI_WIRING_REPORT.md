# Kalshi Backend Wiring Verification Report

**Generated:** 2026-02-18  
**Purpose:** Pre-reboot audit of Kalshi integration for 8 canonical views

---

## Executive Summary

✅ **MAIN LOOP INTEGRATION** - Kalshi fully integrated into loop.py  
✅ **VENUE REGISTRY** - Kalshi adapter registered on startup  
✅ **API ROUTERS** - 4 Kalshi routers mounted in web/main.py  
⚠️ **CONSENSUS BRIDGE** - Needs verification  
⚠️ **RECONCILIATION** - Module exists, needs API endpoint check  
⚠️ **AGENT GRID** - KalshiTradingAgent in loop, needs grid startup check  

---

## 1. Main Loop (`merid/loop.py`) ✅

### Kalshi Signal Generation (Lines 338-361)
```python
if "prediction" in self.config.active_domains:
    await self._refresh_kalshi_signals(now, summary, store)
```

**Status:** ✅ WIRED  
**Function:** Generates Kalshi-specific signals for prediction domain  
**Trigger:** Every feature refresh interval (~30s)  
**Powers Views:** `predictions`, `signal-layer`

---

### Kalshi Agent Cycle (Lines 392-428)
```python
if "prediction" in self.config.active_domains:
    await self._run_kalshi_agent_cycle(summary)
```

**Status:** ✅ WIRED  
**Function:** Runs KalshiTradingAgent decision cycle via agent grid  
**Trigger:** Every agent cycle interval (~60s)  
**Powers Views:** `predictions`, `prediction-consensus`, `operator`

**Integration Point:**
```python
from merid.prediction.agent_grid import get_agent_grid
grid = get_agent_grid()
# Collects signals from grid.agents
```

---

### Kalshi Reconciliation (Lines 700-740)
```python
if "prediction" in self.config.active_domains:
    from merid.reconciliation import get_kalshi_reconciler
    reconciler = get_kalshi_reconciler()
    report = await reconciler.reconcile()
```

**Status:** ✅ WIRED  
**Function:** Compares internal vs Kalshi venue positions  
**Trigger:** Every reconciliation interval (~120s)  
**Powers Views:** `operator`, `risk`, `health`

**Critical Feature:** Blocks execution if `severity == "CRITICAL"`

---

## 2. Venue Registry (`merid/venue_registry.py`) ✅

### Kalshi Adapter Registration (Lines 212-218)
```python
def _initialize_default_venues():
    from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
    kalshi = get_kalshi_venue_adapter(mode="paper")
    registry.register(kalshi, enabled=True)
```

**Status:** ✅ WIRED  
**Function:** Registers Kalshi venue adapter on singleton creation  
**Powers Views:** `overview`, `positions`, `predictions`, `operator`

**Methods Available:**
- `get_all_positions(kalshi_only=True)` - Filters to Kalshi venue
- `get_all_risk_snapshots(kalshi_only=True)` - Kalshi risk data only

---

## 3. API Routers (`web/main.py`) ✅

### Registered Kalshi Routers (Lines 465-472)
```python
application.include_router(kalshi_api_router, prefix="/api/v1")
application.include_router(kalshi_ui_router, prefix="/api/v1")
application.include_router(kalshi_grid_router, prefix="/api/v1")
application.include_router(kalshi_agent_grid_router)
```

**Status:** ✅ MOUNTED  

### Expected Endpoints Per View

| View | API Endpoints Expected | Router Source |
|------|------------------------|---------------|
| **predictions** | `/api/v1/us-compliant/prediction-markets`<br>`/api/v1/prediction-markets/summary`<br>`/api/v1/us-compliant/drift-signals` | kalshi_api_router,<br>us_compliant_markets_router |
| **prediction-consensus** | `/api/v1/prediction/consensus/summary`<br>`/api/v1/prediction/consensus/opinions`<br>`/api/v1/prediction/consensus/plans` | prediction_consensus_router |
| **overview** | `/api/v1/portfolio/summary`<br>`/api/v1/positions`<br>`/api/v1/orders` | kalshi_api_router |
| **positions** | `/api/v1/trading/portfolio/summary` | kalshi_api_router |
| **signal-layer** | `/api/v1/signal-layer/arbs`<br>`/api/v1/signal-layer/drift`<br>`/api/v1/signal-layer/macro` | signal_layer_router |
| **operator** | `/api/operator/audit-trail`<br>`/api/operator/system/status` | operator_router |
| **risk** | `/api/v1/risk/metrics`<br>`/api/v1/risk/alerts`<br>`/api/v1/system/health` | risk_router |
| **health** | `/api/v1/system/health`<br>`/api/system/health`<br>`/api/system/components` | health_router,<br>system_endpoints_router |

---

## 4. Consensus Bridge ⚠️

### Integration Status
**Location:** `consensus/taco_consensus.py`  
**Accessor:** `loop._consensus_coordinator()`

**Current State:**
- ✅ Consensus coordinator called in loop (line 204-206, 430-436)
- ✅ Used for plan generation and approval
- ⚠️ **NEEDS VERIFICATION:** Prediction domain consensus adapter

**Expected Files to Check:**
- `merid/prediction/consensus_adapter.py` - Maps Kalshi signals to consensus
- Consensus should aggregate multi-agent opinions for Kalshi markets

**Action Required:** Verify consensus bridge processes prediction domain signals

---

## 5. Reconciliation Module ✅

### Core Module
**Location:** `merid/reconciliation.py`  
**Function:** `get_kalshi_reconciler()`

**Status:** ✅ INTEGRATED in main loop

### Expected API Endpoints
- `/api/operator/reconciliation/kalshi` - Latest reconciliation report
- `/api/operator/reconciliation/history` - Historical discrepancies
- `/api/v1/system/reconciliation-status` - Real-time status

**Action Required:** Verify these endpoints exist in `operator_router`

---

## 6. Agent Grid Configuration ✅

### Agent Grid Accessor
```python
from merid.prediction.agent_grid import get_agent_grid
```

**Status:** ✅ CALLED in main loop (line 399-401)

### Expected Agents
- `KalshiTradingAgent` - Primary Kalshi market agent
- Multiple prediction agents in grid for consensus

**Startup Integration:**
- Should be initialized in `web/startup_agents.py`
- Grid should start with `grid.start()` on app lifespan

**Action Required:** 
1. Verify agent grid starts on app startup
2. Check `web/startup_agents.py` for grid initialization
3. Confirm agents are enabled by default for prediction domain

---

## 7. Settings Configuration ✅

### KALSHI_ONLY Mode
**File:** `merid/settings.py:166`
```python
KALSHI_ONLY: bool = Field(default=True, description="Kalshi-only mode: restricts UI/API to 8 canonical Kalshi views")
```

**Status:** ✅ CONFIGURED  
**Default:** `True` (Kalshi-only mode enabled by default)

### Router Filtering (web/main.py)
**Lines 402-447:** Non-Kalshi routers conditionally included based on `_kalshi_only` flag

**Effect:** When `KALSHI_ONLY=true`, betting/flow/crypto routers are excluded

---

## 8. WebSocket Streams ⚠️

### Expected WebSocket Endpoints
- `/ws/kalshi/markets` - Real-time Kalshi market updates
- `/ws/kalshi/positions` - Position updates
- `/ws/consensus/prediction` - Consensus vote stream

**Action Required:** Verify WebSocket routes exist for real-time updates

---

## Critical Path Verification Checklist

### Before Reboot, Verify:

**Main Loop:**
- [ ] `python -c "from merid.loop import LoopConfig; cfg=LoopConfig.from_paper_config(); print('prediction' in cfg.active_domains)"` returns `True`
- [ ] Loop starts without errors: `python -m merid.loop` (test mode)

**Venue Registry:**
- [ ] `python -c "from merid.venue_registry import get_venue_registry; r=get_venue_registry(); print('kalshi' in r.list_venues())"` returns `True`

**API Endpoints (test with httpie or curl):**
- [ ] `GET /api/v1/portfolio/summary` returns 200 or 503 (not 404)
- [ ] `GET /api/v1/positions` returns 200 or 503
- [ ] `GET /api/v1/prediction/consensus/summary` returns 200 or 503
- [ ] `GET /api/operator/audit-trail` returns 200 or 503
- [ ] `GET /api/v1/risk/metrics` returns 200 or 503
- [ ] `GET /api/v1/system/health` returns 200

**Agent Grid:**
- [ ] Check logs for "Kalshi agent grid starting" or similar
- [ ] `GET /api/v1/kalshi-grid/agents` returns agent list

**Reconciliation:**
- [ ] Check logs for "Kalshi reconciliation:" messages
- [ ] `GET /api/operator/reconciliation/kalshi` returns report (or 503 if not run yet)

**Settings:**
- [ ] `echo $KALSHI_ONLY` shows `true` (or check .env file)
- [ ] Backend logs show "KALSHI_ONLY mode: ENABLED"

---

## Known Gaps (Require Immediate Attention)

### 1. Consensus Bridge for Prediction Domain
**Status:** ⚠️ NOT VERIFIED  
**Risk:** Medium - Prediction-consensus view may not aggregate signals properly  
**Fix:** Verify `merid/prediction/consensus_adapter.py` exists and integrates with TaCoConsensus

### 2. Agent Grid Startup
**Status:** ⚠️ NOT VERIFIED  
**Risk:** High - Agents may not start automatically on reboot  
**Fix:** Check `web/startup_agents.py` and ensure grid.start() is called

### 3. WebSocket Streams
**Status:** ⚠️ NOT VERIFIED  
**Risk:** Low - Real-time updates may not work, but polling will  
**Fix:** Verify WebSocket routes in `web/main.py`

### 4. Reconciliation API Endpoints
**Status:** ⚠️ NOT VERIFIED  
**Risk:** Low - Operator view may not show reconciliation data  
**Fix:** Verify `operator_router` exposes reconciliation endpoints

---

## Recommendations

### Immediate (Before Reboot):
1. ✅ Run smoke test: `KALSHI_ONLY=true py scripts/smoke_test_kalshi_only.py`
2. ⚠️ Verify agent grid starts: Check `web/startup_agents.py`
3. ⚠️ Test API endpoints: Run manual curl/httpie tests on critical paths
4. ⚠️ Check consensus adapter: Verify prediction domain signals flow to consensus

### Post-Reboot (First 5 Minutes):
1. Monitor logs for "Kalshi agent grid starting"
2. Monitor logs for "Kalshi reconciliation:" messages
3. Check `/api/v1/system/health` endpoint
4. Verify sidebar shows exactly 8 views in UI

### If Issues Detected:
1. Check `KALSHI_ONLY` env var is set
2. Verify "prediction" in `active_domains` from paper_config
3. Check for import errors in logs related to Kalshi modules
4. Verify Kalshi API credentials are set (for live mode)

---

## Test Commands

```bash
# 1. Test main loop config
python -c "from merid.loop import LoopConfig; cfg=LoopConfig.from_paper_config(); print('prediction:', 'prediction' in cfg.active_domains)"

# 2. Test venue registry
python -c "from merid.venue_registry import get_venue_registry; r=get_venue_registry(); print('kalshi venue:', 'kalshi' in r.list_venues())"

# 3. Test settings
python -c "from merid.settings import settings; print('KALSHI_ONLY:', settings.KALSHI_ONLY)"

# 4. Run smoke test
KALSHI_ONLY=true py scripts/smoke_test_kalshi_only.py

# 5. Test Kalshi view endpoints (after server starts)
curl http://localhost:8000/api/v1/portfolio/summary
curl http://localhost:8000/api/v1/positions
curl http://localhost:8000/api/v1/prediction/consensus/summary
curl http://localhost:8000/api/operator/audit-trail
curl http://localhost:8000/api/v1/risk/metrics
curl http://localhost:8000/api/v1/system/health

# 6. Check agent grid status
curl http://localhost:8000/api/v1/kalshi-grid/agents
```

---

**Status:** 🟡 MOSTLY WIRED - 4 items need verification before go-live  
**Next Steps:** Verify agent grid startup, consensus adapter, reconciliation endpoints, WebSocket streams  
**Confidence:** 75% - Core loop and venue integration solid, peripheral integrations need validation
