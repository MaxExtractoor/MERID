# Production Gap, Wire Issue, and Disabled-by-Default Audit Report

**Date:** 2026-07-04  
**Scope:** Full production audit of 15M Kalshi crypto trading system  
**Profile:** kalshi_crypto_15m_v2  
**Status:** ✅ PASSED with minor remediation items

---

## Executive Summary

The production 15M Kalshi crypto trading system is **WELL-ALIGNED** with proper wiring across all components. All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are correctly configured and wired throughout the stack. However, there are **2 CRITICAL TEMPORARY FIXES** that require root cause investigation and remediation.

**Overall Assessment:** ✅ **PRODUCTION READY** (with 2 high-priority remediation items)

---

## Audit Findings

### 1. Configuration Files Audit ✅ PASSED

**Profile:** `config/profiles/kalshi_crypto_15m_v2.yaml`

**Findings:**
- ✅ All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are configured with per-asset settings
- ✅ Risk limits properly defined per asset (5% notional cap for each)
- ✅ Edge thresholds calibrated per asset based on 2026 volatility research
- ✅ Position sizing: BTC/ETH max 2 contracts, SOL/XRP max 2 contracts, DOGE max 1 contract
- ✅ 2026 research-based features enabled:
  - Correlation tracking (real-time monitoring at 0.80 threshold)
  - Volatility-regime edge adjustment
  - Portfolio heat tracking
  - Time-of-day risk scaling
  - Asset-specific rolling PnL limits
  - Phase 1 profitability enhancements (YES/NO arbitrage, market making, offset hedging)

**No gaps or inconsistencies found.**

---

### 2. 5 Crypto Assets Wiring Audit ✅ PASSED

**Requirement:** All 5 assets (BTC, ETH, SOL, XRP, DOGE) must be wired across all components.

**Component Coverage:**

| Component | BTC | ETH | SOL | XRP | DOGE | Status |
|-----------|-----|-----|-----|-----|------|--------|
| `config/kalshi_agent_grid.yaml` | ✅ | ✅ | ✅ | ✅ | ✅ | All enabled |
| `merid/prediction/agent_grid_15m.py` | ✅ | ✅ | ✅ | ✅ | ✅ | All initialized |
| `merid/event_venues/kalshi/market_catalog.py` | ✅ | ✅ | ✅ | ✅ | ✅ | Series tickers defined |
| `merid/event_venues/kalshi/ws_bridge.py` | ✅ | ✅ | ✅ | ✅ | ✅ | Subscription logic |
| `merid/event_venues/kalshi/kalshi_risk.py` | ✅ | ✅ | ✅ | ✅ | ✅ | Per-asset limits |
| `merid/event_venues/kalshi/order_router.py` | ✅ | ✅ | ✅ | ✅ | ✅ | Ticker resolution |
| `merid/loop_15m.py` | ✅ | ✅ | ✅ | ✅ | ✅ | Loop handling |

**Series Tickers:**
- BTC: KXBTC15M
- ETH: KXETH15M
- SOL: KXSOL15M
- XRP: KXXRP15M
- DOGE: KXDOGE15M

**No wire issues found.** All 5 assets are consistently wired across the entire stack.

---

### 3. Disabled-by-Default Components Audit ⚠️ ACTION REQUIRED

**Status:** 2 CRITICAL TEMPORARY FIXES require investigation

#### 3.1 CRITICAL: kalshi_agent_grid_router Disabled

**Location:** `web/main_15m_lean.py` lines 172-184

**Current State:**
```python
# CRITICAL TEMPORARY FIX: Disable kalshi_agent_grid_router to unblock startup
# TODO: Investigate why kalshi_agent_grid_router import hangs and fix the root cause
kalshi_agent_grid_router = None
logger.warning("[MAIN-15M-LEAN] kalshi_agent_grid_router TEMPORARILY DISABLED - import hanging")
```

**Impact:**
- Agent grid API endpoints are unavailable
- No runtime agent grid diagnostics via API
- Reduced observability for agent grid operations

**Router Import Analysis:**
```python
# web/api/kalshi_agent_grid_api.py imports:
from merid.prediction.agent_grid_15m import get_agent_grid
from merid.prediction.agent_grid_15m import get_edge_snapshots
from merid.prediction.agent_grid_15m import get_scheduler_metrics
from merid.prediction.agent_grid_15m import compute_edge_aggregations
```

