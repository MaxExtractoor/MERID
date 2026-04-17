# MERID Live-Readiness Checklist

> Use this before every live Kalshi trading session.  
> See [docs/KILL_SWITCH_INVENTORY.md](docs/KILL_SWITCH_INVENTORY.md) for the full kill-switch control table.

---

## 1. Pre-Start Environment Check

```bash
grep -E "MERID_PM_TRADING_MODE|MERID_PM_LIVE_ENABLED|MERID_ALLOW_LIVE_TRADES|KALSHI_CONFIRM_LIVE|KALSHI_USE_DEMO" .env
```

- [ ] `MERID_PM_TRADING_MODE=live`
- [ ] `MERID_PM_LIVE_ENABLED=true`
- [ ] `MERID_ALLOW_LIVE_TRADES=1`
- [ ] `KALSHI_CONFIRM_LIVE=1`
- [ ] `KALSHI_USE_DEMO=false`
- [ ] `KALSHI_PORTFOLIO_BANKROLL_CENTS` = your actual balance in cents
- [ ] `MERID_MAX_DAILY_LOSS_USD` = your session loss limit (recommend ≤ 5% of bankroll)

---

## 2. Kill Switch Clear

```bash
cat data/risk_kill_switch.json
```

- [ ] File shows `"state": "active"` (TRADING ALLOWED)
- [ ] If `"state": "triggered"`: investigate the `kill_reason` field, then clear via:
  ```bash
  curl -X POST "http://localhost:8000/api/v1/kalshi/kill-switch?activate=false" -H "Authorization: Bearer $TOKEN"
  ```

---

## 3. Startup Log Verification

After server start, check for:

- [ ] `✅ Kalshi grid validation: 30/30 cells OK`
- [ ] `VenueGate initialised: mode=live, live_enabled=True`
- [ ] `Execution gate CLEAR` (within first few cycles)
- [ ] No `STARTUP ABORTED` or `GRID VALIDATION FAILED` lines

---

## 4. Verify All 30 Grid Cells Active

Run offline (no server needed):
```bash
python -c "
from merid.event_venues.kalshi.grid_validator import validate_kalshi_grid
status = validate_kalshi_grid(strict=False)
dead = [k for k,s in status.items() if not s.ok]
print('Dead cells:', dead or 'NONE — all 30 OK')
"
```

Expected cell coverage (all must be present and OK):

| Asset | 15m | 1h | Daily | Weekly | Monthly | Annual |
|-------|-----|-----|-------|--------|---------|--------|
| BTC   | ✓   | ✓   | ✓     | ✓      | ✓       | ✓      |
| ETH   | ✓   | ✓   | ✓     | ✓      | ✓       | ✓      |
| SOL   | ✓   | ✓   | ✓     | ✓      | ✓       | ✓      |
| XRP   | ✓   | ✓   | ✓     | ✓      | ✓       | ✓      |
| DOGE  | ✓   | ✓   | ✓     | ✓      | ✓       | ✓      |

---

## 5. Execution Gate Status

```bash
curl -s http://localhost:8000/api/v1/kalshi/health/execution-gate | python -m json.tool
```

- [ ] `gate_state: "clear"`
- [ ] `blocked: false`
- [ ] `reasons: []`

If blocked, fix the source reported in `reasons` before trading. See [docs/KILL_SWITCH_INVENTORY.md §2](docs/KILL_SWITCH_INVENTORY.md) for fix procedures.

---

## 6. PM Spot Health

```bash
curl -s http://localhost:8000/api/v1/pm/spot-health | python -m json.tool
```

- [ ] BTC/USD — green, age < 120s
- [ ] ETH/USD — green, age < 120s
- [ ] SOL/USD — green, age < 120s
- [ ] XRP/USD — green, age < 120s
- [ ] DOGE/USD — green, age < 120s

If any shows `pm_max_age_exceeded`: restart the Coinbase feed poller.

---

## 7. Kill-Switch Smoke Test (paper mode, first run only)

