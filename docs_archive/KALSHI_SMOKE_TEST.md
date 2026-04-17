# Kalshi Integration Smoke Test

**Date:** 2026-02-17  
**Purpose:** Validate Kalshi → MERID → OpenClaw integration in paper mode

---

## ✅ Pre-Flight Checklist

### **1. Verify Paper Mode Configuration**

Check `merid/paper_config.py` around line 250:

```python
"prediction": DomainConfig(
    name="prediction",
    mode=DomainMode.PAPER,  # ← Must be PAPER
    enabled=True,           # ← Must be True
    venues=["kalshi"],      # ← Must include "kalshi"
    reconciliation_venue="kalshi",  # ← Set for reconciliation
    # ...
)
```

**Expected:** Paper mode enabled, Kalshi venue registered.

---

### **2. Environment Variables**

Ensure Kalshi credentials are set (use demo API by default):

```bash
# Windows PowerShell
$env:KALSHI_API_BASE = "https://demo-api.kalshi.co/trade-api/v2"
$env:KALSHI_USE_DEMO = "true"
$env:KALSHI_EMAIL = "your-demo-email@example.com"
$env:KALSHI_PASSWORD = "your-demo-password"

# OR use RSA key auth (recommended for production)
$env:KALSHI_PRIVATE_KEY_PATH = "path/to/kalshi_rsa_key.pem"
```

**Verify:**
```powershell
echo $env:KALSHI_USE_DEMO
# Should output: true
```

---

## 🚀 Startup Sequence

### **Step 1: Start MERID Backend**

```powershell
# In MERID root directory
cd c:\Dev\MERID

# Start FastAPI server
uvicorn web.main:app --reload --host 127.0.0.1 --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Application startup complete.
```

---

### **Step 2: Start MERID Loop** (in separate terminal)

```powershell
# In MERID root directory
cd c:\Dev\MERID

# Start main loop
python -m merid.loop
```

**Expected output (watch for these lines):**
```
INFO:merid.loop: Loop initialized: prediction domain active
INFO:merid.matching_engine: Matching engine ready: domain=prediction
INFO:merid.venue_registry: Venue registry initialized for prediction domain
INFO:merid.prediction.agent_grid: AgentGrid initialized: N agents
```

---

### **Step 3: Optional - Start Kalshi Agent Grid** (if not auto-started)

```powershell
# If agent grid has separate entrypoint
python -m merid.prediction.agent_grid
```

---

## 🧪 **Verification Tests**

### **Test A: Health Check**

```powershell
# Test Kalshi health endpoint
curl http://127.0.0.1:8000/api/v1/kalshi/health

# Expected response:
# {"status": "healthy", "venue": "kalshi", "mode": "paper", ...}
```

---

### **Test B: Positions & Orders**

```powershell
# Get current positions
curl http://127.0.0.1:8000/api/v1/kalshi/positions

# Expected: [] or [{market_id: "...", size: ..., ...}]

# Get current orders
curl http://127.0.0.1:8000/api/v1/kalshi/orders

# Expected: [] or [{order_id: "...", status: "...", ...}]
```

---

### **Test C: Agent Grid Status**

```powershell
curl http://127.0.0.1:8000/api/v1/kalshi-grid/status

# Expected response:
# {
#   "running": true,
#   "agents": [...],
#   "total_signals": N,
#   "total_orders": N,
#   ...
# }
```

---

### **Test D: Reconciliation Status**

```powershell
curl http://127.0.0.1:8000/api/v1/kalshi/reconciliation

# Expected response:
# {
#   "severity": "OK",  # or "WARNING" or "CRITICAL"
#   "summary": "All positions and orders reconciled successfully",
#   "issue_count": 0,
#   "issues": [],
#   ...
# }
```

**⚠️ If severity is CRITICAL:** Check reconciliation issues and resolve before trading.

---

### **Test E: Operator Summary**

```powershell
curl http://127.0.0.1:8000/api/operator/summary

# Expected (look for these keys):
# {
#   "domains": {..., "prediction": {...}},
#   "reconciliation": {
#     "kalshi": {
#       "severity": "OK",
#       ...
#     }
#   },
#   ...
# }
```

---

## 📊 **Log Monitoring**

### **What to Watch For (in loop logs):**

**Every ~30 seconds (Feature Refresh):**
```
INFO:merid.signals.kalshi: Generated N Kalshi signals
INFO:merid.loop: kalshi_signals:N
```

