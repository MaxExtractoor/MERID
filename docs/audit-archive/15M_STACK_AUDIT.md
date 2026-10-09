# 15m Stack Audit Report

**Generated:** 2026-06-05  
**Purpose:** Deep audit of the 15-minute Kalshi crypto stack to identify legacy code influence, missing components, and canonical modules.

---

## Executive Summary

The 15m stack (`kalshi_crypto_15m_v2` profile) has a clear entrypoint (`start_15m.ps1` → `web/main_15m_lean.py`) but shows evidence of legacy code paths that may be causing the current instability (WS keepalive timeouts, batch worker issues, spot age mismatches).

**Key Findings:**
- **Category A (15m Canonical):** Well-defined surface with explicit separation from legacy
- **Category C (Legacy):** Several legacy modules still present in the codebase that could be accidentally imported
- **Category D (Ambiguous):** Some modules contain both 15m and legacy logic (e.g., `merid.loop.py` vs `merid.loop_15m.py`)

---

## 1. Official 15m Stack Surface

### Entrypoint
- **Script:** `start_15m.ps1`
- **Command:** `.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2`
- **Profile:** `kalshi_crypto_15m_v2` (validated at startup P1.1)

### Web Application
- **File:** `web/main_15m_lean.py` (2267 lines)
- **Purpose:** FastAPI entrypoint with health-triggered startup
- **Key Features:**
  - Health-triggered startup (via `/api/v1/health`)
  - Multi-threaded architecture (startup thread + trading thread)
  - Explicit legacy module guard at P1.2.1
  - Profile validation (rejects non-15m profiles)

### Venue Core (Kalshi)
- **WS Bridge:** `merid/event_venues/kalshi/ws_bridge.py`
- **Market State:** `merid/event_venues/kalshi/market_state.py` (with per-ticker queues + batch worker)
- **Market Catalog:** `merid/event_venues/kalshi/market_catalog.py`
- **Client:** `merid/event_venues/kalshi/client.py`
- **Bankroll:** `merid/event_venues/kalshi/bankroll_service_v2.py`
- **Risk:** `merid/event_venues/kalshi/kalshi_risk.py`
- **Models:** `merid/event_venues/kalshi/models.py` (KalshiMarketState dataclass)
- **Fills:** `merid/event_venues/kalshi/fills_ledger.py`, `merid/event_venues/kalshi/fills_poller.py`
- **Candles:** `merid/event_venues/kalshi/candle_poller.py`

### Prediction/Agents
- **Agent Grid:** `merid/prediction/agent_grid_15m.py`
- **Spot Provider:** `merid/prediction/spot_provider.py`

### Data
- **Unified Spot Service:** `data/unified_spot_service.py`

### Loop
- **15m Loop:** `merid/loop_15m.py` (Kalshi15mLoop)

### Configuration
- **Profile:** `kalshi_crypto_15m_v2` (expected)
- **Settings:** `merid/settings.py`

---

## 2. Dependency Map from 15m Entrypoint

### Direct Imports in `main_15m_lean.py`

#### Standard Library
- `sys`, `pathlib`, `datetime`, `asyncio`, `os`, `time`, `threading`

#### Third-Party
- `dotenv` (python-dotenv)
- `fastapi` (FastAPI, CORSMiddleware, HTTPException)

#### Internal - Utils
- `utils.logger` → `get_logger`
- `web.startup_state` → `startup_state`

#### Internal - API Routers
- `web.api.performance_api` → `performance_router`
- `web.api.kalshi_api` → `kalshi_router`
- `web.api.kalshi_agent_grid_api` → `kalshi_agent_grid_router`
- `web.api.health_api` → `health_router`
- `web.api.loop_api` → `loop_router`
- `web.api.spot_debug_api` → `spot_router`
- `web.api.paper_session_api` → `paper_router`
- `web.api.system_endpoints` → `system_router`
- `web.api.agents` → `agents_router`
- `web.api.auth` → `auth_router`

