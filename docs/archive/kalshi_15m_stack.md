# Kalshi 15m Stack Audit

**Purpose:** Single authoritative source of truth for the 15-minute Kalshi crypto stack. Defines what is canonical, what is legacy, and how to prevent legacy code from affecting 15m operations.

**Last Updated:** 2026-06-05  
**Profile:** `kalshi_crypto_15m_v2`

---

## 1. Canonical 15m Modules (Category A)

These are the only modules allowed to define behavior for 15m live trading. Everything else is either shared infra or legacy.

### 1.1 Entrypoint

| Module | Role | Notes |
|--------|------|-------|
| `start_15m.ps1` | Production entrypoint script | Only valid entry for production 15m stack. Sets `MERID_PROFILE=kalshi_crypto_15m_v2` and launches uvicorn. |
| `web/main_15m_lean.py` | FastAPI web server | Health-triggered startup, multi-threaded architecture (startup thread + trading thread). Explicit legacy module guard at P1.2.1. |

### 1.2 Prediction / Agents

| Module | Role | Notes |
|--------|------|-------|
| `merid/prediction/agent_grid_15m.py` | 15m agent grid | Builds 5 crypto agents (BTC, ETH, SOL, XRP, DOGE). Uses unified spot + WS bridge. |
| `merid/prediction/spot_provider.py` | Spot provider wrapper | Wraps UnifiedSpotService for agent grid consumption. |

### 1.3 Venue / Kalshi Integration

| Module | Role | Notes |
|--------|------|-------|
| `merid/event_venues/kalshi/ws_bridge.py` | WebSocket → state bridge | Single writer for orderbooks. Per-ticker queue + batch worker to eliminate lock contention. |
| `merid/event_venues/kalshi/ws.py` | WebSocket client | Low-level WebSocket connection with keepalive (ping_interval=30s). |
| `merid/event_venues/kalshi/market_state.py` | Per-ticker book state | `KalshiMarketStateStore` with per-ticker queues, batch worker, SUSPECT/GOOD tracking. |
| `merid/event_venues/kalshi/market_catalog.py` | Market catalog | `KalshiMarketCatalog` with auto-refresh. Singleton pattern with `set_market_catalog()`. |
| `merid/event_venues/kalshi/client.py` | Kalshi REST client | `KalshiVenueClient` for REST API calls. |
| `merid/event_venues/kalshi/invariants.py` | Kalshi invariants | Environment-aware base URL selection. |
| `merid/event_venues/kalshi/bankroll_service_v2.py` | Bankroll service V2 | Async bankroll fetching with `get_equity_for_risk_calc_sync()` for risk calculations. |
| `merid/event_venues/kalshi/kalshi_risk.py` | Kalshi risk config | `KalshiRiskConfig` for 15m-specific risk parameters. |
| `merid/event_venues/kalshi/models.py` | Kalshi dataclasses | `KalshiMarketState`, `KalshiMarket`, `KalshiOrder`, etc. |
| `merid/event_venues/kalshi/fills_ledger.py` | Fills ledger | Tracks fills for reconciliation. |
| `merid/event_venues/kalshi/fills_poller.py` | Fills poller | Polls Kalshi REST for fills. |
| `merid/event_venues/kalshi/candle_poller.py` | Candle poller | Fetches 1-minute OHLCV bars for indicator stacks. |

### 1.4 Data / Spot

| Module | Role | Notes |
|--------|------|-------|
| `data/unified_spot_service.py` | Unified spot service | Centralized spot price service for BTC, ETH, SOL, XRP, DOGE. Watched by watchdog thread. |
| `merid/prediction/spot_provider.py` | Spot provider wrapper | Adapter layer for agent grid consumption. |

### 1.5 Loop

| Module | Role | Notes |
|--------|------|-------|
| `merid/loop_15m.py` | 15m trading loop | `Kalshi15mLoop` with signal generation, cycle management. |

### 1.6 API Routers

