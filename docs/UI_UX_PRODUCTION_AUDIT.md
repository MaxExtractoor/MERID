# MERID Kalshi-Only UI/UX & Production Code Audit

**Date:** 2026-03-19  
**Scope:** Strip non-Kalshi surfaces, remove dead crypto/generalist code paths, harden the Kalshi prediction-market UI + API.  
**Status:** ✅ ALL ACTIONS COMPLETED

---

## 1. Legacy Jinja Dashboards — ✅ KILLED

12 dead template routes removed from `web/main.py`. These referenced non-existent templates and were not part of the Kalshi prediction-market surface.

**Removed routes:** `/simulation`, `/live`, `/debug-v2`, `/dashboard/legacy`, `/trading/perps`, `/trading/markets`, `/betting`, `/institutional`, `/control`, `/legacy`, `/analytics/dashboard`, `/observability`

**Kept templates (React shell + production dashboards):** `api_dashboard.html`, `merid_spa.html`, `merid_trading_dashboard.html`, `prime_screen.html`, `production_dashboard.html`, `unified_fixed.html`, `unified_shell.html`

---

## 2. Kalshi API Routers — ✅ REGISTERED

### 2.1 Newly registered routers (4 files)

| File | Router | Frontend Constants Satisfied |
|------|--------|------------------------------|
| `crypto_lanes_api.py` | `/api/v1/lanes/*` | `KALSHI_CRYPTO_RTI`, `KALSHI_GRID_CRYPTO_EDGE`, `LANE_TOGGLE` |
| `crypto_status.py` | `/api/v1/crypto/*` | `CRYPTO_STATUS`, `CRYPTO_MARKETS` |
| `kalshi_execution_telemetry_api.py` | `/api/v1/kalshi-grid/performance/*` | `KALSHI_EXECUTION_TELEMETRY` |
| `replay_api.py` | `/api/v1/replay/*` | `REPLAY_COMPARE`, `REPLAY_QUICK_COMPARE` |

### 2.2 New shim endpoints (`web/api/kalshi_shims.py`)

Created to back frontend constants that had no backend route:

| Endpoint | Frontend Constant |
|----------|-------------------|
| `POST /api/v1/reconciliation/run` | `RECONCILIATION_RUN` |
| `GET /api/v1/reconciliation/status` | `RECONCILIATION_STATUS` |
| `POST /api/v1/risk/downsize-all` | `RISK_DOWNSIZE_ALL` |
| `DELETE /api/v1/risk/kill-switch` | `RISK_KILL_SWITCH_DELETE` |
| `POST /api/v1/system/pause-agents` | `SYSTEM_PAUSE_AGENTS` |
| `POST /api/v1/errors/report` | `ERRORS_REPORT` |
| `GET /api/v1/kalshi/lane/status` | `LANE_STATUS` |
| `POST /api/v1/lanes/{lane_id}/toggle` | `LANE_TOGGLE` |
| `GET /api/v1/venues` | `VENUES` |
| `GET /api/v1/notifications/status` | `NOTIFICATION_STATUS` |
| `GET /api/v1/notifications/recent-alerts` | `NOTIFICATION_RECENT_ALERTS` |

### 2.3 Archived non-Kalshi API files → `archive/legacy_api/` (34 files)

Phase0/experimental, social clients, governance stubs, legacy Kalshi variants, and redundant implementations:

`agent_modes_api.py`, `debate_api.py`, `debate_backtest_api.py`, `debate_integration_api.py`, `dev_chat.py`, `governance_cadence.py`, `governance_intents.py`, `health_api.py`, `kalshi_api_robust.py`, `kalshi_crypto_signals_api.py`, `kalshi_crypto_stub_api.py`, `kalshi_dashboard_api.py`, `kalshi_paper_portfolio_api.py`, `kalshi_rate_limit.py`, `kalshi_status.py`, `kalshi_venue_routes.py`, `kalshi_wiring_api.py`, `minimal_scope.py`, `notification_config.py`, `notification_formatters.py`, `notification_router.py`, `notification_worker.py`, `operator_api.py`, `phase0_adapters.py`, `phase0_experiment.py`, `phase0_trial_api.py`, `risk_metrics_api_state.py`, `slo_api.py`, `telegram_client.py`, `ui_audit.py`, `unified_pipeline_robust.py`, `ws_events.py`, `ws_kafka_bridge.py`, `x_client.py`

---

## 3. Entry Points — ✅ SINGLE SOURCE OF TRUTH

Archived to `archive/stale_entrypoints/` (5 files):