#### Internal - Venue (Kalshi)
- `merid.event_venues.kalshi.market_state` → `get_kalshi_market_state_store`
- `merid.event_venues.kalshi.market_catalog` → `KalshiMarketCatalog`, `set_market_catalog`
- `merid.event_venues.kalshi.ws_bridge` → `get_ws_bridge`
- `merid.event_venues.kalshi.client` → `KalshiVenueClient`
- `merid.event_venues.kalshi.invariants` → `get_kalshi_base_url`
- `merid.event_venues.kalshi.bankroll_service_v2` → `get_bankroll_service`, `get_equity_for_risk_calc_sync`
- `merid.event_venues.kalshi.candle_poller` → `CandlePoller`, `get_candle_poller`, `init_candle_poller`
- `merid.event_venues.kalshi.fills_ledger` → `get_fills_ledger`
- `merid.event_venues.kalshi.fills_poller` → `get_fills_poller`
- `merid.event_venues.kalshi.kalshi_risk` → `KalshiRiskConfig`
- `merid.event_venues.kalshi` → `get_kalshi_client`

#### Internal - Prediction
- `merid.prediction.agent_grid_15m` → `build_15m_agent_grid`
- `merid.prediction.spot_provider` → `get_spot_provider`

#### Internal - Risk/Guards
- `merid.guards.global_risk_guard` → `set_equity_provider`

#### Internal - Loop
- `merid.loop_15m` → `Kalshi15mLoop`

#### Internal - Data
- `data.unified_spot_service` → `get_unified_spot_service`

#### Internal - Settings/Validation
- `merid.settings` → `settings`
- `merid.startup_validations` → `validate_unified_edge_configuration`, `validate_spot_provider_configuration`, `validate_spot_proxy_availability`
- `merid.legacy_module_guard` → `get_legacy_module_report`, `assert_no_legacy_modules`
- `merid.kalshi_15m_runtime_check` → `check_15m_production_invariants`

#### Internal - Meta-Cognition
- `merid.meta_cognition` → `run_meta_check`

#### Internal - Monitoring
- `merid.monitoring.integrity_monitor` → `start_integrity_monitoring`

---

## 3. Legacy Influence Points

### 3.1 Shared Singletons/Globals

**Potentially Problematic:**
- `merid.event_venues.kalshi.market_state` → `get_kalshi_market_state_store()` (singleton)
- `merid.event_venues.kalshi.market_catalog` → `get_market_catalog()`, `set_market_catalog()` (singleton)
- `merid.event_venues.kalshi.ws_bridge` → `get_ws_bridge()` (singleton)
- `merid.event_venues.kalshi.bankroll_service_v2` → `get_bankroll_service()` (singleton)
- `data.unified_spot_service` → `get_unified_spot_service()` (singleton)

**Risk:** If legacy code (e.g., `web/main.py`) also uses these singletons, state could leak between stacks.

### 3.2 Shared Config/Profile Logic

**Profile Validation:**
- `main_15m_lean.py` explicitly validates `MERID_PROFILE == "kalshi_crypto_15m_v2"` at P1.1
- This is good - prevents wrong profile from running

**Settings Module:**
- `merid/settings.py` is shared across all stacks
- Contains both 15m-specific and legacy settings
- **Risk:** Legacy defaults could override 15m settings if not explicitly set

### 3.3 Shared Utility Modules

**Potentially Ambiguous:**
- `merid.loop.py` (142,787 lines) - Legacy loop, NOT used by 15m
- `merid.loop_15m.py` (90,930 lines) - 15m-specific loop
- **Risk:** Accidental import of `merid.loop` instead of `merid.loop_15m`

### 3.4 Multiple Definitions

**WS Client Classes:**
- `merid.event_venues.kalshi.client.py` → `KalshiVenueClient` (15m uses this)
- Potential legacy WS clients in other venue modules

**Spot Services:**
- `data.unified_spot_service.py` → `UnifiedSpotService` (15m uses this)
- Potential legacy spot providers in `merid.prediction.spot_provider`

**Risk Modules:**
- `merid.event_venues.kalshi.kalshi_risk.py` → `KalshiRiskConfig` (15m uses this)
- Legacy risk modules in `merid/risk/`

---

## 4. Code Categorization

### Category A - 15m Canonical (Required for Live 15m Trading)

**Entrypoint:**
- `start_15m.ps1`
- `web/main_15m_lean.py`

**Venue:**
- `merid/event_venues/kalshi/ws_bridge.py`
- `merid/event_venues/kalshi/market_state.py`
- `merid/event_venues/kalshi/market_catalog.py`
- `merid/event_venues/kalshi/client.py`
- `merid/event_venues/kalshi/invariants.py`
- `merid/event_venues/kalshi/bankroll_service_v2.py`
- `merid/event_venues/kalshi/kalshi_risk.py`
- `merid/event_venues/kalshi/models.py`
- `merid/event_venues/kalshi/fills_ledger.py`
- `merid/event_venues/kalshi/fills_poller.py`
- `merid/event_venues/kalshi/candle_poller.py`