| Module | Role | Notes |
|--------|------|-------|
| `web/api/performance_api.py` | Performance metrics | API endpoint for performance data. |
| `web/api/kalshi_api.py` | Kalshi API | Generic Kalshi API endpoints. |
| `web/api/kalshi_agent_grid_api.py` | Agent grid API | Agent grid-specific endpoints. |
| `web/api/health_api.py` | Health API | `/api/v1/health` endpoint for startup trigger. |
| `web/api/loop_api.py` | Loop API | Loop status and control endpoints. |
| `web/api/spot_debug_api.py` | Spot debug API | Spot service debugging endpoints. |
| `web/api/paper_session_api.py` | Paper session API | Paper trading session endpoints. |
| `web/api/system_endpoints.py` | System endpoints | System-level endpoints. |
| `web/api/agents.py` | Agents API | Agent status endpoints. |
| `web/api/auth.py` | Auth API | Authentication endpoints. |

### 1.7 Validation / Guards

| Module | Role | Notes |
|--------|------|-------|
| `merid/startup_validations.py` | Startup validations | Validates unified edge, spot provider, spot proxy availability. |
| `merid/legacy_module_guard.py` | Legacy module guard | `get_legacy_module_report()`, `assert_no_legacy_modules()`. |
| `merid/kalshi_15m_runtime_check.py` | Runtime invariants check | `check_15m_production_invariants()`. |
| `merid/meta_cognition/` | Meta-cognition | Startup→loop alignment checks. |
| `merid/monitoring/integrity_monitor.py` | Integrity monitoring | System integrity checks. |

### 1.8 Utils

| Module | Role | Notes |
|--------|------|-------|
| `utils/logger.py` | Logging | Shared logger utility. |
| `web/startup_state.py` | Startup state | Health-triggered startup state tracking. |

### 1.9 Config

| Module | Role | Notes |
|--------|------|-------|
| `merid/settings.py` | Settings | Shared settings module (see Section 3 for 15m-specific settings). |
| `config/profiles/kalshi_crypto_15m.yaml` | 15m profile | Canonical 15m profile configuration. |

---

## 2. Legacy / Off-Limits Modules (Category C)

These modules must NOT be imported or referenced from 15m code. If any are detected at runtime, the 15m stack should fail hard.

### 2.1 Legacy Entrypoints

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `main.py` | Old main entrypoint | Must not run in 15m process | Assert+kill if imported via `sys.modules` check |
| `web/main.py` | Legacy web entrypoint | Must not run in 15m process | Assert+kill if imported via `sys.modules` check |

### 2.2 Legacy Loops

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/loop.py` (142KB) | Legacy main loop | Not used by 15m (uses `loop_15m.py`) | Rename to `loop_legacy.py` to prevent accidental import |

### 2.3 Legacy Agent Grids

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/prediction/agent_grid.py` | Legacy agent grid | Might be imported by old tests | Rename to `agent_grid_legacy.py` or move to `legacy/` |
| `merid/prediction/agent_grid_legacy.py` | Legacy agent grid | Not used by 15m | Guard under `if False` or move to `legacy/` |

### 2.4 Legacy Venues

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| Old `ws_bridge` variants | Legacy WS bridges | Not used by 15m (uses `kalshi/ws_bridge.py`) | Move to `legacy/` or delete |
| Old `spot` services | Legacy spot providers | Not used by 15m (uses `unified_spot_service.py`) | Move to `legacy/` or delete |

### 2.5 Legacy Core

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/core/` | PM runtime, deployment controller, reflection system | Not used by 15m | Entire directory is legacy - prevent imports |

### 2.6 Legacy Risk

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/risk/` | Legacy risk modules | Not used by 15m (uses `kalshi_risk.py`) | Entire directory is legacy - prevent imports |

### 2.7 Legacy Execution

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/execution/` | Legacy execution engine | Not used by 15m | Entire directory is legacy - prevent imports |
| `merid/execution_guard.py` (45KB) | Legacy execution guard | Not used by 15m | Move to `legacy/` or delete |

### 2.8 Legacy Social

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/social/` | Social broadcasters | Not used by 15m | Entire directory is legacy - prevent imports |

