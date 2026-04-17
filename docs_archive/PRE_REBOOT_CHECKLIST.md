# Pre-Reboot Checklist: Kalshi End-to-End Wiring

**Status:** ✅ READY TO REBOOT  
**Date:** 2026-02-18  
**Critical Fix Applied:** Kalshi agent grid now starts on app startup

---

## What Was Fixed

### 🔧 Agent Grid Startup (CRITICAL)
**File:** `web/startup_agents.py`  
**Change:** Added Kalshi agent grid initialization to `OrchestratorAgentManager.start_all()`

```python
# Start Kalshi agent grid for prediction domain
try:
    from merid.prediction.agent_grid import get_agent_grid
    self.kalshi_agent_grid = get_agent_grid()
    self.kalshi_agent_grid.start()
    logger.info("✅ Kalshi agent grid started")
except Exception as exc:
    logger.warning(f"Kalshi agent grid not started (graceful degradation): {exc}")
```

**Impact:** Agents will now run automatically on app startup, powering the `predictions` and `prediction-consensus` views.

---

## Verified Components (All ✅)

### 1. Main Loop Integration
- ✅ Kalshi signal generation (lines 338-361)
- ✅ Kalshi agent cycle (lines 392-428)
- ✅ Kalshi reconciliation (lines 700-740)
- ✅ Execution pipeline with venue adapter routing

### 2. Venue Registry
- ✅ Kalshi adapter registered on startup
- ✅ `get_all_positions(kalshi_only=True)` implemented
- ✅ `get_all_risk_snapshots(kalshi_only=True)` implemented

### 3. API Routers
- ✅ `kalshi_api_router` mounted at `/api/v1`
- ✅ `kalshi_ui_router` mounted at `/api/v1`
- ✅ `kalshi_grid_router` mounted at `/api/v1`
- ✅ `kalshi_agent_grid_router` mounted

### 4. Settings Configuration
- ✅ `KALSHI_ONLY: bool = True` (default enabled)
- ✅ Router filtering based on `KALSHI_ONLY` flag

### 5. TypeScript Manifest
- ✅ Regenerated with `kalshiOnly: boolean` field
- ✅ `kalshiOnlyViews()` helper function available

### 6. Test Suite
- ✅ `test_kalshi_only_views.py` with frozen set assertions
- ✅ Smoke test script `scripts/smoke_test_kalshi_only.py`
- ✅ Repo-wide grep test for direct Kalshi API calls

---

## 8 Kalshi Views → Backend Wiring Map

| View | Powered By | Status |
|------|------------|--------|
| **predictions** | Main loop signals + agent grid + venue_registry | ✅ |
| **prediction-consensus** | Consensus coordinator + agent grid | ✅ |
| **overview** | Venue_registry positions/orders | ✅ |
| **positions** | Venue_registry.get_all_positions(kalshi_only=True) | ✅ |
| **signal-layer** | Main loop Kalshi signals + drift detector | ✅ |
| **operator** | Reconciliation module + audit trail | ✅ |
| **risk** | Risk manager + venue_registry | ✅ |
| **health** | System health + venue health checks | ✅ |

---

## Reboot Command

```bash
# Set environment
export KALSHI_ONLY=true
export MERID_PM_TRADING_MODE=paper  # or 'live' for real trading

# Start backend
cd /path/to/MERID
uvicorn web.main:app --host 0.0.0.0 --port 8000

# Or with main.py
python -m web.main
```

---

## Post-Reboot Verification (First 60 Seconds)

### Critical Log Lines to Watch For

**✅ MUST SEE:**
```
Starting application lifespan...
✅ Orchestrator agents started
✅ Kalshi agent grid started
MERID loop starting: domains=[prediction=paper], ...
```

**❌ FAILURE INDICATORS:**
```
Failed to register Kalshi venue: ...
Kalshi agent grid not started (graceful degradation): ...
ImportError: cannot import name 'get_agent_grid'
```

### Health Check Commands

```bash
# 1. Check app is running
curl http://localhost:8000/api/v1/system/health

# 2. Verify Kalshi venue registered
curl http://localhost:8000/api/v1/portfolio/summary

# 3. Check agent grid status
curl http://localhost:8000/api/v1/kalshi-grid/agents

# 4. Verify prediction consensus
curl http://localhost:8000/api/v1/prediction/consensus/summary

# 5. Check reconciliation
curl http://localhost:8000/api/operator/audit-trail

# 6. Verify risk metrics
curl http://localhost:8000/api/v1/risk/metrics
```

### Expected Responses

| Endpoint | Success | Failure |
|----------|---------|---------|
| `/api/v1/system/health` | 200 with `{"status": "healthy"}` | 503 |
| `/api/v1/portfolio/summary` | 200 or 503 (not 404) | 404 = router not mounted |
| `/api/v1/kalshi-grid/agents` | 200 with agent list | 404 or 500 |
| `/api/v1/prediction/consensus/summary` | 200 with consensus data | 503 (OK if no data yet) |
| `/api/operator/audit-trail` | 200 with trail | 503 |
| `/api/v1/risk/metrics` | 200 with metrics | 503 |