**Prediction:**
- `merid/prediction/agent_grid_15m.py`
- `merid/prediction/spot_provider.py`

**Data:**
- `data/unified_spot_service.py`

**Loop:**
- `merid/loop_15m.py`

**API:**
- `web/api/performance_api.py`
- `web/api/kalshi_api.py`
- `web/api/kalshi_agent_grid_api.py`
- `web/api/health_api.py`
- `web/api/loop_api.py`
- `web/api/spot_debug_api.py`
- `web/api/paper_session_api.py`
- `web/api/system_endpoints.py`
- `web/api/agents.py`
- `web/api/auth.py`

**Validation:**
- `merid/startup_validations.py`
- `merid/legacy_module_guard.py`
- `merid/kalshi_15m_runtime_check.py`
- `merid/meta_cognition/`
- `merid/monitoring/integrity_monitor.py`

**Utils:**
- `utils/logger.py`
- `web/startup_state.py`

**Settings:**
- `merid/settings.py` (shared, but required)

### Category B - Safe Shared Core (Generic Utilities)

**Logging:**
- `utils/logger.py`

**Settings:**
- `merid/settings.py` (if profile-gated)

**Constants:**
- `merid/constants.py`

**Mode Resolution:**
- `merid/mode_resolver.py`

### Category C - Legacy / Off-Limits (Should NOT be used by 15m)

**Legacy Entrypoints:**
- `main.py` (1569 bytes) - Legacy main entrypoint
- `web/main.py` - Legacy web entrypoint

**Legacy Loops:**
- `merid/loop.py` (142,787 lines) - Legacy main loop

**Legacy Agent Grids:**
- `merid/prediction/agent_grid.py` (if exists) - Legacy agent grid

**Legacy Venues:**
- Any venue modules outside `merid/event_venues/kalshi/` (unless explicitly used)

**Legacy Core:**
- `merid/core/` - Legacy core system (PM runtime, deployment controller, etc.)

**Legacy Risk:**
- `merid/risk/` - Legacy risk modules (15m uses `kalshi_risk.py`)

**Legacy Execution:**
- `merid/execution/` - Legacy execution engine
- `merid/execution_guard.py` (45,858 bytes) - Legacy execution guard

**Legacy Social:**
- `merid/social/` - Social broadcasters (not used by 15m)

**Legacy LLM:**
- `merid/llm/` - LLM modules (not used by 15m)

**Legacy Blockchain:**
- `merid/blockchain/` - Blockchain modules (not used by 15m)

**Legacy PM:**
- `merid/pm_runtime.py`
- `merid/pm_live_readiness.py`
- `merid/pm_crypto_ops.py`

### Category D - Ambiguous (Contains Both 15m and Legacy Logic)

**Settings:**
- `merid/settings.py` (84,386 bytes) - Contains both 15m and legacy settings

**Startup Validations:**
- `merid/startup_validations.py` (170,958 bytes) - May contain legacy validation paths

**Risk:**
- `merid/guards/global_risk_guard.py` - Used by 15m, but may have legacy paths

**Meta-Cognition:**
- `merid/meta_cognition/` - New module, but may reference legacy components

---

## 5. Explicit Flags and Asserts in 15m Path

### Existing Protections

**Profile Validation (P1.1):**
```python
profile = os.getenv("MERID_PROFILE", "")
if profile != "kalshi_crypto_15m_v2":
    logger.error(f"[STARTUP] Invalid profile '{profile}'. Expected 'kalshi_crypto_15m_v2'")
    raise RuntimeError(f"Invalid profile: {profile}. Expected: kalshi_crypto_15m_v2")
```

**Legacy Module Guard (P1.2.1):**
```python
from merid.legacy_module_guard import get_legacy_module_report, assert_no_legacy_modules
legacy_report = get_legacy_module_report()
assert_no_legacy_modules(context="startup")
```

**Forbidden Imports (Documented in Header):**
```python
# FORBIDDEN: merid.prediction.agent_grid (use agent_grid_15m)
# FORBIDDEN: web.main (use web.main_15m_lean only)
# FORBIDDEN: core.* modules (legacy system)
# FORBIDDEN: merid.loop (use merid.loop_15m)
```

### Recommended Additional Protections

