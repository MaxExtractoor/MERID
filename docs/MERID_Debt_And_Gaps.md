# MERID Debt & Gaps Inventory

> Generated: 2026-03-07. Last updated: 2026-03-07 (Phase 5 — loop singleton + debate history).
> Severity: **BLOCKER** = prevents correct operation / hides real state from operator. **IMPORTANT** = degrades quality / correctness. **NICE-TO-HAVE** = cleanup / polish.
> Status legend: FIXED | OPEN | IN-PROGRESS

---

## 1. Wiring Gaps

### 1.1 Duplicate Router Mounts (BLOCKER) — FIXED 2026-03-07
**Files:** `web/main.py:425,451` and `web/main.py:441-442`
- `debate_data_router` is `include_router`'d **twice** — once at `/debates` prefix (line 425) and once bare (line 451). Routes conflict; 2nd mount silently wins. FastAPI does not error on duplicate mounts.
- `health_router` is mounted twice: once bare (line 441) and once at `/api/v1` (line 442). Two different handler registrations for the same router causes overlapping OpenAPI docs and unpredictable behavior.
- **Fix:** Remove the bare `health_router` mount; keep only `/api/v1` prefix. Remove the bare `debate_data_router` mount; keep only the `/debates` prefix.

### 1.2 Crypto Lanes Skip at Startup (IMPORTANT)
**File:** `web/main.py:295-308`
Crypto lanes init is silently skipped if `kalshi_client`, `price_feed`, `risk_bus`, or `portfolio` are `None` in `app.state`. These services are never assigned to `app.state` in the current lifespan code — so lanes **never initialize**. The warning is logged but no operator alert surfaces to the UI.
- **Fix:** Assign the initialized client/feed/portfolio to `app.state` before attempting lane init, or expose a `/api/v1/crypto/lanes/status` endpoint that returns `503 unavailable` so the UI shows a real status.

### 1.3 Kalshi Crypto Signals — Stub Fallback (IMPORTANT)
**File:** `web/main.py:146-150`
If `web/api/kalshi_crypto_signals_api.py` fails to import, a stub router is silently substituted. The import error is logged at INFO level (not WARNING/ERROR). Operators have no dashboard indication that crypto signals are running from a stub.
- **Fix:** Log at WARNING; expose a flag on the stub endpoints (`"stub": true, "reason": "module_unavailable"`) so `GlobalStubBanner` can surface it.

### 1.4 MeridLoop — `reconcile_all_venues` Import Path (IMPORTANT)
**File:** `web/main.py:248-255`
`from merid.reconciliation import reconcile_all_venues` — this module path needs to be confirmed to exist and not be a ghost import. If it fails (caught silently), reconciliation never runs.
- **Fix:** Verify `merid/reconciliation/__init__.py` exports `reconcile_all_venues`. Add an explicit startup health check entry.

### 1.5 Kalshi Balance — Mock Fallback on Auth Failure (BLOCKER) — FIXED 2026-03-07
**File:** `web/api/kalshi_api.py:1128-1129`
On Kalshi 401 auth failure, the balance endpoint silently returns `{"usd": 10000.0, "mock": True}`. The frontend `KalshiBalance` type does not include a `mock` field, so the `mock: True` flag is silently dropped. The operator sees $10,000 balance when the real balance is unknown.
- **Fix:** Return HTTP 503 with `{"error": "kalshi_auth_failed", "message": "Could not authenticate with Kalshi", "mock": true}` instead of a fake dollar amount. Update frontend to handle 503 on balance endpoint.

### 1.6 Kalshi WS Auth — Partially FIXED 2026-03-07
All 5 frontend-consumed WS endpoints are now authenticated via `ws_validate_token()` (`?token=` query param). Frontend hooks (`useMeridSocket`, `useKalshiRiskStream`) append the session token automatically.
- `/ws/trades`, `/ws/orders`, `/ws/risk` — `ws_trade_events.py` ✅
- `/ws/dashboard-prices`, `/ws/risk` — `dashboard_ws.py` ✅
- `streams.py` `/ws/trades` and `/ws/risk` are shadowed (authenticated routes registered first).

All 4 paper trading WS endpoints (`ws_paper.py`) also authenticated 2026-03-07.

~16 remaining WS endpoints (latency, market data, agent sim streams) are unauthenticated but not consumed by frontend. Lower-priority follow-up: `ws_dedicated_streams.py`, `streams.py` non-shadowed paths.

