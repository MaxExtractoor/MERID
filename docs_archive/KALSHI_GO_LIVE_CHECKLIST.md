# Kalshi Go-Live Checklist

Pre-flight gate for flipping real money on. Every item must be ✅ before enabling `PROFILE=kalshi-only` in production.

---

## 1. Backend Infrastructure

### 1.1 Connectivity
- [ ] `KALSHI_API_KEY` and `KALSHI_PRIVATE_KEY` env vars set (not demo keys)
- [ ] Kalshi REST health check returns `healthy`: `GET /api/v1/kalshi/health`
- [ ] Kalshi WebSocket bridge connected: `ws_connected: true` in `/api/v1/ui/mode-indicator`
- [ ] Rate-limit config loaded: `GET /api/v1/ratelimit/status` shows token buckets active
- [ ] stunnel TLS tunnel running (if using FIX): `ss -tlnp | grep 98228`

### 1.2 Execution Pipeline
- [ ] `ExecutionPipeline` initializes without errors in logs
- [ ] `KalshiPositionLimits` cache populated: check log line "Refreshed Kalshi position limits for N markets"
- [ ] Category config loaded: `GET /api/v1/kalshi/categories` returns expected modes
- [ ] Risk limits configured: `max_position_per_market`, `max_daily_loss`, `max_total_notional` match intended values
- [ ] Rate limiters active: `read_rate_limit` and `write_rate_limit` set per Kalshi tier

### 1.3 Execution Gate
- [ ] `GET /api/v1/system/execution-gate` returns `blocked: false, gate_state: "clear"`
- [ ] Kill switch deactivated: `kill_switch_active: false`
- [ ] No critical block reasons in gate response
- [ ] Reconciliation check passes (no venue/internal position discrepancy)
- [ ] Price feed staleness check passes: `GET /api/v1/system/price-feed-staleness`

### 1.4 Profile Isolation
- [ ] `PROFILE=kalshi-only` env var set
- [ ] Crypto feeds NOT started (no `CoinbasePriceFeed` or `BinanceFeed` log lines)
- [ ] Miner/research/rewards orchestrators NOT started
- [ ] Only `kalshi_api_router`, `system_control_router`, `paper_trading_router`, and core monitoring routers registered

---

## 2. Frontend Application

### 2.1 Build & Config
- [ ] `npx vite build` succeeds with zero errors
- [ ] `VITE_KALSHI_ONLY=true` set in `.env.production` (or localStorage `merid-kalshi-only=true`)
- [ ] `VITE_API_BASE` points to correct backend URL
- [ ] No console errors on page load

### 2.2 View Smoke Tests
Run each view and confirm it renders without JS errors and shows real data:

| View | Route | Check |
|------|-------|-------|
| Overview | `overview` | ExecutionGateStrip shows CLEAR, system health cards render |
| Markets | `kalshi-dashboard` | Market list loads, search works, trade ticket opens |
| Agent Grid | `kalshi-grid` | Agent matrix renders, price updates flow |
| Portfolio | `kalshi-portfolio` | Positions/orders/fills tabs load with real data |
| Orders | `orders` | Open orders display, status badges correct |
| Vol & Sizing | `kalshi-vol-dashboard` | Volume charts render, sizing metrics load |
| Kill Switch | `kill-switch` | Gate status matches backend, category toggles work |
| Exposure | `exposure` | PnL chart renders, exposure breakdown matches backend |
| Risk & Health | `risk` | Risk alerts, system health, position limits display |
| Observability | `observability` | SLO metrics and alert rules render |
| Agent Health | `agent-health` | Agent heartbeats visible, leaderboard populates |
| Orchestrator | `operator` | All 5 tabs render without errors |
| Logs | `logs` | Log stream displays |
| Settings | `settings` | Settings page renders |

### 2.3 Kalshi-Only Mode
- [ ] Sidebar hides "Lab / Legacy" section when `kalshiOnly=true`
- [ ] CommandPalette hides legacy commands (paper-trading, positions, agents)
- [ ] No legacy view is reachable via URL manipulation
- [ ] ExecutionGateStrip visible on Overview, Markets, Portfolio, Orders

---

## 3. Operator Workflow Tests

### 3.1 Kill Switch Flow
1. [ ] Navigate to Kill Switch view
2. [ ] Toggle a category from `live` → `read-only` → `blocked` → `live`
3. [ ] Confirm backend `GET /api/v1/kalshi/categories` reflects each change
4. [ ] Submit a test order in a `blocked` category — confirm rejection with `category_blocked` reason
5. [ ] Restore category to `live` — confirm order succeeds