**Note:** 503 = "Service available but no data yet" is OK for first minute. 404 = "Route not found" is BAD.

---

## Frontend Verification

### Open in Browser
```
http://localhost:8000/  # or your frontend URL
```

### Check Sidebar
**MUST SHOW (8 views only):**
- Overview
- Positions  
- Prediction Markets
- Prediction Consensus
- Signal Layer
- Operator
- Risk & Health
- System Health

**MUST NOT SHOW (if KALSHI_ONLY=true):**
- Betting Markets
- Flow Radar
- Trade Floor
- Crypto Trading
- Wallet
- Treasury
- Agents
- Dev Swarm

---

## Troubleshooting

### If agent grid doesn't start

**Check logs for:**
```
Kalshi agent grid not started (graceful degradation): No module named 'merid.prediction.agent_grid'
```

**Fix:**
```bash
# Verify module exists
python -c "from merid.prediction.agent_grid import get_agent_grid; print('OK')"

# If fails, check file exists
ls merid/prediction/agent_grid.py
```

### If venue registry fails

**Check logs for:**
```
Failed to register Kalshi venue: ...
```

**Fix:**
```bash
# Verify Kalshi adapter exists
python -c "from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter; print('OK')"

# Check Kalshi credentials
echo $KALSHI_API_KEY_ID
echo $KALSHI_PRIVATE_KEY_PATH
```

### If reconciliation fails

**Check logs for:**
```
Reconciliation failed: No module named 'merid.reconciliation'
```

**Fix:**
```bash
# Verify reconciliation module exists
python -c "from merid.reconciliation import get_kalshi_reconciler; print('OK')"

# If missing, reconciliation will be skipped (not critical for first boot)
```

---

## Success Criteria

### Backend ✅
- [ ] App starts without exceptions
- [ ] Log shows "✅ Kalshi agent grid started"
- [ ] Log shows "MERID loop starting: domains=[prediction=..."
- [ ] `/api/v1/system/health` returns 200
- [ ] At least 4 of 6 health check endpoints return 200 or 503 (not 404)

### Frontend ✅
- [ ] Sidebar shows exactly 8 views
- [ ] No betting/crypto/flow views visible
- [ ] Overview page loads without console errors
- [ ] Predictions page loads market data (or shows empty state)
- [ ] Agent grid page shows agents (or "No agents running" message)

### Loop ✅
- [ ] Main loop ticks every ~5 seconds (check logs)
- [ ] "features_refreshed" appears in tick summary
- [ ] "kalshi_signals" or "kalshi_agents" appears in tick summary
- [ ] "reconciliation" appears every ~2 minutes

---

## Go/No-Go Decision

### GO ✅ (Safe to proceed with live Kalshi)
- All backend success criteria met
- Frontend loads without errors
- Agent grid running
- Reconciliation shows "OK" or "WARNING" (not "CRITICAL")

### NO-GO ❌ (Stay in paper mode)
- Agent grid fails to start
- More than 2 health check endpoints return 404
- Reconciliation shows "CRITICAL" issues
- Frontend console shows React errors related to Kalshi views

---

## Rollback Plan

If issues detected:

```bash
# 1. Stop the server
# Ctrl+C or kill process

# 2. Revert agent grid changes
git checkout web/startup_agents.py

# 3. Restart without Kalshi agent grid
# Grid will be initialized by main loop but not auto-started

# 4. Investigate logs
tail -f logs/merid.log | grep -i kalshi
```

---

## Files Modified in This Session

1. `merid/ui_views_manifest.py` - Added `kalshi_only: bool` flag to 8 views
2. `scripts/generate_ts_manifest.py` - Updated to export `kalshiOnly` field
3. `merid/venue_registry.py` - Added `kalshi_only` parameter to methods
4. `merid/settings.py` - Added `KALSHI_ONLY: bool = True`
5. `tests/test_kalshi_only_views.py` - Created comprehensive test suite
6. `scripts/smoke_test_kalshi_only.py` - Created smoke test script
7. `web/startup_agents.py` - **CRITICAL: Added Kalshi agent grid startup**
8. `KALSHI_ONLY_MODE.md` - Created documentation
9. `KALSHI_GO_LIVE_CHECKLIST.md` - Updated with guardrails
10. `.windsurf/prompts/KALSHI_ONLY_AGENT_RULES.md` - Created agent prompt
11. `KALSHI_WIRING_REPORT.md` - Created wiring audit
12. `PRE_REBOOT_CHECKLIST.md` - This file

---

## Next Steps After Successful Reboot

1. Run full test suite: `pytest tests/test_kalshi_only_views.py -v`
2. Monitor loop performance for 5 minutes
3. Check agent grid metrics: `/api/v1/kalshi-grid/agents`
4. Verify reconciliation runs: Check logs for "Kalshi reconciliation:"
5. If all green → Proceed with Kalshi Go-Live Checklist (Section 6)

---

**Status:** 🟢 READY  
**Confidence:** 95%  
**Blocking Issues:** None  
**Recommendation:** PROCEED WITH REBOOT
