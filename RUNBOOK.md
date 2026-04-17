# MERID Kalshi Swarm — Operations Runbook

> **Audience**: On-call operator / trader  
> **Scope**: Kill-switch policy, halt conditions, daily pre-open and post-close checklist

---

## 1. Trading Modes

| Mode | Description | Key guard |
|------|-------------|-----------|
| `mock` | Fully simulated, no real API calls | Always safe |
| `paper` | Simulated fills against real market data | `KALSHI_ENV=demo` required |
| `live` | Real-money orders on Kalshi | Double-lock: `KALSHI_ENV=live` + `VenueGate.live_enabled=True` |

**Never set `KALSHI_ENV=live` on a machine used for development or backtesting.**

---

## 2. Kill-Switch Policy

### 2.1 Manual emergency stop
```bash
# Via Python REPL or management script
from merid.risk.kill_switches import risk_controller
risk_controller.emergency_stop(reason="manual_operator_halt")
```
This sets the global kill switch and blocks all subsequent `can_trade()` checks.  
All in-flight agents will drain their current cycle and then stop accepting new orders.

### 2.2 Automatic kill-switch triggers

| Trigger | Default threshold | Env var override |
|---------|------------------|-----------------|
| Daily loss | $500 | `MERID_KILL_DAILY_LOSS_USD` |
| Error burst | 10 errors / window | `MERID_KILL_ERROR_THRESHOLD` |
| Circuit breaker (venue) | 5 consecutive failures | `MERID_KILL_CIRCUIT_THRESHOLD` |
| Brier degradation | Swarm Brier > 0.35 | hardcoded in `check_brier_degradation()` |

### 2.3 Kill-switch reset procedure
1. Confirm the root cause (see `/api/v1/risk/kill-switch` for reason + timestamp).
2. Fix or acknowledge the underlying condition.
3. Reset via the KalshiGridView UI **Reset Kill Switch** button (requires confirmation dialog), or:
```bash
from merid.risk.kill_switches import risk_controller
risk_controller.reset()
```
4. Document the event in the incident log.

### 2.4 Never reset without investigation
- A kill switch that triggered automatically **must** have a documented root cause before reset.
- If the trigger was a daily loss limit, do **not** reset until the next UTC trading day.

---

## 3. Halt Conditions

Stop trading immediately and engage the kill switch if **any** of the following are observed:

- Cumulative daily loss exceeds the configured daily loss limit.
- Swarm Brier score degrades past threshold (automated, but verify manually).
- Venue WebSocket disconnects and does not reconnect within 60 seconds.
- Position reconciliation diff exceeds $50 between local state and Kalshi API.
- Any order is filled at a price more than 5¢ from the intended limit price.
- Unusual repeat rejection patterns (> 20 consecutive rejections in any 5-minute window).
- API rate-limit 429 responses sustained for more than 2 minutes.

---

## 4. Category and Correlation Caps

Default caps (override via env vars):

| Category | Cap (USD/day) | Env var |
|----------|--------------|---------|
| crypto | $2,000 | `MERID_CAT_CAP_CRYPTO_USD` |
| macro | $500 | `MERID_CAT_CAP_MACRO_USD` |
| politics | $200 | `MERID_CAT_CAP_POLITICS_USD` |
| equities | $500 | `MERID_CAT_CAP_EQUITIES_USD` |
| sports/weather/other | $200 each | `MERID_CAT_CAP_{X}_USD` |

Correlated-stack cap (same underlying, any timeframe): **$800/day** (`MERID_CORR_STACK_CAP_USD`).

To inspect live exposure:
```python
from merid.event_venues.kalshi.category_exposure import get_category_exposure_tracker
print(get_category_exposure_tracker().get_snapshot().to_dict())
```

---

## 5. Daily Pre-Open Checklist

Run **before** switching to `paper` or `live` mode each session:

- [ ] Verify `KALSHI_ENV` matches the intended mode (`demo`/`live`).
- [ ] Confirm correct key pair is loaded: `KALSHI_LIVE_API_KEY_ID` vs `KALSHI_DEMO_API_KEY_ID`.
- [ ] Check kill switch is clear: `risk_controller.can_trade()` returns `True`.
- [ ] Check yesterday's P&L did not hit the daily loss limit (auto-reset at UTC midnight).
- [ ] Review swarm Brier degradation: `/api/v1/kalshi/brier-scores` — `swarm_brier` < 0.35.
- [ ] Confirm venue WebSocket is connected: KalshiGridView health panel shows green.
- [ ] Confirm at least 2 agents passed the gauntlet (`/api/v1/kalshi/grid/status`).
- [ ] Review `CategoryExposureTracker` caps — ensure they are appropriate for session.
- [ ] Verify `MERID_PM_MAX_TOTAL_NOTIONAL` is set correctly for the session budget.
- [ ] Check TIF default is `gtc` (not `fill_or_kill`) — confirm `OrderIntent.time_in_force` default.

---

## 6. Daily Post-Close Checklist

Run **after** the trading session ends or before switching to `mock` mode:

- [ ] Switch all agents to `mock` or `paper` mode via KalshiGridView.
- [ ] Export fills: Portfolio View → Export Fills → save to `/data/fills/YYYY-MM-DD.csv`.
- [ ] Confirm open orders are zero (cancel stragglers via Batch Cancel).
- [ ] Record session P&L in the incident log.
- [ ] Review any kill-switch events emitted today (`risk_controller._events`).
- [ ] Check `CategoryExposureTracker` daily totals against caps — document if any were hit.
- [ ] Run Brier score update: resolved markets should flow into `pred_resolved` table.
- [ ] Rotate API keys if any were exposed (check git log for accidental `.env` commits).
- [ ] Verify backup of the SQLite consensus DB (`data/pred_consensus.db`).

---

## 7. Credential Rotation

1. Generate a new RSA key pair on the Kalshi dashboard.
2. Save the new private key to the appropriate file (`kalshi_live_private_key.pem` or `kalshi_demo_private_key.pem`).
3. Update `.env` with the new `KALSHI_LIVE_API_KEY_ID` / `KALSHI_DEMO_API_KEY_ID`.
4. Restart the MERID server process.
5. Confirm connectivity via `GET /api/v1/kalshi/balance`.
6. Revoke the old key on the Kalshi dashboard.

---

## 8. Escalation

| Condition | Action |
|-----------|--------|
| Cannot reset kill switch | Restart MERID process; all state reloads from DB |
| Venue API fully unreachable | Wait; do not restart repeatedly (circuit breaker handles backoff) |
| Unexpected live position | Manually close via Terminal View → open orders → cancel all |
| P&L discrepancy > $50 | Halt; reconcile manually via `/api/v1/reconciliation/unified-status` |
| Suspected key compromise | Rotate immediately (Section 7); engage emergency stop first |

---

## 8. Secrets Migration (B1)

**Current state:** API key ID stored in `.env` on disk; private key PEM at `kalshi_private_key.pem` (gitignored via `*.pem` rule — file is NOT tracked in git).

**Target state:** Injected secrets — no credential files on disk in production.

### Migration steps

1. **Railway / Render / Fly.io deployments:**
   - Add `KALSHI_LIVE_API_KEY_ID`, `KALSHI_LIVE_PRIVATE_KEY_PEM` (the PEM content, not a path) in the platform secrets panel.
   - Set `KALSHI_PRIVATE_KEY_PEM` env var to the raw PEM string. `KalshiConfig.__post_init__` reads `KALSHI_PRIVATE_KEY_PEM` before `KALSHI_PRIVATE_KEY_PATH`.
   - Remove `kalshi_private_key.pem` from the server filesystem after verifying the env-var path works.

2. **Doppler / AWS Secrets Manager / Vault:**
   - Store the PEM as a secret value, inject it as the `KALSHI_LIVE_PRIVATE_KEY_PEM` environment variable at runtime.
   - No file path needed — `KalshiConfig` will use the PEM string directly.

3. **Local dev:**
   - Keep `kalshi_private_key.pem` in the repo root (gitignored). Use `.env` with `KALSHI_ENV=demo`.
   - Never commit `.env` or any `.pem` file.

4. **Verify `.gitignore` coverage:**  `*.pem`, `*.key`, `.env`, `.env.*` are all present. Run `git status` before any commit to confirm no secrets are staged.