**Import-Time Guard:**
```python
# At top of main_15m_lean.py
import sys
FORBIDDEN_MODULES = ['merid.loop', 'merid.prediction.agent_grid', 'web.main', 'merid.core']
for mod in FORBIDDEN_MODULES:
    if mod in sys.modules:
        raise RuntimeError(f"[15M-LEAN] Forbidden module loaded: {mod}")
```

**Runtime Mode Flag:**
```python
# Set early in startup
os.environ['MERID_RUNTIME_MODE'] = '15m_live'

# Check in critical modules
if os.getenv('MERID_RUNTIME_MODE') != '15m_live':
    raise RuntimeError("Invalid runtime mode for 15m stack")
```

---

## 6. Audit Artifacts

### What's Being Used in the 15m Stack

**Core Infrastructure:**
- FastAPI web server with health-triggered startup
- Multi-threaded architecture (startup thread + trading thread)
- Kalshi WebSocket bridge with per-ticker queues and batch worker
- Kalshi market state store with SUSPECT/GOOD tracking
- Kalshi market catalog with auto-refresh
- Kalshi bankroll service V2
- Unified spot service with watchdog
- 15m agent grid with 5 crypto agents (BTC, ETH, SOL, XRP, DOGE)
- Kalshi 15m loop with signal generation
- Kalshi risk config
- Fills ledger and poller
- Candle poller for 1-minute OHLCV bars

**API Endpoints:**
- `/api/v1/health` - Health check and startup trigger
- `/api/v1/ping` - Simple ping
- `/api/v1/md-debug` - Market data freshness debug
- `/api/v1/loop-status` - Loop status
- `/api/v1/agents` - Agent grid status
- `/api/v1/risk-snapshot` - Risk and bankroll state
- `/api/v1/meta-cognition` - Meta-cognitive check
- `/api/v1/self-check` - Production invariants check

### What's Still Missing

**Tests:**
- WS reconnect behavior with stall/keepalive
- Spot service watchdog
- Per-ticker batching and SUSPECT→GOOD transitions
- Integration tests for 15m stack end-to-end

**Monitoring:**
- Prometheus/Grafana metrics
- Structured log summaries for:
  - WS health
  - Spot health
  - Orderbook health
  - Signal health

**Documentation:**
- Runbook for 15m stack operations
- Troubleshooting guide for common issues
- Performance tuning guide

### What's Still Being Affected by Legacy Code

**Shared Settings:**
- `merid/settings.py` contains both 15m and legacy settings
- Risk: Legacy defaults could override 15m settings

**Shared Singletons:**
- Market state store, catalog, WS bridge, bankroll, spot service are all singletons
- Risk: If legacy code uses these singletons, state could leak

**Ambiguous Modules:**
- `merid/startup_validations.py` (170KB) - May contain legacy validation paths
- `merid/guards/global_risk_guard.py` - Used by 15m, but may have legacy paths

**File System Artifacts:**
- Multiple log files from legacy runs (server_*.log, debug_*.log)
- Multiple audit files from legacy audits (audit_*.txt)
- Risk: Confusion about which logs are current

---

## 7. Recommendations

### Short-Term Mitigations

1. **Add Import-Time Guard:** Prevent forbidden modules from being loaded at import time
2. **Add Runtime Mode Flag:** Set `MERID_RUNTIME_MODE=15m_live` and check in critical modules
3. **Audit Shared Settings:** Review `merid/settings.py` and ensure 15m settings are not overridden by legacy defaults
4. **Clean Log Files:** Archive or delete legacy log files to avoid confusion

### Long-Term Fixes

1. **Split Settings Module:** Extract 15m-specific settings to `merid/settings_15m.py`
2. **Split Startup Validations:** Extract 15m-specific validations to `merid/startup_validations_15m.py`
3. **Rename Legacy Modules:** Add `_legacy` suffix to clearly mark legacy modules (e.g., `merid/loop_legacy.py`)
4. **Add Integration Tests:** Create comprehensive integration tests for the 15m stack
5. **Add Monitoring:** Implement Prometheus/Grafana metrics for observability

---

## 8. Next Steps

1. **Review Legacy Module Guard:** Ensure `merid/legacy_module_guard.py` is correctly identifying all legacy modules
2. **Add Import-Time Guard:** Implement import-time guard in `main_15m_lean.py`
3. **Audit Settings:** Review `merid/settings.py` for legacy defaults that could affect 15m
4. **Clean Logs:** Archive legacy log files
5. **Add Tests:** Create integration tests for critical paths (WS reconnect, spot watchdog, batch worker)

---

**End of Audit Report**