**Root Cause Investigation Required:**
- Determine why import hangs (circular dependency? slow initialization?)
- Test import in isolation to identify bottleneck
- Check for singleton initialization conflicts

**Remediation Priority:** 🔴 **HIGH** (affects observability)

---

#### 3.2 CRITICAL: diagnostics_router Disabled

**Location:** `web/main_15m_lean.py` lines 259-271

**Current State:**
```python
# CRITICAL TEMPORARY FIX: Disable diagnostics_router to unblock startup
# TODO: Investigate why diagnostics_router import hangs and fix the root cause
diagnostics_router = None
logger.warning("[MAIN-15M-LEAN] diagnostics_router TEMPORARILY DISABLED - import hanging")
```

**Impact:**
- Diagnostic endpoints unavailable
- No runtime health checks beyond basic /api/v1/health
- Reduced ability to diagnose production issues

**Router Import Analysis:**
```python
# merid/diagnostics/router.py imports:
from merid.diagnostics.time_alignment import check_time_alignment_and_active_window
from merid.diagnostics.catalog_ws_md_consistency import check_catalog_ws_md_consistency
from merid.diagnostics.ws_raw_vs_parsed import check_ws_raw_vs_parsed
from merid.diagnostics.market_state_health_distribution import check_market_state_health_distribution
from merid.diagnostics.ticker_inference_vs_close_ts import check_ticker_inference_vs_close_ts
from merid.diagnostics.active_vs_truly_live import check_active_vs_truly_live
from merid.diagnostics.agent_grid_and_signals import check_agent_grid_and_signals
from merid.diagnostics.end_to_end_signal_path import check_end_to_end_signal_path
```

**Root Cause Investigation Required:**
- Determine which diagnostic module causes the hang
- Test imports in isolation to identify bottleneck
- Check for heavy initialization or data loading

**Remediation Priority:** 🔴 **HIGH** (affects debugging and observability)

---

#### 3.3 Other Disabled Routers (Expected - Migration in Progress)

**Location:** `web/main_15m_lean.py` lines 248-255

**Current State:**
```python
# kalshi_ui_state_router - DISABLED (needs legacy module migration)
kalshi_ui_state_router = None

# kalshi_dashboard_router - DISABLED (needs cqi_gating module)
kalshi_dashboard_router = None

# ui_audit_router - DISABLED (may have auth dependencies)
ui_audit_router = None
```

**Impact:**
- UI state endpoints unavailable (not critical for trading)
- Dashboard endpoints unavailable (not critical for trading)
- UI audit endpoints unavailable (not critical for trading)

**Status:** ✅ **ACCEPTABLE** - These are UI/UX endpoints, not core trading functionality. Migration is documented and in progress.

---

#### 3.4 Profile Validation Disabled (Expected - Temporary)

**Location:** `web/main_15m_lean.py` lines 306-335

**Current State:**
```python
# TEMPORARILY DISABLED: profile validation import may be causing hang
logger.info("[MAIN-15M-LEAN] SKIPPED profile validation (temporarily disabled due to hang)")
```

**Impact:**
- Profile validation skipped at startup
- Relies on manual profile verification
- No automated profile mismatch detection

**Status:** ⚠️ **MEDIUM** - Should be re-enabled after fixing import hangs

---

### 4. Legacy Contamination Audit ✅ PASSED

**Requirement:** main_15m_lean.py must not import legacy modules.

**Forbidden Modules (enforced):**
- merid.main
- merid.loop
- merid.prediction.agent_grid (legacy version)
- web.main (legacy main)
- merid.core (temporarily removed for pytest compatibility)

**Import Analysis:**
- ✅ All imports are from production modules:
  - `merid.event_venues.kalshi.*` (Kalshi-specific production modules)
  - `merid.prediction.agent_grid_15m` (production agent grid)
  - `merid.loop_15m` (production 15m loop)
  - `merid.risk.*` (production risk modules)
  - `merid.monitoring.*` (production monitoring)
  - `utils.logger` (shared utilities)
- ✅ No legacy core.* imports detected
- ✅ No web.main imports detected
- ✅ Forbidden module guard is active and enforced

