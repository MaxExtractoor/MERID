# Kalshi 15m Profile Audit Compilation

**Date**: 2026-05-15
**Profile**: `kalshi_crypto_15m_v2`
**Goal**: Treat the 15m profile as a sealed product surface - only minimal core services + 5 agents + trading/risk allowed to affect it. Everything else must be profile-guarded off or made read-only/telemetry.

---

## Executive Summary

The new thin entrypoint (`web.main_15m.py`) and lean loop (`merid.loop_15m.py`) have been successfully created and isolated from legacy components. However, the codebase still contains many references to 15m assets and constants in legacy PM/research code, UI components, and cross-product hooks that could potentially affect the 15m profile.

**Status**: Core 15m stack is clean, but legacy tentacles remain throughout the codebase.

---

## 1. Core 15m Stack - VERIFIED CLEAN ✓

### Files Created (Isolated Path)
- **`web.main_15m.py`**: New thin FastAPI entrypoint for kalshi_crypto_15m_v2 only
  - Profile validation on startup (rejects non-15m profiles)
  - Minimal imports: no orchestrator, governance, treasury, reflection, mesh
  - Phases: Core infra → Kalshi venue → AgentGrid → Kalshi15mLoop
  - No legacy component imports verified

- **`merid.loop_15m.py`**: New lean event loop for 15m profile
  - `Kalshi15mLoop` class with 5-second cadence
  - Calls `agent_grid.run_cycle(tick)` to step agents
  - No legacy orchestrator, mesh, or PM components
  - No imports of cross-product hooks verified

- **`merid.prediction.agent_grid.py`**: Added `run_cycle()` method
  - Lean method for 15m loop to step all agents
  - No background task machinery (unlike full `start()`)
  - Returns summary with cycle duration, agent states, errors

### Deployment Scripts Updated
- **`start.bat`**: Profile-based entrypoint selection
  - Uses `web.main_15m:app` for `kalshi_crypto_15m_v2`
  - Uses `web.main:app` for other profiles

- **`start.sh`**: Profile-based entrypoint selection
  - Uses `web.main_15m:app` for `kalshi_crypto_15m_v2`
  - Uses `web.main:app` for other profiles

### Test Suite Created
- **`tests/test_kalshi_15m_entrypoint.py`**: Regression tests for new entrypoint
  - Tests profile validation
  - Tests no legacy imports
  - Tests AgentGrid loads 5 agents
  - Tests Kalshi15mLoop instantiation and cycling
  - Tests risk envelope YAML exists

---

## 2. 15m Constants Audit - LEGACY TENTACLES IDENTIFIED

### Series Ticker References (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)

**Core 15m Stack (Keep - No Action Needed)**
- `web/main_15m.py` line 260: allowed_series whitelist
- `config/kalshi_agent_grid.yaml`: Agent series_tickers
- `config/kalshi_universe.py`: KALSHI_CRYPTO_PRODUCTS dictionary
- `merid/event_venues/kalshi/market_catalog.py`: _PRIORITY_SERIES
- `merid/event_venues/kalshi/market_state.py`: Market state tracking
- `merid/event_venues/kalshi/ws_bridge.py`: WebSocket subscriptions
- `merid/event_venues/kalshi/order_router.py`: Order routing
- `merid/loop_15m.py`: Loop references

**Legacy PM/Research (Must Be Profile-Guarded)**
- `strategy_dashboard.py` line 82: Dashboard mock data with KXBTC15M, KXETH15M
- `services/crypto_surface_loader.py` line 358: Crypto surface loader with KXBTC15M, KXETH15M
- `scripts/analyze_entry_window.py` line 41: Entry window analysis script

**Test Files (Safe - Test-Only)**
- 100+ test files use KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M in test fixtures
- These are expected and safe (test isolation)

### Agent Name References (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

**Core 15m Stack (Keep - No Action Needed)**
- `web/main_15m.py` line 387: allowed_15m_agents whitelist
- `config/kalshi_agent_grid.yaml`: Agent definitions
- `merid/prediction/agent_grid.py`: Agent instantiation