**Every ~60 seconds (Agent Cycle):**
```
INFO:merid.loop: Kalshi agents generated N actionable signals this cycle
INFO:merid.loop: kalshi_agents:Nsignals
```

**Every ~120 seconds (Reconciliation):**
```
INFO:merid.reconciliation.kalshi: Reconciling: X internal pos, Y venue pos, ...
INFO:merid.reconciliation.kalshi: Reconciliation complete: OK (or WARNING/CRITICAL)
INFO:merid.loop: reconciliation:OK
```

**If CRITICAL Reconciliation:**
```
ERROR:merid.loop: CRITICAL reconciliation issues detected for Kalshi: ...
ERROR:merid.loop: Blocking new executions.
INFO:merid.loop: reconciliation:CRITICAL:blocked_prediction_domain
```

---

## 🎯 **Concrete Smoke Flow: DOGE Market**

### **Scenario: Paper-trade a DOGE prediction market**

**1. Find a DOGE Market**

In browser, navigate to:
```
http://127.0.0.1:3000/kalshi/dashboard
```

Filter to:
- Category: Crypto
- Search: "DOGE"

Pick an active market like: `DOGE-24FEB-0.50-YES`

**2. Check Edge Signal**

```powershell
curl "http://127.0.0.1:8000/api/v1/kalshi/edge?ticker=DOGE-24FEB-0.50-YES"

# Expected:
# {
#   "ticker": "DOGE-24FEB-0.50-YES",
#   "implied_prob": 0.55,
#   "model_prob": 0.58,
#   "edge_pct": 5.45,
#   "confidence": 0.65,
#   ...
# }
```

**3. Let Agent Grid Run**

Wait 2-3 minutes for:
- Feature refresh (Kalshi signals generated)
- Agent cycle (DOGE market evaluated)
- If edge > threshold, agent should place paper order

**4. Check Orders**

```powershell
curl http://127.0.0.1:8000/api/v1/kalshi/orders

# Should show order if agent triggered:
# [{
#   "order_id": "ME-...",
#   "market_id": "DOGE-24FEB-0.50-YES",
#   "side": "buy",
#   "status": "filled",  # Paper mode = instant fill
#   ...
# }]
```

**5. Check Positions**

```powershell
curl http://127.0.0.1:8000/api/v1/kalshi/positions

# Should show position:
# [{
#   "market_id": "DOGE-24FEB-0.50-YES",
#   "size": 10.0,
#   "average_entry_price": 0.55,
#   ...
# }]
```

**6. Verify Reconciliation**

```powershell
curl http://127.0.0.1:8000/api/v1/kalshi/reconciliation

# In paper mode, internal positions may not match venue (expected)
# Severity should be WARNING (missing position on venue) or OK
```

---

## 🤖 **OpenClaw Integration**

### **Tool Definitions for OpenClaw**

Add these tools to your OpenClaw MERID skill:

**Tool 1: `get_merid_summary`**
```json
{
  "name": "get_merid_summary",
  "description": "Get MERID operator summary including all domain status, risk, and reconciliation",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  },
  "endpoint": "http://127.0.0.1:8000/api/operator/summary",
  "method": "GET"
}
```

**Tool 2: `get_kalshi_grid_status`**
```json
{
  "name": "get_kalshi_grid_status",
  "description": "Get Kalshi agent grid status including running agents and signal counts",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  },
  "endpoint": "http://127.0.0.1:8000/api/v1/kalshi-grid/status",
  "method": "GET"
}
```

**Tool 3: `get_kalshi_reconciliation`**
```json
{
  "name": "get_kalshi_reconciliation",
  "description": "Get Kalshi position reconciliation status. CRITICAL severity blocks execution.",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  },
  "endpoint": "http://127.0.0.1:8000/api/v1/kalshi/reconciliation",
  "method": "GET"
}
```

**Tool 4: `get_kalshi_positions`**
```json
{
  "name": "get_kalshi_positions",
  "description": "Get current Kalshi positions (paper or live mode)",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  },
  "endpoint": "http://127.0.0.1:8000/api/v1/kalshi/positions",
  "method": "GET"
}
```

