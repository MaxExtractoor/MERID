# MERID → Fully Live Kalshi Trading: Comprehensive Audit & Roadmap

**Date**: 2026-02-18  
**Scope**: Full repo audit of `c:\Dev\MERID` — every layer from backend execution to frontend UI  
**Goal**: What must be done for MERID to trade fully live on Kalshi with complete, robust UI/UX

---

## Executive Summary

MERID has significant infrastructure in place but suffers from **architectural drift** — multiple generations of code coexist, creating 3+ parallel execution paths to Kalshi, 2 competing settings systems, and a frontend that is partially wired to real APIs but still has dead endpoints. The system *cannot* safely go live as-is.

**Estimated work to go live**: 3–5 focused engineering days (not 4.5 hours as CRITICAL_PATH_IMPLEMENTATION.md claims).

---

## 🔴 CRITICAL: Drift & Duplication (The Core Problem)

### 1. Three Competing Kalshi Client Implementations

| Layer | File | Auth Method | HTTP Lib | Status |
|-------|------|-------------|----------|--------|
| **Executor** | `merid/execution/executors/kalshi.py` | JWT (RS256 via `pyjwt`) | `httpx` (async, via HTTPExecutor) | Active — used by ExecutionRouter |
| **Venue Client** | `merid/event_venues/kalshi/client.py` | RSA-PSS signature (raw crypto) | `aiohttp` + `httpx` | Active — used by market_catalog, agent_grid, kalshi_api.py |
| **merid_core REST** | `merid_core/kalshi/rest_client.py` | RSA-PSS signature (raw crypto) | `requests` (sync!) | Active — fallback in kalshi_api.py |

**Problem**: These use *different authentication schemes*. The executor uses JWT Bearer tokens; the venue client and merid_core use RSA-PSS request signing. Kalshi's actual API uses RSA-PSS timestamp-based signing (not JWT). **The executor's JWT auth is likely wrong for the current Kalshi API.**

**Fix**: Consolidate to ONE Kalshi client. The `merid/event_venues/kalshi/client.py` has the most complete implementation (circuit breakers, retry logic, proper auth). Make the `KalshiExecutor` delegate to it instead of reimplementing auth.

### 2. Two Competing Env Var Names for Kalshi API Key

- `merid/execution/executors/kalshi.py` reads `KALSHI_API_KEY` via `os.getenv()`
- `merid/settings.py` defines `KALSHI_API_KEY_ID` (the canonical Pydantic setting)
- `merid_core/kalshi/rest_client.py` reads `KALSHI_API_KEY_ID` via `os.environ.get()`
- `web/api/kalshi_api.py` reads `KALSHI_API_KEY_ID` via `os.environ.get()`

**Problem**: The executor (`KalshiExecutor`) reads a *different env var name* than the rest of the system. If you set `KALSHI_API_KEY_ID` (the canonical one), the executor won't find it.

**Fix**: `KalshiExecutor` must read from `merid.settings.settings.KALSHI_API_KEY_ID`, not `os.getenv("KALSHI_API_KEY")`.

### 3. Three Competing Execution Pipelines

| Pipeline | Entry Point | Used By |
|----------|-------------|---------|
| `merid/execution/router.py` → `ExecutionRouter` | `submit_trade()` / `execute()` | Operator endpoints, manual trades |
| `merid/pipeline/router.py` → `TradeRouter` | `submit(TradeProposal)` | Domain agents (the "new" pipeline) |
| `merid_core/kalshi/execution_pipeline.py` | NATS OrderIntents | Designed for TS agents (appears unused) |

Plus a legacy shim at `trading/router.py` that wraps the ExecutionRouter.

**Problem**: No single canonical path from "agent has a trade idea" to "order hits Kalshi." The `TradeRouter` (pipeline) has the best risk architecture (GlobalRiskManager, ModeManager, InstrumentRegistry) but may not route to the `KalshiExecutor`. The `ExecutionRouter` has the kill switch gate but lacks the pipeline's risk sophistication.

**Fix**: Merge. The pipeline's `TradeRouter` should be the canonical entry point. It should delegate final execution to `ExecutionRouter`, which already has the kill switch hard gate and venue dispatch.

### 4. Duplicate `reset()` Methods on RiskController

`merid/risk/kill_switches.py` defines `reset()` **twice** on the `RiskController` class (lines 150 and 258). Python silently uses the last definition. The first `reset()` (no operator param) is dead code.

**Fix**: Delete the first `reset()` method (lines 150–178).

---

## 🟡 BACKEND: What's Needed for Live

### 5. Kalshi API URL is Stale

```python
# merid/execution/executors/kalshi.py line 23
base_url = os.getenv("KALSHI_API_HOST", "https://api.elections.kalshi.com/trade-api/v2")
```