### 1.7 Missing `get_loop_instance()` Export (IMPORTANT) — FIXED 2026-03-07
**File:** `web/main.py:555` references `from merid.loop import get_loop_instance`. This function may not exist in `merid/loop.py` (the code reads `MeridLoop()` directly in the lifespan). If missing, the `/health` loop status silently shows `"error"`.
- **Fix:** Added `get_loop_instance()` + `set_loop_instance()` module-level singleton to `merid/loop.py`; `set_loop_instance(loop)` called in lifespan immediately after `MeridLoop()` construction.

---

## 2. Stub / Mock Data in Production

### 2.1 Balance Mock (BLOCKER)
**File:** `web/api/kalshi_api.py:1128`
See §1.5 above.

### 2.2 Debate Performance Stats — Hardcoded Zeros (IMPORTANT)
**File:** `web/api/risk_metrics_api.py:51-66`
`trades_by_debate_state`, `performance_by_state`, `total_adjustments`, `avg_multiplier`, `total_size_reduction` are all hardcoded zeros with comments "not yet implemented". The risk metrics panel shows zeros even when real trades exist.
- **Fix:** Wire to the `PredictionConsensusStore` and `DebateOrchestrator` to pull real aggregated stats, or mark explicitly as stub and surface in `GlobalStubBanner`.

### 2.3 Flow API — All Stub (IMPORTANT)
**File:** `web/api/flow_api.py`
Radar, entities, and events all return `"source": "stub"`. Frontend never checks this flag so the operator sees fake data silently.
- **Fix:** Add `stub: true` to all flow responses and wire `GlobalStubBanner` to check that field.

### 2.4 Betting Consensus — Stub (NICE-TO-HAVE)
**File:** `web/api/betting_consensus_api.py`
Returns `_stub: True` data. Frontend never reads `_stub`. If no view depends on this, delete the router mount entirely.

### 2.5 `kalshi_agent_performance_api.py:222` — `trades_today = 0` (IMPORTANT) — FIXED 2026-03-07
**File:** `web/api/kalshi_agent_performance_api.py`
`trades_today = 0  # TODO` hardcoded. Agent performance view shows 0 trades today for every agent regardless of reality.
- **Fix:** Now computed from `tracker._closed_trades` filtered by today's UTC midnight timestamp.

### 2.6 `debate_data_api.py` — Synthetic Historical Data (IMPORTANT) — FIXED 2026-03-07
**File:** `web/api/debate_data_api.py`
Historical time-series `/historical-contribution` returned synthetic trending data. Charts showed invented trends.
- **Fix:** Now attempts `attribution_engine.get_agent_history()` first; returns empty points list (honest "No data") if method absent or returns nothing. Alerts and rollups endpoints already use real quota/attribution data.

### 2.7 Mock Files Still Mounted (NICE-TO-HAVE)
Files: `web/api/mock_prediction_markets.py`, `web/api/mock_agent_cohorts.py`, `web/api/mock_arena.py`, `web/api/mock_arbitrage.py`, `web/api/mock_simulation.py`, `web/api/mock_system_admin.py`, `web/api/mock_trading.py`
All are mock modules. If they are still mounted in the router they pollute the OpenAPI schema with fake endpoints. None appear in `web/main.py` router list — verify, then delete files if truly orphaned.

---

## 3. UI/UX Gaps

### 3.1 Execution Gate Strip — Disappears on API Failure (BLOCKER)
**File:** `web/react/src/components/ExecutionGateStrip.tsx:69`
`if (!gate) return null` — the safety strip disappears when `/api/v1/system/execution-gate` fails or returns empty. Operator loses visibility of execution gate state exactly when something is wrong.
- **Fix:** Replace `return null` with a degraded state: `<div className="bg-yellow-900 ...">GATE STATUS UNKNOWN — API UNREACHABLE</div>`.

### 3.2 Risk Protections Panel — Blank on API Failure (BLOCKER)
**File:** `web/react/src/components/RiskProtectionsPanel.tsx:79`
`if (!data) return null` — panel disappears silently. Same pattern.
- **Fix:** Show explicit "Risk data unavailable — check backend" state.

### 3.3 Mode Safety Panel — Blank on API Failure (BLOCKER)
**File:** `web/react/src/components/ModeSafetyPanel.tsx:93`
Same `if (!data) return null` pattern.

### 3.4 Kill Switch Field Name Inconsistency (BLOCKER)
The kill switch active state is referenced by different field names across components:
- `global_kill` (in some components)
- `active`
- `can_trade`
- `kill_switch_active`
- `blocked`
This means some components show kill switch as OFF when it is ON and vice versa depending on which field name is truthy.
- **Fix:** Agree on one canonical field name; update all API response shapes and component reads to match. Recommend: `kill_switch_active: boolean`.