**Tool 5: `get_kalshi_edge_signal`**
```json
{
  "name": "get_kalshi_edge_signal",
  "description": "Get edge signal for a specific Kalshi market ticker",
  "parameters": {
    "type": "object",
    "properties": {
      "ticker": {
        "type": "string",
        "description": "Kalshi market ticker (e.g., DOGE-24FEB-0.50-YES)"
      }
    },
    "required": ["ticker"]
  },
  "endpoint": "http://127.0.0.1:8000/api/v1/kalshi/edge",
  "method": "GET"
}
```

---

### **OpenClaw System Prompt Addition**

Add to your OpenClaw MERID system prompt:

```
KALSHI TRADING RULES:

Before approving any Kalshi trade:
1. Call get_kalshi_reconciliation and CHECK severity.
   - If severity is "CRITICAL", REFUSE the trade and explain reconciliation issues must be resolved first.
   
2. Call get_kalshi_grid_status to confirm grid is running.
   - If not running, cannot execute trades.

3. Call get_merid_summary to verify mode.
   - Must be in "paper" mode for testing.
   - Never allow live trades without explicit user confirmation.

4. For edge-based trades:
   - Require edge_pct >= 3.0% AND confidence >= 0.5 for approval.
   - Explain edge calculation and model probability vs. implied probability.

5. Always check current positions before placing orders to avoid overexposure.
```

---

### **OpenClaw Test Query**

In OpenClaw chat, ask:

```
Summarize current Kalshi crypto exposure and top 3 edge opportunities 
the swarm is considering in paper mode.
```

**Expected Behavior:**
1. Calls `get_merid_summary` to check mode
2. Calls `get_kalshi_positions` for exposure
3. Calls `get_kalshi_reconciliation` for safety
4. Calls `get_kalshi_grid_status` for agent status
5. Responds with:
   - Current positions (if any)
   - Top edge opportunities from signals
   - Confirmation that paper mode is active
   - Reconciliation status

---

## 🐛 **Troubleshooting**

### **Issue: "Kalshi signals: 0" in logs**

**Cause:** KalshiVenueAdapter not returning markets.

**Fix:**
1. Check `KALSHI_USE_DEMO=true` is set
2. Verify demo API credentials
3. Check logs for: `"Failed to fetch Kalshi positions: ..."`

---

### **Issue: "Kalshi agent grid not running"**

**Cause:** Agent grid not started or crashed.

**Fix:**
1. Check if `get_agent_grid()` was called during loop init
2. Manually start: `python -m merid.prediction.agent_grid`
3. Check for import errors in agent_grid.py

---

### **Issue: "Reconciliation CRITICAL"**

**Cause:** Phantom positions or quantity mismatches.

**Fix:**
1. Check reconciliation details: `curl .../kalshi/reconciliation`
2. In paper mode, phantom venue positions are expected (venue has real data, MERID has paper data)
3. If you want to clear: reset matching engine or adjust reconciliation thresholds

---

### **Issue: "Module not found: merid.reconciliation"**

**Cause:** Missing `__init__.py` in reconciliation directory.

**Fix:**
```powershell
# Create if missing
New-Item -ItemType File -Path "c:\Dev\MERID\merid\reconciliation\__init__.py"
```

---

## ✅ **Success Criteria**

Your integration is working if:

- [x] Loop starts without errors
- [x] Kalshi signals generated every ~30s
- [x] Agent cycle logs actionable signals
- [x] Reconciliation runs every ~120s with severity OK/WARNING
- [x] `/api/v1/kalshi/health` returns healthy
- [x] `/api/v1/kalshi-grid/status` shows running agents
- [x] Paper orders placed and filled by agents
- [x] OpenClaw can query MERID tools successfully
- [x] Reconciliation blocks execution if CRITICAL

---

## 📝 **Next Steps**

Once smoke test passes:

1. **Add news mapping** - Map BTC/DOGE/ETH news events → Kalshi tickers
2. **Create signals summary endpoint** - `/api/v1/kalshi/signals/summary` for OpenClaw
3. **Build operator panel** - React component showing reconciliation + risk events
4. **Tune thresholds** - Adjust edge/confidence requirements based on paper trading results

---

## 🎉 **You're Done When...**

You can ask OpenClaw:

> "What's the best Kalshi crypto opportunity right now and why?"

And it:
- Checks reconciliation (OK)
- Checks grid status (running)
- Returns top edge signal with explanation
- Respects paper mode guards

**That's the full Kalshi → MERID → OpenClaw pipeline working!** 🚀
