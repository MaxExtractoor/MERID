# Incident Playbooks

## P0 — Live Trading Halt (unexpected)

**Trigger:** `risk_kill_switch` alert firing AND `MERID_TRADING_MODE=live`.

### Response
1. **Acknowledge** — confirm kill switch is active: `GET /api/v1/risk/status` → check `kill_reason`.
2. **Diagnose** — determine cause:
   - `daily_loss_limit` → review PnL: `GET /api/v1/paper/risk-metrics`
   - `circuit_breaker_open` → check which venue: `GET /api/v1/system/alerts` → `circuit_breaker_open`
   - `manual` → find who triggered it and why (check audit log: `audit/mode_transitions.jsonl`)
3. **Contain** — if cause is unknown or unresolved, leave kill switch active.
4. **Resolve** — once root cause is confirmed safe:
   - `POST /api/v1/operator/reset-kill-switch {"reason": "resolved: <explanation>"}`
5. **Post-mortem** — file a GitHub issue with timeline, root cause, and prevention steps.

---

## P1 — Venue Outage (Kalshi unreachable)

**Trigger:** `circuit_breaker_open` alert firing for `kalshi`.

### Response
1. Check Kalshi status page / Twitter for outage announcements.
2. Check `GET /api/v1/kalshi/ws/status` — look at `reconnect_count` and time since last message.
3. **No action needed** if circuit breaker is open — it will auto-retry every 30s (`KALSHI_CIRCUIT_RECOVERY_TIMEOUT`).
4. If outage > 30 min: optionally switch to paper mode: `POST /api/v1/operator/set-mode {"mode": "paper", "reason": "venue outage"}`.
5. Once Kalshi recovers, circuit breaker half-opens automatically. Monitor fills for 5 min before considering venue healthy.
6. If positions were open during outage: run reconciliation manually: `python scripts/run_reconciliation.py` — verify `all_ok: true` before re-enabling live trading.

---

## P1 — Runaway Agent (fills exceeding risk limits)

**Trigger:** Unusual fill volume, daily loss approaching limit, or `no_active_agents` + `reconciliation_drift` firing simultaneously.

### Response
1. **Immediate:** trigger kill switch: `POST /api/v1/operator/kill-switch {"reason": "runaway agent suspected"}`.
2. Identify the agent: `GET /api/v1/agents/activity` — look for anomalous `tasks_completed` or `last_action`.
3. Check recent fills: `GET /api/v1/paper/trades` — filter by agent_id.
4. Check execution guard logs: search server logs for `ExecutionGuard` entries for that agent.
5. **Contain:** disable the specific agent via the agent management API or by removing it from the manifest (`config/agent_manifest.yml`).
6. Restart server with kill switch still active.
7. Verify reconciliation: `GET /api/v1/system/alerts` → `reconciliation_drift` must be `firing: false`.
8. Re-enable trading only after root cause is identified and fixed.

---

## P2 — Bad Deploy (performance regression or errors spike after deploy)

**Trigger:** New deploy followed by alert spike or error rate increase within 15 min.

### Response
1. Check `real_data_fallback_counts` in observability for new error categories.
2. Check server logs for new tracebacks not present before the deploy.
3. **Rollback decision:** if critical alerts firing or live trading affected:
   ```powershell
   # Docker rollback
   docker compose -f docker-compose.prod.yml down
   docker image tag merid-api:previous merid-api:latest
   docker compose -f docker-compose.prod.yml up -d

   # Kubernetes rollback
   kubectl rollout undo deployment/merid-api -n merid
   ```
4. After rollback: verify alerts clear within 5 min.
5. File a GitHub issue with the failing commit SHA, symptoms, and rollback action taken.

---

## P2 — Data Corruption (reconciliation drift persists)

**Trigger:** `reconciliation_drift` alert firing for > 2 consecutive reconciliation cycles (10+ min).

### Response
1. Halt trading (paper or live): kill switch or `MERID_TRADING_MODE=paper`.
2. Identify failed checks: `GET /api/v1/system/alerts` → `reconciliation_drift.detail.failed_checks`.
3. Run detailed reconciliation: `python scripts/run_reconciliation.py --verbose`.
4. **Paper mode:** restart server — in-memory ledger resets, reconciliation should pass on next cycle.
5. **Live mode:** DO NOT restart without first exporting current positions from the venue:
   ```powershell
   python scripts/export_venue_positions.py --venue kalshi --output positions_backup.json
   ```
   Then restart and reconcile against the backup.
6. If drift persists after restart: escalate — possible venue-side data issue or database corruption.

---

## P3 — Credentials Expired / Rotated

**Trigger:** `circuit_breaker_open` with auth errors, or `ws_kalshi_seq_gap` with `consecutive_auth_failures >= 3`.

### Response
1. Generate new Kalshi API key in the Kalshi dashboard.
2. Update `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PEM` in the secrets manager (or `.env.prod`).
3. Restart the server.
4. Verify `ws_feed_disconnected` clears within 60s of restart.
5. Follow `docs/plans/CREDENTIAL_ROTATION_CHECKLIST.md` for the full rotation procedure.