### 3.2 Order Lifecycle
1. [ ] Place a limit order via trade ticket on a low-liquidity market
2. [ ] Confirm order appears in Orders view with `open` status
3. [ ] Cancel order via `DELETE /api/v1/kalshi/orders/{id}`
4. [ ] Confirm order status updates to `cancelled`

### 3.3 Near-Limit Warnings
1. [ ] Reduce `max_daily_loss` temporarily to trigger >75% utilization
2. [ ] Confirm ExecutionGateStrip shows amber "Loss: XX%" warning
3. [ ] Restore normal limits

### 3.4 Execution Gate Trip
1. [ ] Activate kill switch: `POST /api/v1/kalshi/kill-switch?activate=true`
2. [ ] Confirm ExecutionGateStrip turns red "BLOCKED" across all live trading views
3. [ ] Attempt order — confirm rejection
4. [ ] Deactivate kill switch — confirm gate returns to CLEAR

---

## 4. Agent Swarm

### 4.1 Agent Startup
- [ ] Only Kalshi-critical agents started (check `GET /api/v1/kalshi-grid/agents`)
- [ ] Non-Kalshi agents (crypto, research) NOT running
- [ ] Agent heartbeats visible in Agent Health view
- [ ] At least one agent moves from `idle` → `processing`

### 4.2 Dry Run
- [ ] Run one full swarm cycle on Kalshi demo/paper environment
- [ ] Confirm `msgs` and `decisions` counters increment in Agent Health view
- [ ] Confirm no unhandled exceptions in backend logs
- [ ] Confirm PnL tracking matches expected paper results

---

## 5. Monitoring & Alerting

- [ ] Observability view shows all 8 alert rules loaded
- [ ] `CircuitBreakerOpenAlert` fires when WS bridge disconnects (test by stopping bridge)
- [ ] `RiskKillSwitchAlert` fires when kill switch activated
- [ ] `WSFeedDisconnectedAlert` fires on WS disconnection
- [ ] Slack webhook configured and test alert received (if applicable)
- [ ] Log rotation / export configured for production volume

---

## 6. Kalshi-Only Mode Guardrails

**This is the gate for live Kalshi trading. All tests must pass.**

### 6.1 Frozen View Set
- [ ] Run: `pytest tests/test_kalshi_only_views.py::TestKalshiOnlyManifest::test_kalshi_only_view_ids_are_exact -v`
- [ ] **MUST PASS**: Exactly 8 views with `kalshi_only=True`
- [ ] No extra views added without approval

### 6.2 No Direct Kalshi API Calls
- [ ] Run: `pytest tests/test_kalshi_only_views.py::TestNoDirectKalshiAPICalls::test_no_direct_kalshi_http_calls_in_codebase -v`
- [ ] **MUST PASS**: No `api.elections.kalshi.com` outside `event_venues/kalshi/`

### 6.3 Venue Filtering
- [ ] Run: `pytest tests/test_kalshi_only_views.py::TestKalshiOnlyEndpoints -v`
- [ ] **MUST PASS**: `kalshi_only=True` restricts to Kalshi venue only

### 6.4 Smoke Test
- [ ] Run: `KALSHI_ONLY=true python scripts/smoke_test_kalshi_only.py`
- [ ] **MUST PASS**: All 8 views accessible, no venue leaks
- [ ] Sidebar shows only 8 Kalshi views (no Betting/Flow/Crypto)

### 6.5 Settings Verification
- [ ] `KALSHI_ONLY=true` in `.env`
- [ ] Backend logs show: "KALSHI_ONLY mode: ENABLED"
- [ ] Non-Kalshi views return 404 or hidden in UI

---

## 7. Final Sign-Off

- [ ] All sections above checked by operator
- [ ] **All Kalshi-only tests GREEN** (Section 6)
- [ ] Demo session completed with at least 5 round-trip orders
- [ ] No unexpected errors in last 30 minutes of backend logs
- [ ] Rate limit headroom confirmed: current usage < 50% of tier limit
- [ ] Backup/recovery procedure documented and tested

**Date**: _______________  
**Operator**: _______________  
**Environment**: ☐ Demo  ☐ Production  
**Decision**: ☐ GO  ☐ NO-GO  
**Notes**: _______________

---

## Related Documentation

- `KALSHI_ONLY_MODE.md` — Kalshi-only mode specification
- `.windsurf/prompts/KALSHI_ONLY_AGENT_RULES.md` — Agent guardrails
- `tests/test_kalshi_only_views.py` — CI-enforced tests
- `scripts/smoke_test_kalshi_only.py` — Operational smoke test