### 3.5 WS Parse Errors Silently Dropped (IMPORTANT)
**File:** `web/react/src/hooks/useKalshiRiskStream.ts:188`
`catch {}` — all WebSocket JSON parse errors are swallowed. No operator indication that the risk stream is producing malformed data.
- **Fix:** Log to console.error + optionally update a `parseErrorCount` state that the UI can surface.

### 3.6 Mock Balance Renders as Real (BLOCKER)
**File:** `web/react/src/types/kalshi.ts`
`KalshiBalance` type is missing `mock?: boolean`. The mock $10k balance from the backend (§2.1) renders identically to a real balance. Operator cannot tell if the displayed balance is real.
- **Fix:** Add `mock?: boolean` to `KalshiBalance`. In balance display components, show a yellow "MOCK" badge if `mock === true`.

### 3.7 Settings Not Loaded from Backend on Mount (IMPORTANT)
**File:** `web/react/src/views/Settings.tsx`
Settings are loaded from `localStorage` on mount, not from `/api/v1/user/settings`. So a second browser session sees stale/default settings.
- **Fix:** Add a `useEffect` on mount to `GET /api/v1/user/settings` and merge into local state.

### 3.8 Kalshi Credentials in localStorage (IMPORTANT — security debt)
Kalshi API credentials stored in plaintext `localStorage`. Any JS on the page (XSS) can read them.
- **Fix:** Move credential storage to `httpOnly` cookie or prompt-only-at-session-start flow; never persist to localStorage.

### 3.9 `debate_data_router` Mounted at Both `/debates` and Root (BLOCKER)
Causes doubled routes in OpenAPI, potential response conflicts. See §1.1.

### 3.10 `PnLSummary` Interface Duplicated (NICE-TO-HAVE)
**Files:** `web/react/src/services/api.ts` and `web/react/src/hooks/useDashboard.tsx`
Same interface defined twice. One definition can silently diverge from the other.
- **Fix:** Export from `api.ts` only; import in `useDashboard.tsx`.

### 3.11 Dead Constants in `constants.ts` (NICE-TO-HAVE)
`ARB_STATUS`, `COMPLIANCE_STATUS`, `PROPOSAL_STATUS` reference removed modules (arbitrage, blockchain). Delete them to prevent confusion.

### 3.12 `WS_EVENTS` Constant Stale (IMPORTANT)
**File:** `web/react/src/config/constants.ts`
Defines 4 WS event types; `useMeridSocket` handles 12+. Frontend event handlers reference non-existent constants.
- **Fix:** Regenerate `WS_EVENTS` from the actual backend event names.

---

## 4. Dead Code / Removed Modules

| Path | Status | Action |
|------|--------|--------|
| `arbitrage/` | Deleted from disk (git shows D) | Remove any remaining import references; confirm no router still imports from it |
| `moat/` | Deleted from disk | Same |
| `trading/agents/execution_agent.py` | Deleted | Remove from `trading/agents/__init__.py` if still exported |
| `web3/blockchain_connector.py` | Deleted | Confirm no router imports it |
| `merid/blockchain/` | Deleted | Confirm no lifespan code references it |
| `archive/legacy_scripts/` | Deleted | Git marks all D; confirm `.gitignore` or clean from git history |
| `web/api/arbitrage.py` | Deleted | Remove any router mount |
| `web/api/blockchain_health_api.py` | Deleted | Remove any router mount |
| `web/api/cost_models.py` | Deleted | Remove any router mount |
| `web/api/moat.py` | Deleted | Remove any router mount |
| `ArbScannerPanel.tsx` | Orphan (arbitrage module deleted) | Delete if not rendered anywhere |
| `ArbitragePanel.tsx` | Orphan | Delete if not rendered anywhere |
| `trading/execution_engine.py` | Deleted | Remove references |

---

## 5. Config / Env / Deployment Issues

### 5.1 `PROJECT_ROOT` Hardcoded to Windows Path (BLOCKER for deployment) — FIXED 2026-03-07
**File:** `merid/settings.py:48`
```python
PROJECT_ROOT: str = Field(default="c:/Dev/MERID", ...)
```
Will break any Linux/Docker deployment. Any code that uses `settings.PROJECT_ROOT` will produce wrong paths.
- **Fix:** `default=str(Path(__file__).resolve().parent.parent)`.

