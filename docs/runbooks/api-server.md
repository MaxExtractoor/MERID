# API Server (FastAPI) Runbook

## Overview
`web/main.py` is the FastAPI application serving all REST and WebSocket endpoints on port `8011`. It is the entry point for the UI, the operator console, and the data pipeline.

---

## Start / Stop / Restart

```powershell
# Dev (auto-reload)
uvicorn web.main:app --reload --host 127.0.0.1 --port 8011

# Production (systemd)
sudo systemctl start  merid-api
sudo systemctl stop   merid-api
sudo systemctl restart merid-api
sudo systemctl status  merid-api

# Production (Docker)
docker compose -f docker-compose.prod.yml up -d merid-api
docker compose -f docker-compose.prod.yml restart merid-api
docker compose -f docker-compose.prod.yml logs -f merid-api

# Kubernetes
kubectl rollout restart deployment/merid-api -n merid
kubectl rollout status  deployment/merid-api -n merid
```

---

## Health Check

```powershell
# Liveness
curl http://localhost:8011/api/v1/health

# Startup state (lists per-service status from lifespan)
curl http://localhost:8011/api/v1/startup-state

# Full observability
curl http://localhost:8011/api/v1/system/observability | python -m json.tool
```

Healthy liveness response:
```json
{"status": "ok", "mode": "paper", "env": "production"}
```

---

## Common Failure Modes

### Server fails to start — missing required production settings
- **Symptom:** Process exits immediately with `ValueError: Missing required production settings: SECRET_KEY, NEO4J_PASSWORD`
- **Fix:** Set the missing env vars in `.env.prod` (or the secrets manager) and restart. Never commit secrets to git.

### Router import failures at startup
- **Symptom:** Logs show `STARTUP: N router import(s) skipped — these endpoints will 404`.
- **Cause:** A dependency of a route module failed to import (missing package, misconfigured env).
- **Fix:** Check which routers are listed in the warning. Install missing packages or fix config. Non-fatal — server still starts with degraded endpoints.

### Port conflict (`Address already in use`)
```powershell
# Find the PID on port 8011
netstat -ano | findstr :8011
# Kill it
taskkill /PID <pid> /F
```

### High memory / CPU
- Check if the swarm is looping tightly: `GET /api/v1/system/observability` → `real_data_fallback_counts`.
- If fallback counts are high and growing, a dependency is failing repeatedly — identify and fix the root cause.
- Restart the server as a last resort; this resets in-memory paper state.

### 502 from nginx / reverse proxy
- Verify `merid-api` container is healthy: `docker inspect merid-api | grep Health`.
- Check if port `8011` is accessible inside the container: `docker exec merid-api curl -s localhost:8011/api/v1/health`.

---

## Safe Restart Checklist (LIVE mode)
Before restarting in LIVE mode:
1. Confirm all open orders on Kalshi are either filled or cancelled.
2. Note current positions — they will need to be reloaded from the venue after restart.
3. Trigger kill switch before restart: `POST /api/v1/operator/kill-switch {"reason": "planned restart"}`.
4. Restart server.
5. Verify reconciliation passes after restart: `GET /api/v1/system/alerts` → `reconciliation_drift`.
6. Re-enable trading: `POST /api/v1/operator/reset-kill-switch`.

---

## Escalation Path
1. Server down + auto-restart failing → page on-call immediately.
2. In LIVE mode, server restart without position snapshot → treat as potential data loss, escalate.