**Legacy PM/Research (Must Be Profile-Guarded)**
- `web/startup_agents.py` lines 245-264: Crypto15MLane startup (BTC_15M lane)
- `web/api/kalshi_api.py` line 6798: Lane registry get_lane("BTC_15M")
- `web/api/kalshi_api.py` line 7105-7111: decide_btc_15m_endpoint (sentiment decision)
- `web/api/kalshi_grid_api.py` line 1046: btc_15m_missing check
- `web/api/kalshi_paper_portfolio_api.py` line 67: crypto_agents list includes btc_15m_regime
- `web/api/config/kalshi_signals.py` line 5: btc_15m_regime signal
- `web/api/models/signals.py` line 8: btc_15m in SIGNAL_SOURCES
- `web/api/agent_modes_api.py` line 100: btc_15m_regime in agent list
- `utils/logging_helpers.py` line 91: log_trading_context with btc_15m_regime
- `web/react/src/constants/api.ts` line 3: BTC_15M API endpoint
- `web/react/src/components/KalshiPaperVsShadowPanel.tsx` line 6: btc_15m_regime
- `web/react/src/docs/WEBSOCKET_ENDPOINTS_SPEC.md` line 130: btc_15m_lane_1

**Test Files (Safe - Test-Only)**
- 50+ test files use BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M in test fixtures
- These are expected and safe (test isolation)

### Profile References (kalshi_crypto_15m_v2)

**Profile Guards (Correct - No Action Needed)**
- `web/startup_agents.py` lines 133-194: Multiple profile guards for kalshi_crypto_15m_v2
  - Skip insight pipeline (line 138)
  - Skip AgentMesh (line 161)
  - Skip social broadcaster (line 182)
  - Skip reflection system (line 194)
- `web/main.py` lines 2633-2638: Profile guard for agent grid startup
- `web/main.py` lines 2976-2981: Profile guard for reflection layer
- `web/main.py` lines 3994-4009: Profile guard for core.agent_orchestrator
- `web/main.py` lines 4108-4116: Profile guard for agent mesh
- `tests/test_crypto_15m_sentiment_isolation.py`: Profile guard tests
- `tests/test_crypto_15m_profile_fixes.py`: Profile compatibility tests
- `tests/test_orchestrator_profile_guards.py`: Orchestrator profile guard tests

**Test Files (Safe - Test-Only)**
- Multiple test files check profile guards are in place
- These are expected and safe (test isolation)

---

## 3. UI/UX Audit - REACT DOES NOT REFERENCE 15m PROFILE

### Finding
- **React/JS files do NOT reference `kalshi_crypto_15m_v2` directly**
- Search of `web/react/` directory found zero matches for `kalshi_crypto_15m`

### UI Components That Reference 15m Assets (Read-Only - Safe)
- `web/react/src/constants/api.ts`: BTC_15M API endpoint (read-only)
- `web/react/src/components/KalshiPaperVsShadowPanel.tsx`: btc_15m_regime (read-only display)
- `web/react/src/docs/WEBSOCKET_ENDPOINTS_SPEC.md`: btc_15m_lane_1 (documentation)

### Assessment
- UI components are read-only (display-only)
- No UI component can mutate 15m profile configuration
- No UI component can change risk caps, strategy parameters, or allowed assets
- This is acceptable - UI can read telemetry but cannot mutate

---

## 4. Cross-Product Hooks Audit - web.main_15m VERIFIED CLEAN ✓

### Imports in web.main_15m.py (Top-Level Only)
```python
from __future__ import annotations
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from utils.logger import get_logger
```

### Dynamic Imports (Inside Functions)
```python
# Core infrastructure
from core.redis_client import get_redis_client
from merid.guards.global_risk_guard import get_global_risk_guard

# Kalshi venue
from merid.event_venues.kalshi.client import get_kalshi_client
from merid.event_venues.kalshi import get_bankroll_service
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
from merid.event_venues.kalshi.fills_poller import get_fills_poller
from merid.event_venues.kalshi.settlement_poller import get_settlement_poller
from merid.event_venues.kalshi.rti_feed_service import get_rti_feed_service
from merid.term_structure import get_term_structure_model

# Agent grid and loop
from merid.prediction.agent_grid_config import load_agent_grid_config
from merid.prediction.agent_grid import AgentGrid
from merid.loop_15m import get_kalshi_15m_loop
```