### 5.2 CORS Wildcard in Production (IMPORTANT — security)
**File:** `web/main.py:376-382`
`allow_origins=["*"]` with `allow_credentials=True`. This combination is **invalid** in browsers (CORS spec) and allows any origin to make credentialed requests.
- **Fix:** Restrict to known origins (`MERID_ALLOWED_ORIGINS` env var). Default safe: `["http://localhost:3000", "http://localhost:5173"]`.

### 5.3 Dev Auth Bypass Auto-ON (IMPORTANT — security)
When `MERID_ENV=development`, the auth check in `web/api/auth.py` is bypassed automatically. This is a security risk if a dev server is accidentally exposed.
- **Fix:** Require explicit `MERID_DEV_ALLOW_AUTH_BYPASS=true` env var (currently `MERID_DEV_ALLOW_WS` exists but auth bypass is separate). Default: bypass OFF.

### 5.4 `MERID_TRADING_MODE` Defaults to `"live"` in Lifespan (BLOCKER) — FIXED 2026-03-07
**File:** `web/main.py:175`
```python
trading_mode = os.getenv("MERID_TRADING_MODE", "live").lower()
```
But `merid/settings.py:219` has `MERID_TRADING_MODE` defaulting to `"paper"`. The lifespan reads `os.getenv` directly (not `settings`), so if the env var is unset, the venue adapter is initialized in **live mode** while the settings say paper.
- **Fix:** Use `from merid.settings import settings; trading_mode = settings.MERID_TRADING_MODE`. Remove the redundant `os.getenv` call.

### 5.5 Betting Router Disabled but Still Commented In Code (NICE-TO-HAVE)
**File:** `web/main.py:71,468`
`# Legacy betting router disabled - was causing slow ticks`. The import and include are commented out. The file `web/api/betting_consensus_api.py` still exists. Clean this up.

### 5.6 `MERID_TOTAL_CAPITAL_USD` Default $50,000 but `MERID_MAX_ORDER_SIZE_USD` Default $100 (NICE-TO-HAVE)
Inconsistent defaults. If someone launches with all defaults, the risk limits and capital allocation don't coherently describe the same trading setup.

### 5.7 No `.env.example` (IMPORTANT)
No `.env.example` file exists in the repo. Operators must guess which env vars are needed.
- **Fix:** Generate from `merid/settings.py` field list. Mark which are required vs. optional.

---

## 6. Test Coverage Gaps

### 6.1 P0 Safety Paths Untested
- No test for `ExecutionGateStrip` disappearing on 503 response
- No test for kill switch inconsistent field names
- No test that `MERID_LIVE_TRADING_UNLOCKED=false` blocks a real order placement

### 6.2 WebSocket Auth — No Test
No test that unauthenticated WS connections are rejected.

### 6.3 Crypto Lanes — No Integration Test
No test for the crypto lane initialization path. The silent skip bug (§1.2) would have been caught by a test.

### 6.4 Balance Mock Fallback — No Test
No test verifying the balance endpoint returns an explicit error (not fake data) on Kalshi 401.

### 6.5 `debate_data_router` Double Mount — No Test
No route conflict detection test.

---

## Priority Order for Fixes

### Immediate (BLOCKER — operator safety)
1. **§1.5 / §2.1** — Balance mock: return 503, not fake $10k
2. **§3.1** — ExecutionGateStrip: show UNKNOWN state instead of disappearing
3. **§3.4** — Kill switch field name consistency
4. **§5.4** — `MERID_TRADING_MODE` default inconsistency (live vs. paper)
5. **§1.1** — Duplicate router mounts (debate_data, health)
6. **§3.6** — MockBalance renders as real in UI

### High Priority (IMPORTANT — correctness)
7. **§2.2** — Debate stats: wire real zeros vs. stub
8. **§2.5** — `trades_today = 0` TODO
9. **§1.2** — Crypto lanes silently skip
10. **§5.2** — CORS wildcard
11. **§5.3** — Dev auth bypass explicit opt-in
12. **§5.1** — PROJECT_ROOT hardcoded
13. **§1.6** — WS endpoint auth
14. **§3.5** — WS parse errors silently swallowed
15. **§3.7** — Settings not loaded from backend

### Cleanup (NICE-TO-HAVE)
16. **§4** — Dead code removal (orphaned files, dead imports)
17. **§3.11** — Dead constants
18. **§3.10** — PnLSummary duplication
19. **§5.5** — Betting router comment cleanup
20. **§5.7** — `.env.example` file