### 2.9 Legacy LLM

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/llm/` | LLM modules | Not used by 15m | Entire directory is legacy - prevent imports |

### 2.10 Legacy Blockchain

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/blockchain/` | Blockchain modules | Not used by 15m | Entire directory is legacy - prevent imports |

### 2.11 Legacy PM

| Module | Legacy Influence | Current Impact | Plan |
|--------|-----------------|----------------|------|
| `merid/pm_runtime.py` | PM runtime | Not used by 15m | Move to `legacy/` or delete |
| `merid/pm_live_readiness.py` | PM live readiness | Not used by 15m | Move to `legacy/` or delete |
| `merid/pm_crypto_ops.py` | PM crypto operations | Not used by 15m | Move to `legacy/` or delete |

---

## 3. Config Inventory

### 3.1 Profile Files

| File | Required for 15m? | Status | Notes |
|------|-------------------|--------|-------|
| `config/profiles/kalshi_crypto_15m.yaml` | **YES** | Canonical | Only valid profile for 15m live trading |
| Other Kalshi profiles | NO | Legacy/Sandbox | Must not be used by 15m |
| Daily/event profiles | NO | Legacy | Must not be used by 15m |

### 3.2 Environment Variables

| Variable | Required for 15m? | Default | Notes |
|----------|-------------------|---------|-------|
| `MERID_PROFILE` | **YES** | `kalshi_crypto_15m_v2` | Must be exactly this value for 15m |
| `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST` | NO | `false` | Test-only - must be `false` in production |
| `MERID_KALSHI_FORCE_REST_FALLBACK` | NO | `false` | Optional: force REST polling for MD (Windows debugging) |
| `MERID_KALSHI_REST_REFRESH_THRESHOLD_S` | NO | `10` | WS refresh age threshold (seconds) |
| `MERID_KALSHI_WS_REFRESH_INTERVAL_S` | NO | `5` | WS refresh check interval (seconds) |
| `MERID_UNIFIED_EDGE_ENABLED` | NO | `false` | Unified edge feature flag |
| `MERID_CALIBRATION_VERSION` | NO | `placeholder` | Calibration version (required if unified edge enabled) |
| `MERID_UNIFIED_EDGE_SHADOW_MODE` | NO | `false` | Unified edge shadow mode |
| `MERID_MODE` | NO | `auto` | Mode resolver (demo/live) |
| `MERID_ENV` | NO | `demo` or `live` | Environment (demo/live) |
| `KALSHI_ENV` | NO | `demo` or `live` | Kalshi environment (demo/live) |
| `KALSHI_LIVE_API_KEY_ID` | YES (if live) | N/A | Live API key ID |
| `KALSHI_LIVE_PRIVATE_KEY_PATH` | YES (if live) | N/A | Live private key path |
| `KALSHI_DEMO_API_KEY_ID` | YES (if demo) | N/A | Demo API key ID |
| `KALSHI_DEMO_PRIVATE_KEY_PATH` | YES (if demo) | N/A | Demo private key path |

### 3.3 Settings Modules

| Module | Required for 15m? | Status | Notes |
|--------|-------------------|--------|-------|
| `merid/settings.py` | **YES** | Mixed | Contains both 15m and legacy settings - see Section 3.4 |
| Other `*_settings.py` | NO | Legacy | Must not be used by 15m |
| `config.py` | NO | Legacy | Must not be used by 15m |

### 3.4 15m-Only Config Surface

**Profile:** `kalshi_crypto_15m_v2` (only valid profile for 15m)

**Environment Variables Consumed by 15m:**
- `MERID_PROFILE` (must be `kalshi_crypto_15m_v2`)
- `MERID_MODE` (mode resolver)
- `MERID_ENV` (environment)
- `KALSHI_ENV` (Kalshi environment)
- Kalshi API credentials (live or demo)
- Optional: `MERID_KALSHI_FORCE_REST_FALLBACK`, `MERID_KALSHI_REST_REFRESH_THRESHOLD_S`, `MERID_KALSHI_WS_REFRESH_INTERVAL_S`
- Optional: `MERID_UNIFIED_EDGE_ENABLED`, `MERID_CALIBRATION_VERSION`, `MERID_UNIFIED_EDGE_SHADOW_MODE`