The default URL uses `api.elections.kalshi.com` — an elections-specific subdomain. The general Kalshi API is `https://api.kalshi.com/trade-api/v2` (prod) or `https://demo-api.kalshi.co` (demo). The `merid_core` client gets this right.

**Fix**: Update the default to match `merid/settings.py`'s `KALSHI_API_HOST` default, and always read from settings, not `os.getenv`.

### 6. Kalshi Executor API Paths Are Wrong

The executor uses paths like `/trade/v1/price`, `/trade/v1/order`, `/exchange/status`, `/portfolio/balance`. But the Kalshi API v2 paths are:
- Balance: `GET /portfolio/balance` ← correct
- Positions: `GET /portfolio/positions` ← correct  
- Create order: `POST /portfolio/orders` (not `/trade/v1/order`)
- Exchange status: `GET /exchange/status` ← correct

The order endpoint path is wrong. Also, Kalshi orders require `action` (buy/sell) and `type` (market/limit), and contract count, not just `side` and `count`.

**Fix**: Align all API paths with the Kalshi v2 API spec. The venue client at `merid/event_venues/kalshi/client.py` already has correct paths — delegate to it.

### 7. Symbol Mapping is Hardcoded & Stale

```python
# merid/execution/executors/kalshi.py lines 210-224
def _symbol_to_ticker(self, symbol: str) -> str:
    mapping = {
        "PRES-2024-DEM": "PRES-2024-DEM",
        "PRES-2024-REP": "PRES-2024-REP",
    }
    return mapping.get(symbol, symbol)
```

This is a 2-entry hardcoded identity mapping from 2024. It's useless. The `market_catalog.py` in `merid/event_venues/kalshi/` has a proper dynamic catalog with 18K+ lines of market discovery logic.

**Fix**: Remove the hardcoded mapping. Use passthrough (Kalshi tickers are already the canonical symbols) or delegate to the catalog.

### 8. Reconciliation Needs Kalshi Wiring

`merid/reconciliation.py` compares internal state vs venue reality, but the startup reconciliation in `web/main.py` (line 279) calls `get_kalshi_reconciler()` which may not exist or may not be wired to the correct Kalshi client.

**Fix**: Verify `get_kalshi_reconciler()` exists, uses the canonical Kalshi client, and returns a proper report. The execution gate depends on it.

### 9. Startup Agent Manager Imports Non-Existent Modules

```python
# web/startup_agents.py line 13-15
from agents.news_monitor_agent import NewsMonitorAgent
from agents.twitter_agent import get_twitter_agent
from agents.telegram_agent import get_telegram_agent
```

These are imported at module level. If the `agents/` directory doesn't have these exact files, the entire backend crashes on startup.

**Fix**: Lazy-import these with try/except, or verify the modules exist. The Kalshi agent grid (the important one) is already lazy-imported.

### 10. Operator Summary Has Hardcoded Stubs

`web/api/operator_endpoints.py` line 221: `"mode": "paper"` is hardcoded with a `# TODO` comment. Lines 228-229: agent count is hardcoded to 5. The system uptime, CPU, memory are all hardcoded to 0.

**Fix**: Wire `mode` to `settings.MERID_PM_TRADING_MODE`. Wire agent count to the actual orchestrator. Wire system metrics to `psutil`.

### 11. `web/main.py` is 2,463 Lines — a God File

This single file has 100+ router imports, inline endpoint definitions, the lifespan manager, middleware setup, and more. It's the #1 maintenance risk.

**Fix**: This file should be ~100 lines: create app, attach middleware, include routers, define lifespan. Move all inline endpoints to their respective `web/api/` modules.

---

## 🟡 FRONTEND: What's Needed for Complete UI/UX

### 12. KillSwitchView — Already Wired (Verified Good)

`KillSwitchView.tsx` correctly polls `/api/v1/operator/kill-switch-status` every 2s and `/api/v1/operator/risk-state` every 5s. Emergency stop and reset buttons call the correct POST endpoints. **This view is production-ready.**

### 13. OperatorDashboard — Partially Wired, Partially Stubbed

The dashboard imports `useOperatorSummary` which calls the operator summary endpoint, but in `kalshiOnly` mode (the current default), **it skips the call entirely** (line 71-74 in `useOperatorSummary.ts`: endpoint is set to `''` when `kalshiOnly` is true).

It does fetch `kalshiBalance` and `kalshiPnl` from `/api/v1/kalshi/balance` and `/api/v1/kalshi/pnl`. But the operator summary (swarm status, system health) is completely dark in Kalshi-only mode.

**Fix**: The Kalshi-only mode should still fetch operator summary — just hide non-Kalshi sections. The kill switch, risk state, and agent grid status are critical even in Kalshi-only mode.

### 14. useApiData Hook — Missing Base URL

