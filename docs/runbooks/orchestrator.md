# Orchestrator / MeridLoop Runbook

## Overview
`merid/loop.py` is the main trading loop. It drives agent opinion cycles, reconciliation, kill-switch checks, and Kalshi execution. It runs as a background asyncio task started at server boot.

---

## Start / Stop / Restart

### Via FastAPI server (normal)
The loop starts automatically inside `_app_lifespan` in `web/main.py`.  
Restarting the server restarts the loop:
```powershell
# Dev
uvicorn web.main:app --reload --port 8011

# Systemd
sudo systemctl restart merid-api

# Docker
docker compose restart merid-api
```

### Emergency stop (no server restart)
The loop checks `MERID_ALLOW_LIVE_TRADES` and the execution gate on each cycle.  
To halt execution without restarting:
1. Set `MERID_ALLOW_LIVE_TRADES=false` in the process env and send SIGHUP, **or**
2. Trigger the kill switch via the operator API:
   ```
   POST /api/v1/operator/kill-switch  {"reason": "manual halt"}
   ```

---

## Health Check

```powershell
# Is the loop running?
curl http://localhost:8011/api/v1/health

# Is reconciliation current?
curl http://localhost:8011/api/v1/system/observability | python -m json.tool | grep reconcil

# Are agents producing opinions?
curl http://localhost:8011/api/v1/system/alerts | python -m json.tool | grep opinion_freshness
```

Expected healthy output: `"all_ok": true` in reconciliation, `"firing": false` on opinion freshness.

---

## Common Failure Modes

### Loop stops producing opinions
- **Symptom:** `opinion_freshness` alert fires; `no_active_agents` alert fires.
- **Cause:** Agent registry failed to bootstrap, or consensus coordinator threw on init.
- **Fix:** Check server logs for `STARTUP:` lines. If canonical_registry shows `"status": "failed"`, restart the server. If it persists, check `merid/agents/bootstrap.py` for import errors.

### Loop stuck in reconciliation
- **Symptom:** `ReconciliationDriftAlert` fires; `all_ok: false` in report.
- **Cause:** Position drift vs. Kalshi venue state, or paper engine ledger corruption.
- **Fix:**
  1. Check which checks failed: `GET /api/v1/system/alerts` → `reconciliation_drift.detail.failed_checks`.
  2. If `balance_identity` fails: restart paper engine (server restart clears in-memory ledger).
  3. If `ghost_positions` fails: run `scripts/run_reconciliation.py --fix` (paper mode only).
  4. Never auto-fix in LIVE mode — escalate.

### Kill switch triggered unexpectedly
- **Symptom:** `risk_kill_switch` alert fires; no orders accepted.
- **Cause:** Daily loss limit hit, or manual trigger.
- **Fix:** Check `GET /api/v1/risk/status` for `kill_reason`. If daily limit: wait for reset at midnight UTC. If manual: verify the cause is resolved, then reset via `POST /api/v1/operator/reset-kill-switch`.

---

## Escalation Path
1. On-call engineer checks alerts dashboard.
2. If `critical` alerts firing and auto-recovery not happening within 5 min → page lead.
3. If LIVE mode and unexplained position drift → halt via kill switch immediately, then investigate.