**Hardcoded 15m Constants:**
- Max WS age: 30s (ping_interval)
- Max spot age: 20-30s (reasonable), 60-120s (hard fail)
- Min edge: configured in profile
- Max per-ticker queue: 1000 deltas
- Batch interval: 10ms

**15m Must Ignore:**
- Daily/event profiles
- Legacy flags (e.g., PM runtime flags)
- Old default values that should never override 15m behavior

---

## 4. Guardrails

### 4.1 Profile Assertions

**Location:** `web/main_15m_lean.py` (P1.1), `Crypto15mProfileAdapter`

**Implementation:**
```python
profile = os.getenv("MERID_PROFILE", "")
if profile != "kalshi_crypto_15m_v2":
    logger.error(f"[PROFILE-ERROR] 15m stack must use kalshi_crypto_15m_v2, got {profile}")
    raise RuntimeError(f"Invalid profile: {profile}. Expected: kalshi_crypto_15m_v2")
```

**Status:** ✅ Implemented in `main_15m_lean.py` P1.1

### 4.2 Import Kill-Switches

**Location:** `web/main_15m_lean.py` (top of file, after imports)

**Implementation:**
```python
import sys
FORBIDDEN_MODULES = [
    'merid.main',
    'merid.loop',
    'merid.prediction.agent_grid',
    'web.main',
    'merid.core',
]
for mod in FORBIDDEN_MODULES:
    if mod in sys.modules:
        logger.error(f"[LEGACY-IMPORT-DETECTED] module={mod}; 15m stack can't run with legacy imports loaded")
        raise RuntimeError(f"[LEGACY-IMPORT-DETECTED] module={mod}; 15m stack can't run with legacy imports loaded")
```

**Status:** ✅ Implemented in `main_15m_lean.py` (lines 85-99)

**CI Validation:** ✅ Automated check in `scripts/validate_15m_stack.py`

### 4.3 Mode Flags in Mixed Modules

**Location:** Category D modules (e.g., `merid/settings.py`, `merid/startup_validations.py`)

**Implementation:**
```python
# Set early in 15m startup
os.environ['MERID_RUNTIME_MODE'] = '15m_live'

# Check in critical paths
if os.getenv('MERID_RUNTIME_MODE') != '15m_live':
    raise RuntimeError("Invalid runtime mode for 15m stack")
```

**Status:** ✅ Implemented in `main_15m_lean.py` (lines 101-104)

**CI Validation:** ✅ Automated check in `scripts/validate_15m_stack.py`

---

## 5. Audit Tables

### 5.1 "Used by 15m" Table