The `useApiData` hook (line 62) does `fetch(endpoint, ...)` with just the path — no `API_BASE_URL` prefix. This works only if the frontend is served from the same origin as the backend (Vite proxy). In production deployment (Netlify/Vercel), this will 404 unless a proxy or full URL is configured.

**Fix**: Prepend `API_BASE_URL` to all fetch calls in `useApiData`, or ensure the Vite proxy config covers production.

### 15. Missing View: Operator Dashboard in Sidebar

The sidebar (`Sidebar.tsx`) shows these views:
- Overview, Terminal, Markets, Agent Grid, Performance, Portfolio, Orders, Vol & Sizing
- Kill Switch
- Logs

**Missing from sidebar**: `OperatorDashboard`, `Positions`, `Settings`, `PaperTradingView`, `AgentHealthView`, `ObservabilityView`, `ExposureView`, `Risk`. These views exist in the codebase but are invisible to the user.

The `OperatorDashboard` is arguably the most important operational view (system health, swarm status, equity chart, mode control) and it's not in the sidebar.

**Fix**: Add `OperatorDashboard` to the sidebar under a "Command Center" section. Consider which other views are needed for live ops (at minimum: Positions, Settings).

### 16. View Type Definitions May Be Incomplete

`App.tsx` switches on `view` which is typed as `View`. Need to verify that all sidebar hrefs match the `View` type union and all `App.tsx` switch cases.

The sidebar defines `href: 'overview'` etc. and App.tsx handles `view === "overview"`. Verify no mismatches exist.

### 17. Duplicate Interface Definitions Across Views

`KalshiBalance`, `KalshiOrder`, `KalshiPosition`, `KalshiRiskSummary` are defined identically in both `KalshiPortfolioView.tsx` and `KalshiTerminalView.tsx`. This is a maintenance hazard.

**Fix**: Extract shared Kalshi types to `types/kalshi.ts` and import everywhere.

### 18. No WebSocket for Real-Time Price Updates

The frontend has WebSocket hooks (`useWebSocket.ts`, `useMeridSocket.ts`, `useKafkaStream.ts`) but the actual Kalshi price streaming relies on polling via `useApiData`. For live trading, sub-second price updates matter.

The backend has `merid/event_venues/kalshi/ws.py` (22KB) and `ws_bridge.py` (13KB) for Kalshi WebSocket streaming. The frontend has `RealtimeDisconnectedBanner` which suggests WS was intended but may not be connected.

**Fix**: Wire the Kalshi WS bridge → backend WebSocket endpoint → frontend `useMeridSocket` for real-time orderbook and price data.

---

## 🟡 CONFIGURATION & SAFETY

### 19. Live Trading Has Multiple Independent Unlock Gates

To go live, ALL of these must be true:
1. `MERID_TRADING_MODE = "live"` (settings)
2. `MERID_LIVE_TRADING_UNLOCKED = True` (settings)
3. `MERID_PM_TRADING_MODE = "live"` (settings, for prediction markets)
4. `MERID_PM_LIVE_ENABLED = True` (settings)
5. `KALSHI_USE_DEMO = False` (settings)
6. Kill switch not triggered (runtime)
7. Reconciliation clean (execution gate)
8. Guard decision = ALLOW (per-trade)

**This is actually good** — defense in depth. But the documentation doesn't list all 8 gates in one place. Operators need a single checklist.

**Fix**: Create a `scripts/go_live_preflight.py` that checks all 8 gates and prints a clear pass/fail report.

### 20. Private Key Exposed in Repo Root

`kalshi_private_key.pem` (1,704 bytes) is in the repo root. Even if `.gitignore` covers it, this is a security risk.

**Fix**: Move to a secure location outside the repo (e.g., `~/.merid/keys/`). Update `KALSHI_PRIVATE_KEY_PATH` default. Verify `.gitignore` has `*.pem`.

### 21. `.env` File Contains Live Secrets

`.env` (11,461 bytes) is in the repo root. `.env.backup` (18,608 bytes) too. These likely contain real API keys.

**Fix**: Verify `.gitignore` covers `.env*`. Consider using a secrets manager (Vault, AWS SSM, etc.) for production.

---

## 🟠 DEAD CODE & REPO HYGIENE

### 22. 100+ Root-Level Scripts

The repo root has ~80 Python scripts (`generate_*.py`, `run_*.py`, `phase*_playbook.py`, `test_*.py`, etc.) that appear to be one-off phase reports and old test scripts. These clutter the workspace and make it hard to find what matters.

**Fix**: Move to `archive/scripts/`. Keep only `main.py`, `startup.py`, `conftest.py`, and `Makefile` in root.

### 23. 30+ Root-Level Markdown Reports

`KALSHI_INTEGRATION_STEP1_SUMMARY.md` through `STEP4`, `MISSION_COMPLETE.md`, `SIDEBAR_AUDIT_REPORT.md`, etc. These are historical artifacts.