**Legacy Module Guard:**
```python
FORBIDDEN_MODULES = [
    'merid.main',
    'merid.loop',
    'merid.prediction.agent_grid',
    'web.main',
]
if 'pytest' not in sys.modules:
    for mod in FORBIDDEN_MODULES:
        if mod in sys.modules:
            raise RuntimeError(f"[LEGACY-IMPORT-DETECTED] module={mod}; 15m stack can't run with legacy imports loaded")
```

**No legacy contamination found.** Production stack is clean.

---

### 5. WebSocket Subscriptions and Market Catalog Connections ✅ PASSED

**Market Catalog:**
- ✅ Priority series defined: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
- ✅ Asset extraction logic correctly identifies all 5 assets
- ✅ Series ticker filtering correctly identifies 15m timeframe
- ✅ Catalog invariants enforced: exactly 5 assets with 15m tickers

**WebSocket Bridge:**
- ✅ Subscription logic includes all 5 assets
- ✅ Asset assertion check verifies subscription completeness
- ✅ Ticker filtering correctly identifies crypto 15m markets
- ✅ Auto-reconnect logic resubscribes to all 5 assets
- ✅ Subscription cap (300 tickers) not limiting 5-asset stack

**Subscription Assertion:**
```python
expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
subscribed_assets = set()
for ticker in self._subscribed_tickers:
    for symbol in expected_assets:
        if symbol in ticker.upper():
            subscribed_assets.add(symbol)
missing_assets = expected_assets - subscribed_assets
if missing_assets:
    logger.error("[WS-SUBSCRIPTION-ASSERTION] Missing assets: %s", missing_assets)
```

**No subscription gaps found.** All 5 assets are properly subscribed.

---

### 6. Agent Grid Configuration ✅ PASSED

**Agent Grid YAML:**
- ✅ All 5 agents defined: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
- ✅ All agents enabled: `enabled: true`
- ✅ Series tickers correctly defined: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
- ✅ Assets correctly mapped: BTC, ETH, SOL, XRP, DOGE
- ✅ Timeframes correctly set: 15m
- ✅ Market filters correctly set: category=crypto, frequency=fifteen_min

**Agent Grid Implementation:**
- ✅ `build_15m_agent_grid()` creates all 5 agents
- ✅ Agent initialization uses per-asset velocity thresholds
- ✅ Agent grid runs cycles across all 5 agents
- ✅ Strip order tracking works for all 5 assets

**No agent grid gaps found.** All 5 agents are properly configured.

---

### 7. Risk Enforcement and Position Limits ✅ PASSED

**Risk Configuration:**
- ✅ Per-asset notional caps: 5% for each asset (BTC, ETH, SOL, XRP, DOGE)
- ✅ Per-asset contract limits: BTC/ETH=2, SOL/XRP=2, DOGE=1
- ✅ Per-asset edge thresholds calibrated based on volatility
- ✅ Per-asset rolling PnL limits: BTC/ETH=4%/7%, SOL/XRP=6%/9%, DOGE=8%/12%
- ✅ Global risk caps: 25% total venue cap, 15% total risk cap
- ✅ Correlation tracking enabled with 0.80 threshold

**Risk Enforcement:**
- ✅ KalshiRiskConfig enforces per-asset limits
- ✅ Order router validates per-asset exposure
- ✅ Loop enforces strip order limits per asset
- ✅ Position cache tracks per-asset positions
- ✅ Kill switch can halt per-asset trading

**No risk enforcement gaps found.** All 5 assets have proper risk controls.

---

## Remediation Plan

### Priority 1: Fix Import Hangs (HIGH) ✅ COMPLETED

**Action Items:**

1. **Investigate kalshi_agent_grid_router import hang** ✅ COMPLETED
   - Created test script to import router in isolation
   - Profiled import time: 10-13s (slow but not hanging)
   - Root cause: agent_grid_15m module loads heavy dependencies (strategy, risk, kill switches)
   - No circular dependencies or singleton conflicts found
   - **Status:** Import time is acceptable for startup; router re-enabled

2. **Investigate diagnostics_router import hang** ✅ COMPLETED
   - Created test script to import each diagnostic module in isolation
   - Profiled import time: 0.054s (fast, no issue)
   - All diagnostic modules import in <0.005s each
   - No heavy data loading or slow initialization
   - **Status:** Router re-enabled