| Module | Role in 15m | Category | Notes |
|--------|-------------|----------|-------|
| `start_15m.ps1` | Production entrypoint script | A | Only valid entry for production 15m stack |
| `web/main_15m_lean.py` | HTTP API + lifecycle | A | Health-triggered startup, multi-threaded architecture |
| `merid/prediction/agent_grid_15m.py` | 15m agent grid | A | Builds 5 crypto agents (BTC, ETH, SOL, XRP, DOGE) |
| `merid/prediction/spot_provider.py` | Spot provider wrapper | A | Wraps UnifiedSpotService for agent grid |
| `merid/event_venues/kalshi/ws_bridge.py` | WS → state bridge | A | Per-ticker queues + batch worker |
| `merid/event_venues/kalshi/ws.py` | WebSocket client | A | Low-level WS with keepalive (ping_interval=30s) |
| `merid/event_venues/kalshi/market_state.py` | Per-ticker book state | A | SUSPECT/GOOD tracking, per-ticker queues |
| `merid/event_venues/kalshi/market_catalog.py` | Market catalog | A | Auto-refresh, singleton pattern |
| `merid/event_venues/kalshi/client.py` | Kalshi REST client | A | REST API calls |
| `merid/event_venues/kalshi/invariants.py` | Kalshi invariants | A | Environment-aware base URL selection |
| `merid/event_venues/kalshi/bankroll_service_v2.py` | Bankroll service V2 | A | Async bankroll fetching |
| `merid/event_venues/kalshi/kalshi_risk.py` | Kalshi risk config | A | 15m-specific risk parameters |
| `merid/event_venues/kalshi/models.py` | Kalshi dataclasses | A | KalshiMarketState, KalshiMarket, etc. |
| `merid/event_venues/kalshi/fills_ledger.py` | Fills ledger | A | Tracks fills for reconciliation |
| `merid/event_venues/kalshi/fills_poller.py` | Fills poller | A | Polls Kalshi REST for fills |
| `merid/event_venues/kalshi/candle_poller.py` | Candle poller | A | 1-minute OHLCV bars for indicators |
| `data/unified_spot_service.py` | Unified spot service | A | Spot feed for BTC/ETH/SOL/XRP/DOGE |
| `merid/loop_15m.py` | 15m trading loop | A | Kalshi15mLoop with signal generation |
| `merid/settings.py` | Settings | B | Shared settings (see Section 3.4) |
| `utils/logger.py` | Logging | B | Shared logger utility |
| `web/startup_state.py` | Startup state | B | Health-triggered startup state |
| `merid/startup_validations.py` | Startup validations | A | Validates unified edge, spot provider |
| `merid/legacy_module_guard.py` | Legacy module guard | A | Prevents legacy module imports |
| `merid/kalshi_15m_runtime_check.py` | Runtime invariants check | A | Production invariants validation |
| `merid/meta_cognition/` | Meta-cognition | A | Startup→loop alignment checks |
| `merid/monitoring/integrity_monitor.py` | Integrity monitoring | A | System integrity checks |
| `config/profiles/kalshi_crypto_15m.yaml` | 15m profile | A | Canonical 15m profile |

### 5.2 "Still Missing" TODO Table

| Area | Missing piece | Short-term | Long-term |
|------|---------------|------------|-----------|
| Testing | WS reconnect tests | Manual log-driven checks | Automated async tests |
| Testing | Spot watchdog failure/recovery tests | Manual kill/restart scenario | Unit/integration tests |
| Testing | Per-ticker batching and SUSPECT→GOOD transition tests | Manual log verification | Integration tests |
| Monitoring | Signal health metrics | Log scraping | Metrics + dashboards |
| Monitoring | WS health metrics | Log scraping | Metrics + dashboards |
| Monitoring | Spot health metrics | Log scraping | Metrics + dashboards |
| Config | 15m-only settings surface | Doc in repo (this file) | Separate `settings_15m.py` module |
| Config | Profile validation at import time | Runtime assertion | Import-time guard |
| Guardrails | Import kill-switches | Document in this file | Implement in `main_15m_lean.py` |
| Guardrails | Mode flags in mixed modules | Document in this file | Implement in Category D modules |
| Documentation | 15m runbook | Existing `15m_runbook.md` | Update with latest changes |
| Documentation | Troubleshooting guide | Existing docs | Consolidate into single guide |

### 5.3 "Legacy Influence Points" Table

