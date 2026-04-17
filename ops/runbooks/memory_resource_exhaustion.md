# Runbook: Memory / Resource Exhaustion

**ID:** RB-OPS-005  
**Severity:** Warning → Critical  
**Trigger:** `process_resident_memory_bytes` > 80% of container limit, or OOM kill detected

## Symptoms

- Container restarts with OOM exit code (137)
- `merid_dev_swarm_storage_size_bytes` growing unbounded
- API latency spikes (p95 > 1s)
- Health probe failures: `/healthz` returns 503
- systemd journal shows `oom-kill` entries

## Immediate Actions (T0 — Automated)

1. systemd `Restart=always` auto-restarts the process
2. Kubernetes liveness probe triggers pod restart
3. Alert fires: `HighMemoryUsage` rule in `alert_rules.yml`

## Triage (T1 — On-Call Engineer, < 15 min)

1. Check current memory usage:
   ```bash
   docker stats merid-api
   # or
   kubectl top pod -n merid
   ```
2. Check Prometheus: `process_resident_memory_bytes{job="merid-api"}`
3. Identify growth pattern:
   - **Sudden spike** → likely a single large operation (backtest, bulk import)
   - **Gradual leak** → likely unbounded cache, history, or connection pool

## Common Causes & Fixes

### 1. Task History Unbounded Growth
- **Check:** `merid_dev_swarm_task_history_length` gauge
- **Fix:** Verify `DevSwarm.MAX_HISTORY` is enforced; reduce if needed
- **Immediate:** Restart process (history is trimmed on restart)

### 2. Audit Trail In-Memory Growth
- **Check:** `len(audit_trail.entries)` via `/api/dev-swarm/stats`
- **Fix:** Audit entries should be flushed to disk; check `_persist_entry()`
- **Immediate:** Restart; entries reload from JSONL on disk

### 3. Redis Connection Pool Leak
- **Check:** `redis-cli info clients` — look for `connected_clients` growing
- **Fix:** Ensure all Redis connections use context managers
- **Immediate:** `redis-cli client kill` stale connections

### 4. Neo4j Driver Leak
- **Check:** Neo4j browser → `:sysinfo` → active connections
- **Fix:** Ensure driver sessions are closed after use
- **Immediate:** Restart Neo4j driver pool

### 5. Large Backtest Results
- **Check:** Celery task queue for stuck/large backtest tasks
- **Fix:** Add memory limit to backtest tasks; stream results to disk
- **Immediate:** Kill stuck Celery task: `celery -A core.celery_tasks control revoke <task_id>`

## Resolution Steps

1. Identify root cause from list above
2. Apply immediate fix (restart or kill)
3. Apply permanent fix (code change + PR)
4. Add regression test if applicable
5. Update memory limits in:
   - `deploy/merid-dev-swarm.service` → `MemoryMax=`
   - `deploy/k8s/merid-deployment.yaml` → `resources.limits.memory`
   - `docker-compose.yml` → `deploy.resources.limits.memory`

## Prevention

- Monitor `process_resident_memory_bytes` with alert at 70% and 85% thresholds
- Set `MAX_HISTORY` bounds on all in-memory collections
- Use streaming/pagination for large result sets
- Run weekly memory profiling: `python -m memray run -o profile.bin main.py`

## Escalation

- If OOM recurs within 1 hour after restart → escalate to T2
- If multiple services OOM simultaneously → declare infrastructure incident