```bash
# Activate
curl -X POST "http://localhost:8000/api/v1/kalshi/kill-switch?activate=true" -H "Authorization: Bearer $TOKEN"
# Verify gate blocked
curl -s http://localhost:8000/api/v1/kalshi/health/execution-gate | python -m json.tool | grep gate_state
# Expected: "gate_state": "blocked"

# Reset
curl -X POST "http://localhost:8000/api/v1/kalshi/kill-switch?activate=false" -H "Authorization: Bearer $TOKEN"
# Verify gate clear
curl -s http://localhost:8000/api/v1/kalshi/health/execution-gate | python -m json.tool | grep gate_state
# Expected: "gate_state": "clear"
```

---

## 8. Interpreting Live Logs

### PM_CYCLE_TRACE — per-market decision

```
[PM_CYCLE_TRACE] agent=BTC_15M cycle=42 lifecycle=entry market=KXBTC15M-...
    signal=YES size=50 edge=0.11 reason=...
```

- `lifecycle=entry` — order attempted (look for `order_submitted` or error)
- `lifecycle=no_action` — market seen but no trade (check `reason` field)
- `lifecycle=expiry_miss` — outside entry window (normal for old markets)

Common `no_action` reasons:
| reason | meaning | fix |
|--------|---------|-----|
| `pm_spot_gate` | spot missing/stale | fix PM spot feed for this asset |
| `volume` | below volume floor | lower `MERID_UNIVERSE_MIN_VOLUME` or accept |
| `edge_below_threshold` | not enough edge | normal — strategy working correctly |
| `consensus_flat` | swarm is neutral | check swarm health |
| `stale_snapshot` | market snapshot too old | check Kalshi WS connectivity |

### Kill switch activation

```
⛔ EXECUTION BLOCKED: Kill switch is engaged
```

The remediation hint in the log tells you exactly which API to call.

### Grid validation (startup)

```
GRID VALIDATION: all 30/30 cells OK — BTC/ETH/SOL/XRP/DOGE × 6 timeframes
```

If this line is absent or shows `< 30`: process aborted. Fix YAML and restart.

---

## 9. Emergency Procedures

### Hard stop all trading

```bash
curl -X POST "http://localhost:8000/api/v1/kalshi/kill-switch?activate=true" \
  -H "Authorization: Bearer $TOKEN"
# Confirm persisted:
cat data/risk_kill_switch.json | python -m json.tool | grep state
# Expected: "state": "triggered"
```

### Halt a single agent

```bash
curl -X POST "http://localhost:8000/api/v1/kalshi/deployment/halt" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "BTC_15M", "reason": "Manual halt"}'
```

### Resume after investigation

```bash
# 1. Clear kill switch
curl -X POST "http://localhost:8000/api/v1/kalshi/kill-switch?activate=false" -H "Authorization: Bearer $TOKEN"
# 2. Verify gate is CLEAR
curl -s http://localhost:8000/api/v1/kalshi/health/execution-gate | python -m json.tool | grep gate_state
# 3. Trading resumes automatically on next agent cycle
```

---

## 10. No-Trades Triage Guide

| Symptom | Check | Fix |
|---------|-------|-----|
| Gate BLOCKED, reason=kill_switch | `cat data/risk_kill_switch.json` | Investigate, then reset |
| Gate BLOCKED, reason=price_feed | PM spot health endpoint | Restart Coinbase poller |
| Gate BLOCKED, reason=reconciliation | Fills ledger status | Wait or trigger manual reconcile |
| Gate CLEAR but zero entry cycles | `MERID_PM_TRADING_MODE` + VenueGate log | Set to paper or live |
| `pm_spot_gate` in every PM_CYCLE_TRACE | PM spot health for that asset | Fix spot feed |
| `consensus_flat` for all cells | Swarm matrix panel | Restart swarm if stuck |
| Grid validation failed at startup | Startup logs | Fix `config/kalshi_agent_grid.yaml` |
| Agent shows HALTED in deployment | `GET /api/v1/kalshi/deployment/status` | Resume via API |