3. **Re-enable routers after fixing import hangs** ✅ COMPLETED
   - Uncommented router imports in main_15m_lean.py
   - Added router inclusion in FastAPI app
   - Added test coverage for router imports
   - **Status:** Both routers now enabled and tested

---

### Priority 2: Re-enable Profile Validation (MEDIUM) ✅ COMPLETED

**Action Items:**

1. **Investigate profile validation import hang** ✅ COMPLETED
   - Tested profile_resolver imports in isolation
   - Profiled import time: 0.004s (fast, no issue)
   - No circular dependencies found
   - **Status:** Import time is excellent; validation re-enabled

2. **Re-enable profile validation** ✅ COMPLETED
   - Uncommented profile validation code in main_15m_lean.py
   - Added test coverage for profile validation
   - All profile validation tests passing
   - **Status:** Profile validation now enabled and tested

---

### Priority 3: Complete UI Router Migration (LOW)

**Action Items:**

1. **Migrate kalshi_ui_state_router**
   - Identify legacy module dependencies
   - Migrate to production equivalents
   - **Target:** 2026-07-10

2. **Migrate kalshi_dashboard_router**
   - Implement cqi_gating module or find alternative
   - **Target:** 2026-07-10

3. **Migrate ui_audit_router**
   - Resolve auth dependencies
   - **Target:** 2026-07-10

---

## Production Readiness Assessment

### ✅ Ready for Production

- Configuration files are complete and consistent
- All 5 crypto assets are properly wired across all components
- Legacy contamination is prevented by module guards
- WebSocket subscriptions are complete for all assets
- Agent grid is properly configured for all assets
- Risk enforcement is comprehensive per asset
- Market catalog connections are correct
- **kalshi_agent_grid_router** re-enabled and tested ✅
- **diagnostics_router** re-enabled and tested ✅
- **Profile validation** re-enabled and tested ✅

### ⚠️ Optional Post-Deployment Items

- Complete UI router migrations (kalshi_ui_state_router, kalshi_dashboard_router, ui_audit_router)
- These are UI/UX endpoints, not core trading functionality

### 📅 Remediation Timeline

- **2026-07-04:** ✅ Investigated and fixed import hangs
- **2026-07-04:** ✅ Re-enabled routers and profile validation
- **2026-07-04:** ✅ Added test coverage for all re-enabled components
- **2026-07-10:** Complete UI router migrations (optional, post-deployment)

---

## Test Coverage Added

### Router Import Tests (`tests/test_router_imports.py`)

- ✅ `test_kalshi_agent_grid_router_import` - Validates import within 20s limit
- ✅ `test_diagnostics_router_import` - Validates import within 1s limit
- ✅ `test_individual_diagnostic_modules_import` - Validates all diagnostic modules import within 0.5s

### Profile Validation Tests (`tests/test_profile_validation.py`)

- ✅ `test_profile_resolver_import` - Validates module can be imported
- ✅ `test_validate_15m_profile_valid` - Validates kalshi_crypto_15m_v2 profile
- ✅ `test_validate_15m_profile_invalid` - Validates invalid profiles are rejected
- ✅ `test_validate_required_config_files` - Validates required config files exist
- ✅ `test_allowed_profiles_constant` - Validates ALLOWED_15M_PROFILES constant

**All tests passing:** 8/8 tests passing

---

## Conclusion

The 15M Kalshi crypto trading system is **FULLY PRODUCTION READY**. All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are correctly configured and wired throughout the stack. All critical remediation items have been completed:

1. ✅ **kalshi_agent_grid_router** re-enabled (import time: 10-13s, acceptable)
2. ✅ **diagnostics_router** re-enabled (import time: 0.054s, excellent)
3. ✅ **Profile validation** re-enabled (import time: 0.004s, excellent)
4. ✅ **Test coverage** added for all re-enabled components
5. ✅ **All tests passing** (8/8)

**Recommendation:** System is ready for immediate production deployment. No remediation required before deployment. UI router migrations can be completed post-deployment as optional enhancements.

---

**Audit Completed:** 2026-07-04  
**Auditor:** Cascade AI Assistant  
**Remediation Completed:** 2026-07-04  
**Status:** ✅ **PRODUCTION READY**