### Assessment
- **NO imports of**: core.systemorchestrator, governance.*, treasury.*, reflection, mesh
- **NO imports of**: PM agents, regime agents, consensus engine
- **NO imports of**: KalshiContinuousTrader (legacy/research)
- **VERIFIED CLEAN**: web.main_15m does not import cross-product hooks

---

## 5. API Endpoints Audit - web.main_15m HAS NO MUTATION ROUTES

### Current Endpoints in web.main_15m.py
```python
GET /                    # Root endpoint
GET /health              # Health check (read-only)
GET /status              # Status summary (read-only)
```

### Assessment
- **NO mutation endpoints**: No routes for updating risk, strategy, or config
- **NO admin endpoints**: No routes for changing profile parameters
- **VERIFIED SAFE**: All endpoints are read-only telemetry

### Legacy web.main Endpoints (NOT ACCESSED BY 15m PROFILE)
The legacy `web/main.py` has many mutation endpoints, but these are NOT used by the 15m profile because:
1. The new entrypoint `web.main_15m` does NOT include these routes
2. Deployment scripts route `kalshi_crypto_15m_v2` to `web.main_15m:app`
3. Legacy endpoints remain available for other profiles only

---

## 6. Issues Requiring Action

### Priority P0 (Critical - Blocks 15m Trading)
**None identified** - Core 15m stack is clean and functional.

### Priority P1 (High - Confusion, Over-Engineering)

#### Issue 1: Legacy PM/Research Code References 15m Constants
**Files Affected**:
- `strategy_dashboard.py`
- `services/crypto_surface_loader.py`
- `scripts/analyze_entry_window.py`

**Risk**: These files reference 15m assets and could potentially affect the 15m profile if called.

**Action Required**: Add profile guards to these files to skip or disable when `MERID_PROFILE=kalshi_crypto_15m_v2`.

#### Issue 2: Legacy API Endpoints Reference 15m Agent Names
**Files Affected**:
- `web/api/kalshi_api.py` (decide_btc_15m_endpoint, lane registry access)
- `web/api/kalshi_grid_api.py` (btc_15m_missing check)
- `web/api/kalshi_paper_portfolio_api.py` (crypto_agents list)
- `web/api/config/kalshi_signals.py` (btc_15m_regime signal)
- `web/api/models/signals.py` (btc_15m in SIGNAL_SOURCES)
- `web/api/agent_modes_api.py` (btc_15m_regime in agent list)

**Risk**: These endpoints are in the legacy `web/main.py` and are NOT accessed by the 15m profile (which uses `web.main_15m`). However, if someone accidentally routes the 15m profile to the legacy entrypoint, these could affect it.

**Action Required**: Add profile guards to these endpoints to return 403 or disabled message when `MERID_PROFILE=kalshi_crypto_15m_v2`.

#### Issue 3: UI API Constants Reference 15m Endpoints
**Files Affected**:
- `web/react/src/constants/api.ts` (BTC_15M endpoint)
- `web/react/src/components/KalshiPaperVsShadowPanel.tsx` (btc_15m_regime)
- `web/react/src/docs/WEBSOCKET_ENDPOINTS_SPEC.md` (btc_15m_lane_1)

**Risk**: These are read-only UI components, but they reference legacy endpoints that may not exist in `web.main_15m`.

**Action Required**: Update UI constants to conditionally use correct endpoints based on active profile, or hide these features when `kalshi_crypto_15m_v2` is active.

### Priority P2 (Medium - Cleanup, Maintenance)

#### Issue 4: Test Files Need Profile Guard Validation
**Files Affected**:
- Multiple test files reference 15m assets

**Risk**: Tests may accidentally test legacy code paths instead of the new isolated path.

**Action Required**: Add validation tests to ensure `web.main_15m` is used for `kalshi_crypto_15m_v2` profile.

#### Issue 5: No Contract Document
**Files Affected**:
- No existing contract document

**Risk**: No explicit contract defining allowed/forbidden modules for the 15m profile.

**Action Required**: Create `docs/kalshi_15m_contract.md` with explicit allowed/forbidden module lists.

### Priority P3 (Low - Test-Only, Research)

#### Issue 6: Research Sentiment Tests Reference 15m Profile
**Files Affected**:
- `tests/research_sentiment/*.py` (multiple files)

**Risk**: These test files explicitly state "kalshi_crypto_15m_v2 production test runs. Sentiment is research-only".

