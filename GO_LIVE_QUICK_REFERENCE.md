# Go-Live Quick Reference - MERID Kalshi Trading

**Purpose:** Quick reference for enabling live Kalshi trading after execution halt recovery.

---

## Pre-Flight Checklist (5 Minutes)

### Step 1: Configure .env
```bash
# Production Kalshi API
KALSHI_ENV=prod
KALSHI_USE_DEMO=false
KALSHI_API_KEY_ID=<your_production_key>
KALSHI_PRIVATE_KEY_PATH=/path/to/prod_key.pem

# Enable live trading (ALL THREE required)
MERID_PM_TRADING_MODE=live
MERID_PM_LIVE_ENABLED=true
MERID_LIVE_TRADING_UNLOCKED=true
```

### Step 2: Run Diagnostics
```bash
python scripts/system_diagnostics.py
# ✅ Expected: "SYSTEM READY FOR LIVE TRADING"
```

### Step 3: Run Preflight
```bash
python scripts/go_live_preflight.py
# ✅ Expected: "ALL 10/10 GATES PASSED"
```

### Step 4: Start System
```bash
python -m web.main
# ✅ Check logs for:
#    - Kalshi Agent Grid started
#    - WebSocket connected
#    - Market catalog refreshed
```

### Step 5: Verify APIs
```bash
# Dependency health
curl http://localhost:8011/api/v1/dependencies/health
# ✅ Expected: {"overall_status": "healthy"}

# Execution gate
curl http://localhost:8011/api/v1/execution/gate
# ✅ Expected: {"gate_state": "clear", "safe_to_trade": true}
```

---

## Emergency Stop (Instant)

```bash
# Activate kill switch
curl -X POST http://localhost:8011/api/v1/operator/activate-kill-switch \
  -H "Content-Type: application/json" \
  -d '{"reason": "emergency_halt"}'
```

---

## Health Monitoring URLs

| Endpoint | Purpose |
|----------|---------|
| `/api/v1/dependencies/health` | Overall dependency status |
| `/api/v1/dependencies/websocket` | WebSocket connection details |
| `/api/v1/dependencies/catalog` | Market catalog freshness |
| `/api/v1/dependencies/ready` | Boolean ready/not-ready |
| `/api/v1/execution/gate` | Execution gate status |
| `/api/v1/kalshi-grid/health` | Agent grid health |

---

## Common Issues & Fixes

### WebSocket Not Connected

**Symptom:** Gate 9 fails, dependency health shows WebSocket down

**Fix:**
1. Ensure system is running (`python -m web.main`)
2. Wait 30 seconds for connection
3. Check logs for auth errors
4. Verify credentials in .env

### Market Catalog Empty/Stale

**Symptom:** Gate 10 fails, catalog shows 0 markets or age > 600s

**Fix:**
1. Ensure system is running
2. Wait for initial refresh (happens on startup)
3. Check logs for API errors
4. Verify Kalshi API connectivity

### KALSHI_ENV Mismatch

**Symptom:** Validation error about inconsistent demo/prod config

**Fix:**
```bash
# Production (both must be prod/false)
KALSHI_ENV=prod
KALSHI_USE_DEMO=false

# Demo (both must be demo/true)
KALSHI_ENV=demo
KALSHI_USE_DEMO=true
```

---

## What Changed (Summary)

**New Safety Checks:**
- ✅ WebSocket health validated before trading
- ✅ Market catalog freshness validated
- ✅ KALSHI_ENV explicitly configured
- ✅ Environment consistency enforced

**New Scripts:**
- `scripts/system_diagnostics.py` - Full system audit
- `scripts/go_live_preflight.py` - Now checks 10 gates (was 8)

**New API Endpoints:**
- `/api/v1/dependencies/health` - Monitor subsystem health
- `/api/v1/dependencies/websocket` - WebSocket details
- `/api/v1/dependencies/catalog` - Catalog details
- `/api/v1/dependencies/ready` - Quick ready check

---

## Expected System State (Live Ready)

```
Environment:
  KALSHI_ENV: prod
  KALSHI_USE_DEMO: false
  MERID_PM_TRADING_MODE: live
  MERID_PM_LIVE_ENABLED: true
  MERID_LIVE_TRADING_UNLOCKED: true

Dependencies:
  overall_status: healthy
  kalshi_websocket: healthy (connected, messages flowing)
  market_catalog: healthy (250+ markets, < 600s old)

Execution Gate:
  gate_state: clear
  safe_to_trade: true
  blocked: false
  reasons: [] (no blocking issues)

Preflight Check:
  10/10 gates: PASS
```

---

## Post-Launch Monitoring (First 24 Hours)

**Monitor Every 5 Minutes:**
- [ ] Dependency health status (`/api/v1/dependencies/health`)
- [ ] Execution gate status (`/api/v1/execution/gate`)
- [ ] Agent grid health (`/api/v1/kalshi-grid/health`)
- [ ] WebSocket connection uptime
- [ ] Market catalog refresh success rate

**Alert Thresholds:**
- WebSocket disconnected for > 60 seconds → investigate
- Market catalog age > 600 seconds → investigate
- Execution gate blocked → stop trading, diagnose
- Agent grid crashed → restart, investigate
- Kill switch triggered → investigate reason

**Manual Checks:**
- [ ] First 10 trades executed successfully
- [ ] Order fills received via WebSocket
- [ ] Position tracking accurate
- [ ] PnL calculations correct
- [ ] No execution errors in logs

---

## Rollback Procedure

If issues occur:

1. **Immediate:** Activate kill switch (stops all trading)
2. **Switch to paper mode** in .env
3. **Restart system**
4. **Investigate** using logs and health endpoints
5. **Fix issues**
6. **Re-run diagnostics and preflight**
7. **Attempt go-live again** when ready

---

**Document Owner:** MERID Operations Team
**Last Updated:** 2026-03-26
**Version:** 1.0