| Module | Legacy influence | Current impact | Plan |
|--------|-----------------|----------------|------|
| `merid/main.py` | Old entrypoint | Must not run in 15m process | Assert+kill if imported via `sys.modules` check |
| `web/main.py` | Legacy web entrypoint | Must not run in 15m process | Assert+kill if imported via `sys.modules` check |
| `merid/loop.py` (142KB) | Legacy main loop | Not used by 15m (uses `loop_15m.py`) | Rename to `loop_legacy.py` |
| `merid/prediction/agent_grid.py` | Legacy agent grid | Might be imported by old tests | Rename to `agent_grid_legacy.py` |
| `merid/settings.py` (84KB) | Mixed global settings for all | Risk of wrong defaults for 15m | Split into `settings_15m.py` vs legacy |
| `merid/startup_validations.py` (170KB) | May contain legacy validation paths | Used by 15m, but may have legacy paths | Split into `startup_validations_15m.py` |
| `merid/guards/global_risk_guard.py` | Used by 15m, but may have legacy paths | Used by 15m for equity provider | Add mode flag to separate 15m vs legacy |
| `merid/core/` | PM runtime, deployment controller | Not used by 15m | Entire directory is legacy - prevent imports |
| `merid/risk/` | Legacy risk modules | Not used by 15m (uses `kalshi_risk.py`) | Entire directory is legacy - prevent imports |
| `merid/execution/` | Legacy execution engine | Not used by 15m | Entire directory is legacy - prevent imports |
| `merid/execution_guard.py` (45KB) | Legacy execution guard | Not used by 15m | Move to `legacy/` or delete |
| `merid/social/` | Social broadcasters | Not used by 15m | Entire directory is legacy - prevent imports |
| `merid/llm/` | LLM modules | Not used by 15m | Entire directory is legacy - prevent imports |
| `merid/blockchain/` | Blockchain modules | Not used by 15m | Entire directory is legacy - prevent imports |
| `merid/pm_runtime.py` | PM runtime | Not used by 15m | Move to `legacy/` or delete |
| `merid/pm_live_readiness.py` | PM live readiness | Not used by 15m | Move to `legacy/` or delete |
| `merid/pm_crypto_ops.py` | PM crypto operations | Not used by 15m | Move to `legacy/` or delete |

---

## 6. Next Steps

### Immediate (This Session)

1. ✅ Create `docs/kalshi_15m_stack.md` (this file)
2. ✅ Add import kill-switches to `main_15m_lean.py`
3. ✅ Add runtime mode flag (`MERID_RUNTIME_MODE=15m_live`)
4. ✅ Create automated CI validation script (`scripts/validate_15m_stack.py`)

### Short-Term (Next Few Sessions)

1. Rename legacy modules with `_legacy` suffix:
   - `merid/loop.py` → `merid/loop_legacy.py`
   - `merid/prediction/agent_grid.py` → `merid/prediction/agent_grid_legacy.py`
2. Split settings module:
   - Extract 15m-specific settings to `merid/settings_15m.py`
   - Current `merid/settings.py` is 1558 lines with mixed 15m/legacy settings
   - 15m-relevant: MERID_PROFILE, TRADING_ENABLED, Kalshi API, CFB RTI, risk caps
   - Legacy: Neo4j, Supabase, email/Telegram, market data APIs, AI/ML APIs, blockchain, Polymarket, crypto exchanges
3. Split startup validations:
   - Extract 15m-specific validations to `merid/startup_validations_15m.py`
   - Current `merid/startup_validations.py` is 170KB with mixed 15m/legacy validations

### Long-Term (Future Sessions)

1. Move legacy modules to `legacy/` directory
2. Add integration tests for critical paths
3. Implement Prometheus/Grafana metrics
4. Consolidate documentation into single runbook

---

## 7. How to Use This Document

### Before Making Changes

1. Check if the module you're modifying is in **Category A** (canonical 15m)
2. If it's in **Category C** (legacy), do not modify it for 15m purposes
3. If it's in **Category D** (ambiguous), add a mode flag to separate 15m vs legacy paths

### Before Adding New Code

1. Determine if the new code belongs in **Category A** (15m canonical)
2. If yes, add it to Section 1.1-1.9
3. If no, consider whether it should be in **Category B** (shared core) or **Category C** (legacy)

### Before Debugging Issues

1. Check Section 5.3 (Legacy Influence Points) to see if legacy code could be affecting the 15m stack
2. Check Section 4 (Guardrails) to see if the appropriate guards are in place
3. Check Section 3 (Config) to ensure 15m is using the correct config surface

---

**End of Kalshi 15m Stack Audit**