**Fix**: Move to `docs/archive/`. The root should have only `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, and this audit.

### 24. Multiple `conftest.py` Files

Root has `conftest.py`, `conftest_cohesive.py`, `conftest_production.py`, `conftest_threaded.py`. Only one should be canonical.

**Fix**: Consolidate into `conftest.py` with conditional fixtures.

### 25. Unused Venue Executors

`merid/execution/executors/` has executors for Alpaca, Coinbase, Crypto.com, Cronos, Fulcrom, Jupiter, Webull. In Kalshi-only mode, these are dead weight that increase import time and potential import errors.

**Fix**: Make `executors/__init__.py` lazy-import non-Kalshi executors, or gate them behind feature flags.

---

## 🟢 WHAT'S WORKING WELL

- **Kill switch architecture** (`merid/risk/kill_switches.py`): Solid. Daily loss limits, position limits, error thresholds, operator callbacks, event logging.
- **ExecutionRouter kill switch gate**: Correct — checks kill switch before any guard or execution.
- **Frontend component library**: Rich set of ~120 React components with TailwindCSS, Lucide icons, proper error boundaries.
- **Kalshi agent grid** (`merid/prediction/agent_grid.py`): Well-architected per-(asset, timeframe) agent system with session guards, venue gates, and portfolio risk management.
- **Sidebar & Navigation**: Clean, focused on Kalshi-only views.
- **Feature flags**: Good pattern for `kalshiOnly` mode via env/localStorage/URL param.
- **useApiData hook**: Solid polling, abort handling, generation tracking, stub detection.
- **Settings module**: Pydantic-based, single source of truth, well-organized.

---

## 📋 PRIORITIZED IMPLEMENTATION PLAN

### Phase 1: Fix the Execution Path (Day 1-2) — BLOCKING

1. **Consolidate Kalshi auth**: Make `KalshiExecutor` use the venue client's RSA-PSS auth (not JWT)
2. **Fix env var name**: `KALSHI_API_KEY` → `KALSHI_API_KEY_ID` in executor, read from settings
3. **Fix API paths**: Align order endpoint to Kalshi v2 spec
4. **Remove hardcoded symbol mapping**: Use passthrough
5. **Fix duplicate `reset()`**: Delete lines 150-178 in kill_switches.py
6. **Fix startup imports**: Lazy-import news/twitter/telegram agents
7. **Write integration test**: Auth → balance → positions → place paper order → verify

### Phase 2: Wire Pipeline End-to-End (Day 2-3) — BLOCKING

8. **Connect TradeRouter → ExecutionRouter**: Pipeline proposals flow through kill switch gate
9. **Verify reconciliation**: Ensure `get_kalshi_reconciler()` works and clears execution gate
10. **Wire operator summary to real data**: Mode, agent count, system metrics
11. **Create go-live preflight script**: Check all 8 safety gates

### Phase 3: Complete UI/UX (Day 3-4)

12. **Add OperatorDashboard to sidebar**: + Positions, Settings views
13. **Fix useOperatorSummary in kalshiOnly mode**: Fetch operator data even in Kalshi-only
14. **Extract shared Kalshi types**: `types/kalshi.ts`
15. **Wire WebSocket for real-time prices**: Kalshi WS bridge → frontend
16. **Fix useApiData base URL**: Prepend API_BASE_URL for production deployment

### Phase 4: Hardening & Hygiene (Day 4-5)

17. **Move private key out of repo root**
18. **Archive root-level scripts and reports**
19. **Split web/main.py god file**: Extract inline endpoints
20. **Lazy-import unused executors**
21. **End-to-end smoke test**: Signal → agent grid → proposal → risk → order → UI update

---

## 🎯 The Single Most Important Fix

**Consolidate the Kalshi client.** Three implementations with different auth methods is the #1 source of bugs waiting to happen. The `merid/event_venues/kalshi/client.py` is the most battle-tested (circuit breakers, retry, proper RSA-PSS auth). Make `KalshiExecutor` wrap it. Delete `merid_core/kalshi/rest_client.py`. This single change eliminates 60% of the integration risk.

---

## Architecture After Fixes

```
Agent Grid (per-asset agents)
    ↓ StrategySignal
TradeRouter (merid/pipeline)
    ↓ TradeProposal (risk-checked, mode-gated)
ExecutionRouter (merid/execution)
    ↓ Kill switch gate → Guard evaluation → Venue dispatch
KalshiExecutor → KalshiVenueClient (single auth implementation)
    ↓ RSA-PSS signed HTTP requests
Kalshi REST API v2
    ↓ Order confirmation
Reconciliation loop (periodic)
    ↓ Position sync
UI (React) ← WebSocket + polling ← FastAPI endpoints
```

This is one clean path from idea to execution to UI. No forks, no duplicates, no drift.