**Action Required**: These are test-only and research-only, no action needed. Document that sentiment is research-only for this profile.

---

## 7. Recommended Actions

### Immediate (P1 - High Priority)

1. **Add Profile Guards to Legacy PM/Research Code**
   - `strategy_dashboard.py`: Skip when `MERID_PROFILE=kalshi_crypto_15m_v2`
   - `services/crypto_surface_loader.py`: Skip when `MERID_PROFILE=kalshi_crypto_15m_v2`
   - `scripts/analyze_entry_window.py`: Skip when `MERID_PROFILE=kalshi_crypto_15m_v2`

2. **Add Profile Guards to Legacy API Endpoints**
   - `web/api/kalshi_api.py`: Add 403 for `decide_btc_15m_endpoint` when profile is `kalshi_crypto_15m_v2`
   - `web/api/kalshi_grid_api.py`: Add 403 for btc_15m endpoints when profile is `kalshi_crypto_15m_v2`
   - Other kalshi API files: Add profile guards to 15m-specific endpoints

3. **Update UI Constants for Profile-Based Routing**
   - `web/react/src/constants/api.ts`: Add profile-based endpoint selection
   - Hide or disable 15m-specific UI features when profile is not `kalshi_crypto_15m_v2`

### Short-Term (P2 - Medium Priority)

4. **Create Contract Document**
   - Create `docs/kalshi_15m_contract.md` with explicit allowed/forbidden modules
   - Document that only minimal core services + 5 agents + trading/risk are allowed
   - Document that orchestrator, governance, treasury, reflection, mesh are forbidden

5. **Add Validation Tests**
   - Add test to assert `web.main_15m` is used for `kalshi_crypto_15m_v2` profile
   - Add test to assert legacy endpoints return 403 for 15m profile
   - Add test to assert no cross-product imports in `web.main_15m`

6. **Add Profile Guards to Constants**
   - Create `tests/test_kalshi_15m_constants.py` to assert market allowlist and risk caps
   - Assert that only 5 15m series tickers are allowed
   - Assert that risk caps match profile YAML values

### Long-Term (P3 - Low Priority)

7. **Document Research-Only Components**
   - Document that sentiment is research-only for `kalshi_crypto_15m_v2`
   - Document that KalshiContinuousTrader is legacy/research-only
   - Document that PM agents and regime agents are not used for 15m profile

---

## 8. Summary Statistics

### Files Created (Isolated Path)
- `web.main_15m.py` - New thin entrypoint
- `merid.loop_15m.py` - New lean loop
- `tests/test_kalshi_15m_entrypoint.py` - Regression test suite

### Files Modified (Deployment)
- `start.bat` - Profile-based entrypoint selection
- `start.sh` - Profile-based entrypoint selection
- `merid/prediction/agent_grid.py` - Added `run_cycle()` method

### Files Requiring Profile Guards (P1)
- `strategy_dashboard.py`
- `services/crypto_surface_loader.py`
- `scripts/analyze_entry_window.py`
- `web/api/kalshi_api.py` (multiple endpoints)
- `web/api/kalshi_grid_api.py`
- `web/api/kalshi_paper_portfolio_api.py`
- `web/api/config/kalshi_signals.py`
- `web/api/models/signals.py`
- `web/api/agent_modes_api.py`

### Files Requiring UI Updates (P1)
- `web/react/src/constants/api.ts`
- `web/react/src/components/KalshiPaperVsShadowPanel.tsx`

### Files to Create (P2)
- `docs/kalshi_15m_contract.md`
- `tests/test_kalshi_15m_constants.py`

---

## 9. Conclusion

The core 15m stack is clean and isolated. The new thin entrypoint and lean loop successfully avoid legacy components. However, the codebase still contains legacy tentacles in the form of:
1. PM/research code that references 15m constants without profile guards
2. Legacy API endpoints that reference 15m agents without profile guards
3. UI constants that reference legacy endpoints

These issues do NOT currently block 15m trading because the new entrypoint (`web.main_15m`) is isolated and does not include these components. However, they create confusion and could cause issues if someone accidentally routes the 15m profile to the legacy entrypoint.

**Recommendation**: Implement the P1 actions to add profile guards to legacy code, ensuring the 15m profile remains a sealed product surface.
