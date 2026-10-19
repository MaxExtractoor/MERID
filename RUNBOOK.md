# MERID Kalshi 15m — Operations Runbook

> **Audience**: On-call operator / trader
> **Scope**: Kill-switch policy, halt conditions, daily checklist for the canonical 15m stack (`web.main_15m_lean:app`, port 8011, profile `kalshi_crypto_15m_v2`)
> **Authoritative contract**: [`AGENTS.md`](AGENTS.md) — startup state machine, entry authorization, halt/recovery rules.

---

## 1. Runtime Modes & Live State Machine

| Mode | Description | Key guard |
|------|-------------|-----------|
| non-live (paper/sim) | Bare `uvicorn web.main_15m_lean:app` — no live latches set | Missing `TRADING_ENABLED`/`MERID_PM_TRADING_MODE=live` etc. demotes to non-live |
| observe-only | Full live-data stack, zero order submission | `MERID_OBSERVE_ONLY=1` (always wins) |
| live | Real-money orders on Kalshi prod | `.\start_15m.ps1` latches + `auto_execution_mode:1` + passing preflight |

Live entry state machine (per `AGENTS.md`):

```text
STARTING → PREFLIGHT_RUNNING → LIVE_ENTRIES_ENABLED     (all checks pass)
         → LIVE_ENTRIES_HALTED                          (any check fails — fail closed)
LIVE_ENTRIES_ENABLED → LIVE_ENTRIES_HALTED → RECOVERY_RUNNING → LIVE_ENTRIES_ENABLED
```

In `LIVE_ENTRIES_HALTED`: no new entries; cancels, reduce-only exits, and flatten stay active.

**Never set live-trading latches on a machine used for development or backtesting.**

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
3. Reset via the **Grid** view's kill-switch control (requires confirmation), or:
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

Run **before** each production restart / session:

- [ ] Verify `MERID_KALSHI_ENV=prod` and `KALSHI_USE_DEMO=false` are resolved by the launcher (it sets them).
- [ ] Confirm `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` match the intended live account.
- [ ] Check kill switch is clear and committed `data/kill_switch.json` has `active != true`.
- [ ] Watch startup: `STARTING → PREFLIGHT_RUNNING → LIVE_ENTRIES_ENABLED`; if `LIVE_ENTRIES_HALTED`, read the structured denial reason — do not unset protections to force it green.
- [ ] Confirm Kalshi WebSocket healthy and trusted fill watermark advancing (Monitor view / self-check).
- [ ] Confirm trading-shard (shard 2) collateral: `MERID_AUTO_FUND_TRADING_SHARD=1` relocates idle cash; otherwise ensure shard 2 holds ≥ one centi-contract + fee.
- [ ] Review category/exposure caps and `MERID_FIXED_EXPOSURE_CAP_USD` for the session budget.
- [ ] Confirm reconciliation is clean before expecting entries (per-ticker, signed YES centi-contracts).

---

## 6. Daily Post-Close Checklist

Run **after** the trading session ends or before switching to `mock` mode:

- [ ] Confirm open orders are zero or intentionally resting (Portfolio view → orders).
- [ ] Record session P&L in the incident log.
- [ ] Review any kill-switch / circuit-breaker events emitted today.
- [ ] Check `CategoryExposureTracker` daily totals against caps — document if any were hit.
- [ ] Confirm all fills were promoted from provisional to authoritative (no stuck provisional fills; see `apply_fill_once` contract in `AGENTS.md`).
- [ ] Rotate API keys if any were exposed (check git log for accidental `.env` commits).

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
| Unexpected live position | Manually close via Trade view → open orders → cancel all; verify signed YES exposure |
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