| File | Reason |
|------|--------|
| `main.py` (root) | Overrode `_app_lifespan`, started stale crypto services |
| `concrete_main.py` | POC adapter demo |
| `wire_concrete_main.py` | Generator for above |
| `concrete_kalshi_integration.py` | POC adapter classes |
| `web/minimal_main.py` | Stub with hardcoded empty responses |

**Canonical entry:** `uvicorn web.main:app` → uses `_app_lifespan` exclusively.

---

## 4. Publishers & Services — ✅ KALSHI-ONLY

Archived to `archive/legacy_services/` (7 files):

| File | Reason |
|------|--------|
| `commodities_publisher.py` | Non-Kalshi, never started |
| `forex_publisher.py` | Non-Kalshi, never started |
| `stocks_publisher.py` | Non-Kalshi, never started |
| `swarm_publishers.py` | Never started |
| `swarm_publishers_robust.py` | Never started |
| `prediction_publisher.py` | Not wired to Kalshi grid |
| `decision_explainer.py` | Not surfaced in Kalshi UI |

**Remaining publishers** (`price_publisher.py`, `portfolio_publisher.py`) only run if wired in `_app_lifespan` — currently disabled, which is correct for Kalshi-only mode.

---

## 5. Shutdown Completeness — ✅ FIXED

Added shutdown handlers for 4 services that were started but never stopped:

| Service | Handler Added |
|---------|--------------|
| `KalshiSentimentService` | `get_sentiment_service().stop()` |
| `KalshiMarketCatalog` | `get_market_catalog().stop()` |
| `HashtagMonitor` | `get_hashtag_monitor().stop()` |
| `NotificationManager` | `get_notification_manager().stop()` |

All handlers added to the external feed managers stop loop in `_app_lifespan` shutdown block.

---

## 6. Frontend Constants — ✅ RECONCILED

### Constants updated in `web/react/src/config/constants.ts`:

| Constant | Before | After |
|----------|--------|-------|
| `KALSHI_CRYPTO_RTI` | `/api/v1/kalshi-grid/crypto/rti` (dead) | `/api/v1/lanes/crypto/status` (backed by `crypto_lanes_api.py`) |
| `KALSHI_GRID_CRYPTO_EDGE` | `/api/v1/kalshi-grid/crypto/edge` (dead) | `/api/v1/lanes/crypto/summary` (backed by `crypto_lanes_api.py`) |
| `KALSHI_GRID_CRYPTO_PAPER_VS_SHADOW` | `/api/v1/kalshi-grid/crypto/paper-vs-shadow` (dead) | `/api/v1/lanes/crypto/summary` (stub — no dedicated backend yet) |
| `CRYPTO_MARKETS` | `/api/v1/markets/kalshi/crypto` (dead) | `/api/v1/crypto/markets` (backed by `crypto_status.py`) |

All other constants now resolve to registered routes via either the existing routers or the new `kalshi_shims.py`.

---

## 7. Remaining Debt (non-blocking)

| Item | Priority | Notes |
|------|----------|-------|
| `KalshiLiquidityMonitor` / `KalshiVolumeMonitor` / `KalshiOrderRouter` | Low | Exist in codebase but not wired into `_app_lifespan`; wire explicitly if needed |
| `KALSHI_GRID_CRYPTO_PAPER_VS_SHADOW` | Low | Currently stubs to lane summary; build real paper-vs-shadow comparison when needed |
| `kalshi_shims.py` routes | Medium | Thin shims with try/except fallbacks; replace with real implementations as features mature |
| `crypto_status_authoritative.py` | Low | Still in `web/api/` but not registered; wire if needed or archive |
| `orders_api.py` | Low | Still in `web/api/` but not registered; `OPERATOR_ORDERS` → `/api/v1/kalshi/orders` is backed by `kalshi_api.py` |

---

## Files Changed

### Modified
- `web/main.py` — Removed 12 dead routes, registered 5 new routers (crypto_lanes, crypto_status, kalshi_execution_telemetry, replay, kalshi_shims), added 4 shutdown handlers
- `web/api/crypto_status.py` — Added `/api/v1` prefix
- `web/react/src/config/constants.ts` — Updated 4 constants to point to real routes

### Created
- `web/api/kalshi_shims.py` — 11 shim endpoints for missing Kalshi-facing routes

### Archived (46 files total)
- `archive/legacy_api/` — 34 non-Kalshi API files
- `archive/stale_entrypoints/` — 5 entry point files
- `archive/legacy_services/` — 7 non-Kalshi publishers
